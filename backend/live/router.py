from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
import json
import os
import asyncio
from pydantic import BaseModel
from typing import Optional, Any
from backend.live.engine import SESSION_MANAGER, JuryRateLimitError
from backend.live.catalog import build_catalog
from backend.live.qr import render_qr_svg

router = APIRouter(prefix="/api/live", tags=["live-ops"])

@router.get("/catalog")
def get_catalog():
    return build_catalog()

class CreateSessionRequest(BaseModel):
    scenario_id: Optional[str] = None
    speed_s_per_hour: Optional[float] = None
    start_hour: Optional[float] = None
    session_id: Optional[str] = None

@router.post("/sessions", status_code=202)
def create_session(req: CreateSessionRequest = CreateSessionRequest()):
    kwargs = {}
    if req.speed_s_per_hour is not None: kwargs["speed_s_per_hour"] = req.speed_s_per_hour
    if req.start_hour is not None: kwargs["start_hour"] = req.start_hour
    session = SESSION_MANAGER.create_session(req.session_id, **kwargs)
    return {"session_id": session.session_id, "snapshot": session.last_snapshot}

@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = SESSION_MANAGER.get_or_create(session_id)
    return session.build_snapshot_event(emit_to_history=False)

@router.get("/sessions/{session_id}/impact_preview")
def get_impact_preview(session_id: str):
    session = SESSION_MANAGER.get_or_create(session_id)
    return session.get_impact_preview()

@router.get("/sessions/{session_id}/stream")
def stream_session(session_id: str, request: Request, max_events: Optional[int] = None):
    session = SESSION_MANAGER.get_or_create(session_id)
    q = session.subscribe()
    
    async def event_generator():
        count = 0
        try:
            while True:
                if max_events is not None and count >= max_events:
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    count += 1
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
        finally:
            session.unsubscribe(q)
            
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

class ClockRequest(BaseModel):
    action: str
    hour: Optional[float] = None
    speed_s_per_hour: Optional[float] = None

@router.post("/sessions/{session_id}/clock", status_code=202)
async def set_clock(session_id: str, req: ClockRequest):
    session = SESSION_MANAGER.get_or_create(session_id)
    kwargs = {}
    if req.hour is not None: kwargs["hour"] = req.hour
    if req.speed_s_per_hour is not None: kwargs["speed_s_per_hour"] = req.speed_s_per_hour
    await session.set_clock(req.action, **kwargs)
    return {
        "accepted": True,
        "session_id": session.session_id,
        "clock": {
            "hour": round(session.hour, 2),
            "running": session.running,
            "speed_s_per_hour": session.speed_s_per_hour
        }
    }

@router.post("/sessions/{session_id}/disrupt", status_code=202)
@router.post("/sessions/{session_id}/events", status_code=202)
async def disrupt(session_id: str, body: dict):
    session = SESSION_MANAGER.get_or_create(session_id)
    asset_id = body.get("asset_id") or body.get("id")
    duration_h = body.get("duration_h") or body.get("duration_hours")
    
    from_hour = body.get("from_hour")
    to_hour = body.get("to_hour")
    if duration_h is None and from_hour is not None and to_hour is not None:
        duration_h = to_hour - from_hour

    res = await session.disrupt(
        asset_id,
        duration_h=duration_h,
        source=body.get("source"),
        explicit_type=body.get("type"),
        from_hour_override=from_hour,
        wait_for_options=bool(body.get("wait_for_options", False))
    )
    return {"accepted": True, **res}

@router.post("/sessions/{session_id}/jury/disrupt", status_code=202)
@router.post("/sessions/{session_id}/jury", status_code=202)
async def jury_disrupt(session_id: str, request: Request, body: dict):
    session = SESSION_MANAGER.get_or_create(session_id)
    
    action = body.get("action", {})
    asset_id = action.get("id") or body.get("asset_id")
    action_type = action.get("type") or body.get("type")
    duration_hours = action.get("duration_hours") or body.get("duration_h")
    recipe_id = action.get("recipe_id")
    jury_name = body.get("jury_name")
    
    device_id = body.get("device_id") or request.headers.get("X-Jury-Device")
    host = request.client.host if request.client else "local"
    device_key = device_id or f"{host}:{jury_name or 'anon'}"
    
    try:
        session.check_jury_limits(device_key)
    except JuryRateLimitError as err:
        return JSONResponse(status_code=err.status_code, content={"detail": err.message_es, "code": err.code, "message_es": err.message_es})
        
    wait_for_opts = bool(body.get("wait_for_options", False))
    
    is_recipe = False
    target_recipe_id = None
    if action_type == "stress_recipe":
        is_recipe = True
        target_recipe_id = recipe_id
    elif any(r["id"] == asset_id for r in session.catalog.get("stress_recipes", [])):
        is_recipe = True
        target_recipe_id = asset_id

    if is_recipe:
        recipe = next((r for r in session.catalog.get("stress_recipes", []) if r["id"] == target_recipe_id), None)
        if recipe:
            allowed = max(0, 2 - len(session.active_events))
            events_to_trigger = recipe.get("events", [])[:allowed]
            for ev in events_to_trigger:
                await session.disrupt(
                    ev.get("id"),
                    duration_h=ev.get("duration_hours"),
                    source="jury",
                    explicit_type=ev.get("type"),
                    jury_name=jury_name,
                    wait_for_options=wait_for_opts
                )
        return {"accepted": True}
    else:
        res = await session.disrupt(
            asset_id,
            duration_h=duration_hours,
            source="jury",
            jury_name=jury_name,
            wait_for_options=wait_for_opts,
            explicit_type=action_type
        )
        return {"accepted": True, **res}

@router.post("/sessions/{session_id}/decide", status_code=202)
@router.post("/sessions/{session_id}/decision", status_code=202)
async def decide(session_id: str, body: dict):
    session = SESSION_MANAGER.get_or_create(session_id)
    ev = await session.decide(
        body.get("incident_id"),
        body.get("option_id"),
        body.get("decision"),
        by="operator"
    )
    return {"accepted": True, "event": ev}

@router.post("/sessions/{session_id}/autonomy", status_code=202)
async def autonomy(session_id: str, body: dict):
    session = SESSION_MANAGER.get_or_create(session_id)
    enabled = await session.set_autonomy(bool(body.get("enabled")))
    return {"accepted": True, "autonomy": enabled}

@router.post("/sessions/{session_id}/reset", status_code=202)
async def reset_session(session_id: str):
    session = SESSION_MANAGER.get_or_create(session_id)
    snap = await session.reset()
    return {"accepted": True, "snapshot": snap}

@router.get("/sessions/{session_id}/qr.svg")
def get_qr(session_id: str, request: Request):
    base_url = (os.getenv("PUBLIC_ORIGIN") or "https://andes-a38.pages.dev").rstrip("/")
    target_url = f"{base_url}/jurado?s={session_id}"
    svg = render_qr_svg(target_url)
    return Response(content=svg, media_type="image/svg+xml")

@router.get("/sessions/{session_id}/report")
def get_report(session_id: str, format: str = "md"):
    session = SESSION_MANAGER.get_or_create(session_id)
    try:
        from backend.live.report import render_session_report
        content = render_session_report(session, format)
    except ImportError:
        content = f"# Live Ops Report for {session_id}\n\nNo report generator available."
        if format == "html":
            content = f"<html><body><h1>Live Ops Report for {session_id}</h1><p>No report generator available.</p></body></html>"

    media_type = "text/html; charset=utf-8" if format == "html" else "text/markdown; charset=utf-8"
    return Response(content=content, media_type=media_type)
