"""Round5: lifecycle/display clocks, required fields, active-sources (no sourceTracks mask)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from fusion_mvp.workbench import evaluator as ev
from fusion_mvp.workbench.scenario import generate_observations, get_preset
import fusion_mvp.workbench.runner as runner


def _t0(bundle):
    return datetime.fromisoformat(bundle["t0"].replace("Z", "+00:00"))


def test_early_clear_before_terminate_fails_with_frontier_detail(monkeypatch):
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 80
    sc.aircraft[0].sources["rid"].outage = [(12.0, 50.0)]
    bundle = generate_observations(sc)
    t0 = _t0(bundle)
    original = runner.evaluate_run
    meta = []

    def inject(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        for snap in snaps:
            dt = (datetime.fromisoformat(snap["processingTime"].replace("Z", "+00:00")) - t0).total_seconds()
            if 42 <= dt <= 43:
                assert snap["tracks"] and all(t["trackStatus"] == "lost" for t in snap["tracks"])
                snap["tracks"] = []
        kw["snapshots_by_time"] = snaps
        out = original(**kw)
        errs = [d for d in out["entity_check"]["details"] if d.get("error") == "missing_entity"]
        meta.extend(errs)
        return out

    monkeypatch.setattr(runner, "evaluate_run", inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert result["evaluation"]["entity_check"]["status"] == "FAIL"
    assert meta
    sample = meta[0]
    assert sample.get("lifecycle_clock") or sample.get("frontier")
    assert sample.get("display_clock")
    assert sample.get("last_observation")
    assert sample.get("gap_s") is not None and sample["gap_s"] <= 30.0 + 1e-6
    assert sample.get("expected", {}).get("allow_absent") is False


@pytest.mark.parametrize(
    "gap_lo,gap_hi,label",
    [
        (28.0, 29.5, "before_terminate"),
        (29.5, 30.0 + 1e-9, "at_terminate"),
    ],
)
def test_clear_before_or_at_terminate_fails_realtime(monkeypatch, gap_lo, gap_hi, label):
    """Realtime empty ticks retain lost tracks through gap≤30; clearing must FAIL."""
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 75
    sc.aircraft[0].sources["rid"].outage = [(12.0, 60.0)]
    bundle = generate_observations(sc)
    original = runner.evaluate_run
    touched = []

    def inject(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        for snap in snaps:
            wm = snap.get("watermark") or snap.get("processingTime")
            if not wm or not snap.get("tracks"):
                continue
            life = datetime.fromisoformat(wm.replace("Z", "+00:00"))
            last_raw = snap["tracks"][0].get("lastObservedAt")
            if not last_raw:
                continue
            last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            gap = (life - last).total_seconds()
            if gap_lo <= gap <= gap_hi:
                touched.append({"gap": gap, "wm": wm, "pt": snap.get("processingTime"), "label": label})
                snap["tracks"] = []
        kw["snapshots_by_time"] = snaps
        return original(**kw)

    monkeypatch.setattr(runner, "evaluate_run", inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle, mode="realtime")
    assert touched, {"label": label}
    assert result["evaluation"]["entity_check"]["status"] == "FAIL"
    assert any(d.get("error") == "missing_entity" for d in result["evaluation"]["entity_check"]["details"])


def test_natural_absence_after_terminate_realtime():
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 75
    sc.aircraft[0].sources["rid"].outage = [(12.0, 60.0)]
    result = runner.WorkbenchRunner().run_scenario_bundle(generate_observations(sc), mode="realtime")
    ec = result["evaluation"]["entity_check"]
    assert ec["status"] != "FAIL", {"phases": ec.get("phases"), "errors": [d for d in ec["details"] if d.get("error")][:3]}
    assert any(d.get("note") == "absent_after_terminate_s" for d in ec["details"])


def _iso(t0: datetime, sec: float) -> str:
    return (t0 + timedelta(seconds=sec)).isoformat()


@pytest.mark.parametrize(
    "life_s,disp_s,empty,expect_missing_fail",
    [
        (40.0, 40.0, True, True),   # replay clocks equal; gap=29 from last@11 → must FAIL
        (41.0, 41.0, True, True),   # gap=30 at terminate → FAIL
        (42.0, 42.0, True, False),  # gap=31 after terminate → absence ok
    ],
)
def test_replay_clock_terminate_boundary_unit(life_s, disp_s, empty, expect_missing_fail):
    """Replay: watermark == processingTime. Direct oracle on crafted snaps."""
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
    last = 11.0
    delivered = [
        {
            "observationId": "o1",
            "source": "rid",
            "detectorId": "d",
            "sourceTrackId": "s",
            "measurementTime": _iso(t0, last),
            "aircraftId": "SN-A",
        }
    ]
    track = {
        "fusionId": "f1",
        "aircraftId": "SN-A",
        "trackStatus": "lost",
        "positionMode": "stale",
        "sources": [],
        "sourceTracks": [
            {
                "source": "rid",
                "detectorId": "d",
                "sourceTrackId": "s",
                "lastSeen": _iso(t0, last),
            }
        ],
        "lastObservedAt": _iso(t0, last),
        "stateTime": _iso(t0, last),
    }
    snap = {
        "processingTime": _iso(t0, disp_s),
        "watermark": _iso(t0, life_s),
        "tracks": [] if empty else [track],
    }
    # Warm-up snap with track so attribution can bind SN
    warm = {
        "processingTime": _iso(t0, 12.0),
        "watermark": _iso(t0, 12.0),
        "tracks": [
            {
                **track,
                "trackStatus": "tracked",
                "positionMode": "measured_assisted",
                "sources": ["rid"],
            }
        ],
    }
    out = ev.evaluate_run(
        snapshots_by_time=[warm, snap],
        obs_truth_map={"o1": "T-A"},
        delivered_obs=delivered,
        rejected=[],
        events=[],
        expected_stable_entities={"T-A": {"rid"}},
        stable_window=(_iso(t0, life_s), _iso(t0, life_s)),
        scenario={
            "aircraft": [
                {
                    "truth_id": "T-A",
                    "takeoff_offset_s": 0,
                    "sources": {"rid": {"enabled": True, "outage": [[12.0, 60.0]]}},
                }
            ]
        },
        scenario_t0=t0.isoformat(),
        lifecycle_cfg=None,
    )
    ec = out["entity_check"]
    missing = [d for d in ec["details"] if d.get("error") == "missing_entity"]
    if expect_missing_fail:
        assert ec["status"] == "FAIL" and missing, {"life_s": life_s, "details": ec["details"][:3]}
        assert missing[0].get("lifecycle_clock")
        assert missing[0].get("display_clock")
    else:
        assert not missing, missing
        assert any(d.get("note") == "absent_after_terminate_s" for d in ec["details"])


@pytest.mark.parametrize(
    "fault",
    ["drop_trackStatus", "drop_positionMode", "illegal_status", "illegal_mode"],
)
@pytest.mark.parametrize("window", ["active", "outage"])
def test_required_fields_fail_in_active_and_outage(monkeypatch, fault, window):
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 55
    if window == "outage":
        sc.aircraft[0].sources["rid"].outage = [(12.0, 38.0)]
        lo, hi = 20.0, 24.0
    else:
        lo, hi = 8.0, 12.0
    bundle = generate_observations(sc)
    t0 = _t0(bundle)
    original = runner.evaluate_run

    def inject(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        for snap in snaps:
            dt = (datetime.fromisoformat(snap["processingTime"].replace("Z", "+00:00")) - t0).total_seconds()
            if lo <= dt <= hi:
                for tr in snap.get("tracks") or []:
                    if fault == "drop_trackStatus":
                        tr.pop("trackStatus", None)
                    elif fault == "drop_positionMode":
                        tr.pop("positionMode", None)
                    elif fault == "illegal_status":
                        tr["trackStatus"] = "flying"
                    else:
                        tr["positionMode"] = "measured"
        kw["snapshots_by_time"] = snaps
        return original(**kw)

    monkeypatch.setattr(runner, "evaluate_run", inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert result["evaluation"]["entity_check"]["status"] == "FAIL", fault
    assert any(
        d.get("error") == "snapshot_field_contract" for d in result["evaluation"]["entity_check"]["details"]
    )


def test_nullable_aircraftId_null_is_not_field_error():
    tr = {
        "fusionId": "f1",
        "trackStatus": "tracked",
        "positionMode": "measured_assisted",
        "sources": ["rid"],
        "aircraftId": None,
    }
    assert ev._validate_required_track_fields(tr) is None


def test_active_sources_empty_not_masked_by_sourceTracks(monkeypatch):
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 40
    bundle = generate_observations(sc)
    t0 = _t0(bundle)
    original = runner.evaluate_run

    def inject(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        for snap in snaps:
            dt = (datetime.fromisoformat(snap["processingTime"].replace("Z", "+00:00")) - t0).total_seconds()
            if 15 <= dt <= 18:
                for tr in snap.get("tracks") or []:
                    assert tr.get("sources") == ["rid"]
                    assert tr.get("sourceTracks")
                    tr["sources"] = []
        kw["snapshots_by_time"] = snaps
        return original(**kw)

    monkeypatch.setattr(runner, "evaluate_run", inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert result["evaluation"]["entity_check"]["status"] == "FAIL"
    errs = [
        d
        for d in result["evaluation"]["entity_check"]["details"]
        if d.get("error") in ("active_sources_mismatch", "sources_mismatch_or_foreign")
    ]
    assert errs
    sample = errs[0]
    actual = sample.get("actual_active", sample.get("have"))
    expect = sample.get("expected_active", sample.get("need"))
    assert actual == [] or sample.get("have") == []
    assert "rid" in (expect or sample.get("missing_active") or [])


def test_all_sources_expired_empty_active_ok_when_ttl_elapsed():
    """Unit: expected active empty when last obs older than TTL — empty sources PASS."""
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
    life_clk = t0 + timedelta(seconds=20)
    delivered = [
        {
            "observationId": "o1",
            "source": "rid",
            "detectorId": "d",
            "sourceTrackId": "s",
            "measurementTime": (t0 + timedelta(seconds=10)).isoformat(),
        }
    ]
    sched = {"takeoff_s": 0.0, "enabled": {"rid"}, "outages": {}}
    need = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=life_clk,
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o1": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"rid"},
    )
    assert need == set()


def test_one_source_expired_other_still_fresh():
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
    life_clk = t0 + timedelta(seconds=12)
    delivered = [
        {
            "observationId": "o_rid",
            "source": "rid",
            "detectorId": "d",
            "sourceTrackId": "s1",
            "measurementTime": (t0 + timedelta(seconds=11.5)).isoformat(),
        },
        {
            "observationId": "o_sp",
            "source": "spectrum",
            "detectorId": "d",
            "sourceTrackId": "s2",
            "measurementTime": (t0 + timedelta(seconds=5)).isoformat(),
        },
    ]
    sched = {"takeoff_s": 0.0, "enabled": {"rid", "spectrum"}, "outages": {}}
    need = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=life_clk,
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o_rid": "A", "o_sp": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"rid", "spectrum"},
    )
    assert need == {"rid"}


def test_outage_does_not_revoke_rid_ttl_grace():
    """Round6: outage stops new obs; last rid@11 still active at frontier 12.5 (TTL=2.5)."""
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
    delivered = [
        {
            "observationId": "o1",
            "source": "rid",
            "detectorId": "d",
            "sourceTrackId": "s",
            "measurementTime": (t0 + timedelta(seconds=11.0)).isoformat(),
        }
    ]
    sched = {"takeoff_s": 0.0, "enabled": {"rid"}, "outages": {"rid": [(12.0, 40.0)]}}
    still = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=t0 + timedelta(seconds=12.5),
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o1": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"rid"},
    )
    assert still == {"rid"}
    expired = ev._expected_active_sources(
        truth_id="A",
        sched=sched,
        lifecycle_clock=t0 + timedelta(seconds=14.0),
        t0_dt=t0,
        delivered_obs=delivered,
        obs_truth_map={"o1": "A"},
        rid_fresh_s=2.5,
        coast_s=4.0,
        need_sources_default={"rid"},
    )
    assert expired == set()


def test_snapshot_clocks_prefer_watermark_for_lifecycle():
    snap = {
        "processingTime": "2026-04-09T12:00:42+00:00",
        "watermark": "2026-04-09T12:00:40+00:00",
    }
    life, disp = ev._snapshot_clocks(snap)
    assert life.isoformat() == "2026-04-09T12:00:40+00:00"
    assert disp.isoformat() == "2026-04-09T12:00:42+00:00"


def test_lifecycle_band_terminate_strictly_after_30():
    life = ev._lifecycle_thresholds(None)
    assert ev._lifecycle_band(30.0, life)["allow_absent"] is False
    assert ev._lifecycle_band(30.0 + 1e-9, life)["allow_absent"] is True
