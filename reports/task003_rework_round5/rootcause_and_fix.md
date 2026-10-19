# Round5 根因与修正

## R5-01 评估时钟混用

**根因**：`evaluator` 用 `max(processingTime, watermark)` 判生命周期间隙；realtime 下 frontier 落后 processingTime 约 `reorder_window_s`，导致 42/43s 清空 tracks 时按 display 间隙 >30 误判为可终止缺席。

**修正**：`lifecycle_clock=watermark`，`display_clock=processingTime`；trackStatus/缺席/sources TTL 用 frontier；positionMode 用 display；last_obs 截止到 frontier。不改引擎时钟。

## R5-02 字段校验被绕过

**根因**：仅在 `st_name is None and "status" in tr` 时记缺字段；同时缺 `trackStatus` 与 `status` 则静默；且只在 outage/过期带查枚举。

**修正**：阶段业务前对快照内每条轨迹做必填/类型/枚举校验（`snapshot_field_contract`）；禁止用 legacy `status` 填造。

## R5-03 历史绑定掩盖空活跃源

**根因**：`have = active_srcs or _bound_sources(tr)`，`sources=[]` 时回退 `sourceTracks`。

**修正**：活跃集合只读 `sources`；期望活跃由 outage + 已交付 last MT + TTL 推导；`sourceTracks` 仅归属。
