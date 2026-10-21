# TASK-005 需求闭环表

| # | 要求 | 实现 | 证据 |
|---|---|---|---|
| 1 | 保留七机 A–G | `seven_aircraft_combinations` 未改行为 | `test_seven_default_still_seven` |
| 2 | 七机+挑战 H–M 隔离区 | `seven_plus_challenges_*` 13 机 | 同测 + 预置 JSON |
| 3 | 同时/错时交叉、近距、追越、断源、换号 | `scenario_challenges.py` 预置 | geometry 校验 + matrix |
| 4 | 身份有/无两配置；按源独立 SN | `emit_aircraft_id` | `test_per_source_identity_*` |
| 5 | 不透明局部 ID；顺序扰动 | `opaque_track_ids` | opaque / shuffle 测 |
| 6 | ≥5 种子矩阵，暴露真实 FAIL | `challenge_matrix.json` | 2m_with_id 等 FAIL 如实 |
| 7 | 图层快捷显示／图例中文 | index/app/styles | 浏览器证据 |
| 8 | 目标详情／为什么关联／时钟计数 | app.js | 浏览器 + 指南 |
| 9 | 评估分列；FAIL 不标绿 | metrics_display + UI | 测试 + browser |
| 10 | 冻结引擎未改 | frozen_algo_sha256 | 与 TASK-003 哈希对照 |
| 11 | 用户指南六问 | `docs/task005/user_guide.md` | 文件 |
| 12 | 浏览器 1366/1920 | `browser_workbench_task005.mjs` | browser_evidence.json |

状态：**REVIEW_READY**（非冻结）。TASK-004 外部确认／真实三源 BLOCKED／现场精度 NOT_TESTED／2GB NOT_TESTED **保持**。
