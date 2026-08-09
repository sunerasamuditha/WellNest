import sys
import os
from typing import Dict, Any

# Ensure parent directory is in path for easy importing
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_servers.vitals_server import get_resident_vitals, get_gait_trend, get_resident_details

def get_resident_vitals_tool(resident_id: str) -> str:
    """
    Retrieve real-time camera-free vital signs and sensory telemetry from ambient radar sensors.
    Returns a formatted string description of current vitals, baselines, and deviations.
    """
    try:
        if not resident_id:
            return "Error: resident_id must be provided."
            
        res = get_resident_vitals(resident_id)
        if "error" in res:
            return f"Error fetching vitals: {res['error']}"
        
        tel = res["telemetry"]
        base = res["baselines"]
        
        return (
            f"### Ambient Vital Signs for {res['resident_name']} ({resident_id})\n"
            f"- **Gait Speed:** {tel['gait_speed_ms']} m/s (Baseline: {base['gait_speed_ms']} m/s | Change: {res['gait_change_percent']}%)\n"
            f"- **Blood Pressure:** {tel['bp_systolic']}/{tel['bp_diastolic']} mmHg (Baseline: {base['bp_systolic']}/{base['bp_diastolic']} mmHg | Systolic Change: {res['bp_systolic_change_percent']}%)\n"
            f"- **Heart Rate:** {tel['heart_rate_bpm']} bpm (Baseline: {base['heart_rate_bpm']} bpm)\n"
            f"- **Sleep Duration:** {tel['sleep_hours']} hours (Baseline: {base['sleep_hours']} hours)\n"
            f"- **Room Occupancy:** Currently in {tel['room_occupancy'].replace('_', ' ').title()}\n"
            f"- **Overall Status:** {res['status']}"
        )
    except Exception as e:
        return f"Tool Execution Error (get_resident_vitals): {str(e)}"

def get_gait_trend_tool(resident_id: str) -> str:
    """
    Retrieve historical 5-day gait speed trend in m/s to analyze gradual physical degradation.
    """
    try:
        if not resident_id:
            return "Error: resident_id must be provided."
            
        res = get_gait_trend(resident_id)
        if "error" in res:
            return f"Error fetching gait history: {res['error']}"
        
        history_str = " -> ".join([f"{speed} m/s" for speed in res["gait_speed_history_ms"]])
        return (
            f"### 5-Day Gait Velocity Trend for {resident_id}\n"
            f"- **History:** {history_str}\n"
            f"- **Total Velocity Change:** {res['total_gait_change_percent']}%\n"
            f"- **Gait Quality Verdict:** {res['verdict']}"
        )
    except Exception as e:
        return f"Tool Execution Error (get_gait_trend): {str(e)}"

def get_resident_details_tool(resident_id: str) -> str:
    """
    Retrieve resident demographic information, medical conditions, and active medications.
    """
    try:
        if not resident_id:
            return "Error: resident_id must be provided."
            
        res = get_resident_details(resident_id)
        if "error" in res:
            return f"Error fetching details: {res['error']}"
        
        meds_list = []
        for med in res.get("medications", []):
            meds_list.append(
                f"- **{med['name']}** ({med['brand_name']}): {med['dose']} {med['frequency']} (Started: {med['started_date']}) - Purpose: {med['purpose']}"
            )
        meds_str = "\n".join(meds_list)
        
        return (
            f"### Profile: {res['name']} (Age {res['age']})\n"
            f"- **Active Conditions:** {', '.join(res['conditions'])}\n"
            f"- **Current Prescription Medications:**\n{meds_str}"
        )
    except Exception as e:
        return f"Tool Execution Error (get_resident_details): {str(e)}"

if __name__ == "__main__":
    print(get_resident_details_tool("martha_001"))
    print(get_resident_vitals_tool("martha_001"))
    print(get_gait_trend_tool("martha_001"))
