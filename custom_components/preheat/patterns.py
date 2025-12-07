"""Pattern recognition logic for Preheat."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

@dataclass
class ArrivalCluster:
    """Represents a cluster of arrival times."""
    time_minutes: int
    count: int
    last_seen_days_ago: int = 0
    confidence: float = 1.0

class PatternDetector:
    """Detects patterns in arrival history."""

    def __init__(self) -> None:
        """Initialize."""
        pass

    def find_clusters(self, timestamps: list[int], max_gap: int = 45) -> list[ArrivalCluster]:
        """
        Group timestamps into clusters using a simplified 1D clustering (DBSCAN-like).
        timestamps: list of minutes from midnight (0-1440).
        max_gap: max minutes between points to be considered same cluster.
        """
        if not timestamps:
            return []

        sorted_times = sorted(timestamps)
        clusters: list[list[int]] = []
        current_cluster: list[int] = []

        for t in sorted_times:
            if not current_cluster:
                current_cluster.append(t)
                continue
            
            # Check distance to ANY point in current cluster (single linkage logic for this simple case)
            # Or centroid? Let's stick to "distance to last point" for 1D.
            if t - current_cluster[-1] <= max_gap:
                current_cluster.append(t)
            else:
                clusters.append(current_cluster)
                current_cluster = [t]
        
        if current_cluster:
            clusters.append(current_cluster)

        # Handle Day Wrap (Merge last and first if close)
        if len(clusters) > 1:
            first = clusters[0]
            last = clusters[-1]
            # Distance from Last Point of Last Cluster -> First Point of First Cluster
            gap = (1440 - last[-1]) + first[0]
            if gap <= max_gap:
                # Merge last into first (conceptually simpler to keep sorted order? No, circular.)
                # Actually, let's merge into a new 'Late Night' cluster or just combine.
                # If we average them, we need to handle the wrap logic for average.
                # Simple approach: Treat first cluster as "Next Day" for averaging?
                # e.g. 10 (00:10) becomes 1450.
                extended_first = [t + 1440 for t in first]
                merged = last + extended_first
                
                # Replace last and first
                clusters.pop(0)
                clusters.pop(-1)
                clusters.append(merged)

        results = []
        for c in clusters:
            # Average calculation with wrap support
            # If any val > 1440 (from merge), we normalize average
            total = sum(c)
            avg = total / len(c)
            if avg >= 1440: avg -= 1440
            
            results.append(ArrivalCluster(time_minutes=int(avg), count=len(c)))
        
        return results

    def detect_shift_pattern(self, daily_history: dict[str, list[int]]) -> str | None:
        """
        Analyze daily history for shift patterns.
        daily_history: dict of 'YYYY-MM-DD' -> [minutes, ...]
        Returns: 'check_calendar' or specific prediction logic ID.
        (Placeholder for v1 implementation)
        """
        # Complex shift detection requires analysing sequences.
        # For now, we return null, letting the Planner rely on 'Recent Clusters'.
        return None

    def is_anomaly(self, minute: int, clusters: list[ArrivalCluster], tolerance: int = 60) -> bool:
        """Check if a time is an anomaly compared to known clusters."""
        if not clusters:
            return False # No history = no anomaly
        
        for c in clusters:
            if abs(minute - c.time_minutes) <= tolerance:
                return False
        return True
