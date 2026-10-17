"""Additional Round1 coverage: assignment order, SN key reuse, TTL cache."""
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


def test_global_assignment_independent_of_input_order():
    cfg = deepcopy(load_config())
    rows_a = [radar("a1", "R1", 0.0, 1), radar("a2", "R2", 0.02, 1)]
    rows_b = list(reversed(rows_a))
    s1 = FusionSession("ord-a", cfg)
    s2 = FusionSession("ord-b", deepcopy(cfg))
    r1 = s1.process("1", ts(1), rows_a, "replay")
    r2 = s2.process("1", ts(1), rows_b, "replay")
    assert len(r1.tracks) == 2 and len(r2.tracks) == 2
    # continuing updates keep two entities either order
    cont_a = [radar("c1", "R1", 0.0001, 2), radar("c2", "R2", 0.0201, 2)]
    cont_b = list(reversed(cont_a))
    u1 = s1.process("2", ts(2), cont_a, "replay")
    u2 = s2.process("2", ts(2), cont_b, "replay")
    assert len(u1.tracks) == 2 and len(u2.tracks) == 2


def test_expired_idempotency_rejects_reuse(monkeypatch):
    cfg = deepcopy(load_config())
    cfg["idempotency_ttl_s"] = 1
    sess = FusionSession("ttl", cfg)
    row = dict(
        observationId="x", source="tj-rid", id="SN-Z", detector="D1", aerial_sn="tcp",
        longitude=117.2, latitude=39.13, altitude=40, speed=8, heading=10, created_at=ts(1),
    )
    a = sess.process("batch", ts(1), [row], "replay")
    assert a.error is None
    # force cache entry aged (CacheEntry API after Round2)
    entry = sess.cache["batch"]
    entry.stored_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    b = sess.process("batch", ts(1), [row], "replay")
    assert b.error == "idempotency_expired"


def test_event_ids_are_stable_and_unique():
    sess = FusionSession("eid", deepcopy(load_config()))
    r = sess.process(
        "1", ts(1),
        [dict(observationId="o", source="tj-rid", id="SN-E", detector="D1", aerial_sn="tcp",
              longitude=117.2, latitude=39.13, altitude=40, speed=8, heading=10, created_at=ts(1))],
        "replay",
    )
    ids = [e.payload.get("eventId") for e in r.events]
    assert ids and all(i and i.startswith("E") for i in ids)
    assert len(ids) == len(set(ids))
