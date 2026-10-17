"""Watermark/source expiry regressions; preserve equivalent assertions after refactor."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fusion_mvp.engine import FusionSession,load_config


def ts(sec):return (datetime(2026,4,9,12,tzinfo=timezone.utc)+timedelta(seconds=sec)).isoformat()
def item(oid,t):
 return dict(observationId=oid,source='rid',detectorId='D',sourceTrackId='R',aircraftId='SN',measurementTime=ts(t),receivedAt=ts(t),timeBasis='measurement',longitude=117.2,latitude=39.13,altitude=None,altitudeDatum='unknown',speed=None,heading=None,verticalSpeed=None,qualityFlags=[])
def prepared():
 s=FusionSession('r4',deepcopy(load_config()))
 s.process('a',ts(1),[item('one',1)],'realtime')
 s.process('flush',ts(3),[],'realtime')
 return s


def test_empty_batches_advance_committed_cutoff_and_expire_sources():
 s=prepared();r=s.process('empty',ts(10),[],'realtime')
 assert r.watermark==ts(8), '2 s reorder window commits through t=8 at processingTime=10'
 assert 'rid' not in r.tracks[0].sources
 assert r.tracks[0].positionMode=='stale'
 assert r.tracks[0].lastObservedAt==ts(1)


def test_old_observation_is_explicitly_rejected_after_empty_period():
 s=prepared();s.process('empty',ts(10),[],'realtime')
 r=s.process('old',ts(10),[item('old-two',2)],'realtime')
 assert any(x.observationId=='old-two' and x.reason=='late_beyond_reorder_window' for x in r.rejected)
 assert r.tracks[0].lastObservedAt==ts(1)
 assert not any(e.type=='reacquired' for e in r.events)
