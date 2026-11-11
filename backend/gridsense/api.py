"""Local FastAPI service with a process pool for native simulation work."""

import asyncio
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import pyarrow as pa
import pyarrow.parquet as pq
from .domain import ReviewInput, Scenario, SweepInput
from . import __version__
from .electrical import ElectricalEngine
from .failure_search import SearchInput, replay_search, run_search
from .network import initial_state, load_network
from .service import evaluate, replay, sweep, utc_now
from .storage import IncidentStore
from .verification_api import register as register_verification
from .session_store import SessionStore
from .session_api import pace_sessions, register as register_sessions


async def compute_in_pool(app, function, *args):
    """Keep a slot until native work ends, even if the HTTP caller disconnects."""
    if not getattr(app.state, "worker_pool_available", True):
        raise HTTPException(503, "Simulation worker unavailable. Restart the local server.")
    try:
        await asyncio.wait_for(app.state.slots.acquire(), timeout=2)
    except TimeoutError as exc:
        raise HTTPException(503, "Simulation workers are busy. Try again shortly.") from exc
    try:
        future = asyncio.get_running_loop().run_in_executor(app.state.pool, function, *args)
    except BrokenProcessPool as exc:
        app.state.worker_pool_available = False
        app.state.slots.release()
        raise HTTPException(
            503, "Simulation worker unavailable. Restart the local server."
        ) from exc
    except BaseException:
        app.state.slots.release()
        raise

    def completed(result):
        app.state.slots.release()
        # A disconnected caller will not retrieve a later worker exception.
        if not result.cancelled():
            if isinstance(result.exception(), BrokenProcessPool):
                app.state.worker_pool_available = False

    future.add_done_callback(completed)
    try:
        return await asyncio.shield(future)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except BrokenProcessPool as exc:
        app.state.worker_pool_available = False
        raise HTTPException(
            503, "Simulation worker unavailable. Restart the local server."
        ) from exc


def create_app(data_dir: str | Path | None = None, static_dir: str | Path | None = None) -> FastAPI:
    data_path = Path(data_dir or os.environ.get("GRIDSENSE_DATA_DIR", "var"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = IncidentStore(data_path / "gridsense.sqlite3")
        app.state.sessions = SessionStore(data_path / "gridsense.sqlite3")
        app.state.sessions.restart_paused()
        readiness = ElectricalEngine()
        check = readiness.solve(initial_state({"a": 1, "b": 1, "c": 1}))
        if not check.converged:
            raise RuntimeError("OpenDSS readiness solve failed")
        app.state.solver_version = readiness.version
        app.state.pool = ProcessPoolExecutor(
            max_workers=2,
            mp_context=multiprocessing.get_context("spawn"),
            # The pinned native wrapper retains contexts. End each bounded job
            # in its worker so repeated requests cannot accumulate that memory.
            max_tasks_per_child=1,
        )
        app.state.slots = asyncio.Semaphore(2)
        app.state.worker_pool_available = True
        pacing = asyncio.create_task(pace_sessions(app.state.sessions, compute))
        try:
            yield
        finally:
            pacing.cancel()
            try:
                await pacing
            except asyncio.CancelledError:
                pass
            app.state.pool.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(
        title="GridSense",
        version=__version__,
        lifespan=lifespan,
        description="Simulate grid disturbances and test restoration decisions with OpenDSS. For local use.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    async def compute(function, *args):
        return await compute_in_pool(app, function, *args)

    def get_incident(incident_id: str):
        try:
            return app.state.store.get(incident_id)
        except KeyError as exc:
            raise HTTPException(404, "Incident not found") from exc

    @app.get("/api/health")
    def health():
        available = app.state.worker_pool_available
        payload = {
            "status": "ready" if available else "unavailable",
            "solver": "OpenDSS",
            "solver_version": app.state.solver_version,
            "version": __version__,
            "mode": "simulation",
            "workers": 2 if available else 0,
        }
        if not available:
            payload["detail"] = "Simulation worker unavailable. Restart the local server."
        return JSONResponse(payload, status_code=200 if available else 503)

    @app.get("/api/network")
    def network():
        return load_network()

    @app.get("/api/presets")
    def presets():
        return [
            {
                "id": "stale",
                "description": "A stale west reading can conceal an overloaded backup route.",
                "scenario": Scenario().model_dump(),
            },
            {
                "id": "fresh",
                "description": "Current readings make the west route a feasible choice.",
                "scenario": Scenario(
                    title="Fresh telemetry · west available",
                    load_b=0.7,
                    reported_b=0.7,
                    load_c=1.1,
                    telemetry_age_s=0,
                    uncertainty_pct=0,
                ).model_dump(),
            },
            {
                "id": "partial",
                "description": "Both donors are busy. Compare critical-only restoration with full restoration.",
                "scenario": Scenario(
                    title="Constrained donors · critical priority",
                    load_b=1.65,
                    reported_b=1.65,
                    load_c=1.6,
                    telemetry_age_s=0,
                    uncertainty_pct=0,
                ).model_dump(),
            },
        ]

    @app.post("/api/incidents", status_code=201)
    async def run_incident(scenario: Scenario):
        incident = await compute(evaluate, scenario)
        app.state.store.save(incident)
        return incident

    @app.get("/api/incidents")
    def list_incidents(limit: int = Query(100, ge=1, le=200)):
        return app.state.store.list_incidents(limit)

    @app.get("/api/incidents/{incident_id}")
    def read_incident(incident_id: str):
        return get_incident(incident_id)

    @app.post("/api/incidents/{incident_id}/replay")
    async def replay_incident(incident_id: str):
        return await compute(replay, get_incident(incident_id))

    @app.get("/api/incidents/{incident_id}/export")
    def export_incident(incident_id: str):
        data = get_incident(incident_id)
        return Response(
            json.dumps(data, indent=2, allow_nan=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="gridsense-{data["id"]}.json"'},
        )

    @app.get("/api/incidents/{incident_id}/reviews")
    def reviews(incident_id: str):
        get_incident(incident_id)
        return app.state.store.reviews(incident_id)

    @app.post("/api/incidents/{incident_id}/reviews", status_code=201)
    def add_review(incident_id: str, review: ReviewInput):
        get_incident(incident_id)
        return app.state.store.review(incident_id, utc_now(), review.verdict, review.note)

    @app.post("/api/sweeps", status_code=201)
    async def run_sweep(request: SweepInput):
        result = await compute(sweep, request)
        app.state.store.save_sweep(result)
        return result

    @app.get("/api/sweeps/{sweep_id}")
    def get_sweep(sweep_id: str):
        try:
            return app.state.store.get_sweep(sweep_id)
        except KeyError as exc:
            raise HTTPException(404, "Sweep not found") from exc

    @app.get("/api/sweeps/{sweep_id}/export")
    def export_sweep(sweep_id: str, format: str = Query("json", pattern="^(json|parquet)$")):
        data = get_sweep(sweep_id)
        headers = {
            "Content-Disposition": f'attachment; filename="gridsense-sweep-{data["id"]}.{format}"'
        }
        if format == "json":
            return Response(
                json.dumps(data, indent=2, allow_nan=False),
                media_type="application/json",
                headers=headers,
            )
        table = pa.Table.from_pylist(data["rows"])
        metadata = json.dumps(
            {k: v for k, v in data.items() if k != "rows"}, allow_nan=False
        ).encode()
        table = table.replace_schema_metadata({b"gridsense_manifest": metadata})
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        return Response(
            sink.getvalue().to_pybytes(),
            media_type="application/vnd.apache.parquet",
            headers=headers,
        )

    def get_search(search_id: str):
        try:
            return app.state.store.get_search(search_id)
        except KeyError as exc:
            raise HTTPException(404, "Failure search not found") from exc

    @app.post("/api/failure-searches", status_code=201)
    async def create_search(request: SearchInput):
        result = await compute(run_search, request)
        app.state.store.save_search(result)
        return result

    @app.get("/api/failure-searches")
    def list_searches(limit: int = Query(100, ge=1, le=200)):
        return app.state.store.list_searches(limit)

    @app.get("/api/failure-searches/{search_id}")
    def read_search(search_id: str):
        return get_search(search_id)

    @app.post("/api/failure-searches/{search_id}/replay")
    async def reproduce_search(search_id: str):
        return await compute(replay_search, get_search(search_id))

    @app.get("/api/failure-searches/{search_id}/export")
    def export_search(search_id: str):
        data = get_search(search_id)
        return Response(
            json.dumps(data, indent=2, allow_nan=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="gridsense-failure-{data["id"]}.json"'
            },
        )

    register_verification(app, compute)
    register_sessions(app, compute)

    # Unknown API paths must remain JSON 404s, including when the SPA is mounted.
    @app.api_route("/api/{path:path}", methods=["GET", "POST"], include_in_schema=False)
    def unknown_api(path: str):
        raise HTTPException(404, "API route not found")

    dist = (
        Path(static_dir)
        if static_dir
        else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return app


app = create_app()
