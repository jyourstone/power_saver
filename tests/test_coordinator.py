"""Tests for the Power Saver coordinator."""

from __future__ import annotations

# Coordinator tests require a full Home Assistant test harness.
# These are placeholder stubs documenting the test cases to implement.
# To run these, you'll need pytest-homeassistant-custom-component installed.
#
# Test cases to implement:
#
# 1. test_coordinator_fetches_nordpool_data
#    - Mock Nordpool sensor with raw_today/raw_tomorrow
#    - Verify schedule is built and data is populated
#
# 2. test_coordinator_emergency_mode
#    - Mock Nordpool sensor with no raw_today
#    - Verify emergency mode is activated with all slots active
#
# 3. test_coordinator_handles_missing_sensor
#    - Remove Nordpool sensor from state machine
#    - Verify UpdateFailed is raised
#
# 4. test_coordinator_recovers_activity_history
#    - Pre-populate sensor state with recent_activity_history
#    - Verify coordinator seeds its history from existing state
#
# 5. test_coordinator_nordpool_listener
#    - Fire a state_changed event for the Nordpool sensor
#    - Verify coordinator triggers a refresh
