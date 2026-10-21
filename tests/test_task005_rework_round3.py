"""TASK-005 REWORK Round3 — ID exchange null when not computable."""
from __future__ import annotations

from pathlib import Path

from fusion_mvp.workbench.evaluator import count_id_exchanges
from fusion_mvp.workbench.metrics_display import build_metrics_display


def test_r3_01_empty_snapshots_null():
    out = count_id_exchanges([])
    assert out["id_exchange_count"] is None
    assert out["recreate_count"] is None
    assert out.get("computable") is False


def test_r3_01_anonymous_frames_null_not_zero():
    anonymous = [
        {"tracks": [{"fusionId": "F1"}]},
        {"tracks": [{"fusionId": "F2"}]},
    ]
    out = count_id_exchanges(anonymous)
    assert out["id_exchange_count"] is None
    assert out["cross_exchange_count"] is None
    assert out["recreate_count"] is None
    assert out["frames_mapped"] == 0
    assert "无可映射身份" in (out["note"] or "")


def test_r3_01_one_mappable_frame_null():
    one_frame = [{"tracks": [{"fusionId": "F1", "aircraftId": "SN-A"}]}]
    out = count_id_exchanges(one_frame, sn_to_truth={"SN-A": "TA"})
    assert out["id_exchange_count"] is None
    assert out["frames_mapped"] == 1
    assert "不足2" in (out["note"] or "") or "时间转换" in (out["note"] or "")


def test_r3_01_stable_identity_zero():
    snaps = [
        {
            "tracks": [
                {"fusionId": "F1", "aircraftId": "SN-A"},
                {"fusionId": "F2", "aircraftId": "SN-B"},
            ]
        },
        {
            "tracks": [
                {"fusionId": "F1", "aircraftId": "SN-A"},
                {"fusionId": "F2", "aircraftId": "SN-B"},
            ]
        },
    ]
    out = count_id_exchanges(snaps, sn_to_truth={"SN-A": "TA", "SN-B": "TB"})
    assert out["id_exchange_count"] == 0
    assert out["recreate_count"] == 0
    assert out["computable"] is True
    assert "可映射子集" in (out["note"] or "")


def test_r3_01_swap_and_recreate_still_work():
    swapped = [
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
    assert count_id_exchanges(swapped, sn_to_truth={"SN-A": "TA", "SN-B": "TB"})["id_exchange_count"] == 1
    recre = [
        {"tracks": [{"fusionId": "F1", "aircraftId": "SN-A"}]},
        {"tracks": [{"fusionId": "F9", "aircraftId": "SN-A"}]},
    ]
    r = count_id_exchanges(recre, sn_to_truth={"SN-A": "TA"})
    assert r["id_exchange_count"] == 0
    assert r["recreate_count"] == 1


def test_r3_01_mixed_scope_note_not_full_scene_zero():
    """Partial mappable: measurable 0 must carry subset-scope note."""
    snaps = [
        {
            "tracks": [
                {"fusionId": "F1", "aircraftId": "SN-A"},
                {"fusionId": "Anon1"},  # unmapped
            ]
        },
        {
            "tracks": [
                {"fusionId": "F1", "aircraftId": "SN-A"},
                {"fusionId": "Anon2"},
            ]
        },
    ]
    out = count_id_exchanges(snaps, sn_to_truth={"SN-A": "TA"})
    assert out["id_exchange_count"] == 0
    assert "可映射子集" in (out["note"] or "")
    assert "全场景" in (out["note"] or "") or "未映射" in (out["note"] or "")


def test_r3_01_metrics_display_and_ui_keep_null():
    md = build_metrics_display(
        eval_out={"fusion_to_truth": {}, "attribution_errors": [], "false_merges": [], "duplicate_targets": []},
        last_tracks=[],
        snapshots=[{"tracks": [{"fusionId": "F1"}]}, {"tracks": [{"fusionId": "F2"}]}],
        sn_to_truth={},
    )
    assert md["id_exchange_count"] is None
    assert md["recreate_count"] is None
    assert md.get("id_exchange_computable") is False

    app = Path(__file__).resolve().parents[1] / "demo" / "workbench" / "app.js"
    src = app.read_text(encoding="utf-8")
    assert 'idEx == null ? "不可计算"' in src
    assert "id_exchange_count ?? 0" not in src
    assert "idEx ?? 0" not in src
