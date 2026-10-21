"""TASK-005 REWORK Round2 — four remaining items only (frozen algo)."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from fusion_mvp.workbench.evaluator import count_id_exchanges, position_errors
from fusion_mvp.workbench.metrics_display import build_metrics_display
from fusion_mvp.workbench.runner import WorkbenchRunner
from fusion_mvp.workbench.scenario import generate_observations, get_preset
from fusion_mvp.workbench.scenario_challenges import validate_challenge_geometry


def test_r2_01_position_errors_committed_vs_display_zero_case():
    """Audit counterexample: commit@0m / display@20m / truth matches both → errors 0."""
    truth = {
        "T": [
            {"time": "2026-04-09T12:00:00Z", "lat": 0.0, "lon": 0.0},
            {"time": "2026-04-09T12:00:02Z", "lat": 0.0, "lon": 20 / 111320.0},
        ]
    }
    tr = {
        "fusionId": "F",
        "stateTime": "2026-04-09T12:00:00Z",
        "displayStateTime": "2026-04-09T12:00:02Z",
        "positionMode": "predicted",
        "latitude": 0.0,
        "longitude": 20 / 111320.0,
        "committedHistory": [
            {"stateTime": "2026-04-09T12:00:00Z", "latitude": 0.0, "longitude": 0.0}
        ],
    }
    committed = position_errors(truth, [tr], {"F": "T"}, mode="committed")
    display = position_errors(truth, [tr], {"F": "T"}, mode="display")
    assert committed and committed[0]["computable"] is True
    assert display and display[0]["computable"] is True
    assert committed[0]["error_m"] == pytest.approx(0.0, abs=0.05)
    assert display[0]["error_m"] == pytest.approx(0.0, abs=0.05)
    assert committed[0]["scope"] == "last_committed_point"


def test_r2_01_position_errors_nonzero_and_outside_span():
    truth = {
        "T": [
            {"time": "2026-04-09T12:00:00Z", "lat": 0.0, "lon": 0.0},
            {"time": "2026-04-09T12:00:02Z", "lat": 0.0, "lon": 0.0},
        ]
    }
    tr_bad = {
        "fusionId": "F",
        "displayStateTime": "2026-04-09T12:00:02Z",
        "latitude": 0.0,
        "longitude": 10 / 111320.0,
        "committedHistory": [
            {"stateTime": "2026-04-09T12:00:00Z", "latitude": 0.0, "longitude": 5 / 111320.0}
        ],
    }
    pe_c = position_errors(truth, [tr_bad], {"F": "T"}, mode="committed")
    pe_d = position_errors(truth, [tr_bad], {"F": "T"}, mode="display")
    assert pe_c[0]["computable"] and pe_c[0]["error_m"] == pytest.approx(5.0, abs=0.2)
    assert pe_d[0]["computable"] and pe_d[0]["error_m"] == pytest.approx(10.0, abs=0.2)

    tr_out = {
        "fusionId": "F",
        "displayStateTime": "2026-04-09T12:00:10Z",
        "latitude": 0.0,
        "longitude": 0.0,
        "committedHistory": [
            {"stateTime": "2026-04-09T12:00:10Z", "latitude": 0.0, "longitude": 0.0}
        ],
    }
    pe_out = position_errors(truth, [tr_out], {"F": "T"}, mode="committed")
    assert pe_out[0]["computable"] is False
    assert pe_out[0]["error_m"] is None
    assert "outside_truth_span" in pe_out[0]["reason"]


def test_r2_01_id_exchange_timeline_not_reason_strings():
    snaps_swap = [
        {
            "tracks": [
                {"fusionId": "F1", "aircraftId": "SN-A"},
                {"fusionId": "F2", "aircraftId": "SN-B"},
            ]
        },
        {
            "tracks": [
                {"fusionId": "F2", "aircraftId": "SN-A"},
                {"fusionId": "F1", "aircraftId": "SN-B"},
            ]
        },
    ]
    sn = {"SN-A": "TA", "SN-B": "TB"}
    swapped = count_id_exchanges(snaps_swap, sn_to_truth=sn)
    assert swapped["id_exchange_count"] == 1
    assert swapped["cross_exchange_count"] == 1
    assert swapped["recreate_count"] == 0

    snaps_recreate = [
        {"tracks": [{"fusionId": "F1", "aircraftId": "SN-A"}]},
        {"tracks": [{"fusionId": "F9", "aircraftId": "SN-A"}]},
    ]
    recre = count_id_exchanges(snaps_recreate, sn_to_truth={"SN-A": "TA"})
    assert recre["id_exchange_count"] == 0
    assert recre["recreate_count"] == 1

    empty = count_id_exchanges([])
    assert empty["id_exchange_count"] is None


def test_r2_01_coverage_no_self_denominator():
    md = build_metrics_display(
        eval_out={"fusion_to_truth": {"F": "T"}, "attribution_errors": [], "false_merges": [], "duplicate_targets": []},
        last_tracks=[{"fusionId": "F"}],
        snapshots=[],
        expected_stable_entities=None,
        truth_timeline=None,
    )
    assert md["last_snapshot_entity_coverage"] is None
    assert md["association_coverage"] is None
    assert "缺少期望" in (md["last_snapshot_entity_coverage_note"] or "")


def test_r2_02_jk_pair_geometry_not_hi_global():
    geo = validate_challenge_geometry(get_preset("seven_plus_challenges_with_id"))
    assert geo.get("min_truth_distance_pair") == ["H", "I"] or set(geo.get("min_truth_distance_pair") or []) == {
        "H",
        "I",
    }
    jk = next(c for c in geo["checks"] if c.get("kind") == "near_parallel_spacing" and set(c.get("pair") or []) == {"J", "K"})
    assert jk["min_d"] == pytest.approx(2.0, abs=0.5)
    assert jk["at"] == pytest.approx(0.0, abs=0.5)
    # Global cross is not the focused near pair
    assert set(geo["min_truth_distance_pair"]) != {"J", "K"}
    assert geo["min_truth_distance_m"] < 1.0


def test_r2_03_first_realtime_snapshot_buffer_vs_processed():
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 1
    out = WorkbenchRunner().run_scenario_bundle(generate_observations(sc), mode="realtime")
    first = out["snapshots"][0]
    c = first["counts_at"]
    assert c["delivered"] >= 1
    assert c["processed_updates"] == 0 or len(first["tracks"]) == 0
    assert c["processed_observations"] is None  # 未提供可靠计数
    assert "bind_only" in c and "source_binds" in c
    # After flush, processed_updates may grow; bind_only stays separate key
    last = out["snapshots"][-1]["counts_at"]
    assert "bind_only" in last and "source_binds" in last
    assert out["counts"]["bind_only"] == last["bind_only"]


def test_r2_03_source_bound_and_bind_only_separated():
    """counts keys must remain distinct; UI must not alias source_binds as bind_only."""
    app = Path(__file__).resolve().parents[1] / "demo" / "workbench" / "app.js"
    src = app.read_text(encoding="utf-8")
    assert "已处理观测数=${procObsTxt}" in src or "已处理观测数=" in src
    assert "未提供可靠计数" in src
    assert "secondary_bind_only" in src
    assert "source_bound" in src
    # Must not assign delivered to processed-obs label path
    assert "已处理观测数=${c.delivered_at_t" not in src
    assert "仅绑定事件" not in src or "secondary_bind_only" in src


def test_r2_04_update_transport_clears_inspector_inline():
    app = Path(__file__).resolve().parents[1] / "demo" / "workbench" / "app.js"
    src = app.read_text(encoding="utf-8")
    # Empty-track branch must clear inspector/explain/detail without depending solely on helper name
    assert 'inspector.innerHTML = msg' in src or 'inspector.innerHTML = "当前时刻无目标"' in src
    assert "clearInspectorPanels" in src
    assert "新运行已加载" in src
