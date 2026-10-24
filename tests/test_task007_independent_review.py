"""Independent TASK-007 regressions. Run from a source checkout with PYTHONPATH=src.

Synthetic positions only. These tests do not use truth fields in algorithm input.
Capacity tests may be adapted to a documented pagination API after a fix; do not
remove the requirement to recover every committed point or reject atomically.
"""
from datetime import datetime, timedelta, timezone

from fusion_mvp.engine import load_config
from fusion_mvp.multisensor import MultisensorSession, replay_job

T = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)

def iso(t):
    return t.isoformat(timespec="microseconds")

def session(name):
    return MultisensorSession(name, load_config())

def row(s, oid, sec, x, *, local="L", detector="radar-01", scan=None, source="radar", sn=None):
    lat, lon = s.enu.to_ll(x, 0)
    return dict(observationId=oid, source=source, detectorId=detector,
                scanId=scan or f"s-{sec}", sourceTrackId=local, aircraftId=sn,
                measurementTime=iso(T + timedelta(seconds=sec)),
                longitude=lon, latitude=lat, speed=0, heading=None,
                positionStdM=1, objectClass="unknown")

def send(s, bid, sec, rows):
    return s.process(bid, iso(T + timedelta(seconds=sec)), rows, "realtime")

def test_r1_same_detector_two_targets_must_not_merge():
    s = session("r1-merge")
    for i in range(3):
        r = send(s, f"b{i}", i + 2.1, [
            row(s, f"a{i}", i, 0, local="A", scan=f"scan{i}"),
            row(s, f"b{i}", i, 20, local="B", scan=f"scan{i}"),
        ])
    assert r.error is None
    assert len(r.tracks) == 2, "Two independent same-scan targets collapsed into one"
    assert not any(e.type == "alias" for e in r.events)

def test_r1_complete_scan_remains_atomic_when_interleaved():
    s = session("r1-group")
    r = send(s, "b", 3, [
        row(s, "a", 0, 0, local="A", scan="complete-scan"),
        row(s, "rid", .005, 0, source="rid", detector="rid-01"),
        row(s, "b", .01, 20, local="B", scan="complete-scan"),
    ])
    assert r.error is None
    assert len(r.tracks) == 2
    for t in r.tracks:
        assert len([b for b in t.sourceTracks if b.detectorId == "radar-01"]) <= 1

def test_r2_stale_rid_falls_back_to_fresh_spectrum():
    s = session("r2-primary")
    fid = None
    for i in range(3):
        r = send(s, f"rid{i}", i + 2.1, [row(s, f"rid{i}", i, 0, source="rid", detector="rid-01", sn="SN-1")])
        fid = r.tracks[0].fusionId
    for i in range(3, 8):
        r = send(s, f"sp{i}", i + 2.1, [row(s, f"sp{i}", i, 10 * (i - 2), source="spectrum", detector="spectrum-01", sn="SN-1")])
    assert len(r.tracks) == 1 and r.tracks[0].fusionId == fid
    x, _ = s.enu.to_xy(r.tracks[0].latitude, r.tracks[0].longitude)
    assert x > 20, "Position stayed at old RID fix while fresh spectrum moved 50m"
    assert r.tracks[0].positionSource == "spectrum"

def test_r3_lost_target_reacquires_same_id_and_tracked_status():
    s = session("r3-return")
    for i in range(3):
        r = send(s, f"b{i}", i + 2.1, [row(s, f"a{i}", i, 0)])
    fid = r.tracks[0].fusionId
    r = send(s, "lost", 16, [])
    assert r.tracks[0].trackStatus == "lost"
    r = send(s, "return", 19.1, [row(s, "return", 17, 0)])
    assert not r.rejected and r.tracks[0].fusionId == fid
    assert r.tracks[0].trackStatus == "tracked"

def test_r4_600_committed_points_can_all_be_recovered():
    s = session("r4-history")
    rows = [row(s, f"p{i}", i * .01, 0) for i in range(600)]
    r = send(s, "b", 9, rows)
    if r.error is not None:
        assert s.seq == 0 and not s.tracks, "Capacity failure must roll back the batch"
        return
    assert not r.rejected
    points = r.trajectoryUpdates + [p for t in r.tracks for p in t.committedHistory]
    tick = send(s, "drain", 9.1, [])
    points += tick.trajectoryUpdates + [p for t in tick.tracks for p in t.committedHistory]
    found = {oid for p in points for oid in p["observationIds"]}
    expected = {p["observationId"] for p in rows}
    assert found == expected, f"Unrecoverable committed observations: {sorted(expected - found)}"

def test_r5_cache_respects_configured_bound():
    s = session("r5-memory")
    for i in range(205):
        r = send(s, f"b{i}", 2.1 + .1 * i, [row(s, f"a{i}", .1 * i, 0, local=None)])
        assert r.error is None
    assert len(s.cache) <= s.cfg["max_cache"]

def test_r6_offline_sorts_by_instant_not_timezone_spelling():
    s = session("r6-tz")
    a, b = row(s, "early", 0, 0), row(s, "later", 1, 0)
    a["measurementTime"] = "2026-10-24T09:00:00+08:00"
    b["measurementTime"] = "2026-10-24T01:00:01+00:00"
    r = replay_job(load_config(), "tz", [a, b], 2000)
    assert r.error is None
    assert {oid for p in r.trajectory for oid in p["observationIds"]} == {"early", "later"}

def test_r6_sampled_snapshots_preserve_final_state():
    s = session("r6-snapshot")
    rows = [row(s, f"p{i}", i, 0) for i in range(4)]
    r = replay_job(load_config(), "snapshot", rows, 1)
    assert r.error is None and len(r.snapshots) == 1
    final = datetime.fromisoformat(r.snapshots[-1]["tracks"][0]["lastObservedAt"])
    assert final == T + timedelta(seconds=3)

def test_r6_committed_time_preserves_input_microseconds():
    s = session("r6-precision")
    raw = row(s, "precise", .000123, 0)
    r = replay_job(load_config(), "precise", [raw], 2000)
    assert r.error is None and len(r.trajectory) == 1
    assert datetime.fromisoformat(r.trajectory[0]["stateTime"]) == datetime.fromisoformat(raw["measurementTime"])
