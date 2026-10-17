"""Small perf smoke: synthetic multi-target load. Separates wall time only (no buffer wait)."""
from __future__ import annotations

import json
import platform
import resource
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fusion_mvp.engine import FusionSession, load_config  # noqa: E402

T0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)


def main() -> int:
    cfg = load_config()
    sess = FusionSession("perf", cfg)
    n_targets = 20
    n_steps = 50
    times = []
    for step in range(n_steps):
        t = T0 + timedelta(seconds=step)
        obs = []
        for i in range(n_targets):
            lon = 117.20 + i * 0.01 + step * 0.00001
            lat = 39.13 + (i % 5) * 0.01
            obs.append({
                "observationId": f"p-{step}-{i}",
                "source": "tj-leida",
                "id": f"R{i}",
                "detector": "25040",
                "longitude": lon,
                "latitude": lat,
                "altitude": 50,
                "speed": 10,
                "heading": "90",
                "created_at": t.isoformat(),
            })
            if i % 3 == 0:
                obs.append({
                    "observationId": f"rid-{step}-{i}",
                    "source": "tj-rid",
                    "id": f"SN{i}",
                    "detector": "tcp",
                    "aerial_sn": "tcp",
                    "longitude": lon,
                    "latitude": lat,
                    "altitude": 50,
                    "speed": 10,
                    "heading": "90",
                    "created_at": t.isoformat(),
                })
        t0 = time.perf_counter()
        sess.process(f"pb-{step}", t.isoformat(), obs, mode="replay")
        times.append((time.perf_counter() - t0) * 1000)
    times_sorted = sorted(times)
    p50 = times_sorted[len(times_sorted) // 2]
    p95 = times_sorted[int(len(times_sorted) * 0.95)]
    try:
        peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux KB; macOS bytes — report raw with unit note
        peak_note = f"{peak_rss_kb} (ru_maxrss platform-dependent unit)"
    except Exception:
        peak_note = "n/a"
    out = {
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        "scenario": {
            "targets": n_targets,
            "sources_per_step_approx": "radar+partial_rid",
            "steps": n_steps,
            "obs_rate": f"~{n_targets * 1.3:.0f}/s synthetic",
            "duration_s": n_steps,
        },
        "process_batch_ms": {"p50": round(p50, 3), "p95": round(p95, 3), "max": round(max(times), 3)},
        "note": "纯算法批处理墙钟；无 HTTP/乱序缓冲等待。未承诺准确率或延迟 SLA。",
        "peak_rss": peak_note,
    }
    path = ROOT / "reports" / "performance.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["process_batch_ms"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
