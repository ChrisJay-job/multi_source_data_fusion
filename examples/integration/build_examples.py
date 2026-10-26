#!/usr/bin/env python3
"""Write synthetic current-time integration requests. Never sends network traffic."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


def build(out: Path, tenant: str, site: str) -> dict:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    session = f"{tenant}-{site}-smoke-{stamp}"
    iso = lambda t: t.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def observation(i: int, time: datetime) -> dict:
        return {
            "observationId": f"obs-{stamp}-{i}",
            "source": "rid",
            "detectorId": "synthetic-rid-device-01",
            "sourceTrackId": "SN-SYNTHETIC-001",
            "aircraftId": "SN-SYNTHETIC-001",
            "measurementTime": iso(time),
            "receivedAt": iso(now),
            "timeBasis": "synthetic_test_only",
            "longitude": 118.3500 + i * 0.00005,
            "latitude": 35.1400 + i * 0.00002,
            "altitude": 80.0 + i,
            "altitudeDatum": "MSL",
            "speed": 5.0,
            "heading": 64.0,
            "qualityFlags": ["synthetic_test_only", "altitude_datum_not_verified"],
            "rawRef": {
                "snMappingVersion": "company_source_id_sn_v1",
                "altitudeMappingVersion": "database_altitude_msl_v1",
                "assumption": "USER_ASSUMED",
                "synthetic": True,
            },
        }

    historical = [observation(i, now - timedelta(seconds=4-i)) for i in range(3)]
    process = {
        "sessionId": session + "-http",
        "batchId": f"http-{stamp}-001",
        "mode": "realtime",
        "fusionProfile": "multisensor-3d-v1",
        "processingTime": iso(now),
        "observations": historical,
    }
    # Same process body must be reused on a transport retry; never rewrite its time.
    flush = {
        **process,
        "batchId": f"http-{stamp}-flush",
        "mode": "flush",
        "observations": [],
    }

    def envelope(kind: str, suffix: str, payload: dict) -> dict:
        return {
            "schemaVersion": "fusion-mqtt.v1",
            "messageType": kind,
            "messageId": f"{tenant}-{site}-{stamp}-{suffix}",
            "tenantId": tenant,
            "siteId": site,
            "sessionId": session + "-mqtt",
            "sentAt": iso(now),
            "payload": payload,
        }

    files = {
        "http-process.json": process,
        "http-flush.json": flush,
        "http-replay.json": {
            "jobId": session + "-replay",
            "fusionProfile": "multisensor-3d-v1",
            "observations": historical,
            "maxSnapshots": 1,
        },
        "mqtt-run-start.json": envelope("control", "start", {"action": "run.start"}),
        "mqtt-input.json": envelope("observations", "input", {
            "batchId": f"{tenant}-{site}-{stamp}-mqtt-b001",
            "fusionProfile": "multisensor-3d-v1",
            "mode": "realtime",
            "observations": [observation(0, now)],
        }),
        "mqtt-run-end.json": envelope("control", "end", {"action": "run.end"}),
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(out.resolve()), "sessionPrefix": session, "files": list(files), "networkSent": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("integration-smoke-requests"))
    parser.add_argument("--tenant", default="tenant-test")
    parser.add_argument("--site", default="site-test")
    args = parser.parse_args()
    print(json.dumps(build(args.out, args.tenant, args.site), ensure_ascii=False, indent=2))
