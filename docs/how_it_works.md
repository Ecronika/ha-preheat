# 🧠 How it Works

Intelligent Preheating uses a physics-based model to simulate your room's thermal behavior.

## The Physical Model

The system calculates how long it takes to heat your room:

$$
\text{Duration} = \text{Deadtime} + (\text{Mass} \cdot \Delta T_{in}) + (\text{Loss} \cdot \Delta T_{out})
$$

*   **Deadtime**: A fixed delay before the room reacts (e.g. floor heating slab heat-up).
*   **Delta T_in**: How many degrees you need to raise the room temperature.
*   **Delta T_out**: The difference between indoor and outdoor temperature.

Don't worry about the math. Here is what it means for you:

### 1. Thermal Mass (`mass_factor`)
*   **What is it?**: How much time is needed to raise the room temperature by 1°C?
*   **Unit**: Minutes / Degree.
*   **Learning**: Every time your heating runs and the temperature rises, the system measures the speed. If it heats faster than expected, this number goes down.

### 2. Thermal Loss (`loss_factor`)
*   **What is it?**: How much extra time is needed per degree of outdoor cold?
*   **Impact**: On cold days, the system knows it needs *more* time just to fight heat loss through the walls.
*   **Learning**: Initialized based on "Heating Profile", then continuously fine-tuned by the algorithm (especially on cold days).

### 3. Deadtime (`deadtime`)
*   **What is it?**: The delay between "Valve Open" and "Temperature starts rising".
*   **Typical values**:
    *   Radiators: 15-30 minutes.
    *   Floor Heating: 60-180 minutes.
*   **Effect**: The start time is shifted earlier by this amount.

## The Prediction Loop

Every minute (or 5 minutes when idle), the system runs a simulation:
1.  Look at the **Target Temperature** (e.g. 21°C).
2.  Look at the **Next Predicted Arrival** (based on your history of the last 30 days).
3.  Simulate backwards: "If I want to be 21°C at 07:00, and it's 0°C outside...":
    *   Floor heating needs 4 hours.
    *   Radiator needs 1.5 hours.
4.  If the result says "Start Time" is **NOW** (or in the past), the `binary_sensor.preheat_active` turns **ON**.

## History & Occupancy

The system does NOT use a fixed schedule input from you for the **Start** time. It learns from your behavior.
*   It looks at your `occupancy_sensor` history (rolling window of **30 days** for arrivals, **60 days** for departures).
*   It continuously records when you leave ("Departure") to build a probability model.
*   It predicts the next event based on weekday-specific patterns (e.g., "Usually occupied at 06:45 on Mondays").
*   It supports **Multi-Modal Patterns** (e.g., morning shift AND afternoon return).

> [!NOTE]
> **Schedule-Free Optimal Stop (v2.9.0)**: For the **Stop** time (Optimal Stop), the system can now use **Learned Departure** patterns if no Schedule Helper is configured. A fixed schedule is no longer required!

