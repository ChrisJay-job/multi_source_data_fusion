# Round4 Event Frontier 闭环

| 项 | 处理 | 验证 |
|---|---|---|
| 空批推进 cutoff | `frontier = max(wm, cutoff)`，cutoff=pt−window | `test_empty_batches_*`；watermark==ts(8) @ pt=10 |
| 来源过期 | 生命周期／`_active_sources` 沿 frontier | sources 不含 rid；positionMode=stale |
| 迟到拒绝 | `mt < prior_watermark` → late_beyond_reorder_window | `test_old_observation_*`；无 reacquired |
| 合并后再冲刷 | 先 admit 再单次 flush | Round3 delayed 2.5 仍更新；2502 stale=0 |
| 展示超时 | gap>horizon → stale，不写回主 KF | patch `_snapshots` |
