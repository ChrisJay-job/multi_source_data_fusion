# 活跃来源集合契约（Round6）

## 三个含义（勿混用）

| 概念 | 定义 |
|---|---|
| **计划/已启用来源** | 场景中 `enabled` 的源（雷达等未启用者不在候选） |
| **正在发报来源** | 已启用且当前时刻不在 outage 区间（决定是否还会产生新观测） |
| **当前活跃来源** | 快照字段 `sources`：截至 **frontier** 的最后已交付观测仍在各自 TTL 内（对齐 `engine._active_sources`） |

## TTL（frontier − lastCommittedMT）

| 源 | 阈值 |
|---|---|
| `rid` | `rid_fresh_s`（默认 2.5） |
| `spectrum` / `radar` | `lifecycle.coast_s`（默认 4） |

- **outage = 停止产生新观测**，不撤销已接收观测的 TTL 宽限期。
- last MT 仅计 `measurementTime ≤ lifecycle_clock` 且已在 `delivered_obs` 中的行。
- `sourceTracks` 只做归属，不得回填或掩盖 `sources`。

## 双向校验（full 与 lifecycle 均适用）

对每个应评估轨迹：

- `missing_active` = expected − actual
- `unexpected_active` = actual − expected

任一非空 → `active_sources_mismatch`（FAIL）。不能只用「expected ⊆ actual」。全源计划停报时仍须在 TTL 宽限期内做集合核查；其他源仍在更新不能证明本源在线。

空 `sources` 合法，但必须与当时 expected 一致。
