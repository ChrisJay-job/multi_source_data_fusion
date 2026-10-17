"""Remaining regressions in Round2. Run with PYTHONPATH=src pytest -q tests."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import pytest
from fusion_mvp.engine import FusionSession,load_config


def ts(t):
    return (datetime(2026,4,9,12,tzinfo=timezone.utc)+timedelta(seconds=t)).isoformat()


def obs(oid,t=1,source='rid',offset=0):
    return dict(observationId=oid,source=source,detectorId='D',sourceTrackId=source+'-T',
                aircraftId='SN-A',measurementTime=ts(t),receivedAt=ts(t),timeBasis='measurement',
                longitude=117.2+offset,latitude=39.13,altitude=None,altitudeDatum='unknown',
                speed=None,heading=None,verticalSpeed=None,qualityFlags=[])


def test_empty_flush_must_not_invalidate_legal_delayed_observation():
    s=FusionSession('empty-gap',deepcopy(load_config()))
    s.process('a',ts(1),[obs('one',1)],'realtime')
    empty=s.process('empty',ts(3),[],'realtime')
    # At pt=3 the 2-second event watermark may only commit through t=1.
    # A new t=2.5 observation delivered at pt=3.2 is just 0.7 s late.
    s.process('b',ts(3.2),[obs('two',2.5)],'realtime')
    end=s.process('flush',ts(5),[],'realtime')
    assert end.tracks[0].lastObservedAt == ts(2.5)
    assert not any(e.type=='stale_obs_ignored' for e in end.events)
    assert datetime.fromisoformat(empty.watermark) <= datetime.fromisoformat(ts(1))


def test_same_time_source_order_does_not_change_rid_primary_position():
    def run(items):
        s=FusionSession('order',deepcopy(load_config()))
        result=s.process('a',ts(1),items,'replay')
        assert len(result.tracks)==1
        assert result.tracks[0].positionSource=='rid'
        return result.tracks[0]
    rid=obs('rid');spectrum=obs('sp',source='spectrum',offset=.0002)
    a=run([rid,spectrum]);b=run([spectrum,rid])
    assert a.longitude == pytest.approx(b.longitude,abs=1e-10)
    assert a.latitude == pytest.approx(b.latitude,abs=1e-10)
