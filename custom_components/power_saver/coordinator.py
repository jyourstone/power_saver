"""DataUpdateCoordinator for the Power Saver integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON

from .const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_CONTROLLED_ENTITIES,
    CONF_EXCLUDE_FROM,
    CONF_EXCLUDE_UNTIL,
    CONF_ROLLING_WINDOW,
    CONF_MIN_CONSECUTIVE_HOURS,
    CONF_HOURS_PER_PERIOD,
    CONF_MIN_HOURS_ON,
    CONF_NORDPOOL_SENSOR,
    CONF_NORDPOOL_TYPE,
    CONF_PERIOD_FROM,
    CONF_PERIOD_TO,
    CONF_PRICE_SIMILARITY_PCT,
    CONF_SELECTION_MODE,
    CONF_STRATEGY,
    DEFAULT_ROLLING_WINDOW,
    DEFAULT_HOURS_PER_PERIOD,
    DEFAULT_MIN_HOURS_ON,
    DEFAULT_PERIOD_FROM,
    DEFAULT_PERIOD_TO,
    DEFAULT_SELECTION_MODE,
    DEFAULT_STRATEGY,
    DOMAIN,
    NORDPOOL_TYPE_HACS,
    STATE_ACTIVE,
    STATE_FORCED_OFF,
    STATE_FORCED_ON,
    STATE_STANDBY,
    STRATEGY_LOWEST_PRICE,
    STRATEGY_MINIMUM_RUNTIME,
    UPDATE_INTERVAL_MINUTES,
)
from . import scheduler
from .nordpool_adapter import async_get_prices

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2


@dataclass
class PowerSaverData:
    """Data returned by the Power Saver coordinator."""

    schedule: list[dict] = field(default_factory=list)
    current_state: str = STATE_STANDBY
    current_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    next_change: str | None = None
    active_slots: int = 0
    active_hours_in_period: float = 0.0
    strategy: str = STRATEGY_LOWEST_PRICE
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
        self._nordpool_type = entry.data.get(CONF_NORDPOOL_TYPE, NORDPOOL_TYPE_HACS)
        self._store = Store(hass, STORAGE_VERSION, f"power_saver.{entry.entry_id}")
        self._last_on_time: datetime | None = None
        self._state_loaded = False
        self._unsub_nordpool: callback | None = None
        self._previous_state: str | None = None
        self._force_on: bool = False
        self._force_off: bool = False
        self._locked_schedule: list[dict] | None = None
        self._schedule_has_tomorrow: bool = False
        self._options_fingerprint: str | None = None

    @property
    def last_on_time(self) -> datetime | None:
        """Return the last time the device was active."""
        return self._last_on_time

    @property
    def force_on_active(self) -> bool:
        """Return whether Always on is active."""
        return self._force_on

    @property
    def force_off_active(self) -> bool:
        """Return whether Always off is active."""
        return self._force_off

    async def async_set_force_on(self, active: bool) -> None:
        """Set or clear the Always on state."""
        self._force_on = active
        if active:
            self._force_off = False
            await self._control_entities(STATE_ACTIVE)
        else:
            self._previous_state = None  # Force re-evaluation on next update
        await self.async_request_refresh()

    async def async_set_force_off(self, active: bool) -> None:
        """Set or clear the Always off state."""
        self._force_off = active
        if active:
            self._force_on = False
            await self._control_entities(STATE_STANDBY)
        else:
            self._previous_state = None  # Force re-evaluation on next update
        await self.async_request_refresh()

    async def _async_setup(self) -> None:
        """Set up the coordinator (called once on first refresh)."""
        # Register Nord Pool state change listener for immediate recalculation
        self._unsub_nordpool = async_track_state_change_event(
            self.hass, [self._nordpool_entity], self._on_nordpool_update
        )

    @callback
    def _on_nordpool_update(self, event: Event) -> None:
        """Handle Nord Pool sensor state change."""
        _LOGGER.debug("Nord Pool sensor updated, requesting refresh")
        self.hass.async_create_task(self.async_request_refresh())

    # Options that affect schedule computation (excludes CONF_CONTROLLED_ENTITIES)
    _SCHEDULE_OPTIONS_KEYS = (
        CONF_STRATEGY,
        CONF_HOURS_PER_PERIOD,
        CONF_MIN_HOURS_ON,
        CONF_ALWAYS_CHEAP,
        CONF_ALWAYS_EXPENSIVE,
        CONF_PRICE_SIMILARITY_PCT,
        CONF_MIN_CONSECUTIVE_HOURS,
        CONF_SELECTION_MODE,
        CONF_EXCLUDE_FROM,
        CONF_EXCLUDE_UNTIL,
        CONF_PERIOD_FROM,
        CONF_PERIOD_TO,
        CONF_ROLLING_WINDOW,
    )

    def _compute_options_fingerprint(self) -> str:
        """Compute a deterministic fingerprint of schedule-affecting options."""
        options = self.config_entry.options
        relevant = {k: options.get(k) for k in self._SCHEDULE_OPTIONS_KEYS}
        raw = json.dumps(relevant, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    def _should_recompute_schedule(
        self, raw_tomorrow: list[dict], now: datetime
    ) -> bool:
        """Determine whether the locked schedule needs recomputing.

        Recompute triggers:
        1. No locked schedule (first run or restart without persisted data)
        2. Tomorrow prices newly appeared
        3. All slots in the locked schedule are in the past (day rollover)
        4. User options changed (fingerprint mismatch)
        """
        if not self._locked_schedule:
            _LOGGER.info("No locked schedule, will compute")
            return True

        current_fingerprint = self._compute_options_fingerprint()
        if current_fingerprint != self._options_fingerprint:
            _LOGGER.info("Options changed, recomputing schedule")
            return True

        if raw_tomorrow and not self._schedule_has_tomorrow:
            _LOGGER.info("Tomorrow prices now available, recomputing schedule")
            return True

        if raw_tomorrow:
            # Check if raw_tomorrow contains data beyond the schedule's last slot.
            # This happens after midnight when "tomorrow" (new day+1) prices arrive
            # but the locked schedule only covers today+yesterday's-tomorrow.
            try:
                last_slot_time = datetime.fromisoformat(
                    self._locked_schedule[-1]["time"]
                ).astimezone(now.tzinfo)
                last_tomorrow_time = max(
                    scheduler._to_datetime(s.get("start")).astimezone(now.tzinfo)
                    for s in raw_tomorrow
                )
                if last_tomorrow_time > last_slot_time:
                    _LOGGER.info(
                        "Tomorrow prices extend beyond locked schedule, recomputing"
                    )
                    return True
            except Exception:
                pass

        # Check if the schedule has expired (all slots in the past)
        try:
            last_slot_time = datetime.fromisoformat(
                self._locked_schedule[-1]["time"]
            ).astimezone(now.tzinfo)
        except (KeyError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "Malformed last slot in locked schedule, recomputing: %s", exc
            )
            return True

        if now > last_slot_time + timedelta(minutes=15):
            _LOGGER.info("Locked schedule expired (all slots in past), recomputing")
            return True

        return False

    async def _async_update_data(self) -> PowerSaverData:
        """Fetch data from Nord Pool sensor and compute schedule."""
        now = dt_util.now()

        # Read Nord Pool state
        nordpool_state = self.hass.states.get(self._nordpool_entity)
        if nordpool_state is None:
            raise UpdateFailed(
                f"Nord Pool sensor {self._nordpool_entity} not available"
            )

        raw_today, raw_tomorrow = await async_get_prices(
            self.hass, self._nordpool_entity, self._nordpool_type
        )

        # Read options
        options = self.config_entry.options
        strategy = options.get(CONF_STRATEGY, DEFAULT_STRATEGY)
        if strategy == STRATEGY_MINIMUM_RUNTIME:
            min_hours = options.get(CONF_MIN_HOURS_ON, DEFAULT_MIN_HOURS_ON)
        else:
            min_hours = options.get(CONF_HOURS_PER_PERIOD, DEFAULT_HOURS_PER_PERIOD)
        always_cheap = options.get(CONF_ALWAYS_CHEAP)
        always_expensive = options.get(CONF_ALWAYS_EXPENSIVE)
        price_similarity_pct = options.get(CONF_PRICE_SIMILARITY_PCT)
        min_consecutive_hours = options.get(CONF_MIN_CONSECUTIVE_HOURS)
        selection_mode = options.get(CONF_SELECTION_MODE, DEFAULT_SELECTION_MODE)
        exclude_from = options.get(CONF_EXCLUDE_FROM)
        exclude_until = options.get(CONF_EXCLUDE_UNTIL)
        # Strategy-specific options
        period_from = options.get(CONF_PERIOD_FROM, DEFAULT_PERIOD_FROM)
        period_to = options.get(CONF_PERIOD_TO, DEFAULT_PERIOD_TO)
        rolling_window = options.get(CONF_ROLLING_WINDOW, DEFAULT_ROLLING_WINDOW)
        max_hours_off = rolling_window - min_hours
        if max_hours_off < 0:
            _LOGGER.warning(
                "rolling_window (%s) < min_hours (%s); clamping max_hours_off to 0",
                rolling_window, min_hours,
            )
            max_hours_off = 0

        # Load persisted state on first run
        if not self._state_loaded:
            await self._async_load_state()
            self._state_loaded = True

        # Emergency mode: no price data at all
        if not raw_today and not raw_tomorrow:
            _LOGGER.error(
                "No price data available from Nord Pool sensor! Activating emergency mode"
            )

            # Force on/off overrides take precedence over emergency mode
            if self._force_on:
                current_state = STATE_FORCED_ON
            elif self._force_off:
                current_state = STATE_FORCED_OFF
            else:
                current_state = STATE_ACTIVE

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
                current_state=current_state,
                active_slots=96,
                active_hours_in_period=24.0,
                strategy=strategy,
                emergency_mode=True,
            )

        # No today data but have tomorrow — can't schedule
        if not raw_today:
            _LOGGER.warning("No price data for today from Nord Pool sensor")
            raise UpdateFailed("No price data available for today")

        # Compute or reuse locked schedule
        if self._should_recompute_schedule(raw_tomorrow, now):
            schedule = scheduler.build_schedule(
                raw_today=raw_today,
                raw_tomorrow=raw_tomorrow,
                min_hours=min_hours,
                now=now,
                strategy=strategy,
                # Lowest Price specific
                period_from=period_from,
                period_to=period_to,
                min_consecutive_hours=min_consecutive_hours,
                # Max Off Time specific
                max_hours_off=max_hours_off,
                last_on_time=self._last_on_time,
                # Shared
                always_cheap=always_cheap,
                always_expensive=always_expensive,
                price_similarity_pct=price_similarity_pct,
                selection_mode=selection_mode,
                exclude_from=exclude_from,
                exclude_until=exclude_until,
            )
            self._locked_schedule = schedule
            self._schedule_has_tomorrow = bool(raw_tomorrow)
            self._options_fingerprint = self._compute_options_fingerprint()
            await self._async_save_state()
            _LOGGER.info(
                "Schedule computed and locked (has_tomorrow=%s, slots=%d)",
                self._schedule_has_tomorrow, len(schedule),
            )
        else:
            schedule = self._locked_schedule

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

        # Calculate min/max price from today
        today_prices = [s.get("value") for s in raw_today if s.get("value") is not None]
        min_price = round(min(today_prices), 3) if today_prices else None
        max_price = round(max(today_prices), 3) if today_prices else None

        # Update last_on_time for Minimum Runtime strategy
        if strategy == STRATEGY_MINIMUM_RUNTIME and current_state == STATE_ACTIVE:
            self._last_on_time = now

        # Save last_on_time on active→non-active transitions
        if (
            strategy == STRATEGY_MINIMUM_RUNTIME
            and self._previous_state == STATE_ACTIVE
            and current_state != STATE_ACTIVE
        ):
            await self._async_save_state()

        # Compute active hours in period
        active_slots = sum(1 for s in schedule if s.get("status") == STATE_ACTIVE)
        if strategy == STRATEGY_MINIMUM_RUNTIME:
            active_hours_in_period = active_slots / 4.0
        else:
            active_hours_in_period = scheduler.active_hours_in_current_period(
                schedule, period_from, period_to, now
            )

        # Force on/off mode: bypass schedule
        if self._force_on:
            current_state = STATE_FORCED_ON
            self._previous_state = STATE_FORCED_ON
        elif self._force_off:
            current_state = STATE_FORCED_OFF
            self._previous_state = STATE_FORCED_OFF
        else:
            # Control entities on state change
            if current_state != self._previous_state:
                await self._control_entities(current_state)
                self._previous_state = current_state

        return PowerSaverData(
            schedule=schedule,
            current_state=current_state,
            current_price=round(current_price, 3) if current_price is not None else None,
            min_price=min_price,
            max_price=max_price,
            next_change=next_change,
            active_slots=active_slots,
            active_hours_in_period=active_hours_in_period,
            strategy=strategy,
            emergency_mode=False,
        )

    async def _control_entities(self, new_state: str) -> None:
        """Turn controlled entities on/off based on the new state."""
        entities = self.config_entry.options.get(CONF_CONTROLLED_ENTITIES, [])
        if not entities:
            return

        service = SERVICE_TURN_ON if new_state in (STATE_ACTIVE, STATE_FORCED_ON) else SERVICE_TURN_OFF
        _LOGGER.info(
            "State changed to %s, calling homeassistant.%s for %s",
            new_state, service, entities,
        )

        try:
            await self.hass.services.async_call(
                "homeassistant",
                service,
                {"entity_id": entities},
            )
        except Exception:
            _LOGGER.exception("Failed to control entities %s", entities)

    async def _async_load_state(self) -> None:
        """Load persisted state from storage."""
        try:
            data = await self._store.async_load()
            if not data:
                _LOGGER.debug("No previous state found in storage")
                return
            # The schedule is always recomputed on startup using current prices.
            # Only last_on_time is restored (needed by Minimum Runtime).
            last_on_iso = data.get("last_on_time")
            if last_on_iso:
                try:
                    self._last_on_time = datetime.fromisoformat(last_on_iso)
                    _LOGGER.info(
                        "Restored last_on_time: %s", last_on_iso,
                    )
                except (ValueError, TypeError):
                    self._last_on_time = None
        except Exception:
            _LOGGER.exception("Failed to load state from storage")

    async def _async_save_state(self) -> None:
        """Save state to persistent storage."""
        try:
            await self._store.async_save(
                {
                    "last_on_time": (
                        self._last_on_time.isoformat()
                        if self._last_on_time
                        else None
                    ),
                }
            )
        except Exception:
            _LOGGER.exception("Failed to save state to storage")

    async def async_shutdown(self) -> None:
        """Clean up listeners and persist state."""
        await self._async_save_state()
        if self._unsub_nordpool:
            self._unsub_nordpool()
            self._unsub_nordpool = None
        await super().async_shutdown()
