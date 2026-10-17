# REWORK Round2 变更清单

## 源码

- `src/fusion_mvp/engine.py` — R2-01～R2-05 核心：事件水位、展示预测副本、LSA 未匹配 birth、三阶段去重、CacheEntry 生命周期
- `src/fusion_mvp/models.py` — `altitudeDatum`／`displayStateTime`；CacheEntry 状态
- `src/fusion_mvp/mapping.py` — 非有限值／类型错误拒绝或降级；高度基准保留
- `src/fusion_mvp/api.py` — 冲突／过期缓存错误映射
- `config/fusion.yaml` — 确认阈值与缓存／TTL 配置对齐实现
- `tests/test_round2_regressions.py` — 审查附带 8 项（未削弱断言）
- `tests/test_rework_extra.py` / `tests/test_rework_extras.py` — CacheEntry API 对齐
- `scripts/audit_continuous.py` — 逐观测 `_apply_update`／hits 增量审计

## 需求→代码→测试追溯

| 需求 | 代码 | 测试／证据 |
|---|---|---|
| 事件水位／展示预测 | `_process_locked` watermark、display predict 副本 | `test_irregular_realtime_*`；连续段审计 |
| 非主源不双积分 | secondary bind-only | `test_secondary_prediction_*` |
| LSA 无宽松回退 | `_global_assign_radar` → `_birth` | `test_global_gate_*` |
| 三阶段去重／原子冲突 | accepted／buffer／seen | `test_duplicates_*`／`test_observation_id_conflict_*` |
| 缓存淘汰／过期 | `CacheEntry` status | `test_cache_eviction_*`／TTL extras |
| 高度基准输出 | `TargetSnapshot.altitudeDatum` | `test_output_contains_height_datum` |

## 未改

- 原始 `data/aircraft_flight_data.sql` 只读、不入包
- Round1 审查包与 `reports/rework_round1/` 保留不覆盖
- 技术路线仍为三源 CV-KF ENU MVP，无五源／复杂滤波
