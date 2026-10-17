"""Replay sampled real rows through fusion core. No full dump load."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fusion_mvp.engine import FusionSession, load_config  # noqa: E402
from fusion_mvp.mapping import normalize_row  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(ROOT / "samples" / "real"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "real_replay.json"))
    ap.add_argument("--sources", default="tj-rid,tj-pp,tj-leida")
    args = ap.parse_args()
    cfg = load_config()
    sess = FusionSession("real-replay", cfg)
    wanted = set(args.sources.split(","))
    rows = []
    for src in wanted:
        p = Path(args.samples) / f"{src}.jsonl"
        if p.exists():
            rows.extend(load_jsonl(p))
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    accepted = rejected = 0
    batches = 0
    tracks_peak = 0
    reasons = {}
    for i, row in enumerate(rows):
        obs, rej = normalize_row(row, file_tag="sample", line_no=int(row.get("line_no") or i))
        payload = row
        if obs is None:
            rejected += 1
            reasons[rej.reason if rej else "unknown"] = reasons.get(rej.reason if rej else "unknown", 0) + 1
            continue
        # feed as raw dict so API path same as normalize inside engine
        raw = {
            "observationId": obs.observationId,
            "source": row.get("source"),
            "id": row.get("id"),
            "detector": obs.detectorId,
            "aerial_sn": row.get("aerial_sn"),
            "longitude": row.get("longitude"),
            "latitude": row.get("latitude"),
            "altitude": row.get("altitude"),
            "speed": row.get("speed"),
            "heading": row.get("heading"),
            "created_at": row.get("created_at"),
            "created_time": row.get("created_time"),
            "source_data": row.get("source_data"),
            "uav_type": row.get("uav_type"),
        }
        pt = str(row.get("created_at"))
        if "T" not in pt and " " in pt:
            pt = pt.replace(" ", "T") + "+00:00"
        elif "+" not in pt and "Z" not in pt:
            pt = pt + "+00:00"
        resp = sess.process(f"rb-{i}", pt, [raw], mode="replay")
        batches += 1
        accepted += 1
        rejected += len(resp.rejected)
        for r in resp.rejected:
            reasons[r.reason] = reasons.get(r.reason, 0) + 1
        tracks_peak = max(tracks_peak, len(resp.tracks))
    summary = {
        "rows_input": len(rows),
        "batches": batches,
        "accepted_fed": accepted,
        "rejected": rejected,
        "reject_reasons": reasons,
        "tracks_peak": tracks_peak,
        "final_tracks": [
            {
                "fusionId": t.fusionId,
                "aircraftId": t.aircraftId,
                "sources": t.sources,
                "status": t.trackStatus,
                "positionMode": t.positionMode,
            }
            for t in sess.process("final", "2099-01-01T00:00:00+00:00", [], mode="replay").tracks
        ],
        "note": "真实样本无同步真值；不报告关联准确率。仅解析率/拒绝原因/航迹行为。",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, **{k: summary[k] for k in ("rows_input", "rejected", "tracks_peak")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
