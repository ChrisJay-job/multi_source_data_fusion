# TASK-001 attempt-001 REWORK Round1 审查摘要

状态：**REVIEW_READY**（不停 attempt-002，不冻结）

## 修前 / 修后

| 项 | 结果 |
|---|---|
| 锁定环境 | Docker `python:3.11-slim`；见 `locked_env.txt` |
| 修前回归 | **11 failed**（`pre_fix_regressions.log`） |
| 修后全量 | **29 passed**（`post_fix_all.log`：review 11 + T01–T12 12 + extras 3 + 已含收紧断言） |

## 缺陷闭环

| ID | 处理 |
|---|---|
| R01 | 事件水位提交；先冲刷缓冲再收新观测；展示预测用副本；水位单调 |
| R02 | 可信身份可填充无身份近距航迹，保留原 fusionId |
| R03 | 先选主源；非主源只绑定不更新主 KF |
| R04 | 物理拒绝进入拒绝对；归并再门控；绑定再门控 |
| R05 | 按设备微批 `linear_sum_assignment` + 未匹配代价 |
| R06 | 请求指纹含 time/mode；跨批观测去重；事务快照回滚；session 锁；HTTP 409 |
| R07 | 标准 Observation 与 raw 适配分离 |
| R08 | 经纬度范围；频谱 heading→null；标准无时区拒绝 |
| R09 | sources 仅有效；idempotency TTL；max_tracks/cache；/ready 校验配置 |

## 裁决（分开）

| 维度 | 裁决 | 证据 |
|---|---|---|
| 软件 MVP 行为 | **PASS**（相对本轮回归与收紧 T03/T06/T07/T12） | 29 passed |
| 合成场景 | **PASS** | 同上 |
| 真实单源连续回放 | **PASS（行为级）** | `continuous_replay_*.json`；RID 连续段 2502 点 |
| 真实三源关联 | **BLOCKED** | 仍无同步同目标真值 |
| 现场精度 | **NOT_TESTED** | |

## 连续回放

- 段：`samples/continuous/segment.jsonl`（源 `tj-rid` / id `1581F6N8A2485ML323S2`，扫描前 20 万行内最长连续段）
- realtime：delivered 2502 / buffered 803 / updated 417 / rejected 0
- replay：delivered 2502 / updated 2502 / rejected 0

## Flow2Spec

- `flow2spec_version.txt` / `flow2spec_doctor.txt`（主机实测）

## 已知限制

- KF 未标定；完整 2GB 未入包；三源同目标真值仍缺
- 连续段来自有界扫描，不是全库最长证明
