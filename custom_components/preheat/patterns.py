"""Pattern recognition logic for Preheat."""
from __future__ import annotations

import logging
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

_LOGGER = logging.getLogger(__name__)

# v2.6.0 Constants
MIN_CLUSTER_POINTS = 2
MERGE_THRESHOLD_MINUTES = 60

@dataclass
class ArrivalCluster:
    """Represents a cluster of arrival times."""
    time_minutes: int
    count: int
    std_dev: float = 0.0
    label: str = "regular"  # early, mid, late

@dataclass
class PatternResult:
    """Result of pattern detection."""
    prediction: str = "unknown"  # early, late, unknown
    prediction_time: int | None = None # Calculated time
    pattern_type: str = "none" # single_mode, weekly_parity, none
    confidence: float = 0.0
    stability: float = 0.0
    fallback_used: bool = False
    modes_found: dict[str, int] = field(default_factory=dict)

class PatternDetector:
    """Detects patterns in arrival history (v2.6+)."""

    def find_clusters_v2(self, timestamps: list[int]) -> list[ArrivalCluster]:
        """Legacy V2 clustering for migration support."""
        if not timestamps:
            return []
        
        # Reuse the logic by faking tuples? No, just copy crucial part or refactor.
        # Refactoring reuse:
        return self._cluster_core(timestamps)

    def find_clusters(self, history: list[tuple[date, int]]) -> list[ArrivalCluster]:
        """
        Find clusters in v3 history (date, minutes).
        Filters noise (< 3 points) and merges close clusters.
        """
        if not history:
            return []

        # 1. Extract minutes
        all_minutes = sorted([m for _, m in history])
        return self._cluster_core(all_minutes)

    def _cluster_core(self, all_minutes: list[int]) -> list[ArrivalCluster]:
        """Core clustering logic shared by v2 and v3."""
        # 2. Simple 1D Clustering (Gap based)
        clusters: list[list[int]] = []
        current: list[int] = []
        
        for m in all_minutes:
            if not current:
                current.append(m)
                continue
            
            # Distance to cluster center (approx via last point)
            if m - current[-1] <= MERGE_THRESHOLD_MINUTES:
                current.append(m)
            else:
                clusters.append(current)
                current = [m]
        if current:
            clusters.append(current)

        # 3. Create objects and filter noise
        valid_clusters = []
        for c in clusters:
            if len(c) < MIN_CLUSTER_POINTS:
                continue
            
            avg = int(sum(c) / len(c))
            # Std deviation
            variance = sum((x - avg) ** 2 for x in c) / len(c)
            std = variance ** 0.5
            
            valid_clusters.append(ArrivalCluster(
                time_minutes=avg,
                count=len(c),
                std_dev=std
            ))
            
        # 4. Label Modes (Legacy might not need labels, but v3 does. We label anyway)
        valid_clusters.sort(key=lambda x: x.time_minutes)
        
        if len(valid_clusters) == 1:
            valid_clusters[0].label = "regular"
        elif len(valid_clusters) == 2:
            valid_clusters[0].label = "early"
            valid_clusters[1].label = "late"
        elif len(valid_clusters) >= 3:
            valid_clusters[0].label = "early"
            for i in range(1, len(valid_clusters)-1):
                valid_clusters[i].label = "mid"
            valid_clusters[-1].label = "late"
            
        return valid_clusters

    def _match_point_to_mode(self, minute: int, modes: list[ArrivalCluster]) -> ArrivalCluster | None:
        """Find the mode that explains this point."""
        best_mode = None
        min_dist = float('inf')
        
        for mode in modes:
            dist = abs(minute - mode.time_minutes)
            # Dynamic threshold logic: max(45, 2*std)
            # Simplification: use hard 60 min tolerance for matching to avoid "Unexplained"
            if dist < 60 and dist < min_dist:
                min_dist = dist
                best_mode = mode
                
        return best_mode

    def predict(self, history: list[tuple[date, int]], next_date: date) -> PatternResult:
        """
        Main entry point for v2.6 prediction.
        Analyzes history, detects pattern, returns result.
        """
        if len(history) < 4:
            return PatternResult(fallback_used=True, prediction="insufficient_data")

        # 1. Identify Modes
        modes = self.find_clusters(history)
        if not modes:
             return PatternResult(fallback_used=True, prediction="no_clusters")

        modes_dict = {m.label: m.count for m in modes}
        
        # 2. Hypothesis Testing
        # Invert History: Map date -> Mode Label
        day_map: dict[date, str] = {}
        valid_points = 0
        
        # Limit to RECENCY (last 10 points) for pattern detection
        # Note: history is expected to be already trimmed/relevant, but let's enforce it?
        # Concept says: "PATTERN_POINTS = 10: Max recent points used for evaluation."
        recent_history = history[-10:] 
        
        mode_counts = Counter()
        
        for d, m in recent_history:
            mode = self._match_point_to_mode(m, modes)
            if mode:
                day_map[d] = mode.label
                mode_counts[mode.label] += 1
                valid_points += 1
        
        if valid_points < 3:
             # Too much noise
            result = self._fallback(modes)
            result.modes_found = modes_dict
            return result

        stability = mode_counts.most_common(1)[0][1] / valid_points
        
        # --- Hypothesis A: Single Mode ---
        if stability >= 0.7:
            dominant = mode_counts.most_common(1)[0][0]
            # Backtest
            confidence = self._verify_confidence(recent_history, day_map, "single_mode", dominant)
            
            # Use it if confidence is good (or if stability is extremely high)
            if confidence >= 0.6:
                # Find the mode object
                target_mode = next(m for m in modes if m.label == dominant)
                return PatternResult(
                    prediction=dominant,
                    prediction_time=target_mode.time_minutes,
                    pattern_type="single_mode",
                    confidence=confidence,
                    stability=stability,
                    fallback_used=False,
                    modes_found=modes_dict
                )

        # --- Hypothesis B: Week Parity ---
        # Only if multiple modes exist
        if len(modes) > 1:
            # Check Odd vs Even
            odd_counts = Counter()
            even_counts = Counter()
            odd_days = 0
            even_days = 0
            
            for d, label in day_map.items():
                iso_week = d.isocalendar()[1]
                if iso_week % 2 == 1:
                    odd_counts[label] += 1
                    odd_days += 1
                else:
                    even_counts[label] += 1
                    even_days += 1
            
            if odd_days > 0 and even_days > 0:
                odd_dom = odd_counts.most_common(1)[0]
                even_dom = even_counts.most_common(1)[0]
                
                odd_ratio = odd_dom[1] / odd_days
                even_ratio = even_dom[1] / even_days
                
                # Concept condition: > 0.8 ratio for both AND different modes
                if odd_ratio >= 0.8 and even_ratio >= 0.8 and odd_dom[0] != even_dom[0]:
                    # Strong parity detected
                    target_iso = next_date.isocalendar()[1]
                    predicted_label = odd_dom[0] if target_iso % 2 == 1 else even_dom[0]
                    
                    confidence = self._verify_confidence(recent_history, day_map, "weekly_parity", 
                                                         (odd_dom[0], even_dom[0]))
                    
                    if confidence >= 0.6:
                        target_mode = next(m for m in modes if m.label == predicted_label)
                        return PatternResult(
                            prediction=predicted_label,
                            prediction_time=target_mode.time_minutes,
                            pattern_type="weekly_parity",
                            confidence=confidence,
                            stability=stability, # Stability of single mode is low here
                            fallback_used=False,
                            modes_found=modes_dict
                        )

        # 3. Fallback (Low Confidence)
        result = self._fallback(modes)
        result.stability = stability
        result.confidence = 0.0 # Failed confidence check
        result.modes_found = modes_dict
        return result

    def _verify_confidence(self, history: list[tuple[date, int]], day_map: dict[date, str], 
                          p_type: str, params: any) -> float:
        """Backtest the hypothesis against history."""
        correct = 0
        total = 0
        
        for d, m in history:
            actual_label = day_map.get(d)
            if not actual_label:
                continue # Skip noise points in verification? Or count as miss?
                # Ideally count as miss if patterns claims to explain everything.
                # But here we ignore noise.
            
            predicted = None
            if p_type == "single_mode":
                predicted = params # dominant label
            elif p_type == "weekly_parity":
                odd_label, even_label = params
                prediction_iso = d.isocalendar()[1]
                predicted = odd_label if prediction_iso % 2 == 1 else even_label
            
            if predicted == actual_label:
                correct += 1
            total += 1
            
        return correct / total if total > 0 else 0.0

    def _fallback(self, modes: list[ArrivalCluster]) -> PatternResult:
        """Pessimistic Fallback: Earliest Mode."""
        # modes are sorted by time, so [0] is earliest
        earliest = modes[0]
        return PatternResult(
            prediction=earliest.label,
            prediction_time=earliest.time_minutes,
            pattern_type="none",
            fallback_used=True
        )

    def predict_departure(self, history: list[dict]) -> tuple[int, float] | None:
        """
        Predict departure time using Quantiles (v2.8).
        History format: list of dicts with keys 'minutes', 'dst_flag'.
        Returns: (predicted_minutes, confidence) or None.
        """
        # 1. Filter
        # Exclude DST flagged entries (unreliable transitions)
        valid_minutes = [
            x["minutes"] 
            for x in history 
            if not x.get("dst_flag", False)
        ]
        
        # 2. Gate based on shared constant
        if len(valid_minutes) < MIN_CLUSTER_POINTS:
            return None # Insufficient Data
            
        # 3. Sort
        valid_minutes.sort()
        count = len(valid_minutes)
        
        # 4. Quantiles (Target P50 for prediction, P90 for Safety/Buffer?)
        # For Departure, we want to be SAFE (don't stop too early). 
        # So maybe P75 or P90?
        # Plan says: "Quantiles (P50/P90)". 
        # Let's return P50 (Expected) but calculate confidence based on spread.
        
        # Median (P50)
        p50_idx = int(0.5 * (count - 1))
        p50 = valid_minutes[p50_idx]
        
        # P90
        p90_idx = int(0.9 * (count - 1))
        p90 = valid_minutes[p90_idx]
        
        # 5. Confidence Logic
        # Calculate IQR-like spread relative to 24h
        # Tighter spread = Higher confidence
        # Spread = P90 - P10
        p10_idx = int(0.1 * (count - 1))
        p10 = valid_minutes[p10_idx]
        spread = p90 - p10
        
        # Metric: Map spread 0..120min to 1.0..0.0?
        # If spread is 0 (identical), conf = 1.0
        # If spread is 60min, conf = 0.5
        # If spread > 120min, conf = 0.0
        conf = max(0.0, 1.0 - (spread / 120.0))
        
        # Current Strategy: Return P90 as the safe "Planned Stop" to ensure comfort?
        # Or P50? 
        # If we stop at P50, 50% of time we are too early (cold).
        # We should target P90 (Conservative/Comfort bias) for heating.
        
        return p90, conf
