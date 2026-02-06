# Power Saver

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration that schedules appliances based on [Nordpool](https://github.com/custom-components/nordpool) electricity prices. It selects the cheapest hours to run your appliances, saving money while keeping them running when needed.

## Features

- **Price-based scheduling** — Automatically activates the cheapest hours of the day
- **Always-cheap threshold** — Slots below a price threshold are always activated
- **Always-expensive threshold** — Safety cutoff to never activate above a certain price
- **Rolling window constraint** — Ensures minimum activity within any configurable time window (e.g., water heater must run at least 6 hours in any 24-hour window)
- **Multiple instances** — Add one per appliance (water heater, floor heating, pool pump, etc.)
- **Emergency mode** — Keeps appliances running if price data is unavailable
- **No helpers needed** — All configuration is done through the integration's UI

## Requirements

- Home Assistant 2024.4.0 or newer
- [Nordpool integration](https://github.com/custom-components/nordpool) installed and configured

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots in the top right corner → **Custom repositories**
3. Add `https://github.com/jyourstone/power_saver` with category **Integration**
4. Click **Install**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/power_saver` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Power Saver**
3. Fill in the configuration:

| Field | Description |
|-------|-------------|
| **Name** | A descriptive name (e.g., "Water Heater", "Floor Heating") |
| **Nordpool price sensor** | Your Nordpool sensor entity |
| **Minimum active hours** | How many hours per day the appliance should run (cheapest hours selected) |
| **Always-cheap price** | Price below which slots are always active (0 = disabled) |
| **Always-expensive price** | Price at/above which slots are never active (0 = disabled) |
| **Rolling window hours** | Ensures minimum hours within a rolling window (0 = disabled, uses daily mode) |

4. Click **Submit**

To add another appliance, simply add the integration again with different settings.

### Changing settings

All scheduling parameters can be changed at any time via **Settings** → **Devices & Services** → **Power Saver** → **Configure**. Changes take effect immediately.

## Sensor

Each instance creates a sensor with:

### State

- `active` — The appliance should be running in the current time slot
- `standby` — The appliance should be off in the current time slot

### Attributes

| Attribute | Description |
|-----------|-------------|
| `schedule` | Full schedule with all time slots, prices, and statuses |
| `current_price` | Electricity price for the current time slot |
| `min_price` | Lowest price today |
| `next_change` | Timestamp of the next state transition |
| `active_slots` | Total number of active slots in the schedule |
| `active_hours_in_window` | Hours of activity within the rolling window |
| `hours_since_last_active` | Hours since the last active slot |
| `emergency_mode` | `true` if running without price data |

## Example automation

### Switch appliance based on Power Saver state

```yaml
automation:
  - alias: "Water Heater Power Saver"
    trigger:
      - platform: state
        entity_id: sensor.water_heater_schedule
    action:
      - choose:
          - conditions:
              - condition: state
                entity_id: sensor.water_heater_schedule
                state: "active"
            sequence:
              - service: switch.turn_on
                target:
                  entity_id: switch.water_heater
          - conditions:
              - condition: state
                entity_id: sensor.water_heater_schedule
                state: "standby"
            sequence:
              - service: switch.turn_off
                target:
                  entity_id: switch.water_heater
```

## How it works

1. **Price data** — Reads hourly prices from your Nordpool sensor (today + tomorrow when available)
2. **Slot selection** — Selects the cheapest 15-minute slots to meet your minimum active hours
3. **Thresholds** — Applies always-cheap (force on) and always-expensive (force off) price thresholds
4. **Rolling window** (optional) — Ensures minimum activity within any rolling time window, activating additional slots as needed to meet the constraint
5. **Updates** — Recalculates every 15 minutes and immediately when new prices arrive

## License

MIT License — see [LICENSE](LICENSE) for details.
