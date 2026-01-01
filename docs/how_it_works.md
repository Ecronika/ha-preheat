# 🧠 How it Works

Intelligent Preheating uses a physics-based model (First Order Time Delay - PT1) to simulate your room's thermal behavior.

## The Physical Model

The system solves a differential equation for every room:

$$
\text{Duration} = \text{Deadtime} + (\text{Mass} \cdot \Delta T_{in}) + (\text{Loss} \cdot \Delta T_{out} \cdot \text{Scaling})
$$

*   **Scaling Factor**: The system intelligently scales the impact of outdoor cold ("Cold Weather Penalty") based on how much heating is actually required.
*   **Deadtime**: A fixed delay before the room reacts (e.g. floor heating slab heat-up).

Don't worry about the math. Here is what it means for you:

### 1. Thermal Mass (`mass_factor`)
*   **What is it?**: How much energy (time) is needed to raise the room temperature by 1°C?
*   **Unit**: Minutes / Degree.
*   **Learning**: Every time your heating runs and the temperature rises, the system measures the speed. If it heats faster than expected, this number goes down.

### 2. Thermal Loss (`loss_factor`)
*   **What is it?**: How quickly does the room lose heat to the outside?
*   **Impact**: On cold days, the system knows it needs *more* power (time) just to fight the cold walls.
*   **Learning**: Currently fixed based on "Heating Profile", but fine-tuned by the algorithm.

### 3. Deadtime (`deadtime`)
*   **What is it?**: The delay between "Valve Open" and "Temperature starts rising".
*   **Typical values**:
    *   Radiators: 15-30 minutes.
    *   Floor Heating: 60-180 minutes.
*   **Effect**: The start time is shifted earlier by this amount.

## The prediction Loop

Every minute, the system runs a simulation:
1.  Look at the **Target Temperature** (e.g. 21°C).
2.  Look at the **Next Predicted Arrival** (based on your history of the last 28 days).
3.  Simulate backwards: "If I want to be 21°C at 07:00, and it's 0°C outside...":
    *   Floor heating needs 4 hours.
    *   Radiator needs 1.5 hours.
4.  If the result says "Start Time" is **NOW** (or in the past), the `switch.preheat` turns **ON**.

## History & Occupancy

The system does NOT use a fixed schedule input from you for the **Start** time. It learns from your behavior.
*   It looks at your `occupancy_sensor` history (rolling window of 60 days).
*   It continuously records when you leave ("Departure") to build a probability model.
*   It predicts the next event based on weekday-specific patterns (e.g., "Usually occupied at 06:45 on Mondays").
*   **Shadow Mode**: Even if you use a fixed schedule, the AI runs in the background to show you when it *would* have switched.

*Note: For the **Stop** time (Optimal Stop), it DOES need a fixed schedule input, because predicting when you leave is riskier.*
