# Intelligent Preheating for Home Assistant (v2.4.0)
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

### Recommended Sensors
- **Temperature**: A reliable room sensor (zigbee/zwave).
- **Outdoor Temp**: From a weather integration or physical sensor.
- **Valve Position**: (Optional) For "Smart Valve" logic that filters out low-flow learning noise.

## What's New in v2.4.0-beta1
- **Forecast Integration**: Connect a Weather Entity to predict heat loss during the night.
- **Strict Workday Mode**: Option to disable preheating on weekends/holidays.

