"""Tests for PatternDetector v3 (Multi-Modal)."""
import pytest
from datetime import date, timedelta
from custom_components.preheat.patterns import PatternDetector, ArrivalCluster, PatternResult

@pytest.fixture
def detector():
    return PatternDetector()

def test_find_clusters_simple(detector):
    # Case: Single cluster
    history = [
        (date(2024, 1, 1), 600), # 10:00
        (date(2024, 1, 2), 610),
        (date(2024, 1, 3), 590),
    ]
    clusters = detector.find_clusters(history)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.time_minutes == 600
    assert c.count == 3
    assert c.label == "regular"

def test_find_clusters_multimodal(detector):
    # Case: Early (06:00=360) and Late (14:00=840)
    history = []
    # 5 early points
    for i in range(5):
        history.append((date(2024, 1, i+1), 360 + i*2))
    # 5 late points
    for i in range(5):
        history.append((date(2024, 1, i+10), 840 + i*2))
        
    clusters = detector.find_clusters(history)
    assert len(clusters) == 2
    assert clusters[0].label == "early"
    assert clusters[1].label == "late"
    assert clusters[0].count == 5
    assert clusters[1].count == 5

def test_predict_single_mode_high_confidence(detector):
    # Case: always 08:00
    history = []
    start_date = date(2024, 1, 1)
    for i in range(10): # 10 days
        d = start_date + timedelta(days=i)
        history.append((d, 480)) # 08:00
        
    res = detector.predict(history, start_date + timedelta(days=10))
    assert res.prediction == "regular" # or regular if only 1 mode
    assert res.pattern_type == "single_mode"
    assert res.confidence == 1.0
    assert res.fallback_used is False

def test_predict_week_parity(detector):
    # Case: Odd weeks = 06:00 (360), Even weeks = 14:00 (840)
    history = []
    # Generate 4 weeks of data (Mon-Fri)
    # Week 1 (Odd): Early
    # Week 2 (Even): Late
    # Week 3 (Odd): Early
    # Week 4 (Even): Late
    
    # 2024-01-01 is Monday, Week 1 (Odd)
    start_date = date(2024, 1, 1)
    
    for week in range(4):
        for day in range(5): # Mon-Fri
            d = start_date + timedelta(weeks=week, days=day)
            iso_week = d.isocalendar()[1]
            
            if iso_week % 2 == 1:
                t = 360 # 06:00
            else:
                t = 840 # 14:00
            
            history.append((d, t))
            
    # Predict for Next Week (Week 5, Odd) -> Should be Early
    target_date = start_date + timedelta(weeks=4) # Week 5
    res = detector.predict(history, target_date)
    
    assert res.pattern_type == "weekly_parity"
    assert res.prediction == "early"
    assert res.prediction_time == 360
    assert res.confidence >= 0.8
    assert res.fallback_used is False

def test_fallback_noise(detector):
    # Case: Random noise
    history = [
        (date(2024, 1, 1), 100),
        (date(2024, 1, 2), 500),
        (date(2024, 1, 3), 900),
        (date(2024, 1, 4), 200),
    ]
    # Clusters might filter them out as noise (<3 points)
    # So modes might be empty?
    res = detector.predict(history, date(2024, 1, 5))
    if not res.modes_found:
        assert res.prediction == "no_clusters"
        assert res.fallback_used is True
    else:
        # If any cluster found (e.g. if I lowered threshold), it should use fallback
        assert res.pattern_type == "none"
        assert res.fallback_used is True
