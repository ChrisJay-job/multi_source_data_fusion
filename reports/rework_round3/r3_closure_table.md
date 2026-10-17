# R3-01～R3-02 闭环表

| ID | 严重度 | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| R3-01 | P0 | 空缓冲分支把 watermark／主 KF 推到 processingTime | realtime 空缓冲不推进事件水位与主状态；`mutate_filter=False` 仅老化 | `test_empty_flush_*`；2502 连续段 |
| R3-02 | P0 | 同刻 identity 列表保留输入顺序，频谱先到先建轨 | 按 `primary_source_order` 排序后 ingest | `test_same_time_source_order_*` |
