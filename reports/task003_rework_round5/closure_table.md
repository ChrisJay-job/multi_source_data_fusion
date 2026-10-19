# Round5 闭环表

| ID | 要求 | 证据 | 结果 |
|---|---|---|---|
| R5-01 | lifecycle/display 双时钟；终止前清空捕获 | `contract_pre.log` 3 fail → `round5_focused.log` PASS；`lifecycle_contract.md` | PASS |
| R5-02 | 必填字段前置校验 | `test_required_fields_fail_in_active_and_outage`；合同反例 `missing_snapshot_fields` | PASS |
| R5-03 | 活跃源只看 `sources` | `test_active_sources_empty_not_masked_by_sourceTracks`；合同反例 `empty_active_sources` | PASS |
| 边界 | 终止前/恰好 FAIL；之后自然缺席不误报；replay 合成时钟 | `test_clear_before_or_at_terminate_*` / `test_replay_clock_terminate_boundary_unit` / `test_natural_absence_*` | PASS |
| 回归 | 保留原 97 + Round5 新测 | `full_pytest.log` | 见全量日志 |
| 浏览器 | 不重跑无关 UI；坐标精确逐点仍未覆盖 | Round4 审计保留；本轮登记 | NOT_RETEST / 坐标精确比对 NOT_COVERED |
| 范围 | 不改引擎时钟；不进 TASK-004 / 三源 / 2GB | 变更限于 evaluator + tests + 报告 | 遵守 |

## 修前 → 修后

- 附件三反例：`3 failed` → `3 passed`
- 已知确定故障 → FAIL；缺证据 → NOT_TESTED（未降级逃避）
