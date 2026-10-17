"""Extract a continuous single-source flight segment from the INSERT dump (streaming)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from fusion_mvp.sql_stream import iter_insert_rows  # noqa: E402
from fusion_mvp.mapping import normalize_row  # noqa: E402


def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace(" ", "T"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql", default=str(ROOT / "data" / "aircraft_flight_data.sql"))
    ap.add_argument("--source", default="tj-rid")
    ap.add_argument("--min-points", type=int, default=40)
    ap.add_argument("--max-gap-s", type=float, default=5.0)
    ap.add_argument("--scan-limit", type=int, default=200000)
    ap.add_argument("--out", default=str(ROOT / "samples" / "continuous" / "segment.jsonl"))
    args = ap.parse_args()

    # collect per-id sequences while streaming a bounded prefix for speed
    series = defaultdict(list)
    for line_no, row in iter_insert_rows(args.sql, sources={args.source}, limit=args.scan_limit):
        tid = row.get("id")
        t = parse_dt(row.get("created_at"))
        if not tid or not t:
            continue
        series[tid].append((t, line_no, row))

    best = None
    for tid, pts in series.items():
        pts.sort(key=lambda x: x[0])
        # find longest run with gap <= max_gap
        start = 0
        for i in range(1, len(pts) + 1):
            if i == len(pts) or (pts[i][0] - pts[i - 1][0]).total_seconds() > args.max_gap_s:
                run = pts[start:i]
                if len(run) >= args.min_points and (best is None or len(run) > len(best[1])):
                    best = (tid, run)
                start = i

    if not best:
        print(json.dumps({"ok": False, "reason": "no_segment"}, ensure_ascii=False))
        return 2

    tid, run = best
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "source": args.source,
        "sourceTrackId": tid,
        "n": len(run),
        "t0": run[0][0].isoformat(),
        "t1": run[-1][0].isoformat(),
        "line_nos": [p[1] for p in run[:5]] + ["..."] + [p[1] for p in run[-3:]],
        "scan_limit": args.scan_limit,
        "note": "continuous segment from bounded stream scan; not full-DB proof",
    }
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": meta}, ensure_ascii=False) + "\n")
        for t, line_no, row in run:
            obs, rej = normalize_row(row, file_tag="continuous", line_no=line_no)
            rec = {
                "line_no": line_no,
                "raw_ref": {"file": "data/aircraft_flight_data.sql", "line_no": line_no, "id": row.get("id"), "source": row.get("source")},
                "standard": None if obs is None else json.loads(obs.model_dump_json()),
                "reject": None if rej is None else rej.model_dump(),
            }
            # redact precise bulk: keep coords but mark as local evidence only
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": True, "out": str(out), **meta}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
