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


def _to_iso(val: Any, tmpl: MappingTemplate) -> tuple[Optional[str], list[str]]:
    flags: list[str] = []
    if val is None or val == "":
        return None, ["missing_time"]
    if isinstance(val, (int, float)) or (isinstance(val, str) and val.replace(".", "", 1).isdigit()):
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
        if "+" in s[10:] or s.count("-") >= 3 and "T" in s and (s.rfind("+") > 10 or s[s.find("T"):].count("-") >= 2):
            try:
                return datetime.fromisoformat(s).isoformat(), flags
            except Exception:
                pass
        # naive
        if "T" in s:
            naive = datetime.fromisoformat(s)
        else:
            naive = datetime.fromisoformat(s.replace(" ", "T"))
        if naive.tzinfo is not None:
            return naive.isoformat(), flags
        tz_name = tmpl.source_timezone
        if tz_name and tz_name not in ("", "assume_utc") and not tmpl.assume_utc_naive:
            try:
                zi = ZoneInfo(tz_name)
                aware = naive.replace(tzinfo=zi)
                flags.append(f"timezone_applied:{tz_name}")
                return aware.isoformat(), flags
            except Exception:
                return None, ["unknown_timezone"]
        if tmpl.assume_utc_naive or tz_name == "assume_utc":
            flags.append("timezone_assumed_utc")
            return naive.replace(tzinfo=timezone.utc).isoformat(), flags
        return None, ["timezone_required"]
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


def row_to_observation(row: dict, tmpl: MappingTemplate, line_no: int) -> tuple[Optional[dict], Optional[dict]]:
    fm = tmpl.field_map
    flags: list[str] = []
    oid = _get(row, fm.get("observationId")) or f"imp-{line_no}"
    source = tmpl.source or _get(row, fm.get("source"))
    if source in ("tj-rid", "RID"):
        source = "rid"
    elif source in ("tj-pp", "PP", "spectrum"):
        source = "spectrum"
    elif source in ("tj-leida", "LEIDA", "radar"):
        source = "radar"
    if source not in ("rid", "spectrum", "radar"):
        return None, {"line": line_no, "reason": "unknown_source", "detail": str(source)}

    mt, f1 = _to_iso(_get(row, fm.get("measurementTime") or fm.get("created_at")), tmpl)
    flags.extend(f1)
    if mt is None:
        return None, {"line": line_no, "reason": "bad_measurement_time", "flags": flags}

    recv_raw = _get(row, fm.get("receivedAt"))
    if recv_raw is not None and recv_raw != "":
        rt, f2 = _to_iso(recv_raw, tmpl)
        flags.extend(f2)
        received_basis = "file_receivedAt"
    else:
        rt = mt
        received_basis = "proxy_measurementTime"
        flags.append("receivedAt_proxied_from_measurement")

    lon, ok_lon = _finite_float(_get(row, fm.get("longitude")))
    lat, ok_lat = _finite_float(_get(row, fm.get("latitude")))
    if not ok_lon or not ok_lat:
        return None, {"line": line_no, "reason": "bad_coordinates"}
    if lon is None or lat is None:
        return None, {
            "line": line_no,
            "reason": "position_fusion_unsupported",
            "detail": "当前位置融合接口需要目标经纬度；测向-only 不可伪造位置",
            "raw_keep": True,
        }
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None, {"line": line_no, "reason": "coordinates_out_of_range"}

    stid = _get(row, fm.get("sourceTrackId") or fm.get("id"))
    if stid is None or stid == "":
        return None, {"line": line_no, "reason": "missing_sourceTrackId"}

    det = _get(row, fm.get("detectorId") or fm.get("detector"))
    if det is None or det == "":
        if tmpl.detectorId:
            det = tmpl.detectorId
            flags.append("detectorId_from_template")
        else:
            return None, {"line": line_no, "reason": "missing_detectorId"}

    aircraft_id = _get(row, fm.get("aircraftId"))
    if aircraft_id is None and tmpl.treat_raw_id_as_aircraftId and source in ("rid", "spectrum"):
        aircraft_id = stid
        flags.append("raw_id_as_aircraftId")
    elif aircraft_id in (None, "") and source in ("rid", "spectrum") and not tmpl.treat_raw_id_as_aircraftId:
        flags.append("aircraftId_unconfirmed")

    alt, ok_alt = _finite_float(_get(row, fm.get("altitude")))
    if not ok_alt:
        flags.append("altitude_dropped")
        alt = None
    speed, ok_sp = _finite_float(_get(row, fm.get("speed")))
    if not ok_sp:
        flags.append("speed_dropped")
        speed = None
    heading, ok_hd = _finite_float(_get(row, fm.get("heading")))
    if not ok_hd:
        flags.append("heading_dropped")
        heading = None
    elif heading is not None and not (0 <= heading < 360):
        flags.append("heading_out_of_range")
        heading = None
    vs, ok_vs = _finite_float(_get(row, fm.get("verticalSpeed")))
    if not ok_vs:
        flags.append("verticalSpeed_dropped")
        vs = None
    datum = _get(row, fm.get("altitudeDatum")) or ("unknown" if alt is not None else "unknown")

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
        "rawRef": {"line": line_no, "receivedAtBasis": received_basis},
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


def _namespace_obs(obs: dict, path: Path) -> dict:
    stem = path.stem[:24]
    if str(obs["observationId"]).startswith("imp-"):
        obs["observationId"] = f"{stem}-{obs['observationId']}"
    return obs


def _iter_raw_rows(path: Path) -> Iterator[tuple[int, dict, bool]]:
    """Yield (line_no, row_dict, force_sql). force_sql True for SQL inserts."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                yield i, dict(row), False
    elif suffix == ".json":
        if path.stat().st_size > 32_000_000:
            raise ValueError("json_too_large")
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("observations") or data.get("rows") or []
        for i, row in enumerate(rows, start=1):
            yield i, dict(row), False
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
    try:
        for line_no, row, force_sql in _iter_raw_rows(path):
            scanned += 1
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
            mapped = dict(row)
            apply_schema_candidates(tmpl, mapped, force_sql=force_sql)
            obs, err = row_to_observation(mapped, tmpl, line_no)
            if err:
                error_count += 1
                if len(errors) < max_error_samples:
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

    def handle_row(row: dict, i: int) -> None:
        nonlocal error_count, scanned, skipped_outside_window
        scanned += 1
        if max_rows is not None and len(observations) >= max_rows:
            return
        apply_schema_candidates(tmpl, row, force_sql=False)
        obs, err = row_to_observation(row, tmpl, i)
        if err:
            error_count += 1
            if len(errors) < max_error_samples:
                errors.append(err)
            return
        assert obs is not None
        if not _obs_matches(obs, filt):
            skipped_outside_window += 1
            return
        observations.append(_namespace_obs(obs, path))
        if len(preview) < 5:
            preview.append(obs)

    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                handle_row(dict(row), i)
                if max_rows is not None and len(observations) >= max_rows:
                    break
    elif suffix == ".json":
        # size guard BEFORE read_text (Round3)
        if path.stat().st_size > 32_000_000:
            return {"ok": False, "error": "json_too_large", "limit_bytes": 32_000_000, "hint": "use JSONL or SQL stream"}
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("observations") or data.get("rows") or []
        for i, row in enumerate(rows, start=1):
            handle_row(dict(row), i)
            if max_rows is not None and len(observations) >= max_rows:
                break
    elif suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                handle_row(json.loads(line), i)
                if max_rows is not None and len(observations) >= max_rows:
                    break
    else:
        return {"ok": False, "error": "unsupported_format", "suffix": suffix}

    summary = _summarize(observations, errors, preview, path)
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
