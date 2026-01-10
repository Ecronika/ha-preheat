# ⚙️ Configuration Reference

## Initial Setup Wizard

When you add the integration, you will be asked for the essential entities:

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
> **v2.9.0 Simplification**: Most "Expert" settings (Physics Mode, Initial Gain, Risk Mode, etc.) are now **automatically configured** based on your Heating Profile. You no longer need to tune them manually.

---

## Configure Options

After installation, click **Configure** on the integration entry to access additional settings.

### 🏗️ Profile & Timing

*   **Heating Profile**: Change your heating type if needed (Radiator, Floor, AC).
*   **Buffer (Minutes)**: Add extra minutes to the calculated start time for safety. Default: Profile-based.
*   **Earliest Start Time**: Prevent the heating from starting at 03:00 AM if you don't wake up until 07:00. Default: `180 min` (3 hours before target).
*   **Arrival Window**: Define when the system should expect arrivals (Start/End times).
*   **Comfort Fallback**: The default target temperature if no setpoint can be determined. Default: `21°C`.

### 🛑 Optimal Stop

*   **Enable Optimal Stop**: Activates "Coast-to-Stop" logic to save energy.
*   **Schedule Entity**: A `schedule`, `input_datetime`, or `sensor` helper defining when to stop heating.
    *   **Note**: No longer mandatory! If not provided, the system uses **Learned Departure** patterns.

### 🔒 External Control

*   **External Inhibit (Lock/Window)**: Select a `binary_sensor`, `switch`, or `input_boolean` that blocks preheating when ON.
    *   **Use Case**: Connect your window sensors to pause heating when a window is open.
*   **Workday Sensor**: Select a `binary_sensor` (usually `binary_sensor.workday_sensor`) to distinguish weekends/holidays.
*   **Valve Position Sensor**: Optional sensor for TRV valve position (improves learning accuracy).

---

## Advanced Settings (Auto-Configured)

The following settings are now **automatically determined** based on your Heating Profile and environment. They are hidden from the UI but can still be accessed via internal storage if needed.

| **Setting** | **Default Behavior** |
| :--- | :--- |
| **Physics Mode** | Auto-selects "Advanced" if Weather Entity is configured. |
| **Initial Gain** | Set from Heating Profile (e.g., 20 min/K for Radiators). |
| **Max Coast Duration** | Profile-based (e.g., 2h for Radiators, 4h for Floor). |
| **Occupancy Debounce** | Fixed at 15 minutes (not user-configurable). |
| **Risk Mode** | Always "Balanced" (deprecated setting). |

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
*   **`button.*_recompute`**: Force immediate re-evaluation of all logic.
*   **`button.*_reset_model`**: Reset physics learning to defaults.
*   **`button.*_analyze_history`**: Rebuild patterns from recorder history.

### 📉 Optimal Stop
*   **`binary_sensor.optimal_stop_active`**:
    *   **Note**: This entity is automatically **Hidden by default** if the feature is unused (disabled in config). If enabled, it is visible.
    *   **ON** when the system determines you can turn **OFF** the heating early, because the residual heat will carry you to the end of the schedule.
