# TASK-001 attempt-001 REWORK Round4 审查摘要

状态：**REVIEW_READY**（继续 attempt-001，不开 attempt-002，不冻结）

## 修前 / 修后

| 项 | 结果 |
|---|---|
| 锁定环境 | Docker `python:3.11-slim`；见 `locked_env.txt` |
| 修前 Round4 | **2 failed**（`pre_fix_round4.log`） |
| 修后全量 | **41 passed**（原 39 + Round4 2；`post_fix_all.log`） |
| 连续段 realtime／replay | apply=2502 / position_updates=2502 / stale=0（`post_audit_*.json`） |

## 统一事件水位规则

| 模式 | cutoff | 空批 | 迟到 |
|---|---|---|---|
| realtime | `processingTime − reorder_window` | 单调推进到 cutoff；主状态／生命周期／来源时效沿 frontier | 相对**上次已提交水位**拒绝（不再减一次 window） |
| replay | `processingTime` | 同上（虚拟时钟） | 同上 |

展示预测仍用 KF 副本；超过 predict_horizon 标记 stale 并停止移动。

## 裁决

| 维度 | 裁决 |
|---|---|
| 真实单源连续 | **PASS** |
| 软件 MVP（本轮时钟根因） | **PASS**（限制表仍登记，未宣称现场精度／映射全确认） |
| 真实三源关联 | **BLOCKED** |
| 现场精度 | **NOT_TESTED** |

## 已知限制（延续登记）

- 原始字段映射／无时区默认：待后端／设备确认
- KF／创新距离对角近似、门限未现场标定
- Cache 响应体有界；元数据／seen_obs 截断策略仍粗粒度
- `sourceTracks.bindingStatus` 未实现

## 证据

- 时序：`r4_step_traces.json`（空批→水位 t=8、sources 过期、mt=2 late 拒绝；Round3 延迟 2.5s 兼容）
- 闭环表：`r4_closure_table.md`
