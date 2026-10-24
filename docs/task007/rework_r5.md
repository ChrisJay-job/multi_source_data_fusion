# TASK-007 attempt-001 REWORK R5

本轮只处理 R5-01 到 R5-03。正式文件是 `review_zip/TASK-007-rework-r5/REVIEW_AND_REWORK_R5.md`，SHA-256 `52eb08d97dae28c385a100f98d8f16132109f228ce52109977aeb266d835f9e9`。

| 项 | 结果 | 证据 |
|---|---|---|
| R5-01 slot 约束 | 槽位保存 aircraftId/speed/heading；与 track 共用身份、航向、时刻门。应用前再次校验，不兼容则隔离 spawn | `tests/test_task007_r5_review.py` 第 1、2 项，哈希 `65f1c3c21b8388a9186aa3addaa7ad1dddbd386e2d3d78f3cea900234c2127c3` |
| R5-02 强制列一对一 | 多行同 SN 争用同一列时发出 `identity_ambiguous`，列只保留一次，不二次强制占用 | 官方第 3 项 |
| R5-03 重叠持有传递 | held span 会把被挡住的整扫并入等待集，直到分区稳定；不拆开同扫成员提前关闭 | 官方第 4 项 |

Round5 importer `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c`、engine `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b`、kalman 未改。

本轮指纹：`multisensor.py` `dd9a0ea466688e26bd4c052e8eb06acd8d38892bac8d11b48f99cd33e01b254c`，`fusion.yaml` `ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342`。

工作区全量 pytest：276 passed、1 warning、58.27 秒。五场景覆盖 72/360/360/360/492，crossing RMSE 0.98385 米。默认 4097+flush 完整。真实 JSON 两视口 28/26/2。联调端口 18100，请求响应在 `reports/task007/r5/http/`。

本轮原始证据只在 `reports/task007/r5/`。真实三源同机 BLOCKED；鸟类识别、约 2GB SQL NOT_TESTED；Asia/Shanghai 未确认。
