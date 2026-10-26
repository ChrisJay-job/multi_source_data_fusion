"""MQTT → validate → SQLite inbox → per-session serial queue → HTTP /v1/fusion/process → outbox → publish.
Fusion computation never runs inside MQTT network callbacks.
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urljoin
import httpx
import paho.mqtt.client as mqtt
from pydantic import ValidationError

from fusion_mvp.models import ProcessResponse

from .schemas import (
    SCHEMA_VERSION,
    build_ack,
    build_result,
    build_status,
    content_fingerprint,
    evidence_from_observation,
    map_http_error_to_ack_status,
    utc_now_iso,
    validate_control_payload,
    validate_envelope,
    validate_observations_payload,
    MESSAGE_TYPES_CONTROL,
    MESSAGE_TYPES_INPUT,
)
from .store_sqlite import (
    INBOX_CONFLICT,
    INBOX_DUPLICATE,
    INBOX_PENDING,
    OWNER_HTTP,
    OWNER_MQTT,
    OWNER_NONE,
    IntegrationStore,
    OutboxImmutableConflict,
)
from . import write_fence as _wf
import sqlite3
LOG = logging.getLogger("fusion_mvp.integration.mqtt_bridge")
DEFAULT_QOS = 1
@dataclass
class BridgeConfig:
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    username: str = "fusion_local"
    password: str = "fusion_local_dev_only"
    client_id: str = "fusion-mqtt-adapter-001"
    tenant_id: str = "tenant-demo"
    site_id: str = "site-demo"
    topic_prefix: str = "fusion/v1"
    http_base_url: str = "http://127.0.0.1:18099"
    sqlite_path: str = "data/task008/mqtt_adapter.sqlite3"
    max_inbox: int = 50_000
    http_timeout_s: float = 30.0
    http_retries: int = 3
    max_session_workers: int = 4
    reconnect_min_s: float = 1.0
    reconnect_max_s: float = 30.0
    keepalive_s: int = 30
    idle_tick_s: float = 2.0
    reorder_window_s: float = 2.0
    publish_timeout_s: float = 10.0
    done_retain: int = 100_000
    @classmethod
    def from_env(cls) -> "BridgeConfig":
        return cls(
            broker_host=os.getenv("TASK008_MQTT_HOST", "127.0.0.1"),
            broker_port=int(os.getenv("TASK008_MQTT_PORT", "1883")),
            username=os.getenv("TASK008_MQTT_USER", "fusion_local"),
            password=os.getenv("TASK008_MQTT_PASSWORD", "fusion_local_dev_only"),
            client_id=os.getenv("TASK008_MQTT_CLIENT_ID", "fusion-mqtt-adapter-001"),
            tenant_id=os.getenv("TASK008_TENANT_ID", "tenant-demo"),
            site_id=os.getenv("TASK008_SITE_ID", "site-demo"),
            topic_prefix=os.getenv("TASK008_TOPIC_PREFIX", "fusion/v1").rstrip("/"),
            http_base_url=os.getenv("TASK008_HTTP_BASE", "http://127.0.0.1:18099").rstrip("/"),
            sqlite_path=os.getenv("TASK008_SQLITE_PATH", "data/task008/mqtt_adapter.sqlite3"),
            max_inbox=int(os.getenv("TASK008_MAX_INBOX", "50000")),
            http_timeout_s=float(os.getenv("TASK008_HTTP_TIMEOUT_S", "30")),
            http_retries=int(os.getenv("TASK008_HTTP_RETRIES", "3")),
            max_session_workers=int(os.getenv("TASK008_MAX_SESSION_WORKERS", "4")),
            idle_tick_s=float(os.getenv("TASK008_IDLE_TICK_S", "2")),
            reorder_window_s=float(os.getenv("TASK008_REORDER_WINDOW_S", "2")),
            publish_timeout_s=float(os.getenv("TASK008_PUBLISH_TIMEOUT_S", "10")),
            done_retain=int(os.getenv("TASK008_DONE_RETAIN", "100000")),
        )
    def topic(self, kind: str) -> str:
        return f"{self.topic_prefix}/{self.tenant_id}/{self.site_id}/{kind}"
class PublishNotAcked(RuntimeError):
    """Broker did not confirm PUBACK within timeout (is_published still false)."""
class MqttBridge:
    def __init__(self, cfg: Optional[BridgeConfig] = None):
        self.cfg = cfg or BridgeConfig.from_env()
        self.store = IntegrationStore(
            self.cfg.sqlite_path,
            max_inbox=self.cfg.max_inbox,
            done_retain=self.cfg.done_retain,
        )
        self._stop = threading.Event()
        self._session_events: dict[str, threading.Event] = {}
        self._session_threads: dict[str, threading.Thread] = {}
        self._waiting_sessions: list[str] = []
        self._session_lock = threading.Lock()
        self._outbox_thread: Optional[threading.Thread] = None
        self._idle_tick_thread: Optional[threading.Thread] = None
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._http = httpx.Client(timeout=self.cfg.http_timeout_s)
        self._outbox_event = threading.Event()
        self._session_profiles: dict[str, Optional[str]] = {}
        # Per-session write generation (never a single process-global value).
        self._write_generations: dict[str, int] = {}

    def _session_generation(self, session_id: str) -> Optional[int]:
        if not session_id:
            return None
        if session_id in self._write_generations:
            return int(self._write_generations[session_id])
        meta = self.store.get_session_meta(session_id) or {}
        g = meta.get("write_generation")
        if g is not None and str(g).strip() != "":
            try:
                return int(g)
            except (TypeError, ValueError):
                return None
        return None

    def _remember_generation(self, session_id: str, generation: int) -> None:
        if not session_id:
            return
        g = int(generation)
        self._write_generations[session_id] = g
        try:
            self.store.set_session_write_generation(session_id, g, utc_now_iso())
        except Exception:  # noqa: BLE001
            pass

    def _core_headers(self, session_id: str = "") -> dict[str, str]:
        headers = {_wf.CHANNEL_HEADER: _wf.OWNER_MQTT}
        gen = self._session_generation(session_id) if session_id else None
        if gen is not None:
            headers[_wf.GENERATION_HEADER] = str(gen)
        return headers

    def _core_post(self, url: str, body: dict[str, Any], *, session_id: str = "") -> Any:
        """POST to HTTP core with MQTT channel identity (real protocol header)."""
        headers = self._core_headers(session_id)
        try:
            resp = self._http.post(url, json=body, headers=headers)
        except TypeError:
            resp = self._http.post(url, json=body)
        # First successful MQTT claim: core assigns gen=1; remember per session.
        if (
            session_id
            and self._session_generation(session_id) is None
            and int(getattr(resp, "status_code", 500)) < 400
        ):
            self._remember_generation(session_id, 1)
        return resp

    def _core_transfer_owner(
        self,
        session_id: str,
        *,
        new_owner: str,
        from_owner: Optional[str] = None,
        reason: str = "control_handover",
    ) -> dict[str, Any]:
        url = urljoin(self.cfg.http_base_url + "/", f"v1/fusion/session/{session_id}/write-owner")
        payload = {"owner": new_owner, "reason": reason}
        if from_owner:
            payload["fromOwner"] = from_owner
        gen = self._session_generation(session_id)
        if gen is not None:
            payload["expectedGeneration"] = int(gen)
        resp = self._http.post(url, json=payload, headers=self._core_headers(session_id))
        if int(getattr(resp, "status_code", 500)) >= 400:
            try:
                detail = resp.json()
            except Exception:  # noqa: BLE001
                detail = getattr(resp, "text", "")
            raise RuntimeError(f"core_transfer_http_{getattr(resp, 'status_code', '?')}:{detail}")
        body = resp.json() if hasattr(resp, "json") else {}
        if isinstance(body, dict) and body.get("generation") is not None:
            self._remember_generation(session_id, int(body["generation"]))
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _valid_process_response(body: Any, request_body: Optional[dict[str, Any]] = None) -> bool:
        if not isinstance(body, dict):
            return False
        if body.get("error"):
            return False
        if "raw" in body and "epoch" not in body:
            return False
        if body.get("epoch") is None or body.get("batchId") is None:
            return False
        if "tracks" not in body and "trajectoryUpdates" not in body:
            return False
        req_prof: Any = None
        if request_body is not None:
            req_sid = request_body.get("sessionId")
            req_bid = request_body.get("batchId")
            if req_sid is not None:
                if body.get("sessionId") is None or str(body.get("sessionId")) != str(req_sid):
                    return False
            if req_bid is not None:
                if body.get("batchId") is None or str(body.get("batchId")) != str(req_bid):
                    return False
            req_prof = request_body.get("fusionProfile")
            resp_prof = body.get("fusionProfile")
            if req_prof:
                # 3D / profiled requests must echo fusionProfile; mismatch is invalid.
                if resp_prof is None or str(resp_prof).strip() == "":
                    return False
                if str(resp_prof) != str(req_prof):
                    return False
        # New 3D profiles require full typed ProcessResponse (int snapshotSeq, lists, …).
        prof = str(req_prof or body.get("fusionProfile") or "")
        if prof.startswith("multisensor-3d"):
            try:
                ProcessResponse.model_validate(body)
            except ValidationError:
                return False
            return True
        return True

    # --- topics ---
    def _publish(self, kind: str, payload: dict[str, Any], *, retain: bool = False) -> None:
        assert self._client is not None
        topic = self.cfg.topic(kind)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        info = self._client.publish(topic, body, qos=DEFAULT_QOS, retain=retain)
        info.wait_for_publish(timeout=self.cfg.publish_timeout_s)
        is_pub = getattr(info, "is_published", None)
        if callable(is_pub):
            if not is_pub():
                raise PublishNotAcked(
                    f"mqtt_publish_not_acked topic={kind} timeout_s={self.cfg.publish_timeout_s}"
                )
        elif is_pub is False:
            raise PublishNotAcked(f"mqtt_publish_not_acked topic={kind}")
    def _enqueue_status(
        self,
        state: str,
        detail: Optional[dict[str, Any]] = None,
        session_id: str = "",
        *,
        message_id: Optional[str] = None,
    ) -> None:
        msg = build_status(
            tenant_id=self.cfg.tenant_id,
            site_id=self.cfg.site_id,
            session_id=session_id,
            state=state,
            detail=detail,
        )
        mid = message_id or f"status-{state}-{session_id or 'global'}-{utc_now_iso()}"
        self.store.enqueue_outbox(
            message_id=mid,
            kind="status",
            topic_suffix="status",
            payload=msg,
            now_iso=utc_now_iso(),
            retain=True,
        )
        self._wake_outbox()
    def _publish_status(self, state: str, detail: Optional[dict[str, Any]] = None, session_id: str = "") -> None:
        """Enqueue status via outbox (never wait_for_publish on the MQTT network thread)."""
        self._enqueue_status(state, detail, session_id)
    # --- MQTT callbacks (no fusion compute, no PUBACK waits) ---
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        rc = int(getattr(reason_code, "value", reason_code))
        if rc != 0:
            LOG.error("MQTT connect failed rc=%s", reason_code)
            return
        LOG.info("MQTT connected; subscribing")
        client.subscribe(self.cfg.topic("input"), qos=DEFAULT_QOS)
        client.subscribe(self.cfg.topic("control"), qos=DEFAULT_QOS)
        self._connected.set()
        try:
            self._enqueue_status(
                "online",
                {"schemaVersion": SCHEMA_VERSION, "clientId": self.cfg.client_id},
                message_id=f"status-online-{self.cfg.client_id}",
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("status enqueue failed: %s", exc)
    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connected.clear()
        LOG.warning("MQTT disconnected rc=%s", reason_code)
    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Persist before returning so QoS1 PUBACK follows durable inbox store.

        Permanent rejects (bad JSON / schema) return normally → PUBACK (or manual ack).
        Recoverable store failures withhold PUBACK (manual_ack / skip auto ACK).
        """
        mid = getattr(msg, "mid", None)
        manual = bool(getattr(client, "_manual_ack", False))

        def _ack_if_manual() -> None:
            if manual and mid is not None:
                try:
                    qos = int(getattr(msg, "qos", DEFAULT_QOS) or DEFAULT_QOS)
                    client.ack(mid, qos)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("manual PUBACK failed mid=%s: %s", mid, exc)

        if msg.payload is not None and len(msg.payload) > 8_000_000:
            LOG.warning("payload too large on %s (%s bytes)", msg.topic, len(msg.payload))
            _ack_if_manual()
            return
        try:
            raw = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            LOG.warning("invalid JSON on %s: %s", msg.topic, exc)
            _ack_if_manual()
            return
        topic = msg.topic or ""
        try:
            if topic.endswith("/input"):
                self._handle_input(raw)
            elif topic.endswith("/control"):
                self._handle_control(raw)
            else:
                LOG.debug("ignored topic %s", topic)
            _ack_if_manual()
        except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError):
            # Withhold PUBACK: force manual path so auto-ack after callback is skipped,
            # without raising (protocol handler must still return cleanly for probes).
            LOG.exception("durable store failed on %s; withholding PUBACK for redelivery", topic)
            try:
                client._manual_ack = True
            except Exception:  # noqa: BLE001
                pass
            return
        except Exception as exc:  # noqa: BLE001
            LOG.exception("on_message failed (withholding PUBACK): %s", exc)
            try:
                client._manual_ack = True
            except Exception:  # noqa: BLE001
                pass
            return
    def _reject_site_mismatch(self, raw: Any) -> Optional[list[str]]:
        if not isinstance(raw, dict):
            return ["not_an_object"]
        errors: list[str] = []
        tenant = raw.get("tenantId")
        site = raw.get("siteId")
        if tenant is not None and str(tenant) != self.cfg.tenant_id:
            errors.append("tenant_mismatch")
        if site is not None and str(site) != self.cfg.site_id:
            errors.append("site_mismatch")
        return errors or None
    def _handle_input(self, raw: Any) -> None:
        now = utc_now_iso()
        if not isinstance(raw, dict):
            ack = build_ack(
                message_id=f"invalid-{now}",
                tenant_id=self.cfg.tenant_id,
                site_id=self.cfg.site_id,
                session_id="",
                status="rejected",
                detail={"errors": ["not_an_object"]},
            )
            self.store.enqueue_outbox(
                message_id=f"invalid-{now}", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        mismatch = self._reject_site_mismatch(raw)
        errors = list(mismatch or [])
        errors.extend(validate_envelope(raw, expect_types=MESSAGE_TYPES_INPUT))
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        if not any(e.startswith("missing_payload") or e == "not_an_object" for e in errors):
            if isinstance(payload, dict):
                errors.extend(validate_observations_payload(payload))
            else:
                errors.append("missing_payload")
        mid = str(raw.get("messageId") or f"invalid-{now}")
        session_id = str(raw.get("sessionId") or "")
        tenant = str(raw.get("tenantId") or self.cfg.tenant_id)
        site = str(raw.get("siteId") or self.cfg.site_id)
        if errors:
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="rejected",
                detail={"errors": errors},
            )
            self.store.enqueue_outbox(
                message_id=mid, kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        # Write ownership: MQTT path claims mqtt owner; reject if HTTP owns without handover.
        meta = self.store.get_session_meta(session_id)
        owner = str(meta.get("write_owner") or OWNER_NONE)
        if owner == OWNER_HTTP and not int(meta.get("handover_pending") or 0):
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="rejected",
                detail={"errors": ["write_owner_http"], "writeOwner": OWNER_HTTP},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-owner", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        if owner in (OWNER_NONE, OWNER_MQTT) or int(meta.get("handover_pending") or 0):
            self.store.set_write_owner(session_id, OWNER_MQTT, now, handover_pending=False)
        batch_id = str(payload["batchId"])
        fp = content_fingerprint(
            payload, tenant_id=tenant, site_id=site, session_id=session_id
        )
        profile = payload.get("fusionProfile")
        if isinstance(profile, str):
            self._session_profiles[session_id] = profile
            self.store.set_session_runtime(
                session_id, now, fusion_profile=profile, lifecycle="active"
            )
        ack_stored = build_ack(
            message_id=mid,
            tenant_id=tenant,
            site_id=site,
            session_id=session_id,
            status="stored",
            detail={"batchId": batch_id, "contentHash": fp},
        )
        status = self.store.insert_input_transaction(
            message_id=mid,
            session_id=session_id,
            batch_id=batch_id,
            content_hash=fp,
            raw=raw,
            observations=list(payload.get("observations") or []),
            stored_ack=ack_stored,
            now_iso=now,
        )
        if status == "capacity":
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="capacity",
                detail={"reason": "inbox_full", "maxInbox": self.cfg.max_inbox},
            )
            self.store.enqueue_outbox(
                message_id=mid, kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            self._enqueue_status("backpressure", {"inboxFull": True}, session_id=session_id)
            return
        if status == INBOX_DUPLICATE:
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="duplicate",
                detail={"note": "same_id_same_content_not_reexecuted"},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-dup", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        if status == INBOX_CONFLICT:
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="conflict",
                detail={"reason": "same_id_different_content"},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-conflict", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        wake = self._ensure_session_worker(session_id)
        if wake == "queued":
            # Durable stored; worker slot will pick up when free. Accurate observability ack note.
            LOG.info("session %s queued for worker pool (cap=%s)", session_id, self.cfg.max_session_workers)
        self._wake_outbox()
    def _handle_control(self, raw: Any) -> None:
        now = utc_now_iso()
        if not isinstance(raw, dict):
            ack = build_ack(
                message_id=f"ctrl-invalid-{now}",
                tenant_id=self.cfg.tenant_id,
                site_id=self.cfg.site_id,
                session_id="",
                status="rejected",
                detail={"errors": ["not_an_object"]},
            )
            self.store.enqueue_outbox(
                message_id=f"ctrl-invalid-{now}", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        mismatch = self._reject_site_mismatch(raw)
        errors = list(mismatch or [])
        errors.extend(validate_envelope(raw, expect_types=MESSAGE_TYPES_CONTROL))
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        if not errors:
            errors.extend(validate_control_payload(payload))
        mid = str(raw.get("messageId") or f"ctrl-{now}")
        session_id = str(raw.get("sessionId") or "")
        tenant = str(raw.get("tenantId") or self.cfg.tenant_id)
        site = str(raw.get("siteId") or self.cfg.site_id)
        if errors:
            ack = build_ack(
                message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                status="rejected", detail={"errors": errors},
            )
            self.store.enqueue_outbox(
                message_id=mid, kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        action = payload.get("action")
        write_owner = payload.get("writeOwner")
        # Durable control dedupe BEFORE side effects (transfer / owner / resume).
        # tick/flush/run.end use inbox enqueue path which already dedupes.
        if action not in ("tick", "flush", "run.end"):
            has_immediate = bool(
                (action == "run.start" and session_id)
                or (write_owner in (OWNER_MQTT, OWNER_HTTP, OWNER_NONE) and session_id)
                or (payload.get("resume") and session_id)
            )
            if has_immediate:
                ctrl_fp = content_fingerprint(
                    {
                        "action": action,
                        "kind": "control",
                        "writeOwner": write_owner,
                        "handover": payload.get("handover"),
                        "handoverPending": payload.get("handoverPending"),
                        "resume": payload.get("resume"),
                        "batchId": f"ctrl-side-{mid}",
                    },
                    tenant_id=tenant,
                    site_id=site,
                    session_id=session_id,
                )
                dedup_status = self.store.try_insert_inbox(
                    message_id=mid,
                    session_id=session_id or mid,
                    batch_id=f"ctrl-side-{mid}",
                    content_hash=ctrl_fp,
                    raw=raw,
                    now_iso=now,
                )
                if dedup_status == INBOX_DUPLICATE:
                    dup = build_ack(
                        message_id=mid,
                        tenant_id=tenant,
                        site_id=site,
                        session_id=session_id,
                        status="duplicate",
                        detail={"action": action, "note": "control_idempotent"},
                    )
                    self.store.enqueue_outbox(
                        message_id=f"{mid}-dup",
                        kind="ack",
                        topic_suffix="ack",
                        payload=dup,
                        now_iso=now,
                    )
                    self._wake_outbox()
                    return
                if dedup_status == INBOX_CONFLICT:
                    conf = build_ack(
                        message_id=mid,
                        tenant_id=tenant,
                        site_id=site,
                        session_id=session_id,
                        status="conflict",
                        detail={"action": action, "note": "control_content_conflict"},
                    )
                    self.store.enqueue_outbox(
                        message_id=f"{mid}-conflict",
                        kind="ack",
                        topic_suffix="ack",
                        payload=conf,
                        now_iso=now,
                    )
                    self._wake_outbox()
                    return
                if dedup_status == "capacity":
                    cap = build_ack(
                        message_id=mid,
                        tenant_id=tenant,
                        site_id=site,
                        session_id=session_id,
                        status="capacity",
                        detail={"action": action, "reason": "inbox_full"},
                    )
                    self.store.enqueue_outbox(
                        message_id=mid, kind="ack", topic_suffix="ack", payload=cap, now_iso=now
                    )
                    self._wake_outbox()
                    return
                # Side-effect control is recorded; not processable work.
                self.store.mark_inbox_done(mid, now)
        # Ownership / handover controls (no HTTP process).
        if action == "run.start" and session_id:
            self.store.set_write_owner(session_id, OWNER_MQTT, now, handover_pending=False)
            self.store.set_session_paused(session_id, False, now, reason=None)
        if write_owner in (OWNER_MQTT, OWNER_HTTP, OWNER_NONE) and session_id:
            handover = bool(payload.get("handover") or payload.get("handoverPending"))
            transfer_err: Optional[str] = None
            if handover or write_owner != OWNER_MQTT:
                try:
                    self._core_transfer_owner(
                        session_id,
                        new_owner=str(write_owner),
                        from_owner=OWNER_MQTT if write_owner != OWNER_MQTT else None,
                        reason=f"control:{action or 'writeOwner'}",
                    )
                except Exception as exc:  # noqa: BLE001
                    transfer_err = str(exc)
                    LOG.warning("core write-owner transfer failed: %s", exc)
            self.store.set_write_owner(
                session_id,
                str(write_owner),
                now,
                handover_pending=bool(handover and transfer_err),
            )
            if transfer_err:
                ack = build_ack(
                    message_id=mid,
                    tenant_id=tenant,
                    site_id=site,
                    session_id=session_id,
                    status="error",
                    detail={"action": action, "note": "core_handover_failed", "error": transfer_err},
                )
                self.store.enqueue_outbox(
                    message_id=f"{mid}-handover-error",
                    kind="ack",
                    topic_suffix="ack",
                    payload=ack,
                    now_iso=now,
                )
                self._wake_outbox()
                return
        if payload.get("resume") and session_id:
            self.store.set_session_paused(session_id, False, now, reason=None)
        if action in ("tick", "flush", "run.end") and session_id:
            self._enqueue_control_work(
                mid=mid,
                session_id=session_id,
                tenant=tenant,
                site=site,
                action=str(action),
                raw=raw,
                now=now,
            )
            return
        # Other controls: stored ack only.
        ack = build_ack(
            message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
            status="stored", detail={"action": action},
        )
        self.store.enqueue_outbox(
            message_id=mid, kind="ack", topic_suffix="ack", payload=ack, now_iso=now
        )
        self._wake_outbox()
    def _enqueue_control_work(
        self,
        *,
        mid: str,
        session_id: str,
        tenant: str,
        site: str,
        action: str,
        raw: dict[str, Any],
        now: str,
    ) -> None:
        """Persist control as an ordered per-session work item (idempotent by messageId)."""
        profile = self._session_profiles.get(session_id)
        if not profile:
            meta = self.store.get_session_meta(session_id)
            persisted = meta.get("fusion_profile")
            if isinstance(persisted, str) and persisted:
                profile = persisted
                self._session_profiles[session_id] = profile
        # flush / run.end use mode=flush. Do NOT stamp processingTime at enqueue:
        # FIFO may still hold earlier data; PT is assigned on first queue-head execute
        # and then reused on retry (monotonic vs prior batches, same body on retry).
        http_mode = "flush" if action in ("flush", "run.end") else "realtime"
        batch_id = f"ctrl-{action}-{mid}"
        work_item: dict[str, Any] = {
            "kind": "control",
            "action": action,
            "sessionId": session_id,
            "batchId": batch_id,
            "mode": http_mode,
            "fusionProfile": profile,
            "observations": [],
            "controlRefMessageId": mid,
            "tenantId": tenant,
            "siteId": site,
        }
        fp = content_fingerprint(
            {"batchId": batch_id, "action": action, "kind": "control", "mode": http_mode},
            tenant_id=tenant,
            site_id=site,
            session_id=session_id,
        )
        # Immediate stored vs draining ack (not processed / drained yet).
        ack_status = "draining" if action == "run.end" else "stored"
        if action == "run.end":
            # Stop idle ticks while draining; final mark to ended happens on success.
            self.store.set_session_runtime(session_id, now, lifecycle="ending")
        ack = build_ack(
            message_id=mid,
            tenant_id=tenant,
            site_id=site,
            session_id=session_id,
            status=ack_status,
            detail={
                "action": action,
                "inboxStats": self.store.session_stats(session_id),
                "note": "control_enqueued",
            },
        )
        # Build a synthetic envelope so claim/process path is uniform.
        envelope = {
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "control",
            "messageId": mid,
            "tenantId": tenant,
            "siteId": site,
            "sessionId": session_id,
            "sentAt": now,
            "payload": raw.get("payload") if isinstance(raw.get("payload"), dict) else {"action": action},
        }
        status = self.store.try_insert_inbox(
            message_id=mid,
            session_id=session_id,
            batch_id=batch_id,
            content_hash=fp,
            raw=envelope,
            now_iso=now,
        )
        if status == INBOX_DUPLICATE:
            dup = build_ack(
                message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                status="duplicate", detail={"action": action},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-dup", kind="ack", topic_suffix="ack", payload=dup, now_iso=now
            )
            self._wake_outbox()
            return
        if status == INBOX_CONFLICT:
            conf = build_ack(
                message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                status="conflict", detail={"action": action},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-conflict", kind="ack", topic_suffix="ack", payload=conf, now_iso=now
            )
            self._wake_outbox()
            return
        if status == "capacity":
            cap = build_ack(
                message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                status="capacity", detail={"action": action, "reason": "inbox_full"},
            )
            self.store.enqueue_outbox(
                message_id=mid, kind="ack", topic_suffix="ack", payload=cap, now_iso=now
            )
            self._wake_outbox()
            return
        self.store.set_work_item(mid, work_item, now)
        self.store.enqueue_outbox(
            message_id=f"{mid}-{ack_status}", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
        )
        self._ensure_session_worker(session_id)
        self._wake_outbox()
    # --- session workers (hard capped pool) ---
    def _ensure_session_worker(self, session_id: str) -> str:
        """Start or wake a session worker. Never exceeds max_session_workers threads.
        Returns: started | woken | queued
        """
        if not session_id:
            return "queued"
        with self._session_lock:
            ev = self._session_events.get(session_id)
            if ev is not None:
                ev.set()
                return "woken"
            if len(self._session_threads) >= self.cfg.max_session_workers:
                if session_id not in self._waiting_sessions:
                    self._waiting_sessions.append(session_id)
                LOG.info(
                    "session worker cap=%s; queueing session %s (waiting=%s)",
                    self.cfg.max_session_workers,
                    session_id,
                    len(self._waiting_sessions),
                )
                return "queued"
            return self._start_session_worker_locked(session_id)
    def _start_session_worker_locked(self, session_id: str) -> str:
        ev = threading.Event()
        self._session_events[session_id] = ev
        t = threading.Thread(
            target=self._session_loop,
            args=(session_id, ev),
            name=f"mqtt-session-{session_id[:24]}",
            daemon=True,
        )
        self._session_threads[session_id] = t
        t.start()
        ev.set()
        return "started"
    def _on_session_worker_exit(self, session_id: str) -> None:
        with self._session_lock:
            self._session_threads.pop(session_id, None)
            self._session_events.pop(session_id, None)
            while self._waiting_sessions and len(self._session_threads) < self.cfg.max_session_workers:
                nxt = self._waiting_sessions.pop(0)
                if nxt in self._session_threads:
                    continue
                self._start_session_worker_locked(nxt)
    def _session_loop(self, session_id: str, ev: threading.Event) -> None:
        LOG.info("session worker start %s", session_id)
        idle_rounds = 0
        try:
            while not self._stop.is_set():
                ev.wait(timeout=1.0)
                ev.clear()
                worked = False
                while not self._stop.is_set():
                    row = self.store.claim_next_for_session(session_id, utc_now_iso())
                    if row is None:
                        break
                    worked = True
                    self._process_inbox_row(row)
                if worked:
                    idle_rounds = 0
                else:
                    idle_rounds += 1
                    # Free the worker slot so queued sessions can run.
                    if idle_rounds >= 2:
                        break
        finally:
            LOG.info("session worker stop %s", session_id)
            self._on_session_worker_exit(session_id)
    def _process_inbox_row(self, row: dict[str, Any]) -> None:
        now = utc_now_iso()
        mid = row["message_id"]
        raw = json.loads(row["raw_json"])
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        tenant = str(raw.get("tenantId") or self.cfg.tenant_id)
        site = str(raw.get("siteId") or self.cfg.site_id)
        session_id = str(raw.get("sessionId") or row.get("session_id") or "")
        work_item: dict[str, Any]
        if row.get("work_item_json"):
            work_item = json.loads(row["work_item_json"])
        else:
            work_item = {
                "sessionId": session_id,
                "batchId": payload.get("batchId") or mid,
                "mode": payload.get("mode") or "realtime",
                "fusionProfile": payload.get("fusionProfile"),
                "processingTime": now,
                "observations": list(payload.get("observations") or []),
            }
            self.store.set_work_item(mid, work_item, now)
        # First execution assigns durable processingTime; retries reuse it.
        if not work_item.get("processingTime"):
            work_item = {**work_item, "processingTime": now}
            self.store.set_work_item(mid, work_item, now)
        if work_item.get("kind") == "control" and work_item.get("action") == "run.end":
            self._process_run_end(row, work_item, tenant=tenant, site=site, session_id=session_id)
            return
        http_body = {
            k: v
            for k, v in work_item.items()
            if k not in ("kind", "action", "controlRefMessageId", "tenantId", "siteId") and v is not None
        }
        if "sessionId" not in http_body:
            http_body["sessionId"] = session_id
        url = urljoin(self.cfg.http_base_url + "/", "v1/fusion/process")
        last_exc: Optional[Exception] = None
        resp: Optional[httpx.Response] = None
        for attempt in range(1, self.cfg.http_retries + 1):
            try:
                resp = self._core_post(url, http_body, session_id=session_id)
                if resp.status_code >= 500:
                    last_exc = RuntimeError(f"http_{resp.status_code}")
                    LOG.warning("HTTP 5xx attempt %s for %s: %s", attempt, mid, resp.status_code)
                    if attempt < self.cfg.http_retries:
                        time.sleep(min(2 ** attempt, 8))
                        continue
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                LOG.warning("HTTP attempt %s failed for %s: %s", attempt, mid, exc)
                if attempt < self.cfg.http_retries:
                    time.sleep(min(2 ** attempt, 8))
        else:
            attempt_n = self.store.mark_inbox_error(
                mid,
                f"http_transport:{last_exc}",
                now,
                retryable=True,
                increment_attempt=True,
                next_attempt_at=self._backoff_iso(now, int(row.get("attempt_count") or 0) + 1),
            )
            if attempt_n >= self.cfg.http_retries:
                self.store.mark_inbox_dead(mid, f"dead_letter:{last_exc}", now)
                ack = build_ack(
                    message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                    status="error", detail={"error": str(last_exc), "deadLetter": True},
                )
            else:
                ack = build_ack(
                    message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                    status="transient_error", detail={"error": str(last_exc), "attempt": attempt_n},
                )
            self.store.enqueue_outbox(
                message_id=f"{mid}-ack", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self._wake_outbox()
            return
        assert resp is not None
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = {"raw": resp.text}
        if not isinstance(body, dict):
            body = {"error": "non_object_response", "raw": body}
        if resp.status_code < 400 and not self._valid_process_response(body, http_body):
            now_bad = utc_now_iso()
            attempt_n = self.store.mark_inbox_error(
                mid,
                "core_response_correlation_failed",
                now_bad,
                retryable=True,
                increment_attempt=True,
                next_attempt_at=self._backoff_iso(now_bad, int(row.get("attempt_count") or 0) + 1),
            )
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="error",
                detail={
                    "error": "response_correlation_failed",
                    "attempt": attempt_n,
                    "bodySessionId": body.get("sessionId") if isinstance(body, dict) else None,
                    "bodyBatchId": body.get("batchId") if isinstance(body, dict) else None,
                },
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-ack", kind="ack", topic_suffix="ack", payload=ack, now_iso=now_bad
            )
            self._wake_outbox()
            return
        if resp.status_code >= 400:
            status = map_http_error_to_ack_status(resp.status_code, body)
            retryable = status == "transient_error"
            if retryable:
                attempt_n = self.store.mark_inbox_error(
                    mid,
                    f"http_{resp.status_code}:{status}",
                    now,
                    retryable=True,
                    increment_attempt=True,
                    next_attempt_at=self._backoff_iso(now, int(row.get("attempt_count") or 0) + 1),
                )
                if attempt_n >= self.cfg.http_retries:
                    self.store.mark_inbox_dead(mid, f"dead_letter:http_{resp.status_code}", now)
                    status = "error"
                    retryable = False
            else:
                self.store.mark_inbox_error(mid, f"http_{resp.status_code}:{status}", now, retryable=False)
            if status == "state_recovery_required" or (
                isinstance(body, dict)
                and (
                    body.get("error") == "state_recovery_required"
                    or (isinstance(body.get("detail"), dict) and body["detail"].get("error") == "state_recovery_required")
                )
            ):
                self.store.set_session_paused(
                    session_id, True, now, reason="state_recovery_required"
                )
                self._enqueue_status(
                    "state_recovery_required",
                    {"refMessageId": mid, "httpStatus": resp.status_code, "body": body},
                    session_id=session_id,
                )
            ack = build_ack(
                message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
                status=status, detail={"httpStatus": resp.status_code, "body": body},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-ack", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            if not retryable:
                self.store.mark_inbox_done(mid, now)
            self._wake_outbox()
            return
        # Success path — detect epoch change across successful 200s.
        epoch = body.get("epoch")
        meta = self.store.get_session_meta(session_id)
        expected = meta.get("expected_epoch")
        if expected and epoch and str(epoch) != str(expected):
            self.store.set_session_paused(
                session_id,
                True,
                now,
                reason="epoch_changed",
                expected_epoch=str(epoch),
            )
            # Prefer _publish_status so tests/hooks that patch it observe recovery.
            self._publish_status(
                "state_recovery_required",
                {
                    "refMessageId": mid,
                    "previousEpoch": expected,
                    "newEpoch": epoch,
                    "note": "epoch_changed_on_200",
                },
                session_id=session_id,
            )
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="state_recovery_required",
                detail={"previousEpoch": expected, "newEpoch": epoch},
            )
            # Persist response outbox + done so the probing request is accounted, then pause.
            result = build_result(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                process_response=body,
                evidence_index={},
            )
            self.store.complete_success_transaction(
                message_id=mid,
                result_payload=result,
                ack_payload=ack,
                now_iso=now,
                expected_epoch=str(epoch),
                session_id=session_id,
            )
            self._wake_outbox()
            return
        oids: list[str] = []
        for pt in (body.get("trajectoryUpdates") or []):
            oids.extend(pt.get("observationIds") or [])
            oids.extend(pt.get("altitudeObservationIds") or [])
        for pt in (body.get("altitudeUpdates") or []):
            oids.extend(pt.get("altitudeObservationIds") or [])
        stored_obs = self.store.lookup_observations(oids, session_id=session_id)
        evidence_index = {oid: evidence_from_observation(obs) for oid, obs in stored_obs.items()}
        result = build_result(
            message_id=mid,
            tenant_id=tenant,
            site_id=site,
            session_id=session_id,
            process_response=body,
            evidence_index=evidence_index,
        )
        ack = build_ack(
            message_id=mid,
            tenant_id=tenant,
            site_id=site,
            session_id=session_id,
            status="processed",
            detail={
                "batchId": body.get("batchId"),
                "epoch": body.get("epoch"),
                "snapshotSeq": body.get("snapshotSeq"),
                "trajectoryUpdateCount": len(body.get("trajectoryUpdates") or []),
                "altitudeUpdateCount": len(body.get("altitudeUpdates") or []),
                "rejectedCount": len(body.get("rejected") or []),
                "controlAction": work_item.get("action"),
            },
        )
        self.store.complete_success_transaction(
            message_id=mid,
            result_payload=result,
            ack_payload=ack,
            now_iso=now,
            expected_epoch=str(epoch) if epoch else None,
            session_id=session_id,
        )
        self._wake_outbox()
    def _process_run_end(
        self,
        row: dict[str, Any],
        work_item: dict[str, Any],
        *,
        tenant: str,
        site: str,
        session_id: str,
    ) -> None:
        """Flush core reorder tail; drain only after valid response and published results."""
        mid = row["message_id"]
        result_mid = f"{mid}-flush-result"
        # If a flush result is already durable, never rebuild/overwrite it.
        existing_result = self.store.get_outbox_by_message_kind(result_mid, "result")
        stage = str(work_item.get("flushStage") or "")
        if existing_result is not None and stage in ("result_enqueued", "core_ok", ""):
            if not stage:
                work_item = {**work_item, "flushStage": "result_enqueued"}
                self.store.set_work_item(mid, work_item, utc_now_iso())
            # Skip re-flush; continue drain/publish wait below.
            flush_body = None
            url = None
        else:
            # Persist flush body once (same ID/body/processingTime on retry).
            flush_body = {
                k: v
                for k, v in work_item.items()
                if k
                not in (
                    "kind",
                    "action",
                    "controlRefMessageId",
                    "tenantId",
                    "siteId",
                    "flushStage",
                )
                and v is not None
            }
            flush_body["sessionId"] = session_id
            flush_body["batchId"] = f"ctrl-run.end-flush-{mid}"
            flush_body["mode"] = "flush"
            flush_body["observations"] = []
            if "processingTime" not in flush_body:
                flush_body["processingTime"] = utc_now_iso()
                self.store.set_work_item(
                    mid,
                    {**work_item, "processingTime": flush_body["processingTime"]},
                    utc_now_iso(),
                )
            url = urljoin(self.cfg.http_base_url + "/", "v1/fusion/process")

        def _fail(note: str, err: str, *, retryable: bool = True, pause: bool = False, pause_reason: Optional[str] = None) -> None:
            now_fail = utc_now_iso()
            attempt = int(row.get("attempt_count") or 0) + 1
            next_at = self._backoff_iso(now_fail, attempt) if retryable else None
            fail_ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="error",
                detail={"action": "run.end", "note": note, "error": err, "attempt": attempt},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-flush-error-{attempt}",
                kind="ack",
                topic_suffix="ack",
                payload=fail_ack,
                now_iso=now_fail,
            )
            self.store.mark_inbox_error(
                mid,
                f"{note}:{err}",
                now_fail,
                retryable=retryable,
                increment_attempt=True,
                next_attempt_at=next_at,
            )
            if pause:
                self.store.set_session_paused(
                    session_id, True, now_fail, reason=pause_reason or note
                )
            self._wake_outbox()

        if flush_body is not None and url is not None:
            try:
                flush_resp = self._core_post(url, flush_body, session_id=session_id)
                try:
                    flush_body_json: Any = flush_resp.json()
                except Exception:  # noqa: BLE001
                    flush_body_json = {"raw": getattr(flush_resp, "text", "")}
                status_code = int(getattr(flush_resp, "status_code", 500))
                if status_code >= 400:
                    raise RuntimeError(f"core_flush_http_{status_code}")
                if not self._valid_process_response(flush_body_json, flush_body):
                    raise RuntimeError("core_flush_invalid_response")
                meta = self.store.get_session_meta(session_id) or {}
                expected = meta.get("expected_epoch")
                new_epoch = flush_body_json.get("epoch")
                if expected and new_epoch and str(new_epoch) != str(expected):
                    _fail(
                        "epoch_changed",
                        f"{expected}->{new_epoch}",
                        retryable=False,
                        pause=True,
                        pause_reason="epoch_changed",
                    )
                    self.store.set_session_paused(
                        session_id,
                        True,
                        utc_now_iso(),
                        reason="epoch_changed",
                        expected_epoch=str(new_epoch),
                    )
                    return
                now_flush = utc_now_iso()
                result = build_result(
                    message_id=f"{mid}-flush",
                    tenant_id=tenant,
                    site_id=site,
                    session_id=session_id,
                    process_response=flush_body_json,
                    evidence_index=self.store.lookup_observations(
                        [
                            oid
                            for pt in (flush_body_json.get("trajectoryUpdates") or [])
                            for oid in (pt.get("observationIds") or [])
                            + (pt.get("altitudeObservationIds") or [])
                        ]
                        + [
                            oid
                            for pt in (flush_body_json.get("altitudeUpdates") or [])
                            for oid in (pt.get("altitudeObservationIds") or [])
                        ],
                        session_id=session_id,
                    ),
                )
                try:
                    self.store.enqueue_outbox(
                        message_id=result_mid,
                        kind="result",
                        topic_suffix="result",
                        payload=result,
                        now_iso=now_flush,
                    )
                except OutboxImmutableConflict as exc:
                    LOG.error("run.end result outbox conflict (retained original): %s", exc)
                work_item = {**work_item, "flushStage": "result_enqueued"}
                self.store.set_work_item(mid, work_item, now_flush)
                if new_epoch:
                    self.store.set_session_paused(
                        session_id, False, now_flush, expected_epoch=str(new_epoch)
                    )
                self._wake_outbox()
            except Exception as exc:  # noqa: BLE001
                LOG.warning("run.end core flush failed for %s: %s", mid, exc)
                _fail("core_flush_failed", str(exc), retryable=True)
                return

        deadline = time.time() + max(30.0, self.cfg.http_timeout_s * 2)
        while not self._stop.is_set() and time.time() < deadline:
            stats = self.store.session_stats(session_id)
            # Exclude this run.end row: idle ticks / earlier work must reach 0.
            active_others = self.store.session_active_count_excluding(session_id, mid)
            pending_results = self.store.session_pending_outbox_count(
                session_id, kinds={"result"}
            )
            # Core released + results durable pending is not overall drained.
            if active_others == 0 and pending_results == 0:
                break
            if active_others == 0 and pending_results > 0 and not self._connected.is_set():
                now = utc_now_iso()
                ack = build_ack(
                    message_id=mid,
                    tenant_id=tenant,
                    site_id=site,
                    session_id=session_id,
                    status="pending",
                    detail={
                        "action": "run.end",
                        "note": "core_drained_results_unconfirmed",
                        "pendingResults": pending_results,
                        "connected": False,
                    },
                )
                self.store.enqueue_outbox(
                    message_id=f"{mid}-pending-delivery",
                    kind="ack",
                    topic_suffix="ack",
                    payload=ack,
                    now_iso=now,
                )
                self.store.mark_inbox_error(
                    mid,
                    "results_unconfirmed_broker_offline",
                    now,
                    retryable=True,
                    increment_attempt=True,
                    next_attempt_at=self._backoff_iso(now, int(row.get("attempt_count") or 0) + 1),
                )
                self._wake_outbox()
                return
            # Process other unfinished work even when run.end is the created_at head
            # (idle ticks may arrive after enqueue).
            sibling = self.store.claim_next_for_session_excluding(
                session_id, mid, utc_now_iso()
            )
            if sibling is not None:
                self._process_inbox_row(sibling)
                continue
            self._wake_outbox()
            time.sleep(0.05)
        else:
            stats = self.store.session_stats(session_id)
            now = utc_now_iso()
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="draining",
                detail={"action": "run.end", "inboxStats": stats, "note": "drain_timeout"},
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-draining", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
            )
            self.store.mark_inbox_error(
                mid,
                "drain_timeout",
                now,
                retryable=True,
                increment_attempt=True,
                next_attempt_at=self._backoff_iso(now, int(row.get("attempt_count") or 0) + 1),
            )
            self._wake_outbox()
            return

        pending_results = self.store.session_pending_outbox_count(session_id, kinds={"result"})
        if pending_results > 0:
            now = utc_now_iso()
            ack = build_ack(
                message_id=mid,
                tenant_id=tenant,
                site_id=site,
                session_id=session_id,
                status="pending",
                detail={
                    "action": "run.end",
                    "note": "results_still_pending",
                    "pendingResults": pending_results,
                },
            )
            self.store.enqueue_outbox(
                message_id=f"{mid}-pending-delivery",
                kind="ack",
                topic_suffix="ack",
                payload=ack,
                now_iso=now,
            )
            self.store.mark_inbox_error(
                mid,
                "results_still_pending",
                now,
                retryable=True,
                increment_attempt=True,
                next_attempt_at=self._backoff_iso(now, int(row.get("attempt_count") or 0) + 1),
            )
            self._wake_outbox()
            return

        now = utc_now_iso()
        stats = self.store.session_stats(session_id)
        detail = {
            "action": "run.end",
            "inboxStats": stats,
            "note": "realtime_run_drained",
            "outboxPending": self.store.session_pending_outbox_count(session_id),
        }
        self._enqueue_status("run_end", detail, session_id=session_id, message_id=f"status-runend-{mid}")
        ack = build_ack(
            message_id=mid, tenant_id=tenant, site_id=site, session_id=session_id,
            status="drained",
            detail=detail,
        )
        ack_proc = build_ack(
            message_id=f"{mid}-processed", tenant_id=tenant, site_id=site, session_id=session_id,
            status="processed",
            detail=detail,
        )
        self.store.enqueue_outbox(
            message_id=f"{mid}-drained", kind="ack", topic_suffix="ack", payload=ack, now_iso=now
        )
        self.store.enqueue_outbox(
            message_id=f"{mid}-processed", kind="ack", topic_suffix="ack", payload=ack_proc, now_iso=now
        )
        self.store.mark_inbox_done(mid, now)
        self.store.set_session_runtime(session_id, now, lifecycle="ended")
        self._wake_outbox()
    @staticmethod
    def _backoff_iso(now_iso: str, attempt: int) -> str:
        try:
            base = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        except ValueError:
            base = datetime.now(timezone.utc)
        delay = min(2 ** max(1, attempt), 30)
        return (base + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    # --- outbox publisher ---
    def _wake_outbox(self) -> None:
        self._outbox_event.set()
    def _outbox_loop(self) -> None:
        while not self._stop.is_set():
            self._outbox_event.wait(timeout=1.0)
            self._outbox_event.clear()
            if not self._connected.is_set():
                continue
            for row in self.store.claim_pending_outbox(100):
                if self._stop.is_set():
                    break
                try:
                    payload = json.loads(row["payload_json"])
                    retain = bool(row.get("retain"))
                    self._publish(row["topic_suffix"], payload, retain=retain)
                    self.store.mark_outbox_published(int(row["id"]), utc_now_iso())
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("outbox publish failed id=%s: %s", row["id"], exc)
                    # Leave pending for republish; do not mark published.
                    break
    def _idle_tick_loop(self) -> None:
        """Enqueue durable empty-observation tick work items on a timer (same serial queue)."""
        while not self._stop.is_set():
            self._stop.wait(self.cfg.idle_tick_s)
            if self._stop.is_set():
                break
            for sid in self.store.list_active_sessions():
                meta = self.store.get_session_meta(sid)
                if int(meta.get("paused") or 0):
                    continue
                if str(meta.get("lifecycle") or "active") != "active":
                    continue
                if str(meta.get("write_owner") or OWNER_NONE) == OWNER_HTTP:
                    continue
                now = utc_now_iso()
                mid = f"idle-tick-{sid}-{now}"
                self._enqueue_control_work(
                    mid=mid,
                    session_id=sid,
                    tenant=self.cfg.tenant_id,
                    site=self.cfg.site_id,
                    action="tick",
                    raw={
                        "schemaVersion": SCHEMA_VERSION,
                        "messageType": "control",
                        "messageId": mid,
                        "tenantId": self.cfg.tenant_id,
                        "siteId": self.cfg.site_id,
                        "sessionId": sid,
                        "sentAt": now,
                        "payload": {"action": "tick", "idle": True},
                    },
                    now=now,
                )
                # If no live worker owns this session (pool full / test stub), advance
                # one durable tick inline so lifecycle still moves.
                with self._session_lock:
                    has_worker = sid in self._session_threads
                if not has_worker:
                    row = self.store.claim_next_for_session(sid, now)
                    if row is not None:
                        self._process_inbox_row(row)
    # --- lifecycle ---
    def start(self) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.cfg.client_id,
            protocol=mqtt.MQTTv311,
            clean_session=False,
        )
        # PUBACK only after durable store succeeds (see _on_message).
        if hasattr(client, "manual_ack_set"):
            client.manual_ack_set(True)
        else:
            client._manual_ack = True
        if self.cfg.username:
            client.username_pw_set(self.cfg.username, self.cfg.password)
        lwt = build_status(
            tenant_id=self.cfg.tenant_id,
            site_id=self.cfg.site_id,
            session_id="",
            state="offline",
            detail={"lwt": True, "clientId": self.cfg.client_id},
        )
        client.will_set(
            self.cfg.topic("status"),
            json.dumps(lwt, ensure_ascii=False),
            qos=DEFAULT_QOS,
            retain=True,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(
            min_delay=int(self.cfg.reconnect_min_s),
            max_delay=int(self.cfg.reconnect_max_s),
        )
        self._client = client
        self._outbox_thread = threading.Thread(target=self._outbox_loop, name="mqtt-outbox", daemon=True)
        self._outbox_thread.start()
        self._idle_tick_thread = threading.Thread(
            target=self._idle_tick_loop, name="mqtt-idle-tick", daemon=True
        )
        self._idle_tick_thread.start()
        for sid in self.store.list_active_sessions():
            self._ensure_session_worker(sid)
        self._wake_outbox()
        client.connect_async(self.cfg.broker_host, self.cfg.broker_port, keepalive=self.cfg.keepalive_s)
        client.loop_start()
        LOG.info(
            "bridge started broker=%s:%s http=%s sqlite=%s workers=%s",
            self.cfg.broker_host,
            self.cfg.broker_port,
            self.cfg.http_base_url,
            self.cfg.sqlite_path,
            self.cfg.max_session_workers,
        )
    def stop(self) -> None:
        self._stop.set()
        self._wake_outbox()
        with self._session_lock:
            for ev in self._session_events.values():
                ev.set()
            threads = list(self._session_threads.values())
        if self._outbox_thread is not None:
            threads.append(self._outbox_thread)
        if self._idle_tick_thread is not None:
            threads.append(self._idle_tick_thread)
        for t in threads:
            t.join(timeout=5.0)
        if self._client is not None:
            try:
                # Enqueue only — outbox may already be stopping; best-effort LWT covers offline.
                self._enqueue_status("stopping", message_id=f"status-stopping-{self.cfg.client_id}")
            except Exception:  # noqa: BLE001
                pass
            self._client.loop_stop()
            self._client.disconnect()
        # Join workers before closing shared HTTP / SQLite.
        self._http.close()
        self.store.close()
    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            LOG.info("KeyboardInterrupt")
        finally:
            self.stop()
def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=os.getenv("TASK008_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    bridge = MqttBridge(BridgeConfig.from_env())
    bridge.run_forever()
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
