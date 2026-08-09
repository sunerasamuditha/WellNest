import os
import sys
import json
import time
from datetime import datetime

# Ensure parent directory is in path for easy importing
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ALERTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alerts_timeline.json")

def listen_for_physician_alerts():
    """
    Simulates a Primary Care Physician A2A Client listening for alerts.
    Polls the local event bus (alerts_timeline.json) for new clinical alerts.
    Filters out INFO level alerts, prioritizing WARNING and CRITICAL.
    """
    print("==================================================")
    print(" SilverGrove A2A Client: PHYSICIAN CLINIC ACTIVE  ")
    print(" Connected to EHR integration event bus...        ")
    print("==================================================\n")
    
    seen_alerts = set()
    
    # Pre-populate seen alerts so we only react to NEW ones
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, "r") as f:
                alerts = json.load(f)
                for alert in alerts:
                    seen_alerts.add(alert.get("id"))
        except Exception:
            pass

    while True:
        try:
            if os.path.exists(ALERTS_FILE):
                with open(ALERTS_FILE, "r") as f:
                    alerts = json.load(f)
                    for alert in alerts:
                        alert_id = alert.get("id")
                        if alert_id not in seen_alerts:
                            seen_alerts.add(alert_id)
                            
                            severity = alert.get("severity", "UNKNOWN")
                            if severity in ["WARNING", "CRITICAL"]:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] [ESCALATION] CLINICAL ESCALATION RECEIVED")
                                print(f"Patient ID:  {alert.get('resident_id', 'Unknown')} ({alert.get('resident_name', 'Unknown')})")
                                print(f"Severity:    {severity}")
                                print(f"Findings:    {alert.get('message', '')}")
                                if alert.get("correlation"):
                                    print(f"Correlation: {alert.get('correlation')}")
                                print("--- Added to physician triage queue ---\n")
            
            time.sleep(2) # Poll every 2 seconds
        except KeyboardInterrupt:
            print("\nShutting down Physician Clinic A2A Listener.")
            break
        except Exception as e:
            print(f"Error reading EHR event bus: {e}")
            time.sleep(2)

if __name__ == "__main__":
    listen_for_physician_alerts()
