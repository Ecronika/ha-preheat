# ⚙️ Configuration Reference

## Initial Setup Wizard

When you add the integration, you will be asked for the essential entities:

| **Setting** | **Description** | **Required** |
| :--- | :--- | :--- |
| **Occupancy Sensor** | A `binary_sensor` that is **ON** when the room is in use (occupied). | ✅ Yes |
| **Climate Entity** | The thermostat itself. | ✅ Yes |
| **Temperature Sensor** | Room temperature sensor. Optional if Climate entity is accurate. | Optional |
| **Weather Entity** | `weather.*` entity for forecast logic. | Optional |
| **Enable Optimal Stop** | Activates "Coast-to-Stop" logic to save energy. | Optional |
| **Schedule Entity** | A `schedule` helper defining when the day ends. **Required** if Optimal Stop is enabled. | **Conditionally** |

---

## Detailed Settings (Configure)

After installation, click **Configure** on the integration entry to access advanced settings.

### 🏗️ Physics & Learning

*   **Heating Profile**: Select the preset that best matches your hardware to help the initial learning.
    *   *Radiator (Standard)*: Typical water-based radiators.
    *   *Floor (Concrete)*: Slow reacting implementation. High deadtime defaults.
    *   *Air Conditioning*: Fast reacting systems.
*   **Physics Mode**: Choose the simulation engine.
    *   *Standard (Default)*: Robust, noise-tolerant model. Best for most users.
    *   *Advanced (Euler)*: Precise forward-simulation using 30-minute steps. Improved accuracy for complex variable-temperature schedules but more sensitive to sensor noise.
*   **Initial Gain**: Manually override the "Minutes per Degree" factor if the automatic learning starts too slow/fast. Lower = Faster heating.


### ⚠️ Risk & Buffers

*   **Risk Mode**: How aggressively should we trust the weather forecast?
    *   *Balanced (Default)*: Moderate trust.
    *   *Pessimistic*: Assumes it's colder than forecasted. Safer, but uses more energy.
    *   *Optimistic*: Assumes it's warmer. Saves energy, risk of being cold.
*   **Buffer (Minutes)**: Add extra minutes to the calculated start time just to be safe. Default: `10`.

### 🛑 Optimal Stop (Eco)

*   **Enable Optimal Stop**: Turns on the coast-to-stop calculation.
*   **Schedule Entity**: A `schedule` helper that defines your "Day". The system needs to know when the "End of Day" is to calculate when to shut off.
    *   *Tip*: Create one in Settings → Helpers → Schedule.
    *   **Note**: If Optimal Stop is enabled, this field is **mandatory**. You cannot save the configuration without it.
*   **Stop Tolerance**: How many degrees drop is acceptable during the coasting phase? Default: `0.5°C`.

### 🕐 Triggers

*   **Only on Workdays**: If checked, preheating will only activate on Mon-Fri (or days defined by your `binary_sensor.workday_sensor`).
*   **Earliest Start Time**: Prevent the heating from starting 03:00 AM if you don't wake up until 07:00.

---

### 📅 Holidays & Intelligence

*   **Holiday Calendar**: Select a Home Assistant `calendar` entity.
    *   **Logic**: If *any* event is active on a day (e.g., "Holiday", "Vacation"), that day is treated as a **blocked day** (no preheating).
    *   **Check**: The system checks 8 days into the future.
*   **Workday Sensor**: Select a `binary_sensor` (usually `binary_sensor.workday_sensor`) to distinguish weekends/holidays.
    *   **Fallback**: If not configured, Mon-Fri are considered workdays.
*   **Occupancy Debounce**: Avoid false alarms when you leave for just 5 minutes.
    *   **Setting**: `Occupancy Debounce Time (Minutes)`.
    *   **Logic**: The system waits this many minutes after occupancy is lost before officially declaring "Departure" and fitting the heating curve. Default: `15 minutes`.

---

## Entity Explanations (Automation Interface)

### 🎛️ Controls
*   **`switch.enabled`**: **Master Enable**. Turns the integration on/off. If OFF, no calculations or checks run.
*   **`switch.preheat`** (Hidden by default): **Manual Override**. Reflects the *current* heating state. Toggling it manually **Forces** preheat ON or OFF.
*   **`switch.preheat_hold`**: **Temporary Hold (Logic)**. Temporarily blocks preheating (e.g., for automation-based inhibits).
    *   **Note**: This state is **logic-based** and resets to OFF upon a Home Assistant restart. It is not suitable for long-term "Vacation Mode". Use the Integration's `Enable` switch for long absences.

### 🚥 Automation Triggers
*   **`binary_sensor.preheat_needed`**:
    *   **Logic**: Returns `ON` when `Now >= Next Start Time`.
    *   **Note**: This entity is **Hidden by default** (Expert debug tool).
    *   **Recommendation**: For automation triggers, prefer **`binary_sensor.preheat_active`**.
*   **`binary_sensor.preheat_active`** (Primary Trigger):
    *   **Logic**: `ON` when the room **should be heating right now** (Needed AND Not Blocked AND Not Occupied).
    *   **Use Case**: Use this entity to start your boiler/thermostat.
*   **`binary_sensor.preheat_blocked`**:
    *   **Logic**: `ON` if heating is prevented (Hold, Window, Holiday, Disabled). Check attributes for the specific reason.

### 📊 Data Sensors
*   **`sensor.*_next_preheat_start`**: Timestamp of next heating cycle start (`next_start`).
*   **`sensor.*_predicted_duration`**: Estimated heat-up time (minutes).
*   **`sensor.*_target_temperature`**: The effective target setpoint.
*   **`sensor.*_next_arrival_time`**: Next expected occupancy event.
*   **`sensor.*_next_session_end`**: When the current session ends (for Optimal Stop).

### 🛠️ Maintenance (Buttons)
*   **`button.*_recompute_decisions`**: Force immediate re-evaluation of all logic.
*   **`button.*_reset_thermal_model`**: Reset physics learning to defaults.
*   **`button.*_analyze_history`**: Rebuild patterns from recorder history.

### 📉 Optimal Stop
*   **`binary_sensor.optimal_stop_active`**:
    *   **Note**: This entity is **Hidden by default** if the feature is unused.
    *   **ON** when the system determines you can turn **OFF** the heating early, because the residual heat will carry you to the end of the schedule.
