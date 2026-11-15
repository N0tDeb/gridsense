# HTTP API

FastAPI serves the dashboard and `/api` on one local origin after the frontend
build. Interactive schemas are at `/docs`; the machine-readable specification is
at `/openapi.json`. The route table below is derived from the actual application.
Public request models are strict Pydantic records; inspect OpenAPI for complete
field types, defaults and bounds.

## Routes

| Route | Operation |
| --- | --- |
| `GET /api/health` | Health |
| `GET /api/network` | Network |
| `GET /api/presets` | Presets |
| `POST /api/incidents` | Run Incident |
| `GET /api/incidents` | List Incidents |
| `GET /api/incidents/{incident_id}` | Read Incident |
| `POST /api/incidents/{incident_id}/replay` | Replay Incident |
| `GET /api/incidents/{incident_id}/export` | Export Incident |
| `GET /api/incidents/{incident_id}/reviews` | Reviews |
| `POST /api/incidents/{incident_id}/reviews` | Add Review |
| `POST /api/sweeps` | Run Sweep |
| `GET /api/sweeps/{sweep_id}` | Get Sweep |
| `GET /api/sweeps/{sweep_id}/export` | Export Sweep |
| `POST /api/failure-searches` | Create Search |
| `GET /api/failure-searches` | List Searches |
| `GET /api/failure-searches/{search_id}` | Read Search |
| `POST /api/failure-searches/{search_id}/replay` | Reproduce Search |
| `GET /api/failure-searches/{search_id}/export` | Export Search |
| `GET /api/verification/presets` | Examples |
| `GET /api/verification/cases/from-incident/{incident_id}` | Import Case |
| `GET /api/verification/reference` | Reference |
| `POST /api/verification/regressions` | Regress |
| `POST /api/verification/temporal` | Temporal |
| `GET /api/verification/records` | History |
| `GET /api/verification/records/{run_id}` | Read |
| `POST /api/verification/records/{run_id}/rerun` | Rerun |
| `POST /api/verification/records/{run_id}/replay` | Replay |
| `GET /api/verification/records/{run_id}/export` | Export |
| `GET /api/sessions` | History |
| `POST /api/sessions` | Create |
| `GET /api/sessions/{session_id}` | Read |
| `GET /api/sessions/{session_id}/simulation` | Simulation |
| `POST /api/sessions/{session_id}/actions` | Action |
| `GET /api/sessions/{session_id}/export` | Export |
| `POST /api/sessions/{session_id}/replay` | Replay |

## Examples

Start the local server using SETUP.md. Create a snapshot incident:

```bash
curl -X POST http://127.0.0.1:8000/api/incidents \
  -H 'Content-Type: application/json' -d '{}'
```

The response contains its ID, actual observations/decisions, native electrical
outcomes and source/solver manifest. Use that ID with the read, export, replay
and append-only review endpoints. The empty object selects the declared default
stale-reading scenario; it is not an empty electrical model.

Create a live session with explicit control:

```bash
curl -X POST http://127.0.0.1:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"create-demo-1","config":{"horizon_s":30,"control":{"policy":"nominal"}}}'
```

Submit actions to `/api/sessions/SESSION_ID/actions` with the latest receipt's
revision. For a first paused session, a step request is:

```json
{"request_id":"step-demo-1","expected_revision":0,"operation":"step"}
```

Use a new request ID for a new operation. If its response is lost, retry the
identical request/ID. Reusing an ID with another payload is rejected. The current
revision comes from the server; concurrent changes can make zero stale.
See [live sessions](LIVE_SESSIONS.md) for scheduling, play/pause/rates and exports.

## Boundaries and errors

| Response | Meaning |
| --- | --- |
| 200 / 201 | Read or completed operation / created saved record |
| 404 | Unknown record or API route |
| 409 | Incompatible replay, conflicting revision/request or rejected simulation operation |
| 422 | Request schema, bounds or scenario validation failure |
| 503 | Simulation capacity timeout, unavailable worker pool or unreadable session store |

A completed HTTP request can contain a failed controller contract or a search
with no discovered failure. Inspect its explicit status/accepted/passed fields;
HTTP success does not certify restoration or safety. Unknown electrical values,
failed actuator feedback and exhausted computation are recorded distinctly.

The ordinary session route exposes delivered observations/controller state.
`/simulation` and exports expose evaluator truth/future events for analysis.
This separation prevents controller leakage inside the engine; it is not access
control against the local operator. No route executes supplied Python, DSS
commands or arbitrary client filesystem paths. The two-worker service accepts
bounded jobs. It is not an authenticated multiuser or resumable job service.

JSON exports preserve manifests and integrity fields. Sweep Parquet exports
carry the manifest in schema metadata. Replay distinguishes historical source-
matching reproduction from a new evaluation under the current controller.
[Storage](DATA_MODEL.md), [architecture](ARCHITECTURE.md), [security](../SECURITY.md).
