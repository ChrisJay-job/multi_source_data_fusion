# TASK-007 attempt-001 REWORK R4

本轮只处理 R4-01 到 R4-03。正式文件是 `review_zip/TASK-007-rework-r4/REVIEW_AND_REWORK_R4.md`，SHA-256 `1927599f1e2c02f003589e21f4c8fe9781c6def20761ed9765e4fc44ae639fd6`。

| 项 | 结果 | 证据 |
|---|---|---|
| R4-01 扫描预留与缓冲时序 | 扫描预留包含尚未生成目标的逻辑槽位；交错设备可先填入同一槽位。因末点未到释放线而持有的扫描，测量时间落在其跨度内的其他观测一并等待，释放后按事件时间提交 | `tests/test_task007_r4_review.py` 第 1、5 项，与正式件哈希同为 `98a7fda8c5a9babf653254de682dc4276da82e1275a508f2a4ca73f735b20b26` |
| R4-02 SN 列先占用 | 唯一门内同 SN 行先落实列占用，再对剩余行列做匿名匈牙利 | 官方第 2 项；原门外/异 SN/歧义用例保留 |
| R4-03 公开 process 幂等 | 公开 `/v1/fusion/process` 的 realtime/replay 均保留重试与冲突。仅内部 `replay_job(..., retain_idempotency=False)` 不逐帧占名额 | 官方第 3、4 项；`reports/task007/r4/default_replay_4097.json` |

`fusion.yaml` 去掉重复的 `closed_scan_reject_s` / `max_closed_scans` 定义，保留一份说明。

Round5 importer `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c`、engine `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b`、kalman 未改。

本轮指纹：`multisensor.py` `d4e7fcbcd73fff1281d22622588336274c7c06458a2b1b9c6f8236b7c11d7330`，`fusion.yaml` `ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342`。

工作区全量 pytest：272 passed、1 warning、59.49 秒（`reports/task007/r4/pytest_worktree_r4.log`）。五场景覆盖 72/360/360/360/492，crossing RMSE 0.98385 米。默认 4097+flush 仍完整。真实 JSON 两视口 28/26/2。联调端口 18099，请求响应在 `reports/task007/r4/http/`。

本轮原始证据只在 `reports/task007/r4/`。真实三源同机 BLOCKED；鸟类识别、约 2GB SQL NOT_TESTED；Asia/Shanghai 未确认。
