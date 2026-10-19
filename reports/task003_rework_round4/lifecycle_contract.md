# 生命周期评估契约（Round4）

## 配置来源（`config/fusion.yaml` → runner `lifecycle_cfg`）

| 阈值 | 默认 | 含义（相对 last measurement ≤ clock） |
|---|---|---|
| `predict_horizon_s` | 4 | ≤：允许 tracked/tentative/coasting + measured*/predicted（边界可 stale） |
| `lost_s` | 12 | (h, lost]：coasting/lost + stale/predicted；禁止 `sources` 宣称在线 |
| `terminate_s` | 30 | (lost, term]：lost + stale；>term：允许从 tracks 消失 |
| `rid_fresh_s` | 2.5 | 与引擎活跃源新鲜度对齐（评估侧禁伪新鲜） |

时钟：`max(processingTime, watermark)`，与快照内已推进的 `trackStatus` 对齐。

## 字段

- 读 **`trackStatus`** / **`positionMode`** / 活跃 **`sources`**（不用内部 `status`；`sourceTracks` 仅归属，不证明当前在线）。
- 缺 `trackStatus` → FAIL（`missing_trackStatus_field`）。

## 每实体预期

- 按场景每机启用源与 outage 推导 `expected_now`；仅该实体全部应出源均停报时走 lifecycle 带；兄弟机仍 full 检查。
- 尚无交付观测：`not_yet_detected`，不强求建轨。
- 无快照且窗口内无交付：`NOT_TESTED`（非算法 FAIL）。
- 终止后正常缺席允许；提前清空 → `missing_entity`。
- 失联期伪装 `tracked`+`measured`+`sources=[rid]` → `lifecycle_state_mismatch` / `stale_sources_still_fresh`。

失败明细含 expected/actual、gap、band、thresholds，便于页面解释。
