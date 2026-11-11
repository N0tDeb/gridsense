"""Routes for portable regression, electrical reference and event experiments."""

import json
from typing import Literal
from fastapi import HTTPException
from fastapi.responses import Response
from .cases import RegressionInput, case_from_incident, presets
from .domain import Record
from .published_reference import validate_published_reference as validate_reference
from .regression import run_regression, rerun_regression, replay_regression
from .temporal import TemporalInput, run_temporal, replay_temporal


class RerunInput(Record):
    candidate: Literal["nominal-v1", "guarded-v1", "hold-v1"] = "guarded-v1"


def register(app, compute):
    def get(run_id):
        try:
            return app.state.store.get_verification(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Verification run not found") from exc

    def save(record):
        app.state.store.save_verification(record)
        return record

    @app.get("/api/verification/presets")
    def examples():
        return presets()

    @app.get("/api/verification/cases/from-incident/{incident_id}")
    def import_case(incident_id: str):
        try:
            return case_from_incident(app.state.store.get(incident_id))
        except KeyError as exc:
            raise HTTPException(404, "Incident not found") from exc

    @app.get("/api/verification/reference")
    async def reference():
        return await compute(validate_reference)

    @app.post("/api/verification/regressions", status_code=201)
    async def regress(request: RegressionInput):
        return save(await compute(run_regression, request))

    @app.post("/api/verification/temporal", status_code=201)
    async def temporal(request: TemporalInput):
        return save(await compute(run_temporal, request))

    @app.get("/api/verification/records")
    def history():
        return app.state.store.list_verifications()

    @app.get("/api/verification/records/{run_id}")
    def read(run_id: str):
        return get(run_id)

    @app.post("/api/verification/records/{run_id}/rerun", status_code=201)
    async def rerun(run_id: str, request: RerunInput):
        previous = get(run_id)
        if previous["kind"] != "regression":
            raise HTTPException(
                422, "Only a controller regression supports cross-version comparison"
            )
        return save(await compute(rerun_regression, previous, request.candidate))

    @app.post("/api/verification/records/{run_id}/replay")
    async def replay(run_id: str):
        record = get(run_id)
        return await compute(
            replay_regression if record["kind"] == "regression" else replay_temporal, record
        )

    @app.get("/api/verification/records/{run_id}/export")
    def export(run_id: str):
        record = get(run_id)
        return Response(
            json.dumps(record, indent=2, allow_nan=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="gridsense-{record["kind"]}-{record["id"]}.json"'
            },
        )
