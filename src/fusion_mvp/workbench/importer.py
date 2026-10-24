"""File import adapters. SQL is parsed as text only — never executed."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

from fusion_mvp.sql_stream import COLUMNS as FLIGHT_COLUMNS
from fusion_mvp.sql_stream import parse_sql_tuple

FLIGHT_PREFIX = 'INSERT INTO "public"."aircraft_flight_data" VALUES ('
_INSERT_WITH_COLS = re.compile(
    r'INSERT\s+INTO\s+(?:"?public"?\.)?"?aircraft_flight_data"?\s*\(([^)]+)\)\s*VALUES\s*\(',
    re.IGNORECASE,
)


@dataclass
class MappingTemplate:
    version: str = "1"
    source: Optional[str] = None
    detectorId: Optional[str] = None  # None => require field or reject
    field_map: dict[str, str] = field(default_factory=dict)
    source_timezone: Optional[str] = None
    assume_utc_naive: bool = False
    treat_raw_id_as_aircraftId: bool = False
    time_unit: str = "auto"  # auto|s|ms
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_dict(cls, d: dict) -> "MappingTemplate":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _get(row: dict, key: Optional[str]) -> Any:
    """Resolve flat key or dotted JSON path (e.g. source_data.deviceId)."""
    if not key:
        return None
    if key in row:
        return row[key]
    low = {str(k).lower(): k for k in row}
    k = low.get(str(key).lower())
    if k:
        return row[k]
    if "." in str(key):
        parts = str(key).split(".")
        cur: Any = row
        for p in parts:
            if cur is None:
                return None
            if isinstance(cur, str):
                try:
                    cur = json.loads(cur)
                except Exception:
                    return None
            if not isinstance(cur, dict):
                return None
            low2 = {str(x).lower(): x for x in cur}
            kk = low2.get(p.lower())
            if kk is None:
                return None
            cur = cur[kk]
        return cur
    return None


# Page / Navicat aircraft_flight_data default candidates (not a claim of confirmed semantics)
SQL_FLIGHT_CANDIDATES = {
    "measurementTime": ["created_at", "measurementTime", "source_data.trackTime"],
    "sourceTrackId": ["id", "sourceTrackId"],
    "detectorId": ["detector", "source_data.deviceId", "detectorId"],
    "source": ["source"],
    "longitude": ["longitude"],
    "latitude": ["latitude"],
    "altitude": ["altitude"],
    "speed": ["speed"],
    "heading": ["heading"],
    "aircraftId": ["aircraftId"],  # never auto-fill from aerial_sn/tcp
    "receivedAt": ["receivedAt"],
    "observationId": ["observationId"],
}


def apply_schema_candidates(tmpl: MappingTemplate, row: dict, *, force_sql: bool = False) -> list[str]:
    """
    Bind standard fields to schema candidates when current map misses the row.
    Does not override a user-explicit mapping that resolves to a present value.
    """
    notes: list[str] = []
    fm = tmpl.field_map
    for std, cands in SQL_FLIGHT_CANDIDATES.items():
        cur = fm.get(std)
        if cur and _get(row, cur) not in (None, ""):
            continue  # active mapping works
        # Do not silently override non-identity explicit choices that simply miss
        if cur and cur not in (std, *cands) and not force_sql:
            # still try if value missing — only when identity/placeholder
            if cur not in ("measurementTime", "sourceTrackId", "detectorId", "created_at", "id", "detector"):
                notes.append(f"keep_explicit:{std}->{cur}")
                continue
        for c in cands:
            if _get(row, c) not in (None, ""):
                if cur != c:
                    notes.append(f"schema_map:{std}->{c}")
                fm[std] = c
                break
    return notes


def _apply_tz(naive: datetime, tmpl: MappingTemplate, flags: list[str]) -> tuple[Optional[str], list[str]]:
    if naive.tzinfo is not None:
        return naive.isoformat(), flags
    tz_name = tmpl.source_timezone
    if tz_name and tz_name not in ("", "assume_utc") and not tmpl.assume_utc_naive:
        try:
            zi = ZoneInfo(tz_name)
            aware = naive.replace(tzinfo=zi)
            flags.append(f"timezone_applied:{tz_name}")
            # Asia/Shanghai is a local-replay assumption until device confirms
            if tz_name in ("Asia/Shanghai", "Asia/Chongqing"):
                flags.append("timezone_pending_device_confirm")
            return aware.isoformat(), flags
        except Exception:
            return None, flags + ["unknown_timezone"]
    if tmpl.assume_utc_naive or tz_name == "assume_utc":
        flags.append("timezone_assumed_utc")
        return naive.replace(tzinfo=timezone.utc).isoformat(), flags
    return None, flags + ["timezone_required"]


def _parse_slash_or_iso_naive(s: str) -> Optional[datetime]:
    """Parse ISO / space / slash local datetimes (Y/M/D or D/M/Y when unambiguous)."""
    s = s.strip()
    if not s:
        return None
    # Normalize slash dates: 2026/6/24 or 24/6/2026 8:00:30.123
    if "/" in s[:12]:
        parts = s.replace("T", " ").split(" ", 1)
        nums = [int(x) for x in parts[0].split("/")]
        if len(nums) != 3:
            return None
        a, b, c = nums
        if a > 31:  # Y/M/D
            y, m, day = a, b, c
        elif c > 31:  # day/month/year or month/day/year
            if a > 12:  # D/M/Y
                day, m, y = a, b, c
            elif b > 12:  # M/D/Y
                m, day, y = a, b, c
            else:
                # Ambiguous (both <=12): prefer D/M/Y (common in this project's CSV export)
                day, m, y = a, b, c
        else:
            return None
        if not (1 <= m <= 12 and 1 <= day <= 31 and y >= 1):
            return None
        d_norm = f"{y:04d}-{m:02d}-{day:02d}"
        t = parts[1] if len(parts) > 1 else "00:00:00"
        tp = t.split(":")
        if len(tp) >= 1 and tp[0].isdigit():
            tp[0] = f"{int(tp[0]):02d}"
        t_norm = ":".join(tp)
        s = f"{d_norm}T{t_norm}"
    elif " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_iso(val: Any, tmpl: MappingTemplate) -> tuple[Optional[str], list[str]]:
    flags: list[str] = []
    if val is None or val == "":
        return None, ["missing_time"]
    # Generic numeric / digit-string → epoch (s|ms|auto). Excel serials are converted
    # only in the OLE reader (typed date cells / known time columns + workbook datemode).
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        num = float(val)
        try:
            if tmpl.time_unit == "ms" or (tmpl.time_unit == "auto" and num > 1e12):
                num = num / 1000.0
            return datetime.fromtimestamp(num, tz=timezone.utc).isoformat(), flags
        except Exception:
            return None, ["bad_epoch"]
    if isinstance(val, str) and val.replace(".", "", 1).replace("-", "", 1).isdigit() and "/" not in val and ":" not in val:
        try:
            num = float(val)
            if tmpl.time_unit == "ms" or (tmpl.time_unit == "auto" and num > 1e12):
                num = num / 1000.0
            return datetime.fromtimestamp(num, tz=timezone.utc).isoformat(), flags
        except Exception:
            return None, ["bad_epoch"]
    s = str(val).strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat(), flags
        # with offset already
        if "+" in s[10:] or (s.count("-") >= 3 and "T" in s and (s.rfind("+") > 10 or s[s.find("T") :].count("-") >= 2)):
            try:
                return datetime.fromisoformat(s).isoformat(), flags
            except Exception:
                pass
        naive = _parse_slash_or_iso_naive(s)
        if naive is None:
            return None, ["unparseable_time"]
        return _apply_tz(naive, tmpl, flags)
    except Exception:
        return None, ["unparseable_time"]


def _finite_float(val: Any) -> tuple[Optional[float], bool]:
    if val is None or val == "":
        return None, True
    try:
        f = float(val)
        if f != f or f in (float("inf"), float("-inf")):
            return None, False
        return f, True
    except Exception:
        return None, False


def _normalize_source(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Map row source aliases → rid|spectrum|radar. Returns (canonical, original_or_None)."""
    if raw is None or raw == "":
        return None, None
    s = str(raw).strip()
    low = s.lower()
    if low in ("rid", "tj-rid") or s == "RID":
        return "rid", s if s != "rid" else None
    if low in ("pp", "tj-pp", "spectrum") or s == "PP":
        return "spectrum", s if low != "spectrum" else None
    if low in ("leida", "tj-leida", "radar", "lida") or s == "LEIDA":
        return "radar", s if low != "radar" else None
    return None, s


def row_to_observation(row: dict, tmpl: MappingTemplate, line_no: int) -> tuple[Optional[dict], Optional[dict]]:
    fm = tmpl.field_map
    flags: list[str] = []
    sheet = row.get("__sheet__") or "sheet"
    prow = row.get("__row__") or line_no
    oid = _get(row, fm.get("observationId"))
    if oid in (None, ""):
        oid = f"imp-{sheet}-{prow}"
    source_raw = tmpl.source or _get(row, fm.get("source") or "source")
    source, alias_from = _normalize_source(source_raw)
    if alias_from:
        flags.append(f"source_alias:{alias_from}->{source}")
    if source not in ("rid", "spectrum", "radar"):
        return None, {"line": line_no, "reason": "unknown_source", "detail": str(source_raw), "sheet": sheet, "row": prow}

    # Prefer created_at; keep created_time as parallel mark (do not silently rewrite)
    mt_raw = _get(row, fm.get("measurementTime") or fm.get("created_at") or "created_at")
    mt, f1 = _to_iso(mt_raw, tmpl)
    flags.extend(f1)
    ct_raw = row.get("created_time")
    if ct_raw not in (None, "") and str(ct_raw) != str(mt_raw):
        flags.append("created_time_present_distinct")
        # optional delta note only — do not replace measurementTime
        ct_iso, _ = _to_iso(ct_raw, tmpl)
        if mt and ct_iso:
            try:
                dlt = abs(
                    datetime.fromisoformat(mt.replace("Z", "+00:00")).timestamp()
                    - datetime.fromisoformat(ct_iso.replace("Z", "+00:00")).timestamp()
                )
                if dlt > 1.0:
                    flags.append(f"created_time_delta_s:{dlt:.3f}")
            except Exception:
                pass
    if mt is None:
        return None, {"line": line_no, "reason": "bad_measurement_time", "flags": flags, "sheet": sheet, "row": prow}

    recv_raw = _get(row, fm.get("receivedAt"))
    if recv_raw is not None and recv_raw != "":
        rt, f2 = _to_iso(recv_raw, tmpl)
        flags.extend(f2)
        received_basis = "file_receivedAt"
    else:
        rt = mt
        received_basis = "proxy_measurementTime"
        flags.append("receivedAt_proxied_from_measurement")

    lon, ok_lon = _finite_float(_get(row, fm.get("longitude") or "longitude"))
    lat, ok_lat = _finite_float(_get(row, fm.get("latitude") or "latitude"))
    if not ok_lon or not ok_lat:
        return None, {"line": line_no, "reason": "bad_coordinates", "sheet": sheet, "row": prow}
    if lon is None or lat is None:
        return None, {
            "line": line_no,
            "reason": "position_fusion_unsupported",
            "detail": "当前位置融合接口需要目标经纬度；测向-only 不可伪造位置",
            "raw_keep": True,
            "sheet": sheet,
            "row": prow,
        }
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None, {"line": line_no, "reason": "coordinates_out_of_range", "sheet": sheet, "row": prow}
    # Dataset placeholder: exact (0,0) — isolate; do not use for map fit / co-occurrence hard filter
    if lon == 0.0 and lat == 0.0:
        return None, {
            "line": line_no,
            "reason": "position_placeholder_0_0",
            "detail": "lon=lat=0 treated as invalid placeholder for this dataset",
            "raw_keep": True,
            "sheet": sheet,
            "row": prow,
            "flags": ["position_placeholder_0_0"],
        }

    stid = _get(row, fm.get("sourceTrackId") or fm.get("id") or "id")
    if stid is None or stid == "":
        return None, {"line": line_no, "reason": "missing_sourceTrackId", "sheet": sheet, "row": prow}

    det = _get(row, fm.get("detectorId") or fm.get("detector") or "detector")
    if det is None or det == "":
        if tmpl.detectorId:
            det = tmpl.detectorId
            flags.append("detectorId_from_template")
        else:
            return None, {"line": line_no, "reason": "missing_detectorId", "sheet": sheet, "row": prow}

    aircraft_id = _get(row, fm.get("aircraftId") or "aircraftId")
    if aircraft_id is None and tmpl.treat_raw_id_as_aircraftId and source in ("rid", "spectrum"):
        aircraft_id = stid
        flags.append("raw_id_as_aircraftId")
    elif aircraft_id in (None, "") and source in ("rid", "spectrum") and not tmpl.treat_raw_id_as_aircraftId:
        flags.append("aircraftId_unconfirmed")

    alt, ok_alt = _finite_float(_get(row, fm.get("altitude") or "altitude"))
    if not ok_alt:
        flags.append("altitude_dropped")
        alt = None
    speed, ok_sp = _finite_float(_get(row, fm.get("speed") or "speed"))
    if not ok_sp:
        flags.append("speed_dropped")
        speed = None
    heading, ok_hd = _finite_float(_get(row, fm.get("heading") or "heading"))
    if not ok_hd:
        flags.append("heading_dropped")
        heading = None
    elif heading is not None and not (0 <= heading < 360):
        flags.append("heading_out_of_range")
        heading = None
    vs, ok_vs = _finite_float(_get(row, fm.get("verticalSpeed") or "verticalSpeed"))
    if not ok_vs:
        flags.append("verticalSpeed_dropped")
        vs = None
    datum = _get(row, fm.get("altitudeDatum") or "altitudeDatum") or ("unknown" if alt is not None else "unknown")

    obs = {
        "observationId": str(oid),
        "source": source,
        "detectorId": str(det),
        "sourceTrackId": str(stid),
        "aircraftId": str(aircraft_id) if aircraft_id not in (None, "") else None,
        "measurementTime": mt,
        "receivedAt": rt,
        "timeBasis": "measurement",
        "longitude": lon,
        "latitude": lat,
        "altitude": alt,
        "altitudeDatum": str(datum),
        "speed": speed,
        "heading": heading,
        "verticalSpeed": vs,
        "qualityFlags": flags,
        "rawRef": {
            "line": line_no,
            "sheet": sheet,
            "row": prow,
            "receivedAtBasis": received_basis,
            "sourceRaw": str(source_raw) if source_raw is not None else None,
        },
    }
    return obs, None


def iter_sql_inserts(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Stream INSERT rows from Navicat-style dump. Never executes SQL."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            upper = line.upper()
            if "DROP " in upper or "TRUNCATE " in upper:
                continue
            stripped = line.lstrip()
            # Form A: VALUES without column list (project actual dump) — require exact 25 cols
            if stripped.startswith(FLIGHT_PREFIX) or line.startswith(FLIGHT_PREFIX):
                body = line[line.index(FLIGHT_PREFIX) + len(FLIGHT_PREFIX) :]
                vals = parse_sql_tuple(body)
                if len(vals) != len(FLIGHT_COLUMNS):
                    yield line_no, {"__sql_error__": "column_count_mismatch", "__got__": len(vals), "__want__": len(FLIGHT_COLUMNS)}
                    continue
                row = {FLIGHT_COLUMNS[i]: vals[i] for i in range(len(FLIGHT_COLUMNS))}
                yield line_no, row
                continue
            # Form B: INSERT ... (cols) VALUES (...)
            m = _INSERT_WITH_COLS.search(line)
            if not m:
                continue
            cols = [c.strip().strip('`"') for c in m.group(1).split(",")]
            body = line[m.end() :]
            vals = parse_sql_tuple(body)
            if len(vals) != len(cols):
                yield line_no, {"__sql_error__": "column_list_mismatch", "__got__": len(vals), "__want__": len(cols)}
                continue
            yield line_no, dict(zip(cols, vals))


@dataclass
class ObsFilter:
    """Unified selection applied while scanning (before max_rows / page limit)."""

    time_from: Optional[str] = None
    time_to: Optional[str] = None
    detector_id: Optional[str] = None
    lon_min: Optional[float] = None
    lon_max: Optional[float] = None
    lat_min: Optional[float] = None
    lat_max: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeFrom": self.time_from,
            "timeTo": self.time_to,
            "detectorId": self.detector_id,
            "lonMin": self.lon_min,
            "lonMax": self.lon_max,
            "latMin": self.lat_min,
            "latMax": self.lat_max,
        }


def _in_time_window(obs: dict, time_from: Optional[str], time_to: Optional[str]) -> bool:
    if not time_from and not time_to:
        return True
    raw = obs.get("measurementTime") or ""
    if not raw:
        return False
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if time_from:
        tf = datetime.fromisoformat(str(time_from).replace("Z", "+00:00"))
        if t < tf:
            return False
    if time_to:
        tt = datetime.fromisoformat(str(time_to).replace("Z", "+00:00"))
        if t > tt:
            return False
    return True


def _obs_matches(obs: dict, filt: Optional[ObsFilter]) -> bool:
    if filt is None:
        return True
    if not _in_time_window(obs, filt.time_from, filt.time_to):
        return False
    if filt.detector_id is not None and str(obs.get("detectorId") or "") != str(filt.detector_id):
        return False
    lon = obs.get("longitude")
    lat = obs.get("latitude")
    if filt.lon_min is not None and (lon is None or lon < filt.lon_min):
        return False
    if filt.lon_max is not None and (lon is None or lon > filt.lon_max):
        return False
    if filt.lat_min is not None and (lat is None or lat < filt.lat_min):
        return False
    if filt.lat_max is not None and (lat is None or lat > filt.lat_max):
        return False
    return True


# path -> (fp8, size, mtime_ns). Invalidated when size/mtime change; value is content hash.
_PATH_FP_CACHE: dict[str, tuple[str, int, int]] = {}


def clear_path_fp_cache() -> None:
    _PATH_FP_CACHE.clear()


def _path_fp8(path: Path) -> str:
    """Stable content-based file identity (8 hex). Cache keyed by path+size+mtime_ns."""
    key = str(path.resolve())
    st = path.stat()
    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
    cached = _PATH_FP_CACHE.get(key)
    if cached and cached[1] == st.st_size and cached[2] == mtime_ns:
        return cached[0]
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    fid = h.hexdigest()[:8]
    _PATH_FP_CACHE[key] = (fid, st.st_size, mtime_ns)
    return fid


def _namespace_obs(obs: dict, path: Path) -> dict:
    stem = path.stem[:24]
    fid = _path_fp8(path)
    oid = str(obs["observationId"])
    if oid.startswith("imp-"):
        obs["observationId"] = f"{stem}-{fid}-{oid}"
    obs.setdefault("rawRef", {})
    if isinstance(obs["rawRef"], dict):
        obs["rawRef"]["fileFp8"] = fid
        obs["rawRef"]["fileStem"] = stem
    return obs


# Object containers. A present key wins even when its value is an empty list.
# Two or more of these keys at once is an ambiguity error, not a truthiness fallback.
JSON_CONTAINER_KEYS = ("observations", "rows", "RECORDS")
# JSON-only marks. Spreadsheet __sheet__/__row__ stay until row_to_observation.
_JSON_META_KEYS = frozenset({
    "__json_row_error__",
    "__json_index__",
    "__json_type__",
    "__record_index__",
})


def _row_for_mapping(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _JSON_META_KEYS}


def _json_container(data: Any) -> tuple[list, str]:
    """Return (records, container name) or raise ValueError('json_structure:...')."""
    if isinstance(data, list):
        return data, "top_level_array"
    if isinstance(data, dict):
        present = [k for k in JSON_CONTAINER_KEYS if k in data]
        if len(present) > 1:
            raise ValueError("json_structure:ambiguous_containers:" + ",".join(present))
        if not present:
            raise ValueError("json_structure:unknown_object")
        key = present[0]
        rows = data[key]
        if not isinstance(rows, list):
            raise ValueError(f"json_structure:container_not_array:{key}:{type(rows).__name__}")
        return rows, key
    raise ValueError(f"json_structure:top_level_{type(data).__name__}")


def _json_structure_result(msg: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "json_structure",
        "detail": msg,
        "file_read_ok": False,
        "scanned_rows": 0,
        "n_observations": 0,
        "n_errors": 0,
        "empty_record_set": False,
    }


def _note_json_row_error(row: dict, line_no: int, errors: list[dict], error_count: int, max_error_samples: int) -> int:
    error_count += 1
    if len(errors) < max_error_samples:
        errors.append(
            {
                "line": line_no,
                "record_index": row.get("__json_index__"),
                "index_kind": "json_record",
                "reason": row.get("__json_row_error__"),
                "detail": row.get("__json_type__"),
            }
        )
    return error_count


def _iter_raw_rows(path: Path, meta: Optional[dict] = None) -> Iterator[tuple[int, dict, bool]]:
    """Yield (line_no, row_dict, force_sql). force_sql True for SQL inserts."""
    suffix = path.suffix.lower()
    kind = None
    if suffix in {".xls", ".xlsx"}:
        from .xls_reader import detect_spreadsheet_kind, iter_ole_xls_rows

        kind = detect_spreadsheet_kind(path)
        if kind == "ole_xls":
            for line_no, row in iter_ole_xls_rows(path):
                yield line_no, row, False
            return
        if kind == "ooxml_xlsx":
            raise ValueError("unsupported_format:.xlsx_ooxml_not_enabled")
        raise ValueError(f"unsupported_format:{suffix}:{kind}")
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                yield i, dict(row), False
    elif suffix == ".json":
        if path.stat().st_size > 32_000_000:
            raise ValueError("json_too_large")
        text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"json_structure:malformed:{exc.lineno}:{exc.colno}") from exc
        rows, container = _json_container(data)
        if meta is not None:
            meta["json_container"] = container
            meta["json_record_count"] = len(rows)
            meta["empty_record_set"] = len(rows) == 0
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                yield i, {
                    "__json_row_error__": "json_element_not_object",
                    "__json_index__": i,
                    "__json_type__": type(row).__name__,
                }, False
                continue
            tagged = dict(row)
            tagged["__record_index__"] = i
            yield i, tagged, False
    elif suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                yield i, json.loads(line), False
    elif suffix == ".sql":
        for line_no, row in iter_sql_inserts(path):
            yield line_no, row, True
    else:
        raise ValueError(f"unsupported_format:{suffix}")


def page_observations(
    path: str | Path,
    tmpl: MappingTemplate,
    *,
    offset: int = 0,
    limit: int = 50,
    filt: Optional[ObsFilter] = None,
) -> dict[str, Any]:
    """
    Stream: normalize → filter → skip offset hits → retain at most limit (+1 for hasMore).
    Does not materialize skipped prefix in memory.
    """
    path = Path(path)
    if offset < 0 or limit <= 0:
        return {"ok": False, "error": "invalid_pagination", "offset": offset, "limit": limit}
    limit = min(int(limit), 2000)
    offset = int(offset)
    page: list[dict] = []
    errors: list[dict] = []
    scanned = 0
    matched = 0
    skipped_filter = 0
    skipped_offset = 0
    error_count = 0
    max_error_samples = 20
    has_more = False
    read_meta: dict[str, Any] = {}
    try:
        for line_no, row, force_sql in _iter_raw_rows(path, read_meta):
            scanned += 1
            if row.get("__json_row_error__"):
                error_count = _note_json_row_error(row, line_no, errors, error_count, max_error_samples)
                continue
            if row.get("__sql_error__"):
                error_count += 1
                if len(errors) < max_error_samples:
                    errors.append(
                        {
                            "line": line_no,
                            "reason": row["__sql_error__"],
                            "got": row.get("__got__"),
                            "want": row.get("__want__"),
                        }
                    )
                continue
            mapped = _row_for_mapping(row)
            apply_schema_candidates(tmpl, mapped, force_sql=force_sql)
            obs, err = row_to_observation(mapped, tmpl, line_no)
            if err:
                error_count += 1
                if len(errors) < max_error_samples:
                    if row.get("__record_index__") is not None:
                        err = dict(err)
                        err["record_index"] = row["__record_index__"]
                        err["index_kind"] = "json_record"
                    errors.append(err)
                continue
            assert obs is not None
            if not _obs_matches(obs, filt):
                skipped_filter += 1
                continue
            matched += 1
            if matched <= offset:
                skipped_offset += 1
                continue
            if len(page) < limit:
                page.append(_namespace_obs(obs, path))
            else:
                has_more = True
                break
    except ValueError as e:
        msg = str(e)
        if msg.startswith("json_too_large"):
            return {"ok": False, "error": "json_too_large", "limit_bytes": 32_000_000}
        if msg.startswith("json_structure"):
            return _json_structure_result(msg)
        if msg.startswith("unsupported_format"):
            return {"ok": False, "error": "unsupported_format", "suffix": path.suffix.lower()}
        raise
    return {
        "ok": True,
        "path": str(path),
        "observations": page,
        "n": len(page),
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + len(page) if has_more else None,
        "matched_so_far": matched,
        "scanned": scanned,
        "skipped_filter": skipped_filter,
        "skipped_offset": skipped_offset,
        "n_errors": error_count,
        "errors_sample": errors[:max_error_samples],
        "json_container": read_meta.get("json_container"),
        "empty_record_set": bool(read_meta.get("empty_record_set")),
        "filters": (filt.to_dict() if filt else ObsFilter().to_dict()),
        "truncated": has_more,
        # Memory bound: only page (+ nothing of skipped prefix)
        "materialized": len(page),
    }


def import_tabular(
    path: str | Path,
    tmpl: MappingTemplate,
    *,
    max_rows: Optional[int] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    detector_id: Optional[str] = None,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    filt: Optional[ObsFilter] = None,
) -> dict[str, Any]:
    path = Path(path)
    observations: list[dict] = []
    errors: list[dict] = []
    preview: list[dict] = []
    suffix = path.suffix.lower()
    filt = filt or ObsFilter(
        time_from=time_from,
        time_to=time_to,
        detector_id=detector_id,
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max,
    )

    error_count = 0
    scanned = 0
    skipped_outside_window = 0
    max_error_samples = 20
    raw_preview_rows: list[dict] = []
    columns: list[str] = []
    read_meta: dict[str, Any] = {}

    try:
        for i, row, force_sql in _iter_raw_rows(path, read_meta):
            if len(raw_preview_rows) < 5:
                # strip internal keys for UI
                raw_preview_rows.append({k: v for k, v in row.items() if not str(k).startswith("__")})
            if not columns:
                columns = [k for k in row.keys() if not str(k).startswith("__")]
            scanned += 1
            if max_rows is not None and len(observations) >= max_rows:
                # continue counting scan? stop early for import_tabular materialize path
                break
            if row.get("__json_row_error__"):
                error_count = _note_json_row_error(row, i, errors, error_count, max_error_samples)
                continue
            if row.get("__sql_error__"):
                error_count += 1
                if len(errors) < max_error_samples:
                    errors.append({"line": i, "reason": row["__sql_error__"]})
                continue
            mapped = _row_for_mapping(row)
            apply_schema_candidates(tmpl, mapped, force_sql=force_sql)
            obs, err = row_to_observation(mapped, tmpl, i)
            if err:
                error_count += 1
                if len(errors) < max_error_samples:
                    if row.get("__record_index__") is not None:
                        err = dict(err)
                        err["record_index"] = row["__record_index__"]
                        err["index_kind"] = "json_record"
                    errors.append(err)
                continue
            assert obs is not None
            if not _obs_matches(obs, filt):
                skipped_outside_window += 1
                continue
            observations.append(_namespace_obs(obs, path))
            if len(preview) < 5:
                preview.append(obs)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("unsupported_format"):
            return {"ok": False, "error": "unsupported_format", "suffix": suffix, "detail": msg}
        if msg.startswith("json_too_large"):
            return {"ok": False, "error": "json_too_large", "limit_bytes": 32_000_000}
        if msg.startswith("json_structure"):
            out = _json_structure_result(msg)
            out["suffix"] = suffix
            return out
        raise

    summary = _summarize(observations, errors, preview, path)
    summary["raw_columns"] = columns
    summary["raw_preview_rows"] = raw_preview_rows
    summary["file_read_ok"] = True
    summary["json_container"] = read_meta.get("json_container")
    summary["empty_record_set"] = bool(read_meta.get("empty_record_set"))
    summary["error_count"] = error_count
    summary["n_errors"] = error_count
    summary["errors_sample"] = errors[:max_error_samples]
    summary["scanned_rows"] = scanned
    summary["skipped_outside_window"] = skipped_outside_window
    summary["filters"] = filt.to_dict()
    summary["window"] = {"timeFrom": filt.time_from, "timeTo": filt.time_to}
    summary["truncated"] = bool(max_rows is not None and len(observations) >= max_rows)
    return summary


def import_sql_stream(
    path: str | Path,
    tmpl: MappingTemplate,
    *,
    max_rows: Optional[int] = 5000,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    detector_id: Optional[str] = None,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    filt: Optional[ObsFilter] = None,
    progress_cb=None,
) -> dict[str, Any]:
    path = Path(path)
    observations: list[dict] = []
    errors: list[dict] = []
    preview: list[dict] = []
    scanned = 0
    unsupported = 0
    error_count = 0
    skipped_outside_window = 0
    max_error_samples = 20
    filt = filt or ObsFilter(
        time_from=time_from,
        time_to=time_to,
        detector_id=detector_id,
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max,
    )
    for line_no, row in iter_sql_inserts(path):
        scanned += 1
        if progress_cb and scanned % 1000 == 0:
            progress_cb(scanned, len(observations), error_count)
        if max_rows is not None and len(observations) >= max_rows:
            # Still count remaining errors without retaining all samples when scanning fails
            # only after acceptance quota filled — stop ingest; do not accumulate unbounded errors.
            break
        if row.get("__sql_error__"):
            unsupported += 1
            error_count += 1
            if len(errors) < max_error_samples:
                errors.append(
                    {
                        "line": line_no,
                        "reason": row["__sql_error__"],
                        "got": row.get("__got__"),
                        "want": row.get("__want__"),
                    }
                )
            continue
        mapped = dict(row)
        apply_schema_candidates(tmpl, mapped, force_sql=True)
        obs, err = row_to_observation(mapped, tmpl, line_no)
        if err:
            error_count += 1
            if len(errors) < max_error_samples:
                errors.append(err)
            continue
        assert obs is not None
        if not _obs_matches(obs, filt):
            skipped_outside_window += 1
            continue
        observations.append(_namespace_obs(obs, path))
        if len(preview) < 5:
            preview.append(obs)
    summary = _summarize(observations, errors, preview, path)
    summary["n_errors"] = error_count
    summary["error_count"] = error_count
    summary["errors_sample"] = errors[:max_error_samples]
    summary["scanned_inserts"] = scanned
    summary["unsupported_syntax"] = unsupported
    summary["skipped_outside_window"] = skipped_outside_window
    summary["filters"] = filt.to_dict()
    summary["window"] = {"timeFrom": filt.time_from, "timeTo": filt.time_to}
    summary["truncated"] = bool(max_rows is not None and len(observations) >= max_rows)
    summary["sql_note"] = "仅解析 INSERT 文本；不执行 DROP/INSERT；源文件只读；25列 VALUES 须列数严格匹配"
    summary["field_map_applied"] = dict(tmpl.field_map)
    if scanned == 0 and summary["n_observations"] == 0:
        summary["ok"] = False
        summary["error"] = "no_insert_rows_recognized"
        summary["hint"] = "支持 aircraft_flight_data VALUES 无列名形式，或带列名 INSERT；其他语法计入拒绝"
    if summary["n_observations"] == 0 and error_count:
        summary["ok"] = False
        summary["error"] = summary.get("error") or "no_valid_observations"
    return summary


def _summarize(observations: list[dict], errors: list[dict], preview: list[dict], path: Path) -> dict:
    by_src: dict[str, int] = {}
    times: list[str] = []
    lons: list[float] = []
    lats: list[float] = []
    for o in observations:
        by_src[o["source"]] = by_src.get(o["source"], 0) + 1
        times.append(o["measurementTime"])
        lons.append(o["longitude"])
        lats.append(o["latitude"])
    return {
        "ok": True,
        "path": str(path),
        "n_observations": len(observations),
        "n_errors": len(errors),
        "error_count": len(errors),
        "by_source": by_src,
        "time_range": [min(times), max(times)] if times else None,
        "lon_range": [min(lons), max(lons)] if lons else None,
        "lat_range": [min(lats), max(lats)] if lats else None,
        "errors_sample": errors[:20],
        "preview": preview,
        "observations": observations,
        "cooccurrence_note": "仅时间范围重叠不能标同目标同步；跨源共现需人工／评估模块确认",
    }
