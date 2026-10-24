# TASK-007 attempt-001 REWORK R6

本轮只处理 R6-01。正式文件是 `review_zip/TASK-007-rework-r6/REVIEW_AND_REWORK_R6.md`，SHA-256 `1dc083cf568f54b168a092350da572577a4af71edfafec05372b873239fb9381`。

| 项 | 结果 | 证据 |
|---|---|---|
| R6-01 未来槽位参考时刻 | `_cost_target` 对 pending slot 不再套用已提交 KF 的 dt&lt;-1 迟到门；按槽位速度/航向把锚点外推到观测时刻再比距离。SN/航向门、一对一、重叠等待、track 负 dt 保护保留 | `tests/test_task007_r6_review.py` 哈希 `41707101fbdc38c781bef2148a4a9f7a1942cf75f5628e9df13472bdd964e4b3` |

Round5 importer `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c`、engine `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b`、kalman 未改。

本轮指纹：`multisensor.py` `f5d919551c5ebc921d617a314d8a6be86f818ffe1c6a5a95400097ffa662d6e2`，`fusion.yaml` `ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342`。

工作区全量 pytest：279 passed、1 warning、61.15 秒。34 独立回归通过。五场景覆盖 72/360/360/360/492，crossing RMSE 0.98385 米。默认 4097+flush 完整。真实 JSON 两视口 28/26/2。联调端口 18101，请求响应在 `reports/task007/r6/http/`。

本轮原始证据只在 `reports/task007/r6/`。真实三源同机 BLOCKED；鸟类识别、约 2GB SQL NOT_TESTED；Asia/Shanghai 未确认。
