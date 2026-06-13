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

For zone-specific behaviors, the system can learn from your historical activity.
*   It looks at your occupancy sensor history (rolling window of **30 days** for arrivals, **60 days** for departures).
*   It continuously records when you leave ("Departure") to build a probability model.
*   It predicts the next event based on weekday-specific patterns.
*   It supports **Multi-Modal Patterns** (e.g., morning shift AND afternoon return).

## House Arrival Prediction

To enable fully autonomous, schedule-free preheating, the **House Arrival Hub** analyzes occupancy patterns across the entire home.

### The Prediction Model
Arrival events from the occupancy sensors are processed using a statistical pooling model:
*   **Time Blocks**: Arrival events are divided into **AM** (morning) and **PM** (evening) blocks.
*   **Day Groups**: Data is pooled by **workday** vs. **weekend** (using the configured Workday Sensor) to distinguish daily routines.
*   **First-Event Filtering**: To prevent noise (e.g. going out briefly to get the mail), the hub only records the **first arrival per block per day**.
*   **Target Quantile (P25)**: Rather than aiming for the average arrival time (which would leave you cold half of the time), the hub targets an **early quantile (P25)** by default. This "prefer early" approach ensures the house is warm before the typical arrival window begins.
*   **Graded Confidence**: Instead of an all-or-nothing threshold, arrival confidence is graded dynamically based on the spread (tolerance band) of historical arrivals. If arrivals are highly consistent, confidence is high.
*   **Shift Patterns**: The model can detect alternating weekly shift patterns (e.g., early/late weeks) if the arrival times are clearly separated.

### Morning vs. Evening Preheating
*   **Morning Arrivals**: Typically exhibit highly consistent, high-confidence patterns, allowing the autonomous engine to reliably preheat without a schedule helper.
*   **Evening Homecoming**: Intrinsically more variable. To manage this variability, you can adjust the **Arrival Comfort Bias** (economy, balanced, comfort) or rely on the **Evening Comfort Window fallback**. If arrival confidence is too low to predict a specific time, the system will fallback to the configured evening window to guarantee warmth.

> [!NOTE]
> **Schedule-Free & Energy Saving Features**:
> *   **Schedule-Free Autonomous Start (since v2.11)**: Managed globally via the House Arrival Hub. Once arrival patterns are mature and confident, zones can preheat dynamically without requiring a manual Schedule Helper.
> *   **Optimal Stop (since v2.10)**: Available as an opt-in feature (`Enable Optimal Stop` in configuration) to turn off heating early when residual heat is sufficient to carry the room to the end of a scheduled session.

