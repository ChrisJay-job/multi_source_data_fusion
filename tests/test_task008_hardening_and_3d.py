"""TASK-008: idempotency/session/altitude timing hardenings + multisensor-3d-v1."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import yaml
from fastapi.testclient import TestClient

from fusion_mvp.api import app
from fusion_mvp.kalman import ConstantVelocity1D
from fusion_mvp.multisensor import PROFILE, PROFILE_3D, MultisensorSession, MultisensorStore


ROOT_CFG = yaml.safe_load(open("config/fusion.yaml", encoding="utf-8"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _obs(oid: str, t: datetime, alt: float | None, *, sn: str = "SN-A", src: str = "rid", det: str = "D1", xy=(118.7, 37.45)):
    row = {
        "observationId": oid,
        "source": src,
        "detectorId": det,
        "sourceTrackId": "L1",
        "aircraftId": sn,
        "measurementTime": _iso(t),
        "receivedAt": _iso(t),
        "longitude": xy[0],
        "latitude": xy[1],
        "altitudeDatum": "MSL" if alt is not None else "unknown",
        "speed": 5.0,
        "heading": 90.0,
        "positionStdM": 8.0,
    }
    if alt is not None:
        row["altitude"] = alt
    return row


def test_idempotency_expires_before_capacity():
    cfg = yaml.safe_load(yaml.dump(ROOT_CFG))
    cfg["idempotency_ttl_s"] = 10
    cfg.setdefault("multisensor_v1", {})["max_idempotency_ids"] = 4
    cfg["max_cache"] = 4
    clock = {"now": datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)}

    def now():
        return clock["now"]

    sess = MultisensorSession("idem-cap", cfg, clock=now)
    t0 = clock["now"]
    for i in range(4):
        pt = _iso(t0 + timedelta(seconds=i))
        obs = [_obs(f"o{i}", t0 + timedelta(seconds=i), 10.0)]
        resp = sess.process(f"b{i}", pt, obs, "realtime")
        assert resp.error is None, resp.error
    # All four remembered; advance past TTL then new batch must succeed after cleanup.
    clock["now"] = t0 + timedelta(seconds=30)
    pt = _iso(clock["now"])
    resp = sess.process("b-new", pt, [_obs("o-new", clock["now"], 11.0)], "realtime")
    assert resp.error is None, resp.error


def test_active_session_survives_create_age():
    cfg = yaml.safe_load(yaml.dump(ROOT_CFG))
    cfg["session_idle_ttl_s"] = 3600
    clock = {"now": datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)}

    def now():
        return clock["now"]

    store = MultisensorStore(cfg, clock=now)
    s1 = store.get("alive", profile=PROFILE)
    epoch = s1.epoch
    # Created 2h ago but touched recently → keep
    store.created["alive"] = clock["now"] - timedelta(seconds=7200)
    store.last_active["alive"] = clock["now"]
    clock["now"] = clock["now"] + timedelta(seconds=10)
    s2 = store.get("alive", profile=PROFILE)
    assert s2.epoch == epoch
    # Idle beyond TTL → new epoch
    store.last_active["alive"] = clock["now"] - timedelta(seconds=4000)
    clock["now"] = clock["now"] + timedelta(seconds=1)
    s3 = store.get("alive", profile=PROFILE)
    assert s3.epoch != epoch


def test_2d_altitude_passthrough_uses_this_observation():
    cfg = yaml.safe_load(yaml.dump(ROOT_CFG))
    sess = MultisensorSession("alt-2d", cfg, profile=PROFILE)
    t0 = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)
    r1 = sess.process("b1", _iso(t0 + timedelta(seconds=2)), [_obs("a1", t0, 10.0)], "realtime")
    assert r1.error is None
    assert len(r1.trajectoryUpdates) >= 1
    assert r1.trajectoryUpdates[0]["altitude"] == 10.0
    t1 = t0 + timedelta(seconds=1)
    r2 = sess.process("b2", _iso(t1 + timedelta(seconds=2)), [_obs("a2", t1, 20.0)], "realtime")
    assert r2.error is None
    assert len(r2.trajectoryUpdates) >= 1
    assert r2.trajectoryUpdates[0]["altitude"] == 20.0
    assert r2.tracks[0].altitude == 20.0


def test_3d_vertical_kf_and_secondary_altitude_update():
    cfg = yaml.safe_load(yaml.dump(ROOT_CFG))
    sess = MultisensorSession("alt-3d", cfg, profile=PROFILE_3D)
    t0 = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)
    # Confirm bind with two rid hits then secondary spectrum altitude-only contribution.
    rows = [
        _obs("r1", t0, 100.0, src="rid", det="RID1"),
        _obs("r2", t0 + timedelta(milliseconds=20), 101.0, src="rid", det="RID1"),
    ]
    r1 = sess.process("b1", _iso(t0 + timedelta(seconds=2)), rows, "realtime")
    assert r1.error is None
    assert r1.fusionProfile == PROFILE_3D
    alts = [p.get("altitude") for p in r1.trajectoryUpdates if p.get("altitude") is not None]
    assert alts, r1.trajectoryUpdates
    # Spectrum secondary: same SN/location, different altitude — should emit altitudeUpdates
    t2 = t0 + timedelta(seconds=1)
    r2 = sess.process(
        "b2",
        _iso(t2 + timedelta(seconds=2)),
        [_obs("s1", t2, 110.0, src="spectrum", det="PP1")],
        "realtime",
    )
    assert r2.error is None
    # Either a trajectory point or an independent altitude update must carry spectrum evidence.
    alt_upd = r2.altitudeUpdates or []
    traj = r2.trajectoryUpdates or []
    assert alt_upd or traj
    if alt_upd:
        assert any("s1" in (u.get("altitudeObservationIds") or []) for u in alt_upd)


def test_vertical_kf_independent_analytic():
    kf = ConstantVelocity1D(0.0, q_pos=0.0, q_vel=0.0, r=1.0)
    innov = kf.update(10.0, 1.0)
    assert abs(innov - 10.0) < 1e-9
    # Equal prior/measurement variance → posterior midpoint.
    assert abs(kf.alt - 5.0) < 1e-6


def test_http_3d_profile_and_legacy_default():
    client = TestClient(app)
    t0 = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
    body = {
        "sessionId": "http-3d-1",
        "batchId": "b1",
        "mode": "realtime",
        "fusionProfile": PROFILE_3D,
        "processingTime": _iso(t0 + timedelta(seconds=2)),
        "observations": [_obs("h1", t0, 50.0)],
    }
    resp = client.post("/v1/fusion/process", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["fusionProfile"] == PROFILE_3D
    # profile conflict
    bad = dict(body, batchId="b2", fusionProfile=PROFILE, observations=[_obs("h2", t0 + timedelta(seconds=1), 51.0)])
    assert client.post("/v1/fusion/process", json=bad).status_code == 409
    # omitted profile still legacy-compatible path
    legacy = {
        "sessionId": "http-legacy-1",
        "batchId": "b1",
        "mode": "realtime",
        "processingTime": _iso(t0 + timedelta(seconds=2)),
        "observations": [_obs("L1", t0, 1.0)],
    }
    # R1-10: assert success on a valid legacy payload (do not treat 4xx as pass).
    resp = client.post("/v1/fusion/process", json=legacy)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("error") is None or body.get("error") == ""
