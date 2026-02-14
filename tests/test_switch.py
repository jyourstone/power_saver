"""Tests for the Power Saver force on/off switch entities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tests.helpers import make_config_entry

from custom_components.power_saver.switch import ForceOnSwitch, ForceOffSwitch


# --- ForceOnSwitch tests ---


def test_force_on_switch_unique_id():
    """Test force on switch has correct unique ID."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    switch = ForceOnSwitch(coordinator, make_config_entry("abc"))
    assert switch.unique_id == "abc_force_on"


def test_force_on_switch_translation_key():
    """Test force on switch uses correct translation key."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    switch = ForceOnSwitch(coordinator, make_config_entry())
    assert switch.translation_key == "force_on"


def test_force_on_switch_has_entity_name():
    """Test force on switch uses entity naming."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    switch = ForceOnSwitch(coordinator, make_config_entry())
    assert switch.has_entity_name is True


def test_force_on_switch_is_on_true():
    """Test is_on returns True when force on is active."""
    coordinator = MagicMock()
    coordinator.force_on_active = True
    switch = ForceOnSwitch(coordinator, make_config_entry())
    assert switch.is_on is True


def test_force_on_switch_is_on_false():
    """Test is_on returns False when force on is inactive."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    switch = ForceOnSwitch(coordinator, make_config_entry())
    assert switch.is_on is False


def test_force_on_switch_not_diagnostic():
    """Test force on switch is not in diagnostic category."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    switch = ForceOnSwitch(coordinator, make_config_entry())
    assert switch.entity_category is None


def test_force_on_switch_icon():
    """Test force on switch has the hand icon."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    switch = ForceOnSwitch(coordinator, make_config_entry())
    assert switch.icon == "mdi:hand-back-right"


async def test_force_on_switch_turn_on():
    """Test turning on calls coordinator.async_set_force_on(True)."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    coordinator.async_set_force_on = AsyncMock()
    switch = ForceOnSwitch(coordinator, make_config_entry())
    await switch.async_turn_on()
    coordinator.async_set_force_on.assert_awaited_once_with(True)


async def test_force_on_switch_turn_off():
    """Test turning off calls coordinator.async_set_force_on(False)."""
    coordinator = MagicMock()
    coordinator.force_on_active = True
    coordinator.async_set_force_on = AsyncMock()
    switch = ForceOnSwitch(coordinator, make_config_entry())
    await switch.async_turn_off()
    coordinator.async_set_force_on.assert_awaited_once_with(False)


async def test_force_on_switch_restore_on():
    """Test that force on state is restored to ON on startup."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    coordinator.async_set_force_on = AsyncMock()
    switch = ForceOnSwitch(coordinator, make_config_entry())

    last_state = MagicMock()
    last_state.state = "on"

    with patch.object(switch, "async_get_last_state", return_value=last_state):
        await switch.async_added_to_hass()

    coordinator.async_set_force_on.assert_awaited_once_with(True)


async def test_force_on_switch_restore_off():
    """Test that force on state OFF does not call async_set_force_on."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    coordinator.async_set_force_on = AsyncMock()
    switch = ForceOnSwitch(coordinator, make_config_entry())

    last_state = MagicMock()
    last_state.state = "off"

    with patch.object(switch, "async_get_last_state", return_value=last_state):
        await switch.async_added_to_hass()

    coordinator.async_set_force_on.assert_not_awaited()


async def test_force_on_switch_restore_no_previous_state():
    """Test that no previous state does not call async_set_force_on."""
    coordinator = MagicMock()
    coordinator.force_on_active = False
    coordinator.async_set_force_on = AsyncMock()
    switch = ForceOnSwitch(coordinator, make_config_entry())

    with patch.object(switch, "async_get_last_state", return_value=None):
        await switch.async_added_to_hass()

    coordinator.async_set_force_on.assert_not_awaited()


# --- ForceOffSwitch tests ---


def test_force_off_switch_unique_id():
    """Test force off switch has correct unique ID."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    switch = ForceOffSwitch(coordinator, make_config_entry("abc"))
    assert switch.unique_id == "abc_force_off"


def test_force_off_switch_translation_key():
    """Test force off switch uses correct translation key."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    switch = ForceOffSwitch(coordinator, make_config_entry())
    assert switch.translation_key == "force_off"


def test_force_off_switch_has_entity_name():
    """Test force off switch uses entity naming."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    switch = ForceOffSwitch(coordinator, make_config_entry())
    assert switch.has_entity_name is True


def test_force_off_switch_is_on_true():
    """Test is_on returns True when force off is active."""
    coordinator = MagicMock()
    coordinator.force_off_active = True
    switch = ForceOffSwitch(coordinator, make_config_entry())
    assert switch.is_on is True


def test_force_off_switch_is_on_false():
    """Test is_on returns False when force off is inactive."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    switch = ForceOffSwitch(coordinator, make_config_entry())
    assert switch.is_on is False


def test_force_off_switch_not_diagnostic():
    """Test force off switch is not in diagnostic category."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    switch = ForceOffSwitch(coordinator, make_config_entry())
    assert switch.entity_category is None


def test_force_off_switch_icon():
    """Test force off switch has the hand-off icon."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    switch = ForceOffSwitch(coordinator, make_config_entry())
    assert switch.icon == "mdi:hand-back-right-off"


async def test_force_off_switch_turn_on():
    """Test turning on calls coordinator.async_set_force_off(True)."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    coordinator.async_set_force_off = AsyncMock()
    switch = ForceOffSwitch(coordinator, make_config_entry())
    await switch.async_turn_on()
    coordinator.async_set_force_off.assert_awaited_once_with(True)


async def test_force_off_switch_turn_off():
    """Test turning off calls coordinator.async_set_force_off(False)."""
    coordinator = MagicMock()
    coordinator.force_off_active = True
    coordinator.async_set_force_off = AsyncMock()
    switch = ForceOffSwitch(coordinator, make_config_entry())
    await switch.async_turn_off()
    coordinator.async_set_force_off.assert_awaited_once_with(False)


async def test_force_off_switch_restore_on():
    """Test that force off state is restored to ON on startup."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    coordinator.async_set_force_off = AsyncMock()
    switch = ForceOffSwitch(coordinator, make_config_entry())

    last_state = MagicMock()
    last_state.state = "on"

    with patch.object(switch, "async_get_last_state", return_value=last_state):
        await switch.async_added_to_hass()

    coordinator.async_set_force_off.assert_awaited_once_with(True)


async def test_force_off_switch_restore_off():
    """Test that force off state OFF does not call async_set_force_off."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    coordinator.async_set_force_off = AsyncMock()
    switch = ForceOffSwitch(coordinator, make_config_entry())

    last_state = MagicMock()
    last_state.state = "off"

    with patch.object(switch, "async_get_last_state", return_value=last_state):
        await switch.async_added_to_hass()

    coordinator.async_set_force_off.assert_not_awaited()


async def test_force_off_switch_restore_no_previous_state():
    """Test that no previous state does not call async_set_force_off."""
    coordinator = MagicMock()
    coordinator.force_off_active = False
    coordinator.async_set_force_off = AsyncMock()
    switch = ForceOffSwitch(coordinator, make_config_entry())

    with patch.object(switch, "async_get_last_state", return_value=None):
        await switch.async_added_to_hass()

    coordinator.async_set_force_off.assert_not_awaited()
