"""Replay continuous segment with delivered/buffered/processed/updated/rejected counters."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fusion_mvp.engine import FusionSession, load_config  # noqa: E402
from fusion_mvp.mapping import parse_dt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", default=str(ROOT / "samples" / "continuous" / "segment.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "rework_round1" / "continuous_replay.json"))
    ap.add_argument("--mode", default="realtime", choices=["realtime", "replay"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = []
    meta = {}
    for line in Path(args.segment).read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        if "_meta" in obj:
            meta = obj["_meta"]
            continue
        if obj.get("standard"):
            rows.append(obj)
    if args.limit:
        rows = rows[: args.limit]

    sess = FusionSession("continuous", load_config())
    stats = {
        "mode": args.mode,
        "delivered": 0,
        "buffered": 0,
        "processed": 0,
        "updated": 0,
        "rejected": 0,
        "reject_reasons": {},
        "snapshots": [],
    }
    for i, rec in enumerate(rows):
        std = rec["standard"]
        mt, _ = parse_dt(std["measurementTime"], allow_naive=False, assume_utc=False)
        if mt is None:
            mt, _ = parse_dt(std["measurementTime"], allow_naive=True, assume_utc=True)
        pt = std["measurementTime"]
        stats["delivered"] += 1
        before_hits = sum(t.hits for t in sess.tracks.values())
        before_wm = sess.event_watermark
        resp = sess.process(f"c-{i}", pt, [std], mode=args.mode)
        if resp.rejected:
            stats["rejected"] += len(resp.rejected)
            for r in resp.rejected:
                stats["reject_reasons"][r.reason] = stats["reject_reasons"].get(r.reason, 0) + 1

        after_hits = sum(t.hits for t in sess.tracks.values())
        committed_this = False
        if resp.tracks:
            lo, _ = parse_dt(resp.tracks[0].lastObservedAt, allow_naive=True, assume_utc=True)
            if lo is not None and mt is not None and lo == mt:
                committed_this = True
            if sess.event_watermark is not None and before_wm is not None and sess.event_watermark > before_wm:
                committed_this = True
            if before_wm is None and sess.event_watermark is not None:
                committed_this = True
        if after_hits > before_hits:
            stats["updated"] += 1
            stats["processed"] += 1
        elif committed_this:
            stats["processed"] += 1
        elif resp.rejected:
            pass
        else:
            stats["buffered"] += 1

        if i % max(1, len(rows) // 20) == 0 or i == len(rows) - 1:
            stats["snapshots"].append({
                "i": i,
                "line_no": rec.get("raw_ref", {}).get("line_no"),
                "watermark": resp.watermark,
                "event_watermark": None if sess.event_watermark is None else sess.event_watermark.isoformat(),
                "lastObservedAt": resp.tracks[0].lastObservedAt if resp.tracks else None,
                "fusionId": resp.tracks[0].fusionId if resp.tracks else None,
                "hits": after_hits,
                "positionMode": resp.tracks[0].positionMode if resp.tracks else None,
                "events": [e.type for e in resp.events],
            })

    out = {
        "meta": meta,
        "stats": stats,
        "note": (
            "Counters: delivered=requests fed; buffered=held in reorder window without hit increase; "
            "processed/updated=KF/hit advanced; rejected=explicit rejects. Not association accuracy."
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "delivered": stats["delivered"],
        "buffered": stats["buffered"],
        "processed": stats["processed"],
        "updated": stats["updated"],
        "rejected": stats["rejected"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
