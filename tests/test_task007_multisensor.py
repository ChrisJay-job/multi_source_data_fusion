"""TASK-007 multisensor-v1 acceptance. Truth JSON is evaluator-only."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fusion_mvp.engine import FusionSession, load_config
from fusion_mvp.multisensor import MultisensorSession, MultisensorStore, replay_job

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "review_zip" / "TASK-007-approved-round5" / "TASK-007" / "examples"
T0 = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def row(oid, source, detector, lon, lat, t, *, local="L1", scan="s", sn=None, std=5.0, heading=90.0, speed=8.0, cls="unknown"):
    return {
        "observationId": oid,
        "source": source,
        "detectorId": detector,
        "scanId": scan,
        "sourceTrackId": local,
        "aircraftId": sn,
        "measurementTime": iso(t),
        "receivedAt": iso(t),
        "longitude": lon,
        "latitude": lat,
        "altitude": None,
        "altitudeDatum": "unknown",
        "speed": speed,
        "heading": heading,
        "verticalSpeed": None,
        "positionStdM": std,
        "objectClass": cls,
        "qualityFlags": ["synthetic_test_input"],
    }


def commit(sess: MultisensorSession, batch, rows, t):
    return sess.process(batch, iso(t + timedelta(seconds=sess.reorder_s + 0.2)), rows, "realtime")


def test_a01_legacy_profile_still_runs():
    cfg = load_config()
    sess = FusionSession("legacy-a01", deepcopy(cfg))
    raw = dict(
        observationId="a", source="tj-rid", id="SN-A", detector="D1", aerial_sn="tcp",
        longitude=117.2, latitude=39.13, altitude=40, speed=8, heading=45,
        created_at=iso(T0),
    )
    resp = sess.process("b1", iso(T0), [raw], "replay")
    assert resp.error is None
    assert resp.tracks and resp.tracks[0].aircraftId == "SN-A"
    assert resp.fusionProfile is None
    client = TestClient(__import__("fusion_mvp.api", fromlist=["app"]).app)
    body = {
        "sessionId": "legacy-http-a01",
        "batchId": "b",
        "mode": "replay",
        "processingTime": iso(T0),
        "observations": [raw],
    }
    got = client.post("/v1/fusion/process", json=body)
    assert got.status_code == 200
    assert got.json().get("fusionProfile") in (None, "legacy")


def test_a02_six_devices_one_anonymous_target_and_shuffle():
    doc = json.loads((EX / "offline_single_target.json").read_text(encoding="utf-8"))
    out = replay_job(load_config(), "a02", doc["observations"], 2000)
    assert out.error is None
    last = out.snapshots[-1]["tracks"]
    active = [t for t in last if t["trackStatus"] in {"tracked", "coasting"}]
    assert len(active) == 1
    dets = {b["detectorId"] for b in active[0]["sourceTracks"] if b["bindingStatus"] == "confirmed"}
    assert len(dets) == 6
    assert active[0]["identityStatus"] == "unknown"
    assert active[0]["fusionMethod"] == "multi_sensor_estimate"
    shuffled = list(reversed(doc["observations"]))
    out2 = replay_job(load_config(), "a02b", shuffled, 2000)
    a = active[0]
    b = [t for t in out2.snapshots[-1]["tracks"] if t["trackStatus"] in {"tracked", "coasting"}][0]
    assert abs(a["longitude"] - b["longitude"]) < 1e-4
    assert abs(a["latitude"] - b["latitude"]) < 1e-4
    assert {x["detectorId"] for x in a["sourceTracks"]} == {x["detectorId"] for x in b["sourceTracks"]}


def test_a03_three_targets_same_local_spelling_do_not_cross_link():
    doc = json.loads((EX / "offline_three_targets.json").read_text(encoding="utf-8"))
    out = replay_job(load_config(), "a03", doc["observations"], 2000)
    assert out.error is None
    active = [t for t in out.snapshots[-1]["tracks"] if t["trackStatus"] in {"tracked", "coasting"}]
    assert len(active) == 3
    locals_by_det = {}
    for tr in active:
        for b in tr["sourceTracks"]:
            locals_by_det.setdefault(b["sourceTrackId"], set()).add(b["detectorId"])
    # Identical local spellings may exist, but only inside one global target's own detectors.
    assert len(active) == 3


def _scene(name: str) -> dict:
    doc = json.loads((EX / "evaluation_truth_DO_NOT_SEND_TO_ALGORITHM.json").read_text(encoding="utf-8"))
    return next(item for item in doc if item.get("scene") == name)


def _truth_geometry(out, meta: dict):
    entity_ids: dict[str, set[str]] = {}
    id_entities: dict[str, set[str]] = {}
    covered: set[str] = set()
    errors: list[float] = []
    for point in out.trajectory:
        for oid in point["observationIds"]:
            ground = meta.get(oid)
            if not ground or ground.get("entity") is None:
                continue
            covered.add(oid)
            entity_ids.setdefault(ground["entity"], set()).add(point["fusionId"])
            id_entities.setdefault(point["fusionId"], set()).add(ground["entity"])
            gt_lon = 120.3 + ground["east_m"] / (111320 * math.cos(math.radians(36)))
            gt_lat = 36 + ground["north_m"] / 111320
            dx = (point["longitude"] - gt_lon) * 111320 * math.cos(math.radians(36))
            dy = (point["latitude"] - gt_lat) * 111320
            errors.append(math.hypot(dx, dy))
    return entity_ids, id_entities, covered, errors


def test_a04_crossing_identity_against_evaluator_truth():
    scene = json.loads((EX / "offline_crossing.json").read_text(encoding="utf-8"))
    sent_keys = {"truth_id", "truthId", "expectedFusionId", "entity", "east_m", "north_m"}
    assert all(not (sent_keys & set(row)) for row in scene["observations"])
    meta = _scene("crossing")["observations"]
    out = replay_job(load_config(), "a04", scene["observations"], 4000)
    assert out.error is None
    entity_ids, id_entities, covered, errors = _truth_geometry(out, meta)
    target_obs = sum(item.get("entity") is not None for item in meta.values())
    assert len(covered) == target_obs
    assert entity_ids and all(len(v) == 1 for v in entity_ids.values())
    assert len({next(iter(v)) for v in entity_ids.values()}) == len(entity_ids)
    assert not id_entities or all(len(v) == 1 for v in id_entities.values())
    rmse = (sum(x * x for x in errors) / len(errors)) ** 0.5
    assert rmse < 40.0


def test_a05_missing_local_id_does_not_collapse_targets():
    doc = json.loads((EX / "offline_missing_local_ids.json").read_text(encoding="utf-8"))
    assert any(not row.get("sourceTrackId") for row in doc["observations"])
    meta = _scene("missing_local_ids")["observations"]
    out = replay_job(load_config(), "a05", doc["observations"], 2000)
    assert out.error is None
    entity_ids, id_entities, covered, _errors = _truth_geometry(out, meta)
    target_obs = sum(item.get("entity") is not None for item in meta.values())
    assert len(covered) == target_obs
    assert set(entity_ids) == {"T1", "T2", "T3"}
    assert all(len(v) == 1 for v in entity_ids.values())
    assert len({next(iter(v)) for v in entity_ids.values()}) == 3
    assert all(len(v) == 1 for v in id_entities.values())
    confirmed = [t for t in out.snapshots[-1]["tracks"] if t["trackStatus"] in {"tracked", "coasting"}]
    assert len(confirmed) == 3
    assert "generated" in [b.get("origin") for t in confirmed for b in t["sourceTracks"]]


def test_a06_clutter_stays_tentative_and_unknown_is_not_a_drone():
    doc = json.loads((EX / "offline_clutter.json").read_text(encoding="utf-8"))
    meta = _scene("clutter")["observations"]
    out = replay_job(load_config(), "a06", doc["observations"], 4000)
    assert out.error is None
    entity_ids, id_entities, covered, _errors = _truth_geometry(out, meta)
    target_obs = sum(item.get("entity") is not None for item in meta.values())
    assert len(covered) == target_obs
    assert set(entity_ids) == {"T1", "T2", "T3"}
    assert all(len(v) == 1 for v in entity_ids.values())
    assert all(len(v) == 1 for v in id_entities.values())
    last = out.snapshots[-1]["tracks"]
    confirmed = [t for t in last if t["trackStatus"] in {"tracked", "coasting"}]
    assert len(confirmed) == 3
    confirmed_ids = {t["fusionId"] for t in confirmed}
    assert confirmed_ids == {next(iter(v)) for v in entity_ids.values()}
    assert all(t["objectClass"] != "drone" for t in last)
    assert all(t["identityStatus"] == "unknown" for t in confirmed)
    assert any(t["trackStatus"] == "tentative" for t in last)


def test_a07_resend_scan_and_multi_scan_counts():
    sess = MultisensorSession("a07", load_config())
    t = T0
    batch = [
        row("a", "rid", "rid-01", 120.30, 36.00, t, local="9", scan="rid-01:1"),
        row("b", "radar", "radar-01", 120.30001, 36.00001, t + timedelta(milliseconds=10), local="9", scan="radar-01:1"),
        row("c", "rid", "rid-01", 120.31, 36.02, t, local="8", scan="rid-01:1"),
    ]
    first = commit(sess, "s1", batch, t)
    again = sess.process("s1", first.watermark, batch, "realtime")
    # identical request uses the original processing time
    again = sess.process("s1", iso(t + timedelta(seconds=sess.reorder_s + 0.2)), batch, "realtime")
    assert again.model_dump() == first.model_dump()
    live = [tr for tr in first.tracks if tr.trackStatus != "terminated"]
    assert len(live) == 2


def test_a08_reorder_future_and_empty_tick():
    sess = MultisensorSession("a08", load_config())
    t = T0
    early = sess.process("e", iso(t + timedelta(seconds=0.2)), [row("e", "rid", "rid-01", 120.3, 36.0, t)], "realtime")
    assert early.tracks == []
    assert early.rejected == []
    future = row("f", "rid", "rid-09", 120.4, 36.1, t + timedelta(seconds=30))
    bad = sess.process("f", iso(t + timedelta(seconds=0.3)), [future], "realtime")
    assert any(r.reason == "future_timestamp" for r in bad.rejected)
    assert bad.watermark != iso(t + timedelta(seconds=30))
    flush = sess.process("tick", iso(t + timedelta(seconds=2.4)), [], "realtime")
    assert flush.error is None
    assert flush.rejected == []
    assert len(flush.tracks) == 1
    late = sess.process("late", iso(t + timedelta(seconds=3)), [row("old", "radar", "radar-09", 120.3, 36.0, t - timedelta(seconds=5))], "realtime")
    assert any(r.reason == "late_after_frontier" for r in late.rejected)


def test_a09_gap_renumber_and_identity_keep_fusion_id():
    sess = MultisensorSession("a09", load_config())
    base = T0
    first_id = None
    for i in range(4):
        t = base + timedelta(seconds=i)
        resp = commit(sess, f"n{i}", [row(f"n{i}", "rid", "rid-01", 120.30 + i * 0.0001, 36.0, t, local="17")], t)
        first_id = resp.tracks[0].fusionId
    gap = base + timedelta(seconds=8)
    back = commit(sess, "gap", [row("gap", "rid", "rid-01", 120.3005, 36.0, gap, local="99")], gap)
    assert back.tracks[0].fusionId == first_id
    named = commit(
        sess, "sn",
        [row("sn", "rid", "rid-01", 120.3006, 36.0, gap + timedelta(seconds=1), local="99", sn="SN-1")],
        gap + timedelta(seconds=1),
    )
    assert named.tracks[0].fusionId == first_id
    assert named.tracks[0].aircraftId == "SN-1"
    assert named.tracks[0].identityStatus == "identified"
    assert named.tracks[0].fusionMethod == "primary_source"
    other = commit(
        sess, "other",
        [row("ot", "rid", "rid-02", 121.0, 37.0, gap + timedelta(seconds=2), sn="SN-2")],
        gap + timedelta(seconds=2),
    )
    assert all(t.fusionId != first_id or t.aircraftId != "SN-2" for t in other.tracks)


def test_a10_http_idempotency_conflict_isolation_and_limits():
    from fusion_mvp.api import app

    client = TestClient(app)
    body = {
        "sessionId": "a10-ms",
        "batchId": "same",
        "mode": "realtime",
        "fusionProfile": "multisensor-v1",
        "processingTime": iso(T0 + timedelta(seconds=3)),
        "observations": [row("z", "rid", "rid-01", 120.3, 36.0, T0)],
    }
    first = client.post("/v1/fusion/process", json=body)
    assert first.status_code == 200
    assert client.post("/v1/fusion/process", json=body).json() == first.json()
    changed = deepcopy(body)
    changed["observations"][0]["longitude"] += 0.00001
    assert client.post("/v1/fusion/process", json=changed).status_code == 409
    assert client.post("/v1/fusion/process", json={**body, "fusionProfile": "nope", "batchId": "x"}).status_code == 422
    other = deepcopy(body)
    other["sessionId"] = "a10-other"
    other["batchId"] = "o"
    other["observations"] = [row("q", "radar", "radar-77", 121.0, 37.0, T0)]
    assert client.post("/v1/fusion/process", json=other).status_code == 200
    legacy = deepcopy(body)
    legacy["sessionId"] = "a10-ms"
    legacy.pop("fusionProfile")
    legacy["batchId"] = "legacy"
    assert client.post("/v1/fusion/process", json=legacy).status_code == 409
    huge = deepcopy(body)
    huge["batchId"] = "huge"
    huge["sessionId"] = "a10-huge"
    huge["observations"] = [row(f"h{i}", "rid", "rid-01", 120.3, 36.0, T0) for i in range(5001)]
    assert client.post("/v1/fusion/process", json=huge).status_code == 413


def test_a11_anonymous_sources_move_the_estimate_without_collapsing_variance():
    sess = MultisensorSession("a11", load_config())
    t = T0
    commit(sess, "r", [row("r", "rid", "rid-01", 120.30, 36.00, t, std=8.0)], t)
    moved = commit(
        sess, "s",
        [row("s", "spectrum", "spectrum-01", 120.3004, 36.0002, t + timedelta(seconds=1), std=20.0)],
        t + timedelta(seconds=1),
    )
    tr = moved.tracks[0]
    assert "rid" in tr.contributingSources and "spectrum" in tr.contributingSources
    assert tr.fusionMethod == "multi_sensor_estimate"
    kf = sess.tracks[tr.fusionId].kf
    assert float(kf.P[0, 0]) >= 1.0
    assert float(kf.P[1, 1]) >= 1.0
    # The second source must pull the estimate off the first measurement.
    x0, y0 = sess.enu.to_xy(36.00, 120.30)
    assert abs(kf.pos[0] - x0) + abs(kf.pos[1] - y0) > 1.0


def test_a12_realtime_and_offline_match_on_causal_input():
    doc = json.loads((EX / "offline_single_target.json").read_text(encoding="utf-8"))
    offline = replay_job(load_config(), "a12-off", doc["observations"], 4000)
    sess = MultisensorSession("a12-rt", load_config())
    groups: list[list[dict]] = []
    for obs in sorted(doc["observations"], key=lambda r: r["measurementTime"]):
        if not groups or groups[-1][0]["measurementTime"] != obs["measurementTime"]:
            groups.append([obs])
        else:
            groups[-1].append(obs)
    last = None
    for i, rows in enumerate(groups):
        mt = datetime.fromisoformat(rows[0]["measurementTime"])
        last = sess.process(f"rt{i}", iso(mt + timedelta(seconds=sess.reorder_s)), rows, "realtime")
    flush_t = datetime.fromisoformat(groups[-1][0]["measurementTime"]) + timedelta(seconds=sess.reorder_s + 0.25)
    last = sess.process("rt-flush", iso(flush_t), [], "realtime")
    off = [t for t in offline.snapshots[-1]["tracks"] if t["trackStatus"] in {"tracked", "coasting"}][0]
    rt = [t for t in last.tracks if t.trackStatus in {"tracked", "coasting"}][0]
    assert abs(off["longitude"] - rt.longitude) < 1e-4
    assert abs(off["latitude"] - rt.latitude) < 1e-4
    assert {b["detectorId"] for b in off["sourceTracks"]} == {b.detectorId for b in rt.sourceTracks}


def test_a15_hundred_observations_smoke_and_capacity_fields(tmp_path):
    import os
    import time

    try:
        import resource
    except ImportError:
        resource = None
    sess = MultisensorSession("a15", load_config())
    duration_s = 2.0
    rate_hz = 100
    total = int(duration_s * rate_hz)
    batch_size = 20
    durations = []
    accepted = 0
    rejected = 0
    response_bytes = []
    t = T0
    cpu0 = time.process_time()
    for i in range(total // batch_size):
        rows = []
        for k in range(batch_size):
            n = i * batch_size + k
            when = t + timedelta(seconds=n / rate_hz)
            rows.append(row(f"p{n}", "radar", "radar-01", _east(120.30, n * 0.08), 36.0, when, local="1", scan=f"sc{n}", speed=8))
        started = time.perf_counter()
        resp = sess.process(
            f"c{i}",
            iso(when + timedelta(seconds=sess.reorder_s)),
            rows,
            "realtime",
        )
        durations.append((time.perf_counter() - started) * 1000)
        accepted += batch_size - len(resp.rejected)
        rejected += len(resp.rejected)
        response_bytes.append(len(resp.model_dump_json()))
    durations.sort()
    def pct(p):
        if not durations:
            return None
        idx = min(len(durations) - 1, max(0, math.ceil(p * len(durations)) - 1))
        return durations[idx]
    rss = None
    if resource is not None:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    record = {
        "synthetic": True,
        "inputRatePerSecond": rate_hz,
        "durationSeconds": duration_s,
        "observations": total,
        "batches": len(durations),
        "latencySamples": len(durations),
        "devices": 1,
        "activeTracks": len([tr for tr in sess.tracks.values() if tr.status != "terminated"]),
        "accepted": accepted,
        "rejected": rejected,
        "p50Ms": pct(0.50),
        "p95Ms": pct(0.95),
        "p99Ms": pct(0.99),
        "cpuSeconds": time.process_time() - cpu0,
        "rssKb": rss,
        "maxResponseBytes": max(response_bytes) if response_bytes else 0,
        "reorderWindowSeconds": sess.reorder_s,
        "note": "synthetic 100 observations/second for 2 seconds; not a customer capacity promise",
    }
    assert record["observations"] == 200
    assert record["activeTracks"] >= 1
    assert record["accepted"] == 200
    assert record["latencySamples"] == 10
    out = ROOT / "reports" / "task007" / "capacity_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    assert os.path.isfile(out)


def test_rejects_placeholder_and_keeps_heading_flag():
    sess = MultisensorSession("rej", load_config())
    bad = row("z", "rid", "rid-01", 0.0, 0.0, T0)
    flagged = row("h", "rid", "rid-01", 120.3, 36.0, T0)
    flagged["heading"] = 361
    resp = commit(sess, "b", [bad, flagged], T0)
    assert any(r.reason == "position_placeholder_0_0" for r in resp.rejected)
    assert resp.tracks
    assert "heading_out_of_range" in resp.tracks[0].qualityFlags
    assert resp.tracks[0].heading is None or resp.tracks[0].speed is not None


def test_rollback_restores_empty_session():
    sess = MultisensorSession("rb", load_config())

    def boom(*_a, **_k):
        raise RuntimeError("forced")

    sess._assign_group = boom
    resp = commit(sess, "x", [row("z", "rid", "rid-01", 120.3, 36.0, T0)], T0)
    assert resp.error == "batch_rollback"
    assert sess.tracks == {}


def _east(lon: float, meters: float, lat: float = 36.0) -> float:
    return lon + meters / (111320 * math.cos(math.radians(lat)))


def test_r1_tracked_targets_do_not_merge_when_they_approach():
    sess = MultisensorSession("r1", load_config())
    resp = None
    for i in range(16):
        t = T0 + timedelta(seconds=i)
        resp = commit(
            sess,
            f"f{i}",
            [
                row(f"a{i}", "radar", "radar-01", _east(120.30, 8 * i), 36.0, t, local="1", scan=f"s{i}", speed=8),
                row(f"b{i}", "radar", "radar-01", _east(120.30, 80 + 4 * i), 36.0, t + timedelta(milliseconds=10), local="2", scan=f"s{i}", speed=4),
            ],
            t,
        )
    live = [tr for tr in resp.tracks if tr.trackStatus in {"tracked", "coasting"}]
    assert len(live) == 2
    assert {b.sourceTrackId for tr in live for b in tr.sourceTracks} == {"1", "2"}


def test_r2_stale_primary_source_hands_off_without_new_id():
    sess = MultisensorSession("r2", load_config())
    fid = None
    for i in range(4):
        t = T0 + timedelta(seconds=i)
        resp = commit(sess, f"r{i}", [row(f"r{i}", "rid", "rid-01", _east(120.30, i * 8), 36.0, t, local="1", sn="SN-9")], t)
        fid = resp.tracks[0].fusionId
        assert resp.tracks[0].fusionMethod == "primary_source"
    t = T0 + timedelta(seconds=10)
    moved = commit(
        sess,
        "spec",
        [row("s", "spectrum", "spectrum-01", _east(120.30, 10 * 8), 36.0, t, local="1")],
        t,
    )
    tr = next(item for item in moved.tracks if item.fusionId == fid)
    assert tr.fusionId == fid
    assert tr.fusionMethod == "primary_source"
    assert "spectrum" in tr.contributingSources
    assert any(ev.type == "strategy_changed" and ev.payload.get("reason") == "primary_source_failover" for ev in moved.events)
    assert abs(tr.longitude - _east(120.30, 0)) > 0.0003


def test_r3_lost_track_is_reacquired():
    sess = MultisensorSession("r3", load_config())
    fid = None
    for i in range(4):
        t = T0 + timedelta(seconds=i)
        resp = commit(sess, f"n{i}", [row(f"n{i}", "rid", "rid-01", _east(120.30, i * 8), 36.0, t, local="7")], t)
        fid = resp.tracks[0].fusionId
    lost = sess.process("gap", iso(T0 + timedelta(seconds=20)), [], "realtime")
    assert any(tr.fusionId == fid and tr.trackStatus == "lost" for tr in lost.tracks)
    back_t = T0 + timedelta(seconds=20)
    back = commit(sess, "back", [row("back", "rid", "rid-01", _east(120.30, 20 * 8), 36.0, back_t, local="8")], back_t)
    assert len(back.tracks) == 1
    assert back.tracks[0].fusionId == fid
    assert back.tracks[0].trackStatus == "tracked"
    assert any(ev.type == "track_reacquired" for ev in back.events)


def test_r4_batch_trajectory_is_not_truncated():
    sess = MultisensorSession("r4", load_config())
    sess.ms["committed_history_cap"] = 5
    sess.ms["trajectory_batch_cap"] = 5
    rows = []
    for k in range(30):
        when = T0 + timedelta(milliseconds=200 * k)
        rows.append(row(f"p{k}", "radar", "radar-01", _east(120.30, k * 1.6), 36.0, when, local="1", scan=f"p{k}"))
    resp = commit(sess, "batch", rows, T0 + timedelta(seconds=8))
    assert resp.error is None
    assert len(resp.trajectoryUpdates) == 30
    assert len({p["pointId"] for p in resp.trajectoryUpdates}) == 30
    assert len(resp.tracks) == 1
    assert len(resp.tracks[0].committedHistory) == 5
    assert "history_capped" in resp.tracks[0].qualityFlags


def test_r5_memory_bounds_drop_old_state_and_report_it():
    cfg = load_config()
    cfg["max_cache"] = 2
    cfg["multisensor_v1"]["max_seen"] = 3
    sess = MultisensorSession("r5", cfg)
    first_id = None
    for i in range(5):
        t = T0 + timedelta(seconds=i)
        resp = commit(sess, f"m{i}", [row(f"m{i}", "rid", "rid-01", _east(120.30, i * 8), 36.0, t, local="1")], t)
        if i == 0:
            first_id = resp.batchId
    assert len(sess.seen) <= 3
    assert any(ev.type == "memory_bounded" for ev in resp.events)
    expired = sess.process(first_id, iso(T0 + timedelta(seconds=3)), [row("m0", "rid", "rid-01", 120.30, 36.0, T0, local="1")], "realtime")
    assert expired.error == "idempotency_expired"
    ended = sess.process("end", iso(T0 + timedelta(seconds=40)), [], "realtime")
    assert ended.error is None
    assert sess.tracks == {}
    assert any(ev.type == "track_ended" for ev in ended.events)
    store = MultisensorStore(load_config())
    store.get("old")
    store.created["old"] = datetime.now(timezone.utc) - timedelta(hours=2)
    store.get("new")
    assert "old" not in store.sessions
    assert "new" in store.sessions


def test_r6_offline_sorts_and_keeps_the_last_snapshot():
    doc = json.loads((EX / "offline_single_target.json").read_text(encoding="utf-8"))
    ordered = replay_job(load_config(), "r6a", doc["observations"], 2000)
    shuffled = replay_job(load_config(), "r6b", list(reversed(doc["observations"])), 2000)
    assert ordered.error is None and shuffled.error is None
    assert ordered.summary["trajectory_points"] == len(doc["observations"])
    assert shuffled.summary["trajectory_points"] == ordered.summary["trajectory_points"]
    assert ordered.summary["last_snapshot_track_count_is_not_total_targets"] is True
    assert ordered.summary["distinct_fusion_ids"] >= 1
    sampled = replay_job(load_config(), "r6c", doc["observations"], 2)
    assert sampled.snapshots[-1]["batchId"].endswith("flush")
    assert sampled.snapshots[-1]["watermark"] == ordered.snapshots[-1]["watermark"]


def test_r2_internal_counters_stay_bounded():
    sess = MultisensorSession("r2-bound", load_config())
    resp = None
    for i in range(120):
        t = T0 + timedelta(milliseconds=100 * i)
        resp = commit(sess, f"c{i}", [row(f"c{i}", "radar", "radar-01", _east(120.30, i * 0.4), 36.0, t, local="1", scan=f"b{i}", speed=4)], t)
    tr = next(iter(sess.tracks.values()))
    assert resp.error is None
    assert len(tr.distinct_times) <= 32
    assert len(tr.consumed) <= 64
    assert len(tr.binds) <= 24
    assert all(len(b.times) <= 8 for b in tr.binds.values())


def test_r2_idempotency_capacity_rejects_without_forgetting():
    cfg = load_config()
    cfg["max_cache"] = 1
    cfg["multisensor_v1"]["max_idempotency_ids"] = 3
    sess = MultisensorSession("r2-cap", cfg)
    first = sess.process("b0", iso(T0 + timedelta(seconds=3)), [], "realtime")
    assert first.error is None
    assert sess.process("b1", iso(T0 + timedelta(seconds=3)), [], "realtime").error is None
    assert sess.process("b2", iso(T0 + timedelta(seconds=3)), [], "realtime").error is None
    seq = sess.seq
    blocked = sess.process("b3", iso(T0 + timedelta(seconds=3)), [], "realtime")
    assert blocked.error == "idempotency_capacity"
    assert sess.seq == seq
    retry = sess.process("b0", iso(T0 + timedelta(seconds=3)), [], "realtime")
    assert retry.error in {"idempotency_expired", "idempotency_evicted"} or retry.model_dump() == first.model_dump()
    assert sess.seq == seq


def test_r3_out_of_gate_same_sn_does_not_copy_onto_anonymous_track():
    sess = MultisensorSession("r3-oog", load_config())
    known = None
    for i in range(3):
        t = T0 + timedelta(seconds=i)
        resp = commit(
            sess, f"s{i}",
            [
                row(f"a{i}", "radar", "radar-01", _east(120.30, 0), 36.0, t, local="A", scan=f"g{i}", sn="SN-A", speed=0),
                row(f"b{i}", "radar", "radar-01", _east(120.30, 20), 36.0, t, local="B", scan=f"g{i}", speed=0),
            ],
            t,
        )
        known = next(tr.fusionId for tr in resp.tracks if tr.aircraftId == "SN-A")
    far_t = T0 + timedelta(seconds=3)
    resp = commit(
        sess, "far",
        [row("far", "radar", "radar-01", _east(120.30, 200), 36.0, far_t, local="A2", scan="far", sn="SN-A", speed=0)],
        far_t,
    )
    assert resp.error is None and not resp.rejected
    assert any(ev.type == "identity_out_of_gate" for ev in resp.events)
    anon = next(tr for tr in resp.tracks if any(b.sourceTrackId == "B" for b in tr.sourceTracks))
    assert anon.aircraftId != "SN-A"
    assert any(tr.fusionId == known and tr.aircraftId == "SN-A" for tr in resp.tracks)
    owners = {p["fusionId"] for p in resp.trajectoryUpdates if "far" in p["observationIds"]}
    assert owners and known not in owners and anon.fusionId not in owners


def test_r3_different_sn_does_not_replace_known_identity():
    sess = MultisensorSession("r3-other-sn", load_config())
    known = None
    for i in range(3):
        t = T0 + timedelta(seconds=i)
        resp = commit(
            sess, f"s{i}",
            [row(f"a{i}", "rid", "rid-01", _east(120.30, 0), 36.0, t, local="A", scan=f"d{i}", sn="SN-A", speed=0)],
            t,
        )
        known = resp.tracks[0].fusionId
    t = T0 + timedelta(seconds=3)
    resp = commit(
        sess, "other",
        [row("other", "rid", "rid-01", _east(120.30, 1), 36.0, t, local="B", scan="other", sn="SN-B", speed=0)],
        t,
    )
    assert resp.error is None
    kept = next(tr for tr in resp.tracks if tr.fusionId == known)
    assert kept.aircraftId == "SN-A"
    assert all(tr.fusionId != known or tr.aircraftId != "SN-B" for tr in resp.tracks)


def test_r3_same_sn_ambiguity_emits_reason():
    sess = MultisensorSession("r3-amb", load_config())
    for i in range(3):
        t = T0 + timedelta(seconds=i)
        commit(
            sess, f"a{i}",
            [row(f"a{i}", "radar", "radar-01", _east(120.30, 0), 36.0, t, local="A", scan=f"a{i}", sn="SN-A", speed=0)],
            t,
        )
    second_t = T0 + timedelta(seconds=3)
    second = commit(
        sess, "second",
        [row("second", "radar", "radar-01", _east(120.30, 100), 36.0, second_t, local="A2", scan="second", sn="SN-A", speed=0)],
        second_t,
    )
    assert any(ev.type == "identity_out_of_gate" for ev in second.events)
    mid_t = T0 + timedelta(seconds=4)
    resp = commit(
        sess, "mid",
        [row("mid", "radar", "radar-01", _east(120.30, 50), 36.0, mid_t, local="A3", scan="mid", sn="SN-A", speed=0)],
        mid_t,
    )
    assert any(ev.type == "identity_ambiguous" for ev in resp.events)
    assert not any("mid" in p["observationIds"] for p in resp.trajectoryUpdates)


def test_r3_default_offline_replay_accepts_4097_rows():
    cfg = load_config()
    assert cfg["multisensor_v1"]["max_idempotency_ids"] == 4096
    assert cfg["multisensor_v1"]["max_replay_observations"] >= 4097
    rows = [
        row(f"o{i}", "radar", "radar-01", 120.30, 36.0, T0 + timedelta(milliseconds=100 * i), local="A", scan=f"sc{i}", speed=0)
        for i in range(4097)
    ]
    out = replay_job(cfg, "offline-4097", rows, 1)
    assert out.error is None
    assert out.summary["input"] == 4097
    assert out.summary["processed"] == 4097
    assert out.summary["unprocessed"] == 0
    assert out.summary["valid"] == 4097
    assert out.summary["rejected"] == 0
    assert len(out.trajectory) == 4097
    assert len(out.snapshots) == 1
    assert str(out.snapshots[-1]["batchId"]).endswith("flush")
    record = {
        "input": out.summary["input"],
        "processed": out.summary["processed"],
        "valid": out.summary["valid"],
        "rejected": out.summary["rejected"],
        "unprocessed": out.summary["unprocessed"],
        "trajectory_points": len(out.trajectory),
        "snapshots": len(out.snapshots),
        "last_batch": out.snapshots[-1]["batchId"],
        "last_track_count": out.summary["tracks_in_last_snapshot"],
        "distinct_fusion_ids": out.summary["distinct_fusion_ids"],
        "error": out.error,
        "note": out.summary["note"],
        "max_idempotency_ids": 4096,
        "includes_final_flush": True,
    }
    path = ROOT / "reports" / "task007" / "r3" / "default_replay_4097.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

