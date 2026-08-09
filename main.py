import os
import sys
import json
import uuid
import asyncio
import datetime
import threading
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

# Ensure parent directory is in path for easy importing
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agent import SilverGroveOrchestrator
from tools.vitals_tools import get_resident_vitals, get_resident_details
from tools.alert_tools import get_alerts_timeline, clear_alerts_timeline
from tools.trace_events import TraceCollector
from a2a.agent_cards import get_root_agent_card, get_all_agent_cards
from mcp_servers.vitals_server import set_vitals_frozen
from agents.clinical_analyst import clinical_analyst_agent
from google.adk.runners import Runner
from agent import session_service, invoke_agent

# Initialize FastAPI App
app = FastAPI(
    title="SilverGrove AAL Portal",
    description="Privacy-First Ambient Assisted Living Multi-Agent System Dashboard Gateway",
    version="1.0.0"
)

# Enable CORS for external dashboard client integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Orchestrator instance
orchestrator = SilverGroveOrchestrator()

# Endpoint: List all resident profiles
@app.get("/api/residents")
def list_residents():
    try:
        from mcp_servers.vitals_server import load_residents
        residents = load_residents()
        # Clean up to return array
        res_list = []
        for rid, data in residents.items():
            res_list.append({
                "id": rid,
                "name": data.get("name"),
                "age": data.get("age"),
                "conditions": data.get("conditions"),
                "medications_count": len(data.get("medications", []))
            })
        return res_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint: Get full details & vitals of a resident
@app.get("/api/residents/{resident_id}")
def get_resident_profile(resident_id: str):
    profile = get_resident_details(resident_id)
    if "error" in profile:
        raise HTTPException(status_code=404, detail=profile["error"])
        
    vitals_data = get_resident_vitals(resident_id)
    return {
        "profile": profile,
        "vitals": vitals_data
    }

# Endpoint: Get resident vital telemetry formatted as FHIR Observation Bundle
@app.get("/api/residents/{resident_id}/fhir")
def get_resident_fhir_bundle(resident_id: str):
    profile = get_resident_details(resident_id)
    if "error" in profile:
        raise HTTPException(status_code=404, detail=profile["error"])
        
    vitals_data = get_resident_vitals(resident_id)
    telemetry = vitals_data.get("telemetry", {})
    
    from tools.fhir_formatter import format_heart_rate_fhir, format_blood_pressure_fhir, format_gait_speed_fhir
    
    hr_obs = format_heart_rate_fhir(resident_id, telemetry.get("heart_rate_bpm", 72))
    bp_obs = format_blood_pressure_fhir(resident_id, telemetry.get("bp_systolic", 120), telemetry.get("bp_diastolic", 80))
    gait_obs = format_gait_speed_fhir(resident_id, telemetry.get("gait_speed_ms", 0.85))
    
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"resource": hr_obs},
            {"resource": bp_obs},
            {"resource": gait_obs}
        ]
    }

# Endpoint: Trigger End-to-End Multi-Agent Health Check
@app.post("/api/residents/{resident_id}/check")
def trigger_agent_check(resident_id: str):
    try:
        set_vitals_frozen(resident_id, True)
        trajectory = orchestrator.run_health_check(resident_id)
        set_vitals_frozen(resident_id, False)
        return trajectory
    except Exception as e:
        set_vitals_frozen(resident_id, False)
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint: Stream End-to-End Multi-Agent Health Check in Real-time
@app.get("/api/residents/{resident_id}/check/stream")
def stream_agent_check(resident_id: str):
    """
    Asynchronously streams the end-to-end multi-agent clinical audit logs in real-time.
    Strictly emoji-free standard prefix logs.
    """
    async def event_generator():
        collector = TraceCollector(session_id=f"session_{uuid.uuid4().hex[:8]}")
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        def listener(event):
            loop.call_soon_threadsafe(queue.put_nowait, event)
            
        collector.add_listener(listener)
        
        def run_check():
            try:
                set_vitals_frozen(resident_id, True)
                orchestrator.run_health_check(resident_id, collector)
            except Exception as e:
                collector.log("ORCHESTRATOR", "ERROR", f"Fatal exception during multi-agent check: {str(e)}")
            finally:
                set_vitals_frozen(resident_id, False)
                loop.call_soon_threadsafe(queue.put_nowait, "DONE")
                
        thread = threading.Thread(target=run_check)
        thread.start()
        
        while True:
            event = await queue.get()
            if event == "DONE":
                break
            yield f"data: {json.dumps(event)}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# A2A Protocol Discovery Endpoints
@app.get("/.well-known/agent.json")
def get_root_card():
    return get_root_agent_card()

@app.get("/a2a/agents")
def get_agents():
    return get_all_agent_cards()

@app.get("/a2a/{agent_name}/card")
def get_agent_card(agent_name: str):
    cards = get_all_agent_cards()
    if agent_name in cards:
        return cards[agent_name]
    raise HTTPException(status_code=404, detail=f"Agent card {agent_name} not found.")

# A2A Gateway In-Memory Receive Queues (persisted per container lifecycle)
family_inbox = []
physician_inbox = []

@app.post("/a2a/family-gateway/inbox")
def receive_family_dispatch(payload: dict):
    payload["received_at"] = datetime.datetime.now().isoformat()
    family_inbox.insert(0, payload)
    return {"status": "success"}

@app.get("/api/family/messages")
def get_family_messages():
    return family_inbox

@app.post("/a2a/physician-gateway/fhir-ingest")
def receive_physician_dispatch(payload: dict):
    payload["received_at"] = datetime.datetime.now().isoformat()
    physician_inbox.insert(0, payload)
    return {"status": "success"}

@app.get("/api/physician/inbox")
def get_physician_messages():
    return physician_inbox


# Endpoint: Retrieve Active A2A Alerts Timeline
@app.get("/api/alerts")
def get_alerts():
    return get_alerts_timeline()

# Endpoint: Reset Alert Log for fresh demo
@app.post("/api/alerts/clear")
def clear_alerts():
    clear_alerts_timeline()
    family_inbox.clear()
    physician_inbox.clear()
    return {"status": "success", "message": "Alert timeline and gateway inboxes cleared successfully."}

class ReportRequest(BaseModel):
    resident_id: str

analyst_runner = Runner(agent=clinical_analyst_agent, app_name="silvergrove", session_service=session_service, auto_create_session=True)

@app.post("/api/reports/generate")
def generate_report(req: ReportRequest):
    try:
        from services.pdf_service import generate_local_pdf
        message = generate_local_pdf(req.resident_id)
        return {"status": "success", "message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Serve High-Fidelity UI Static Files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8180))
    # Disable reload in production container for better performance
    reload = os.environ.get("ENV") != "production"
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)
