# TASK-002 attempt-001 REWORK Round4 闭环表

裁决：`REVIEW_READY`（不冻结）

| 项 | 结果 | 证据 |
|---|---|---|
| R4-01 多文件队列不被覆盖 | PASS | Node probe `queue_preserves_configured_files`；浏览器 `run_sends_configured_queue` + `multi_replay_two_sources` n=6 两源 |
| R4-02 页面 UTC 模板保存→加载 | PASS | 页面 btnSaveMap→切换→btnLoadMap；`page_save_load_assume_utc`；probe `page_saved_utc_template` |
| R4-03 稳定窗口接入 | PASS | `run_scenario_bundle` 传 `stable_window`；`test_primary_scenario_runner_supplies_stable_window`；W01 entity_check ok |
| R4-03 归属按 lastSeen／watermark | PASS | `test_reused_key_uses_bound_observation_time_not_future_processing_time` |
| R4-04 窗优先于 maxRows | PASS | `test_time_window_limit_applies_after_filtering`；导入摘要含 scanned／skipped_outside_window |
| R4-04 SQL 错误样例有界 | PASS | `test_sql_error_collector_has_bounded_samples`（内存 ≤20，总数 100） |
| R4-04 有界分页／筛选 | PASS | `/datasets/{id}/observations` 支持 time／detector／bbox；页面「有界翻页读」 |
| R4-05 当前计数取自快照 | PASS | `counts_at` 写入 snapshot；probe `future_rejection_at_start`；浏览器 `counts_at_after_multi` |
| 真实鼠标拖动 | PASS | Playwright mouse down/move/up；坐标变、点数不变、再加点 |
| 原 67 + Round4 | PASS | Docker 3.11 **71 passed** |
| 真实三源关联 | BLOCKED | — |
| 现场精度 | NOT_TESTED | — |

修前：`pre_test_round4.log`（4 failed）、`ui_probe_pre.json`（3 FAIL）  
修后：`post_test_full.log`（71 passed）、`ui_probe_post.json`（exit 0）、`browser/browser_evidence.json` pass=true
