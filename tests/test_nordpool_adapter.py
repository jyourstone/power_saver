"""Tests for the Nordpool adapter module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.power_saver.const import NORDPOOL_TYPE_HACS, NORDPOOL_TYPE_NATIVE
from custom_components.power_saver.nordpool_adapter import (
    _convert_native_response,
    find_all_nordpool_sensors,
)


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
