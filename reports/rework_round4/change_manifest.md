# REWORK Round4 变更清单

## 源码

- `src/fusion_mvp/engine.py` — 等价于 `reference_event_frontier_fix.patch`：
  - 新观测相对 `prior_watermark` 迟到拒绝
  - 合并缓冲后一次冲刷至 cutoff
  - 空批／有批均将 `event_watermark` 推进到 `max(wm, cutoff)`
  - 展示超时强制 stale
- `tests/test_round4_event_frontier.py` — 审查附带 2 项（未削弱）

## 未改

- Round1–3 证据保留；不重写关联／LSA／主源排序
- 不入 2GB SQL；不扩展仿真编辑器
