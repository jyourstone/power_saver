<p align="center">
  <img src="https://brands.home-assistant.io/_/power_saver/icon@2x.png" alt="Power Saver logo" width="128" height="128">
</p>

<h1 align="center">Power Saver</h1>

<p align="center">
  A Home Assistant custom integration that finds the cheapest (or most expensive) upcoming hours based on<br>
  <a href="https://www.home-assistant.io/integrations/nordpool/">Nordpool</a> electricity prices to save money automatically.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS"></a>
  <a href="https://github.com/jyourstone/power_saver/releases"><img src="https://img.shields.io/github/v/release/jyourstone/power_saver" alt="Release"></a>
  <a href="https://github.com/jyourstone/power_saver/blob/main/LICENSE"><img src="https://img.shields.io/github/license/jyourstone/power_saver" alt="License"></a>
</p>

---

## Features

- **Price-based scheduling** — Automatically activates the cheapest/most expensive hours of the day
- **Always-cheap threshold** — Slots below/above a price threshold are always activated
- **Always-expensive threshold** — Safety cutoff to never activate above/below a certain price
- **Price similarity threshold** — Groups slots with nearly identical prices for more natural scheduling
- **Rolling window constraint** — Ensures minimum activity within any configurable time window (e.g., water heater must run at least 4 hours in any 24-hour window)
- **Minimum consecutive hours** — Prevents short on/off cycles by requiring a minimum run duration
- **Multiple instances** — Add one per appliance (water heater, floor heating, pool pump, etc.)
- **Emergency mode** — Keeps appliances running if price data is unavailable
- **No helpers needed** — All configuration is done through the integration's UI

## Requirements

- Home Assistant 2024.4.0 or newer
- Nordpool integration, either the [native addon](https://www.home-assistant.io/integrations/nordpool/) or the [HACS custom addon](https://github.com/custom-components/nordpool) installed and configured

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jyourstone&repository=power_saver&category=integration)

1. Click the button above (or manually add `https://github.com/jyourstone/power_saver` as a custom repository in HACS, category: **Integration**)
2. Click **Install**
3. Restart Home Assistant

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
| **Mode** | `Cheapest` selects the cheapest hours; `Most expensive` selects the most expensive (inverts the schedule) |
| **Rolling window hours** | Ensures minimum hours within a rolling window (empty = disabled, uses daily mode) |
| **Minimum active hours** | How many hours per day the appliance should run |
| **Always-cheap price** | Price below which slots are always active (empty = disabled) |
| **Always-expensive price** | Price at/above which slots are never active (empty = disabled) |
| **Price similarity threshold** | Prices within this range are treated as equal (empty = disabled) |
| **Minimum consecutive active hours** | Minimum number of hours to keep active in a row (empty = disabled) |
| **Controlled entities** | One or more `switch`, `input_boolean`, or `light` entities to turn on/off automatically (empty = disabled) |

4. Click **Submit**

To add another appliance, simply add the integration again with different settings.

### Changing settings

All scheduling parameters can be changed at any time via **Settings** → **Devices & Services** → **Power Saver** → **Configure**. Changes take effect immediately.

## Sensors

Each instance creates the following sensors:

### Status sensor

| State | Description |
|-------|-------------|
| `active` | The appliance should be running in the current time slot |
| `standby` | The appliance should be off in the current time slot |

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

### Diagnostic sensors

| Sensor | Description |
|--------|-------------|
| **Schedule** | Full schedule as a diagnostic entity |
| **Last Active** | Timestamp of the last active slot |
| **Active Hours in Window** | Hours of activity within the rolling window |

## How it works

1. **Price data** — Reads hourly prices from your Nordpool sensor (today + tomorrow when available)
2. **Slot selection** — Selects the cheapest (or most expensive) 15-minute slots to meet your minimum active hours
3. **Thresholds** — Applies always-cheap (force on) and always-expensive (force off) price thresholds
4. **Similarity grouping** — Groups slots with nearly identical prices for more consistent scheduling
5. **Rolling window** (optional) — Ensures minimum activity within any rolling time window, activating additional slots as needed
6. **Consecutive hours** (optional) — Merges short active segments to prevent rapid on/off cycling
7. **Updates** — Recalculates every 15 minutes and immediately when new prices arrive

## License

MIT License — see [LICENSE](LICENSE) for details.
