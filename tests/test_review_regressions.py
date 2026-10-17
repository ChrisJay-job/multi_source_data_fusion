"""Independent review regressions. Run from project root with PYTHONPATH=src.

These tests target the submitted mvp-0.1.0 public behaviour and engine boundary.
Keep equivalent assertions if implementation is refactored; do not weaken them.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from fusion_mvp.engine import FusionSession, load_config
from fusion_mvp.mapping import normalize_row


def ts(sec):
    return (datetime(2026, 4, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=sec)).isoformat()


def obs(oid, source="tj-rid", sn="SN-A", offset=0.0, t=1, tid=None):
    row = dict(observationId=oid, source=source, id=tid or sn, detector="D1",
               aerial_sn="tcp", longitude=117.2 + offset, latitude=39.13,
               altitude=40, speed=8, heading=45, created_at=ts(t))
    if source == "tj-pp":
        row["source_data"] = dict(sn=sn, deviceId=1, trackTime=ts(t), az=45, courseAngle=0)
    return row


@pytest.fixture
def session():
    return FusionSession("independent-review", deepcopy(load_config()))


def test_radar_then_rid_really_fills_existing_identity(session):
    a = session.process("1", ts(1), [obs("r", "tj-leida", tid="R1")], "replay")
    original = a.tracks[0].fusionId
    b = session.process("2", ts(1.4), [obs("i", offset=.0001, t=1.4)], "replay")
    assert len(b.tracks) == 1, "Nearby consistent RID should fill the radar entity"
    assert b.tracks[0].aircraftId == "SN-A"
    assert b.tracks[0].fusionId == original
    assert set(b.tracks[0].sources) == {"rid", "radar"}


def test_secondary_position_must_not_move_fresh_rid_state(session):
    a = session.process("1", ts(1), [obs("i")], "replay")
    b = session.process("2", ts(1), [obs("r", "tj-leida", offset=.0005, tid="R1")], "replay")
    assert len(b.tracks) == 1
    assert b.tracks[0].positionSource == "rid"
    assert b.tracks[0].longitude == pytest.approx(a.tracks[0].longitude, abs=1e-10)


def test_realtime_buffer_keeps_accepting_real_measurements(session):
    watermarks = []
    for i in range(1, 7):
        b = session.process(str(i), ts(i), [obs(str(i), offset=i*.00001, t=i)], "realtime")
        watermarks.append(datetime.fromisoformat(b.watermark))
    assert b.tracks[0].lastObservedAt == ts(4), "2 s reorder buffer must process t=4 by t=6"
    assert watermarks == sorted(watermarks), "Committed watermark cannot go backwards"


def test_cross_batch_duplicate_does_not_confirm_track(session):
    row = obs("same")
    a = session.process("1", ts(1), [row], "replay")
    hits = next(iter(session.tracks.values())).hits
    for batch in ("2", "3"):
        b = session.process(batch, ts(1), [row], "replay")
    assert next(iter(session.tracks.values())).hits == hits
    assert b.tracks[0].trackStatus == a.tracks[0].trackStatus


def test_batch_failure_rolls_back_mutations(session, monkeypatch):
    original = session._ingest
    calls = 0

    def injected(item):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure after first successful observation")
        return original(item)

    monkeypatch.setattr(session, "_ingest", injected)
    b = session.process("1", ts(1), [obs("a"), obs("b", sn="SN-B", offset=.01)], "replay")
    assert b.error is not None
    assert not session.tracks, "Returning batch_rollback must undo the first mutation"
    assert session.seq == 0
    assert session.next_id == 1


def test_standard_observation_contract_works(session):
    standard = dict(observationId="s", source="rid", detectorId="D1", sourceTrackId="R1",
                    aircraftId="SN-A", measurementTime=ts(1), receivedAt=ts(1),
                    timeBasis="measurement", longitude=117.2, latitude=39.13,
                    altitude=None, altitudeDatum="unknown", speed=None, heading=None,
                    verticalSpeed=None, qualityFlags=[])
    b = session.process("1", ts(1), [standard], "replay")
    assert b.error is None and not b.rejected
    assert len(b.tracks) == 1 and b.tracks[0].aircraftId == "SN-A"


def test_out_of_range_longitude_is_rejected():
    row = obs("bad")
    row["longitude"] = 181
    normalized, rejection = normalize_row(row)
    assert normalized is None and rejection is not None


def test_unverified_spectrum_bearing_not_used_as_heading():
    normalized, rejection = normalize_row(obs("sp", source="tj-pp"))
    assert rejection is None
    assert normalized.heading is None, "az-like heading is not verified course"
    assert normalized.qualityFlags


def test_idempotency_hash_includes_reference_time(session):
    row = obs("i")
    session.process("same", ts(1), [row], "replay")
    b = session.process("same", ts(2), [row], "replay")
    assert b.error is not None, "Same batchId with changed processingTime is a conflict"


def test_sn_spatial_conflict_not_merged_only_by_identity(session):
    session.process("1", ts(1), [obs("i")], "replay")
    b = session.process("2", ts(2), [obs("sp", "tj-pp", offset=.1, t=2)], "replay")
    assert not any(t.aliases for t in b.tracks), "Rejected identity match must not re-enter unconditional merge"
    assert not any({"rid", "spectrum"} <= set(t.sources) for t in b.tracks)


def test_http_conflict_is_409():
    from fastapi.testclient import TestClient
    from fusion_mvp.api import app

    with TestClient(app) as client:
        request = dict(sessionId="review-http", batchId="same", mode="replay",
                       processingTime=ts(1), observations=[obs("a")])
        client.post("/v1/fusion/reset/review-http")
        assert client.post("/v1/fusion/process", json=request).status_code == 200
        request["observations"] = [obs("b")]
        assert client.post("/v1/fusion/process", json=request).status_code == 409
