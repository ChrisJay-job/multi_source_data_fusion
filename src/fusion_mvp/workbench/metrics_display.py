"""Shared eval-side metrics_display builder (API + runner). Never fed to frozen engine."""
from __future__ import annotations

import math
from typing import Any, Optional

from .evaluator import count_id_exchanges, position_errors


def build_metrics_display(
    *,
    eval_out: dict[str, Any],
    last_tracks: list[dict],
    snapshots: list[dict],
    expected_stable_entities: Optional[list] = None,
    truth_timeline: Optional[dict] = None,
    sn_to_truth: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    attrs = list(eval_out.get("attribution_errors") or [])
    f2t = eval_out.get("fusion_to_truth") or {}

    # Last-snapshot entity coverage (not observation association rate).
    bound_truths = set(f2t.values())
    n_expected = len(expected_stable_entities) if expected_stable_entities else None
    last_cov = None
    last_cov_note = "不可计算：缺少期望稳定实体分母（不自分母）"
    if n_expected and n_expected > 0:
        last_cov = len(bound_truths) / float(n_expected)
        last_cov_note = (
            "末快照实体覆盖率=已映射真值实体数/期望稳定实体数；"
            f"分子={len(bound_truths)}；分母={n_expected}；不等于观测正确关联比例"
        )

    # ID exchange from timeline (not reason substrings).
    idex = count_id_exchanges(snapshots, sn_to_truth=sn_to_truth or {})

    rmse_c = None
    rmse_d = None
    rmse_c_note = "不可计算：无 truth_timeline 或 fusion_to_truth"
    rmse_d_note = rmse_c_note
    match_c = None
    match_d = None
    if truth_timeline and f2t and last_tracks:
        pe_c = [p for p in position_errors(truth_timeline, last_tracks, f2t, mode="committed") if p.get("computable")]
        pe_d = [p for p in position_errors(truth_timeline, last_tracks, f2t, mode="display") if p.get("computable")]
        if pe_c:
            rmse_c = math.sqrt(sum(float(p["error_m"]) ** 2 for p in pe_c) / len(pe_c))
            match_c = len(pe_c) / max(len(last_tracks), 1)
            rmse_c_note = (
                "已提交误差=末个 committedHistory 点 vs 同刻真值（最近邻，max_gap=0.75s）；"
                f"匹配={len(pe_c)}/{len(last_tracks)}；范围=末点非全程；无现场阈值只报数值"
            )
        else:
            rmse_c_note = "不可计算：无有效已提交匹配（缺历史/超出真值时间/超容差）"
        if pe_d:
            rmse_d = math.sqrt(sum(float(p["error_m"]) ** 2 for p in pe_d) / len(pe_d))
            match_d = len(pe_d) / max(len(last_tracks), 1)
            rmse_d_note = (
                "展示预测误差=顶层 lat/lon @ displayStateTime vs 真值；"
                f"匹配={len(pe_d)}/{len(last_tracks)}；与已提交分列"
            )
        else:
            rmse_d_note = "不可计算：无有效展示预测匹配"

    return {
        "n_targets_last_snapshot": len(last_tracks),
        "false_merge_count": len(eval_out.get("false_merges") or []),
        "duplicate_target_count": len(eval_out.get("duplicate_targets") or []),
        "id_exchange_count": idex.get("id_exchange_count"),  # null = 不可计算，禁止当成 0
        "id_exchange_note": idex.get("note"),
        "id_exchange_frames_mapped": idex.get("frames_mapped"),
        "id_exchange_computable": idex.get("computable"),
        "recreate_count": idex.get("recreate_count"),  # null 与交换同口径
        "hard_attribution_error_count": len(
            [a for a in attrs if a not in (eval_out.get("undetermined") or [])]
        ),
        "undetermined_count": len(eval_out.get("undetermined") or []),
        # Prefer explicit last-snapshot name; keep association_coverage alias = same value only when defined.
        "last_snapshot_entity_coverage": last_cov,
        "last_snapshot_entity_coverage_note": last_cov_note,
        "association_coverage": last_cov,
        "association_coverage_note": last_cov_note,
        "position_rmse_m_committed": rmse_c,
        "position_rmse_note": rmse_c_note,
        "position_match_coverage": match_c,
        "position_rmse_m_display": rmse_d,
        "position_rmse_display_note": rmse_d_note,
        "position_match_coverage_display": match_d,
        "entity_status": (eval_out.get("entity_check") or {}).get("status"),
        "denominator_note": (
            "末快照实体覆盖≠观测关联率；已提交/展示预测误差分列；"
            "ID交换仅覆盖可映射身份子集（不足2帧可映射→null非0）；硬错误保留原始 FAIL。"
        ),
    }
