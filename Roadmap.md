# Intelligent Preheating Roadmap (v3.0+)

**Vision: From "Predictive Control" to "Autonomous Operation"**

The goal of v3.0 ("Autonomous Intelligence") is to reduce configuration to near zero. The system should not only learn *how* to heat, but also *when* to heat and *when* to stop.

---

## 🏁 Completed Milestones (v2.x Era)
**Status:** ✅ Released & Stable

*   [x] **Sensor Fusion Layer** (v2.2)
*   [x] **Dynamic Physics Model (Deadtime & Inertia)** (v2.3)
*   [x] **Forecast Integration** (v2.4)
*   [x] **Optimal Stop (Coast-to-Vacancy)** (v2.5)
*   [x] **Multi-Modal Clustering (Shift Work)** (v2.6)
*   [x] **Diagnostics, Health Score & Repair Issues** (v2.6)

---

## 🚀 Phase 3: Autonomous Departure (The Road to v3.0)

### 📦 Release v2.7.x: Shadow-Mode & Stability (Current Stable)
**Status:** ✅ Released (v2.7.4)

*   [x] **Provider Architecture**: Separation of Schedule vs. Learned Logic.
*   [x] **Shadow Mode**: Running the AI Brain in background without switching.
*   [x] **Observability**: `decision_trace` attribute & Lovelace Debug Card.
*   [x] **Effective Departure**: Logic to arbitrate between Schedule and AI.
*   [x] **Optimal Stop Integration**: Now uses "Effective Departure" (Schedule OR AI).
*   [x] **Safety Fixes**:
    *   **Manual Hold**: Switch `switch.preheat_hold` kills all auto-logic immediately.
    *   **Workday Override**: Strict blocking if `binary_sensor.workday` is off.
    *   **Physics Hotfix**: Resolved scaling issues in v2.7.1.
    *   **Dev Tools**: Debug logging for Override logic (v2.7.4).

### 📦 Release v2.8: "The Brain Update" (Completed)
**Status:** ✅ Released (v2.8.0)
*Goal: Give the system the Context (Calendar) and the Intelligence (Clustering) to predict heating needs autonomously.*

*   [x] **Feature: Calendar Intelligence** (Knowing *When*) (v2.8-beta3/4)
    *   [x] **Workday Lookahead**: Query `calendar.get_events` (7-day) to identify valid workdays/holidays precisely.
    *   [x] **Auto-Discovery**: Automatically find `binary_sensor.workday_sensor` if present.
*   [x] **Feature: Autonomous Brain** (Knowing *How Long*)
    *   [x] ** foundation**: Session State Machine & Departure Recorder (v2.8-beta1).
    *   [x] **Prediction Logic**: Quantile Regression (P50/P90) for robust estimates.
*   [x] **Physics v2.8**:
    *   [x] **Euler Integration**: For Cooling Prediction (Higher Accuracy) via `CONF_PHYSICS_MODE`.

### 📦 Release v3.0: Autonomous Intelligence (Control Mode)
**Status:** Vision (Zero Config)

*   [ ] **Smart Departure Control**
    *   Opt-in: Allow the Learned Provider to take control (overriding Schedule).
    *   **Safety Net**: Auto-fallback to Schedule if AI confidence drops.
    *   **V3 Clustering Engine**: Full implementation of DBSCAN for complex patterns.
    *   **Prediction Metrics**: Calculate `Departure Error` and `Promotion Signal`.
*   [ ] **Zero-Config Onboarding**:
    *   "Just install and wait 5 days" experience.
*   [ ] **Advanced DSP**:
    *   Deadtime Filter (Savitzky-Golay) to reject noise spikes.

### 🏗️ Architecture & Technical Debt (Planned for v3.0+)
*   [ ] **Session ID Concept**: Remove "1 Departure per Day" limitation.
    *   Support multiple sessions (Morning/Evening shifts). requires storage migration.
*   [ ] **Event-Driven Debouncer**:
    *   Replace `OccupancyDebouncer` polling loop with purely event-driven logic to eliminate race conditions by design.
*   [ ] **Advanced DST Handling**:
    *   Replace offset-based DST flagging with fully timezone-aware storage (UTC + Zone Info).
*   [ ] **Pluggable Physics**:
    *   Expose `CONF_PHYSICS_MODE` (Standard/Advanced) to users.

---

## 🛠️ Phase 3.1: Precision & Refinement (Future)
**Goal:** Tuning and Scaling.

*   [ ] **Presence Prediction (Soft Signal)**:
    *   Geofence Bias: "Away" -> `start_delay += 15min`.
*   [ ] **Data Privacy**: Granular retention controls ("Forget my history").
*   [ ] **Performance**: Incremental loading optimization for extremely large histories.

---

## 🏗️ Phase 3.2: Advanced Architecture (v3.2)
**Goal:** Modularization & Advanced Control.

*   [ ] **Pluggable Physics Architecture**
    *   Interface: `predict_duration`, `update_model`, `serialize`.
    *   Viz: Show `active_model_type` + `version` in Diagnostics/UI.
*   [ ] **Seasonal Adaptation (RLS/Kalman)**
    *   Goal: No Oscillation during transitions; Converges faster than EMA in Spring tests.

---

## 🔮 Phase 4: Future Concepts & Ecosystem
**Goal:** Optimization beyond Comfort.

*   [ ] **Confidence-Aware Planning**: Weighing risks dynamically.
*   [ ] **Dynamic Tariff Optimization**: Integrating energy prices into the start time calculation.

---

## ⛔ Non-Goals (v3.0)
*   **No Tariff Optimization**: Scheduled for v4.
*   **No Live Hot-Swap**: Config Reload/Restart is acceptable.

---

## 🔬 Technical Review Findings (Physics & Math)
**Source:** Expert Code Review (Jan 2026).
**Action Plan:** Address in v2.9 / v3.0 logic updates.

### High Priority (Stability & Accuracy)
*   [ ] **Euler Integration Stability**:
    *   **Finding**: Explicit Euler is unstable for small time constants (τ < 20min).
    *   **Goal**: Replace with **Crank-Nicolson** or exact analytical solution ($T(t) = T_{\infty} - ... e^{-t/\tau}$) for cooling prediction.
*   [ ] **Solar Gain Integration (ISO 52016)**:
    *   **Finding**: Current heat loss calculation ignores solar gains, leading to over-heating on sunny days.
    *   **Goal**: Integrate `sun.sun` azimuth and elevation (or pyranometer sensors) into the energy balance equation: $Q_{loss} = U \cdot A \cdot \Delta T - Q_{solar}$.

### Medium Priority (Model Quality)
*   [ ] **Deadtime Curve Fit**:
    *   **Finding**: Linear extrapolation for deadtime determination is mathematically incorrect for exponential heating curves.
    *   **Goal**: Implement non-linear curve fitting (Newton-Raphson) to find inflection points accurately without `scipy`.
*   [ ] **Thermodynamic Cutoff**:
    *   **Finding**: Hard 0.5K cutoff in `calculate_coast_duration` is arbitrary.
    *   **Goal**: Implement `min_delta` proportional to sensor resolution/noise floor dynamically.
*   [ ] **Cluster Validation**:
    *   **Finding**: `MIN_CLUSTER_POINTS = 3` lacks statistical rigor.
    *   **Goal**: Implement **Silhouette Score** or Davies-Bouldin-Index to validate clusters before accepting them as patterns.

    *   **Goal**: Implement **Silhouette Score** or Davies-Bouldin-Index to validate clusters before accepting them as patterns.

### Low Priority (UX & Polish)
*   [ ] **Direct Climate Control (Opt-in)**:
    *   **Finding**: Users expect simple "Turn on Heat" logic without external automation.
    *   **Goal**: Add option to directly control `climate.set_temperature` via the integration.
*   [ ] **UX Overhaul**:
    *   **Goal**: Clean up Config Flow, rename confusing attributes (e.g. `switch` -> `sensor`?), add Tooltips.
*   [ ] **Official Blueprints**:
    *   **Finding**: Users need Plug & Play.
    *   **Goal**: Move blueprints into the repo (`blueprints/`) to ensure version compatibility.
*   [ ] **First-Class Sensors**:
    *   **Finding**: Attributes in `sensor.status` are hard to graph.
    *   **Goal**: Expose `next_start_time`, `predicted_duration`, `next_departure` as separate sensors (default disabled?).
