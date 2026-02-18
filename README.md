<p align="center">
  <img src="https://brands.home-assistant.io/_/power_saver/icon@2x.png" alt="Power Saver logo" width="128" height="128">
</p>

<h1 align="center">Power Saver</h1>

<p align="center">
  A Home Assistant custom integration that finds the cheapest (or most expensive) upcoming hours based on<br>
  <a href="https://www.home-assistant.io/integrations/nordpool/">Nordpool</a> electricity prices to save money automatically.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Default-41BDF5.svg" alt="HACS"></a>
  <a href="https://github.com/jyourstone/power_saver/releases"><img src="https://img.shields.io/github/v/release/jyourstone/power_saver" alt="Release"></a>
  <a href="https://github.com/jyourstone/power_saver/blob/main/LICENSE"><img src="https://img.shields.io/github/license/jyourstone/power_saver" alt="License"></a>
  <a href="https://buymeacoffee.com/jyourstone"><img src="https://img.shields.io/badge/Buy_Me_A_Coffee-FFDD00?logo=buy-me-a-coffee&logoColor=black" alt="Buy Me A Coffee"></a>
</p>

---

## Features

- **Price-based scheduling** — Automatically activates the cheapest/most expensive hours of the day
- **Always-cheap threshold** — Slots below/above a price threshold are always activated
- **Always-expensive threshold** — Safety cutoff to never activate above/below a certain price
- **Price similarity threshold** — Groups slots with nearly identical prices for more natural scheduling
- **Rolling window constraint** — Ensures minimum activity within any configurable time window (e.g., water heater must run at least 4 hours in any 24-hour window)
- **Minimum consecutive hours** — Prevents short on/off cycles by requiring a minimum run duration
- **Excluded hours** — Block a time range from ever being activated (e.g., to avoid grid fee peak hours)
- **Multiple instances** — Add one per appliance (water heater, floor heating, pool pump, etc.)
- **Always on / Always off** — Force all controlled entities ON or OFF via switches, bypassing the schedule
- **Emergency mode** — Keeps appliances running if price data is unavailable
- **No helpers needed** — All configuration is done through the integration's UI

## Requirements

- Home Assistant 2024.4.0 or newer
- Nord Pool integration, either the [native addon](https://www.home-assistant.io/integrations/nordpool/) or the [HACS custom addon](https://github.com/custom-components/nordpool), installed and configured

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jyourstone&repository=power_saver&category=integration)

1. Click the button above, or search for **Power Saver** in HACS
2. Click **Install**
3. Restart Home Assistant

### Manual

1. Copy the `custom_components/power_saver` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

[![Add integration to your Home Assistant instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=power_saver)

Click the button above, or add it manually:

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Power Saver**
3. Fill in the configuration:

| Field | Description |
|-------|-------------|
| **Nord Pool sensor** | The Nord Pool sensor to use for electricity prices |
| **Name** | A descriptive name (e.g., "Water Heater", "Floor Heating") |
| **Mode** | `Cheapest` selects the cheapest hours; `Most expensive` selects the most expensive (inverts the schedule) |
| **Rolling window hours** | Ensures minimum hours within a rolling window (default = 24) |
| **Minimum active hours** | How many hours per day the appliance should run |
| **Always-cheap price** | Price below which slots are always active (empty = disabled) |
| **Always-expensive price** | Price at/above which slots are never active (empty = disabled) |
| **Price similarity threshold** | Prices within this range are treated as equal (empty = disabled) |
| **Minimum consecutive active hours** | Minimum number of hours to keep active in a row (empty = disabled) |
| **Exclude from / Exclude until** | Time range during which slots are never activated and ignored by the scheduler. Useful for avoiding hours with extra grid fees. Supports cross-midnight ranges (e.g., 22:00 to 06:00). Both fields must be set to enable (empty = disabled) |
| **Controlled entities** | One or more `switch`, `input_boolean`, or `light` entities to turn on/off automatically (empty = disabled) |

4. Click **Submit**

To add another appliance, simply add a new service with different settings.

### Changing settings

All scheduling parameters can be changed at any time via **Settings** → **Devices & Services** → **Power Saver** → **Configure**. Changes take effect immediately.

## Sensors

Each instance creates the following sensors:

### Status sensor

| State | Description |
|-------|-------------|
| `active` | The appliance should be running in the current time slot |
| `standby` | The appliance should be off in the current time slot |
| `excluded` | The slot is in the excluded time range and will never activate |
| `forced_on` | Always on is active — all controlled entities are forced ON |
| `forced_off` | Always off is active — all controlled entities are forced OFF |

### Attributes

| Attribute | Description |
|-----------|-------------|
| `current_price` | Electricity price for the current time slot |
| `min_price` | Lowest price today |
| `max_price` | Highest price today |
| `active_slots` | Total number of active slots in the schedule |

### Override switches

Each instance includes two override switches:

- **Always on** — Forces all controlled entities ON regardless of the schedule. The status sensor shows `forced_on`.
- **Always off** — Forces all controlled entities OFF regardless of the schedule. The status sensor shows `forced_off`.

The two switches are mutually exclusive — enabling one automatically disables the other. Turn both OFF to resume normal scheduling. Switch states persist across Home Assistant restarts.

### Diagnostic sensors

| Sensor | Type | Description |
|--------|------|-------------|
| **Schedule** | Sensor | Full schedule with all time slots, prices, and statuses |
| **Last Active** | Sensor | Timestamp of the last active slot |
| **Active Hours in Window** | Sensor | Scheduled active hours in the upcoming rolling window |
| **Next Change** | Sensor | Timestamp of the next state transition (displayed as relative time) |
| **Emergency Mode** | Binary sensor | Indicates if running without price data (problem badge) |

## How it works

1. **Price data** — Reads prices from your Nord Pool sensor (today + tomorrow when available)
2. **Excluded hours** (optional) — Marks slots in the excluded time range as permanently off, removing them from scheduling
3. **Slot selection** — Selects the cheapest (or most expensive) slots from the remaining hours to meet your minimum active hours
4. **Thresholds** — Applies always-cheap (force on) and always-expensive (force off) price thresholds
5. **Similarity grouping** — Groups slots with nearly identical prices for more consistent scheduling
6. **Rolling window** (optional) — Ensures minimum activity within any rolling time window, activating additional slots as needed
7. **Consecutive hours** (optional) — Merges short active segments to prevent rapid on/off cycling
8. **Updates** — Recalculates every 15 minutes and immediately when new prices arrive

## Dashboard example

You can visualize the electricity price alongside the Power Saver schedule using the [ApexCharts Card](https://github.com/RomRider/apexcharts-card) for Home Assistant. This gives you a clear overview of when the appliance is active and how it correlates with the price.

<p>
  <img src="images/apexcharts_example.png" alt="ApexCharts price and schedule graph">
</p>

Replace `sensor.heater_power_saver_schedule` with your own schedule sensor entity ID.

<details>
<summary>ApexCharts card YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Price 48t + Powersaver
now:
  show: true
  label: Now
graph_span: 2d
span:
  start: day
apex_config:
  stroke:
    width: 2
  dataLabels:
    enabled: true
  fill:
    type: gradient
    gradient:
      shadeIntensity: 1
      inverseColors: false
      opacityFrom: 0.45
      opacityTo: 0.05
      stops:
        - 10
        - 50
        - 75
        - 1000
  legend:
    show: false
  yaxis:
    - id: price
      show: true
      decimalsInFloat: 1
      floating: false
      forceNiceScale: true
      extend_to: end
    - id: usage
      show: true
      opposite: true
      decimalsInFloat: 0
      floating: false
      forceNiceScale: true
      extend_to: end
    - id: powersaver
      show: false
      decimalsInFloat: 0
      floating: false
      extend_to: now
series:
  - entity: sensor.heater_power_saver_schedule
    yaxis_id: price
    extend_to: now
    name: Price
    type: area
    curve: stepline
    color: tomato
    show:
      legend_value: false
    data_generator: |
      return entity.attributes.schedule.map((entry) => {
        return [new Date(entry.time).getTime(), entry.price];
      });
  - entity: sensor.heater_power_saver_schedule
    data_generator: |
      return entity.attributes.schedule.map((entry) => {
        return [new Date(entry.time).getTime(), entry.status === "active" ? 1 : 0];
      });
    yaxis_id: powersaver
    name: " "
    type: area
    color: rgb(0, 255, 0)
    opacity: 0.2
    stroke_width: 0
    curve: stepline
    group_by:
      func: min
    show:
      legend_value: false
      in_header: false
      name_in_header: false
      datalabels: false
```

</details>

## Disclaimer

The vast majority of this project was developed by an AI assistant. While I do have some basic experience with programming from a long time ago, I'm essentially the architect, guiding the AI, fixing its occasional goofs, and trying to keep it from becoming self-aware.
