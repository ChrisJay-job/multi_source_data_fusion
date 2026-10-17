"""Capture step traces for Round3 R3-01 / R3-02 after fix."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fusion_mvp.engine import FusionSession, load_config


def ts(t: float) -> str:
    return (datetime(2026, 4, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=t)).isoformat()


def obs(oid, t=1, source="rid", offset=0):
    return dict(
        observationId=oid,
        source=source,
        detectorId="D",
        sourceTrackId=source + "-T",
        aircraftId="SN-A",
        measurementTime=ts(t),
        receivedAt=ts(t),
        timeBasis="measurement",
        longitude=117.2 + offset,
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
        "positionSource": t0.positionSource if t0 else None,
        "longitude": t0.longitude if t0 else None,
        "latitude": t0.latitude if t0 else None,
        "events": [e.type for e in resp.events],
        "rejected": [r.reason for r in resp.rejected],
    }


def main() -> None:
    out: dict = {"r3_01": [], "r3_02": {}}

    s = FusionSession("empty-gap", deepcopy(load_config()))
    for batch, pt, rows in [
        ("a", 1, [obs("one", 1)]),
        ("empty", 3, []),
        ("b", 3.2, [obs("two", 2.5)]),
        ("flush", 5, []),
    ]:
        r = s.process(batch, ts(pt), rows, "realtime")
        out["r3_01"].append(snap(r) | {"processingTime": ts(pt), "n_obs": len(rows)})

    def run(items, label):
        sess = FusionSession("order-" + label, deepcopy(load_config()))
        r = sess.process("a", ts(1), items, "replay")
        return snap(r)

    rid = obs("rid")
    spectrum = obs("sp", source="spectrum", offset=0.0002)
    out["r3_02"]["rid_then_spectrum"] = run([rid, spectrum], "rs")
    out["r3_02"]["spectrum_then_rid"] = run([spectrum, rid], "sr")

    path = Path("reports/rework_round3/r3_step_traces.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
