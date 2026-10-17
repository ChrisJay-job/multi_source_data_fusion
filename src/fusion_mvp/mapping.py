from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Optional

from .models import Observation, Rejected, SourceKind


SOURCE_MAP = {
    "tj-rid": "rid",
    "rid": "rid",
    "tj-pp": "spectrum",
    "spectrum": "spectrum",
    "pp": "spectrum",
    "tj-leida": "radar",
    "radar": "radar",
    "leida": "radar",
}

STANDARD_KEYS = {
    "observationId", "source", "detectorId", "sourceTrackId", "measurementTime",
}


def parse_dt(value: Any, *, allow_naive: bool = True, assume_utc: bool = True) -> tuple[Optional[datetime], list[str]]:
    flags: list[str] = []
    if value is None:
        return None, flags
    s = str(value).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None, flags
    if dt.tzinfo is None:
        if not allow_naive:
            return None, ["naive_datetime_rejected"]
        if assume_utc:
            dt = dt.replace(tzinfo=timezone.utc)
            flags.append("timezone_assumed_utc")
        else:
            return None, ["timezone_unconfirmed"]
    return dt, flags


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_heading(raw: Any, *, spectrum_unverified: bool = False) -> tuple[Optional[float], list[str]]:
    flags: list[str] = []
    if spectrum_unverified:
        flags.append("heading_unverified_spectrum_bearing")
        if raw is not None and raw != "":
            flags.append("bearing_retained_for_trace_only")
        return None, flags
    if raw is None or raw == "":
        flags.append("heading_missing")
        return None, flags
    try:
        v = float(raw)
    except (TypeError, ValueError):
        flags.append("heading_unparsed")
        return None, flags
    if not math.isfinite(v) or v < 0 or v >= 360:
        flags.append("heading_out_of_range")
        return None, flags
    return v, flags


def parse_alt(raw: Any) -> tuple[Optional[float], list[str]]:
    flags: list[str] = ["altitude_datum_unknown"]
    if raw is None or raw == "":
        flags.append("altitude_missing")
        return None, flags
    try:
        v = float(raw)
    except (TypeError, ValueError):
        flags.append("altitude_unparsed")
        return None, flags
    if not math.isfinite(v):
        flags.append("altitude_non_finite")
        return None, flags
    if v == -2:
        flags.append("altitude_sentinel_candidate")
    return v, flags


def _json_obj(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def aircraft_id_for(kind: SourceKind, row: dict, payload: dict) -> Optional[str]:
    if kind == "radar":
        return None
    if kind == "rid":
        rid = row.get("id")
        aerial = row.get("aerial_sn")
        if aerial and str(aerial).lower() == "tcp":
            return str(rid) if rid else None
        return str(rid) if rid else None
    sn = payload.get("sn") or payload.get("uavSn") or row.get("id")
    if sn in ("", None):
        return None
    return str(sn)


def detector_id(kind: SourceKind, row: dict, payload: dict) -> str:
    det = row.get("detector")
    if det:
        return str(det)
    if kind == "spectrum":
        did = payload.get("deviceId")
        if did is not None:
            return f"pp-{did}"
        sensors = payload.get("sensors") or row.get("sensors")
        if sensors:
            return str(sensors)
    if kind == "rid":
        code = payload.get("deviceCode")
        if code:
            return str(code)
        aerial = row.get("aerial_sn")
        if aerial:
            return str(aerial)
    if kind == "radar":
        rid = payload.get("radarId")
        if rid is not None:
            return str(rid)
    return "unknown-detector"


def measurement_time(row: dict, payload: dict) -> tuple[Optional[datetime], str, list[str]]:
    flags: list[str] = []
    track = payload.get("trackTime")
    dt, f1 = parse_dt(track, allow_naive=True, assume_utc=True)
    flags.extend(f1)
    if dt:
        return dt, "source_data.trackTime", flags
    dt, f2 = parse_dt(row.get("created_at"), allow_naive=True, assume_utc=True)
    flags.extend(f2)
    if dt:
        return dt, "created_at_assumed_measure", flags
    return None, "missing", flags


def stable_obs_id(file_tag: str, line_no: int, row: dict) -> str:
    basis = f"{file_tag}|{line_no}|{row.get('id')}|{row.get('source')}|{row.get('created_at')}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def _validate_latlon(lat: Any, lon: Any) -> tuple[Optional[float], Optional[float], Optional[str]]:
    try:
        lat_f = float(lat) if lat is not None else None
        lon_f = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        return None, None, "invalid_latlon"
    if lat_f is None or lon_f is None:
        return None, None, "missing_position"
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return None, None, "non_finite_latlon"
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None, None, "latlon_out_of_range"
    return lat_f, lon_f, None


def is_standard_observation(row: dict) -> bool:
    if not STANDARD_KEYS.issubset(set(row.keys())):
        return False
    src = row.get("source")
    return src in ("rid", "spectrum", "radar")


def normalize_standard(row: dict) -> tuple[Optional[Observation], Optional[Rejected]]:
    kind = row.get("source")
    if kind not in ("rid", "spectrum", "radar"):
        return None, Rejected(observationId=row.get("observationId"), reason="unknown_source", detail=str(kind))
    lat_f, lon_f, err = _validate_latlon(row.get("latitude"), row.get("longitude"))
    if err:
        return None, Rejected(observationId=row.get("observationId"), reason=err)
    mt, flags = parse_dt(row.get("measurementTime"), allow_naive=False, assume_utc=False)
    if mt is None:
        return None, Rejected(
            observationId=row.get("observationId"),
            reason="missing_time" if "naive" not in str(flags) else "naive_datetime_rejected",
            detail=",".join(flags) or None,
        )
    rec = None
    if row.get("receivedAt") is not None:
        rec, rflags = parse_dt(row.get("receivedAt"), allow_naive=False, assume_utc=False)
        flags.extend(rflags)
        if rec is None:
            return None, Rejected(observationId=row.get("observationId"), reason="invalid_received_at")
    heading, hflags = parse_heading(row.get("heading"), spectrum_unverified=False)
    flags.extend(hflags)
    alt = row.get("altitude")
    alt_f = None
    if alt is not None:
        try:
            alt_f = float(alt)
            if not math.isfinite(alt_f):
                return None, Rejected(observationId=row.get("observationId"), reason="altitude_non_finite")
        except (TypeError, ValueError):
            return None, Rejected(observationId=row.get("observationId"), reason="altitude_unparsed")
    qin = list(row.get("qualityFlags") or [])
    speed = row.get("speed")
    if speed is not None:
        try:
            speed = float(speed)
            if not math.isfinite(speed):
                return None, Rejected(observationId=row.get("observationId"), reason="speed_non_finite")
        except (TypeError, ValueError):
            return None, Rejected(observationId=row.get("observationId"), reason="speed_unparsed")
    vs = row.get("verticalSpeed")
    if vs is not None:
        try:
            vs = float(vs)
            if not math.isfinite(vs):
                return None, Rejected(observationId=row.get("observationId"), reason="vertical_speed_non_finite")
        except (TypeError, ValueError):
            return None, Rejected(observationId=row.get("observationId"), reason="vertical_speed_unparsed")
    if not row.get("detectorId") or not row.get("sourceTrackId") or not row.get("observationId"):
        return None, Rejected(observationId=row.get("observationId"), reason="missing_standard_keys")
    obs = Observation(
        observationId=str(row["observationId"]),
        source=kind,  # type: ignore[arg-type]
        detectorId=str(row["detectorId"]),
        sourceTrackId=str(row["sourceTrackId"]),
        aircraftId=(str(row["aircraftId"]) if row.get("aircraftId") not in (None, "") else None),
        measurementTime=iso(mt),
        receivedAt=iso(rec) if rec else None,
        timeBasis=str(row.get("timeBasis") or "measurement"),
        longitude=lon_f,
        latitude=lat_f,
        altitude=alt_f,
        altitudeDatum=row.get("altitudeDatum") or ("unknown" if alt_f is not None or alt is None else None),
        speed=speed,
        heading=heading,
        verticalSpeed=vs,
        qualityFlags=qin + flags,
        rawRef={"contract": "standard"},
    )
    return obs, None


def normalize_raw_row(row: dict, *, file_tag: str = "live", line_no: int = 0) -> tuple[Optional[Observation], Optional[Rejected]]:
    src_raw = str(row.get("source") or "").strip()
    kind = SOURCE_MAP.get(src_raw.lower())
    if kind is None:
        return None, Rejected(observationId=None, reason="unknown_source", detail=src_raw, rawRef={"id": row.get("id")})
    payload = _json_obj(row.get("source_data") or row.get("payload"))
    lat_f, lon_f, err = _validate_latlon(row.get("latitude"), row.get("longitude"))
    if err:
        return None, Rejected(reason=err, rawRef={"id": row.get("id")})
    mt, basis, tflags = measurement_time(row, payload)
    if mt is None:
        return None, Rejected(reason="missing_time", rawRef={"id": row.get("id")})
    heading, hflags = parse_heading(row.get("heading"), spectrum_unverified=(kind == "spectrum"))
    alt, aflags = parse_alt(row.get("altitude"))
    speed = None
    try:
        if row.get("speed") is not None:
            speed = float(row["speed"])
            if not math.isfinite(speed):
                speed = None
    except (TypeError, ValueError):
        pass
    oid = row.get("observationId") or stable_obs_id(file_tag, line_no, row)
    det = detector_id(kind, row, payload)
    if det == "unknown-detector":
        return None, Rejected(observationId=str(oid), reason="missing_detector", rawRef={"id": row.get("id")})
    rec_at, rflags = parse_dt(row.get("receivedAt") or row.get("created_time"), allow_naive=True, assume_utc=True)
    qin = list(row.get("qualityFlags") or [])
    obs = Observation(
        observationId=str(oid),
        source=kind,  # type: ignore[arg-type]
        detectorId=det,
        sourceTrackId=str(row.get("id") or payload.get("id") or oid),
        aircraftId=aircraft_id_for(kind, row, payload),  # type: ignore[arg-type]
        measurementTime=iso(mt),
        receivedAt=iso(rec_at) if rec_at else None,
        timeBasis=basis,
        longitude=lon_f,
        latitude=lat_f,
        altitude=alt,
        altitudeDatum="unknown",
        speed=speed,
        heading=heading,
        qualityFlags=qin + tflags + hflags + aflags + rflags,
        rawRef={"line_no": line_no, "file": file_tag, "source": src_raw, "contract": "raw"},
    )
    return obs, None


def normalize_row(row: dict, *, file_tag: str = "live", line_no: int = 0) -> tuple[Optional[Observation], Optional[Rejected]]:
    """Accept standard Observation JSON or historical raw table rows."""
    if is_standard_observation(row):
        return normalize_standard(row)
    if "source" not in row and row.get("kind"):
        row = {**row, "source": row["kind"]}
    return normalize_raw_row(row, file_tag=file_tag, line_no=line_no)
