"""Store incident snapshots and append-only review notes in SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class IncidentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, title TEXT NOT NULL,
                    policy TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, verdict TEXT NOT NULL, note TEXT NOT NULL,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id)
                );
                CREATE TABLE IF NOT EXISTS sweeps (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failure_searches (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, policy TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS verification_runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL,
                    title TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, incident: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO incidents VALUES (?, ?, ?, ?, ?)",
                (
                    incident["id"],
                    incident["created_at"],
                    incident["scenario"]["title"],
                    incident["scenario"]["policy"],
                    json.dumps(incident, allow_nan=False),
                ),
            )

    def get(self, incident_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise KeyError(incident_id)
        return json.loads(row["payload"])

    def list_incidents(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id, created_at, title, policy FROM incidents ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            ]

    def review(self, incident_id: str, at: str, verdict: str, note: str):
        self.get(incident_id)
        with self.connect() as db:
            db.execute(
                "INSERT INTO reviews (incident_id, created_at, verdict, note) VALUES (?, ?, ?, ?)",
                (incident_id, at, verdict, note),
            )
        return self.reviews(incident_id)

    def reviews(self, incident_id: str) -> list[dict]:
        self.get(incident_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id, created_at, verdict, note FROM reviews WHERE incident_id=? ORDER BY id",
                    (incident_id,),
                )
            ]

    def save_sweep(self, sweep: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO sweeps VALUES (?, ?, ?)",
                (sweep["id"], sweep["created_at"], json.dumps(sweep, allow_nan=False)),
            )

    def get_sweep(self, sweep_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM sweeps WHERE id=?", (sweep_id,)).fetchone()
        if row is None:
            raise KeyError(sweep_id)
        return json.loads(row["payload"])

    def save_search(self, search: dict):
        """Save the search and its two evidence incidents in one transaction."""
        incidents = {
            i["id"]: i for i in (search["original_incident"], search["reduced_incident"]) if i
        }
        with self.connect() as db:
            for incident in incidents.values():
                db.execute(
                    "INSERT INTO incidents VALUES (?, ?, ?, ?, ?)",
                    (
                        incident["id"],
                        incident["created_at"],
                        incident["scenario"]["title"],
                        incident["scenario"]["policy"],
                        json.dumps(incident, allow_nan=False),
                    ),
                )
            db.execute(
                "INSERT INTO failure_searches VALUES (?, ?, ?, ?, ?)",
                (
                    search["id"],
                    search["created_at"],
                    search["request"]["policy"],
                    search["status"],
                    json.dumps(search, allow_nan=False),
                ),
            )

    def get_search(self, search_id: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM failure_searches WHERE id=?", (search_id,)
            ).fetchone()
        if row is None:
            raise KeyError(search_id)
        return json.loads(row["payload"])

    def list_searches(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, created_at, policy, status FROM failure_searches ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            ]

    def save_verification(self, record: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO verification_runs VALUES (?, ?, ?, ?, ?)",
                (
                    record["id"],
                    record["created_at"],
                    record["kind"],
                    record["request"]["case"]["title"],
                    json.dumps(record, allow_nan=False),
                ),
            )

    def get_verification(self, run_id: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM verification_runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row["payload"])

    def list_verifications(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, created_at, kind, title FROM verification_runs ORDER BY created_at DESC LIMIT 100"
                )
            ]
