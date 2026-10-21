# TASK-005 attempt-001 REWORK Round3 闭环表

| 项 | 根因 | 修改文件 | 修前复现 | 修后结果 | 未测项 |
|---|---|---|---|---|---|
| R3-01 ID交换假0 | `frames_mapped<2` 仍返回 0 | `evaluator.count_id_exchanges`；`metrics_display`；`app.js` 文案；指标文档 | 匿名/单帧→`id_exchange_count=0` | 同例→`null`+不可计算原因；可测稳定仍为真实0；互换/重建不变 | 匿名目标新匹配算法（本轮不做） |

## 冻结

engine/kalman/mapping/models/config 未改。Round2 已通过项不重开。

## 状态

REVIEW_READY · attempt-001 · 禁止 commit/tag/push/下一阶段 · TASK-004 仍待确认 · 真实三源 BLOCKED · 现场精度/2GB NOT_TESTED
