import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from backend.config import Settings
from backend.executor import ExecutionError, isolated
from backend.models import (
    Decision,
    RunDocument,
    RunRequest,
    Scenario,
    ScenarioList,
    SolveRequest,
    SolveResponse,
    ValidateRequest,
    Validation,
    wire,
)
from backend.runtime import available, scenario_catalog
from backend.store import Conflict, QueueFull, Store
from backend.worker import failure, fingerprint

log = logging.getLogger("gridpilot")


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings.db_path)
    scenarios = scenario_catalog(settings)
    direct_compute_lock = asyncio.Lock()

    async def work_loop():
        while True:
            claimed = store.claim()
            if claimed is None:
                await asyncio.sleep(0.1)
                continue
            run_id, request = claimed
            payload = dict(
                operation="investigate",
                scenario=request["_scenario_snapshot"],
                evidence_snapshot=request.get("_evidence_snapshot"),
                options=request["settings"],
                execution_mode=request["execution_mode"],
            )
            try:
                async with direct_compute_lock:
                    result = await isolated(payload, settings)
            except ExecutionError as exc:
                result = failure(exc.code, exc.message)
            try:
                store.finish(run_id, result)
            except (ValueError, TypeError):
                store.finish(
                    run_id,
                    failure(
                        "invalid_result_contract", "Worker result did not satisfy the run contract"
                    ),
                )

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        task = asyncio.create_task(work_loop()) if settings.worker_enabled else None
        app.state.worker_task = task
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="GridPilot API", version="1.0.0", lifespan=lifespan)
    app.state.store = store
    app.state.worker_task = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
        expose_headers=["Location", "ETag", "X-Request-ID", "Content-Disposition"],
    )

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request_id = str(uuid4())
        # Consume with a hard limit, including chunked requests, before JSON parsing.
        if request.method == "POST":
            chunks, length = [], 0
            async for chunk in request.stream():
                length += len(chunk)
                if length > 262144:
                    return JSONResponse(
                        {"error": {"code": "body_too_large", "message": "Request exceeds 256 KiB"}},
                        status_code=413,
                    )
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        log.info(
            "request id=%s method=%s status=%s", request_id, request.method, response.status_code
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic's default includes original input: never echo potential secrets.
        errors = [{"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            {"error": {"code": "invalid_request", "details": errors}}, status_code=422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {"error": {"code": f"http_{exc.status_code}", "message": exc.detail}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(ExecutionError)
    async def execution_error(request, exc):
        code = (
            504
            if exc.code == "execution_timeout"
            else 503
            if exc.code == "adapter_unavailable"
            else 502
        )
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=code)

    def authorize(authorization: str | None = Header(default=None)):
        if settings.api_token and not secrets.compare_digest(
            authorization or "", f"Bearer {settings.api_token}"
        ):
            raise HTTPException(
                401, "A valid demo API token is required", headers={"WWW-Authenticate": "Bearer"}
            )

    def scenario(scenario_id):
        if scenario_id not in scenarios:
            raise HTTPException(404, "Unknown scenario")
        return scenarios[scenario_id]

    @app.get("/api/health")
    async def health():
        adapters = {
            "agent": available(settings.agent_callable),
            "solver": available(settings.solve_callable),
            "validator": available(settings.validate_callable),
        }
        return dict(
            status="ok",
            schema_version="1.0.0",
            scenarios=len(scenarios),
            replay_available=all(
                (settings.data_dir / "demo" / f"{s.scenario_id}.replay.json").is_file()
                for s in scenarios.values()
            ),
            live_ready=all(adapters.values()),
            adapters=adapters,
            auth_required=bool(settings.api_token),
            worker_enabled=app.state.worker_task is not None and not app.state.worker_task.done(),
            readiness_scope="Local adapters and fixtures; provider connectivity is not probed",
        )

    @app.get("/api/ready")
    async def ready(mode: str = "replay"):
        state = await health()
        if mode not in ("replay", "live"):
            raise HTTPException(422, "mode must be replay or live")
        if (
            not state["worker_enabled"]
            or not state["live_ready" if mode == "live" else "replay_available"]
        ):
            raise HTTPException(503, f"{mode} execution is not ready")
        return {"ready": True, "mode": mode}

    @app.get("/api/scenario", response_model=Scenario | ScenarioList)
    async def get_scenario(scenario_id: str | None = None):
        if scenario_id:
            return wire(scenario(scenario_id))
        return {"schema_version": "1.0.0", "scenarios": [wire(s) for s in scenarios.values()]}

    @app.get("/api/evidence/{evidence_id}")
    async def evidence(evidence_id: str):
        allowed = {s.provenance.evidence_id for s in scenarios.values()}
        if evidence_id not in allowed:
            raise HTTPException(404, "Unknown evidence")
        return json.loads(
            (settings.data_dir / "processed" / f"{evidence_id}.evidence.json").read_text()
        )

    @app.post("/api/optimise", response_model=SolveResponse, dependencies=[Depends(authorize)])
    async def optimise(body: SolveRequest):
        if direct_compute_lock.locked():
            raise HTTPException(429, "Compute worker is busy", headers={"Retry-After": "5"})
        async with direct_compute_lock:
            return await isolated(
                dict(
                    operation="solve",
                    scenario=wire(scenario(body.scenario_id)),
                    options=wire(body.options),
                ),
                settings,
            )

    @app.post("/api/validate", response_model=Validation, dependencies=[Depends(authorize)])
    async def validate(body: ValidateRequest):
        if direct_compute_lock.locked():
            raise HTTPException(429, "Compute worker is busy", headers={"Retry-After": "5"})
        async with direct_compute_lock:
            return await isolated(
                dict(
                    operation="validate",
                    scenario=wire(scenario(body.scenario_id)),
                    options=wire(body.options),
                    solution=wire(body.solution),
                ),
                settings,
            )

    @app.post(
        "/api/agent/run",
        status_code=202,
        response_model=RunDocument,
        dependencies=[Depends(authorize)],
    )
    async def run(
        body: RunRequest, idempotency_key: str | None = Header(default=None, max_length=120)
    ):
        selected = scenario(body.scenario_id)
        if body.execution_mode == "live" and not all(
            available(x)
            for x in (settings.agent_callable, settings.solve_callable, settings.validate_callable)
        ):
            raise HTTPException(
                503,
                "Live agent, solver and validator must all be installed; use execution_mode=replay for offline demonstration",
            )
        request_json = wire(body)
        stored_request = {**request_json, "_scenario_snapshot": wire(selected)}
        if selected.provenance.evidence_id:
            try:
                stored_request["_evidence_snapshot"] = json.loads(
                    (
                        settings.data_dir
                        / "processed"
                        / f"{selected.provenance.evidence_id}.evidence.json"
                    ).read_text()
                )
            except (OSError, ValueError):
                raise HTTPException(
                    503, "Historical evidence is unavailable; synthetic-demo-001 remains available"
                ) from None
        try:
            doc, created = store.enqueue(
                stored_request,
                fingerprint({"request": request_json, "scenario": wire(selected)}),
                idempotency_key,
                settings.queue_limit,
            )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except QueueFull:
            raise HTTPException(
                429, "Investigation queue is full", headers={"Retry-After": "5"}
            ) from None
        return JSONResponse(
            doc,
            status_code=202 if created else 200,
            headers={"Location": f"/api/agent/runs/{doc['run_id']}"},
        )

    @app.get(
        "/api/agent/runs/{run_id}", response_model=RunDocument, response_model_exclude_unset=True
    )
    async def get_run(run_id: str):
        try:
            return store.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown investigation") from None

    @app.post(
        "/api/agent/runs/{run_id}/decision",
        response_model=RunDocument,
        response_model_exclude_unset=True,
        dependencies=[Depends(authorize)],
    )
    async def decide(run_id: str, body: Decision):
        try:
            return store.decide(run_id, body)
        except KeyError:
            raise HTTPException(404, "Unknown investigation") from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/agent/runs/{run_id}/report")
    async def report(run_id: str):
        doc = await get_run(run_id)
        if doc["status"] not in ("completed", "failed"):
            raise HTTPException(409, "Report is available after investigation terminates")
        content = json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False).encode()
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="gridpilot-{doc["run_id"]}.json"',
                "ETag": f'"{hashlib.sha256(content).hexdigest()}"',
            },
        )

    return app
