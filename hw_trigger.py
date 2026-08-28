

from __future__ import annotations

import datetime
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("hw_trigger")
router = APIRouter(tags=["hardware"])

DEFAULT_RESIDENT = "sriyani_001"


# ---------------------------------------------------------------------------
#  SCENARIOS
#  Defined RELATIVE to each resident's clinical baseline, so the same three
#  words work for every resident without hardcoding absolute numbers.
#
#  Your engine flags an anomaly when:
#     abs(gait_change_pct) >= 15   OR   bp_systolic >= 140   OR   <= 100
#  and get_gait_trend() flags degradation when the 5-day change <= -15%.
#
#  normal   : nothing abnormal
#  mild     : gait speed only
#  critical : gait speed AND heart rate
#  Blood pressure is deliberately held in the normal band in all three, so
#  the abnormal signal is unambiguous.
# ---------------------------------------------------------------------------
SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {
        "gait_factor": 0.98,      # 2% below baseline -> NORMAL
        "gait_decline": 0.02,     # 5-day trend stays STABLE
        "hr_delta": 0,
        "sleep_hours": 7.2,
        "label": "All vitals within baseline",
    },
    "mild": {
        "gait_factor": 0.80,      # 20% below baseline -> ANOMALY_DETECTED
        "gait_decline": 0.18,     # trend -> DEGRADATION_DETECTED
        "hr_delta": 3,            # heart rate stays normal
        "sleep_hours": 6.4,
        "label": "Gait speed declined ~20 percent, single-domain anomaly",
    },
    "critical": {
        "gait_factor": 0.58,      # 42% below baseline
        "gait_decline": 0.38,
        "hr_delta": 50,           # pushes heart rate into tachycardia
        "sleep_hours": 5.0,
        "label": "Gait collapse plus tachycardia, multi-domain anomaly",
    },
}

SCENARIO_ALIASES = {
    "ok": "normal", "healthy": "normal", "green": "normal", "stable": "normal",
    "warn": "mild", "warning": "mild", "amber": "mild", "gait": "mild",
    "crit": "critical", "severe": "critical", "red": "critical",
}

# Blood pressure is clamped into this band so it never trips the BP branch
BP_SYS_MIN, BP_SYS_MAX = 108, 134
BP_DIA_MIN, BP_DIA_MAX = 66, 86
HR_MIN, HR_MAX = 40, 150

# Original gait_decline_severity values, captured once so /api/hw/reset
# can put the engine back exactly as it shipped.
_ORIGINAL_DECLINE: dict[str, float] = {}
_LAST_INJECTION: dict[str, Any] = {}
LAST_PRESENCE: dict[str, Any] = {}


def _capture_originals() -> None:
    global _ORIGINAL_DECLINE
    if _ORIGINAL_DECLINE:
        return
    try:
        from mcp_servers import vitals_server as vs
        _ORIGINAL_DECLINE = {
            rid: prof.get("gait_decline_severity")
            for rid, prof in vs.RESIDENT_ANOMALY_PROFILES.items()
        }
    except Exception as exc:
        log.warning("hw_trigger: could not capture original profiles: %s", exc)


def resolve_scenario(name: str) -> str:
    key = (name or "").strip().lower()
    key = SCENARIO_ALIASES.get(key, key)
    if key not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{name}'. Use: {', '.join(SCENARIOS)}",
        )
    return key


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
#  INJECTION
# ---------------------------------------------------------------------------
def build_telemetry(resident_id: str, scenario_key: str,
                    room: Optional[str] = None) -> dict:
    """Compute scenario telemetry relative to the resident's real baselines."""
    from services.gcp_service import get_resident_profile_db

    profile = get_resident_profile_db(resident_id) or {}
    b = profile.get("baselines", {}) or {}

    base_gait = float(b.get("gait_speed_ms", 0.85))
    base_hr = float(b.get("heart_rate_bpm", 72))
    base_sys = float(b.get("bp_systolic", 120))
    base_dia = float(b.get("bp_diastolic", 78))

    spec = SCENARIOS[scenario_key]

    return {
        "heart_rate_bpm": int(_clamp(round(base_hr + spec["hr_delta"]), HR_MIN, HR_MAX)),
        "bp_systolic": int(_clamp(round(base_sys * 0.98), BP_SYS_MIN, BP_SYS_MAX)),
        "bp_diastolic": int(_clamp(round(base_dia), BP_DIA_MIN, BP_DIA_MAX)),
        "gait_speed_ms": round(base_gait * spec["gait_factor"], 2),
        "sleep_hours": spec["sleep_hours"],
        "room_occupancy": room or "living_room",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


def inject_scenario(resident_id: str, scenario_key: str,
                    room: Optional[str] = None) -> dict:
    """Write the scenario into the vitals engine. Returns a verification report."""
    from mcp_servers import vitals_server as vs

    _capture_originals()

    if resident_id not in vs.RESIDENT_ANOMALY_PROFILES:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown resident '{resident_id}'. Valid ids: "
                f"{', '.join(vs.RESIDENT_ANOMALY_PROFILES)}"
            ),
        )

    telemetry = build_telemetry(resident_id, scenario_key, room)

    # Write BOTH stores. _LAST_GENERATED is essential because
    # set_vitals_frozen(rid, True) copies from it into _FROZEN_VITALS.
    vs._LAST_GENERATED[resident_id] = telemetry
    vs._FROZEN_VITALS[resident_id] = telemetry

    # Keep the 5-day gait trend consistent with the reading.
    vs.RESIDENT_ANOMALY_PROFILES[resident_id]["gait_decline_severity"] = \
        SCENARIOS[scenario_key]["gait_decline"]

    # Read back through the real tool the agents will call.
    check = vs.get_resident_vitals(resident_id)
    read_tel = check.get("telemetry", {}) if isinstance(check, dict) else {}
    verified = bool(read_tel) and all(
        abs(float(read_tel.get(k, -9999)) - float(v)) < 0.001
        for k, v in telemetry.items()
        if isinstance(v, (int, float))
    )

    trend = vs.get_gait_trend(resident_id)

    _LAST_INJECTION[resident_id] = {
        "scenario": scenario_key,
        "telemetry": telemetry,
        "at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    return {
        "verified": verified,
        "method": "_LAST_GENERATED + _FROZEN_VITALS + gait_decline_severity",
        "telemetry": telemetry,
        "resident_name": check.get("resident_name") if isinstance(check, dict) else None,
        "baselines": check.get("baselines") if isinstance(check, dict) else None,
        "gait_change_percent": check.get("gait_change_percent") if isinstance(check, dict) else None,
        "vitals_status": check.get("status") if isinstance(check, dict) else None,
        "gait_trend": {
            "history": trend.get("gait_speed_history_ms"),
            "change_percent": trend.get("total_gait_change_percent"),
            "verdict": trend.get("verdict"),
        } if isinstance(trend, dict) else None,
    }


def clear_injection(resident_id: str) -> dict:
    """Return the engine to its shipped behaviour for one resident."""
    from mcp_servers import vitals_server as vs
    _capture_originals()

    vs._FROZEN_VITALS.pop(resident_id, None)
    vs._LAST_GENERATED.pop(resident_id, None)
    original = _ORIGINAL_DECLINE.get(resident_id)
    if original is not None and resident_id in vs.RESIDENT_ANOMALY_PROFILES:
        vs.RESIDENT_ANOMALY_PROFILES[resident_id]["gait_decline_severity"] = original
    _LAST_INJECTION.pop(resident_id, None)
    return {"ok": True, "resident_id": resident_id,
            "gait_decline_severity_restored": original}


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
    resident_id: str = DEFAULT_RESIDENT
    node_id: str = "livingroom_node_01"
    source: str = "esp32_hardware"
    room: Optional[str] = None
    presence: PresenceCtx = Field(default_factory=PresenceCtx)


# ---------------------------------------------------------------------------
#  ENDPOINTS
# ---------------------------------------------------------------------------
@router.get("/api/hw/residents")
async def hw_residents():
    """Valid resident ids. Put one of these in the ESP32 firmware."""
    from mcp_servers import vitals_server as vs
    from services.gcp_service import get_resident_profile_db

    out = []
    for rid in vs.RESIDENT_ANOMALY_PROFILES:
        p = get_resident_profile_db(rid) or {}
        out.append({
            "resident_id": rid,
            "name": p.get("name"),
            "baselines": p.get("baselines"),
        })
    return {"ok": True, "default": DEFAULT_RESIDENT, "residents": out,
            "scenarios": {k: v["label"] for k, v in SCENARIOS.items()}}


@router.get("/api/hw/selftest")
async def hw_selftest(resident_id: str = DEFAULT_RESIDENT, scenario: str = "critical"):
    """
    Inject and read back WITHOUT running a health check.
    Run this once after deploying. If "verified" is true, the ESP32 will work.
    """
    key = resolve_scenario(scenario)
    report = inject_scenario(resident_id, key)
    clear_injection(resident_id)
    return {
        "verified": report["verified"],
        "scenario": key,
        "resident_id": resident_id,
        "resident_name": report["resident_name"],
        "baselines": report["baselines"],
        "injected_telemetry": report["telemetry"],
        "gait_change_percent": report["gait_change_percent"],
        "vitals_status": report["vitals_status"],
        "gait_trend": report["gait_trend"],
        "note": "Injection reverted after this test. Nothing was left modified.",
        "next_step": ("Ready. Point the ESP32 at this backend."
                      if report["verified"] else
                      "Read-back mismatch - send me this JSON."),
    }


@router.post("/api/hw/scenario")
async def hw_scenario(req: ScenarioRequest):
    """
    Called by the ESP32. Injects the scenario, then runs the SAME broadcast
    health check the dashboard button runs. Awaits the full agent run, so the
    caller needs a long timeout (the firmware uses 150 s).
    """
    key = resolve_scenario(req.scenario)

    LAST_PRESENCE[req.resident_id] = {
        **req.presence.model_dump(),
        "node_id": req.node_id,
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
    }

    # Real RF presence from the node decides the room_occupancy field.
    room = req.room or ("living_room" if req.presence.detected else "bedroom")

    report = inject_scenario(req.resident_id, key, room=room)
    if not report["verified"]:
        log.warning("hw_trigger: injection read-back mismatch for %s", req.resident_id)

    # Reuse the existing broadcast trigger verbatim. Nothing duplicated.
    import main as app_main
    result = await app_main.trigger_broadcast_check(req.resident_id)

    # Re-pin so the dashboard keeps showing what the agents just reasoned about
    # (trigger_broadcast_check unfreezes in its finally block).
    try:
        from mcp_servers import vitals_server as vs
        vs._FROZEN_VITALS[req.resident_id] = report["telemetry"]
    except Exception:
        pass

    return {
        "ok": True,
        "scenario": key,
        "scenario_label": SCENARIOS[key]["label"],
        "resident_id": req.resident_id,
        "resident_name": report["resident_name"],
        "vitals_injected": report["verified"],
        "telemetry": report["telemetry"],
        "vitals_status": report["vitals_status"],
        "gait_change_percent": report["gait_change_percent"],
        "gait_trend_verdict": (report["gait_trend"] or {}).get("verdict"),
        "health_check": result,
    }


@router.post("/api/hw/reset")
async def hw_reset(resident_id: str = DEFAULT_RESIDENT):
    """Clear an injection and restore the resident's shipped behaviour."""
    return clear_injection(resident_id)


@router.post("/api/hw/telemetry")
async def hw_telemetry(body: dict):
    """Optional RF presence feed from the node. Stored for context only."""
    rid = body.get("resident_id", "unknown")
    LAST_PRESENCE[rid] = {**body, "ts": datetime.datetime.utcnow().isoformat() + "Z"}
    return {"ok": True}


@router.get("/api/hw/status")
async def hw_status():
    return {
        "ok": True,
        "default_resident": DEFAULT_RESIDENT,
        "scenarios": {k: v["label"] for k, v in SCENARIOS.items()},
        "aliases": SCENARIO_ALIASES,
        "last_injection": _LAST_INJECTION,
        "last_presence": LAST_PRESENCE,
    }
