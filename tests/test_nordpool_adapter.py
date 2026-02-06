"""Tests for the Nordpool adapter module."""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest

from custom_components.power_saver.nordpool_adapter import _convert_native_response

TZ = timezone(timedelta(hours=1), name="CET")


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
            prices.append({
                "start": f"2026-02-06T{hour:02d}:00:00+01:00",
                "end": f"2026-02-06T{hour + 1 if hour < 23 else 0:02d}:00:00+01:00",
                "price": 100.0 + hour * 10,  # 100-330 SEK/MWh
            })

        response = {"SE4": prices}
        result = _convert_native_response(response)

        assert len(result) == 24
        # First hour: 100 MWh = 0.1 kWh
        assert result[0]["value"] == pytest.approx(0.1)
        # Last hour: 330 MWh = 0.33 kWh
        assert result[23]["value"] == pytest.approx(0.33)
