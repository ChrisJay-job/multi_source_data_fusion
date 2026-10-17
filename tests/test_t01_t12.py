from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fusion_mvp.engine import FusionSession, load_config
from fusion_mvp.mapping import normalize_row


CFG = load_config()
T0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)


def ts(sec: float) -> str:
    return (T0 + timedelta(seconds=sec)).isoformat()


def rid(oid, sn, xoff, yoff, t, det="tcp"):
    return {
        "observationId": oid,
        "source": "tj-rid",
        "id": sn,
        "detector": det,
        "aerial_sn": "tcp",
        "longitude": 117.20 + xoff,
        "latitude": 39.13 + yoff,
        "altitude": 40,
        "speed": 8,
        "heading": "90",
        "created_at": ts(t),
    }


def spec(oid, sn, xoff, yoff, t, det="30"):
    return {
        "observationId": oid,
        "source": "tj-pp",
        "id": sn,
        "detector": det,
        "longitude": 117.20 + xoff,
        "latitude": 39.13 + yoff,
        "altitude": 12,
        "speed": 8,
        "heading": "45",
        "created_at": ts(t),
        "source_data": {"sn": sn, "deviceId": int(det) if str(det).isdigit() else 1, "trackTime": ts(t).replace("+00:00", "").replace("T", " ")[:19], "az": 45, "courseAngle": 0},
    }


def radar(oid, tid, xoff, yoff, t, det="25040"):
    return {
        "observationId": oid,
        "source": "tj-leida",
        "id": tid,
        "detector": det,
        "longitude": 117.20 + xoff,
        "latitude": 39.13 + yoff,
        "altitude": 50,
        "speed": 10,
        "heading": "90",
        "created_at": ts(t),
    }


def run(obs, session="s1", batch="b1", tproc=None, mode="replay"):
    sess = FusionSession(session, CFG)
    last = None
    for i, item in enumerate(obs):
        pt = tproc or item.get("created_at") or ts(i)
        last = sess.process(f"{batch}-{i}", pt, [item], mode=mode)
    return sess, last


def test_t01_same_sn_associate_diff_sn_not():
    sess = FusionSession("t01", CFG)
    r1 = sess.process("1", ts(1), [rid("o1", "SN-A", 0, 0, 1)], "replay")
    s1 = sess.process("2", ts(1.2), [spec("o2", "SN-A", 0.0002, 0, 1.2)], "replay")
    ids = {t.aircraftId: t.fusionId for t in s1.tracks}
    assert "SN-A" in ids
    assert len([t for t in s1.tracks if t.aircraftId == "SN-A"]) == 1
    r2 = sess.process("3", ts(1.3), [rid("o3", "SN-B", 0.01, 0.01, 1.3)], "replay")
    sns = {t.aircraftId for t in r2.tracks}
    assert "SN-A" in sns and "SN-B" in sns
    assert len(r2.tracks) >= 2


def test_t02_radar_two_targets_not_merged():
    sess = FusionSession("t02", CFG)
    sess.process("1", ts(1), [radar("a", "r-1", 0, 0, 1)], "replay")
    out = sess.process("2", ts(1.1), [radar("b", "r-2", 0.02, 0, 1.1)], "replay")
    live = [t for t in out.tracks if t.trackStatus != "terminated"]
    assert len(live) == 2


def test_t03_radar_then_rid_keeps_id_or_alias():
    sess = FusionSession("t03", CFG)
    a = sess.process("1", ts(1), [radar("a", "rad-1", 0, 0, 1)], "replay")
    fid = a.tracks[0].fusionId
    b = sess.process("2", ts(1.4), [rid("b", "SN-C", 0.0001, 0, 1.4)], "replay")
    assert len(b.tracks) == 1
    assert b.tracks[0].aircraftId == "SN-C"
    assert b.tracks[0].fusionId == fid
    assert set(b.tracks[0].sources) == {"radar", "rid"}


def test_t04_crossing_not_forced():
    sess = FusionSession("t04", CFG)
    sess.process("1", ts(1), [radar("a", "x1", 0, 0, 1)], "replay")
    sess.process("2", ts(1), [radar("b", "x2", 0.00015, 0, 1)], "replay")
    out = sess.process("3", ts(2), [
        radar("c", "x1", 0.00015, 0, 2),
        radar("d", "x2", 0, 0, 2),
    ], "replay")
    assert out.error is None
    live = [t for t in out.tracks if t.trackStatus != "terminated"]
    assert len(live) == 2
    ids = {t.fusionId for t in live}
    assert len(ids) == 2


def test_t05_predict_does_not_refresh_last_obs():
    sess = FusionSession("t05", CFG)
    a = sess.process("1", ts(1), [rid("o", "SN-P", 0, 0, 1)], "replay")
    last = a.tracks[0].lastObservedAt
    b = sess.process("2", ts(3), [], "replay")
    tr = [t for t in b.tracks if t.aircraftId == "SN-P"][0]
    assert tr.lastObservedAt == last
    assert tr.positionMode in ("predicted", "stale")
    c = sess.process("3", ts(20), [], "replay")
    moving = [t for t in c.tracks if t.aircraftId == "SN-P" and t.positionMode == "predicted"]
    assert moving == []


def test_t06_radar_reid():
    sess = FusionSession("t06", CFG)
    a = sess.process("1", ts(1), [radar("a", "old", 0, 0, 1)], "replay")
    fid = a.tracks[0].fusionId
    b = sess.process("2", ts(3), [radar("b", "new", 0.0002, 0, 3)], "replay")
    assert len(b.tracks) == 1
    assert b.tracks[0].fusionId == fid
    assert any(st.sourceTrackId == "new" for st in b.tracks[0].sourceTracks)


def test_t07_rid_stale_then_resume():
    sess = FusionSession("t07", CFG)
    sess.process("1", ts(1), [rid("a", "SN-R", 0, 0, 1)], "replay")
    sess.process("2", ts(2), [radar("b", "rr", 0.0001, 0, 2)], "replay")
    mid = sess.process("3", ts(6), [radar("c", "rr", 0.0003, 0, 6)], "replay")
    assert len(mid.tracks) == 1
    assert mid.tracks[0].positionSource == "radar"
    assert "rid" not in mid.tracks[0].sources
    back = sess.process("4", ts(6.2), [rid("d", "SN-R", 0.00031, 0, 6.2)], "replay")
    tr = [t for t in back.tracks if t.aircraftId == "SN-R"]
    assert len(tr) == 1
    assert tr[0].positionSource == "rid"


def test_t08_idempotent_and_partial_reject():
    sess = FusionSession("t08", CFG)
    payload = [rid("dup", "SN-D", 0, 0, 1)]
    a = sess.process("same", ts(1), payload, "replay")
    b = sess.process("same", ts(1), payload, "replay")
    assert a.snapshotSeq == b.snapshotSeq
    c = sess.process("same", ts(1), [rid("dup2", "SN-D", 0, 0, 1)], "replay")
    assert c.error == "batch_id_conflict"
    d = sess.process("mix", ts(2), [rid("ok", "SN-E", 0, 0, 2), {"source": "nope", "id": "x"}], "replay")
    assert d.error is None
    assert d.rejected
    assert any(t.aircraftId == "SN-E" for t in d.tracks)


def test_t09_reorder_and_late_reject():
    sess = FusionSession("t09", CFG)
    sess.process("1", ts(5), [rid("latewin", "SN-F", 0, 0, 4.5)], "realtime")
    out = sess.process("2", ts(10), [rid("toolate", "SN-F", 0, 0, 1)], "realtime")
    assert any(r.reason == "late_beyond_reorder_window" for r in out.rejected)
    empty = sess.process("3", ts(10.5), [], "realtime")
    assert empty.watermark


def test_t10_degraded_heading_alt():
    row = rid("h", "SN-H", 0, 0, 1)
    row["heading"] = "361"
    row["altitude"] = -2
    obs, rej = normalize_row(row)
    assert rej is None
    assert obs.heading is None
    assert "heading_out_of_range" in obs.qualityFlags
    assert "altitude_datum_unknown" in obs.qualityFlags
    sess = FusionSession("t10", CFG)
    out = sess.process("1", ts(1), [row], "replay")
    assert out.tracks


def test_t11_session_isolation_and_epoch():
    s1 = FusionSession("iso-a", CFG)
    s2 = FusionSession("iso-b", CFG)
    s1.process("1", ts(1), [rid("a", "SN-I", 0, 0, 1)], "replay")
    b = s2.process("1", ts(1), [rid("b", "SN-J", 0, 0, 1)], "replay")
    assert all(t.aircraftId != "SN-I" for t in b.tracks)
    e1 = s1.epoch
    s3 = FusionSession("iso-a", CFG)
    assert s3.epoch != e1
    s3.process("1", ts(1), [rid("c", "SN-I", 0, 0, 1)], "replay")
    assert s3.tracks[list(s3.tracks)[0]].fusionId != list(s1.tracks)[0]


def test_t12_same_time_multi_target_and_multi_detector():
    sess = FusionSession("t12", CFG)
    out = sess.process("1", ts(1), [
        radar("a", "t1", 0, 0, 1, det="d1"),
        radar("b", "t2", 0.01, 0, 1, det="d1"),
        spec("c", "SN-M", 0, 0, 1, det="80"),
    ], "replay")
    assert len(out.tracks) == 2
    fused = [t for t in out.tracks if "radar" in t.sources and "spectrum" in t.sources]
    assert len(fused) == 1
    assert fused[0].aircraftId == "SN-M"
