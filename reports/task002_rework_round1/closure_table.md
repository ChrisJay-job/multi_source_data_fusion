# TASK-002 attempt-001 REWORK Round1 闭环表

裁决目标：`REVIEW_READY`（不冻结 TASK-002）

| 项 | 审查缺口 | 本轮证据 | 结果 |
|---|---|---|---|
| R01 轨迹分组／时间轴 | 同源混连、未来点、无融合历史、停在末帧 | `scripts/probe_canvas_round1.cjs` PASS；Playwright `output/review_stage/task002_round1_browser/`（seek=0、only A／RID／fused、hide pred、play/step） | PASS（浏览器可执行） |
| R02 航线编辑／预置 | 仅固定场景 | 预置 8 场景 API + 页面编辑器（航点／三源启停／噪声／保存导入导出）；`POST /v1/workbench/run/scenario` 接受 `scenario` 体 | PASS |
| R03 导入回放 | SQL0条／预览截断／无observations／时区 | `tests/test_task002_review.py` 4 项导入相关全绿；正式 run 重解析 + 回传 observations | PASS |
| R04 评估归属 | 错雷达绑定假阳性 | `test_evaluator_catches_wrong_radar_truth_binding` PASS | PASS |
| R05 乱序／计数 | 改 measurementTime；hits 不准；truth 泄漏常量 | reorder 测例 PASS；runner 累计 updates／binds；`truth_leaked_to_algorithm` 扫描输入 | PASS |
| R06 接口文档 | 缺字段／确认表／OpenAPI | `docs/interface/*` + `docs/openapi.yaml` workbench 路径 | PASS |
| TASK-001 41 基线 | 不得破坏 | Docker 3.11 `pytest tests`：**59 passed**（含原 TASK-001 + Round + workbench + 7 review） | PASS |
| 真实三源关联／现场精度 | — | 未测 | NOT_TESTED |
| 2GB 全量 SQL 关联 | — | 不入包；流式能力具备 | NOT_TESTED／范围外入包 |

修前：`reports/task002_rework_round1/pre_test_round1.log`（7 failed）  
修后：`output/review_stage/task002_round1/pytest_post_fix.txt`（59 passed）
