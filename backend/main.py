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
from pydantic import ValidationError

from backend.config import Settings
from backend.live import gemini_configured
from backend.executor import ExecutionError, isolated
from backend.models import (
    Decision,
    RunDocument,
    RunRequest,
    Scenario,
    SolveResponse,
    SolveRequest,
    ValidateRequest,
    wire,
)
from backend.runtime import available, scenario_catalog, native_scenario_catalog
from backend.native_models import (
    NativeCompareRequest,
    NativeRunDocument,
    NativeRunRequest,
    NativeScenario,
    NativeScenarioResponse,
    NativeSolveRequest,
    NativeValidateRequest,
    NativeSolution,
)
from backend.store import Conflict, QueueFull, Store
from backend.worker import failure, fingerprint

log = logging.getLogger("gridpilot")


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings.db_path)
    scenarios = scenario_catalog(settings)
    native_scenarios = native_scenario_catalog(settings)
    direct_compute_lock = asyncio.Lock()

    async def work_loop():
        while True:
            claimed = store.claim()
            if claimed is None:
                await asyncio.sleep(0.1)
                continue
            run_id, request = claimed
            payload = dict(
                operation="native_investigate"
                if request.get("_protocol") == "2.0.0"
                else "investigate",
                scenario=request["_scenario_snapshot"],
                evidence_snapshot=request.get("_evidence_snapshot"),
                options=request["settings"],
                execution_mode=request["execution_mode"],
                settings=request["settings"],
                governance_mode=request.get("governance_mode", "operator_approval"),
            )
            try:
                async with direct_compute_lock:
                    result = await isolated(payload, settings)
            except ExecutionError as exc:
                if (
                    request.get("_protocol") == "2.0.0"
                    and request["execution_mode"] == "live"
                    and request["settings"].get("allow_cached_fallback", True)
                    and exc.code
                    in (
                        "execution_timeout",
                        "adapter_unavailable",
                        "adapter_failed",
                        "gemini_credentials_missing",
                    )
                ):
                    try:
                        result = await isolated({**payload, "execution_mode": "replay"}, settings)
                        result.update(
                            requested_execution_mode="live",
                            fallback=dict(
                                reason=exc.code,
                                message=exc.message,
                                mode="replay",
                                live_gemini=False,
                            ),
                        )
                    except ExecutionError as fallback_error:
                        result = failure(fallback_error.code, fallback_error.message)
                else:
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

    app = FastAPI(title="GridPilot API", version="2.0.0", lifespan=lifespan)
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
        if scenario_id not in scenarios and scenario_id not in native_scenarios:
            raise HTTPException(404, "Unknown scenario")
        return native_scenarios.get(scenario_id) or scenarios[scenario_id]

    def parse(model, body):
        try:
            return model.model_validate(
                body.model_dump(mode="json", by_alias=True, exclude_unset=True)
            )
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from None

    @app.get("/api/health")
    async def health():
        adapters = {
            "agent": available(settings.agent_callable),
            "solver": available(settings.solve_callable),
            "validator": available(settings.validate_callable),
        }
        credentials_configured = gemini_configured()
        return dict(
            status="ok",
            schema_version="2.0.0",
            scenarios=len(scenarios) + len(native_scenarios),
            default_scenario_id="chile-sen-5node-demo",
            replay_available=all(
                (settings.data_dir / "demo" / f"{s.scenario_id}.replay.json").is_file()
                for s in scenarios.values()
            )
            and all(
                (settings.data_dir / "demo" / f"{s.scenario_id}.native-replay.json").is_file()
                for s in native_scenarios.values()
            ),
            live_ready=all(adapters.values()) and credentials_configured,
            gemini_credentials_configured=credentials_configured,
            adapters=adapters,
            auth_required=bool(settings.api_token),
            worker_enabled=app.state.worker_task is not None and not app.state.worker_task.done(),
            readiness_scope="Local adapters and fixtures; provider connectivity is not probed",
        )

    @app.get("/api/ready")
    async def ready(mode: str = "replay"):
        state = await health()
        if mode not in ("replay", "live", "deterministic"):
            raise HTTPException(422, "mode must be replay, live or deterministic")
        if not state["worker_enabled"] or not (
            state["live_ready"]
            if mode == "live"
            else all(state["adapters"][k] for k in ("solver", "validator"))
            if mode == "deterministic"
            else state["replay_available"]
        ):
            raise HTTPException(503, f"{mode} execution is not ready")
        return {"ready": True, "mode": mode}

    @app.get("/api/scenario", response_model=NativeScenarioResponse | Scenario)
    async def get_scenario(scenario_id: str | None = None):
        selected = scenario(scenario_id or "chile-sen-5node-demo")
        result = wire(selected)
        if isinstance(selected, NativeScenario):
            from optimisation import modification_menu

            result["modification_menu"] = modification_menu(result)
        return result

    @app.get("/api/scenarios")
    async def list_scenarios():
        return dict(
            schema_version="2.0.0",
            default_scenario_id="chile-sen-5node-demo",
            scenarios=[wire(s) for s in [*native_scenarios.values(), *scenarios.values()]],
        )

    @app.get("/api/evidence/{evidence_id}")
    async def evidence(evidence_id: str):
        allowed = {s.provenance.evidence_id for s in scenarios.values()} | {
            s.provenance.get("evidence_id") for s in native_scenarios.values()
        }
        if evidence_id not in allowed:
            raise HTTPException(404, "Unknown evidence")
        return json.loads(
            (settings.data_dir / "processed" / f"{evidence_id}.evidence.json").read_text()
        )

    @app.post(
        "/api/optimise",
        response_model=NativeSolution | SolveResponse,
        dependencies=[Depends(authorize)],
    )
    async def optimise(body: NativeSolveRequest | SolveRequest):
        selected = scenario(body.scenario_id)
        native = isinstance(selected, NativeScenario)
        parsed = parse(NativeSolveRequest if native else SolveRequest, body)
        if direct_compute_lock.locked():
            raise HTTPException(429, "Compute worker is busy", headers={"Retry-After": "5"})
        async with direct_compute_lock:
            return await isolated(
                dict(
                    operation="native_solve" if native else "solve",
                    scenario=wire(selected),
                    **{k: v for k, v in wire(parsed).items() if k != "scenario_id"},
                ),
                settings,
            )

    @app.post("/api/validate", dependencies=[Depends(authorize)])
    async def validate(body: NativeValidateRequest | ValidateRequest):
        selected = scenario(body.scenario_id)
        native = isinstance(selected, NativeScenario)
        parsed = parse(NativeValidateRequest if native else ValidateRequest, body)
        if direct_compute_lock.locked():
            raise HTTPException(429, "Compute worker is busy", headers={"Retry-After": "5"})
        async with direct_compute_lock:
            return await isolated(
                dict(
                    operation="native_validate" if native else "validate",
                    scenario=wire(selected),
                    **{k: v for k, v in wire(parsed).items() if k != "scenario_id"},
                ),
                settings,
            )

    @app.post("/api/compare", dependencies=[Depends(authorize)])
    async def compare_native(body: NativeCompareRequest):
        selected = scenario(body.scenario_id)
        if not isinstance(selected, NativeScenario):
            raise HTTPException(422, "Native comparison requires a v2 scenario")
        if (
            body.baseline.get("scenario_id") != body.scenario_id
            or body.candidate.get("scenario_id") != body.scenario_id
        ):
            raise HTTPException(422, "Compared results must belong to the requested scenario")
        if direct_compute_lock.locked():
            raise HTTPException(429, "Compute worker is busy", headers={"Retry-After": "5"})
        async with direct_compute_lock:
            return await isolated(
                dict(
                    operation="native_compare",
                    scenario=wire(selected),
                    baseline=body.baseline,
                    candidate=body.candidate,
                ),
                settings,
            )

    @app.post(
        "/api/agent/run",
        status_code=202,
        response_model=RunDocument | NativeRunDocument,
        dependencies=[Depends(authorize)],
    )
    async def run(
        body: NativeRunRequest | RunRequest,
        idempotency_key: str | None = Header(default=None, max_length=120),
    ):
        selected = scenario(body.scenario_id)
        native = isinstance(selected, NativeScenario)
        body = parse(NativeRunRequest if native else RunRequest, body)
        if (
            body.execution_mode == "live"
            and not (native and body.settings.allow_cached_fallback)
            and (
                not gemini_configured()
                or not all(
                    available(x)
                    for x in (
                        settings.agent_callable,
                        settings.solve_callable,
                        settings.validate_callable,
                    )
                )
            )
        ):
            raise HTTPException(
                503,
                "Live mode requires Gemini credentials and installed agent/solver/validator; no live execution was started",
            )
        request_json = wire(body)
        stored_request = {**request_json, "_scenario_snapshot": wire(selected)}
        if native:
            from backend.native_service import computational_settings

            try:
                computational_settings(wire(selected), request_json["settings"])
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            stored_request["_protocol"] = "2.0.0"
        evidence_id = (
            selected.provenance.get("evidence_id") if native else selected.provenance.evidence_id
        )
        if evidence_id:
            try:
                stored_request["_evidence_snapshot"] = json.loads(
                    (settings.data_dir / "processed" / f"{evidence_id}.evidence.json").read_text()
                )
            except (OSError, ValueError):
                if native and selected.mode == "synthetic":
                    stored_request["_evidence_snapshot"] = None
                else:
                    raise HTTPException(
                        503,
                        "Historical evidence is unavailable; synthetic-demo-001 remains available",
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
        "/api/agent/runs/{run_id}",
        response_model=RunDocument | NativeRunDocument,
        response_model_exclude_unset=True,
    )
    async def get_run(run_id: str):
        try:
            return store.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown investigation") from None

    @app.post(
        "/api/agent/runs/{run_id}/decision",
        response_model=RunDocument | NativeRunDocument,
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
        if doc["status"] not in ("completed", "failed", "infeasible"):
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
