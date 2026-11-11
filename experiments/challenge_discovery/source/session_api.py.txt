"""Headless session routes and best-effort pacing of the backend logical clock."""

import asyncio
import json
import logging
import sqlite3

from fastapi import HTTPException
from fastapi.responses import Response

from .session_store import (
    CreateSession,
    SessionMutation,
    create_session,
    mutate_session,
    replay_episode,
    tick_session,
)

logger = logging.getLogger(__name__)


async def pace_sessions(store, compute):
    due = {}
    clock = asyncio.get_running_loop().time
    while True:
        try:
            rows = store.running()
        except sqlite3.Error:
            logger.exception("Session clock cannot read storage; no tick was attempted")
            await asyncio.sleep(1)
            continue
        active = {row["id"] for row in rows}
        due = {key: value for key, value in due.items() if key in active}
        for row in rows:
            session_id, rate = row["id"], row["rate"]
            if session_id not in due or due[session_id][0] != rate:
                due[session_id] = (rate, clock() + 1 / rate)
            if clock() < due[session_id][1]:
                continue
            try:
                await compute(tick_session, str(store.path), session_id, row["revision"])
            except Exception as exc:
                detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                conflict = isinstance(exc, KeyError) or (
                    (
                        isinstance(exc, ValueError)
                        or isinstance(exc, HTTPException)
                        and exc.status_code == 409
                    )
                    and detail.startswith("Stale session revision;")
                )
                if not conflict:
                    logger.exception("Session tick failed for %s", session_id)
                    reason = (
                        str(exc.detail)
                        if isinstance(exc, HTTPException)
                        else "Session worker failed; inspect the server log before resuming"
                    )
                    try:
                        store.system_action(session_id, row["revision"], "worker_error", reason)
                    except (KeyError, ValueError):
                        pass  # A concurrent committed mutation already won.
                    except sqlite3.Error:
                        logger.exception("Could not persist the session pause")
            # Pace from completion. Slow work never produces catch-up ticks.
            due[session_id] = (rate, clock() + 1 / rate)
        await asyncio.sleep(0.05)


def register(app, compute):
    async def work(function, *args):
        try:
            return await compute(function, *args)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        except sqlite3.Error as exc:
            raise HTTPException(
                503, "Session storage is unavailable; no partial tick is accepted"
            ) from exc

    def get(session_id, *, simulation=False):
        try:
            return app.state.sessions.read(session_id, simulation=simulation)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        except sqlite3.Error as exc:
            raise HTTPException(503, "Session storage is unavailable") from exc

    def exported(session_id):
        try:
            return app.state.sessions.export(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        except sqlite3.Error as exc:
            raise HTTPException(503, "Session storage is unavailable") from exc

    @app.post("/api/sessions", status_code=201)
    async def create(request: CreateSession):
        return await work(create_session, str(app.state.sessions.path), request)

    @app.get("/api/sessions")
    def history():
        try:
            return app.state.sessions.list()
        except sqlite3.Error as exc:
            raise HTTPException(503, "Session storage is unavailable") from exc

    @app.get("/api/sessions/{session_id}")
    def read(session_id: str):
        return get(session_id)

    @app.get("/api/sessions/{session_id}/simulation")
    def simulation(session_id: str):
        """Explicit evaluator view; never an input to measurement-based rules."""
        return get(session_id, simulation=True)

    @app.post("/api/sessions/{session_id}/actions")
    async def action(session_id: str, request: SessionMutation):
        return await work(mutate_session, str(app.state.sessions.path), session_id, request)

    @app.get("/api/sessions/{session_id}/export")
    def export(session_id: str):
        record = exported(session_id)
        return Response(
            json.dumps(record, indent=2, allow_nan=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="gridsense-session-{record["id"]}.json"'
            },
        )

    @app.post("/api/sessions/{session_id}/replay")
    async def replay(session_id: str):
        return await work(replay_episode, exported(session_id))
