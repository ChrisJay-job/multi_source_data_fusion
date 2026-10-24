"""TASK-007 R3 independent regressions; run from the supplied project root."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from fusion_mvp.engine import load_config
from fusion_mvp.multisensor import MultisensorSession, replay_job

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


def seeded(name):
    s = MultisensorSession(name, load_config())
    rows = [
        row(s, f"{local}{sec}", sec, x, scan=f"init{sec}", local=local)
        for sec in (-3, -2, -1) for local, x in (("A", 0), ("B", 20))
    ]
    r = send(s, "seed", 1.1, rows)
    assert r.error is None and not r.rejected and len(r.tracks) == 2
    a_id = next(t.fusionId for t in r.tracks if any(b.sourceTrackId == "A" for b in t.sourceTracks))
    b_id = next(t.fusionId for t in r.tracks if any(b.sourceTrackId == "B" for b in t.sourceTracks))
    return s, a_id, b_id


def test_long_scan_interleaving_is_permutation_invariant_and_keeps_entity():
    for reverse in (False, True):
        s, a_id, b_id = seeded(f"permutation-{reverse}")
        rows = [
            row(s, "a", 0, 0, scan="long", local="A"),
            row(s, "b", 4, 20, scan="long", local="B"),
            row(s, "rid-b", 2, 20, detector="rid-01", scan="rid-scan", local="b"),
        ]
        if reverse:
            rows.reverse()
        r = send(s, "interleaved", 6.1, rows)
        assert r.error is None and not r.rejected
        assert {t.fusionId for t in r.tracks} == {a_id, b_id}
        owner = next(p["fusionId"] for p in r.trajectoryUpdates if "rid-b" in p["observationIds"])
        assert owner == b_id, "RID observation of stationary B was assigned to A"


def test_interleaved_scan_does_not_move_filter_clock_backwards():
    s, _a_id, b_id = seeded("clock")
    r = send(s, "interleaved", 4, [
        row(s, "a", 0, 0, scan="long", local="A"),
        row(s, "b", 1.2, 20, scan="long", local="B"),
        row(s, "rid-b", .6, 20, detector="rid-01", scan="rid-scan", local="b"),
    ])
    assert r.error is None and not r.rejected
    times = [datetime.fromisoformat(p["stateTime"]) for p in r.trajectoryUpdates if p["fusionId"] == b_id]
    assert times == sorted(times), "A newer state was updated using an older measurement without OOS handling"
    assert len(times) == 2
    assert datetime.fromisoformat(s.tracks[b_id].state_time.isoformat()) == T + timedelta(seconds=1.2)


def test_same_scan_arriving_in_two_requests_cannot_silently_share_one_target():
    s = MultisensorSession("split-scan", load_config())
    first = send(s, "part1", 2.1, [row(s, "a", 0, 0, scan="same-scan", local="A")])
    assert first.error is None
    r = send(s, "part2", 3.3, [row(s, "b", 1.2, 20, scan="same-scan", local="B")])
    # A declared, explicit closed-scan rejection is an acceptable bounded
    # alternative to accepting a second independent target. No silent merge.
    if r.rejected:
        assert any(x.observationId == "b" and x.reason in {"scan_closed", "scan_already_committed", "incomplete_scan"} for x in r.rejected)
        return
    assert r.error is None and len(r.tracks) == 2
    assert all(len({b.sourceTrackId for b in t.sourceTracks if b.detectorId == "radar-01"}) <= 1 for t in r.tracks)


def test_trusted_sn_prefers_existing_compatible_identity_over_nearer_anonymous_track():
    s = MultisensorSession("sn-rival", load_config())
    seed = [
        row(s, f"{local}{sec}", sec, x, scan=f"s{sec}", local=local, sn=sn)
        for sec in (0, 1, 2) for local, x, sn in (("A", 0, "SN-A"), ("B", 20, None))
    ]
    r = send(s, "seed", 4.1, seed)
    known = next(t.fusionId for t in r.tracks if t.aircraftId == "SN-A")
    r = send(s, "known", 5.1, [row(s, "known-return", 3, 18, local="A-new", sn="SN-A")])
    assert r.error is None and not r.rejected
    identified = [t for t in r.tracks if t.aircraftId == "SN-A"]
    assert len(identified) == 1 and identified[0].fusionId == known
    assert {p["fusionId"] for p in r.trajectoryUpdates if "known-return" in p["observationIds"]} == {known}


def replay_rows(cfg):
    s = MultisensorSession("generator", cfg)
    return [row(s, f"o{i}", i, 0) for i in range(8)]


def test_offline_does_not_consume_the_live_retry_capacity_per_measurement():
    cfg = load_config()
    cfg["multisensor_v1"]["max_idempotency_ids"] = 4
    r = replay_job(cfg, "offline-cap", replay_rows(cfg), 1)
    assert r.error is None, "Eight valid offline rows hit the four-ID live-session retry cap"
    assert r.summary["processed"] == 8 and len(r.trajectory) == 8
    assert len(r.snapshots) == 1


def test_http_replay_failure_is_not_reported_as_http_success(monkeypatch):
    import fusion_mvp.api as api
    cfg = load_config()
    cfg["multisensor_v1"]["max_idempotency_ids"] = 4
    monkeypatch.setattr(api, "CFG", cfg)
    r = TestClient(api.app).post("/v1/fusion/replay", json=dict(jobId="http-cap", observations=replay_rows(cfg), maxSnapshots=1))
    body = r.json()
    result = body.get("detail", body)
    if result.get("error"):
        assert r.status_code >= 400, "Business failure idempotency_capacity returned HTTP 200"
    else:
        assert r.status_code == 200 and result["summary"]["processed"] == 8


def test_partial_replay_summary_never_claims_all_observations_processed():
    cfg = load_config()
    cfg["multisensor_v1"]["max_idempotency_ids"] = 4
    r = replay_job(cfg, "partial-summary", replay_rows(cfg), 1)
    if r.error:
        assert r.summary["processed"] < r.summary["input"]
        assert "all_observations_processed" not in str(r.summary.get("note", ""))
        assert r.summary.get("unprocessed") == r.summary["input"] - r.summary["processed"]
    else:
        assert r.summary["processed"] == 8
