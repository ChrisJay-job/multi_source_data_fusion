# TASK-003 attempt-001 闭环表

| # | 要求 | 结果 | 证据 |
|---|---|---|---|
| 1 | 从 TASK-002 冻结 commit 开独立分支，保留 tag | PASS | branch=`task-003-workbench-usability-and-association`；tag `task-002-fusion-validation-workbench-v1`→`5749a240…` |
| 2 | 默认七机 + 恢复默认；原三机保留 | PASS | preset `seven_aircraft_combinations`；UI `btnResetSeven`；浏览器 n=7 |
| 3 | 轨迹历史可见；关预测不丢实测；单点不丢 | PASS | `canvas.js` 单点 stub；浏览器 draw_cmds>0 |
| 4 | 附录四机误关联修前/后；显式 20s 换号 | PASS | `pre_fix/` vs `post_fix/`；`test_task003.py` |
| 5 | 动态评估按实际飞机/来源 | PASS | `runner.expected_sources_from_scenario` |
| 6 | 布局：列表+抽屉；结果可解释 | PASS | `index.html` / `app.js` 结果区 |
| 7 | 保留原回归 + 浏览器断言 1366/1920 | PASS | 83 passed；`reports/task003/browser/` |
| 8 | REVIEW_READY；不 commit/tag/push | PASS | 本包；见 git_status |

边界：真实三源 **BLOCKED**；现场精度 **NOT_TESTED**；全量 2GB SQL **NOT_TESTED**。
