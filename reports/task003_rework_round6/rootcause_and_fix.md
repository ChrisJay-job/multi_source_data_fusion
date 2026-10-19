# Round6 根因与修正

## 3.1 outage 立即剔除候选

`_expected_sources_at` 在 outage 开始瞬间去掉 RID，TTL 宽限期内 expected 不含 RID，引擎仍正确保留 → 漏判提前失活。

**修**：候选 = 已启用来源；活跃 = frontier 上最后已交付观测仍在 TTL 内。outage 只影响后续是否有新观测。

## 3.2 仅子集检查

`need ⊆ have` 漏判过期 RID 仍挂在 `sources`（spectrum 仍鲜活时整机 gap 很小）。

**修**：`_diff_active_sources` 双向 `missing_active` / `unexpected_active`；full 与 lifecycle 均执行；去掉 outage 分支 `continue` 跳过。

## 冲突单测

`test_outage_schedule_excludes_source_from_active` 改为 TTL 宽限/过期两条时间线（Round6 要求）。
