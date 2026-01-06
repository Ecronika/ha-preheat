from datetime import datetime, timedelta, timezone

# Constants
predicted_duration = 126.0
buffer_minutes = 10.0
earliest_minutes = 0.0

# Timestamps from CSV (UTC)
# Start Time calculated in CSV: 01:57 UTC
# Current Time sample: 02:00 UTC
# Event Time from CSV: 04:13 UTC

now = datetime.fromisoformat("2026-01-05T02:00:00+00:00")
next_event = datetime.fromisoformat("2026-01-05T04:13:00+00:00")

def check_logic():
    print(f"Now: {now}")
    print(f"Event: {next_event}")
    
    # 1. Calc Start Time
    start_time_raw = next_event - timedelta(minutes=predicted_duration + buffer_minutes)
    print(f"Calculated Start Raw: {start_time_raw}")
    
    # 2. Earliest Limit
    earliest_min = earliest_minutes
    earliest_dt = next_event.replace(hour=0, minute=0, second=0) + timedelta(minutes=earliest_min)
    print(f"Earliest Limit: {earliest_dt}")
    
    start_time = start_time_raw
    if start_time < earliest_dt:
        print("Clamping to Earliest!")
        start_time = earliest_dt
    
    print(f"Final Start Time: {start_time}")
    
    # 3. Check Trigger
    should_start = False
    if start_time <= now < next_event:
        should_start = True
        print("TRIGGER: YES")
    else:
        print("TRIGGER: NO")
        
    return should_start

check_logic()
