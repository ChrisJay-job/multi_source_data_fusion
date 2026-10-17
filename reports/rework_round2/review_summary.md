# TASK-001 attempt-001 REWORK Round2 审查摘要

状态：**REVIEW_READY**（继续 attempt-001，不开 attempt-002，不冻结）

## 修前 / 修后

| 项 | 结果 |
|---|---|
| 锁定环境 | Docker `python:3.11-slim`；见 `locked_env.txt` |
| 修前 Round2 回归 | **8 failed**（`pre_fix_round2.log`） |
| 修前连续段 realtime | apply=2502 / updates=513 / stale_obs_ignored=1989（`pre_audit_realtime.json`） |
| 修后全量 | **37 passed**（`post_fix_all.log`：Round1 回归 + T01–T12 + Round2 8 项 + extras） |
| 修后连续段 realtime | apply=2502 / position_updates=2502 / stale=0（`post_audit_realtime.json`） |
| 修后连续段 replay | apply=2502 / position_updates=2502（`post_audit_replay.json`） |

计数口径：`position_updates` = `_apply_update` 成功导致 hits 增量；不以请求数 / after_hits 猜测代替。

## R2-01～R2-06 闭环

| ID | 处理 |
|---|---|
| R2-01 | 提交事件水位 `event_watermark`；缓冲未成熟不借 processingTime 推进主 KF；展示预测自 KF 副本；空批按水位；窗口外显式拒绝 |
| R2-02 | 非主来源只绑定不 predict 主 KF；提交路径每个 dt 只积分一次；跳点拒绝不留半写状态 |
| R2-03 | LSA 未匹配直接 `_birth`，禁止 `_gated_pick` 回退；身份感知创新门限；同设备占用；歧义有确定路径 |
| R2-04 | 本批／缓冲／已提交三阶段观测身份统一检查；同 ID 不同内容整批 `observation_id_conflict`；静默忽略≠成功 |
| R2-05 | `CacheEntry` complete／evicted／expired；淘汰与 TTL 后重放返回明确错误，不静默重执行 |
| R2-06 | `TargetSnapshot.altitudeDatum`／`displayStateTime`；有效 sources 与确认分离；非有限值走拒绝／降级 |

## 裁决（分开）

| 维度 | 裁决 | 证据 |
|---|---|---|
| 软件 MVP 行为 | **PASS**（相对本轮 37 项回归） | `post_fix_all.log` |
| 合成场景 | **PASS** | Round2 8 项 + extras |
| 真实单源连续回放 | **PASS（行为级，逐观测）** | realtime/replay 对照：2502/2502 更新，stale=0 |
| 真实三源关联 | **BLOCKED** | 仍无同步同目标真值 |
| 现场精度 | **NOT_TESTED** | |

## 连续回放守恒

| 指标 | 修前 realtime | 修后 realtime | 修后 replay |
|---|---:|---:|---:|
| 输入观测 | 2502 | 2502 | 2502 |
| apply_calls | 2502 | 2502 | 2502 |
| position_updates | 513 | 2502 | 2502 |
| stale_obs_ignored | 1989 | 0 | 0 |
| explicit_rejections | 0 | 0 | 0 |
| buffer flush 前／后 | 6／0 | 6／0 | 0／0 |

## 已知限制

- KF 未现场标定；完整 2GB SQL 不入包
- 三源同目标真值仍缺 → 三源关联 BLOCKED
- 连续段来自有界扫描样本，不是全库最长证明
