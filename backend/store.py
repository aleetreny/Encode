"""SQLite journal: atomic enqueue, idempotency, state transitions and decisions."""

import json
import sqlite3
from contextlib import contextmanager
from uuid import uuid4

from backend.models import RunDocument, utc_now


class Conflict(Exception):
    pass


class QueueFull(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, idem TEXT UNIQUE, fingerprint TEXT NOT NULL,
                    request TEXT NOT NULL, state TEXT NOT NULL, document TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    run_id TEXT PRIMARY KEY, document TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, request, fingerprint, key, limit):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if key:
                old = db.execute(
                    "SELECT fingerprint, document FROM runs WHERE idem=?", (key,)
                ).fetchone()
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise Conflict("Idempotency-Key was already used with different input")
                    return json.loads(old["document"]), False
            count = db.execute(
                "SELECT count(*) FROM runs WHERE state IN ('queued','running')"
            ).fetchone()[0]
            if count >= limit:
                raise QueueFull()
            run_id = str(uuid4())
            now = utc_now()
            document = dict(
                schema_version="1.0.0",
                run_id=run_id,
                scenario_id=request["scenario_id"],
                execution_mode=request["execution_mode"],
                status="queued",
                created_at=now,
                updated_at=now,
                revision=0,
                approval_status="unavailable",
                tool_trace=[],
                baseline=None,
                candidate=None,
                comparison=None,
                validation={
                    "passed": False,
                    "violations": ["not yet validated"],
                    "max_residual_mw": 0,
                },
                operator_report=None,
                error=None,
            )
            if request.get("_protocol") == "2.0.0":
                document.update(
                    schema_version="2.0.0",
                    crisis_analysis=None,
                    governance_mode=request["governance_mode"],
                )
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    key,
                    fingerprint,
                    json.dumps(request),
                    "queued",
                    json.dumps(document),
                    now,
                ),
            )
            return document, True

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM runs WHERE state='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            document = json.loads(row["document"])
            document.update(
                status="running", updated_at=utc_now(), revision=document["revision"] + 1
            )
            db.execute(
                "UPDATE runs SET state='running',document=? WHERE id=?",
                (json.dumps(document), row["id"]),
            )
            return row["id"], json.loads(row["request"])

    def finish(self, run_id, result):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document,state FROM runs WHERE id=?", (run_id,)).fetchone()
            if row["state"] != "running":
                raise Conflict("run is no longer running")
            document = json.loads(row["document"])
            document.update(result, updated_at=utc_now(), revision=document["revision"] + 1)
            if document["schema_version"] == "2.0.0":
                from backend.native_models import NativeRunDocument

                NativeRunDocument.model_validate(document)
            else:
                RunDocument.model_validate(document)
            db.execute(
                "UPDATE runs SET state=?,document=? WHERE id=?",
                (document["status"], json.dumps(document, allow_nan=False), run_id),
            )

    def recover(self):
        # One API process per database. Queued work survives restart; running work fails explicitly.
        with self.connect() as db:
            for row in db.execute("SELECT id,document FROM runs WHERE state='running'").fetchall():
                doc = json.loads(row["document"])
                doc.update(
                    status="failed",
                    error={
                        "code": "worker_interrupted",
                        "message": "Service restarted during investigation; submit a new run.",
                    },
                    updated_at=utc_now(),
                    revision=doc["revision"] + 1,
                )
                db.execute(
                    "UPDATE runs SET state='failed',document=? WHERE id=?",
                    (json.dumps(doc), row["id"]),
                )

    def decide(self, run_id, decision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            doc = json.loads(row[0])
            if doc["revision"] != decision.expected_revision:
                raise Conflict("stale revision; reload the run")
            if (
                doc["status"] != "completed"
                or not doc["validation"]["passed"]
                or doc["approval_status"] != "pending"
            ):
                raise Conflict(
                    "only a completed, verified, undecided simulation can receive a decision"
                )
            record = decision.model_dump()
            record.update(decided_at=utc_now(), scope="simulation_only")
            if doc["schema_version"] == "2.0.0":
                record["applies_to"] = (
                    ["crisis_recovery"]
                    if doc["governance_mode"] == "autonomous_sced_with_audit_gate"
                    else ["normal_dispatch", "crisis_recovery"]
                )
                action = "approved_in_simulation" if decision.decision == "approved" else "rejected"
                for target in record["applies_to"]:
                    doc["governance"][target] = action
            db.execute("INSERT INTO decisions VALUES (?,?)", (run_id, json.dumps(record)))
            doc.update(
                approval_status=decision.decision,
                decision=record,
                revision=doc["revision"] + 1,
                updated_at=utc_now(),
            )
            db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(doc), run_id))
            return doc
