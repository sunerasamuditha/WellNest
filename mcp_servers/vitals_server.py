import os
import sys
import json
import random
import datetime
from mcp.server.fastmcp import FastMCP

# Ensure parent directory is in path for easy importing
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.gcp_service import get_resident_profile_db

# Initialize MCP Server
# This module serves a dual purpose:
# 1. Standalone MCP Server: Run via `python vitals_server.py` to expose tools over
#    the Model Context Protocol (stdio transport) for external agent discovery.
# 2. Direct Import: ADK agents in the local pipeline import these same functions
#    directly (via tools/vitals_tools.py) for zero-latency in-process tool calls.
mcp = FastMCP("SilverGroveVitalsServer")

# Path to residents database
DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESIDENTS_PATH = os.path.join(DATA_DIR, "data", "residents.json")

# ============================================================
# DYNAMIC SENSOR SIMULATION ENGINE
# ============================================================
# Each resident has a clinically-defined anomaly profile. On every read,
# the engine generates values with controlled random variance (+/- jitter)
# around the target anomaly values. This simulates what real ambient
# radar sensors would output -- slight variance per reading, but the
# clinical trend remains consistent and anomaly-triggering.

RESIDENT_ANOMALY_PROFILES = {
    "martha_001": {
        # Martha: Elevated BP from new Metoprolol + gait slowdown
        "heart_rate_bpm": {"target": 78, "jitter": 3},
        "bp_systolic": {"target": 142, "jitter": 4},
        "bp_diastolic": {"target": 88, "jitter": 3},
        "gait_speed_ms": {"target": 0.72, "jitter": 0.03},
        "sleep_hours": {"target": 5.4, "jitter": 0.4},
        "room_options": ["bedroom", "living_room", "hallway"],
        "gait_decline_severity": 0.15  # 15% decline from baseline
    },
    "arthur_002": {
        # Arthur: Stable vitals, minor sleep reduction (no anomaly)
        "heart_rate_bpm": {"target": 69, "jitter": 2},
        "bp_systolic": {"target": 122, "jitter": 3},
        "bp_diastolic": {"target": 75, "jitter": 2},
        "gait_speed_ms": {"target": 0.64, "jitter": 0.02},
        "sleep_hours": {"target": 6.2, "jitter": 0.3},
        "room_options": ["living_room", "bedroom", "kitchen"],
        "gait_decline_severity": 0.02  # Stable, ~2% natural variance
    },
    "clara_003": {
        # Clara: Parkinson's gait freeze + orthostatic hypotension (low BP)
        "heart_rate_bpm": {"target": 76, "jitter": 3},
        "bp_systolic": {"target": 98, "jitter": 4},
        "bp_diastolic": {"target": 60, "jitter": 3},
        "gait_speed_ms": {"target": 0.42, "jitter": 0.03},
        "sleep_hours": {"target": 4.8, "jitter": 0.4},
        "room_options": ["hallway", "bedroom", "bathroom"],
        "gait_decline_severity": 0.28  # Severe 28% decline (Parkinson's shuffle)
    },
    "james_004": {
        # James: Post-op opioid sedation + severe gait collapse
        "heart_rate_bpm": {"target": 92, "jitter": 4},
        "bp_systolic": {"target": 138, "jitter": 4},
        "bp_diastolic": {"target": 84, "jitter": 3},
        "gait_speed_ms": {"target": 0.35, "jitter": 0.03},
        "sleep_hours": {"target": 8.5, "jitter": 0.5},
        "room_options": ["living_room", "bedroom"],
        "gait_decline_severity": 0.50  # Extreme 50% decline (post-op)
    }
}


def _generate_live_telemetry(resident_id: str) -> dict:
    """
    Generate dynamic vital sign readings with controlled clinical variance.
    Each call produces slightly different values, simulating real-time
    ambient radar sensor output.
    """
    profile = RESIDENT_ANOMALY_PROFILES.get(resident_id)
    if not profile:
        return None

    def jittered(spec):
        return round(spec["target"] + random.uniform(-spec["jitter"], spec["jitter"]), 2)

    # Integer vitals (heart rate, BP) are rounded to whole numbers
    hr = int(jittered(profile["heart_rate_bpm"]))
    bp_sys = int(jittered(profile["bp_systolic"]))
    bp_dia = int(jittered(profile["bp_diastolic"]))
    gait = round(jittered(profile["gait_speed_ms"]), 2)
    sleep = round(jittered(profile["sleep_hours"]), 1)
    room = random.choice(profile["room_options"])

    return {
        "heart_rate_bpm": hr,
        "bp_systolic": bp_sys,
        "bp_diastolic": bp_dia,
        "gait_speed_ms": gait,
        "sleep_hours": sleep,
        "room_occupancy": room,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }


def _generate_gait_history(resident_id: str, baseline_gait: float) -> list:
    """
    Generate a dynamic 5-day gait speed trend that shows realistic
    day-to-day variance while maintaining the overall clinical trend.
    The decline severity is defined per resident anomaly profile.
    """
    profile = RESIDENT_ANOMALY_PROFILES.get(resident_id)
    if not profile:
        return None

    decline = profile["gait_decline_severity"]
    current_target = baseline_gait * (1.0 - decline)
    history = []

    for day in range(5):
        # Interpolate from baseline (day 0) to current target (day 4)
        t = day / 4.0
        interpolated = baseline_gait + t * (current_target - baseline_gait)
        # Add small daily jitter (+/- 0.02 m/s)
        jittered_val = interpolated + random.uniform(-0.02, 0.02)
        history.append(round(max(0.10, jittered_val), 2))

    return history


def load_residents():
    try:
        with open(RESIDENTS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

_FROZEN_VITALS = {}
_LAST_GENERATED = {}

def set_vitals_frozen(resident_id: str, freeze: bool):
    if freeze:
        if resident_id in _LAST_GENERATED:
            _FROZEN_VITALS[resident_id] = _LAST_GENERATED[resident_id]
    else:
        if resident_id in _FROZEN_VITALS:
            del _FROZEN_VITALS[resident_id]

@mcp.tool()
def get_resident_details(resident_id: str) -> dict:
    """Retrieve full details of a resident (name, age, active conditions, medications)."""
    return get_resident_profile_db(resident_id)

@mcp.tool()
def get_resident_vitals(resident_id: str) -> dict:
    """Retrieve real-time camera-free vital signs and sensory telemetry from ambient radar sensors."""
    if resident_id in _FROZEN_VITALS:
        vitals = _FROZEN_VITALS[resident_id]
    else:
        vitals = _generate_live_telemetry(resident_id)
        _LAST_GENERATED[resident_id] = vitals

    if not vitals:
        return {"error": f"No vital telemetry available for resident {resident_id}."}
    
    profile = get_resident_profile_db(resident_id)
    baselines = profile.get("baselines", {})
    
    # Calculate percentage change for critical metrics
    gait_speed = vitals["gait_speed_ms"]
    gait_baseline = baselines.get("gait_speed_ms", 1.0)
    gait_change = ((gait_speed - gait_baseline) / gait_baseline) * 100
    
    bp_sys = vitals["bp_systolic"]
    bp_sys_baseline = baselines.get("bp_systolic", 120)
    bp_sys_change = ((bp_sys - bp_sys_baseline) / bp_sys_baseline) * 100
    
    return {
        "resident_name": profile.get("name", "Unknown"),
        "telemetry": vitals,
        "baselines": baselines,
        "gait_change_percent": round(gait_change, 1),
        "bp_systolic_change_percent": round(bp_sys_change, 1),
        "status": "ANOMALY_DETECTED" if abs(gait_change) >= 15.0 or bp_sys >= 140 or bp_sys <= 100 else "NORMAL"
    }

@mcp.tool()
def get_gait_trend(resident_id: str) -> dict:
    """Get historical 5-day gait speed trend in m/s for gait degradation analysis."""
    profile = get_resident_profile_db(resident_id)
    baselines = profile.get("baselines", {})
    baseline_gait = baselines.get("gait_speed_ms", 0.85)

    history = _generate_gait_history(resident_id, baseline_gait)
    if not history:
        return {"error": f"No historical gait data for resident {resident_id}."}
    
    change_pct = ((history[-1] - history[0]) / history[0]) * 100
    return {
        "resident_id": resident_id,
        "gait_speed_history_ms": history,
        "total_gait_change_percent": round(change_pct, 1),
        "verdict": "DEGRADATION_DETECTED" if change_pct <= -15.0 else "STABLE"
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
