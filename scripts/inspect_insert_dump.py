"""Stream Navicat INSERT dump. Never load the whole file."""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

COLUMNS = [
    "id", "longitude", "latitude", "altitude", "speed", "heading", "created_at",
    "source", "type", "aerial_sn", "detector", "source_data", "uav_type", "model",
    "brand", "model_number", "base_latitude", "base_longitude", "azimuth_angle",
    "target_distance", "sensors", "freq", "district", "height", "created_time",
]

PREFIX = 'INSERT INTO "public"."aircraft_flight_data" VALUES ('


def parse_sql_tuple(body: str) -> list:
    out = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if body[i] == ")":
            break
        if body.startswith("NULL", i) and (i + 4 == n or body[i + 4] in ",)"):
            out.append(None)
            i += 4
            continue
        if body[i] == "'":
            i += 1
            buf = []
            while i < n:
                ch = body[i]
                if ch == "'" and i + 1 < n and body[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                if ch == "'":
                    i += 1
                    break
                buf.append(ch)
                i += 1
            out.append("".join(buf))
            continue
        j = i
        while j < n and body[j] not in ",)":
            j += 1
        token = body[i:j].strip()
        if token:
            out.append(token)
        i = j
    return out


def to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_dt(v):
    if not v:
        return None
    s = str(v).replace(" ", "T")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.min(1.0, math.sqrt(a)))


def json_keys(text: str) -> list[str]:
    try:
        obj = json.loads(text)
    except Exception:
        return []
    return list(obj.keys()) if isinstance(obj, dict) else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sql_path")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--sample-dir", required=True)
    ap.add_argument("--per-source", type=int, default=80)
    ap.add_argument("--json-parse-cap", type=int, default=8000)
    args = ap.parse_args()

    path = Path(args.sql_path)
    rng = random.Random(17)
    st = path.stat()
    sources = Counter()
    detectors = defaultdict(Counter)
    ids = defaultdict(Counter)
    aerial = defaultdict(Counter)
    heading_odd = Counter()
    alt_neg = Counter()
    nulls = defaultdict(Counter)
    rows = 0
    parse_fail = 0
    json_parsed = 0
    sd_keys = Counter()
    sn_from_json = Counter()
    time_min = {}
    time_max = {}
    ctime_min = {}
    ctime_max = {}
    samples = defaultdict(list)
    sample_seen = defaultdict(lambda: [0])
    hour_bins = defaultdict(Counter)
    latlon = defaultdict(lambda: {"lat": [], "lon": []})

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            if not line.startswith(PREFIX):
                continue
            body = line[len(PREFIX) :]
            vals = parse_sql_tuple(body)
            if len(vals) < 8:
                parse_fail += 1
                continue
            row = {COLUMNS[i]: (vals[i] if i < len(vals) else None) for i in range(len(COLUMNS))}
            src = row.get("source") or "UNKNOWN"
            sources[src] += 1
            rows += 1
            for c in COLUMNS:
                if row.get(c) is None:
                    nulls[src][c] += 1
            det = row.get("detector")
            if det:
                if len(detectors[src]) < 200 or det in detectors[src]:
                    detectors[src][det] += 1
            tid = row.get("id")
            if tid and (len(ids[src]) < 400 or tid in ids[src]):
                ids[src][tid] += 1
            asn = row.get("aerial_sn")
            if asn and (len(aerial[src]) < 80 or asn in aerial[src]):
                aerial[src][asn] += 1
            h = to_float(row.get("heading"))
            if h is not None and (h < 0 or h >= 360):
                heading_odd[src] += 1
            alt = to_float(row.get("altitude"))
            if alt is not None and alt < 0:
                alt_neg[src] += 1
            ca = parse_dt(row.get("created_at"))
            ct = parse_dt(row.get("created_time"))
            if ca:
                time_min[src] = ca if src not in time_min else min(time_min[src], ca)
                time_max[src] = ca if src not in time_max else max(time_max[src], ca)
                hour_bins[src][ca.strftime("%Y-%m-%d")] += 1
            if ct:
                ctime_min[src] = ct if src not in ctime_min else min(ctime_min[src], ct)
                ctime_max[src] = ct if src not in ctime_max else max(ctime_max[src], ct)
            lat = to_float(row.get("latitude"))
            lon = to_float(row.get("longitude"))
            if lat is not None and lon is not None and len(latlon[src]["lat"]) < 2000:
                latlon[src]["lat"].append(lat)
                latlon[src]["lon"].append(lon)
            sd = row.get("source_data")
            if sd and json_parsed < args.json_parse_cap:
                json_parsed += 1
                keys = json_keys(sd)
                for k in keys:
                    sd_keys[k] += 1
                try:
                    obj = json.loads(sd)
                    sn = obj.get("sn") or obj.get("uavSn")
                    if sn:
                        sn_from_json[str(sn)[:80]] += 1
                except Exception:
                    pass
            compact = {
                "line_no": line_no,
                "id": row.get("id"),
                "source": src,
                "longitude": lon,
                "latitude": lat,
                "altitude": alt,
                "speed": to_float(row.get("speed")),
                "heading": row.get("heading"),
                "created_at": row.get("created_at"),
                "created_time": row.get("created_time"),
                "aerial_sn": row.get("aerial_sn"),
                "detector": row.get("detector"),
                "uav_type": row.get("uav_type"),
                "source_data": (sd[:1500] if isinstance(sd, str) else sd),
            }
            store = samples[src]
            seen = sample_seen[src]
            seen[0] += 1
            n = seen[0]
            if len(store) < args.per_source:
                store.append(compact)
            else:
                j = rng.randint(1, n)
                if j <= args.per_source:
                    store[j - 1] = compact
            if rows % 200000 == 0:
                print(f"progress rows={rows} line={line_no}", file=sys.stderr, flush=True)

    sample_dir = Path(args.sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)
    for src, items in samples.items():
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in src)
        outp = sample_dir / f"{safe}.jsonl"
        with outp.open("w", encoding="utf-8") as wf:
            for it in items:
                wf.write(json.dumps(it, ensure_ascii=False) + "\n")

    overlap = []
    src_list = sorted(time_min)
    for i, a in enumerate(src_list):
        for b in src_list[i + 1 :]:
            lo = max(time_min[a], time_min[b])
            hi = min(time_max[a], time_max[b])
            overlap.append({
                "a": a, "b": b,
                "overlap": lo <= hi,
                "overlap_start": lo.isoformat() if lo <= hi else None,
                "overlap_end": hi.isoformat() if lo <= hi else None,
            })

    bbox = {}
    for src, ll in latlon.items():
        if not ll["lat"]:
            continue
        bbox[src] = {
            "lat_min": min(ll["lat"]), "lat_max": max(ll["lat"]),
            "lon_min": min(ll["lon"]), "lon_max": max(ll["lon"]),
            "n_bbox_samples": len(ll["lat"]),
        }

    report = {
        "file": str(path),
        "size_bytes": st.st_size,
        "format": "navicat_plain_sql_insert",
        "scan": "full_insert_stream",
        "rows_parsed": rows,
        "parse_fail": parse_fail,
        "sources": sources.most_common(),
        "time_created_at": {k: {"min": time_min[k].isoformat(), "max": time_max[k].isoformat()} for k in time_min},
        "time_created_time": {k: {"min": ctime_min[k].isoformat(), "max": ctime_max[k].isoformat()} for k in ctime_min},
        "overlap_created_at": overlap,
        "nulls": {s: dict(c) for s, c in nulls.items()},
        "detectors_top": {s: d.most_common(20) for s, d in detectors.items()},
        "ids_top_capped": {s: d.most_common(15) for s, d in ids.items()},
        "aerial_sn_top": {s: d.most_common(15) for s, d in aerial.items()},
        "heading_out_of_range": dict(heading_odd),
        "altitude_negative": dict(alt_neg),
        "source_data_keys_sampled": sd_keys.most_common(50),
        "json_sn_sampled": sn_from_json.most_common(20),
        "json_parse_cap": args.json_parse_cap,
        "day_bins": {s: dict(sorted(c.items())[:40]) for s, c in hour_bins.items()},
        "bbox_sampled": bbox,
        "risky": {
            "drop_table": True,
            "source_host_in_header": "10.128.110.39:5433",
            "restore_only_isolated": True,
        },
    }
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "rows": rows, "sources": sources.most_common()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
