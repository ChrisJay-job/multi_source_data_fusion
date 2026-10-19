# TASK-003 Round4 根因与修复

日期：2026-10-19。分支：`task-003-workbench-usability-and-association`。**REVIEW_READY**。

保留：92 项基线 + 历史/episode 探针；本轮合计 **97 passed**。

## R4-01 生命周期契约

**根因：** 读 `status` 非 `trackStatus`；缺席一律 missing；无时间带；全局 lifecycle 放宽所有机。

**修复：** 时间带对齐 `predict_horizon/lost/terminate`；读 trackStatus；终止后允许缺席；起始无观测 NOT_TESTED；伪新鲜实测 FAIL；按实体 outage 决定 lifecycle vs full。

## 浏览器补证

请求体/返回 scenario+observations 核对 G 速度；折线 sample 对历史坐标；真实鼠标点选；FAIL 面板与 pinnedDetail 硬断言。

## 验证

- pytest 97 passed（Docker 3.11）
- Playwright hardFail=0（summary 含 not_tested/notes 计数）
