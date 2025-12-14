# Roadmap to V3.0: The Path to Autonomy

The goal of V3.0 is "Zero-Touch" operation. To get there, we will iterate through several minor releases, each adding a building block of intelligence.

---

## 📅 The Path Forward

### v2.5.0 (Current)
*   **Focus**: Robustness & Physics.
*   **Status**: Beta (Workday Logic fixed, Health Score added).
*   **Goal**: Release as Stable.

### v2.6.0: "Visibility" (Gamification)
*   **Feature**: Energy Dashboard / Savings Report.
*   **Concept**: Track "Saved Runtime" (Minutes not heated due to Optimal Stop) and estimate kWh savings.
*   **Value**: Users see immediate ROI.

### v2.7.0: "Context" (Calendar & Tariffs)
*   **Feature 1**: Full HA Calendar Support.
    *   Support for Shifts, Vacations, and complex patterns beyond simple "Workdays".
*   **Feature 2**: Dynamic Tariff Awareness (Initial).
    *   Shift heating start slightly to optimize for Price/CO2 (e.g. Tibber).
*   **Feature 3**: Extended History Import (InfluxDB).
    *   Allow importing history from external DBs like InfluxDB for users with short Recorder retention.

### v2.8.0: "Patterns" (Smart Departure Beta)
*   **Feature**: Auto-Schedule Learning.
*   **Concept**: Begin analyzing vacancy patterns ("When does the user leave?") without acting on them yet.
*   **Goal**: Shadow Mode to gather data for V3.

---

## 🔮 V3.0: Autonomous Intelligence
*   **The Big Switch**: Enable "Auto-Schedule" by default.
*   **Machine Learning V2**: Replace simple Clustering with Time-Series prediction.
*   **Zero Config**: No more manual Schedule Helpers required.

