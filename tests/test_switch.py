"""Tests for the Power Saver override switch entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tests.helpers import make_config_entry

from custom_components.power_saver.switch import OverrideSwitch


def test_override_switch_unique_id():
    """Test override switch has correct unique ID."""
    coordinator = MagicMock()
    coordinator.override_active = False
    switch = OverrideSwitch(coordinator, make_config_entry("abc"))
    assert switch.unique_id == "abc_override"


def test_override_switch_translation_key():
    """Test override switch uses correct translation key."""
    coordinator = MagicMock()
    coordinator.override_active = False
    switch = OverrideSwitch(coordinator, make_config_entry())
    assert switch.translation_key == "override"


def test_override_switch_has_entity_name():
    """Test override switch uses entity naming."""
    coordinator = MagicMock()
    coordinator.override_active = False
    switch = OverrideSwitch(coordinator, make_config_entry())
    assert switch.has_entity_name is True


def test_override_switch_is_on_true():
    """Test is_on returns True when override is active."""
    coordinator = MagicMock()
    coordinator.override_active = True
    switch = OverrideSwitch(coordinator, make_config_entry())
    assert switch.is_on is True


def test_override_switch_is_on_false():
    """Test is_on returns False when override is inactive."""
    coordinator = MagicMock()
    coordinator.override_active = False
    switch = OverrideSwitch(coordinator, make_config_entry())
    assert switch.is_on is False


def test_override_switch_not_diagnostic():
    """Test override switch is not in diagnostic category."""
    coordinator = MagicMock()
    coordinator.override_active = False
    switch = OverrideSwitch(coordinator, make_config_entry())
    assert switch.entity_category is None


def test_override_switch_icon():
    """Test override switch has the hand icon."""
    coordinator = MagicMock()
    coordinator.override_active = False
    switch = OverrideSwitch(coordinator, make_config_entry())
    assert switch.icon == "mdi:hand-back-right"


async def test_override_switch_turn_on():
    """Test turning on calls coordinator.async_set_override(True)."""
    coordinator = MagicMock()
    coordinator.override_active = False
    coordinator.async_set_override = AsyncMock()
    switch = OverrideSwitch(coordinator, make_config_entry())
    await switch.async_turn_on()
    coordinator.async_set_override.assert_awaited_once_with(True)


async def test_override_switch_turn_off():
    """Test turning off calls coordinator.async_set_override(False)."""
    coordinator = MagicMock()
    coordinator.override_active = True
    coordinator.async_set_override = AsyncMock()
    switch = OverrideSwitch(coordinator, make_config_entry())
    await switch.async_turn_off()
    coordinator.async_set_override.assert_awaited_once_with(False)


async def test_override_switch_restore_on():
    """Test that override state is restored to ON on startup."""
    coordinator = MagicMock()
    coordinator.override_active = False
    coordinator.async_set_override = AsyncMock()
    switch = OverrideSwitch(coordinator, make_config_entry())

    last_state = MagicMock()
    last_state.state = "on"

    with patch.object(switch, "async_get_last_state", return_value=last_state):
        await switch.async_added_to_hass()

    coordinator.async_set_override.assert_awaited_once_with(True)


async def test_override_switch_restore_off():
    """Test that override state OFF does not call async_set_override."""
    coordinator = MagicMock()
    coordinator.override_active = False
    coordinator.async_set_override = AsyncMock()
    switch = OverrideSwitch(coordinator, make_config_entry())

    last_state = MagicMock()
    last_state.state = "off"

    with patch.object(switch, "async_get_last_state", return_value=last_state):
        await switch.async_added_to_hass()

    coordinator.async_set_override.assert_not_awaited()


async def test_override_switch_restore_no_previous_state():
    """Test that no previous state does not call async_set_override."""
    coordinator = MagicMock()
    coordinator.override_active = False
    coordinator.async_set_override = AsyncMock()
    switch = OverrideSwitch(coordinator, make_config_entry())

    with patch.object(switch, "async_get_last_state", return_value=None):
        await switch.async_added_to_hass()

    coordinator.async_set_override.assert_not_awaited()
