# TASK-003 Round2 根因与修复

日期：2026-10-19。分支：`task-003-workbench-usability-and-association`。状态：**REVIEW_READY**。

保留 Round1：不透明 ID、一对一 LSA、`committedHistory`、结果面板契约、原 87+ 回归。

## R2-01 预测历史虚线

**根因：** `layers.pred` 只取 tIndex−3…当前预测点画菱形；虚线仅为 speed/heading 方向示意（hint 色），不是算法预测轨迹。

**修复：** 按 `fusionId||trackSegmentId` 汇集截至播放时刻的预测显示坐标（`predictedHistory` 或快照 `positionMode=predicted`），画 `#ff6b6b` 虚线折线并按时间空档分段；关闭 pred 层移除预测线；方向示意仍用 hint 色单独标注。

## R2-02 终止后提交历史

**根因：** 只读 `nowSnap.tracks` 的 `committedHistory`；目标离开 tracks 后历史线为 0。

**修复：** 扫描 `snapshots[0..tIndex]` 归档最长提交历史，按播放时刻截断未来点；活目标标记仍只来自当前帧。

## R2-03 恢复阶段评估

**根因：** `stable_window` 止于最早 outage−1，恢复段不评估，整次仍可 PASS。

**修复：** `evaluation_phases_from_bundle` 生成 pre_outage/stable + recovery（outage 结束后 +confirm）；`evaluate_run` 逐阶段检查；缺 recovery 覆盖时不得整次 PASS；附件恢复漏目标反例 → FAIL。

## 验证

- pytest：**88 passed**（Docker Python 3.11）
- Node `probe_history_round2.cjs`：预测虚线≥1、终止后提交线≥1
- Playwright：1366×768 / 1920×1080，中段实线/虚线、关预测、异常跳转、无横溢

边界：真实三源 **BLOCKED**；现场精度 / 2GB **NOT_TESTED**。
