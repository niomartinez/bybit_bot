#!/usr/bin/env python3
"""
Quick test to verify timezone fix.
"""

import sys
from datetime import datetime
sys.path.append('src')

# Test the new timezone handling
try:
    import zoneinfo
    NYC_TZ = zoneinfo.ZoneInfo("America/New_York")
    print("✅ Using zoneinfo for timezone handling")
except ImportError:
    try:
        import pytz
        NYC_TZ = pytz.timezone("America/New_York")
        print("✅ Using pytz for timezone handling")
    except ImportError:
        import time
        if time.daylight and time.localtime().tm_isdst:
            from datetime import timezone, timedelta
            NYC_TZ = timezone(timedelta(hours=-4))  # EDT (UTC-4)
            print("⚠️ Using fallback EDT (UTC-4)")
        else:
            from datetime import timezone, timedelta
            NYC_TZ = timezone(timedelta(hours=-5))  # EST (UTC-5)
            print("⚠️ Using fallback EST (UTC-5)")

def get_nyc_time():
    return datetime.now(NYC_TZ)

if __name__ == "__main__":
    print("🕐 Timezone Fix Test")
    print("=" * 20)
    
    nyc_time = get_nyc_time()
    utc_time = datetime.utcnow()
    
    print(f"UTC Time:  {utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"NYC Time:  {nyc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"NYC Offset: {nyc_time.strftime('%z')}")
    
    # Check if we're in DST
    if hasattr(nyc_time, 'dst') and nyc_time.dst():
        print("🌞 Currently in Daylight Saving Time (EDT)")
    else:
        print("❄️ Currently in Standard Time (EST)")
    
    # Test session detection
    hour = nyc_time.hour
    minute = nyc_time.minute
    
    print(f"\nCurrent NYC Time: {hour:02d}:{minute:02d}")
    
    # Silver Bullet sessions
    sessions = [
        {"name": "London Open", "start": (3, 0), "end": (4, 0)},
        {"name": "AM Session", "start": (10, 0), "end": (11, 0)},
        {"name": "PM Session", "start": (14, 0), "end": (15, 0)}
    ]
    
    in_session = False
    current_session = None
    
    for session in sessions:
        start_hour, start_min = session["start"]
        end_hour, end_min = session["end"]
        
        start_total = start_hour * 60 + start_min
        end_total = end_hour * 60 + end_min
        current_total = hour * 60 + minute
        
        if start_total <= current_total < end_total:
            in_session = True
            current_session = session["name"]
            break
    
    if in_session:
        print(f"🎯 IN SESSION: {current_session}")
    else:
        print("⏳ Outside all sessions")
        
        # Show next session
        next_sessions = []
        for session in sessions:
            start_hour, start_min = session["start"]
            next_start_total = start_hour * 60 + start_min
            current_total = hour * 60 + minute
            
            if next_start_total > current_total:
                hours_until = (next_start_total - current_total) / 60
                next_sessions.append((session["name"], hours_until))
        
        if next_sessions:
            next_session = min(next_sessions, key=lambda x: x[1])
            print(f"Next session: {next_session[0]} in {next_session[1]:.1f} hours")
        else:
            # Next session is tomorrow
            print("Next session: London Open tomorrow at 3:00 AM") 