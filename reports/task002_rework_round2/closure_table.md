# TASK-002 attempt-001 REWORK Round2 闭环表

裁决目标：`REVIEW_READY`（不冻结）

| 项 | 缺口 | 证据 | 结果 |
|---|---|---|---|
| R2-01 目标筛选／预测历史 | only A 丢融合；pred 关仍实线桥接预测点 | `scripts/probe_render_round2.cjs` pass；浏览器 only_A_fusion 断言 | PASS |
| R2-02 页面 SQL 默认映射 | created_at/id/detector 未接通 | `test_actual_sql_works_with_the_pages_default_mapping`；字段映射表单 | PASS |
| R2-03 全过程评估 | 中间错绑被最终恢复抹掉；重复实体仍 ok | Round2 两测例；evaluator 逐快照 | PASS |
| R2-04 空批计数 | tick 未计入 processed_updates | `test_realtime_empty_ticks...` → 2 | PASS |
| R2-05 图上画线／多源／映射 | 原范围补齐 | 画布加点 API；`/run/import/multi`；mapping 模板；浏览器断言 | PASS |
| 原 59 + Round2 | — | Docker 3.11 `pytest tests` **63 passed** | PASS |
| 浏览器 | 仅截图假 PASS | `browser_evidence.json` 全断言 pass=true | PASS |
| 真实三源关联 | — | — | BLOCKED |
| 现场精度 | — | — | NOT_TESTED |

修前：`reports/task002_rework_round2/pre_test_round2.log`（4 failed）  
修后：`reports/task002_rework_round2/post_test_full.log`（63 passed）
