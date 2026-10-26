"""R1-01/R1-02/R1-03 altitude semantics and mapping."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from fusion_mvp.api import app
from fusion_mvp.kalman import ConstantVelocity1D
import numpy as np
from fusion_mvp.multisensor import PROFILE_3D, MultisensorSession
from fusion_mvp.workbench.altitude_mapping import apply_database_altitude_msl_v1
from fusion_mvp.workbench.importer import MappingTemplate, import_tabular
from fusion_mvp.integration.schemas import build_result


CFG = yaml.safe_load(open("config/fusion.yaml", encoding="utf-8"))
T0 = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def obs(oid: str, t: datetime, alt, *, datum="MSL", src="rid", det="D-rid"):
    row = {
        "observationId": oid,
        "source": src,
        "detectorId": det,
        "sourceTrackId": "L1",
        "aircraftId": "SN-A",
        "measurementTime": iso(t),
        "receivedAt": iso(t),
        "longitude": 118.7,
        "latitude": 37.45,
        "speed": 0.0,
        "heading": 90.0,
        "positionStdM": 8.0,
    }
    if alt is not None:
        row["altitude"] = alt
        row["altitudeDatum"] = datum
    return row


def test_r1_01_predict_then_expire_without_stale_paste():
    sess = MultisensorSession("r1-01", CFG, profile=PROFILE_3D)
    r0 = sess.process("b0", iso(T0 + timedelta(seconds=2)), [obs("a0", T0, 100.0)], "realtime")
    assert r0.error is None
    r1 = sess.process("b1", iso(T0 + timedelta(seconds=3)), [obs("a1", T0 + timedelta(seconds=1), 110.0)], "realtime")
    assert r1.error is None
    # t2: horizontal only — expect predicted ~110, not glued prior filtered mean
    r2 = sess.process("b2", iso(T0 + timedelta(seconds=4)), [obs("a2", T0 + timedelta(seconds=2), None)], "realtime")
    assert r2.error is None
    p2 = r2.trajectoryUpdates[0]
    assert p2["altitudeMode"] == "predicted"
    assert p2["altitude"] is not None
    assert abs(p2["altitude"] - 110.0) < 5.0
    # t10 beyond horizon 4s from last altitude obs at t1 → expired/null
    r10 = sess.process(
        "b10", iso(T0 + timedelta(seconds=12)), [obs("a10", T0 + timedelta(seconds=10), None)], "realtime"
    )
    assert r10.error is None
    p10 = r10.trajectoryUpdates[0]
    assert p10["altitude"] is None
    assert p10["altitudeMode"] == "expired"


def test_r1_01_unsupported_datum_not_in_snapshot():
    sess = MultisensorSession("r1-01b", CFG, profile=PROFILE_3D)
    r = sess.process(
        "b0",
        iso(T0 + timedelta(seconds=2)),
        [obs("e1", T0, 123.0, datum="ELLIPSOID")],
        "realtime",
    )
    assert r.error is None
    assert any(e.type == "altitude_datum_unsupported" for e in r.events)
    assert r.trajectoryUpdates[0]["altitude"] is None
    assert r.tracks[0].altitude is None
    assert r.tracks[0].altitudeDatum is None


def test_r1_01_analytic_kf_mean_cov():
    # Independent of session: equal R and prior variance → midpoint; P shrinks.
    kf = ConstantVelocity1D(0.0, q_pos=0.0, q_vel=0.0, r=4.0)
    assert abs(kf.P[0, 0] - 4.0) < 1e-12
    innov = kf.update(10.0, 4.0)
    assert abs(innov - 10.0) < 1e-12
    assert abs(kf.alt - 5.0) < 1e-9
    assert kf.P[0, 0] < 4.0


def test_r1_02_mqtt_and_replay_keep_altitude_updates():
    sess = MultisensorSession("r1-02", CFG, profile=PROFILE_3D)
    rows = [
        obs("r1", T0, 100.0, src="rid", det="RID1"),
        obs("r2", T0 + timedelta(milliseconds=20), 101.0, src="rid", det="RID1"),
    ]
    sess.process("b1", iso(T0 + timedelta(seconds=2)), rows, "realtime")
    r2 = sess.process(
        "b2",
        iso(T0 + timedelta(seconds=3)),
        [obs("s1", T0 + timedelta(seconds=1), 110.0, src="spectrum", det="PP1")],
        "realtime",
    )
    assert r2.altitudeUpdates, r2.model_dump()
    payload = build_result(
        message_id="m1",
        tenant_id="t",
        site_id="s",
        session_id="r1-02",
        process_response=r2.model_dump(mode="json"),
        evidence_index={"s1": {"observationId": "s1", "altitude": 110.0}},
    )
    assert "altitudeUpdates" in payload["payload"]
    assert payload["payload"]["altitudeUpdates"]
    assert any(
        (e.get("role") == "altitude_update")
        for u in payload["payload"]["altitudeUpdates"]
        for e in u.get("evidence") or []
    )
    # Replay path also retains altitudeUpdates on ReplayResponse / snapshots.
    from fusion_mvp.multisensor import replay_job

    replayed = replay_job(
        CFG,
        "r1-02-replay",
        rows + [obs("s1", T0 + timedelta(seconds=1), 110.0, src="spectrum", det="PP1")],
        max_snapshots=50,
        fusion_profile=PROFILE_3D,
    )
    assert replayed.altitudeUpdates
    assert any(s.get("altitudeUpdates") for s in (replayed.snapshots or []))


def test_r1_03_importer_msl_mapping_for_3d_csv():
    csv_path = Path("samples/task007/5_rid_pp5_leida1_simp.csv")
    if not csv_path.is_file():
        return
    tmpl = MappingTemplate(altitude_mapping_version="database_altitude_msl_v1", source_timezone="Asia/Shanghai")
    summary = import_tabular(csv_path, tmpl, max_rows=20)
    obs_list = summary.get("observations") or []
    assert obs_list
    with_alt = [o for o in obs_list if o.get("altitude") is not None]
    assert with_alt
    assert all(o.get("altitudeDatum") == "MSL" for o in with_alt)
    # legacy path keeps unknown when mapping disabled
    raw = apply_database_altitude_msl_v1(
        {"altitude": 1.0, "altitudeDatum": "unknown", "qualityFlags": []}, enabled=False
    )
    assert raw["altitudeDatum"] == "unknown"


def test_r1_03_http_import_3d_maps_altitude():
    client = TestClient(app)
    csv_path = Path("samples/task007/5_rid_pp5_leida1_simp.csv")
    if not csv_path.is_file():
        return
    # Use local path API
    body = {
        "path": str(csv_path).replace("\\", "/"),
        "mode": "replay",
        "fusionProfile": PROFILE_3D,
        "maxRows": 30,
        "mapping": {"source_timezone": "Asia/Shanghai"},
    }
    # Prefer local-preview + run/import if path resolver accepts samples/
    resp = client.post("/v1/workbench/run/import", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("fusionProfile") == PROFILE_3D
    obs_list = data.get("observations") or []
    with_alt = [o for o in obs_list if o.get("altitude") is not None][:20]
    assert with_alt
    assert all(o.get("altitudeDatum") == "MSL" for o in with_alt)
    tracks = data.get("final_tracks") or []
    # At least some fused altitude or altitudeUpdates when mapped MSL present
    assert tracks or data.get("altitudeUpdates") is not None
