"""R6: pending future-anchor slots are not already-committed KF states."""
from datetime import datetime, timedelta, timezone

import pytest

from fusion_mvp.engine import load_config
from fusion_mvp.multisensor import MultisensorSession

T = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


def iso(sec):
    return (T + timedelta(seconds=sec)).isoformat(timespec="microseconds")


def row(s, oid, sec, x, *, detector="radar-01", scan=None, local="A", sn=None, speed=0, heading=None):
    lat, lon = s.enu.to_ll(x, 0)
    return dict(observationId=oid, source="rid" if detector.startswith("rid") else "radar",
                detectorId=detector, scanId=scan or oid, sourceTrackId=local,
                aircraftId=sn, measurementTime=iso(sec), longitude=lon, latitude=lat,
                positionStdM=1, speed=speed, heading=heading)


def send(s, batch, sec, rows):
    return s.process(batch, iso(sec), rows, "realtime")


def exercise(sn=None, speed=0):
    s = MultisensorSession(f"long-cold-{sn}-{speed}", load_config())
    def bx(sec):
        return 200 if speed == 0 else 100 + speed * sec
    responses = [send(s, "cold", 6.1, [
        row(s, "a", 0, 0, scan="long", local="A"),
        row(s, "b", 4, bx(4), scan="long", local="B", sn=sn, speed=speed, heading=90 if speed else None),
        row(s, "rid-b", 2, bx(2), detector="rid-01", scan="rid", local="b", sn=sn, speed=speed, heading=90 if speed else None),
    ])]
    for i in range(1, 5):
        sec = 4 + i
        responses.append(send(s, f"next{i}", sec + 2.1, [
            row(s, f"a{i}", sec, 0, scan=f"radar-{i}", local="A"),
            row(s, f"b{i}", sec, bx(sec), scan=f"radar-{i}", local="B", sn=sn, speed=speed, heading=90 if speed else None),
            row(s, f"rid-b{i}", sec + .01, bx(sec + .01), detector="rid-01", scan=f"rid-{i}", local="b", sn=sn, speed=speed, heading=90 if speed else None),
        ]))
    return s, responses


@pytest.mark.parametrize("sn", [None, "SN-B"], ids=["anonymous", "same-sn"])
def test_long_cold_scan_does_not_fragment_due_to_future_slot_timestamp(sn):
    _s, responses = exercise(sn=sn)
    assert all(r.error is None and not r.rejected for r in responses)
    last = responses[-1]
    confirmed = [t for t in last.tracks if t.trackStatus == "tracked"]
    assert len(confirmed) == 2, "Future slot t=4 rejected compatible observation t=2; duplicates never converged"
    assert len(last.tracks) == 2
    by_ref = {(b.detectorId, b.sourceTrackId): t.fusionId for t in confirmed for b in t.sourceTracks}
    assert by_ref[("radar-01", "A")] != by_ref[("radar-01", "B")]
    assert by_ref[("radar-01", "B")] == by_ref[("rid-01", "b")]
    if sn:
        assert len([t for t in last.tracks if t.aircraftId == sn]) == 1
    last_oids = {oid for p in last.trajectoryUpdates for oid in p["observationIds"]}
    # Identified primary-source policy may legitimately bind radar only.
    assert {"a4", "rid-b4"} <= last_oids
    if sn is None:
        assert "b4" in last_oids
    for response in responses:
        for track in response.tracks:
            times = [datetime.fromisoformat(p["stateTime"]) for p in track.committedHistory]
            assert times == sorted(times)


def test_pending_slot_motion_gate_compares_positions_at_the_same_instant():
    _s, responses = exercise(speed=50)
    assert all(r.error is None and not r.rejected for r in responses)
    last = responses[-1]
    confirmed = [t for t in last.tracks if t.trackStatus == "tracked"]
    assert len(confirmed) == 2, "Raw slot anchor distance blocked a valid 50m/s constant-velocity match"
    by_ref = {(b.detectorId, b.sourceTrackId): t.fusionId for t in confirmed for b in t.sourceTracks}
    assert by_ref[("radar-01", "B")] == by_ref[("rid-01", "b")]
    final_oids = {oid for p in last.trajectoryUpdates for oid in p["observationIds"]}
    assert {"a4", "b4", "rid-b4"} <= final_oids
