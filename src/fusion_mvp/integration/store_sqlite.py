"""SQLite inbox / outbox / observation index for the MQTT adapter.

Not a KF state store. Survives adapter restarts for dedupe and outbox republish.
Active inbox capacity is separate from done retention / archive.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger(__name__)


class OutboxImmutableConflict(ValueError):
    """Same outbox message_id/kind already stored with a different immutable body."""


INBOX_PENDING = "pending"
INBOX_PROCESSING = "processing"
INBOX_DONE = "done"
INBOX_ERROR = "error"
INBOX_DEAD = "dead"
INBOX_CONFLICT = "conflict"
INBOX_DUPLICATE = "duplicate"

OUTBOX_PENDING = "pending"
OUTBOX_PUBLISHED = "published"

OWNER_MQTT = "mqtt"
OWNER_HTTP = "http"
OWNER_NONE = "none"

# Process-wide write ownership for HTTP/MQTT shared fence (same OS process).
# Depth counter (not threading.local): TestClient/ASGI may run the handler on
# another worker thread while the MQTT adapter is still inside post().
_OWNER_REGISTRY: dict[str, str] = {}
_OWNER_REGISTRY_LOCK = threading.Lock()
_MQTT_WRITE_DEPTH = 0
_MQTT_WRITE_LOCK = threading.Lock()


def registry_set_owner(session_id: str, owner: str) -> None:
    with _OWNER_REGISTRY_LOCK:
        if owner in (OWNER_NONE, "", None):
            _OWNER_REGISTRY.pop(session_id, None)
        else:
            _OWNER_REGISTRY[session_id] = str(owner)


def registry_get_owner(session_id: str) -> str:
    with _OWNER_REGISTRY_LOCK:
        return _OWNER_REGISTRY.get(session_id, OWNER_NONE)


def mqtt_adapter_write_begin() -> None:
    global _MQTT_WRITE_DEPTH
    with _MQTT_WRITE_LOCK:
        _MQTT_WRITE_DEPTH += 1


def mqtt_adapter_write_end() -> None:
    global _MQTT_WRITE_DEPTH
    with _MQTT_WRITE_LOCK:
        _MQTT_WRITE_DEPTH = max(0, _MQTT_WRITE_DEPTH - 1)


def is_mqtt_adapter_write() -> bool:
    with _MQTT_WRITE_LOCK:
        return _MQTT_WRITE_DEPTH > 0


class IntegrationStore:
    def __init__(
        self,
        path: str | Path,
        *,
        max_inbox: int = 50_000,
        done_retain: int = 100_000,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_inbox = int(max_inbox)
        self.done_retain = int(done_retain)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        self._hydrate_owner_registry()

    def _hydrate_owner_registry(self) -> None:
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT session_id, write_owner FROM session_meta"
                ).fetchall()
            except sqlite3.Error:
                return
            for row in rows:
                owner = str(row["write_owner"] or OWNER_NONE)
                if owner not in (OWNER_NONE, ""):
                    registry_set_owner(str(row["session_id"]), owner)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS inbox (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    batch_id TEXT,
                    content_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    work_item_json TEXT,
                    error TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_inbox_session_status
                    ON inbox(session_id, status, created_at);
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    topic_suffix TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retain INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(message_id, kind)
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status, id);
                CREATE TABLE IF NOT EXISTS observations (
                    session_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    obs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, observation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id);
                CREATE TABLE IF NOT EXISTS session_meta (
                    session_id TEXT PRIMARY KEY,
                    write_owner TEXT NOT NULL DEFAULT 'none',
                    expected_epoch TEXT,
                    paused INTEGER NOT NULL DEFAULT 0,
                    pause_reason TEXT,
                    handover_pending INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inbox_archive (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    archived_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._migrate_columns()
            self._migrate_observations_pk()

    def _migrate_columns(self) -> None:
        cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(inbox)").fetchall()
        }
        if "attempt_count" not in cols:
            self._conn.execute(
                "ALTER TABLE inbox ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        if "next_attempt_at" not in cols:
            self._conn.execute("ALTER TABLE inbox ADD COLUMN next_attempt_at TEXT")
        out_cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(outbox)").fetchall()
        }
        if "retain" not in out_cols:
            self._conn.execute(
                "ALTER TABLE outbox ADD COLUMN retain INTEGER NOT NULL DEFAULT 0"
            )
        meta_cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(session_meta)").fetchall()
        }
        if "fusion_profile" not in meta_cols:
            self._conn.execute("ALTER TABLE session_meta ADD COLUMN fusion_profile TEXT")
        if "lifecycle" not in meta_cols:
            self._conn.execute(
                "ALTER TABLE session_meta ADD COLUMN lifecycle TEXT NOT NULL DEFAULT 'active'"
            )
        if "last_processing_time" not in meta_cols:
            self._conn.execute("ALTER TABLE session_meta ADD COLUMN last_processing_time TEXT")
        if "write_generation" not in meta_cols:
            self._conn.execute("ALTER TABLE session_meta ADD COLUMN write_generation INTEGER")

    def _migrate_observations_pk(self) -> None:
        """Rebuild observations if legacy global observation_id PRIMARY KEY remains."""
        info = self._conn.execute("PRAGMA table_info(observations)").fetchall()
        pk_cols = [r["name"] for r in info if int(r["pk"]) > 0]
        if pk_cols == ["session_id", "observation_id"]:
            return
        if not info:
            return
        # Legacy or unexpected shape → rebuild with composite key.
        self._conn.execute("ALTER TABLE observations RENAME TO observations_legacy")
        self._conn.execute(
            """
            CREATE TABLE observations (
                session_id TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                obs_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, observation_id)
            )
            """
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO observations(session_id, observation_id, message_id, obs_json, created_at)
            SELECT session_id, observation_id, message_id, obs_json, created_at FROM observations_legacy
            """
        )
        self._conn.execute("DROP TABLE observations_legacy")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id)"
        )

    def inbox_count(self) -> int:
        """Total inbox rows (including done). Prefer active_inbox_count for capacity."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM inbox").fetchone()
            return int(row["c"])

    def active_inbox_count(self) -> int:
        """Pending / processing / retryable rows that consume the live queue budget."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM inbox
                WHERE status IN (?, ?)
                """,
                (INBOX_PENDING, INBOX_PROCESSING),
            ).fetchone()
            return int(row["c"])

    def try_insert_inbox(
        self,
        *,
        message_id: str,
        session_id: str,
        batch_id: str,
        content_hash: str,
        raw: dict[str, Any],
        now_iso: str,
    ) -> str:
        """Return status: pending | duplicate | conflict | capacity."""
        with self._lock:
            existing = self._conn.execute(
                "SELECT content_hash, status FROM inbox WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if existing is None:
                archived = self._conn.execute(
                    "SELECT content_hash FROM inbox_archive WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                if archived is not None:
                    if archived["content_hash"] == content_hash:
                        return INBOX_DUPLICATE
                    return INBOX_CONFLICT
            if existing is not None:
                if existing["content_hash"] == content_hash:
                    return INBOX_DUPLICATE
                return INBOX_CONFLICT
            if self.active_inbox_count() >= self.max_inbox:
                return "capacity"
            self._conn.execute(
                """
                INSERT INTO inbox(
                    message_id, session_id, batch_id, content_hash, raw_json,
                    status, work_item_json, error, attempt_count, next_attempt_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    batch_id,
                    content_hash,
                    json.dumps(raw, ensure_ascii=False),
                    INBOX_PENDING,
                    now_iso,
                    now_iso,
                ),
            )
            return INBOX_PENDING

    def insert_input_transaction(
        self,
        *,
        message_id: str,
        session_id: str,
        batch_id: str,
        content_hash: str,
        raw: dict[str, Any],
        observations: list[dict[str, Any]],
        stored_ack: dict[str, Any],
        now_iso: str,
    ) -> str:
        """Atomically: inbox + observation index + stored-ack outbox. Returns insert status."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                status = self._try_insert_inbox_unlocked(
                    message_id=message_id,
                    session_id=session_id,
                    batch_id=batch_id,
                    content_hash=content_hash,
                    raw=raw,
                    now_iso=now_iso,
                )
                if status != INBOX_PENDING:
                    self._conn.execute("COMMIT")
                    return status
                self._index_observations_unlocked(
                    session_id=session_id,
                    message_id=message_id,
                    observations=observations,
                    now_iso=now_iso,
                )
                self._enqueue_outbox_unlocked(
                    message_id=f"{message_id}-stored",
                    kind="ack",
                    topic_suffix="ack",
                    payload=stored_ack,
                    now_iso=now_iso,
                    retain=False,
                )
                self._conn.execute("COMMIT")
                return INBOX_PENDING
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _try_insert_inbox_unlocked(
        self,
        *,
        message_id: str,
        session_id: str,
        batch_id: str,
        content_hash: str,
        raw: dict[str, Any],
        now_iso: str,
    ) -> str:
        existing = self._conn.execute(
            "SELECT content_hash, status FROM inbox WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if existing is None:
            archived = self._conn.execute(
                "SELECT content_hash FROM inbox_archive WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if archived is not None:
                if archived["content_hash"] == content_hash:
                    return INBOX_DUPLICATE
                return INBOX_CONFLICT
        if existing is not None:
            if existing["content_hash"] == content_hash:
                return INBOX_DUPLICATE
            return INBOX_CONFLICT
        active = self._conn.execute(
            "SELECT COUNT(*) AS c FROM inbox WHERE status IN (?, ?)",
            (INBOX_PENDING, INBOX_PROCESSING),
        ).fetchone()
        if int(active["c"]) >= self.max_inbox:
            return "capacity"
        self._conn.execute(
            """
            INSERT INTO inbox(
                message_id, session_id, batch_id, content_hash, raw_json,
                status, work_item_json, error, attempt_count, next_attempt_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, ?, ?)
            """,
            (
                message_id,
                session_id,
                batch_id,
                content_hash,
                json.dumps(raw, ensure_ascii=False),
                INBOX_PENDING,
                now_iso,
                now_iso,
            ),
        )
        return INBOX_PENDING

    def claim_next_for_session(self, session_id: str, now_iso: str) -> Optional[dict[str, Any]]:
        """Claim session head only. Never overtake a blocked head waiting on backoff."""
        return self.claim_next_for_session_excluding(session_id, None, now_iso)

    def claim_next_for_session_excluding(
        self, session_id: str, exclude_message_id: Optional[str], now_iso: str
    ) -> Optional[dict[str, Any]]:
        """Claim earliest unfinished row, optionally skipping one message (e.g. run.end drain)."""
        with self._lock:
            meta = self._conn.execute(
                "SELECT paused FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            paused = meta is not None and int(meta["paused"]) == 1
            if exclude_message_id:
                head = self._conn.execute(
                    """
                    SELECT * FROM inbox
                    WHERE session_id = ? AND status IN (?, ?) AND message_id != ?
                    ORDER BY created_at ASC, message_id ASC
                    LIMIT 1
                    """,
                    (session_id, INBOX_PENDING, INBOX_PROCESSING, exclude_message_id),
                ).fetchone()
            else:
                # Earliest unfinished row is the head (ignore next_attempt_at for ordering).
                head = self._conn.execute(
                    """
                    SELECT * FROM inbox
                    WHERE session_id = ? AND status IN (?, ?)
                    ORDER BY created_at ASC, message_id ASC
                    LIMIT 1
                    """,
                    (session_id, INBOX_PENDING, INBOX_PROCESSING),
                ).fetchone()
            if head is None:
                return None
            is_control = False
            wj = head["work_item_json"] or ""
            if '"kind":"control"' in wj or '"kind": "control"' in wj:
                is_control = True
            if paused and not is_control:
                return None
            nxt = head["next_attempt_at"]
            if nxt is not None and str(nxt) > str(now_iso):
                # Head blocked on backoff — do not claim later messages.
                return None
            row = head
            if row["status"] == INBOX_PENDING:
                self._conn.execute(
                    "UPDATE inbox SET status = ?, updated_at = ? WHERE message_id = ?",
                    (INBOX_PROCESSING, now_iso, row["message_id"]),
                )
            return dict(row)

    def list_active_sessions(self) -> list[str]:
        """Sessions needing lifecycle ticks: active meta and/or unfinished inbox."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT session_id FROM session_meta
                WHERE COALESCE(lifecycle, 'active') = 'active'
                  AND COALESCE(paused, 0) = 0
                UNION
                SELECT DISTINCT session_id FROM inbox
                WHERE status IN (?, ?)
                ORDER BY 1
                """,
                (INBOX_PENDING, INBOX_PROCESSING),
            ).fetchall()
            return [r["session_id"] for r in rows]

    def get_inbox(self, message_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM inbox WHERE message_id = ?", (message_id,)
            ).fetchone()
            return dict(row) if row else None

    def set_work_item(self, message_id: str, work_item: dict[str, Any], now_iso: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE inbox SET work_item_json = ?, updated_at = ? WHERE message_id = ?",
                (json.dumps(work_item, ensure_ascii=False), now_iso, message_id),
            )

    def mark_inbox_done(self, message_id: str, now_iso: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE inbox SET status = ?, updated_at = ?, next_attempt_at = NULL WHERE message_id = ?",
                (INBOX_DONE, now_iso, message_id),
            )
            self._maybe_archive_done_unlocked(now_iso)

    def mark_inbox_error(
        self,
        message_id: str,
        error: str,
        now_iso: str,
        *,
        retryable: bool,
        next_attempt_at: Optional[str] = None,
        increment_attempt: bool = False,
    ) -> int:
        with self._lock:
            attempt = 0
            if increment_attempt:
                row = self._conn.execute(
                    "SELECT attempt_count FROM inbox WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                attempt = int(row["attempt_count"] if row else 0) + 1
            # Retryable failures return to pending so the serial worker can reclaim
            # after next_attempt_at; non-retryable stay terminal error.
            status = INBOX_PENDING if retryable else INBOX_ERROR
            if increment_attempt:
                self._conn.execute(
                    """
                    UPDATE inbox SET status = ?, error = ?, updated_at = ?,
                           attempt_count = ?, next_attempt_at = ?
                    WHERE message_id = ?
                    """,
                    (status, error, now_iso, attempt, next_attempt_at, message_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE inbox SET status = ?, error = ?, updated_at = ?,
                           next_attempt_at = ?
                    WHERE message_id = ?
                    """,
                    (status, error, now_iso, next_attempt_at, message_id),
                )
                row = self._conn.execute(
                    "SELECT attempt_count FROM inbox WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                attempt = int(row["attempt_count"] if row else 0)
            return attempt

    def mark_inbox_dead(self, message_id: str, error: str, now_iso: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE inbox SET status = ?, error = ?, updated_at = ?, next_attempt_at = NULL
                WHERE message_id = ?
                """,
                (INBOX_DEAD, error, now_iso, message_id),
            )

    def complete_success_transaction(
        self,
        *,
        message_id: str,
        result_payload: dict[str, Any],
        ack_payload: dict[str, Any],
        now_iso: str,
        expected_epoch: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Atomically: result+ack outbox + inbox done (+ optional epoch remember)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                try:
                    self._enqueue_outbox_unlocked(
                        message_id=message_id,
                        kind="result",
                        topic_suffix="result",
                        payload=result_payload,
                        now_iso=now_iso,
                        retain=False,
                    )
                except OutboxImmutableConflict as exc:
                    # Keep original immutable body; conflict is logged/raised at enqueue —
                    # still complete ack+inbox so the worker does not drop other work.
                    LOG.error("result outbox immutable conflict (retained original): %s", exc)
                self._enqueue_outbox_unlocked(
                    message_id=f"{message_id}-ack",
                    kind="ack",
                    topic_suffix="ack",
                    payload=ack_payload,
                    now_iso=now_iso,
                    retain=False,
                )
                self._conn.execute(
                    "UPDATE inbox SET status = ?, updated_at = ?, next_attempt_at = NULL WHERE message_id = ?",
                    (INBOX_DONE, now_iso, message_id),
                )
                if session_id is not None and expected_epoch is not None:
                    self._upsert_session_meta_unlocked(
                        session_id=session_id,
                        expected_epoch=expected_epoch,
                        now_iso=now_iso,
                    )
                self._maybe_archive_done_unlocked(now_iso)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _maybe_archive_done_unlocked(self, now_iso: str) -> None:
        """Keep active queue lean: archive excess done rows while retaining hash for dedup."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM inbox WHERE status = ?",
            (INBOX_DONE,),
        ).fetchone()
        done_n = int(row["c"])
        if done_n <= self.done_retain:
            return
        excess = done_n - self.done_retain
        old = self._conn.execute(
            """
            SELECT message_id, session_id, content_hash, status FROM inbox
            WHERE status = ?
            ORDER BY updated_at ASC, message_id ASC
            LIMIT ?
            """,
            (INBOX_DONE, excess),
        ).fetchall()
        for r in old:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO inbox_archive(message_id, session_id, content_hash, status, archived_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (r["message_id"], r["session_id"], r["content_hash"], r["status"], now_iso),
            )
            self._conn.execute("DELETE FROM inbox WHERE message_id = ?", (r["message_id"],))

    def index_observations(
        self,
        *,
        session_id: str,
        message_id: str,
        observations: list[dict[str, Any]],
        now_iso: str,
    ) -> None:
        with self._lock:
            self._index_observations_unlocked(
                session_id=session_id,
                message_id=message_id,
                observations=observations,
                now_iso=now_iso,
            )

    def _index_observations_unlocked(
        self,
        *,
        session_id: str,
        message_id: str,
        observations: list[dict[str, Any]],
        now_iso: str,
    ) -> None:
        """Index observations immutably within a session.

        Same id + same content → idempotent keep. Same id + different content →
        keep the first accepted body (do not overwrite evidence).
        """
        for obs in observations:
            oid = obs.get("observationId")
            if not oid:
                continue
            blob = json.dumps(obs, ensure_ascii=False, sort_keys=True)
            existing = self._conn.execute(
                """
                SELECT obs_json FROM observations
                WHERE session_id = ? AND observation_id = ?
                """,
                (session_id, str(oid)),
            ).fetchone()
            if existing is not None:
                try:
                    old = json.loads(existing["obs_json"])
                    old_blob = json.dumps(old, ensure_ascii=False, sort_keys=True)
                except (TypeError, json.JSONDecodeError):
                    old_blob = existing["obs_json"]
                if old_blob == blob:
                    continue  # identical redelivery
                # Conflict: preserve original evidence; audit row optional later.
                continue
            self._conn.execute(
                """
                INSERT INTO observations(session_id, observation_id, message_id, obs_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, str(oid), message_id, json.dumps(obs, ensure_ascii=False), now_iso),
            )

    def lookup_observations(
        self,
        observation_ids: list[str],
        *,
        session_id: Optional[str] = None,
    ) -> dict[str, dict[str, Any]]:
        """Lookup by (session_id, observation_id). session_id is required for correct isolation."""
        if not observation_ids:
            return {}
        with self._lock:
            out: dict[str, dict[str, Any]] = {}
            for oid in observation_ids:
                if session_id is not None:
                    row = self._conn.execute(
                        """
                        SELECT obs_json FROM observations
                        WHERE session_id = ? AND observation_id = ?
                        """,
                        (session_id, oid),
                    ).fetchone()
                else:
                    # Without session_id: single hit is unambiguous; multiple hits
                    # return the earliest indexed row (never silently prefer a later
                    # session overwrite — composite PK keeps both).
                    rows = self._conn.execute(
                        """
                        SELECT obs_json FROM observations
                        WHERE observation_id = ?
                        ORDER BY created_at ASC, session_id ASC
                        """,
                        (oid,),
                    ).fetchall()
                    row = rows[0] if rows else None
                if row:
                    out[oid] = json.loads(row["obs_json"])
            return out

    def enqueue_outbox(
        self,
        *,
        message_id: str,
        kind: str,
        topic_suffix: str,
        payload: dict[str, Any],
        now_iso: str,
        retain: bool = False,
    ) -> None:
        with self._lock:
            self._enqueue_outbox_unlocked(
                message_id=message_id,
                kind=kind,
                topic_suffix=topic_suffix,
                payload=payload,
                now_iso=now_iso,
                retain=retain,
            )

    def get_outbox_by_message_kind(self, message_id: str, kind: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM outbox WHERE message_id = ? AND kind = ?",
                (message_id, kind),
            ).fetchone()
            return dict(row) if row else None

    def _enqueue_outbox_unlocked(
        self,
        *,
        message_id: str,
        kind: str,
        topic_suffix: str,
        payload: dict[str, Any],
        now_iso: str,
        retain: bool = False,
    ) -> None:
        existing = self._conn.execute(
            "SELECT id, status, payload_json FROM outbox WHERE message_id = ? AND kind = ?",
            (message_id, kind),
        ).fetchone()
        new_payload = json.dumps(payload, ensure_ascii=False)
        if existing is not None:
            old_payload = existing["payload_json"]
            if old_payload == new_payload:
                # Same id + same body: idempotent no-op.
                return
            # Published (or any durable) result body is immutable: different body must
            # be observable — never silently ignore or overwrite.
            if str(existing["status"]) == OUTBOX_PUBLISHED or kind == "result":
                msg = (
                    f"outbox_conflict message_id={message_id} kind={kind} "
                    f"status={existing['status']} immutable body mismatch"
                )
                LOG.error(msg)
                raise OutboxImmutableConflict(msg)
            self._conn.execute(
                """
                UPDATE outbox SET payload_json=?, topic_suffix=?, retain=?, updated_at=?
                WHERE id=?
                """,
                (new_payload, topic_suffix, 1 if retain else 0, now_iso, int(existing["id"])),
            )
            return
        self._conn.execute(
            """
            INSERT INTO outbox(
                message_id, kind, topic_suffix, payload_json, status, retain, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                kind,
                topic_suffix,
                new_payload,
                OUTBOX_PENDING,
                1 if retain else 0,
                now_iso,
                now_iso,
            ),
        )

    def claim_pending_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM outbox WHERE status = ? ORDER BY id ASC LIMIT ?
                """,
                (OUTBOX_PENDING, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_outbox_published(self, outbox_id: int, now_iso: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET status = ?, updated_at = ? WHERE id = ?",
                (OUTBOX_PUBLISHED, now_iso, outbox_id),
            )

    def session_pending_outbox_count(self, session_id: str, *, kinds: Optional[set[str]] = None) -> int:
        """Count pending outbox rows for a session. Default: all kinds."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT kind, payload_json FROM outbox WHERE status = ?
                """,
                (OUTBOX_PENDING,),
            ).fetchall()
            n = 0
            for r in rows:
                if kinds is not None and r["kind"] not in kinds:
                    continue
                try:
                    payload = json.loads(r["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if str(payload.get("sessionId") or "") == session_id:
                    n += 1
            return n

    def session_stats(self, session_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS c FROM inbox WHERE session_id = ? GROUP BY status",
                (session_id,),
            ).fetchall()
            return {r["status"]: int(r["c"]) for r in rows}

    def session_active_count(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM inbox
                WHERE session_id = ? AND status IN (?, ?)
                """,
                (session_id, INBOX_PENDING, INBOX_PROCESSING),
            ).fetchone()
            return int(row["c"])

    def session_active_count_excluding(self, session_id: str, exclude_message_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM inbox
                WHERE session_id = ? AND status IN (?, ?) AND message_id != ?
                """,
                (session_id, INBOX_PENDING, INBOX_PROCESSING, exclude_message_id),
            ).fetchone()
            return int(row["c"])

    # --- session ownership / epoch ---
    def get_session_meta(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return {
                    "session_id": session_id,
                    "write_owner": OWNER_NONE,
                    "expected_epoch": None,
                    "paused": 0,
                    "pause_reason": None,
                    "handover_pending": 0,
                }
            return dict(row)

    def set_write_owner(
        self,
        session_id: str,
        owner: str,
        now_iso: str,
        *,
        handover_pending: bool = False,
    ) -> None:
        with self._lock:
            self._upsert_session_meta_unlocked(
                session_id=session_id,
                write_owner=owner,
                handover_pending=1 if handover_pending else 0,
                now_iso=now_iso,
            )
        registry_set_owner(session_id, owner)

    def set_session_paused(
        self,
        session_id: str,
        paused: bool,
        now_iso: str,
        *,
        reason: Optional[str] = None,
        expected_epoch: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._upsert_session_meta_unlocked(
                session_id=session_id,
                paused=1 if paused else 0,
                pause_reason=reason,
                expected_epoch=expected_epoch,
                now_iso=now_iso,
            )

    def set_session_runtime(
        self,
        session_id: str,
        now_iso: str,
        *,
        fusion_profile: Optional[str] = None,
        lifecycle: Optional[str] = None,
        last_processing_time: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._upsert_session_meta_unlocked(
                session_id=session_id,
                now_iso=now_iso,
                fusion_profile=fusion_profile,
                lifecycle=lifecycle,
                last_processing_time=last_processing_time,
            )

    def set_session_write_generation(self, session_id: str, generation: int, now_iso: str) -> None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT session_id FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if cur is None:
                self._upsert_session_meta_unlocked(session_id=session_id, now_iso=now_iso)
            self._conn.execute(
                "UPDATE session_meta SET write_generation = ?, updated_at = ? WHERE session_id = ?",
                (int(generation), now_iso, session_id),
            )

    def _upsert_session_meta_unlocked(
        self,
        *,
        session_id: str,
        now_iso: str,
        write_owner: Optional[str] = None,
        expected_epoch: Optional[str] = None,
        paused: Optional[int] = None,
        pause_reason: Optional[str] = None,
        handover_pending: Optional[int] = None,
        fusion_profile: Optional[str] = None,
        lifecycle: Optional[str] = None,
        last_processing_time: Optional[str] = None,
    ) -> None:
        cur = self._conn.execute(
            "SELECT * FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if cur is None:
            self._conn.execute(
                """
                INSERT INTO session_meta(
                    session_id, write_owner, expected_epoch, paused, pause_reason,
                    handover_pending, updated_at, fusion_profile, lifecycle, last_processing_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    write_owner or OWNER_NONE,
                    expected_epoch,
                    0 if paused is None else int(paused),
                    pause_reason,
                    0 if handover_pending is None else int(handover_pending),
                    now_iso,
                    fusion_profile,
                    lifecycle or "active",
                    last_processing_time,
                ),
            )
            return
        self._conn.execute(
            """
            UPDATE session_meta SET
                write_owner = COALESCE(?, write_owner),
                expected_epoch = COALESCE(?, expected_epoch),
                paused = COALESCE(?, paused),
                pause_reason = COALESCE(?, pause_reason),
                handover_pending = COALESCE(?, handover_pending),
                fusion_profile = COALESCE(?, fusion_profile),
                lifecycle = COALESCE(?, lifecycle),
                last_processing_time = COALESCE(?, last_processing_time),
                updated_at = ?
            WHERE session_id = ?
            """,
            (
                write_owner,
                expected_epoch,
                paused,
                pause_reason,
                handover_pending,
                fusion_profile,
                lifecycle,
                last_processing_time,
                now_iso,
                session_id,
            ),
        )
