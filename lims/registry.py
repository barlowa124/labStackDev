"""Minimal LIMS layer: sample registry, experiment records, plate
assignment, and an append-only hash-chained audit log.

SQLite only (stdlib). The load-bearing piece is the integrity contract:
every mutation writes an audit row whose hash covers the row content plus
the previous audit hash, so a modified history row breaks the chain.

Status machine: registered -> queued -> assigned -> processed ->
analyzed -> locked. Locked experiments reject further mutation.
"""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    meta      TEXT NOT NULL DEFAULT '{}',
    created   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'registered',
    meta          TEXT NOT NULL DEFAULT '{}',
    created       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plates (
    experiment_id TEXT NOT NULL,
    plate         TEXT NOT NULL,
    well          TEXT NOT NULL,
    sample_id     TEXT NOT NULL,
    PRIMARY KEY (experiment_id, plate, well),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id),
    FOREIGN KEY (sample_id)     REFERENCES samples(sample_id)
);
CREATE TABLE IF NOT EXISTS results (
    result_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    name          TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    meta          TEXT NOT NULL DEFAULT '{}',
    created       REAL NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '{}',
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
"""

STATUS_ORDER = ["registered", "queued", "assigned",
                "processed", "analyzed", "locked"]
_ALLOWED = {STATUS_ORDER[i]: STATUS_ORDER[i + 1]
            for i in range(len(STATUS_ORDER) - 1)}

# hash width of sha256 hexdigest and the chain's empty-history sentinel
_HASH_HEX_LEN = 64
GENESIS_HASH = "0" * _HASH_HEX_LEN


class LimsError(Exception):
    pass


class Registry:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA foreign_keys = ON")

    # ── audit ────────────────────────────────────────────────────────

    def _audit(self, entity, entity_id, action, detail=None):
        detail = json.dumps(detail or {}, sort_keys=True)
        prev = self.db.execute(
            "SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev["hash"] if prev else GENESIS_HASH
        ts = time.time()
        payload = f"{ts}|{entity}|{entity_id}|{action}|{detail}|{prev_hash}"
        h = hashlib.sha256(payload.encode()).hexdigest()
        self.db.execute(
            "INSERT INTO audit_log (ts, entity, entity_id, action,"
            " detail, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
            (ts, entity, entity_id, action, detail, prev_hash, h))
        return h

    def verify_audit_chain(self, expected_head=None, expected_rows=None) -> dict:
        """Recompute the hash chain. Tamper-evident: any edited or
        reordered row breaks linkage from that point on."""
        rows = self.db.execute(
            "SELECT * FROM audit_log ORDER BY seq").fetchall()
        prev_hash = GENESIS_HASH
        for row in rows:
            payload = (f"{row['ts']}|{row['entity']}|{row['entity_id']}|"
                       f"{row['action']}|{row['detail']}|{prev_hash}")
            h = hashlib.sha256(payload.encode()).hexdigest()
            if h != row["hash"] or row["prev_hash"] != prev_hash:
                return {"ok": False, "rows": len(rows),
                        "first_bad_seq": row["seq"]}
            prev_hash = h
        if expected_head is not None and prev_hash != expected_head:
            return {'ok': False, 'rows': len(rows), 'reason': 'head_mismatch'}
        if expected_rows is not None and len(rows) != expected_rows:
            return {'ok': False, 'rows': len(rows), 'reason': 'row_count_mismatch'}
        return {"ok": True, "rows": len(rows)}

    def audit_checkpoint(self):
        row = self.db.execute(
            'SELECT COUNT(*) AS rows, '
            '(SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1) AS head '
            'FROM audit_log').fetchone()
        return {'rows': row['rows'], 'head': row['head'] or GENESIS_HASH}

    # ── registry ─────────────────────────────────────────────────────

    @contextmanager
    def _transaction(self):
        if self.db.in_transaction:
            raise LimsError('registry mutation requires no active transaction')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def register_sample(self, sample_id, kind, meta=None):
        with self._transaction():
            self.db.execute(
                "INSERT INTO samples (sample_id, kind, meta, created)"
                " VALUES (?,?,?,?)",
                (sample_id, kind, json.dumps(meta or {}), time.time()))
            self._audit("sample", sample_id, "register", {"kind": kind})
        return sample_id

    def create_experiment(self, experiment_id, name, meta=None):
        with self._transaction():
            self.db.execute(
                "INSERT INTO experiments (experiment_id, name, meta, created)"
                " VALUES (?,?,?,?)",
                (experiment_id, name, json.dumps(meta or {}), time.time()))
            self._audit("experiment", experiment_id, "create",
                        {"name": name})
        return experiment_id

    def _status(self, experiment_id):
        r = self.db.execute(
            "SELECT status FROM experiments WHERE experiment_id=?",
            (experiment_id,)).fetchone()
        if not r:
            raise LimsError(f"unknown experiment {experiment_id}")
        return r["status"]

    def _require_unlocked(self, experiment_id):
        if self._status(experiment_id) == "locked":
            raise LimsError(f"{experiment_id} is locked, mutations refused")

    def transition(self, experiment_id, to):
        with self._transaction():
            cur = self._status(experiment_id)
            if _ALLOWED.get(cur) != to:
                raise LimsError(f"illegal transition {cur} -> {to}")
            self.db.execute(
                "UPDATE experiments SET status=? WHERE experiment_id=?",
                (to, experiment_id))
            self._audit("experiment", experiment_id, "transition",
                        {"from": cur, "to": to})
        return to

    def assign_well(self, experiment_id, plate, well, sample_id):
        with self._transaction():
            self._require_unlocked(experiment_id)
            if not self.db.execute(
                    "SELECT 1 FROM samples WHERE sample_id=?",
                    (sample_id,)).fetchone():
                raise LimsError(f"unknown sample {sample_id}")
            if self.db.execute(
                    "SELECT 1 FROM plates WHERE experiment_id=? AND plate=?"
                    " AND well=?",
                    (experiment_id, plate, well)).fetchone():
                raise LimsError(f"{plate}:{well} already occupied")
            self.db.execute(
                "INSERT INTO plates VALUES (?,?,?,?)",
                (experiment_id, plate, well, sample_id))
            self._audit("plate", f"{experiment_id}:{plate}:{well}",
                        "assign", {"sample_id": sample_id})

    def attach_result(self, experiment_id, name, content: bytes,
                      meta=None):
        """Record a result artifact by content hash. The file itself
        stays wherever it lives. The registry tracks identity."""
        with self._transaction():
            self._require_unlocked(experiment_id)
            sha = hashlib.sha256(content).hexdigest()
            cur = self.db.execute(
                "INSERT INTO results (experiment_id, name, content_sha256,"
                " meta, created) VALUES (?,?,?,?,?)",
                (experiment_id, name, sha, json.dumps(meta or {}),
                 time.time()))
            self._audit("result", f"{experiment_id}:{name}", "attach",
                        {"sha256": sha})
            return cur.lastrowid

    def plate_map(self, experiment_id, plate):
        return {r["well"]: r["sample_id"] for r in self.db.execute(
            "SELECT well, sample_id FROM plates WHERE experiment_id=?"
            " AND plate=? ORDER BY well", (experiment_id, plate))}

    def history(self, entity_id):
        return [dict(r) for r in self.db.execute(
            "SELECT ts, entity, action, detail FROM audit_log"
            " WHERE entity_id LIKE ? ORDER BY seq",
            (f"%{entity_id}%",))]
