# ⚙️ Configuration Reference

## Initial Setup Wizard

When you add the integration, you will be asked for the essential entities:

| **Setting** | **Description** | **Required** |
| :--- | :--- | :--- |
| **Heating Profile** | Select your heating type (Radiator, Floor, AC). Determines default physics. | ✅ Yes |
| **Occupancy Sensor** | A `binary_sensor` that is **ON** when the room is in use (occupied). | ✅ Yes |
| **Climate Entity** | The thermostat itself. | ✅ Yes |
| **Temperature Sensor** | Room temperature sensor. Optional if Climate entity is accurate. | Optional |
| **Weather Entity** | `weather.*` entity for forecast logic. | Optional |
| **External Inhibit / Window Sensor** | A `binary_sensor` or `switch` that blocks preheating when ON. | Optional |

> [!NOTE]
> **v2.9.0 Simplification**: Most "Expert" settings (Physics Mode, Initial Gain, Risk Mode, etc.) are now **automatically configured** based on your Heating Profile. You no longer need to tune them manually.

---

## Configure Options

After installation, click **Configure** on the integration entry to access additional settings.

### 🕐 Schedule & Triggers

*   **Enable Optimal Stop**: Activates "Coast-to-Stop" logic to save energy.
*   **Schedule Entity**: A `schedule` or `input_datetime` helper defining when to stop heating.
    *   **Note**: No longer mandatory! If not provided, the system uses **Learned Departure** patterns.
*   **Only on Workdays**: If checked, preheating will only activate on Mon-Fri (or days defined by your `binary_sensor.workday_sensor`).
*   **Earliest Start Time**: Prevent the heating from starting at 03:00 AM if you don't wake up until 07:00.

### 📅 Holidays & Calendar Intelligence

*   **Holiday Calendar**: Select a Home Assistant `calendar` entity.
    *   **Logic**: If *any* event is active on a day (e.g., "Holiday", "Vacation"), that day is treated as a **blocked day** (no preheating).
*   **Workday Sensor**: Select a `binary_sensor` (usually `binary_sensor.workday_sensor`) to distinguish weekends/holidays.
*   **Occupancy Debounce**: Avoid false alarms when you leave for just 5 minutes.
    *   **Default**: `15 minutes`.

### 🔒 External Inhibit (Window Sensor)

*   **External Inhibit Entity**: Select a `binary_sensor` (e.g., window contact) or `switch`.
    *   **Logic**: When this entity is **ON**, preheating is blocked (shows "External Inhibit" as blocking reason).
    *   **Use Case**: Connect your window sensors to pause heating when a window is open.

---

## Advanced Settings (Auto-Configured)

The following settings are now **automatically determined** based on your Heating Profile and environment. They are hidden from the UI but can still be accessed via YAML or the internal storage if needed.

| **Setting** | **Default Behavior** |
| :--- | :--- |
| **Physics Mode** | Auto-selects "Advanced" if Weather Entity is configured. |
| **Initial Gain** | Set from Heating Profile (e.g., 20 min/K for Radiators). |
| **Buffer (Minutes)** | Profile-based (e.g., 10 min for Radiators, 30 for Floor). |
| **Max Coast Duration** | Profile-based (e.g., 2h for Radiators, 4h for Floor). |
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
