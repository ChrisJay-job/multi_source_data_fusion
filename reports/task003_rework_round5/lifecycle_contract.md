# 生命周期评估契约（Round5）

## 双时钟（对齐 `engine.py`，不改引擎）

| 时钟 | 来源 | 用途 |
|---|---|---|
| `lifecycle_clock` / frontier | 快照 `watermark`（缺省则 `processingTime`） | `trackStatus`、终止/缺席、`sources` TTL、last observation 截止 |
| `display_clock` | 快照 `processingTime` | `positionMode` 显示外推 / stale |

Realtime：`frontier ≈ processingTime − reorder_window_s`。Replay：`frontier ≈ processingTime`。禁止用 `max(pt, wm)` 混判全部状态。

## 阈值（`config/fusion.yaml` → `lifecycle_cfg`）

| 阈值 | 默认 | lifecycle 间隙 `gap = frontier − last_obs` |
|---|---|---|
| `predict_horizon_s` | 4 | ≤：`tracked`/`tentative`/`coasting` |
| `lost_s` | 12 | (h, lost]：`coasting`；禁止 `sources` 宣称在线 |
| `terminate_s` | 30 | (lost, term]：`lost`；**仅当 gap > 30** 允许从 `tracks` 消失 |
| `rid_fresh_s` / `coast_s` | 2.5 / 4 | 活跃源 TTL（frontier − lastSeen） |

Display：`disp_gap = processingTime − last_obs`；`disp_gap ≤ predict_horizon` 允许 `measured_assisted`/`predicted`/`stale`，否则仅 `stale`。

边界精确，不扩大状态集合、不人为容忍「时钟偏差」。

## last observation

只计 `measurementTime ≤ lifecycle_clock` 且已在 `delivered_obs` 中的观测（已交付且已到 frontier）。缓冲区未提交 / 未来接收的观测不提前计入。

## 字段契约（先于阶段业务判断）

必填：`trackStatus`、`positionMode`（缺失 / 空串 / 非法枚举 → `snapshot_field_contract` FAIL）。不用 legacy `status` 或历史值填造。`aircraftId` 等可空字段合法 null 不误报。

## 活跃来源 vs 历史绑定

- **活跃集合**：只读快照 `sources`；按场景启停/outage + 各源已交付 last MT + TTL（frontier）推导期望集合。
- **`sourceTracks`**：仅归属/关联；非空历史绑定不得掩盖 `sources=[]`。
- 慢周期导致 TTL 过期时，期望活跃可为空（不强制每源时刻在线）。

## 失败明细

含 `expected`/`actual`、`lifecycle_clock`/`display_clock`/`frontier`、`last_observation`、`gap_s`/`display_gap_s`、阈值，便于面板解释。
