# Round6 闭环表

| ID | 要求 | 证据 | 结果 |
|---|---|---|---|
| R6-1 | premature_rid_removal → FAIL | `test_partial_outage_sources_round6`；`partial_outage_pre_independent.log`→`round6_focused.log` | PASS |
| R6-2 | expired_rid_kept_active → FAIL | 同上；`unexpected_active` 含 rid | PASS |
| 正例 | 同场景无故障 PASS | `test_normal_partial_outage_still_pass`；`normal_partial_outage.json` | PASS |
| TTL | 前/恰好/之后 + 分源阈值 | `test_rid_ttl_*` / `test_spectrum_coast_ttl_*` / helper 边界 | PASS |
| 双向字段 | missing / unexpected 显式 | `active_sources_mismatch` 明细 | PASS |
| 回归 | 保留原 122 + Round6 | `full_pytest.log` | 见全量 |
| 范围 | 仅 evaluator；不改引擎/UI | diff 限于 workbench evaluator + tests | 遵守 |
