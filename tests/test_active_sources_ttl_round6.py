"""Round6: TTL grace, bidirectional active-set faults, per-source limits."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from fusion_mvp.workbench import evaluator as ev
from fusion_mvp.workbench.scenario import generate_observations, get_preset
import fusion_mvp.workbench.runner as runner


def _t0(bundle):
    return datetime.fromisoformat(bundle["t0"].replace("Z", "+00:00"))


def test_normal_partial_outage_still_pass():
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = [sc.aircraft[3]]
    sc.duration_s = 45
    sc.aircraft[0].sources["rid"].outage = [(12.0, 30.0)]
    result = runner.WorkbenchRunner().run_scenario_bundle(generate_observations(sc))
    assert result["evaluation"]["entity_check"]["status"] == "PASS"


@pytest.mark.parametrize(
    "age_lo,age_hi,expect_rid",
    [
        (0.5, 2.5, True),     # before / at rid_fresh_s inclusive
        (2.5000001, 6.0, False),  # after TTL
    ],
)
def test_rid_ttl_boundaries_via_evaluator_fault(monkeypatch, age_lo, age_hi, expect_rid):
    """Drop rid from sources when age(frontier−lastRid) in band; FAIL iff still within TTL."""
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = [sc.aircraft[3]]
    sc.duration_s = 45
    sc.aircraft[0].sources["rid"].outage = [(12.0, 30.0)]
    bundle = generate_observations(sc)
    original = runner.evaluate_run
    touched = []

    def inject(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        delivered = kw.get("delivered_obs") or []
        for snap in snaps:
            wm = snap.get("watermark")
            if not wm or not snap.get("tracks"):
                continue
            life = datetime.fromisoformat(wm.replace("Z", "+00:00"))
            last_rid = None
            for o in delivered:
                if o.get("source") != "rid":
                    continue
                mt = o.get("measurementTime")
                if not mt:
                    continue
                t = datetime.fromisoformat(mt.replace("Z", "+00:00"))
                if t <= life and (last_rid is None or t > last_rid):
                    last_rid = t
            if last_rid is None:
                continue
            age = (life - last_rid).total_seconds()
            if age_lo <= age <= age_hi:
                for tr in snap["tracks"]:
                    if "spectrum" not in (tr.get("sources") or []):
                        continue
                    # Within TTL we need rid present in the original snap to drop it.
                    if expect_rid and "rid" not in (tr.get("sources") or []):
                        continue
                    before = list(tr["sources"])
                    tr["sources"] = [x for x in tr["sources"] if x != "rid"]
                    touched.append({"age": age, "before": before, "after": list(tr["sources"])})
        kw["snapshots_by_time"] = snaps
        return original(**kw)

    monkeypatch.setattr(runner, "evaluate_run", inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert touched, {"age_lo": age_lo, "age_hi": age_hi, "expect_rid": expect_rid}
    errs = [
        d
        for d in result["evaluation"]["entity_check"]["details"]
        if d.get("error") == "active_sources_mismatch"
    ]
    if expect_rid:
        assert result["evaluation"]["entity_check"]["status"] == "FAIL"
        assert any("rid" in (e.get("missing_active") or []) for e in errs)
    else:
        assert not any("rid" in (e.get("missing_active") or []) for e in errs)


def test_rid_ttl_exact_boundary_helper_and_fault_fields():
    """Exactly age==rid_fresh_s remains active; +epsilon expires (helper + diff fields)."""
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
    last = t0 + timedelta(seconds=11.0)
    delivered = [
        {
            "observationId": "o1",
            "source": "rid",
            "detectorId": "d",
            "sourceTrackId": "s",
            "measurementTime": last.isoformat(),
        }
    ]
    sched = {"takeoff_s": 0.0, "enabled": {"rid"}, "outages": {"rid": [(12.0, 40.0)]}}
    at = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=last + timedelta(seconds=2.5),
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o1": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"rid"},
    )
    after = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=last + timedelta(seconds=2.5 + 1e-6),
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o1": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"rid"},
    )
    assert at == {"rid"}
    assert after == set()
    d = ev._diff_active_sources(at, set())
    assert d["missing_active"] == ["rid"] and d["ok"] is False


def test_spectrum_coast_ttl_differs_from_rid():
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
    delivered = [
        {
            "observationId": "o_sp",
            "source": "spectrum",
            "detectorId": "d",
            "sourceTrackId": "s",
            "measurementTime": (t0 + timedelta(seconds=10)).isoformat(),
        }
    ]
    sched = {"takeoff_s": 0.0, "enabled": {"spectrum"}, "outages": {}}
    at_3_9 = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=t0 + timedelta(seconds=13.9),
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o_sp": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"spectrum"},
    )
    at_4_1 = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=t0 + timedelta(seconds=14.1),
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o_sp": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"spectrum"},
    )
    assert at_3_9 == {"spectrum"}
    assert at_4_1 == set()


def test_full_outage_ttl_grace_then_empty(monkeypatch):
    """All sources outaged: within rid TTL still expect rid; after TTL empty sources ok."""
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 50
    sc.aircraft[0].sources["rid"].outage = [(12.0, 40.0)]
    # disable other sources if present
    for name, cfg in list(sc.aircraft[0].sources.items()):
        if name != "rid":
            cfg.enabled = False
    bundle = generate_observations(sc)
    t0 = _t0(bundle)
    original = runner.evaluate_run

    def inject_premature(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        for snap in snaps:
            dt = (datetime.fromisoformat(snap["watermark"].replace("Z", "+00:00")) - t0).total_seconds()
            if 12.0 <= dt <= 13.0:
                for tr in snap.get("tracks") or []:
                    if "rid" in tr.get("sources", []):
                        tr["sources"] = []
        kw["snapshots_by_time"] = snaps
        return original(**kw)

    monkeypatch.setattr(runner, "evaluate_run", inject_premature)
    bad = runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert bad["evaluation"]["entity_check"]["status"] == "FAIL"

    # no fault: normal full outage must not fail
    monkeypatch.undo()
    ok = runner.WorkbenchRunner().run_scenario_bundle(generate_observations(sc))
    assert ok["evaluation"]["entity_check"]["status"] != "FAIL"


def test_diff_active_sources_helper():
    d = ev._diff_active_sources({"rid", "spectrum"}, {"spectrum"})
    assert d["missing_active"] == ["rid"]
    assert d["unexpected_active"] == []
    d2 = ev._diff_active_sources({"spectrum"}, {"spectrum", "rid"})
    assert d2["unexpected_active"] == ["rid"]
    assert d2["ok"] is False
