"""CSV/XLS comparison layers for TASK-006 Round3. Not an algorithm gate."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fusion_mvp.workbench.importer import MappingTemplate, _parse_slash_or_iso_naive, _to_iso
from fusion_mvp.workbench.xls_reader import CANONICAL_HEADERS

# Exported columns that must participate in raw semantic compare.
RAW_SEMANTIC_COLUMNS = list(CANONICAL_HEADERS)
TIME_COLUMNS = {"created_at", "created_time"}
NUMERIC_COLUMNS = {
    "longitude",
    "latitude",
    "altitude",
    "speed",
    "heading",
    "base_latitude",
    "base_longitude",
    "azimuth_angle",
    "target_distance",
    "freq",
    "height",
    "is_cooperation",
}
JSON_COLUMNS = {"source_data"}

# Std observation fields that must match. File identity / row location excluded.
STD_COMPARE_FIELDS = [
    "source",
    "detectorId",
    "sourceTrackId",
    "aircraftId",
    "measurementTime",
    "receivedAt",
    "timeBasis",
    "longitude",
    "latitude",
    "altitude",
    "altitudeDatum",
    "speed",
    "heading",
    "verticalSpeed",
    "qualityFlags",
]
STD_EXCLUDED = {
    "observationId": "generated from sheet/row/file fingerprint; not a business field",
    "rawRef": "file location metadata (sheet/row/line), not observation semantics",
}

MISSING = object()
TZ = MappingTemplate(source_timezone="Asia/Shanghai")


def _fp(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def representation_record(row: dict, *, columns: Optional[list[str]] = None) -> dict:
    """Layer 1: original values as read (types preserved via tagged JSON)."""
    cols = columns or RAW_SEMANTIC_COLUMNS
    out = {}
    for c in cols:
        if c not in row:
            out[c] = {"missing": True}
            continue
        v = row[c]
        out[c] = {"t": type(v).__name__, "v": v if not isinstance(v, float) else format(v, ".17g")}
    extras = [k for k in row if k not in cols and not str(k).startswith("__") and k is not None]
    if None in row:
        extras.append(None)
    out["__extras__"] = sorted(str(x) for x in extras)
    return out


def _number_semantic(v: Any) -> Any:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        return str(v.normalize())
    if isinstance(v, int) and not isinstance(v, bool):
        return str(Decimal(v).normalize())
    if isinstance(v, float):
        # Exact float round-trip text; does not collapse nearby decimals.
        return str(Decimal(format(v, ".17g")).normalize())
    s = str(v).strip()
    if s == "":
        return None
    try:
        return str(Decimal(s).normalize())
    except (InvalidOperation, ValueError):
        return {"unparsed_number": s}


def _time_semantic(v: Any) -> Any:
    """Actual instant in UTC with full parsed precision. Naive → Asia/Shanghai (documented)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            iso, flags = _to_iso(v.isoformat(sep=" "), TZ)
            if not iso:
                return {"unparsed_time": v.isoformat(sep=" "), "flags": flags}
            utc = datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat()
            return {"utc": utc, "raw": v.isoformat(sep=" ")}
        return {"utc": v.astimezone(timezone.utc).isoformat(), "raw": v.isoformat()}
    iso, flags = _to_iso(v, TZ)
    if not iso:
        return {"unparsed_time": str(v), "flags": flags}
    utc = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    return {"utc": utc, "raw": str(v).strip(), "precision_note": "parsed via importer _to_iso; naive uses Asia/Shanghai"}


def _json_semantic(v: Any) -> Any:
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return {"unparsed_json": s}
    return obj


def semantic_cell(col: str, v: Any) -> Any:
    if v is MISSING or (isinstance(v, dict) and v.get("missing") is True):
        return {"missing_column": col}
    if col in TIME_COLUMNS:
        return _time_semantic(v)
    if col in JSON_COLUMNS:
        return _json_semantic(v)
    if col in NUMERIC_COLUMNS:
        return _number_semantic(v)
    if v is None:
        return None
    return str(v).strip()


def raw_semantic_record(row: dict, *, columns: Optional[list[str]] = None) -> dict:
    """Layer 2: all exported columns under documented normalization."""
    cols = columns or RAW_SEMANTIC_COLUMNS
    body = {c: semantic_cell(c, row[c] if c in row else MISSING) for c in cols}
    extras = {}
    for k, v in row.items():
        if k in cols or (isinstance(k, str) and k.startswith("__")):
            continue
        extras[str(k)] = None if v is None else str(v)
    if extras:
        body["__extra_columns__"] = extras
    return body


def equality_record(row: dict, *, columns: Optional[list[str]] = None) -> dict:
    """Semantic record used for multiset equality.

    Time cells compare the UTC instant only. Original date text stays in
    raw_semantic_record for samples and in the representation layer.
    """
    rec = raw_semantic_record(row, columns=columns)
    out = {}
    for k, v in rec.items():
        if k in TIME_COLUMNS and isinstance(v, dict) and "utc" in v:
            out[k] = {"utc": v["utc"]}
        else:
            out[k] = v
    return out


def raw_semantic_fp(row: dict, *, columns: Optional[list[str]] = None) -> str:
    return _fp(equality_record(row, columns=columns))


def cell_diff_class(col: str, left: Any, right: Any) -> Optional[str]:
    """Classify a semantic-cell mismatch. None means the cells are equal."""
    if left == right:
        return None
    if col in TIME_COLUMNS and isinstance(left, dict) and isinstance(right, dict):
        if "utc" in left and left.get("utc") == right.get("utc"):
            return "time_text_same_instant"
        return "time_instant_mismatch"
    if col in NUMERIC_COLUMNS and isinstance(left, str) and isinstance(right, str):
        try:
            dl, dr = Decimal(left), Decimal(right)
            if format(float(dl), ".17g") == format(float(dr), ".17g"):
                return "binary_float_vs_decimal_text"
        except (InvalidOperation, ValueError):
            return "numeric_unparsed"
        return "numeric_value_mismatch"
    if col in JSON_COLUMNS:
        return "json_value_mismatch"
    return "text_mismatch"


def representation_fp(row: dict, *, columns: Optional[list[str]] = None) -> str:
    return _fp(representation_record(row, columns=columns))


def _instant_from_iso(iso: Optional[str]) -> Any:
    if not iso:
        return None
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return {"naive_uncompared": iso}
    return dt.astimezone(timezone.utc).isoformat()


def _std_number(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    # Keep float identity via round-trip format; do not quantize to 7 decimals.
    return format(float(v), ".17g")


def std_semantic_record(obs: dict) -> dict:
    """Layer 3: full business observation. Excludes generated ids and file location."""
    flags = obs.get("qualityFlags") or []
    return {
        "source": obs.get("source"),
        "detectorId": obs.get("detectorId"),
        "sourceTrackId": obs.get("sourceTrackId"),
        "aircraftId": obs.get("aircraftId"),
        "measurementTime": _instant_from_iso(obs.get("measurementTime")),
        "receivedAt": _instant_from_iso(obs.get("receivedAt")),
        "timeBasis": obs.get("timeBasis"),
        "longitude": _std_number(obs.get("longitude")),
        "latitude": _std_number(obs.get("latitude")),
        "altitude": _std_number(obs.get("altitude")),
        "altitudeDatum": obs.get("altitudeDatum"),
        "speed": _std_number(obs.get("speed")),
        "heading": _std_number(obs.get("heading")),
        "verticalSpeed": _std_number(obs.get("verticalSpeed")),
        "qualityFlags": sorted(str(x) for x in flags),
    }


def std_semantic_fp(obs: dict) -> str:
    return _fp(std_semantic_record(obs))


def compare_incomplete(record: dict) -> bool:
    blob = json.dumps(record, ensure_ascii=False, default=str)
    return "unparsed_time" in blob or "missing_column" in blob or "unparsed_json" in blob
