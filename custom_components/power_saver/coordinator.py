"""DataUpdateCoordinator for the Power Saver integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_MIN_HOURS,
    CONF_NORDPOOL_SENSOR,
    CONF_ROLLING_WINDOW_HOURS,
    DEFAULT_ALWAYS_CHEAP,
    DEFAULT_ALWAYS_EXPENSIVE,
    DEFAULT_MIN_HOURS,
    DEFAULT_ROLLING_WINDOW_HOURS,
    DOMAIN,
    STATE_ACTIVE,
    STATE_STANDBY,
    UPDATE_INTERVAL_MINUTES,
)
from . import scheduler

_LOGGER = logging.getLogger(__name__)


@dataclass
class PowerSaverData:
    """Data returned by the Power Saver coordinator."""

    schedule: list[dict] = field(default_factory=list)
    current_state: str = STATE_STANDBY
    current_price: float | None = None
    min_price: float | None = None
    next_change: str | None = None
    active_slots: int = 0
    last_active_time: str | None = None
    hours_since_last_active: float | None = None
    active_slots_in_window: int = 0
    active_hours_in_window: float = 0.0
    activity_history: list[str] = field(default_factory=list)
    emergency_mode: bool = False


class PowerSaverCoordinator(DataUpdateCoordinator[PowerSaverData]):
    """Coordinator that manages Power Saver schedule updates."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            config_entry=entry,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._nordpool_entity = entry.data[CONF_NORDPOOL_SENSOR]
        self._activity_history: list[str] = []
        self._history_recovered = False
        self._unsub_nordpool: callback | None = None

    async def _async_setup(self) -> None:
        """Set up the coordinator (called once on first refresh)."""
        # Register Nordpool state change listener for immediate recalculation
        self._unsub_nordpool = async_track_state_change_event(
            self.hass, [self._nordpool_entity], self._on_nordpool_update
        )

    @callback
    def _on_nordpool_update(self, event: Event) -> None:
        """Handle Nordpool sensor state change."""
        _LOGGER.debug("Nordpool sensor updated, requesting refresh")
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> PowerSaverData:
        """Fetch data from Nordpool sensor and compute schedule."""
        now = dt_util.now()

        # Read Nordpool state
        nordpool_state = self.hass.states.get(self._nordpool_entity)
        if nordpool_state is None:
            raise UpdateFailed(
                f"Nordpool sensor {self._nordpool_entity} not available"
            )

        raw_today = nordpool_state.attributes.get("raw_today") or []
        raw_tomorrow = nordpool_state.attributes.get("raw_tomorrow") or []

        # Read options
        options = self.config_entry.options
        min_hours = options.get(CONF_MIN_HOURS, DEFAULT_MIN_HOURS)
        always_cheap = options.get(CONF_ALWAYS_CHEAP, DEFAULT_ALWAYS_CHEAP)
        always_expensive = options.get(CONF_ALWAYS_EXPENSIVE, DEFAULT_ALWAYS_EXPENSIVE)
        rolling_window_hours = options.get(
            CONF_ROLLING_WINDOW_HOURS, DEFAULT_ROLLING_WINDOW_HOURS
        )
        rolling_window = rolling_window_hours if rolling_window_hours > 0 else None

        # Recover activity history from existing sensor state on first run
        if not self._history_recovered:
            self._recover_activity_history()
            self._history_recovered = True

        # Emergency mode: no price data at all
        if not raw_today and not raw_tomorrow:
            _LOGGER.error(
                "No price data available from Nordpool sensor! Activating emergency mode"
            )
            emergency_schedule = []
            for i in range(96):  # 24 hours * 4 slots per hour
                slot_time = now + timedelta(minutes=i * 15)
                slot_time = slot_time.replace(
                    minute=(slot_time.minute // 15) * 15, second=0, microsecond=0
                )
                emergency_schedule.append({
                    "price": 0.0,
                    "time": slot_time.isoformat(),
                    "status": STATE_ACTIVE,
                })

            return PowerSaverData(
                schedule=emergency_schedule,
                current_state=STATE_ACTIVE,
                active_slots=96,
                last_active_time=now.isoformat(),
                hours_since_last_active=0.0,
                active_slots_in_window=96,
                active_hours_in_window=24.0,
                activity_history=[],
                emergency_mode=True,
            )

        # No today data but have tomorrow — can't schedule
        if not raw_today:
            _LOGGER.warning("No price data for today from Nordpool sensor")
            raise UpdateFailed("No price data available for today")

        # Build schedule
        schedule = scheduler.build_schedule(
            raw_today=raw_today,
            raw_tomorrow=raw_tomorrow,
            min_hours=min_hours,
            always_cheap=always_cheap,
            always_expensive=always_expensive,
            rolling_window_hours=rolling_window,
            now=now,
            prev_activity_history=self._activity_history,
        )

        # Find current slot
        current_slot = scheduler.find_current_slot(schedule, now)
        if current_slot:
            current_state = current_slot.get("status", STATE_STANDBY)
            current_price = current_slot.get("price")
        else:
            current_state = STATE_STANDBY
            current_price = None

        # Find next state change
        next_change = scheduler.find_next_change(schedule, current_slot, now)

        # Calculate min price from today
        today_prices = [s.get("value") for s in raw_today if s.get("value") is not None]
        min_price = round(min(today_prices), 3) if today_prices else None

        # Update activity history
        window_hours = rolling_window_hours if rolling_window_hours > 0 else 24.0
        self._activity_history = scheduler.build_activity_history(
            schedule, self._activity_history, now, window_hours
        )

        # Compute metrics
        active_slots_in_window = len(self._activity_history)
        active_hours_in_window = round(active_slots_in_window / 4.0, 1)

        last_active_time: str | None = None
        hours_since_last_active: float | None = None
        if self._activity_history:
            last_active_time = self._activity_history[-1]
            last_active_dt = datetime.fromisoformat(last_active_time).astimezone(
                now.tzinfo
            )
            hours_since_last_active = round(
                (now - last_active_dt).total_seconds() / 3600, 1
            )

        active_slots = sum(1 for s in schedule if s.get("status") == STATE_ACTIVE)

        return PowerSaverData(
            schedule=schedule,
            current_state=current_state,
            current_price=round(current_price, 3) if current_price is not None else None,
            min_price=min_price,
            next_change=next_change,
            active_slots=active_slots,
            last_active_time=last_active_time,
            hours_since_last_active=hours_since_last_active,
            active_slots_in_window=active_slots_in_window,
            active_hours_in_window=active_hours_in_window,
            activity_history=self._activity_history,
            emergency_mode=False,
        )

    def _recover_activity_history(self) -> None:
        """Try to recover activity history from the existing sensor state.

        This provides soft persistence across HA restarts without file storage.
        """
        # Build the expected entity_id from the config entry
        # The sensor entity may already exist from a previous run
        for state in self.hass.states.async_all("sensor"):
            if state.attributes.get("recent_activity_history") is not None:
                # Check if this sensor belongs to our config entry
                entity_entry = self.hass.helpers.entity_registry.async_get(
                    state.entity_id
                )
                if (
                    entity_entry
                    and entity_entry.config_entry_id == self.config_entry.entry_id
                ):
                    history = state.attributes.get("recent_activity_history", [])
                    if isinstance(history, list) and history:
                        self._activity_history = list(history)
                        _LOGGER.info(
                            "Recovered %d activity history entries from %s",
                            len(history),
                            state.entity_id,
                        )
                    return

        _LOGGER.debug("No previous activity history found to recover")

    async def async_shutdown(self) -> None:
        """Clean up listeners."""
        if self._unsub_nordpool:
            self._unsub_nordpool()
            self._unsub_nordpool = None
        await super().async_shutdown()
