# TASK-007 attempt-001 REWORK R3

本轮只处理 R3-01 到 R3-04。正式文件是 `review_zip/TASK-007-rework-r3/REVIEW_AND_REWORK_R3.md`，SHA-256 `f2c0785401237b63bc9c1d00a5af370cf62b6dccaeeec42a81e0a85f5858a4ad`。

| 项 | 结果 | 证据 |
|---|---|---|
| R3-01 扫描预留与滤波时钟 | 同一次扫描先一对一预留，再按测量时间更新。输入顺序不改变目标归属。已释放扫描在 4 秒内出现另一个设备局部编号时返回 `scan_closed` | `tests/test_task007_r3_review.py` 前三项，正文与 `review_zip/TASK-007-rework-r3/test_task007_r3_review.py` 哈希同为 `8e6857d858554465e306b9f30849a374beb911fa345ad7f43c9c81ffdfcdc963` |
| R3-02 可信身份优先 | 波门内唯一同号航迹优先于更近的匿名航迹。越波门同号不抄到匿名航迹。同号含糊给出 `identity_ambiguous` | 官方第四项，以及 `test_r3_out_of_gate_same_sn_does_not_copy_onto_anonymous_track`、`test_r3_different_sn_does_not_replace_known_identity`、`test_r3_same_sn_ambiguity_emits_reason` |
| R3-03 离线容量与失败映射 | 回放逐帧不占用实时幂等名额。回放业务失败返回非 2xx。摘要含 `unprocessed`，中止时不声称全部已处理。默认配置 4097 行加最后 flush 全部完成 | `reports/task007/r3/default_replay_4097.json` |
| R3-04 本轮原始证据 | 旧的 ready、smoke、verify、runtime consistency、R2 全量日志和镜像说明已移到 `reports/task007/history/`。本轮只引用 `reports/task007/r3/` | 本文件与 `docs/task007/00_交付入口.md` |

Round5 的 `importer.py` 仍是 `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c`。`engine.py` 仍是 `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b`。`kalman.py` 仍是 `a0e52d4b44c5fbf4b8e00a5627cf0369542e7065c7618a6cd17fa46b98b5a8ae`。

当前源码指纹：`config/fusion.yaml` `2dbedf38134cc705d6101760ff96ddfc7cf8e6b4bf6e919aa5f42533f02385c5`，`src/fusion_mvp/multisensor.py` `b42f96153c43c60e11aa7f9f867ff5527fa48fb8f2822b9ecb5d3fbb859d9bad`。工作区全量 pytest 为 267 passed、1 warning、58.99 秒，日志 `reports/task007/r3/pytest_worktree_r3.log`。这是工作区日志，不是解压目录日志。解压目录日志是 `reports/task007/r3/pytest_fresh_unzip_r3.log`。

五场景真值覆盖仍是 single 72/72、three 360/360、missing 360/360、clutter 真实目标 360/360、crossing 492/492。末次确认数 1/3/3/3/2。没有混号。crossing RMSE 0.98385 米。见 `reports/task007/r3/fixture_truth_r3.json`。

真实 JSON 预览在 1366×768 和 1920×1080 都是扫描 28、有效 26、拒绝 2。见 `reports/task007/r3/browser/browser_result.json`。

联调镜像没有挂载源码目录。请求和响应在 `reports/task007/r3/http/`。镜像索引和端口见 `reports/task007/r3/image.json`。

真实三源同机仍是 BLOCKED。鸟类识别、约 2GB SQL 仍是 NOT_TESTED。Asia/Shanghai 仍未确认。当前剖面不是最终算法验收。
