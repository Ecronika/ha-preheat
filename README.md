# Intelligent Preheating for Home Assistant (v2.2.2)

A smart, learning-based preheating controller that ensures your room is at the target temperature exactly when you arrive.

## Features
- **Predictive**: Learns your room's thermal physics (mass/insulation) to calculate the perfect start time.
- **Adaptive**: Uses Exponential Moving Average (EMA) to adapt to changing seasons.
- **Robust**: Detects open windows and sensor errors to prevent wasteful heating.
- **Transparent**: Includes a Confidence Sensor and detailed Diagnostics to see exactly "why" it's doing what it's doing.

## Installation
1. Install via HACS (Custom Repository) or copy `custom_components/preheat` to your HA config.
2. Add integration via Settings -> Devices -> Add Integration -> "Intelligent Preheating".

## Configuration
### Critical Note on Occupancy ⚠️
This integration uses the **Occupancy Sensor** to **STOP** preheating.
- **TRUE/ON**: Means "User is physically present". The preheater stops, and your normal thermostat schedule should take over.
- **FALSE/OFF**: Means "Room is empty". The preheater waits for the next scheduled arrival to start purely predictive heating.

**DO NOT** use a scheduler entity (that turns ON at 07:00) as the Occupancy Sensor! This will cause the preheater to shut down exactly when you want it to run. Usage of a schedule helper logic should be inverted or handled separately.

### Recommended Sensors
- **Temperature**: A reliable room sensor (zigbee/zwave).
- **Outdoor Temp**: From a weather integration or physical sensor.
- **Valve Position**: (Optional) For "Smart Valve" logic that filters out low-flow learning noise.

## What's New in v2.2.1
- **HACS Ready**: Full compliance with default repository standards (Linting, Licenses, Workflows).
- **Window Detection**: Pauses learning if temp drops >0.4K in 5 minutes.
- **System Health**: Full Diagnostics export available.
- **Persistence**: Improved error metric tracking across restarts.
