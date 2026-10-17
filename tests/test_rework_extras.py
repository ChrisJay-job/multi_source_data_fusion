"""Additional rework coverage: assignment order, TTL, event ids."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fusion_mvp.engine import FusionSession, load_config


def ts(sec):
    return (datetime(2026, 4, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=sec)).isoformat()


def radar(oid, tid, offset, t, det="D1"):
    return dict(
        observationId=oid, source="tj-leida", id=tid, detector=det,
        longitude=117.2 + offset, latitude=39.13, altitude=40, speed=8,
        heading=90, created_at=ts(t),
    )


def test_global_assignment_order_invariant():
    cfg = deepcopy(load_config())
    rows_a = [radar("a1", "R1", 0.0, 1), radar("a2", "R2", 0.02, 1)]
    rows_b = list(reversed(rows_a))
    s1 = FusionSession("ord-a", cfg)
    s2 = FusionSession("ord-b", deepcopy(cfg))
    r1 = s1.process("1", ts(1), rows_a, "replay")
    r2 = s2.process("1", ts(1), rows_b, "replay")
    assert len(r1.tracks) == 2 and len(r2.tracks) == 2
    # same sourceTrackIds bound regardless of input order
    bind1 = sorted((st.sourceTrackId, round(t.longitude, 5)) for t in r1.tracks for st in t.sourceTracks)
    bind2 = sorted((st.sourceTrackId, round(t.longitude, 5)) for t in r2.tracks for st in t.sourceTracks)
    assert bind1 == bind2


def test_event_ids_stable_and_unique():
    s = FusionSession("eid", deepcopy(load_config()))
    r = s.process("1", ts(1), [radar("a", "R1", 0, 1), radar("b", "R2", 0.02, 1)], "replay")
    ids = [e.payload.get("eventId") for e in r.events]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_idempotency_expired_not_recomputed_as_new():
    cfg = deepcopy(load_config())
    cfg["idempotency_ttl_s"] = 0.0
    s = FusionSession("ttl", cfg)
    row = radar("a", "R1", 0, 1)
    a = s.process("same", ts(1), [row], "replay")
    # force cache entry aged (CacheEntry API after Round2)
    batch_id = "same"
    entry = s.cache[batch_id]
    entry.stored_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    b = s.process("same", ts(1), [row], "replay")
    assert b.error == "idempotency_expired"
    assert a.snapshotSeq == 1
