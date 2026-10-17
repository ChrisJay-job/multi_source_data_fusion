"""Round2 regressions against submitted Round1 implementation.

Run from project root: PYTHONPATH=src python -m pytest -q tests/test_round2_regressions.py
Equivalent public-behaviour checks must survive engine refactoring.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from fusion_mvp.engine import FusionSession, load_config
from fusion_mvp.mapping import normalize_row


def ts(sec):
    return (datetime(2026, 4, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=sec)).isoformat()


def row(oid, sec=1, source="rid", tid="T", sn="SN", offset=0):
    return dict(observationId=oid, source=source, detectorId="D",
                sourceTrackId=tid, aircraftId=None if source == "radar" else sn,
                measurementTime=ts(sec), receivedAt=ts(sec), timeBasis="measurement",
                longitude=117.2+offset, latitude=39.13, altitude=None,
                altitudeDatum="unknown", speed=None, heading=None,
                verticalSpeed=None, qualityFlags=[])


@pytest.fixture
def s():
    return FusionSession("round2", deepcopy(load_config()))


def test_irregular_realtime_no_silent_stale_updates(s):
    events=[]
    times=[1,3,3.2,3.4,3.6,4,5,6]
    for i,t in enumerate(times):
        r=s.process(str(i),ts(t),[row(str(i),t)],"realtime")
        events.extend(e.type for e in r.events)
    r=s.process("flush",ts(14),[],"realtime")
    events.extend(e.type for e in r.events)
    assert "stale_obs_ignored" not in events, "Ordered in-window data must reach the filter"
    assert sum(t.hits for t in s.tracks.values()) == len(times)
    assert not s.buffer


def test_duplicates_inside_one_batch_update_once(s):
    item=row("same")
    s.process("a",ts(1),[item,item],"replay")
    assert sum(t.hits for t in s.tracks.values()) == 1


def test_duplicate_while_buffered_is_not_applied_twice(s):
    item=row("same")
    s.process("a",ts(1),[item],"realtime")
    s.process("b",ts(1.5),[item],"realtime")
    s.process("flush",ts(4),[],"realtime")
    assert sum(t.hits for t in s.tracks.values()) == 1


def test_observation_id_conflict_is_atomic_batch_error(s):
    original=row("same")
    s.process("a",ts(1),[original],"replay")
    before=[t.model_dump() for t in s._snapshots()]
    seq=s.seq
    changed=row("same",sec=2,offset=.0001)
    new=row("other",sec=2,sn="OTHER",tid="OTHER",offset=.01)
    result=s.process("b",ts(2),[changed,new],"replay")
    assert result.error == "observation_id_conflict"
    assert s.seq == seq
    assert [t.model_dump() for t in s._snapshots()] == before


def test_secondary_prediction_does_not_double_advance_filter(s):
    s.process("a",ts(1),[row("rid")],"replay")
    track=next(iter(s.tracks.values()))
    track.kf.x[2]=10.0
    before_x=track.kf.x.copy()
    before_t=track.stateTime
    s.process("b",ts(2),[row("radar",2,"radar",offset=.0001)],"replay")
    dt=(track.stateTime-before_t).total_seconds()
    expected_x=before_x[0]+before_x[2]*dt
    assert track.kf.x[0] == pytest.approx(expected_x), "Secondary prediction and lifecycle must not integrate dt twice"


def test_global_gate_cannot_be_bypassed_by_fallback(s):
    s.process("a",ts(1),[row("rid")],"replay")
    tr=next(iter(s.tracks.values()))
    radar=row("radar",1,"radar",offset=.001)
    x,y=s.geo.to_xy(radar["latitude"],radar["longitude"])
    assert s._mahalanobis(tr,x,y,s.cfg["kalman"]["r_radar"]) > 6
    result=s.process("b",ts(1),[radar],"replay")
    assert not any({"rid","radar"} <= set(t.sources) for t in result.tracks), "LSA unmatch cannot call a looser nearest-neighbour path"


def test_cache_eviction_does_not_allow_old_batch_to_be_new():
    cfg=deepcopy(load_config());cfg["max_cache"]=1
    s=FusionSession("cache",cfg)
    first=s.process("a",ts(1),[],"replay")
    s.process("b",ts(1),[],"replay")
    result=s.process("a",ts(1),[],"replay")
    assert result.error is not None or result.snapshotSeq == first.snapshotSeq


def test_output_contains_height_datum(s):
    item=row("rid");item["altitude"]=100;item["altitudeDatum"]="relative_takeoff"
    result=s.process("a",ts(1),[item],"replay")
    assert result.tracks[0].model_dump().get("altitudeDatum") == "relative_takeoff"
