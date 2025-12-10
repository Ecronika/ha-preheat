# Intelligent Preheating for Home Assistant (v2.5.0-beta1)
- **Transparent**: Includes a Confidence Sensor and detailed Diagnostics to see exactly "why" it's doing what it's doing.

## Installation
1. Install via HACS (Custom Repository) or copy `custom_components/preheat` to your HA config.
2. Add integration via Settings -> Devices -> Add Integration -> "Intelligent Preheating".

## Configuration
### Expert Settings (Optional)
- **Minimum Comfort Temp**: Threshold to distinguish "Eco/Off" from "Comfort" (Default: 19°C).
- **Fallback Temp**: Target used if no history exists yet (Default: 21°C).

### Weather Forecast (New in v2.4) ⛈️
Enable "Use Weather Forecast" in Expert Settings to react to incoming cold fronts.
- **Risk Mode**:
    - *Balanced*: Standard physics calculation (Recommended).
    - *Pessimistic (P10)*: Assumes it will be colder than average. Better comfort.
    - *Optimistic (P90)*: Assumes it will be warmer. Better savings.


### Critical Note on Occupancy ⚠️
This integration uses the **Occupancy Sensor** to **STOP** preheating.
- **TRUE/ON**: Means "User is physically present". The preheater stops, and your normal thermostat schedule should take over.
- **FALSE/OFF**: Means "Room is empty". The preheater waits for the next scheduled arrival to start purely predictive heating.

**DO NOT** use a scheduler entity (that turns ON at 07:00) as the Occupancy Sensor! This will cause the preheater to shut down exactly when you want it to run. Usage of a schedule helper logic should be inverted or handled separately.
- **Robust**: Detects open windows and sensor errors to prevent wasteful heating.
- **Transparent**: Includes a Confidence Sensor and detailed Diagnostics to see exactly "why" it's doing what it's doing.

## Installation
1. Install via HACS (Custom Repository) or copy `custom_components/preheat` to your HA config.
2. Add integration via Settings -> Devices -> Add Integration -> "Intelligent Preheating".

## Configuration
### Expert Settings (Optional)
- **Minimum Comfort Temp**: Threshold to distinguish "Eco/Off" from "Comfort" (Default: 19°C).
- **Fallback Temp**: Target used if no history exists yet (Default: 21°C).

### Weather Forecast (New in v2.4) ⛈️
Enable "Use Weather Forecast" in Expert Settings to react to incoming cold fronts.
- **Risk Mode**:
    - *Balanced*: Standard physics calculation (Recommended).
    - *Pessimistic (P10)*: Assumes it will be colder than average. Better comfort.
    - *Optimistic (P90)*: Assumes it will be warmer. Better savings.

### Weather Forecast (New in v2.4) ⛈️
Enable "Use Weather Forecast" in Expert Settings to react to incoming cold fronts.
- **Risk Mode**:
    - *Balanced*: Standard physics calculation (Recommended).
    - *Pessimistic (P10)*: Assumes it will be colder than average. Better comfort.
    - *Optimistic (P90)*: Assumes it will be warmer. Better savings.

### Critical Note on Occupancy ⚠️
This integration uses the **Occupancy Sensor** to **STOP** preheating.
- **TRUE/ON**: Means "User is physically present". The preheater stops, and your normal thermostat schedule should take over.
- **FALSE/OFF**: Means "Room is empty". The preheater waits for the next scheduled arrival to start purely predictive heating.

**DO NOT** use a scheduler entity (that turns ON at 07:00) as the Occupancy Sensor! This will cause the preheater to shut down exactly when you want it to run. Usage of a schedule helper logic should be inverted or handled separately.

### Optimal Stop (Coast-to-Stop) 🍃
*New in v2.5.0*

Intelligent Preheating now helps you save energy at the **end** of your heating cycle by "Coasting" to a stop.
- **How it works?** It learns how fast your room cools down (`tau_cool`) and calculates the exact moment to switch off the heating so that the room reaches your target Minimum Comfort Temp exactly at the end of the schedule.
- **Configuration**: Enabled via "Expert Settings".
- **Schedule Requirement**: For this to work, your **Schedule Entity** must accurately reflect the "Required Comfort Period" (e.g., 08:00 - 22:00). If you just toggle it manually, Optimal Stop cannot predict when to stop.

> **Signals, not Magic**: This integration provides a `binary_sensor.preheat_optimal_stop_active`. **YOU** decide what to do with it (e.g., turn off the switch, lower the thermostat). We do not override your climate entity automatically.

### Recommended Sensors
- **Temperature**: A reliable room sensor (zigbee/zwave).
- **Outdoor Temp**: From a weather integration or physical sensor.
- **Valve Position**: (Optional) For "Smart Valve" logic that filters out low-flow learning noise.

## What's New in v2.5.0-beta1
- **Optimal Stop**: predictive coasting to save energy at the end of the day.
- **Improved Forecast Integration**: Better handling of mild weather conditions.
- **Strict Workday Mode**: Option to disable preheating on weekends/holidays.

