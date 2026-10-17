# TASK-001 attempt-001 REWORK Round3 审查摘要

状态：**REVIEW_READY**（继续 attempt-001，不开 attempt-002，不冻结）

## 修前 / 修后

| 项 | 结果 |
|---|---|
| 锁定环境 | Docker `python:3.11-slim`；见 `locked_env.txt` |
| 修前 Round3 回归 | **2 failed**（`pre_fix_round3.log`） |
| 修后全量 | **39 passed**（原 37 + Round3 2；`post_fix_all.log`） |
| 连续段 realtime／replay | 仍为 apply=2502 / position_updates=2502 / stale=0（`post_audit_*.json`） |

## R3-01 / R3-02 闭环

| ID | 处理 |
|---|---|
| R3-01 | realtime 空缓冲不再把 watermark／主 KF 推到 processingTime；仅 status-only 老化；展示预测仍用副本。replay 虚拟时钟仍可沿 processingTime coast |
| R3-02 | 同事件时刻按 `primary_source_order`（默认 rid→spectrum→radar）稳定排序后再 ingest；主滤波由优先来源初始化／更新，其余二次绑定 |

## 裁决（分开）

| 维度 | 裁决 | 说明 |
|---|---|---|
| 本段真实单源行为 | **PASS**（已核验，保持） | 2502 逐观测 |
| 软件 MVP 总体 | **PASS（相对本轮 39 项 + 定向缺口）** | R3-01/02 已关；§4 已知限制仍登记 |
| 合成场景 | **PASS** | Round3 + 既有回归 |
| 真实三源关联 | **BLOCKED** | 无同步同目标真值 |
| 现场精度 | **NOT_TESTED** | |

> 复审原文写「总体暂不能 PASS」针对修前缺口；本轮定向两项已修并通过附带断言后，软件 MVP 相对本轮范围标 PASS，同时保留 §4 限制表，避免过度承诺。

## 已知限制与状态（Round3 §4 登记）

| 项 | 状态 |
|---|---|
| CacheEntry 响应体有界；evicted／expired 元数据与 seen_obs 截断 | **部分**：响应淘汰已实现；元数据／seen 有上限截断，恢复／过期策略仍粗粒度，**不宣称内存全部有界或 TTL 全部闭环** |
| `_mahalanobis` 对角近似；门限 6／11 | **近似未标定**：已说明；门限仍为配置旁硬编码常量，非现场标定 |
| 原始字段映射／无时区默认 UTC | **待后端／设备确认**；标准契约可信身份由明确输入负责 |
| 标准 processingTime 无时区 | **历史适配假设档仍接受**；正式标准入口应带时区（既有拒绝路径保留） |
| sourceTracks.bindingStatus | **未实现**：接口规格待补；当前仅 sources 列表 |

## 证据路径

- 修前：`pre_fix_round3.log`
- 修后：`post_fix_all.log`、`post_audit_realtime.json`、`post_audit_replay.json`
- 逐步对照：`r3_step_traces.json`
- 闭环表：`r3_closure_table.md`
