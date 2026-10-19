# TASK-003 Round3 根因与修复

日期：2026-10-19。分支：`task-003-workbench-usability-and-association`。状态：**REVIEW_READY**。

保留：原 88 项 + Round1/2 历史显示与关联修复；本轮合计 **92 passed**。

## R3-01 分阶段覆盖漏判

**根因：** 仅用全局 earliest/latest outage 生成两端窗口，中间恢复与停源期不检查。

**修复：** `evaluation_phases_from_bundle` 合并重叠/连续 outage，生成 `pre_outage`、每段 `outage_i`（lifecycle）、每次 `recovery_i` 与最终 recovery；确认时长 ≥ max(4s, 2×周期)。`evaluate_run` 按阶段独立计分再聚合；lifecycle 允许 predict/stale/lost，但目标无故消失 → FAIL。

## R3-02 预测片段串线

**根因：** 按 fusionId 汇集全部 predicted 点，8s 才断线，跨实测恢复仍连成一条。

**修复：** 按快照序列维护预测 episode；非 predicted（实测恢复）立即闭合；输出多条虚线。

## R3-03 浏览器产品行为

**根因：** Round2 脚本自写 anomaly DOM/onclick。

**修复：** `browser_workbench_task003_round3.mjs` 注入评估数据后调用产品 `renderAnomalies`/`renderResultPanels`；真实点击跳转；G 编辑/导出重载/拖动正对照/终止历史/观测检查器均走产品路径。

## 验证

- pytest 92 passed（Docker 3.11）
- `probe_prediction_episodes`：2×2 点虚线；`probe_history_round2` 仍 PASS
- Playwright hardFail=0（1366 / 1920）

边界：真实三源 **BLOCKED**；2GB **NOT_TESTED**（见 `history_resource_bounds.md`）。
