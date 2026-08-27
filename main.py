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
from typing import List, Optional, Dict

# ─── BROADCAST PUB/SUB STATE ───────────────────────────────────────────────
# Maps resident_id -> list of asyncio.Queue instances (one per connected SSE client)
# When any client fires /trigger, ALL queues receive the event stream in real-time.
broadcast_listeners: Dict[str, List] = {}
check_running: Dict[str, bool] = {}

# Ensure parent directory is in path for easy importing
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agent import WellNestOrchestrator
from tools.vitals_tools import get_resident_vitals, get_resident_details
from tools.alert_tools import get_alerts_timeline, clear_alerts_timeline
from tools.trace_events import TraceCollector
from services.gcp_service import save_trace_event_db, clear_trace_events_db, FIRESTORE_ACTIVE, firestore_client
from a2a.agent_cards import get_root_agent_card, get_all_agent_cards
from mcp_servers.vitals_server import set_vitals_frozen
from agents.clinical_analyst import clinical_analyst_agent
from google.adk.runners import Runner
from agent import session_service, invoke_agent

# Initialize FastAPI App
app = FastAPI(
    title="WellNest AAL Portal",
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
orchestrator = WellNestOrchestrator()

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

# Endpoint: Stream End-to-End Multi-Agent Health Check in Real-time (single-client)
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


# ─── BROADCAST TRIGGER: fires agents, pushes events to Firestore, and holds connection ─
@app.post("/api/residents/{resident_id}/check/trigger")
async def trigger_broadcast_check(resident_id: str):
    """
    Trigger a health check that broadcasts live events to ALL clients subscribed
    to /check/broadcast (via Firestore).
    We await the execution here to hold the HTTP connection open, which prevents 
    Cloud Run from throttling the CPU while the background agents run.
    """
    # Always clear traces to guarantee a clean slate for the real-time broadcast
    clear_trace_events_db(resident_id)

    session_id = f"broadcast_{uuid.uuid4().hex[:8]}"
    collector = TraceCollector(session_id=session_id)
    
    def listener(event):
        if FIRESTORE_ACTIVE:
            event['_ts'] = datetime.datetime.utcnow().isoformat()
            save_trace_event_db(resident_id, event)
            
    collector.add_listener(listener)

    try:
        set_vitals_frozen(resident_id, True)
        # Block the request until agents finish, keeping Cloud Run CPU alive
        await asyncio.to_thread(orchestrator.run_health_check, resident_id, collector)
    except Exception as e:
        err_event = {"agent": "ORCHESTRATOR", "event_type": "ERROR",
                     "message": f"Check failed: {str(e)}",
                     "timestamp_str": datetime.datetime.utcnow().strftime("%H:%M:%S")}
        listener(err_event)
    finally:
        set_vitals_frozen(resident_id, False)
        # Sentinel to end the stream for broadcast listeners
        done_event = {"agent": "ORCHESTRATOR", "event_type": "COMPLETE", "message": "Done."}
        listener(done_event)

    return {
        "status": "completed",
        "resident_id": resident_id,
        "message": "Health check successfully completed."
    }


# ─── BROADCAST STREAM: subscribe to live events from Firestore ─────────
@app.get("/api/residents/{resident_id}/check/broadcast")
def broadcast_stream(resident_id: str):
    """
    Persistent SSE endpoint. Desktop dashboard connects here.
    Listens to Firestore `live_traces` in real-time, bridging events across all Cloud Run instances.
    """
    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        watch = None

        if FIRESTORE_ACTIVE:
            def on_snapshot(col_snapshot, changes, read_time):
                # Only push added events (ignore modifications/deletions)
                for change in changes:
                    if change.type.name == 'ADDED':
                        event = change.document.to_dict()
                        if '_ts' in event:
                            del event['_ts']
                        loop.call_soon_threadsafe(queue.put_nowait, event)
            
            # Watch the collection for this resident
            try:
                # We order by _ts to ensure events come in order
                query = firestore_client.collection(f"live_traces_{resident_id}").order_by('_ts')
                watch = query.on_snapshot(on_snapshot)
            except Exception as e:
                print(f"Failed to start Firestore watch: {e}")
        else:
            # Fallback to local memory if Firestore isn't configured
            if resident_id not in broadcast_listeners:
                broadcast_listeners[resident_id] = []
            broadcast_listeners[resident_id].append(queue)

        # Send initial handshake
        connected_event = {
            "agent": "SYSTEM",
            "event_type": "BROADCAST_CONNECTED",
            "message": f"Broadcast channel open (Firestore Sync active). Waiting for trigger...",
            "timestamp_str": datetime.datetime.utcnow().strftime("%H:%M:%S")
        }
        yield f"data: {json.dumps(connected_event)}\n\n"

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("event_type") == "COMPLETE":
                        # Stay connected for the next run
                        pass
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if watch:
                watch.unsubscribe()
            if not FIRESTORE_ACTIVE:
                try:
                    broadcast_listeners[resident_id].remove(queue)
                except (ValueError, KeyError):
                    pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

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

analyst_runner = Runner(agent=clinical_analyst_agent, app_name="wellnest", session_service=session_service, auto_create_session=True)

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
