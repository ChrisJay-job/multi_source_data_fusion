"""Independent R5 checks for constraints introduced by R4 slots/reservations."""
from datetime import datetime, timedelta, timezone

from fusion_mvp.engine import load_config
from fusion_mvp.multisensor import MultisensorSession

T = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


def iso(sec):
    return (T + timedelta(seconds=sec)).isoformat(timespec="microseconds")


def row(s, oid, sec, x, *, detector="radar-01", scan=None, local="A", sn=None, speed=0, heading=None):
    lat, lon = s.enu.to_ll(x, 0)
    return dict(
        observationId=oid, source="rid" if detector.startswith("rid") else "radar",
        detectorId=detector, scanId=scan or oid, sourceTrackId=local,
        aircraftId=sn, measurementTime=iso(sec), longitude=lon, latitude=lat,
        positionStdM=1, speed=speed, heading=heading,
    )


def send(s, batch, sec, rows):
    return s.process(batch, iso(sec), rows, "realtime")


def owners(response, observation_id):
    return {p["fusionId"] for p in response.trajectoryUpdates if observation_id in p["observationIds"]}


def test_pending_slot_respects_different_trusted_sn_before_identity_attachment():
    s = MultisensorSession("slot-sn", load_config())
    r = send(s, "cold", 4, [
        row(s, "a", 0, 200, scan="long", local="A"),
        row(s, "snA", 1.2, 0, scan="long", local="B", sn="SN-A"),
        row(s, "snB", .6, 20, detector="rid-01", scan="rid", local="b", sn="SN-B"),
    ])
    assert r.error is None and not r.rejected
    by_sn = {t.aircraftId: t.fusionId for t in r.tracks if t.aircraftId}
    assert set(by_sn) == {"SN-A", "SN-B"}, "Pending SN-A slot was filled by SN-B and later kept only SN-B with conflict"
    assert by_sn["SN-A"] != by_sn["SN-B"]
    assert len(r.tracks) == 3
    assert owners(r, "snA") == {by_sn["SN-A"]}
    assert owners(r, "snB") == {by_sn["SN-B"]}
    assert not any(t.identityStatus == "conflict" for t in r.tracks)


def test_pending_slot_respects_existing_opposite_heading_gate():
    s = MultisensorSession("slot-heading", load_config())
    r = send(s, "cold", 4, [
        row(s, "a", 0, 200, scan="long", local="A"),
        row(s, "east", 1.2, 12, scan="long", local="E", speed=10, heading=90),
        row(s, "west", .6, 6, detector="rid-01", scan="rid", local="W", speed=10, heading=270),
    ])
    assert r.error is None and not r.rejected
    assert len(r.tracks) == 3
    assert owners(r, "east") and owners(r, "west")
    assert not owners(r, "east") & owners(r, "west"), "Slot bypassed 70-degree heading gate and fused opposite movers"


def test_multiple_same_sn_rows_cannot_force_the_same_scan_column_twice():
    s = MultisensorSession("forced-duplicate", load_config())
    for i in range(3):
        r = send(s, f"seed{i}", i + 2.1, [row(s, f"a{i}", i, 0, sn="SN-A")])
        assert r.error is None
    r = send(s, "collision", 5.1, [
        row(s, "left", 3, 0, scan="same", local="L", sn="SN-A"),
        row(s, "right", 3, 20, scan="same", local="R", sn="SN-A"),
    ])
    assert r.error is None
    # Duplicate/ambiguous SN may be quarantined, rejected with a reason, or
    # represented by distinct candidates. It cannot defeat scan one-to-one.
    assert not owners(r, "left") & owners(r, "right"), "Two forced SN rows claimed one global column in the same scan"
    represented = {oid for p in r.trajectoryUpdates for oid in p["observationIds"]}
    rejected = {q.observationId for q in r.rejected}
    if {"left", "right"} - represented - rejected:
        assert any(e.type in {"identity_ambiguous", "identity_conflict", "scan_conflict", "association_ambiguous"} for e in r.events)


def test_overlapping_held_spans_preserve_whole_scan_transitively():
    s = MultisensorSession("overlap", load_config())
    responses = [send(s, "hold", 2.1, [
        row(s, "a0", 0, 0, scan="R1", local="A"),
        row(s, "b3", 3, 20, scan="R1", local="B"),
        row(s, "rid1", 1, 200, detector="rid-01", scan="R2", local="C"),
        row(s, "rid4", 4, 400, detector="rid-01", scan="R2", local="D"),
    ])]
    responses.append(send(s, "tick1", 5.1, []))
    responses.append(send(s, "tick2", 6.1, []))
    assert all(r.error is None and not r.rejected for r in responses)
    mapping = {}
    for r in responses:
        for p in r.trajectoryUpdates:
            for oid in p["observationIds"]:
                mapping[oid] = p["fusionId"]
    assert set(mapping) == {"a0", "b3", "rid1", "rid4"}
    assert len(set(mapping.values())) == 4, "A held observation split another full scan; A/B then shared one global target"
    assert len(responses[-1].tracks) == 4
