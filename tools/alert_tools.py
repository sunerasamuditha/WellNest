import os
import json
import datetime
import uuid
from typing import Dict, Any, List
from services.gcp_service import get_alerts_db, save_alert_db, clear_alerts_db, publish_alert_event

VALID_SEVERITIES = ["INFO", "ADVISORY", "WARNING", "CRITICAL"]

def log_alert_to_timeline(resident_id: str, resident_name: str, severity: str, message: str, actions: list, correlation: str = None) -> dict:
    """
    Format a structured health alert, log it to Firestore (or local timeline),
    publish it over Cloud Pub/Sub, and return the alert dictionary.
    Strictly emoji-free logs.
    """
    try:
        # Input Validation
        if not resident_id or not isinstance(resident_id, str):
            raise ValueError("resident_id must be a non-empty string.")
        if not resident_name or not isinstance(resident_name, str):
            raise ValueError("resident_name must be a non-empty string.")
        if severity.upper() not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {VALID_SEVERITIES}.")
        if not message or not isinstance(message, str):
            raise ValueError("message must be a non-empty string.")
        if not isinstance(actions, list):
            raise ValueError("actions must be a list of strings.")

        # Create timestamp
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        
        alert = {
            "id": f"alert_{uuid.uuid4().hex[:12]}",
            "timestamp": timestamp,
            "resident_id": resident_id,
            "resident_name": resident_name,
            "severity": severity.upper(),
            "message": message,
            "actions": actions,
            "correlation": correlation,
            "acknowledged": False
        }
        
        # Persist alert in Firestore / file
        save_alert_db(alert)
        
        # Broadcast event via Pub/Sub
        publish_alert_event(alert)
                
        return alert
    except Exception as e:
        return {"error": f"Failed to log alert: {str(e)}"}

def escalate_to_human_tool(resident_id: str, resident_name: str, reason: str, urgency: str) -> dict:
    """
    Trigger an immediate escalation to a human caregiver or medical professional.
    Used by the Cognitive Companion when a resident exhibits severe confusion, distress, or critical symptoms during a conversation.
    urgency must be "HIGH" or "CRITICAL".
    """
    try:
        if not resident_id or not resident_name or not reason:
            raise ValueError("resident_id, resident_name, and reason are required.")
        if urgency.upper() not in ["HIGH", "CRITICAL"]:
            raise ValueError("urgency must be 'HIGH' or 'CRITICAL'.")

        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        escalation_event = {
            "id": f"escalation_{uuid.uuid4().hex[:12]}",
            "timestamp": timestamp,
            "resident_id": resident_id,
            "resident_name": resident_name,
            "severity": "CRITICAL" if urgency.upper() == "CRITICAL" else "WARNING",
            "message": f"HUMAN ESCALATION REQUESTED: {reason}",
            "actions": ["Immediate human check-in required", "Review recent conversation logs"],
            "correlation": "Triggered via Cognitive Companion interaction",
            "acknowledged": False
        }

        save_alert_db(escalation_event)
        publish_alert_event(escalation_event)
        
        return {"status": "success", "message": f"Escalation logged and routed successfully for {resident_name}."}
    except Exception as e:
        return {"error": f"Failed to escalate: {str(e)}"}

def get_alerts_timeline() -> list:
    """Retrieve all logged alerts from the timeline."""
    try:
        return get_alerts_db()
    except Exception as e:
        return [{"error": f"Failed to retrieve alerts: {str(e)}"}]

def clear_alerts_timeline():
    """Clear all alerts for a fresh simulation run."""
    try:
        clear_alerts_db()
    except Exception as e:
        print(f"Failed to clear alerts: {str(e)}")

if __name__ == "__main__":
    clear_alerts_timeline()
    log_alert_to_timeline(
        resident_id="martha_001",
        resident_name="Martha Reynolds",
        severity="WARNING",
        message="Gait speed decline of 15.3% detected over 5 days. Elevated blood pressure of 142/88 mmHg.",
        actions=["Check on Martha immediately", "Advise her to drink water and stand slowly", "Request primary care physician medication review"],
        correlation="Recently started Metoprolol Succinate 50mg (Beta-blocker) on 2026-05-23. Common side effects include orthostatic hypotension."
    )
    print(get_alerts_timeline())
