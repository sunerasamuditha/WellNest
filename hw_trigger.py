"""
=============================================================================
 hw_trigger.py  —  Hardware scenario trigger for WellNest
=============================================================================

 WHAT THIS DOES
   Adds ONE endpoint:  POST /api/hw/scenario
   It (1) writes scenario vitals into the resident's telemetry, then
      (2) calls your EXISTING trigger_broadcast_check() in main.py.

 WHAT THIS DOES NOT DO
   It does not modify the orchestrator, the agents, the broadcast stream,
   the dashboard, or any existing route. The health check runs through the
   exact same code path as pressing the button in the UI.

 WIRING (2 lines at the bottom of main.py, after `app` exists)
     from hw_trigger import router as hw_router
     app.include_router(hw_router)

 VERIFY BEFORE DEMO DAY (no ESP32 needed)
     GET  /api/hw/selftest?resident_id=martha_001&scenario=critical
   This injects the vitals and reads them back WITHOUT running a health
   check. If "verified" is true, the ESP32 trigger will work.
=============================================================================
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("hw_trigger")
router = APIRouter(tags=["hardware"])


# ---------------------------------------------------------------------------
#  SCENARIO DEFINITIONS
#  Every scenario sets ALL fields so a previous run never leaks into the next.
#  normal   : nothing abnormal
#  mild     : gait speed abnormal only
#  critical : heart rate AND gait speed abnormal
# ---------------------------------------------------------------------------
SCENARIOS: dict[str, dict[str, float]] = {
    "normal": {
        "heart_rate_bpm": 72,
        "bp_systolic": 118,
        "bp_diastolic": 76,
        "gait_speed_ms": 1.05,
    },
    "mild": {
        "heart_rate_bpm": 74,
        "bp_systolic": 120,
        "bp_diastolic": 78,
        "gait_speed_ms": 0.55,      # <-- the only abnormal value
    },
    "critical": {
        "heart_rate_bpm": 132,      # <-- abnormal
        "bp_systolic": 126,
        "bp_diastolic": 80,
        "gait_speed_ms": 0.35,      # <-- abnormal
    },
}

SCENARIO_ALIASES = {
    "ok": "normal", "healthy": "normal", "green": "normal",
    "warn": "mild", "warning": "mild", "amber": "mild", "gait": "mild",
    "crit": "critical", "severe": "critical", "red": "critical",
}

# Latest presence reading from the RF node, for display / context only.
LAST_PRESENCE: dict[str, Any] = {}


def resolve_scenario(name: str) -> str:
    key = (name or "").strip().lower()
    key = SCENARIO_ALIASES.get(key, key)
    if key not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{name}'. Use one of: {', '.join(SCENARIOS)}",
        )
    return key


# ---------------------------------------------------------------------------
#  VITALS INJECTION
#  vitals_server internals differ between builds, so we try several safe
#  strategies and then READ BACK to confirm which one actually stuck.
# ---------------------------------------------------------------------------
def _read_telemetry(resident_id: str) -> dict:
    from tools.vitals_tools import get_resident_vitals
    data = get_resident_vitals(resident_id) or {}
    tel = data.get("telemetry")
    return tel if isinstance(tel, dict) else {}


def _verify(resident_id: str, overrides: dict) -> bool:
    tel = _read_telemetry(resident_id)
    if not tel:
        return False
    for k, v in overrides.items():
        if k not in tel:
            return False
        try:
            if abs(float(tel[k]) - float(v)) > 0.001:
                return False
        except (TypeError, ValueError):
            return False
    return True


def inject_vitals(resident_id: str, overrides: dict) -> dict:
    """Write scenario vitals. Returns a report of what was tried."""
    attempts: list[str] = []
    from mcp_servers import vitals_server as vs

    # Strategy 1 — a purpose-built setter, if this build has one
    for fname in ("set_resident_vitals", "override_vitals", "set_vitals",
                  "update_vitals", "set_telemetry", "inject_vitals"):
        fn = getattr(vs, fname, None)
        if callable(fn):
            try:
                fn(resident_id, dict(overrides))
                if _verify(resident_id, overrides):
                    return {"ok": True, "method": f"vitals_server.{fname}()", "attempts": attempts}
                attempts.append(f"{fname}: called, value did not stick")
            except Exception as exc:
                attempts.append(f"{fname}: {exc}")

    # Strategy 2 — freeze the resident, then mutate the frozen snapshot.
    # This is the normal path: run_health_check() freezes vitals anyway.
    try:
        vs.set_vitals_frozen(resident_id, True)
        tel = _read_telemetry(resident_id)
        if isinstance(tel, dict):
            tel.update(overrides)
            if _verify(resident_id, overrides):
                return {"ok": True, "method": "freeze + mutate snapshot", "attempts": attempts}
        attempts.append("freeze+mutate: snapshot is a copy, not a reference")
    except Exception as exc:
        attempts.append(f"freeze+mutate: {exc}")

    # Strategy 3 — mutate any module-level store keyed by resident id
    try:
        hits = 0
        for name, obj in list(vars(vs).items()):
            if name.startswith("__") or not isinstance(obj, dict):
                continue
            entry = obj.get(resident_id)
            if isinstance(entry, dict):
                target = entry.get("telemetry") if isinstance(entry.get("telemetry"), dict) else entry
                target.update(overrides)
                hits += 1
        if hits and _verify(resident_id, overrides):
            return {"ok": True, "method": f"module store mutation ({hits} dict(s))", "attempts": attempts}
        if hits:
            attempts.append(f"module store: updated {hits} dict(s), value did not stick")
    except Exception as exc:
        attempts.append(f"module store: {exc}")

    # Strategy 4 — mutate the loaded residents record
    try:
        loader = getattr(vs, "load_residents", None)
        if callable(loader):
            residents = loader()
            rec = residents.get(resident_id) if isinstance(residents, dict) else None
            if isinstance(rec, dict):
                target = rec.get("telemetry") if isinstance(rec.get("telemetry"), dict) else rec
                target.update(overrides)
                if _verify(resident_id, overrides):
                    return {"ok": True, "method": "load_residents() record mutation", "attempts": attempts}
                attempts.append("load_residents: updated, value did not stick")
    except Exception as exc:
        attempts.append(f"load_residents: {exc}")

    return {"ok": False, "method": None, "attempts": attempts}


# ---------------------------------------------------------------------------
#  MODELS
# ---------------------------------------------------------------------------
class PresenceCtx(BaseModel):
    detected: bool = False
    movement: bool = False
    variance: float = 0.0
    baseline: float = 0.0
    ratio: float = 0.0
    calibrated: bool = False


class ScenarioRequest(BaseModel):
    scenario: str
    resident_id: str = "martha_001"
    node_id: str = "livingroom_node_01"
    source: str = "esp32_hardware"
    presence: PresenceCtx = Field(default_factory=PresenceCtx)


# ---------------------------------------------------------------------------
#  ENDPOINTS
# ---------------------------------------------------------------------------
@router.post("/api/hw/scenario")
async def hw_scenario(req: ScenarioRequest):
    """
    Called by the ESP32. Injects scenario vitals, then runs the SAME
    broadcast health check the dashboard button runs.

    This awaits the full agent run (like your existing /check/trigger does),
    so the caller must use a long timeout. The ESP32 firmware uses 150 s.
    """
    key = resolve_scenario(req.scenario)
    overrides = dict(SCENARIOS[key])

    LAST_PRESENCE[req.resident_id] = {
        **req.presence.model_dump(),
        "node_id": req.node_id,
        "ts": datetime.datetime.utcnow().isoformat(),
    }

    report = inject_vitals(req.resident_id, overrides)
    if not report["ok"]:
        log.warning("hw_trigger: vitals injection failed: %s", report["attempts"])

    # Reuse the existing broadcast trigger verbatim. Nothing is duplicated.
    import main as app_main
    result = await app_main.trigger_broadcast_check(req.resident_id)

    return {
        "ok": True,
        "scenario": key,
        "resident_id": req.resident_id,
        "vitals_applied": overrides,
        "vitals_injected": report["ok"],
        "injection_method": report["method"],
        "injection_attempts": None if report["ok"] else report["attempts"],
        "health_check": result,
    }


@router.get("/api/hw/selftest")
async def hw_selftest(resident_id: str = "martha_001", scenario: str = "critical"):
    """Inject and read back WITHOUT running a health check. Run this first."""
    key = resolve_scenario(scenario)
    overrides = dict(SCENARIOS[key])
    before = dict(_read_telemetry(resident_id))
    report = inject_vitals(resident_id, overrides)
    after = dict(_read_telemetry(resident_id))

    try:
        from mcp_servers.vitals_server import set_vitals_frozen
        set_vitals_frozen(resident_id, False)
    except Exception:
        pass

    return {
        "verified": report["ok"],
        "method": report["method"],
        "scenario": key,
        "resident_id": resident_id,
        "expected": overrides,
        "telemetry_before": before,
        "telemetry_after": after,
        "attempts": report["attempts"],
        "next_step": (
            "Injection works. The ESP32 trigger is ready."
            if report["ok"] else
            "Injection did not stick. See 'attempts' and adjust inject_vitals() "
            "in hw_trigger.py to match your vitals_server API."
        ),
    }


@router.post("/api/hw/telemetry")
async def hw_telemetry(body: dict):
    """Optional RF presence feed from the node. Stored for context only."""
    rid = body.get("resident_id", "unknown")
    LAST_PRESENCE[rid] = {**body, "ts": datetime.datetime.utcnow().isoformat()}
    return {"ok": True}


@router.get("/api/hw/status")
async def hw_status():
    return {
        "ok": True,
        "scenarios": SCENARIOS,
        "aliases": SCENARIO_ALIASES,
        "last_presence": LAST_PRESENCE,
    }
