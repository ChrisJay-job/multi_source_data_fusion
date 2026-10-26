"""fusion-mqtt.v1 envelope and validation helpers.

Altitude mapping version for DB CSV rows: database_altitude_msl_v1
(DB column ``altitude`` treated as MSL metres; not height AGL / ellipsoid).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "fusion-mqtt.v1"
ALTITUDE_MAPPING_VERSION = "database_altitude_msl_v1"
SN_MAPPING_VERSION = "confirmed_sn_v1"  # legacy fixture path
COMPANY_SN_MAPPING_VERSION = "company_source_id_sn_v1"  # company DB default

MESSAGE_TYPES_INPUT = frozenset({"observations"})
MESSAGE_TYPES_CONTROL = frozenset({"control"})
CONTROL_ACTIONS = frozenset({"run.start", "run.end", "flush", "tick"})

SUPPORTED_DATUMS_MSL = frozenset({"MSL", "msl", "WGS84_MSL"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_fingerprint(
    payload: dict[str, Any],
    *,
    tenant_id: str = "",
    site_id: str = "",
    session_id: str = "",
) -> str:
    """Stable hash including tenant/site/session so cross-session reuse cannot silently dedupe."""
    body = {
        "tenantId": tenant_id,
        "siteId": site_id,
        "sessionId": session_id,
        "batchId": payload.get("batchId"),
        "fusionProfile": payload.get("fusionProfile"),
        "mode": payload.get("mode"),
        "observations": payload.get("observations") or [],
        "clockMode": payload.get("clockMode"),
        "action": payload.get("action"),
        "kind": payload.get("kind"),
        "writeOwner": payload.get("writeOwner"),
        "handover": payload.get("handover"),
        "handoverPending": payload.get("handoverPending"),
        "resume": payload.get("resume"),
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _require_str(d: dict, key: str, errors: list[str]) -> Optional[str]:
    v = d.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        errors.append(f"missing_{key}")
        return None
    if not isinstance(v, str):
        errors.append(f"invalid_{key}_type")
        return None
    return v


def validate_envelope(msg: dict[str, Any], *, expect_types: frozenset[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(msg, dict):
        return ["not_an_object"]
    if msg.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    mt = msg.get("messageType")
    if mt not in expect_types:
        errors.append("unsupported_message_type")
    for key in ("messageId", "tenantId", "siteId", "sessionId", "sentAt"):
        _require_str(msg, key, errors)
    if "payload" not in msg or not isinstance(msg.get("payload"), dict):
        errors.append("missing_payload")
    return errors


def validate_observations_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require_str(payload, "batchId", errors)
    mode = payload.get("mode") or "realtime"
    if mode != "realtime":
        errors.append("mqtt_adapter_realtime_only")
    profile = payload.get("fusionProfile")
    if profile is not None and not isinstance(profile, str):
        errors.append("invalid_fusion_profile")
    obs = payload.get("observations")
    if not isinstance(obs, list):
        errors.append("observations_not_list")
        return errors
    if len(obs) > 5000:
        errors.append("too_many_observations")
    for i, item in enumerate(obs):
        if not isinstance(item, dict):
            errors.append(f"obs[{i}]_not_object")
            continue
        for key in ("observationId", "source", "detectorId", "sourceTrackId", "measurementTime"):
            if not item.get(key):
                errors.append(f"obs[{i}]_missing_{key}")
        src = item.get("source")
        if src not in ("rid", "spectrum", "radar"):
            errors.append(f"obs[{i}]_unknown_source")
        # Pass through scanId / positionStdM; never strip.
        datum = item.get("altitudeDatum")
        if datum is not None and not isinstance(datum, str):
            errors.append(f"obs[{i}]_invalid_altitudeDatum")
    return errors


def validate_control_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    action = payload.get("action")
    if action not in CONTROL_ACTIONS:
        errors.append("unsupported_control_action")
    return errors


def build_ack(
    *,
    message_id: str,
    tenant_id: str,
    site_id: str,
    session_id: str,
    status: str,
    detail: Optional[dict[str, Any]] = None,
    reply_to: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "messageType": "ack",
        "messageId": f"ack-{message_id}-{status}",
        "tenantId": tenant_id,
        "siteId": site_id,
        "sessionId": session_id,
        "sentAt": utc_now_iso(),
        "payload": {
            "refMessageId": message_id,
            "status": status,
            "detail": detail or {},
            "replyTo": reply_to,
        },
    }


def build_result(
    *,
    message_id: str,
    tenant_id: str,
    site_id: str,
    session_id: str,
    process_response: dict[str, Any],
    evidence_index: Optional[dict[str, Any]] = None,
    reply_to: Optional[str] = None,
) -> dict[str, Any]:
    tracks = []
    for t in process_response.get("tracks") or []:
        # MQTT: light tracks without full committedHistory
        light = {k: v for k, v in t.items() if k != "committedHistory"}
        tracks.append(light)
    def _enrich(points: list[dict[str, Any]], id_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for pt in points:
            item = dict(pt)
            oids: list[str] = []
            for key in id_keys:
                for oid in item.get(key) or []:
                    if oid not in oids:
                        oids.append(oid)
            evidence = []
            if evidence_index:
                for oid in oids:
                    if oid in evidence_index:
                        ev = dict(evidence_index[oid])
                        roles: list[str] = []
                        if oid in (item.get("observationIds") or []):
                            roles.append("position_update")
                        if oid in (item.get("altitudeObservationIds") or []):
                            roles.append("altitude_update")
                        if len(roles) == 1:
                            ev = {**ev, "role": roles[0], "roles": roles}
                        elif len(roles) > 1:
                            # Dual-axis: keep both facts; do not overwrite one role with the other.
                            ev = {**ev, "roles": roles, "role": "position_and_altitude_update"}
                        evidence.append(ev)
            if evidence:
                item["evidence"] = evidence
            enriched.append(item)
        return enriched

    updates = process_response.get("trajectoryUpdates") or []
    alt_updates = process_response.get("altitudeUpdates") or []
    enriched = _enrich(list(updates), ("observationIds", "altitudeObservationIds"))
    enriched_alt = _enrich(list(alt_updates), ("altitudeObservationIds",))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "messageType": "result",
        "messageId": f"result-{message_id}",
        "tenantId": tenant_id,
        "siteId": site_id,
        "sessionId": session_id,
        "sentAt": utc_now_iso(),
        "payload": {
            "refMessageId": message_id,
            "replyTo": reply_to,
            "batchId": process_response.get("batchId"),
            "epoch": process_response.get("epoch"),
            "snapshotSeq": process_response.get("snapshotSeq"),
            "algorithmVersion": process_response.get("algorithmVersion"),
            "configVersion": process_response.get("configVersion"),
            "fusionProfile": process_response.get("fusionProfile"),
            "watermark": process_response.get("watermark"),
            "tracks": tracks,
            "trajectoryUpdates": enriched,
            "altitudeUpdates": enriched_alt,
            "events": process_response.get("events") or [],
            "rejected": process_response.get("rejected") or [],
            "error": process_response.get("error"),
        },
    }


def build_status(
    *,
    tenant_id: str,
    site_id: str,
    session_id: Optional[str],
    state: str,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "messageType": "status",
        "messageId": f"status-{utc_now_iso()}",
        "tenantId": tenant_id,
        "siteId": site_id,
        "sessionId": session_id or "",
        "sentAt": utc_now_iso(),
        "payload": {
            "state": state,
            "expiresHintS": 60,
            "detail": detail or {},
        },
    }


def _extract_http_error(body: Any) -> Optional[str]:
    if isinstance(body, dict):
        err = body.get("error")
        detail = body.get("detail")
        if err is None and isinstance(detail, dict):
            err = detail.get("error")
        if err is None and isinstance(detail, str):
            err = detail
        return str(err) if err is not None else None
    return None


def map_http_error_to_ack_status(http_status: int, body: Any) -> str:
    """Map HTTP failures to ack.status. 409 subtypes are distinct (not all conflict)."""
    err = _extract_http_error(body)
    if err == "idempotency_expired":
        return "idempotency_expired"
    if err == "idempotency_capacity":
        return "idempotency_capacity"
    if err == "state_recovery_required":
        return "state_recovery_required"
    if http_status == 409:
        if err in {
            "batch_id_conflict",
            "session_mode_conflict",
            "session_profile_conflict",
            "observation_id_conflict",
            "idempotency_evicted",
        }:
            return "conflict"
        return "conflict" if not err else "conflict"
    if http_status in (400, 422):
        return "rejected"
    if http_status == 413:
        return "capacity"
    if http_status >= 500:
        return "transient_error"
    return "error"


def evidence_from_observation(obs: dict[str, Any]) -> dict[str, Any]:
    raw_ref = obs.get("rawRef") if isinstance(obs.get("rawRef"), dict) else {}
    sn_ver = raw_ref.get("snMappingVersion") if isinstance(raw_ref, dict) else None
    alt_ver = raw_ref.get("altitudeMappingVersion") if isinstance(raw_ref, dict) else None
    if not sn_ver:
        sn_ver = obs.get("snMappingVersion") or SN_MAPPING_VERSION
    if not alt_ver:
        alt_ver = obs.get("altitudeMappingVersion") or ALTITUDE_MAPPING_VERSION
    return {
        "role": "position_update",
        "observationId": obs.get("observationId"),
        "source": obs.get("source"),
        "detectorId": obs.get("detectorId"),
        "sourceTrackId": obs.get("sourceTrackId"),
        "aircraftId": obs.get("aircraftId"),
        "longitude": obs.get("longitude"),
        "latitude": obs.get("latitude"),
        "altitude": obs.get("altitude"),
        "altitudeDatum": obs.get("altitudeDatum"),
        "measurementTime": obs.get("measurementTime"),
        "receivedAt": obs.get("receivedAt"),
        "rawRef": obs.get("rawRef"),
        "scanId": obs.get("scanId"),
        "snMappingVersion": sn_ver,
        "altitudeMappingVersion": alt_ver,
    }
