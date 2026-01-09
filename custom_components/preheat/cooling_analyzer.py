"""Cooling Analyzer to learn thermal time constant (tau) for Optimal Stop."""
from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime
from typing import NamedTuple

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

class CoolingSegment(NamedTuple):
    start_time: datetime
    end_time: datetime
    start_temp: float
    end_temp: float
    avg_outdoor: float
    samples: int

class CoolingAnalyzer:
    """Analyzes historical data to find the cooling time constant (tau)."""
    
    def __init__(self):
        self._buffer = [] # List of (dt, t_in, t_out, is_heating)
        self.learned_tau = 4.0 # Default fallback (hours)
        self.confidence = 0.0  # 0.0 - 1.0
        self.sample_count = 0
        
    def add_data_point(self, dt: datetime, t_in: float, t_out: float, is_heating: bool, window_open: bool = False):
        """Streaming input of data points."""
        # If heating or window open, we shouldn't use this for cooling analysis *directly*,
        # but we need to track segments. 
        # Actually, if heating=True, the cooling segment ends.
        
        valid_cooling = (not is_heating) and (not window_open)
        self._buffer.append({
            "dt": dt,
            "t_in": t_in,
            "t_out": t_out,
            "valid": valid_cooling
        })
        
        # Prune buffer (keep last 24h?)
        # For a proper analyzer, we normally process completed segments.
        # This simple version will just keep a reasonable buffer window.
        cutoff = dt - timedelta(hours=24)
        while self._buffer and self._buffer[0]["dt"] < cutoff:
            self._buffer.pop(0)
            
    def analyze(self) -> dict:
        """
        Trigger analysis of the buffer.
        Returns debug stats.
        """
        segments = self._extract_segments()
        if not segments:
            return {"status": "no_segments"}
            
        # Fit tau for each segment or global?
        # Better: Fit one regression over all valid segments combined? 
        # Or average the partial taus?
        # Physics: slope should be constant.
        
        taus = []
        confidences = []
        total_samples = 0
        
        for seg in segments:
            tau, r2, mae, samples = self._fit_segment(seg)
            if tau and r2 > 0.5: # Loose filter
                # Sanity check tau
                if 0.5 < tau < 48.0:
                    taus.append(tau)
                    confidences.append(self._calc_confidence(samples, r2, mae))
                    total_samples += samples

        if not taus:
             return {"status": "no_valid_fits", "samples": total_samples}
             
        # Weighted average of Taus
        # Weight by confidence
        weighted_sum = sum(t * c for t, c in zip(taus, confidences))
        total_conf = sum(confidences)
        
        if total_conf > 0:
            final_tau = weighted_sum / total_conf
            # Boost confidence by number of segments/coverage?
            # User formula: min(samples/80, 1.0) was for single fit.
            # Here we have aggregate.
            
            # Simple aggregate confidence
            avg_confidence = total_conf / len(confidences)
            
            # Update State
            # Gate: Only update if high confidence?
            # User Logic: Gate > 60%
            if avg_confidence > 0.6 and total_samples > 60: # 60 mins total
                
                # Action 1.2: Model Stability Check for Tau
                old_tau = self.learned_tau
                change = abs(final_tau - old_tau) / old_tau
                
                if change > 0.2:
                    limit = old_tau * 0.2
                    clamped_tau = old_tau + limit if final_tau > old_tau else old_tau - limit
                    _LOGGER.warning("Tau Model Instability! Jump %.2fh->%.2fh (%.1f%%). Clamped to %.2fh",
                                   old_tau, final_tau, change*100, clamped_tau)
                    final_tau = clamped_tau
                    # Confidence Penalty: Don't set self.confidence to full value?
                    # Or keep confidence but acknowledge value is capped.
                    avg_confidence *= 0.8 # Penalty
                
                self.learned_tau = final_tau
                self.confidence = avg_confidence
                _LOGGER.info("CoolingAnalyzer learned new Tau: %.2fh (Conf: %.1f%%)", final_tau, avg_confidence*100)
            
            return {
                "tau": final_tau, 
                "confidence": avg_confidence, 
                "segments": len(taus), 
                "total_samples": total_samples
            }
            
        return {"status": "low_confidence"}

    def _extract_segments(self) -> list[list[dict]]:
        """Slice buffer into continuous valid cooling blocks."""
        segments = []
        current_segment = []
        
        for pt in self._buffer:
            if pt["valid"]:
                current_segment.append(pt)
            else:
                if len(current_segment) > 60: # Min 60 mins (assuming 1 pt/min or similar)
                    segments.append(current_segment)
                current_segment = []
                
        # Trailing segment
        if len(current_segment) > 60:
             segments.append(current_segment)
             
        return segments

    def _fit_segment(self, segment: list[dict]):
        """
        Fit ln(T_in - T_out) = -t/tau + C
        y = ln(delta_T)
        x = t (hours)
        Slope m = -1/tau
        """
        # Data Prep & Filtering
        x_data = [] # hours relative to start
        y_data = [] # ln(delta)
        
        start_time = segment[0]["dt"]
        
        # Calculate T_out_eff (Max of T_out over segment? Or simple Avg?)
        # User Spec: Learning Phase uses max(T_out, T_floor). 
        # Here we just use per-point T_out, or segment average?
        # Physics is instantaneous. But fitting linear regression assumes constant T_out (or diff).
        # Standard approach: y = ln(T_in - T_out_avg).
        
        t_outs = [p["t_out"] for p in segment]
        avg_out = sum(t_outs) / len(t_outs)
        
        # Guard: Check trend. If T_in is rising, reject.
        if segment[-1]["t_in"] > segment[0]["t_in"]:
             return None, 0, 0, 0
        
        for pt in segment:
            delta = pt["t_in"] - avg_out
            if delta < 0.3: continue # Validity constraint
            
            try:
                val = math.log(delta)
                dt_hours = (pt["dt"] - start_time).total_seconds() / 3600.0
                x_data.append(dt_hours)
                y_data.append(val)
            except ValueError:
                continue
                
        if len(x_data) < 20: return None, 0, 0, 0
        
        # Robust Regression: Trim Outliers (Top/Bottom 10% of residuals? Or just raw ?)
        # Hard to trim residuals before fitting.
        # Simple approach: Trim y_data top/bottom 5% (extreme deltas?)
        # Better: Basic Least Squares
        
        slope, intercept, r2 = self._linear_regression(x_data, y_data)
        
        if slope >= 0: return None, 0, 0, 0 # Heating or steady
        
        tau = -1.0 / slope
        
        # Calculate MAE
        # prediction = slope*x + intercept
        errors = [abs(y - (slope*x + intercept)) for x, y in zip(x_data, y_data)]
        mae = statistics.median(errors) if errors else 1.0
        
        # Transform MAE back to Temp domain? 
        # ln(dt) error of 0.1 => dt error of ~10%. 
        # For now, use raw log-domain MAE or approximation.
        # User asked for MAE < 0.2°C. That is in Temp domain.
        # Temp_pred = T_out + exp(slope*x + intercept)
        # We should compute Temp MAE.
        
        temp_errors = []
        for i, pt in enumerate(segment[:len(x_data)]): # Match indices
             # Re-evaluate logic: x_data was potentially filtered.
             # Just iterate fitted data
             pred_log = slope * x_data[i] + intercept
             pred_delta = math.exp(pred_log)
             actual_delta = math.exp(y_data[i])
             temp_errors.append(abs(actual_delta - pred_delta))
             
        temp_mae = statistics.median(temp_errors) if temp_errors else 10.0
        
        return tau, r2, temp_mae, len(x_data)

    def _linear_regression(self, x, y):
        """Simple OLS."""
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi*yi for xi, yi in zip(x, y))
        sum_xx = sum(xi*xi for xi in x)
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0: return 0, 0, 0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # R2
        y_mean = sum_y / n
        ss_tot = sum((yi - y_mean)**2 for yi in y)
        ss_res = sum((yi - (slope*xi + intercept))**2 for xi, yi in zip(x, y))
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        return slope, intercept, r2

    def _calc_confidence(self, samples, r2, mae):
        """
        C = min(samples/80, 1.0) * clamp((R2-0.6)/0.3) * clamp((0.2-MAE)/0.2)
        """
        # Samples (minutes)
        c_samples = min(samples / 80.0, 1.0)
        
        # R2
        c_r2 = max(0.0, min(1.0, (r2 - 0.6) / 0.3))
        
        # MAE
        c_mae = max(0.0, min(1.0, (0.2 - mae) / 0.2))
        
        return c_samples * c_r2 * c_mae
from datetime import timedelta
