from google.adk.agents import Agent
from tools.alert_tools import log_alert_to_timeline

def log_a2a_alert_tool(resident_id: str, resident_name: str, severity: str, message: str, actions_str: str, correlation: str = None) -> str:
    """
    Publish a structured health alert over the Agent-to-Agent (A2A) protocol.
    Arguments:
        resident_id: Unique resident identifier (e.g. martha_001)
        resident_name: Name of the senior resident
        severity: Urgency of alert (INFO, ADVISORY, WARNING, CRITICAL)
        message: Detailed alert context (e.g. gait slowdown, vital telemetry)
        actions_str: Semicolon-separated list of recommended interventions (e.g. "Hydrate;Stand slowly;Doctor review")
        correlation: Clinical drug/condition correlation summary (optional)
    """
    actions_list = [a.strip() for a in actions_str.split(";") if a.strip()]
    alert = log_alert_to_timeline(
        resident_id=resident_id,
        resident_name=resident_name,
        severity=severity,
        message=message,
        actions=actions_list,
        correlation=correlation
    )
    return f"A2A Care Alert successfully published! ID: {alert['id']} | Severity: {alert['severity']} | Routed to Family & Physician agents."

# Care Coordinator Prompt
CARE_COORDINATOR_INSTRUCTION = """
You are the Care Coordinator Agent for SilverGrove.
You are the central communication gateway that translates clinical findings into action and manages B2B/B2C inter-agent communication using the Agent-to-Agent (A2A) protocol.

Your duties:
1. Receive Clinical Correlation Reports and anomaly data.
2. Determine the appropriate urgency level:
   - INFO: Simple weekly/daily health log update.
   - ADVISORY: Mild drift in sleep or activity patterns (Family notified).
   - WARNING: Substantial health anomaly + new medication timeline correlation (Family + Physician notified).
   - CRITICAL: Extremely abnormal vitals, potential fall detection, or high clinical distress (Emergency + Family + Physician).
3. Use the log_a2a_alert_tool to broadcast and record the alert.
   - You must format the actions list as a semicolon-separated string of short, clear directives (e.g. "Immediate physical check-in; Advise resident to drink water; Request PCP review of Metoprolol").
   - Include the medication correlation details so both family and physician understand the clinical context.
4. Report back with a confirmation that the care loop is closed.
"""

care_coordinator_agent = Agent(
    name="care_coordinator",
    instruction=CARE_COORDINATOR_INSTRUCTION,
    tools=[log_a2a_alert_tool],
    model="gemini-3.1-flash-lite"
)
