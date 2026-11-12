# ⚙️ Configuration Reference

## Integration Entry Types

Starting with **v2.11.1**, the integration automatically manages two types of configuration entries:
1.  **Per-Zone Entries**: Created for each heating zone (room). They contain zone-specific settings (thermostats, local sensors, heating profiles).
2.  **Preheat System Entry**: Created automatically in the background (no manual step required). It manages the shared **House Arrival Hub** and holds global settings.

---

## Initial Setup Wizard

When you add the integration for a new zone, you will be asked for the essential entities:

| **Setting** | **Description** | **Required** |
| :--- | :--- | :--- |
| **Zone Name** | A friendly name for this heating zone (e.g., "Office", "Living Room"). | ✅ Yes |
| **Occupancy Sensor** | A `binary_sensor` that is **ON** when the room is in use (occupied). | ✅ Yes |
| **Climate Entity** | The thermostat itself. | ✅ Yes |
| **Heating Profile** | Select your heating type (Radiator, Floor, AC). Determines default physics. | ✅ Yes |
| **Temperature Sensor** | Room temperature sensor. Optional if Climate entity is accurate enough. | Optional |
| **Valve Position Sensor** | Optional sensor for TRV valve position (improves learning). | Optional |
| **Weather Entity** | `weather.*` entity for forecast logic. | Optional |

> [!NOTE]
> **Simplification**: Most "Expert" settings (Physics Mode, Initial Gain, Risk Mode, etc.) are now **automatically configured** based on your Heating Profile. You no longer need to tune them manually.

---

## Configure Options

After setup, click **Configure** on any entry to access settings.

### 🏠 Preheat System (Global Hub) Options
These options are configured only on the automatically created **Preheat System** entry:

*   **Global Presence Source** (`global_presence`): An optional `binary_sensor`, `person`, or presence entity used as the primary source for detecting when anyone is home. If left empty, the hub automatically aggregates occupancy data across all active zones.
*   **Arrival Comfort Bias** (`arrival_comfort_bias`): Controls how early the predicted arrival target is set. Options:
    *   `comfort`: P15/P10 percentile (earliest target, prioritizes warmth, lower savings).
    *   `balanced`: P25 percentile (default, standard balance).
    *   `economy`: P50 percentile (median target, prioritizes savings, might feel cooler).
*   **Evening Comfort Window** (`evening_comfort_window`): An optional fallback window (e.g., `17:00-22:00`) used for evening preheating when the hub's statistical arrival confidence falls below the 70% threshold. This guarantees evening warmth when schedules are irregular.

### 🏗️ Zone Options (Per-Zone Entries)
These options are configured on each individual zone entry:

*   **Heating Profile**: Change your heating type if needed (Radiator, Floor, AC).
*   **Buffer (Minutes)**: Start this many minutes earlier than the calculated heat-up time, so the target is reached before the arrival (start = arrival − (predicted duration + buffer)). The total lead time is capped by *Max Preheat Duration*; no buffer is added if the room is already warm. The buffer is excluded when the model learns from a preheat run. Range 0–60. Default: Profile-based.
*   **Earliest Start Time**: Prevent the heating from starting at 03:00 AM if you don't wake up until 07:00. Default: `180 min` (3 hours before target).
*   **Arrival Window**: Define when the system should expect arrivals (Start/End times).
*   **Comfort Fallback**: The default target temperature if no setpoint can be determined. Default: `21°C`.

### 🛑 Optimal Stop
*   **Enable Optimal Stop**: Activates "Coast-to-Stop" logic to save energy. Turns off the heating early if the room stays warm enough until the schedule ends.
*   **Use House Arrival prediction** (`use_house_arrivals`, default on): When on, a confident House Arrival Hub prediction (or its evening fallback window) replaces this zone's own learned arrival pattern. Turn it off for zones with their own rhythm (e.g. a bedroom); the zone then uses its own pattern.
*   **Schedule Entity**: A `schedule` helper defining your comfort periods. While it is **off**, its next ON transition is used as the next preheat target (taking priority over House and learned arrival predictions; days excluded by the holiday calendar or workday settings are skipped). While it is **on**, the end of the current period is used as the session end for Optimal Stop.

### 🔒 External Control
*   **External Inhibit (Lock/Window)**: Select a `binary_sensor`, `switch`, or `input_boolean` that blocks preheating when ON (e.g., window sensor to pause heating when open).
*   **Workday Sensor**: Select a `binary_sensor` (usually `binary_sensor.workday_sensor`) to distinguish weekends/holidays.
*   **Valve Position Sensor**: Optional sensor for TRV valve position (improves learning accuracy).

---

## Advanced Settings (Auto-Configured)

The following settings are automatically determined based on your Heating Profile and environment:

| **Setting** | **Default Behavior** |
| :--- | :--- |
| **Physics Mode** | Auto-selects "Advanced" if Weather Entity is configured. |
| **Initial Gain** | Set from Heating Profile (e.g., 20 min/K for Radiators). |
| **Max Coast Duration** | Profile-based (e.g., 2h for Radiators, 4h for Floor). |
| **Occupancy Debounce** | Fixed at 15 minutes (not user-configurable). |

---

## Entity Explanations (Automation Interface)

### 🏠 Global House Entities (Exposed by Preheat System)
Exposed under the **Preheat House** device:
*   **`sensor.preheat_house_next_arrival`**: Timestamp of the next predicted arrival for the house.
*   **`sensor.preheat_house_arrival_confidence`**: Confidence in the house arrival prediction (%).
*   **`sensor.preheat_house_arrival_window`**: expected arrival window (e.g. `12:13-13:34`).
*   **`binary_sensor.preheat_house_incoming`**: Primary "someone is coming home" preheat signal. Returns `ON` within the maximum preheat lead time before expected house arrival.

### 🎛️ Zone Controls
*   **`switch.<zone>_enabled`**: Master Enable. Turns the zone on/off. If OFF, no calculations or checks run.
*   **`switch.<zone>_preheat`** (Hidden by default): Manual Override. Reflects the current heating state. Toggling it manually forces preheat ON or OFF.
*   **`switch.<zone>_preheat_hold`**: Temporary Hold. Temporarily blocks preheating. Resets to OFF on restart.

### 🚥 Zone Automation Triggers
*   **`binary_sensor.<zone>_preheat_needed`**: `ON` when `Now >= Next Start Time`. (Hidden by default).
*   **`binary_sensor.<zone>_preheat_active`** (Primary Trigger): `ON` when the room should be heating right now (Needed AND Not Blocked AND Not Occupied). Use this to trigger your thermostat.
*   **`binary_sensor.<zone>_preheat_blocked`**: `ON` if heating is actively prevented by a **true suppressor** (e.g., integration disabled, window open, manual hold, or safety limits). 
    *   *Note*: Having "no source available" (no upcoming schedule and no confident house pattern) is **not** considered blocked.

### 📊 Zone Data Sensors
*   **`sensor.<zone>_next_preheat_start`**: Timestamp of next heating cycle start (`next_start`).
*   **`sensor.<zone>_predicted_duration`**: Estimated heat-up time (minutes).
*   **`sensor.<zone>_target_temperature`**: The effective target setpoint. While the zone is occupied this is the thermostat setpoint; otherwise the higher of the thermostat setpoint and the **learned comfort setpoint**.
    *   *Learned comfort setpoint* (`learned_setpoint` on the status sensor): the setpoint held **longest** while the zone was occupied (time-weighted median, learned after 15 minutes of occupancy), limited to 19.0–23.5 °C, so short boosts do not become the preheat target. `comfort_tracked_min` and `comfort_session_setpoints` show what the current session is based on. Reset it with the `preheat.reset_comfort_setpoint` service.
*   **`sensor.<zone>_next_arrival_time`**: Next expected occupancy event.
*   **`sensor.<zone>_next_session_end`**: When the current session ends (for Optimal Stop).

### 📉 Optimal Stop
*   **`binary_sensor.<zone>_optimal_stop_active`**: `ON` when the system determines you can turn OFF the heating early, because the residual heat will carry you to the end of the schedule.

### 🛠️ Maintenance (Buttons)
*   **`button.<zone>_recompute`**: Force immediate re-evaluation of all logic.
*   **`button.<zone>_reset_model`**: Reset physics learning to defaults.
*   **`button.<zone>_analyze_history`**: Rebuild patterns from recorder history.
*   Services: `preheat.recompute`, `preheat.reset_model`, `preheat.reset_comfort_setpoint` (target zone entities, devices or areas; no target = all zones).

---

## Decision Trace (Debugging)

The `decision_trace` attribute on `binary_sensor.<zone>_preheat_active` contains detailed diagnostics. The `start_source` field indicates which preheating provider won the arbitration.

### `start_source` values and priority:
When evaluating when to start preheating, the system arbitrates among available providers in the following strict priority:
1.  **`schedule`**: Preheating is scheduled via a configured Schedule entity (highest priority).
2.  **`house`**: Preheating is triggered by a confident (>= 70% confidence) prediction from the House Arrival Hub (unless *Use House Arrival prediction* is off for the zone).
3.  **`house_fallback`**: Preheating is triggered by the global Evening Comfort Window fallback.
4.  **`learned`**: Preheating is triggered by zone-specific learned patterns (only if no house prediction wins).
5.  **`none`**: No preheating is needed or no source is available (lowest priority).
