import os
import sys
import json
import uuid
import time
import asyncio
import hashlib
import requests
from dataclasses import dataclass, field, asdict
from dotenv import load_dotenv

# Ensure local path is configured
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environmental variables
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from agents.sensory_guardian import sensory_guardian_agent
from agents.cognitive_companion import cognitive_companion_agent
from agents.medical_compliance import medical_compliance_agent
from agents.care_coordinator import care_coordinator_agent
from tools.trace_events import TraceCollector

# Initialize one global Session Service for the application
session_service = InMemorySessionService()

# Create standard ADK Runners for all 4 agents
sensory_runner = Runner(agent=sensory_guardian_agent, app_name="silvergrove", session_service=session_service, auto_create_session=True)
compliance_runner = Runner(agent=medical_compliance_agent, app_name="silvergrove", session_service=session_service, auto_create_session=True)
companion_runner = Runner(agent=cognitive_companion_agent, app_name="silvergrove", session_service=session_service, auto_create_session=True)
coordinator_runner = Runner(agent=care_coordinator_agent, app_name="silvergrove", session_service=session_service, auto_create_session=True)

def invoke_agent(runner: Runner, prompt: str, user_id: str, session_id: str, collector: TraceCollector = None) -> str:
    """
    Helper function to run an agent via its stateful ADK Runner.
    Translates string prompts into Google GenAI types.Content, consumes yielded events,
    and extracts the final text response. Includes a 3-attempt retry policy for free tier robustness.
    Strictly emoji-free logging.
    """
    agent_name = runner.agent.name
    if collector:
        collector.log(
            agent=agent_name,
            event_type="LLM_REQUEST",
            message=f"Invoking Gemini 3.1 Flash Lite on model {runner.agent.model or 'gemini-3.1-flash-lite'}",
            data={"prompt": prompt}
        )

    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    
    for attempt in range(1, 4):
        try:
            if collector and attempt > 1:
                collector.log(
                    agent=agent_name,
                    event_type="RETRY",
                    message=f"Attempt {attempt} to execute agent after failure"
                )
            
            # Run the generator synchronously to collect all events
            events = list(runner.run(user_id=user_id, session_id=session_id, new_message=content))
            
            # Extract response and log tool events
            response_text = ""
            for event in events:
                # Log any tool calls made by the agent
                if hasattr(event, "tool_calls") and event.tool_calls:
                    for tc in event.tool_calls:
                        tool_args = getattr(tc, "args", {}) or {}
                        tool_name = getattr(tc, "name", "unknown_tool")
                        if collector:
                            collector.log(
                                agent=agent_name,
                                event_type="TOOL_CALL",
                                message=f"Calling tool: {tool_name}",
                                data={"args": tool_args}
                            )
                
                # Check for tool response/results
                if hasattr(event, "tool_response") and event.tool_response:
                    if collector:
                        collector.log(
                            agent=agent_name,
                            event_type="TOOL_RESULT",
                            message="Tool execution successful",
                            data={"result": str(event.tool_response)[:500]}
                        )
                        
                if hasattr(event, "content") and event.content:
                    for part in event.content.parts:
                        if part.text:
                            response_text += part.text
                            
            if not response_text:
                for event in events:
                    if hasattr(event, "output") and event.output:
                        if isinstance(event.output, str):
                            response_text += event.output
                        elif hasattr(event.output, "text") and event.output.text:
                            response_text += event.output.text
                            
            if response_text and "empty response" not in response_text.lower():
                if collector:
                    collector.log(
                        agent=agent_name,
                        event_type="LLM_RESPONSE",
                        message="Response successfully generated by agent",
                        data={"response": response_text}
                    )
                return response_text
                
            raise ValueError("Agent returned an empty or invalid response.")
            
        except Exception as e:
            print(f"[Retry Warning] Attempt {attempt} failed: {e}. Retrying in 2 seconds...")
            time.sleep(2)
            
    # All 3 retry attempts exhausted -- propagate transparent error to the frontend
    error_msg = f"Agent '{agent_name}' failed to generate a response after 3 attempts. Verify API key and network connectivity."
    if collector:
        collector.log(
            agent=agent_name,
            event_type="ERROR",
            message=error_msg
        )
    raise RuntimeError(error_msg)


@dataclass
class AgentState:
    status: str = "SKIPPED"
    output: str = ""

@dataclass
class PipelineTrajectory:
    resident_id: str
    session_id: str
    sensory_guardian: AgentState = field(default_factory=AgentState)
    medical_compliance: AgentState = field(default_factory=AgentState)
    cognitive_companion: AgentState = field(default_factory=AgentState)
    care_coordinator: AgentState = field(default_factory=AgentState)
    summary: str = "No critical anomalies detected. Routine vitals are within stable thresholds."

class AsyncEventBus:
    def __init__(self):
        self.subscribers = {}
        
    def subscribe(self, topic: str, queue: asyncio.Queue):
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(queue)
        
    async def publish(self, topic: str, payload: dict):
        if topic in self.subscribers:
            for q in self.subscribers[topic]:
                await q.put(payload)

class SilverGroveOrchestrator:
    """
    SilverGrove Multi-Agent Orchestrator.
    Coordinates execution using a true Asynchronous Event Bus.
    Agents publish and subscribe to clinical events independently.
    Retains long-term episodic memory via persistent session IDs.
    """
    
    def run_health_check(self, resident_id: str, collector: TraceCollector = None) -> dict:
        # Run the async orchestrator inside the current thread's event loop (or a new one)
        try:
            loop = asyncio.get_running_loop()
            # If we are already in an event loop, we shouldn't use asyncio.run
            # This handles the FastAPI background thread case
            return asyncio.run_coroutine_threadsafe(self.run_health_check_async(resident_id, collector), loop).result()
        except RuntimeError:
            return asyncio.run(self.run_health_check_async(resident_id, collector))
            
    async def run_health_check_async(self, resident_id: str, collector: TraceCollector = None) -> dict:
        if collector:
            collector.log("ORCHESTRATOR", "START", "Booting Asynchronous Event Bus for Multi-Agent Clinical Audit", {"resident_id": resident_id})
            
        trajectory = PipelineTrajectory(resident_id=resident_id, session_id=f"session_{resident_id}")
        user_id = f"user_{resident_id}"
        
        # Persistent memory: Agents remember this specific resident across multiple checks!
        sensory_session = f"sensory_{resident_id}"
        compliance_session = f"compliance_{resident_id}"
        companion_session = f"companion_{resident_id}"
        coordinator_session = f"coordinator_{resident_id}"
        
        bus = AsyncEventBus()
        loop = asyncio.get_running_loop()
        
        # Create queues for each agent
        sensory_q = asyncio.Queue()
        compliance_q = asyncio.Queue()
        companion_q = asyncio.Queue()
        coordinator_q = asyncio.Queue()
        
        # Subscribe agents to topics
        bus.subscribe("SYSTEM.START_CHECK", sensory_q)
        bus.subscribe("CLINICAL.ANOMALY_DETECTED", compliance_q)
        bus.subscribe("CLINICAL.COMPLIANCE_REPORT_READY", companion_q)
        bus.subscribe("CLINICAL.COMPANION_DRAFT_READY", coordinator_q)

        # Event to signal the orchestrator that the workflow is complete
        workflow_complete = asyncio.Event()

        async def sensory_worker():
            event = await sensory_q.get()
            if collector:
                collector.log("SENSORY_GUARDIAN", "SUBSCRIBE", "Received SYSTEM.START_CHECK event via Async Bus")
            
            prompt = (
                f"Analyze vital sign readings, baselines, and 5-day gait history for resident '{resident_id}'. "
                "Report if there are any significant anomalies (elevated/low blood pressure or gait speed slowdown >=15%)."
            )
            try:
                resp = await loop.run_in_executor(None, invoke_agent, sensory_runner, prompt, user_id, sensory_session, collector)
                trajectory.sensory_guardian.status = "COMPLETED"
                trajectory.sensory_guardian.output = resp
                
                has_anomaly = any(w in resp.upper() for w in ["ANOMALY", "WARNING", "DEGRADATION", "BP ELEVATED", "SLOWDOWN", "ELEVATED", "SPIKE", "ALERT", "LOW BLOOD PRESSURE", " hypotension"])
                if has_anomaly:
                    if collector:
                        collector.log("SENSORY_GUARDIAN", "PUBLISH", "Publishing CLINICAL.ANOMALY_DETECTED to Async Bus")
                    await bus.publish("CLINICAL.ANOMALY_DETECTED", {"data": resp})
                else:
                    msg = "Vitals are normal. No clinical escalation needed."
                    trajectory.summary = msg
                    if collector:
                        collector.log("ORCHESTRATOR", "COMPLETE", msg)
                    workflow_complete.set()
            except Exception as e:
                trajectory.sensory_guardian.status = "FAILED"
                trajectory.sensory_guardian.output = str(e)
                workflow_complete.set()
                
        async def compliance_worker():
            event = await compliance_q.get()
            if collector:
                collector.log("MEDICAL_COMPLIANCE", "SUBSCRIBE", "Received CLINICAL.ANOMALY_DETECTED event. Beginning analysis.")
            
            sensory_data = event["data"]
            prompt = (
                f"An anomaly was flagged for resident '{resident_id}'. Sensory Guardian report:\n\"\"\"{sensory_data}\"\"\"\n"
                "Look up current prescriptions. Determine if any medication correlates chemically with these symptoms. "
                "Provide a structured Clinical Correlation Report."
            )
            try:
                resp = await loop.run_in_executor(None, invoke_agent, compliance_runner, prompt, user_id, compliance_session, collector)
                trajectory.medical_compliance.status = "COMPLETED"
                trajectory.medical_compliance.output = resp
                
                risk_level = "WARNING"
                if "CRITICAL" in resp.upper(): risk_level = "CRITICAL"
                elif "LOW" in resp.upper(): risk_level = "ADVISORY"
                
                if collector:
                    collector.log("MEDICAL_COMPLIANCE", "PUBLISH", f"Publishing CLINICAL.COMPLIANCE_REPORT_READY (Risk: {risk_level})")
                await bus.publish("CLINICAL.COMPLIANCE_REPORT_READY", {"data": resp, "risk": risk_level})
            except Exception as e:
                trajectory.medical_compliance.status = "FAILED"
                workflow_complete.set()

        async def companion_worker():
            event = await companion_q.get()
            if collector:
                collector.log("COGNITIVE_COMPANION", "SUBSCRIBE", "Received CLINICAL.COMPLIANCE_REPORT_READY event. Drafting empathy message.")
                
            compliance_data = event["data"]
            prompt = (
                f"Resident '{resident_id}' needs a check-in. The Medical Compliance Agent noted:\n\"\"\"{compliance_data}\"\"\"\n"
                "You have access to episodic memory of past chats. Recall if this is a recurring issue. "
                "Write a warm conversational message advising them of safety steps."
            )
            try:
                resp = await loop.run_in_executor(None, invoke_agent, companion_runner, prompt, user_id, companion_session, collector)
                trajectory.cognitive_companion.status = "COMPLETED"
                trajectory.cognitive_companion.output = resp
                
                if collector:
                    collector.log("COGNITIVE_COMPANION", "PUBLISH", "Publishing CLINICAL.COMPANION_DRAFT_READY")
                await bus.publish("CLINICAL.COMPANION_DRAFT_READY", {"companion_draft": resp, "compliance_data": compliance_data, "risk": event["risk"]})
            except Exception as e:
                trajectory.cognitive_companion.status = "FAILED"
                workflow_complete.set()

        async def coordinator_worker():
            event = await coordinator_q.get()
            if collector:
                collector.log("CARE_COORDINATOR", "SUBSCRIBE", "Received CLINICAL.COMPANION_DRAFT_READY. Routing A2A alerts.")
                
            prompt = (
                f"Health situation for '{resident_id}'.\n"
                f"- Risk: {event['risk']}\n"
                f"- Compliance: {event['compliance_data'][:500]}...\n"
                f"- Check-in Draft: {event['companion_draft'][:300]}...\n"
                "Route this care alert via log_a2a_alert_tool. Include actionable semicolon-separated actions."
            )
            try:
                resp = await loop.run_in_executor(None, invoke_agent, coordinator_runner, prompt, user_id, coordinator_session, collector)
                trajectory.care_coordinator.status = "COMPLETED"
                trajectory.care_coordinator.output = resp
                
                if collector:
                    # Build dispatch payloads from real agent outputs
                    companion_summary = event["companion_draft"][:500]
                    compliance_context = event["compliance_data"][:500]
                    
                    family_dispatch_payload = {
                        "resident_id": resident_id,
                        "risk": event["risk"],
                        "summary": companion_summary,
                    }
                    # Compute SHA-256 integrity hash over the payload content
                    family_payload_bytes = json.dumps(family_dispatch_payload, sort_keys=True).encode("utf-8")
                    family_dispatch_payload["integrity_sha256"] = hashlib.sha256(family_payload_bytes).hexdigest()
                    
                    physician_dispatch_payload = {
                        "patient_identifier": resident_id,
                        "fhir_resource_type": "Observation",
                        "loinc_code": "85354-9",
                        "clinical_status": "preliminary",
                        "risk_severity": event["risk"],
                        "compliance_correlation": compliance_context,
                    }
                    physician_payload_bytes = json.dumps(physician_dispatch_payload, sort_keys=True).encode("utf-8")
                    physician_dispatch_payload["integrity_sha256"] = hashlib.sha256(physician_payload_bytes).hexdigest()
                    
                    port = os.environ.get("PORT", 8180)
                    gateway_base = f"http://127.0.0.1:{port}"
                    
                    collector.log("CARE_COORDINATOR", "A2A_DISPATCH", f"Dispatching SHA-256 signed payload to Family Gateway at {gateway_base}/a2a/family-gateway/inbox", family_dispatch_payload)
                    collector.log("CARE_COORDINATOR", "A2A_DISPATCH", f"Dispatching SHA-256 signed FHIR payload to Physician Gateway at {gateway_base}/a2a/physician-gateway/fhir-ingest", physician_dispatch_payload)
                    
                    # Deliver payloads to self-hosted A2A gateway endpoints via HTTP
                    try:
                        requests.post(f"{gateway_base}/a2a/family-gateway/inbox", json=family_dispatch_payload, timeout=2)
                        requests.post(f"{gateway_base}/a2a/physician-gateway/fhir-ingest", json=physician_dispatch_payload, timeout=2)
                    except Exception as http_e:
                        collector.log("CARE_COORDINATOR", "ERROR", f"Gateway delivery failed: {str(http_e)}")

                trajectory.summary = f"Multi-agent async workflow complete. Consensus: {event['risk']} risk. A2A alerts dispatched."
                if collector:
                    collector.log("ORCHESTRATOR", "COMPLETE", trajectory.summary)
            except Exception as e:
                trajectory.care_coordinator.status = "FAILED"
            finally:
                workflow_complete.set()

        # Start all agent workers concurrently
        tasks = [
            asyncio.create_task(sensory_worker()),
            asyncio.create_task(compliance_worker()),
            asyncio.create_task(companion_worker()),
            asyncio.create_task(coordinator_worker())
        ]
        
        # Fire the starting gun on the Event Bus
        await bus.publish("SYSTEM.START_CHECK", {})
        
        # Wait for the workflow to complete
        await workflow_complete.wait()
        
        # Cleanup tasks (they are one-shot in this implementation)
        for t in tasks:
            t.cancel()
            
        return asdict(trajectory)

if __name__ == "__main__":
    # Test orchestrator locally
    orchestrator = SilverGroveOrchestrator()
    collector = TraceCollector("test_session")
    res = orchestrator.run_health_check("martha_001", collector)
    print("\n--- HEALTH CHECK SUMMARY ---")
    print(res["summary"])
