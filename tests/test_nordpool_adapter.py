"""Tests for the Nordpool adapter module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.power_saver.const import NORDPOOL_TYPE_HACS, NORDPOOL_TYPE_NATIVE
from custom_components.power_saver.nordpool_adapter import (
    _convert_native_response,
    _get_native_coordinator_prices,
    find_all_nordpool_sensors,
)


# Mock types that mirror pynordpool's DeliveryPeriodEntry / DeliveryPeriodData
@dataclass
class MockDeliveryPeriodEntry:
    """Mock for pynordpool DeliveryPeriodEntry."""

    start: datetime
    end: datetime
    entry: dict[str, float]  # area -> price in MWh


@dataclass
class MockDeliveryPeriodData:
    """Mock for pynordpool DeliveryPeriodData."""

    requested_date: str
    entries: list[MockDeliveryPeriodEntry] = field(default_factory=list)


@dataclass
class MockDeliveryPeriodsData:
    """Mock for pynordpool DeliveryPeriodsData."""

    entries: list[MockDeliveryPeriodData] = field(default_factory=list)


class TestConvertNativeResponse:
    """Tests for converting native Nordpool service response to standard format."""

    def test_dict_response_grouped_by_area(self):
        """Native response grouped by area should be converted correctly."""
        response = {
            "SE4": [
                {
                    "start": "2026-02-06T00:00:00+01:00",
                    "end": "2026-02-06T01:00:00+01:00",
                    "price": 500.0,  # 500 SEK/MWh = 0.5 SEK/kWh
                },
                {
                    "start": "2026-02-06T01:00:00+01:00",
                    "end": "2026-02-06T02:00:00+01:00",
                    "price": 300.0,  # 300 SEK/MWh = 0.3 SEK/kWh
                },
            ]
        }

        result = _convert_native_response(response)

        assert len(result) == 2
        assert result[0]["start"] == "2026-02-06T00:00:00+01:00"
        assert result[0]["end"] == "2026-02-06T01:00:00+01:00"
        assert result[0]["value"] == pytest.approx(0.5)
        assert result[1]["value"] == pytest.approx(0.3)

    def test_list_response(self):
        """Response as a flat list should also be handled."""
        response = [
            {
                "start": "2026-02-06T00:00:00+01:00",
                "end": "2026-02-06T01:00:00+01:00",
                "price": 150.0,
            },
        ]

        result = _convert_native_response(response)

        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(0.15)

    def test_mwh_to_kwh_conversion(self):
        """Prices should be divided by 1000 (MWh -> kWh)."""
        response = {
            "SE3": [
                {
                    "start": "2026-02-06T10:00:00+01:00",
                    "end": "2026-02-06T11:00:00+01:00",
                    "price": 1234.56,
                },
            ]
        }

        result = _convert_native_response(response)

        assert result[0]["value"] == pytest.approx(1.23456)

    def test_negative_prices(self):
        """Negative prices (common in Nordics) should convert correctly."""
        response = {
            "SE4": [
                {
                    "start": "2026-02-06T03:00:00+01:00",
                    "end": "2026-02-06T04:00:00+01:00",
                    "price": -50.0,
                },
            ]
        }

        result = _convert_native_response(response)

        assert result[0]["value"] == pytest.approx(-0.05)

    def test_missing_end_generates_one_hour_slot(self):
        """If 'end' is missing, it should be calculated as start + 1 hour."""
        response = {
            "SE4": [
                {
                    "start": "2026-02-06T05:00:00+01:00",
                    "price": 200.0,
                },
            ]
        }

        result = _convert_native_response(response)

        assert len(result) == 1
        assert result[0]["end"] == "2026-02-06T06:00:00+01:00"

    def test_empty_response(self):
        """Empty response should return empty list."""
        assert _convert_native_response({}) == []
        assert _convert_native_response([]) == []
        assert _convert_native_response(None) == []

    def test_picks_first_area(self):
        """When multiple areas exist, should pick the first one."""
        response = {
            "SE3": [
                {
                    "start": "2026-02-06T00:00:00+01:00",
                    "end": "2026-02-06T01:00:00+01:00",
                    "price": 100.0,
                },
            ],
            "SE4": [
                {
                    "start": "2026-02-06T00:00:00+01:00",
                    "end": "2026-02-06T01:00:00+01:00",
                    "price": 200.0,
                },
            ],
        }

        result = _convert_native_response(response)

        # Should get the first area's data
        assert len(result) == 1

    def test_entry_missing_start_is_skipped(self):
        """Entries without 'start' should be skipped."""
        response = {
            "SE4": [
                {"end": "2026-02-06T01:00:00+01:00", "price": 100.0},
                {
                    "start": "2026-02-06T01:00:00+01:00",
                    "end": "2026-02-06T02:00:00+01:00",
                    "price": 200.0,
                },
            ]
        }

        result = _convert_native_response(response)

        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(0.2)

    def test_entry_missing_price_is_skipped(self):
        """Entries without 'price' should be skipped."""
        response = {
            "SE4": [
                {
                    "start": "2026-02-06T00:00:00+01:00",
                    "end": "2026-02-06T01:00:00+01:00",
                },
                {
                    "start": "2026-02-06T01:00:00+01:00",
                    "end": "2026-02-06T02:00:00+01:00",
                    "price": 300.0,
                },
            ]
        }

        result = _convert_native_response(response)

        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(0.3)

    def test_full_day_conversion(self):
        """Converting a full day of 24 hourly prices should work."""
        prices = []
        for hour in range(24):
            start_dt = datetime(2026, 2, 6, hour, tzinfo=timezone(timedelta(hours=1)))
            end_dt = start_dt + timedelta(hours=1)
            prices.append({
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "price": 100.0 + hour * 10,  # 100-330 SEK/MWh
            })

        response = {"SE4": prices}
        result = _convert_native_response(response)

        assert len(result) == 24
        # First hour: 100 MWh = 0.1 kWh
        assert result[0]["value"] == pytest.approx(0.1)
        # Last hour: 330 MWh = 0.33 kWh
        assert result[23]["value"] == pytest.approx(0.33)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations."""
    yield


class TestFindAllNordpoolSensors:
    """Tests for finding all available Nordpool sensors."""

    async def test_no_sensors(self, hass: HomeAssistant):
        """Returns empty list when no Nordpool integration exists."""
        result = find_all_nordpool_sensors(hass)
        assert result == []

    async def test_single_hacs_sensor(self, hass: HomeAssistant):
        """Finds a single HACS Nordpool sensor with friendly name label."""
        entry = MockConfigEntry(
            domain="nordpool", entry_id="hacs_entry"
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            domain="sensor",
            platform="nordpool",
            unique_id="kwh_se4_sek",
            suggested_object_id="nordpool_kwh_se4_sek",
            config_entry=entry,
        )
        hass.states.async_set(
            "sensor.nordpool_kwh_se4_sek",
            "0.50",
            {
                "friendly_name": "Nordpool kWh SE4 SEK",
                "raw_today": [{"start": "2026-02-06T00:00:00+01:00", "value": 0.5}],
            },
        )

        result = find_all_nordpool_sensors(hass)

        assert len(result) == 1
        entity_id, nordpool_type, label = result[0]
        assert entity_id == "sensor.nordpool_kwh_se4_sek"
        assert nordpool_type == NORDPOOL_TYPE_HACS
        assert label == "Nordpool kWh SE4 SEK"

    async def test_single_native_sensor(self, hass: HomeAssistant):
        """Finds a single native Nordpool current_price sensor."""
        entry = MockConfigEntry(
            domain="nordpool", entry_id="native_entry"
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        entity_entry = registry.async_get_or_create(
            domain="sensor",
            platform="nordpool",
            unique_id="se4-current_price",
            suggested_object_id="nordpool_se4_sek",
            config_entry=entry,
        )
        hass.states.async_set(
            entity_entry.entity_id, "0.45",
            {"friendly_name": "Nord Pool SE4", "unit_of_measurement": "SEK/kWh"},
        )

        result = find_all_nordpool_sensors(hass)

        assert len(result) == 1
        entity_id, nordpool_type, label = result[0]
        assert entity_id == entity_entry.entity_id
        assert nordpool_type == NORDPOOL_TYPE_NATIVE
        assert label == "Nord Pool SE4"

    async def test_native_filters_non_current_price(self, hass: HomeAssistant):
        """Only current_price sensors are returned for native Nordpool."""
        entry = MockConfigEntry(
            domain="nordpool", entry_id="native_entry"
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)

        # current_price sensor (should be included)
        current = registry.async_get_or_create(
            domain="sensor",
            platform="nordpool",
            unique_id="se4-current_price",
            suggested_object_id="nordpool_se4_current",
            config_entry=entry,
        )
        hass.states.async_set(current.entity_id, "0.45")

        # Other sensors that should be filtered out
        for key in ["last_price", "next_price", "lowest_price", "highest_price",
                     "daily_average", "updated_at", "currency"]:
            other = registry.async_get_or_create(
                domain="sensor",
                platform="nordpool",
                unique_id=f"se4-{key}",
                suggested_object_id=f"nordpool_se4_{key}",
                config_entry=entry,
            )
            hass.states.async_set(other.entity_id, "0.00")

        result = find_all_nordpool_sensors(hass)

        assert len(result) == 1
        assert result[0][0] == current.entity_id

    async def test_multiple_native_current_price_sensors(self, hass: HomeAssistant):
        """Finds current_price sensors from different config entries."""
        registry = er.async_get(hass)

        entry_se4 = MockConfigEntry(
            domain="nordpool", entry_id="entry_se4"
        )
        entry_se4.add_to_hass(hass)
        entity_se4 = registry.async_get_or_create(
            domain="sensor",
            platform="nordpool",
            unique_id="se4-current_price",
            suggested_object_id="nordpool_se4",
            config_entry=entry_se4,
        )
        hass.states.async_set(entity_se4.entity_id, "0.45")

        entry_se3 = MockConfigEntry(
            domain="nordpool", entry_id="entry_se3"
        )
        entry_se3.add_to_hass(hass)
        entity_se3 = registry.async_get_or_create(
            domain="sensor",
            platform="nordpool",
            unique_id="se3-current_price",
            suggested_object_id="nordpool_se3",
            config_entry=entry_se3,
        )
        hass.states.async_set(entity_se3.entity_id, "0.50")

        result = find_all_nordpool_sensors(hass)

        assert len(result) == 2
        entity_ids = [r[0] for r in result]
        assert entity_se4.entity_id in entity_ids
        assert entity_se3.entity_id in entity_ids

    async def test_hacs_sensor_not_duplicated_as_native(self, hass: HomeAssistant):
        """HACS sensor should not appear twice (once as HACS, once as native)."""
        entry = MockConfigEntry(
            domain="nordpool", entry_id="hacs_entry"
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            domain="sensor",
            platform="nordpool",
            unique_id="kwh_se4_sek",
            suggested_object_id="nordpool_kwh_se4_sek",
            config_entry=entry,
        )
        hass.states.async_set(
            "sensor.nordpool_kwh_se4_sek",
            "0.50",
            {"raw_today": [{"start": "2026-02-06T00:00:00+01:00", "value": 0.5}]},
        )

        result = find_all_nordpool_sensors(hass)

        assert len(result) == 1
        assert result[0][1] == NORDPOOL_TYPE_HACS


CET = timezone(timedelta(hours=1))


def _make_mock_config_entry(
    areas: list[str],
    today_str: str,
    today_entries: list[MockDeliveryPeriodEntry],
    tomorrow_str: str | None = None,
    tomorrow_entries: list[MockDeliveryPeriodEntry] | None = None,
):
    """Create a mock config entry with native coordinator data."""
    periods = [MockDeliveryPeriodData(requested_date=today_str, entries=today_entries)]
    if tomorrow_str is not None:
        periods.append(
            MockDeliveryPeriodData(
                requested_date=tomorrow_str,
                entries=tomorrow_entries or [],
            )
        )

    coordinator = MagicMock()
    coordinator.data = MockDeliveryPeriodsData(entries=periods)

    entry = MagicMock()
    entry.data = {"areas": areas}
    entry.runtime_data = coordinator
    return entry


MOCK_NOW = datetime(2026, 3, 12, 14, 0, 0, tzinfo=CET)


@patch(
    "custom_components.power_saver.nordpool_adapter.dt_util.now",
    return_value=MOCK_NOW,
)
class TestGetNativeCoordinatorPrices:
    """Tests for reading prices directly from native Nord Pool coordinator."""

    def test_reads_today_and_tomorrow(self, _mock_now):
        """Should extract today and tomorrow prices from coordinator data."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                entry={"SE4": 500.0},
            ),
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 2, 0, tzinfo=CET),
                entry={"SE4": 300.0},
            ),
        ]
        tomorrow_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 13, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 13, 1, 0, tzinfo=CET),
                entry={"SE4": 200.0},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE4"],
            today_str="2026-03-12",
            today_entries=today_entries,
            tomorrow_str="2026-03-13",
            tomorrow_entries=tomorrow_entries,
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        today_prices, tomorrow_prices = result
        assert len(today_prices) == 2
        assert today_prices[0]["value"] == pytest.approx(0.5)
        assert today_prices[1]["value"] == pytest.approx(0.3)
        assert len(tomorrow_prices) == 1
        assert tomorrow_prices[0]["value"] == pytest.approx(0.2)

    def test_today_only_no_tomorrow(self, _mock_now):
        """Should return empty tomorrow list when no tomorrow data exists."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                entry={"SE4": 400.0},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE4"],
            today_str="2026-03-12",
            today_entries=today_entries,
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        today_prices, tomorrow_prices = result
        assert len(today_prices) == 1
        assert tomorrow_prices == []

    def test_mwh_to_kwh_conversion(self, _mock_now):
        """Prices should be converted from MWh to kWh."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 10, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 11, 0, tzinfo=CET),
                entry={"SE3": 1234.56},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE3"],
            today_str="2026-03-12",
            today_entries=today_entries,
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        assert result[0][0]["value"] == pytest.approx(1.23456)

    def test_uses_first_configured_area(self, _mock_now):
        """Should use the first area from config entry data."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                entry={"SE3": 100.0, "SE4": 200.0},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE4", "SE3"],
            today_str="2026-03-12",
            today_entries=today_entries,
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        # Should use SE4 (first in areas list) -> 200 MWh -> 0.2 kWh
        assert result[0][0]["value"] == pytest.approx(0.2)

    def test_returns_none_when_no_runtime_data(self, _mock_now):
        """Should return None when config entry has no runtime_data."""
        entry = MagicMock(spec=[])  # No attributes at all
        assert _get_native_coordinator_prices(entry) is None

    def test_returns_none_when_no_coordinator_data(self, _mock_now):
        """Should return None when coordinator has no data."""
        entry = MagicMock()
        entry.runtime_data = MagicMock()
        entry.runtime_data.data = None
        assert _get_native_coordinator_prices(entry) is None

    def test_returns_none_when_no_areas(self, _mock_now):
        """Should return None when config entry has no areas configured."""
        entry = MagicMock()
        entry.data = {"areas": []}
        entry.runtime_data = MagicMock()
        entry.runtime_data.data = MockDeliveryPeriodsData(entries=[])
        assert _get_native_coordinator_prices(entry) is None

    def test_returns_none_when_no_today_data(self, _mock_now):
        """Should return None when today's data is not found."""
        # Only has data for a different date
        config_entry = _make_mock_config_entry(
            areas=["SE4"],
            today_str="2026-01-01",
            today_entries=[
                MockDeliveryPeriodEntry(
                    start=datetime(2026, 1, 1, 0, 0, tzinfo=CET),
                    end=datetime(2026, 1, 1, 1, 0, tzinfo=CET),
                    entry={"SE4": 100.0},
                ),
            ],
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is None

    def test_skips_entries_missing_area(self, _mock_now):
        """Should skip entries that don't have the configured area."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                entry={"SE3": 100.0},  # No SE4
            ),
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 2, 0, tzinfo=CET),
                entry={"SE4": 200.0},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE4"],
            today_str="2026-03-12",
            today_entries=today_entries,
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        today_prices, _ = result
        assert len(today_prices) == 1
        assert today_prices[0]["value"] == pytest.approx(0.2)

    def test_start_and_end_are_isoformat_strings(self, _mock_now):
        """Output start/end should be ISO format strings."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                entry={"SE4": 100.0},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE4"],
            today_str="2026-03-12",
            today_entries=today_entries,
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        assert result[0][0]["start"] == "2026-03-12T00:00:00+01:00"
        assert result[0][0]["end"] == "2026-03-12T01:00:00+01:00"

    def test_handles_corrupt_coordinator_data_gracefully(self, _mock_now):
        """Should return None on unexpected data structures."""
        entry = MagicMock()
        entry.data = {"areas": ["SE4"]}
        coordinator = MagicMock()
        # data.entries is not iterable
        coordinator.data = MagicMock()
        coordinator.data.entries = 42
        entry.runtime_data = coordinator

        assert _get_native_coordinator_prices(entry) is None

    def test_tomorrow_empty_when_no_entries(self, _mock_now):
        """Tomorrow should be empty when delivery period exists but has no entries."""
        today_entries = [
            MockDeliveryPeriodEntry(
                start=datetime(2026, 3, 12, 0, 0, tzinfo=CET),
                end=datetime(2026, 3, 12, 1, 0, tzinfo=CET),
                entry={"SE4": 100.0},
            ),
        ]

        config_entry = _make_mock_config_entry(
            areas=["SE4"],
            today_str="2026-03-12",
            today_entries=today_entries,
            tomorrow_str="2026-03-13",
            tomorrow_entries=[],
        )

        result = _get_native_coordinator_prices(config_entry)

        assert result is not None
        today_prices, tomorrow_prices = result
        assert len(today_prices) == 1
        assert tomorrow_prices == []
