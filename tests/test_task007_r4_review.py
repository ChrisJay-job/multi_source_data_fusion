"""R4 independent regressions for the submitted R3 build."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from fusion_mvp.engine import load_config
from fusion_mvp.multisensor import MultisensorSession

T = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


def iso(sec):
    return (T + timedelta(seconds=sec)).isoformat(timespec="microseconds")


def row(s, oid, sec, x, *, detector="radar-01", scan=None, local="A", sn=None):
    lat, lon = s.enu.to_ll(x, 0)
    return dict(
        observationId=oid, source="rid" if detector.startswith("rid") else "radar",
        detectorId=detector, scanId=scan or oid, sourceTrackId=local,
        aircraftId=sn, measurementTime=iso(sec), longitude=lon, latitude=lat,
        positionStdM=1, speed=0,
    )


def send(s, batch, sec, rows):
    return s.process(batch, iso(sec), rows, "realtime")


def test_cold_interleaved_scan_converges_without_permanent_duplicate_ambiguity():
    s = MultisensorSession("cold-interleaved", load_config())
    responses = [send(s, "cold", 4, [
        row(s, "a", 0, 0, scan="long", local="A"),
        row(s, "b", 1.2, 200, scan="long", local="B"),
        row(s, "rid-b", .6, 200, detector="rid-01", scan="rid", local="b"),
    ])]
    for i in range(1, 5):
        sec = 1.2 + i
        responses.append(send(s, f"next{i}", sec + 2.1, [
            row(s, f"a{i}", sec, 0, scan=f"r{i}", local="A"),
            row(s, f"b{i}", sec, 200, scan=f"r{i}", local="B"),
            row(s, f"rid-b{i}", sec + .01, 200, detector="rid-01", scan=f"rid{i}", local="b"),
        ]))
    assert all(r.error is None and not r.rejected for r in responses)
    last = responses[-1]
    confirmed = [t for t in last.tracks if t.trackStatus == "tracked"]
    assert len(confirmed) == 2, "Two stationary entities left three tracks and only one confirmed after four extra frames"
    owners = {}
    for t in confirmed:
        for b in t.sourceTracks:
            owners[(b.detectorId, b.sourceTrackId)] = t.fusionId
    assert owners[("radar-01", "A")] != owners[("radar-01", "B")]
    assert owners[("radar-01", "B")] == owners[("rid-01", "b")]
    final_oids = {oid for p in last.trajectoryUpdates for oid in p["observationIds"]}
    assert {"a4", "b4", "rid-b4"} <= final_oids


def test_unique_in_gate_sn_is_reserved_before_rectangular_anonymous_assignment():
    s = MultisensorSession("sn-column", load_config())
    seed = [
        row(s, f"{local}{sec}", sec, x, scan=f"s{sec}", local=local, sn=sn)
        for sec in (0, 1, 2) for local, x, sn in (("A", 0, "SN-A"), ("B", 40, None))
    ]
    first = send(s, "seed", 4.1, seed)
    known = next(t.fusionId for t in first.tracks if t.aircraftId == "SN-A")
    r = send(s, "same-scan", 5.1, [
        row(s, "known", 3, 18, local="Anew", sn="SN-A", scan="current"),
        row(s, "anon0", 3, 0, local="X", scan="current"),
        row(s, "anon40", 3, 40, local="B", scan="current"),
    ])
    assert r.error is None and not r.rejected
    owners = {p["fusionId"] for p in r.trajectoryUpdates if "known" in p["observationIds"]}
    assert owners == {known}, "Anonymous row took the column reserved for the unique compatible SN owner"
    assert [t.fusionId for t in r.tracks if t.aircraftId == "SN-A"] == [known]


def test_public_process_replay_mode_retry_keeps_original_response():
    import fusion_mvp.api as api
    client = TestClient(api.app)
    sid = "r4-public-replay-retry"
    client.post(f"/v1/fusion/reset/{sid}")
    body = dict(sessionId=sid, batchId="same", mode="replay", fusionProfile="multisensor-v1", processingTime=iso(3), observations=[])
    try:
        first = client.post("/v1/fusion/process", json=body)
        retry = client.post("/v1/fusion/process", json=body)
        assert first.status_code == retry.status_code == 200
        assert first.json() == retry.json(), "Public replay-mode retry advanced snapshotSeq"
    finally:
        client.post(f"/v1/fusion/reset/{sid}")


def test_public_process_replay_mode_conflicting_batch_is_http_409():
    import fusion_mvp.api as api
    client = TestClient(api.app)
    sid = "r4-public-replay-conflict"
    client.post(f"/v1/fusion/reset/{sid}")
    body = dict(sessionId=sid, batchId="same", mode="replay", fusionProfile="multisensor-v1", processingTime=iso(3), observations=[])
    try:
        first = client.post("/v1/fusion/process", json=body)
        assert first.status_code == 200
        s = MultisensorSession("generator", load_config())
        changed = dict(body, observations=[row(s, "new", 0, 0)])
        response = client.post("/v1/fusion/process", json=changed)
        assert response.status_code == 409, "Public replay-mode conflicting batch executed instead of returning conflict"
        assert response.json()["detail"]["error"] == "batch_id_conflict"
    finally:
        client.post(f"/v1/fusion/reset/{sid}")


def test_buffered_scan_does_not_silently_lose_earlier_anonymous_measurement():
    s = MultisensorSession("held-scan", load_config())
    seed = [
        row(s, f"{local}{sec}", sec, x, scan=f"s{sec}", local=local)
        for sec in (-3, -2, -1) for local, x in (("A", 0), ("B", 200))
    ]
    assert send(s, "seed", 1.1, seed).error is None
    responses = [send(s, "hold", 1.2, [
        row(s, "a0", 0, 0, scan="long", local="A"),
        row(s, "b3", 3, 200, scan="long", local="B"),
        row(s, "rid-a1", 1, 0, detector="rid-01", scan="rid", local="a"),
    ])]
    responses.append(send(s, "mid-tick", 3.1, []))
    responses.append(send(s, "flush", 5.1, []))
    assert all(r.error is None and not r.rejected for r in responses)
    oids = {oid for r in responses for p in r.trajectoryUpdates for oid in p["observationIds"]}
    assert oids == {"a0", "b3", "rid-a1"}, "Accepted anonymous a0 vanished when a held scan was released after a newer RID update"
