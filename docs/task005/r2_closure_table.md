# TASK-005 attempt-001 REWORK Round2 闭环表

| 项 | 根因 | 修改文件 | 修前复现 | 修后结果 | 未测项 |
|---|---|---|---|---|---|
| R2-01 位置误差/ID交换 | committed 用展示坐标；id_exchange 靠 reason 字串；覆盖率自分母 | `evaluator.py` `position_errors`/`count_id_exchanges`；`metrics_display.py`；`runner.py`/`api.py` 共用 builder | audit：committed=20m；ID交换≈0 伪测量 | committed/display 分列末点；时间序列交换；缺分母→不可计算 | 现场真值精度 NOT_TESTED |
| R2-02 J/K 近距视图 | `updateNearDist` 用全图 H/I@14s 冒充聚焦对 | `app.js` `pairDistanceInfo`/`btnZoomNear`/`chkJumpNearTime` | 对=H/I 0m@14s | J/K 专属≈2m@0s；全图最小单独标记；可选跳转 | 像素可分辨依赖缩放 |
| R2-03 接收/处理/绑定计数 | delivered→已处理；source_binds→仅绑定 | `runner` `counts_at`；`app.js` `updateTransport`/`countsUpTo` | 首帧已处理=1 | 处理观测未提供可靠计数；source_bound≠bind_only | 观测冲刷精确计数仍 null |
| R2-04 检查器残留 | 空轨仅清 detail，不清 inspector/explain | `app.js` `updateTransport`/`showRun`/`clearInspectorPanels` | 切 2 机仍见机=A | 新 run/空快照清空；浏览器硬断言无旧 SN-A | 审查侧独立 E2E NOT_TESTED |

## 冻结

engine/kalman/mapping/models/config 字节级保持 Round1/TASK-003 Round6 口径；不调参消 FAIL。

## 状态

REVIEW_READY · attempt-001 · 禁止 commit/tag/push/下一阶段 · TASK-004 仍待确认 · 真实三源 BLOCKED · 现场精度/2GB NOT_TESTED
