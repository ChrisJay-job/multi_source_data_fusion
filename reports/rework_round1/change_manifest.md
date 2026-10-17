# REWORK Round1 变更清单

## 源码

- `src/fusion_mvp/engine.py` — R01–R06/R09 核心重写（保留 FusionSession/API 骨架）
- `src/fusion_mvp/mapping.py` — R07/R08 标准契约与降级
- `src/fusion_mvp/api.py` — 409/400/500、/ready
- `tests/test_review_regressions.py` — 审查附带回归（未削弱）
- `tests/test_t01_t12.py` — 收紧 T03/T06/T07/T12
- `tests/test_rework_extras.py` — 分配顺序/事件ID/TTL
- `scripts/extract_continuous_segment.py` / `replay_continuous.py`

## 需求→代码→测试追溯

| 需求 | 代码 | 测试 |
|---|---|---|
| 实时水位 | engine process flush 顺序 | test_realtime_buffer_* |
| 身份后补 | _associate anonymous fill | test_radar_then_rid_* / T03 |
| RID 主源 | _choose_primary + secondary_bind_only | test_secondary_position_* |
| 全局分配 | _global_assign_radar + LSA | test_global_assignment_* / T04 |
| 幂等回滚 | fingerprint/snapshot/_ingest | test_batch_failure_* / test_cross_batch_* / HTTP 409 |
| 标准接口 | normalize_standard | test_standard_observation_* |
| 降级 | latlon/heading | test_out_of_range_* / spectrum heading |

## 未改

- 原始 `data/aircraft_flight_data.sql` 只读
- 旧 `reports/review_summary.md` 保留；本轮写在 `reports/rework_round1/`
