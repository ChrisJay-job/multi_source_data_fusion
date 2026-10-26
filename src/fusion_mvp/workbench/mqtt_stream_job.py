"""Server-side 1× MQTT stream jobs driven by the workbench UI.

Page starts/stops jobs; this module publishes real fusion-mqtt.v1 observations and
subscribes to result/ack for SSE. Does not connect the browser to port 1883.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fusion_mvp.integration.schemas import SCHEMA_VERSION, utc_now_iso

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None  # type: ignore

# Application-level drain wait: timeout → failed (never fake-complete).
_DRAIN_WAIT_S = 30.0
_SUBSCRIBE_WAIT_S = 5.0
_START_ACK_WAIT_S = 10.0
_EVENT_BUFFER_SOFT = 4000
_EVENT_BUFFER_KEEP = 3000
_EVENT_BUFFER_SOFT_BYTES = 8 * 1024 * 1024  # ~8 MiB retained event payloads
_EVENT_BUFFER_KEEP_BYTES = 6 * 1024 * 1024
_EVENT_PAGE_MAX_COUNT = 200
_EVENT_PAGE_MAX_BYTES = 256 * 1024  # response byte budget (not silent empty)
_EVENT_SINGLE_MAX_BYTES = 64 * 1024
_MAX_RETAINED_JOBS = 16
_MAX_SEEN_IDS = 20000
_BACKPRESSURE_PENDING = 64
_BACKPRESSURE_AWAITING = 64
# Per-shard packing for trajectory/altitude when a slim result still exceeds single-event budget.
_SHARD_TRAJ_CHUNK = 32
_SHARD_ALT_CHUNK = 32


def _utf8_json_bytes(obj: Any) -> int:
    """UTF-8 byte length of JSON (not Python char count)."""
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:  # noqa: BLE001
        return 0


# Current track snapshot fields kept for UI (omit committedHistory — points live in trajectoryUpdates).
_TRACK_CURRENT_KEEP = (
    "fusionId",
    "trackSegmentId",
    "aircraftId",
    "longitude",
    "latitude",
    "altitude",
    "altitudeDatum",
    "altitudeMode",
    "altitudeStateTime",
    "lastAltitudeObservedAt",
    "altitudeObservationIds",
    "speed",
    "heading",
    "verticalSpeed",
    "stateTime",
    "lastObservedAt",
    "displayStateTime",
    "trackStatus",
    "positionMode",
    "positionSource",
    "sources",
    "sourceTracks",
    "qualityFlags",
    "aliases",
    "identityStatus",
    "objectClass",
    "fusionMethod",
    "contributingSources",
)

# Soft cap for a single evidence.rawRef / retained blob in transport (UTF-8 chars ≈ bytes for ASCII).
_EVIDENCE_RAW_REF_MAX_CHARS = 4096

# Business evidence that must survive transport bounding (null values retained).
_EVIDENCE_ESSENTIAL_KEYS = (
    "observationId",
    "source",
    "detectorId",
    "sourceTrackId",
    "aircraftId",
    "measurementTime",
    "longitude",
    "latitude",
    "altitude",
    "altitudeDatum",
    "receivedAt",
    "role",
    "qualityFlags",
)

_TRAJECTORY_UPDATE_KEEP = (
    "pointId",
    "fusionId",
    "trackSegmentId",
    "longitude",
    "latitude",
    "altitude",
    "altitudeDatum",
    "altitudeMode",
    "stateTime",
    "observationIds",
    "altitudeObservationIds",
    "positionMode",
    "contributingSources",
    "source",
    "altitudeSigmaM",
    "altitudePriorNote",
)

_ALTITUDE_UPDATE_KEEP = (
    "altitudeUpdateId",
    "fusionId",
    "trackSegmentId",
    "longitude",
    "latitude",
    "altitude",
    "altitudeDatum",
    "altitudeMode",
    "stateTime",
    "altitudeObservationIds",
    "observationIds",
    "role",
    "source",
    "altitudeSigmaM",
)


def _truncate_large_json_values(obj: Any, max_chars: int, *, depth: int = 0) -> tuple[Any, bool, int]:
    """Recursively omit oversized string leaves in nested JSON; return (obj, truncated, approx_bytes)."""
    if depth > 16:
        return obj, False, 0
    if isinstance(obj, str):
        if len(obj) > max_chars:
            return None, True, len(obj.encode("utf-8"))
        return obj, False, 0
    if isinstance(obj, list):
        out_l: list[Any] = []
        trunc = False
        approx = 0
        for x in obj:
            y, t, a = _truncate_large_json_values(x, max_chars, depth=depth + 1)
            trunc = trunc or t
            approx += a
            out_l.append(y)
        return out_l, trunc, approx
    if isinstance(obj, dict):
        out_d: dict[str, Any] = {}
        trunc = False
        approx = 0
        for k, v in obj.items():
            y, t, a = _truncate_large_json_values(v, max_chars, depth=depth + 1)
            trunc = trunc or t
            approx += a
            out_d[k] = y
        if trunc:
            out_d["evidenceTruncated"] = True
            out_d["approxBytes"] = int(approx)
            out_d["hint"] = "raw_blob_omitted_over_transport_budget"
        return out_d, trunc, approx
    return obj, False, 0


def _bound_evidence_item(item: Any, *, strip_raw_ref: bool = False) -> Any:
    """Keep essential source evidence; omit/truncate only oversized raw attachment bodies."""
    if not isinstance(item, dict):
        return item
    e: dict[str, Any] = {}
    for k, v in item.items():
        if k == "rawRef":
            continue
        e[k] = v
    # Ensure essential keys present when they existed (including explicit null).
    for k in _EVIDENCE_ESSENTIAL_KEYS:
        if k in item:
            e[k] = item[k]
    if strip_raw_ref:
        e["rawRef"] = {
            "evidenceTruncated": True,
            "hint": "raw_blob_omitted_over_transport_budget",
            "approxBytes": _utf8_json_bytes(item.get("rawRef")),
        }
        return e
    raw = item.get("rawRef")
    if raw is None:
        return e
    if isinstance(raw, str) and len(raw) > _EVIDENCE_RAW_REF_MAX_CHARS:
        e["rawRef"] = {
            "evidenceTruncated": True,
            "approxBytes": len(raw.encode("utf-8")),
            "hint": "raw_blob_omitted_over_transport_budget",
        }
        return e
    bound, trunc, approx = _truncate_large_json_values(raw, _EVIDENCE_RAW_REF_MAX_CHARS)
    if trunc:
        if isinstance(bound, dict):
            e["rawRef"] = bound
        else:
            e["rawRef"] = {
                "evidenceTruncated": True,
                "approxBytes": approx,
                "hint": "raw_blob_omitted_over_transport_budget",
            }
    else:
        e["rawRef"] = bound
    return e


def _bound_evidence_list(evidence: Any, *, strip_raw_ref: bool = False) -> list[Any]:
    """Bound each evidence item; never drop observationId / source / XYZ / time."""
    if not isinstance(evidence, list):
        return []
    return [_bound_evidence_item(item, strip_raw_ref=strip_raw_ref) for item in evidence]


def _constrain_update_for_transport(u: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Last-resort slim: keep update identity + essential evidence; omit raw blobs only."""
    keys = _TRAJECTORY_UPDATE_KEEP if kind == "trajectory" else _ALTITUDE_UPDATE_KEEP
    keep = {k: u.get(k) for k in keys if k in u}
    # Always surface identity keys even if somehow missing from input (null).
    if kind == "trajectory":
        for k in ("pointId", "observationIds", "altitudeObservationIds"):
            if k in u:
                keep[k] = u.get(k)
    else:
        for k in ("altitudeUpdateId", "altitudeObservationIds"):
            if k in u:
                keep[k] = u.get(k)
    keep["evidence"] = _bound_evidence_list(u.get("evidence"), strip_raw_ref=True)
    keep["transportConstrained"] = True
    return keep


def _bound_update_list(updates: Any) -> list[Any]:
    if not isinstance(updates, list):
        return []
    out: list[Any] = []
    for u in updates:
        if not isinstance(u, dict):
            out.append(u)
            continue
        u2 = dict(u)
        if "evidence" in u2:
            u2["evidence"] = _bound_evidence_list(u2.get("evidence"))
        out.append(u2)
    return out


def slim_result_body_for_transport(body: dict[str, Any]) -> dict[str, Any]:
    """Keep current track XYZ/time/status; drop committedHistory; bound large evidence blobs."""
    if not isinstance(body, dict):
        return {}
    out = {
        k: v
        for k, v in body.items()
        if k
        not in (
            "tracks",
            "trajectoryUpdates",
            "altitudeUpdates",
        )
    }
    tracks_in = body.get("tracks") if isinstance(body.get("tracks"), list) else []
    slim_tracks: list[dict[str, Any]] = []
    # Always retain current XYZ/time keys for UI snapshot (even when null).
    _always = (
        "fusionId",
        "trackSegmentId",
        "aircraftId",
        "longitude",
        "latitude",
        "altitude",
        "altitudeDatum",
        "altitudeMode",
        "stateTime",
        "lastObservedAt",
        "displayStateTime",
        "trackStatus",
        "positionMode",
        "sourceTracks",
    )
    for t in tracks_in:
        if not isinstance(t, dict):
            continue
        row = {k: t.get(k) for k in _TRACK_CURRENT_KEEP if k in t or k in _always}
        slim_tracks.append(row)
    out["tracks"] = slim_tracks
    # Bound evidence on updates so a single huge rawRef cannot bypass byte budgets.
    out["trajectoryUpdates"] = _bound_update_list(body.get("trajectoryUpdates"))
    out["altitudeUpdates"] = _bound_update_list(body.get("altitudeUpdates"))
    return out


def project_result_event_shard(
    ev: dict[str, Any],
    *,
    shard_offset: int = 0,
    max_bytes: int = _EVENT_SINGLE_MAX_BYTES,
) -> tuple[dict[str, Any], bool, int]:
    """Return (transport_event, shard_complete, next_shard_offset).

    Preserves trajectoryUpdates / altitudeUpdates / rejected / evidence across shards.
    Never replaces a retained result with a body-less oversized stub.
    Single oversized evidence is bounded to an explicit truncated reference.
    """
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    body_in = payload.get("body") if isinstance(payload.get("body"), dict) else None
    if ev.get("kind") != "result" or body_in is None:
        out = {k: v for k, v in ev.items() if k != "_bytes"}
        return out, True, 0

    slim = slim_result_body_for_transport(body_in)
    traj = list(slim.get("trajectoryUpdates") or [])
    alts = list(slim.get("altitudeUpdates") or [])
    rejected = list(slim.get("rejected") or [])
    events = list(slim.get("events") or [])
    total_updates = len(traj) + len(alts)

    full_payload = {**payload, "body": slim, "oversized": False}
    full_ev = {k: v for k, v in ev.items() if k != "_bytes"}
    full_ev["payload"] = full_payload
    if _utf8_json_bytes(full_ev) <= max_bytes and int(shard_offset or 0) <= 0:
        return full_ev, True, 0

    off = max(0, int(shard_offset or 0))
    chunk = max(1, _SHARD_TRAJ_CHUNK)

    def _pack(start: int, n: int, *, force_bound: bool = False) -> tuple[dict[str, Any], int, bool]:
        end = min(total_updates, start + n)
        traj_slice: list[Any] = []
        alt_slice: list[Any] = []
        for i in range(start, end):
            if i < len(traj):
                item = traj[i]
                if force_bound and isinstance(item, dict):
                    item = dict(item)
                    item["evidence"] = _bound_evidence_list(item.get("evidence"))
                traj_slice.append(item)
            else:
                item = alts[i - len(traj)]
                if force_bound and isinstance(item, dict):
                    item = dict(item)
                    item["evidence"] = _bound_evidence_list(item.get("evidence"))
                alt_slice.append(item)
        shard_body = {
            k: v
            for k, v in slim.items()
            if k not in ("trajectoryUpdates", "altitudeUpdates", "rejected", "events", "tracks")
        }
        shard_body["tracks"] = slim.get("tracks") if start == 0 else []
        shard_body["trajectoryUpdates"] = traj_slice
        shard_body["altitudeUpdates"] = alt_slice
        shard_body["rejected"] = rejected if start == 0 else []
        shard_body["events"] = events if start == 0 else []
        complete = end >= total_updates
        next_off = 0 if complete else end
        shard_payload = {
            **{k: v for k, v in payload.items() if k != "body"},
            "body": shard_body,
            "oversized": False,
            "shard": {
                "offset": start,
                "nextOffset": next_off,
                "complete": complete,
                "trajTotal": len(traj),
                "altTotal": len(alts),
            },
        }
        out_ev = {k: v for k, v in ev.items() if k != "_bytes"}
        out_ev["payload"] = shard_payload
        return out_ev, next_off, complete

    # Shrink chunk until under budget (down to 1 update) — never drop the update.
    n = chunk
    while n >= 1:
        out_ev, next_off, complete = _pack(off, n)
        if _utf8_json_bytes(out_ev) <= max_bytes:
            return out_ev, complete, next_off
        if n == 1:
            break
        n = max(1, n // 2)
    # One update still over budget: re-bound evidence (nested rawRef), keep essentials.
    out_ev, next_off, complete = _pack(off, 1, force_bound=True)
    if _utf8_json_bytes(out_ev) <= max_bytes:
        return out_ev, complete, next_off
    # Last resort: omit raw attachment bodies only — never delete source evidence /
    # pointId / altitudeUpdateId / observation relations / XYZ / time.
    body = out_ev.get("payload", {}).get("body") if isinstance(out_ev.get("payload"), dict) else None
    if isinstance(body, dict):
        for key, kind in (
            ("trajectoryUpdates", "trajectory"),
            ("altitudeUpdates", "altitude"),
        ):
            lst = body.get(key)
            if not isinstance(lst, list):
                continue
            for i, u in enumerate(lst):
                if isinstance(u, dict):
                    lst[i] = _constrain_update_for_transport(u, kind=kind)
        out_ev["payload"]["body"] = body
        out_ev["payload"]["transportConstrained"] = True
    if _utf8_json_bytes(out_ev) <= max_bytes:
        return out_ev, complete, next_off
    # Essentials themselves cannot fit: do not claim complete consumption.
    out_ev.setdefault("payload", {})
    if isinstance(out_ev["payload"], dict):
        out_ev["payload"]["transportError"] = "essential_fields_exceed_single_event_byte_budget"
        out_ev["payload"]["oversized"] = True
    return out_ev, False, off


def _sender():
    import importlib.util
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "task008_csv_mqtt_sender", root / "scripts" / "task008_csv_mqtt_sender.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _reason_ok(codes: Any) -> bool:
    """SUBACK / publish reason codes: 0–2 are success for MQTT 3.1.1 QoS grants."""
    if codes is None:
        return True
    if isinstance(codes, (int, float)):
        return int(codes) <= 2
    try:
        seq = list(codes)
    except TypeError:
        val = getattr(codes, "value", codes)
        try:
            return int(val) <= 2
        except (TypeError, ValueError):
            return False
    if not seq:
        return False
    for c in seq:
        v = getattr(c, "value", c)
        try:
            if int(v) > 2:
                return False
        except (TypeError, ValueError):
            return False
    return True


@dataclass
class StreamJob:
    run_id: str
    session_id: str
    csv_path: str
    fusion_profile: str = "multisensor-3d-v1"
    altitude_mapping: str = "database_altitude_msl_v1"
    sn_mapping: str = "company_source_id_sn_v1"
    source_timezone: str = "Asia/Shanghai"
    max_observations: int = 0  # 0 = all
    tenant_id: str = field(default_factory=lambda: os.getenv("TASK008_TENANT_ID", "tenant-demo"))
    site_id: str = field(default_factory=lambda: os.getenv("TASK008_SITE_ID", "site-demo"))
    topic_prefix: str = field(default_factory=lambda: os.getenv("TASK008_TOPIC_PREFIX", "fusion/v1"))
    status: str = "created"  # created|running|stopping|stopped|completed|failed
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    # progress
    total_planned: int = 0
    published_obs: int = 0
    published_batches: int = 0
    ack_stored: int = 0
    ack_processed: int = 0
    ack_rejected: int = 0
    ack_conflict: int = 0
    ack_capacity: int = 0
    results_received: int = 0
    tick_results: int = 0
    trajectory_points: int = 0
    altitude_points: int = 0
    original_t0: Optional[str] = None
    original_t_last: Optional[str] = None
    sim_t0: Optional[str] = None
    current_original_time: Optional[str] = None
    current_sim_time: Optional[str] = None
    offset_seconds: float = 0.0
    mqtt_connected: bool = False
    result_subscribed: bool = False
    stop_requested: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    _events_bytes: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _client: Any = field(default=None, repr=False)
    _seen_result_ids: set[str] = field(default_factory=set, repr=False)
    _seen_ack_ids: set[str] = field(default_factory=set, repr=False)
    _point_ids: set[str] = field(default_factory=set, repr=False)
    _altitude_ids: set[str] = field(default_factory=set, repr=False)
    _event_seq: int = field(default=0, repr=False)
    _oldest_seq: int = field(default=0, repr=False)
    _pending_data_mids: set[str] = field(default_factory=set, repr=False)
    # Data mids that got a successful processed ack but whose result is not yet consumed.
    _awaiting_result_mids: set[str] = field(default_factory=set, repr=False)
    _start_acked: bool = field(default=False, repr=False)
    _start_failed: bool = field(default=False, repr=False)
    _start_mid: Optional[str] = field(default=None, repr=False)
    _end_mid: Optional[str] = field(default=None, repr=False)
    _run_end_drained: bool = field(default=False, repr=False)
    _end_control_failed: bool = field(default=False, repr=False)
    _publish_epoch: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)
    # Slim durable per-observation destinations (not trimmed with event pages).
    _obs_ledger: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _batch_obs: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            oldest, latest = self._cursor_unlocked()
            return {
                "runId": self.run_id,
                "sessionId": self.session_id,
                "status": self.status,
                "error": self.error,
                "csvPath": self.csv_path,
                "fusionProfile": self.fusion_profile,
                "altitudeMapping": self.altitude_mapping,
                "snMapping": self.sn_mapping,
                "sourceTimezone": self.source_timezone,
                "createdAt": self.created_at,
                "mqttConnected": self.mqtt_connected,
                "resultSubscribed": self.result_subscribed,
                "totalPlannedObservations": self.total_planned,
                "publishedObservations": self.published_obs,
                "publishedBatches": self.published_batches,
                "ackStored": self.ack_stored,
                "ackProcessed": self.ack_processed,
                "ackRejected": self.ack_rejected,
                "ackConflict": self.ack_conflict,
                "ackCapacity": self.ack_capacity,
                "resultsReceived": self.results_received,
                "tickResults": self.tick_results,
                "trajectoryPointIds": self.trajectory_points,
                "altitudePointIds": self.altitude_points,
                "pendingDataMessages": len(self._pending_data_mids),
                "awaitingResultMessages": len(self._awaiting_result_mids),
                "runEndDrained": self._run_end_drained,
                "oldestEventSeq": oldest,
                "latestEventSeq": latest,
                "originalT0": self.original_t0,
                "originalTLast": self.original_t_last,
                "simT0": self.sim_t0,
                "currentOriginalTime": self.current_original_time,
                "currentSimTime": self.current_sim_time,
                "offsetSeconds": self.offset_seconds,
                "eventCount": len(self.events),
                "ledgerPublished": len(self._obs_ledger),
                "ledgerWithResult": sum(
                    1 for r in self._obs_ledger.values() if r.get("results")
                ),
                "ledgerWithReject": sum(
                    1 for r in self._obs_ledger.values() if r.get("rejects")
                ),
                "ledgerMissingDestination": sum(
                    1
                    for r in self._obs_ledger.values()
                    if not r.get("results") and not r.get("rejects") and not r.get("processedEmpty")
                ),
                "modeLabel": "实时MQTT推流（1×）· 联调候选开发版",
                "note": "按数据库altitude作海拔米约定；设备基准未核实。RID/频谱id=SN，雷达id=局部目标ID。",
            }

    def slim_ledger(self) -> dict[str, Any]:
        """Full slim per-ID account (IDs/status/result/point/altitude); not event-buffer dependent."""
        with self._lock:
            rows = list(self._obs_ledger.values())
        missing = [
            r["observationId"]
            for r in rows
            if not r.get("results") and not r.get("rejects") and not r.get("processedEmpty")
        ]
        return {
            "runId": self.run_id,
            "publishedObs": len(rows),
            "withResult": sum(1 for r in rows if r.get("results")),
            "withReject": sum(1 for r in rows if r.get("rejects")),
            "processedEmpty": sum(1 for r in rows if r.get("processedEmpty")),
            "missingDestination": missing,
            "complete": len(rows) > 0 and len(missing) == 0,
            "rows": rows,
        }

    def _ledger_note_published(self, mid: str, observations: list[dict[str, Any]]) -> None:
        ids: list[str] = []
        with self._lock:
            for o in observations:
                oid = str((o or {}).get("observationId") or "")
                if not oid:
                    continue
                ids.append(oid)
                row = self._obs_ledger.get(oid) or {
                    "observationId": oid,
                    "published": False,
                    "results": [],
                    "rejects": [],
                }
                row["published"] = True
                row["publishMessageId"] = mid
                row["batchId"] = mid
                row["source"] = (o or {}).get("source")
                row["measurementTime"] = (o or {}).get("measurementTime")
                self._obs_ledger[oid] = row
            self._batch_obs[mid] = ids

    def _ledger_note_result(
        self,
        *,
        message_id: str,
        ref: str,
        batch_id: str,
        tick: bool,
        body: dict[str, Any],
    ) -> None:
        rejected = body.get("rejected") if isinstance(body.get("rejected"), list) else []
        traj = body.get("trajectoryUpdates") if isinstance(body.get("trajectoryUpdates"), list) else []
        alts = body.get("altitudeUpdates") if isinstance(body.get("altitudeUpdates"), list) else []

        def _ensure(oid: str) -> dict[str, Any]:
            row = self._obs_ledger.get(oid) or {
                "observationId": oid,
                "published": False,
                "results": [],
                "rejects": [],
            }
            self._obs_ledger[oid] = row
            return row

        with self._lock:
            for rj in rejected:
                if not isinstance(rj, dict):
                    continue
                oid = str(rj.get("observationId") or "")
                if not oid:
                    continue
                row = _ensure(oid)
                row.setdefault("rejects", []).append(
                    {
                        "reason": rj.get("reason") or rj.get("code") or "reject",
                        "messageId": message_id,
                        "batchId": batch_id,
                        "tick": tick,
                    }
                )
            for p in traj:
                if not isinstance(p, dict):
                    continue
                oids = list(p.get("observationIds") or [])
                for ev in p.get("evidence") or []:
                    if isinstance(ev, dict) and ev.get("observationId"):
                        oids.append(str(ev["observationId"]))
                for oid in {str(x) for x in oids if x}:
                    row = _ensure(oid)
                    row.pop("processedEmpty", None)
                    row.pop("processedEmptyRef", None)
                    row.setdefault("results", []).append(
                        {
                            "kind": "trajectory",
                            "pointId": p.get("pointId"),
                            "fusionId": p.get("fusionId"),
                            "altitude": p.get("altitude"),
                            "messageId": message_id,
                            "batchId": batch_id,
                            "tick": tick,
                        }
                    )
            for p in alts:
                if not isinstance(p, dict):
                    continue
                oids = list(p.get("altitudeObservationIds") or []) + list(p.get("observationIds") or [])
                for ev in p.get("evidence") or []:
                    if isinstance(ev, dict) and ev.get("observationId"):
                        oids.append(str(ev["observationId"]))
                for oid in {str(x) for x in oids if x}:
                    row = _ensure(oid)
                    row.pop("processedEmpty", None)
                    row.pop("processedEmptyRef", None)
                    row.setdefault("results", []).append(
                        {
                            "kind": "altitude",
                            "pointId": p.get("pointId") or p.get("altitudeUpdateId"),
                            "fusionId": p.get("fusionId"),
                            "altitude": p.get("altitude"),
                            "messageId": message_id,
                            "batchId": batch_id,
                            "tick": tick,
                        }
                    )
            # Batch processed: any remaining published obs in this batch without a
            # traj/alt/reject link still get an explicit destination (empty/bound).
            batch_keys = []
            if ref:
                batch_keys.append(ref)
            if batch_id:
                batch_keys.append(batch_id)
            linked = set()
            for oid_list in (self._batch_obs.get(k) for k in batch_keys):
                if not oid_list:
                    continue
                for oid in oid_list:
                    row = self._obs_ledger.get(oid)
                    if row and (row.get("results") or row.get("rejects")):
                        linked.add(oid)
            for k in batch_keys:
                for oid in self._batch_obs.get(k, []):
                    row = _ensure(oid)
                    if row.get("results") or row.get("rejects") or row.get("processedEmpty"):
                        continue
                    # Prefer evidence from tracks when trajectoryUpdates omitted.
                    track_hit = False
                    for tr in body.get("tracks") or []:
                        if not isinstance(tr, dict):
                            continue
                        for h in tr.get("committedHistory") or []:
                            if not isinstance(h, dict):
                                continue
                            evid = h.get("evidence") or []
                            oids = list(h.get("observationIds") or []) + [
                                str(ev.get("observationId"))
                                for ev in evid
                                if isinstance(ev, dict) and ev.get("observationId")
                            ]
                            if oid in oids:
                                row.setdefault("results", []).append(
                                    {
                                        "kind": "track_history",
                                        "pointId": h.get("pointId"),
                                        "fusionId": tr.get("fusionId"),
                                        "altitude": h.get("altitude"),
                                        "messageId": message_id,
                                        "batchId": batch_id,
                                        "tick": tick,
                                    }
                                )
                                track_hit = True
                                break
                        if track_hit:
                            break
                    if track_hit:
                        continue
                    row["processedEmpty"] = True
                    row["processedEmptyRef"] = {
                        "messageId": message_id,
                        "batchId": batch_id,
                        "tick": tick,
                        "refMessageId": ref,
                    }

    def _cursor_unlocked(self) -> tuple[int, int]:
        if self.events:
            return int(self.events[0]["seq"]), int(self.events[-1]["seq"])
        return int(self._oldest_seq or 0), int(self._event_seq or 0)

    def append_event(self, kind: str, payload: dict[str, Any]) -> None:
        # Slim large result bodies before enqueue so cache/MQTT callback stay bounded.
        store_payload = payload
        if kind == "result" and isinstance(payload, dict):
            body = payload.get("body")
            if isinstance(body, dict):
                store_payload = {
                    **payload,
                    "body": slim_result_body_for_transport(body),
                }
        # Size once at enqueue (UTF-8); trim uses cached _bytes — no full-buffer reserialize.
        nbytes = self._event_payload_bytes({"payload": store_payload})
        with self._lock:
            self._event_seq += 1
            seq = self._event_seq
            self.events.append(
                {
                    "seq": seq,
                    "kind": kind,
                    "at": utc_now_iso(),
                    "runId": self.run_id,
                    "sessionId": self.session_id,
                    "payload": store_payload,
                    "_bytes": int(nbytes),
                }
            )
            self._events_bytes += int(nbytes)
            if self._oldest_seq <= 0:
                self._oldest_seq = seq
            self._trim_event_buffer_unlocked()

    def _event_payload_bytes(self, ev: dict[str, Any]) -> int:
        """UTF-8 payload size. Prefer cached `_bytes` on retained events."""
        cached = ev.get("_bytes")
        if isinstance(cached, int) and cached >= 0:
            return cached
        return _utf8_json_bytes(ev.get("payload"))

    def _trim_event_buffer_unlocked(self) -> None:
        """Trim by count and cached UTF-8 bytes; O(dropped), no full reserialize."""
        if len(self.events) > _EVENT_BUFFER_SOFT:
            dropped = self.events[: -_EVENT_BUFFER_KEEP]
            self.events = self.events[-_EVENT_BUFFER_KEEP:]
            for d in dropped:
                self._events_bytes -= int(d.get("_bytes") or 0)
            self._oldest_seq = int(self.events[0]["seq"]) if self.events else self._oldest_seq
        if self._events_bytes < 0:
            self._events_bytes = sum(int(e.get("_bytes") or 0) for e in self.events)
        while self._events_bytes > _EVENT_BUFFER_SOFT_BYTES and len(self.events) > 1:
            drop = self.events.pop(0)
            self._events_bytes -= int(drop.get("_bytes") or 0)
            if self._events_bytes <= _EVENT_BUFFER_KEEP_BYTES:
                break
        if self.events:
            self._oldest_seq = int(self.events[0]["seq"])
        else:
            self._events_bytes = 0

    def events_since(self, after_seq: int) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self.events if int(e["seq"]) > int(after_seq)]

    def events_page(self, after_seq: int = 0) -> dict[str, Any]:
        """Incremental page with cursor + explicit gap when afterSeq is stale."""
        with self._lock:
            after = int(after_seq or 0)
            oldest, latest = self._cursor_unlocked()
            gap = False
            recovery = None
            # afterSeq=0 also gaps when the retained buffer no longer starts at 1
            # (refresh must not treat a trimmed tail as a complete prefix).
            if oldest > 1 and after < (oldest - 1):
                gap = True
                recovery = "cursor_expired_reattach_active_or_restart"
            events = [e for e in self.events if int(e["seq"]) > after]
            return {
                "events": events,
                "oldestSeq": oldest,
                "latestSeq": latest,
                "gap": gap,
                "gapRecovery": recovery,
                "completePrefix": (not gap) and (oldest <= 1 or after >= (oldest - 1)),
            }

    def bound_seen_sets(self) -> None:
        """Cap ephemeral dedupe sets; durable business ledgers stay in bridge store."""
        with self._lock:
            for attr in ("_seen_result_ids", "_seen_ack_ids", "_point_ids", "_altitude_ids"):
                s = getattr(self, attr)
                if len(s) > _MAX_SEEN_IDS:
                    # Drop arbitrary excess; IDs already counted in counters.
                    overflow = len(s) - (_MAX_SEEN_IDS // 2)
                    for i, x in enumerate(list(s)):
                        if i >= overflow:
                            break
                        s.discard(x)


class StreamJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, StreamJob] = {}
        self._lock = threading.Lock()
        self._active_run: Optional[str] = None

    def get(self, run_id: str) -> Optional[StreamJob]:
        with self._lock:
            return self._jobs.get(run_id)

    def active(self) -> Optional[StreamJob]:
        with self._lock:
            if self._active_run and self._active_run in self._jobs:
                job = self._jobs[self._active_run]
                if job.status in ("created", "running", "stopping"):
                    return job
            return None

    def recent(self, limit: int = 8) -> list[StreamJob]:
        """Newest retained jobs including terminal ones (for reopen / light control)."""
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[: max(1, min(int(limit or 8), _MAX_RETAINED_JOBS))]

    def _release_active(self, job: StreamJob) -> None:
        with self._lock:
            if self._active_run == job.run_id:
                self._active_run = None

    def _prune_jobs_unlocked(self) -> None:
        if len(self._jobs) <= _MAX_RETAINED_JOBS:
            return
        # Drop oldest terminal jobs first; never drop the active pointer.
        terminal = [
            j
            for j in self._jobs.values()
            if j.status in ("completed", "stopped", "failed") and j.run_id != self._active_run
        ]
        terminal.sort(key=lambda j: j.created_at)
        while len(self._jobs) > _MAX_RETAINED_JOBS and terminal:
            old = terminal.pop(0)
            self._jobs.pop(old.run_id, None)

    def start(
        self,
        *,
        csv_path: Path,
        fusion_profile: str,
        altitude_mapping: str,
        sn_mapping: str,
        source_timezone: str,
        max_observations: int = 0,
        session_id: Optional[str] = None,
    ) -> StreamJob:
        if mqtt is None:
            raise RuntimeError("paho-mqtt_required")
        path = Path(csv_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        with self._lock:
            if self._active_run:
                cur = self._jobs.get(self._active_run)
                if cur and cur.status in ("running", "stopping", "created"):
                    raise RuntimeError("job_already_active")
            self._prune_jobs_unlocked()
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            sid = session_id or f"mqtt-stream-{run_id}"
            job = StreamJob(
                run_id=run_id,
                session_id=sid,
                csv_path=str(path.resolve()),
                fusion_profile=fusion_profile or "multisensor-3d-v1",
                altitude_mapping=altitude_mapping or "database_altitude_msl_v1",
                sn_mapping=sn_mapping or "company_source_id_sn_v1",
                source_timezone=source_timezone or "Asia/Shanghai",
                max_observations=int(max_observations or 0),
            )
            self._jobs[run_id] = job
            self._active_run = run_id
        job._thread = threading.Thread(target=self._run_job, args=(job,), name=f"mqtt-stream-{run_id}", daemon=True)
        job._thread.start()
        return job

    def stop(self, run_id: str) -> StreamJob:
        job = self.get(run_id)
        if not job:
            raise KeyError(run_id)
        with job._lock:
            if job.status in ("completed", "stopped", "failed"):
                return job
            job.stop_requested = True
            job.status = "stopping"
        job.append_event("status", {"status": "stopping"})
        return job

    def restart(self, run_id: str) -> StreamJob:
        old = self.get(run_id)
        if not old:
            raise KeyError(run_id)
        self.stop(run_id)
        if old._thread and old._thread.is_alive():
            old._thread.join(timeout=15.0)
        return self.start(
            csv_path=Path(old.csv_path),
            fusion_profile=old.fusion_profile,
            altitude_mapping=old.altitude_mapping,
            sn_mapping=old.sn_mapping,
            source_timezone=old.source_timezone,
            max_observations=old.max_observations,
            session_id=None,
        )

    def _fail_job(self, job: StreamJob, error: str) -> None:
        with job._lock:
            job.status = "failed"
            job.error = error
        job.append_event("error", {"error": error})
        self._release_active(job)

    def _finish_job(self, job: StreamJob, status: str, *, note: Optional[str] = None) -> None:
        with job._lock:
            job.status = status
            if note:
                job.error = note
        job.append_event("status", {"status": status, "published": job.published_obs, "note": note})
        self._release_active(job)

    def _publish_checked(self, client: Any, topic: str, payload: str) -> Any:
        info = client.publish(topic, payload, qos=1)
        rc = getattr(info, "rc", 0)
        if rc not in (0, None):
            raise RuntimeError(f"mqtt_publish_rc_{rc}")
        wait = getattr(info, "wait_for_publish", None)
        if callable(wait):
            wait(timeout=10.0)
        is_pub = getattr(info, "is_published", None)
        if callable(is_pub) and not is_pub():
            raise RuntimeError("mqtt_publish_not_acked")
        return info

    def _run_job(self, job: StreamJob) -> None:
        client = None
        try:
            self._run_job_body(job)
        except Exception as exc:  # noqa: BLE001
            self._fail_job(job, str(exc))
        finally:
            if client is None:
                client = job._client
            if client is not None:
                try:
                    client.loop_stop()
                    client.disconnect()
                except Exception:
                    pass
            with job._lock:
                job.mqtt_connected = False
            # Ensure slot freed even if status left non-terminal by unexpected exit.
            if job.status in ("completed", "stopped", "failed"):
                self._release_active(job)
            elif job.status in ("created", "running", "stopping"):
                self._fail_job(job, job.error or "job_exited_without_terminal_status")

    def _run_job_body(self, job: StreamJob) -> None:
        sender = _sender()
        broker = os.getenv("TASK008_MQTT_HOST", "127.0.0.1")
        port = int(os.getenv("TASK008_MQTT_PORT", "1883"))
        user = os.getenv("TASK008_MQTT_USER", "fusion_local")
        password = os.getenv("TASK008_MQTT_PASSWORD", "fusion_local_dev_only")
        topic_in = f"{job.topic_prefix.rstrip('/')}/{job.tenant_id}/{job.site_id}/input"
        topic_ctl = f"{job.topic_prefix.rstrip('/')}/{job.tenant_id}/{job.site_id}/control"
        topic_result = f"{job.topic_prefix.rstrip('/')}/{job.tenant_id}/{job.site_id}/result"
        topic_ack = f"{job.topic_prefix.rstrip('/')}/{job.tenant_id}/{job.site_id}/ack"

        try:
            rows = sender.load_timed_rows(Path(job.csv_path), source_timezone=job.source_timezone)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"load_timed_rows_failed:{exc}") from exc

        file_tag = Path(job.csv_path).stem
        planned: list[tuple[datetime, dict[str, Any], int]] = list(rows)
        if not planned:
            raise RuntimeError("no_timed_rows")

        t0_file = planned[0][0]
        t_last = planned[-1][0]
        t0_wall = datetime.now(timezone.utc)
        offset = t0_wall - t0_file
        with job._lock:
            job.original_t0 = t0_file.isoformat()
            job.original_t_last = t_last.isoformat()
            job.sim_t0 = t0_wall.isoformat()
            job.offset_seconds = offset.total_seconds()
            job.status = "running"

        if mqtt is None:
            raise RuntimeError("paho-mqtt_required")

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"task008-ui-stream-{job.run_id}",
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(user, password)
        job._client = client

        def on_connect(c, _u, _f, rc, _p=None):
            ok = rc == 0 if isinstance(rc, int) else getattr(rc, "value", 1) == 0
            with job._lock:
                job.mqtt_connected = bool(ok)
            if not ok:
                job.append_event("mqtt", {"connected": False, "rc": str(rc)})
                return
            c.subscribe([(topic_result, 1), (topic_ack, 1)])
            job.append_event("mqtt", {"connected": True, "subscribe_sent": [topic_result, topic_ack]})

        def on_disconnect(_c, _u, rc, _p=None, *_a):
            with job._lock:
                job.mqtt_connected = False
            job.append_event("mqtt", {"connected": False, "disconnect_rc": str(rc)})

        def on_subscribe(_c, _u, mid, reason_codes, _properties=None):
            if not _reason_ok(reason_codes):
                job.append_event("mqtt", {"suback": False, "mid": mid, "reasonCodes": str(reason_codes)})
                return
            with job._lock:
                job.result_subscribed = True
            job.append_event("mqtt", {"suback": True, "mid": mid, "subscribed": [topic_result, topic_ack]})

        def _ingest_ack(mid: str, payload: dict[str, Any]) -> None:
            st = str(payload.get("status") or "")
            ref = str(payload.get("refMessageId") or "")
            with job._lock:
                if mid and mid in job._seen_ack_ids:
                    return
                if mid:
                    job._seen_ack_ids.add(mid)
                if st == "stored":
                    job.ack_stored += 1
                elif st == "processed":
                    job.ack_processed += 1
                elif st == "conflict":
                    job.ack_conflict += 1
                    job.ack_rejected += 1
                elif st == "capacity" or st == "idempotency_capacity":
                    job.ack_capacity += 1
                    job.ack_rejected += 1
                elif st in ("error", "rejected", "transient_error"):
                    job.ack_rejected += 1

                if ref and job._start_mid and ref == job._start_mid:
                    if st in ("stored", "processed"):
                        job._start_acked = True
                    elif st in ("error", "rejected", "conflict", "capacity", "transient_error"):
                        job._start_failed = True

                if ref and job._end_mid and ref == job._end_mid:
                    if st == "drained":
                        job._run_end_drained = True
                    elif st in ("error", "rejected", "conflict", "capacity", "transient_error"):
                        job._end_control_failed = True

                if ref and ref in job._pending_data_mids:
                    # Terminal application outcomes leave the send ledger.
                    if st in (
                        "processed",
                        "rejected",
                        "conflict",
                        "capacity",
                        "error",
                        "transient_error",
                        "idempotency_capacity",
                    ):
                        job._pending_data_mids.discard(ref)
                        # Successful process still requires a consumed result (or empty tracks body).
                        if st == "processed":
                            job._awaiting_result_mids.add(ref)
                # Explicit rejects on awaiting clear the result wait without a body.
                if ref and ref in job._awaiting_result_mids and st in (
                    "rejected",
                    "conflict",
                    "capacity",
                    "error",
                    "transient_error",
                    "idempotency_capacity",
                ):
                    job._awaiting_result_mids.discard(ref)
            job.append_event("ack", {"messageId": mid, "refMessageId": ref, "status": st, "payload": payload})

        def _count_result_ids(body: dict[str, Any]) -> None:
            for item in body.get("trajectoryUpdates") or []:
                if not isinstance(item, dict):
                    continue
                hist = item.get("committedHistory")
                pts = hist if isinstance(hist, list) and hist else [item]
                for p in pts:
                    if not isinstance(p, dict):
                        continue
                    pid = str(p.get("pointId") or "")
                    if not pid:
                        continue
                    with job._lock:
                        if pid not in job._point_ids:
                            job._point_ids.add(pid)
                            job.trajectory_points = len(job._point_ids)
            for au in body.get("altitudeUpdates") or []:
                if not isinstance(au, dict):
                    continue
                aid = str(au.get("altitudeUpdateId") or au.get("pointId") or "")
                if not aid:
                    continue
                with job._lock:
                    if aid not in job._altitude_ids:
                        job._altitude_ids.add(aid)
                        job.altitude_points = len(job._altitude_ids)

        def on_message(_c, _u, msg):
            try:
                env = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                return
            if env.get("sessionId") != job.session_id:
                return
            if env.get("tenantId") not in (None, job.tenant_id):
                return
            if env.get("siteId") not in (None, job.site_id):
                return
            mid = str(env.get("messageId") or "")
            kind = str(env.get("messageType") or "")
            payload = env.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            if kind == "ack":
                _ingest_ack(mid, payload)
                return
            if kind != "result":
                return
            with job._lock:
                if mid and mid in job._seen_result_ids:
                    return
                if mid:
                    job._seen_result_ids.add(mid)
                job.results_received += 1
            body = payload.get("body") if isinstance(payload.get("body"), dict) else payload
            if not isinstance(body, dict):
                body = {}
            batch_id = str(body.get("batchId") or payload.get("batchId") or "")
            is_tick = batch_id.startswith("ctrl-tick") or bool(payload.get("idle"))
            if is_tick:
                with job._lock:
                    job.tick_results += 1
            # Correlated data ref clears pending when result replies to a published batch.
            ref = str(payload.get("refMessageId") or body.get("refMessageId") or "")
            if ref:
                with job._lock:
                    job._pending_data_mids.discard(ref)
                    job._awaiting_result_mids.discard(ref)
            _count_result_ids(body)
            job._ledger_note_result(
                message_id=mid,
                ref=ref,
                batch_id=batch_id,
                tick=is_tick,
                body=body,
            )
            # Preserve rejected/events in the event log (do not drop).
            job.append_event(
                "result",
                {
                    "messageId": mid,
                    "refMessageId": ref,
                    "batchId": batch_id,
                    "tick": is_tick,
                    "events": body.get("events") if isinstance(body.get("events"), list) else [],
                    "rejected": body.get("rejected") if isinstance(body.get("rejected"), list) else [],
                    "body": body,
                },
            )

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_message = on_message

        client.connect(broker, port, keepalive=30)
        client.loop_start()

        # Wait for real SUBACK (not subscribe() return alone).
        sub_deadline = time.time() + _SUBSCRIBE_WAIT_S
        while time.time() < sub_deadline and not job.stop_requested:
            if job.result_subscribed:
                break
            time.sleep(0.05)
        if not job.result_subscribed:
            raise RuntimeError("result_subscribe_timeout_no_suback")

        start_mid = f"{job.run_id}-ctl-start"
        with job._lock:
            job._start_mid = start_mid
        start_msg = {
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "control",
            "messageId": start_mid,
            "tenantId": job.tenant_id,
            "siteId": job.site_id,
            "sessionId": job.session_id,
            "sentAt": utc_now_iso(),
            "payload": {
                "action": "run.start",
                "writeOwner": "mqtt",
                "handover": True,
                "fusionProfile": job.fusion_profile,
                "runId": job.run_id,
                "epoch": job._publish_epoch,
            },
        }
        self._publish_checked(client, topic_ctl, json.dumps(start_msg, ensure_ascii=False))
        job.append_event("control", {"action": "run.start", "messageId": start_mid})

        start_deadline = time.time() + _START_ACK_WAIT_S
        while time.time() < start_deadline and not job.stop_requested:
            with job._lock:
                if job._start_acked:
                    break
                if job._start_failed:
                    raise RuntimeError("run_start_ack_failed")
            time.sleep(0.05)
        with job._lock:
            start_ok = job._start_acked
        if not start_ok:
            raise RuntimeError("run_start_ack_timeout")

        batch: list[dict[str, Any]] = []
        batch_idx = 0
        batch_max_span_s = 1.5
        batch_open_mt: Optional[datetime] = None
        batch_open_wall: Optional[datetime] = None

        def flush_batch() -> None:
            nonlocal batch_idx, batch, batch_open_mt, batch_open_wall
            if not batch:
                return
            # Bounded in-flight: wait for pending/awaiting capacity; stop still interrupts.
            while not job.stop_requested:
                with job._lock:
                    pending_n = len(job._pending_data_mids)
                    awaiting_n = len(job._awaiting_result_mids)
                if pending_n < _BACKPRESSURE_PENDING and awaiting_n < _BACKPRESSURE_AWAITING:
                    break
                time.sleep(0.05)
            if job.stop_requested:
                return
            job.bound_seen_sets()
            batch_idx += 1
            mid = f"{job.run_id}-b{batch_idx:06d}"
            msg = {
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "observations",
                "messageId": mid,
                "tenantId": job.tenant_id,
                "siteId": job.site_id,
                "sessionId": job.session_id,
                "sentAt": utc_now_iso(),
                "payload": {
                    "batchId": mid,
                    "fusionProfile": job.fusion_profile,
                    "mode": "realtime",
                    "clockMode": "wallclock_rebase_1x_absolute",
                    "runId": job.run_id,
                    "epoch": job._publish_epoch,
                    "observations": batch,
                },
            }
            # Register pending before publish so in-callback acks can clear the ledger.
            with job._lock:
                job._pending_data_mids.add(mid)
            try:
                self._publish_checked(client, topic_in, json.dumps(msg, ensure_ascii=False))
            except Exception:
                with job._lock:
                    job._pending_data_mids.discard(mid)
                raise
            with job._lock:
                job.published_batches = batch_idx
                job.published_obs += len(batch)
            job._ledger_note_published(mid, list(batch))
            job.append_event(
                "published",
                {
                    "messageId": mid,
                    "n": len(batch),
                    "publishedObservations": job.published_obs,
                    # UI incremental raw layer (observationId-deduped on client).
                    "observations": list(batch),
                },
            )
            batch = []
            batch_open_mt = None
            batch_open_wall = None

        try:
            pre_obs = []
            for mt, row, line_no in planned:
                obs = sender.row_to_observation(
                    row,
                    line_no=line_no,
                    file_tag=file_tag,
                    time_offset=offset,
                    original_mt=mt,
                    altitude_mapping=job.altitude_mapping,
                    sn_mapping=job.sn_mapping,
                    run_id=job.run_id,
                )
                if obs is None:
                    continue
                pre_obs.append((mt, obs))
                if job.max_observations > 0 and len(pre_obs) >= job.max_observations:
                    break
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"row_to_observation_failed:{exc}") from exc

        with job._lock:
            job.total_planned = len(pre_obs)

        user_stop = False
        for mt, obs in pre_obs:
            if job.stop_requested:
                user_stop = True
                break
            deadline = t0_wall + (mt - t0_file)
            while True:
                if job.stop_requested:
                    user_stop = True
                    break
                now = datetime.now(timezone.utc)
                if (
                    batch
                    and batch_open_wall is not None
                    and (now - batch_open_wall).total_seconds() >= batch_max_span_s
                ):
                    flush_batch()
                    now = datetime.now(timezone.utc)
                remain = (deadline - now).total_seconds()
                if remain <= 0:
                    break
                sleep_for = remain
                if batch and batch_open_wall is not None:
                    batch_remain = batch_max_span_s - (now - batch_open_wall).total_seconds()
                    if batch_remain > 0:
                        sleep_for = min(sleep_for, batch_remain)
                time.sleep(min(max(sleep_for, 0.0), 1.0))
            if job.stop_requested:
                user_stop = True
                break
            sim_mt = mt + offset
            with job._lock:
                job.current_original_time = mt.isoformat()
                job.current_sim_time = sim_mt.isoformat()
            if batch_open_mt is None:
                batch_open_mt = mt
                batch_open_wall = datetime.now(timezone.utc)
            elif (mt - batch_open_mt).total_seconds() > batch_max_span_s:
                flush_batch()
                batch_open_mt = mt
                batch_open_wall = datetime.now(timezone.utc)
            batch.append(obs)
            if len(batch) >= 1:
                flush_batch()
        # Stop cancels unsent; do not flush leftover unsent batch after stop.
        if not job.stop_requested:
            flush_batch()
        else:
            user_stop = True
            batch = []
            batch_open_mt = None
            batch_open_wall = None

        end_mid = f"{job.run_id}-ctl-end"
        with job._lock:
            job._end_mid = end_mid
        end_msg = {
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "control",
            "messageId": end_mid,
            "tenantId": job.tenant_id,
            "siteId": job.site_id,
            "sessionId": job.session_id,
            "sentAt": utc_now_iso(),
            "payload": {
                "action": "run.end",
                "runId": job.run_id,
                "epoch": job._publish_epoch,
                "reason": "user_stop" if user_stop or job.stop_requested else "file_exhausted",
            },
        }
        self._publish_checked(client, topic_ctl, json.dumps(end_msg, ensure_ascii=False))
        job.append_event("control", {"action": "run.end", "messageId": end_mid})

        # Wait for drained + no pending sends + every processed mid has a consumed result.
        drain_deadline = time.time() + _DRAIN_WAIT_S
        drained_ok = False
        while time.time() < drain_deadline:
            with job._lock:
                if job._end_control_failed:
                    raise RuntimeError("run_end_ack_failed")
                pending = len(job._pending_data_mids)
                awaiting = len(job._awaiting_result_mids)
                drained = job._run_end_drained
            if drained and pending == 0 and awaiting == 0:
                drained_ok = True
                break
            # Zero publishes: drained alone is enough (nothing to await).
            if drained and job.published_obs == 0 and pending == 0 and awaiting == 0:
                drained_ok = True
                break
            time.sleep(0.05)

        if not drained_ok:
            with job._lock:
                pending = sorted(job._pending_data_mids)
                awaiting = sorted(job._awaiting_result_mids)
                drained = job._run_end_drained
            # Input halted ≠ core drained. Never mark normal stopped/completed without drained.
            if (user_stop or job.stop_requested) and not pending and not awaiting and not drained:
                self._fail_job(
                    job,
                    f"stop_input_halted_drain_unconfirmed drained={drained} "
                    f"results={job.results_received}",
                )
                return
            raise RuntimeError(
                f"application_drain_timeout drained={drained} pending={pending} "
                f"awaiting_result={awaiting} results={job.results_received} "
                f"rejected={job.ack_rejected}"
            )

        note = None
        if job.ack_rejected > 0:
            note = f"completed_with_{job.ack_rejected}_rejects"
        if user_stop or job.stop_requested:
            self._finish_job(job, "stopped", note=note)
        else:
            self._finish_job(job, "completed", note=note)


MANAGER = StreamJobManager()
