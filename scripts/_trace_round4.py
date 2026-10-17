"""Step traces for Round4 event-frontier: empty cutoff, source expiry, late reject."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fusion_mvp.engine import FusionSession, load_config


def ts(sec: float) -> str:
    return (datetime(2026, 4, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=sec)).isoformat()


def item(oid: str, t: float) -> dict:
    return dict(
        observationId=oid,
        source="rid",
        detectorId="D",
        sourceTrackId="R",
        aircraftId="SN",
        measurementTime=ts(t),
        receivedAt=ts(t),
        timeBasis="measurement",
        longitude=117.2,
        latitude=39.13,
        altitude=None,
        altitudeDatum="unknown",
        speed=None,
        heading=None,
        verticalSpeed=None,
        qualityFlags=[],
    )


def snap(resp):
    t0 = resp.tracks[0] if resp.tracks else None
    return {
        "batchId": resp.batchId,
        "watermark": resp.watermark,
        "error": resp.error,
        "lastObservedAt": t0.lastObservedAt if t0 else None,
        "positionMode": t0.positionMode if t0 else None,
        "sources": list(t0.sources) if t0 else [],
        "events": [e.type for e in resp.events],
        "rejected": [{"observationId": r.observationId, "reason": r.reason} for r in resp.rejected],
    }


def main() -> None:
    s = FusionSession("r4-trace", deepcopy(load_config()))
    steps = []
    for batch, pt, rows in [
        ("a", 1, [item("one", 1)]),
        ("flush", 3, []),
        ("empty", 10, []),
        ("old", 10, [item("old-two", 2)]),
    ]:
        r = s.process(batch, ts(pt), rows, "realtime")
        steps.append(snap(r) | {"processingTime": ts(pt), "n_obs": len(rows)})

    # Round3 delayed-in-window still holds under unified frontier
    s2 = FusionSession("r3-compat", deepcopy(load_config()))
    r3 = []
    for batch, pt, rows in [
        ("a", 1, [item("one", 1)]),
        ("empty", 3, []),
        ("b", 3.2, [item("two", 2.5)]),
        ("flush", 5, []),
    ]:
        r = s2.process(batch, ts(pt), rows, "realtime")
        r3.append(snap(r) | {"processingTime": ts(pt), "n_obs": len(rows)})

    out = {"r4_frontier": steps, "r3_delayed_compat": r3}
    path = Path("reports/rework_round4/r4_step_traces.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
