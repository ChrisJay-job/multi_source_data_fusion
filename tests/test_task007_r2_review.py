"""Focused regressions for the submitted TASK-007 R1 implementation."""
from datetime import datetime, timedelta, timezone
from fusion_mvp.engine import load_config
from fusion_mvp.multisensor import MultisensorSession

T = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)
def iso(t): return t.isoformat(timespec='microseconds')
def session(name, cfg=None): return MultisensorSession(name, cfg or load_config())
def row(s, oid, sec, x=0, *, local='L', source='radar', detector='radar-01', scan=None, sn=None, speed=0, heading=None):
    lat, lon = s.enu.to_ll(x, 0)
    return dict(observationId=oid, source=source, detectorId=detector,
                sourceTrackId=local, scanId=scan or f's-{sec}', aircraftId=sn,
                measurementTime=iso(T + timedelta(seconds=sec)), longitude=lon,
                latitude=lat, speed=speed, heading=heading, positionStdM=1,
                objectClass='unknown')
def send(s, batch, sec, rows):
    return s.process(batch, iso(T + timedelta(seconds=sec)), rows, 'realtime')

def test_generated_ids_are_not_device_identity_exclusions():
    s = session('generated')
    r = send(s, 'one-target', 4, [row(s, f'a{i}', i * .1, local=None) for i in range(10)])
    assert r.error is None and not r.rejected
    assert len(r.tracks) == 1, 'One stationary target without local IDs fragmented into ten'
    assert r.tracks[0].trackStatus == 'tracked'

def test_same_sn_unambiguous_local_renumber_preserves_fusion_id():
    s = session('renumber')
    for i in range(3):
        r = send(s, f'a{i}', i + 2.1, [row(s, f'a{i}', i, local='old', source='rid', detector='rid-01', sn='SN-A')])
    fid = r.tracks[0].fusionId
    r = send(s, 'renumber', 4.4, [row(s, 'new', 2.2, local='new', source='rid', detector='rid-01', sn='SN-A')])
    assert not r.rejected and r.error is None
    assert len(r.tracks) == 1 and r.tracks[0].fusionId == fid

def test_complete_scan_constraint_is_not_one_second_lock():
    s = session('scan-span')
    r = send(s, 'complete', 4, [
        row(s, 'a', 0, 0, local='A', scan='complete-scan'),
        row(s, 'rid', .6, 0, source='rid', detector='rid-01'),
        row(s, 'b', 1.2, 20, local='B', scan='complete-scan'),
    ])
    assert r.error is None and not r.rejected
    assert len(r.tracks) == 2
    assert all(len([b for b in t.sourceTracks if b.detectorId == 'radar-01']) <= 1 for t in r.tracks)

def test_kf_state_clock_agrees_with_state_after_secondary_binding():
    s = session('state-clock')
    r = send(s, 'rid', 2.1, [row(s, 'rid', 0, 0, local='r', source='rid', detector='rid-01', sn='SN-A', speed=10, heading=90)])
    fid = r.tracks[0].fusionId
    r = send(s, 'secondary', 3.1, [row(s, 'sp', 1, 10, local='p', source='spectrum', detector='spectrum-01', sn='SN-A', speed=10, heading=90)])
    tr = s.tracks[fid]
    elapsed = (tr.state_time - T).total_seconds()
    # A bind-only secondary may leave the KF at t=0 or propagate it consistently.
    # Advancing only the clock without propagating the state is invalid.
    assert abs(tr.kf.pos[0] - 10 * elapsed) < .05

def test_evicted_retry_is_not_reexecuted_inside_ttl():
    cfg = load_config()
    cfg['max_cache'] = 2
    s = session('retry-window', cfg)
    first = send(s, 'b0', 3, [])
    for i in range(1, 12):
        assert send(s, f'b{i}', 3, []).error is None
    seq = s.seq
    retry = send(s, 'b0', 3, [])
    assert retry.error in {'idempotency_expired', 'idempotency_evicted'} or retry.model_dump() == first.model_dump()
    assert s.seq == seq, 'Old retry was executed as a new batch after tombstone eviction'

def test_failed_batch_rolls_back_cache_eviction():
    cfg = load_config()
    cfg['max_cache'] = 1
    s = session('cache-rollback', cfg)
    first = send(s, 'first', 3, [])
    original = s._take_updates
    def fail_after_eviction():
        raise RuntimeError('forced after cache trimming')
    s._take_updates = fail_after_eviction
    failed = send(s, 'failed', 4, [])
    s._take_updates = original
    assert failed.error == 'batch_rollback'
    assert 'first' in s.cache, 'Failed transaction evicted a previously successful response'
    assert send(s, 'first', 3, []).model_dump() == first.model_dump()
