# R2-01～R2-06 闭环表

| ID | 严重度 | 根因摘要 | 修复要点 | 验证 |
|---|---|---|---|---|
| R2-01 | P0 | 缓冲未成熟仍 predict→processingTime，随后合法点被 stale | 事件水位仅提交推进；展示预测副本；空批不跳水位 | Round2 irregular；realtime 2502→2502 |
| R2-02 | P0 | 非主源 predict + 生命周期再 predict，双积分 | 非主源不动主 KF；提交一次 dt | `test_secondary_prediction_*` |
| R2-03 | P0 | LSA 未匹配走 `_gated_pick` 宽松回退 | 未匹配 `_birth`；身份感知门限 | `test_global_gate_*` |
| R2-04 | P0 | 只查已提交 seen；冲突非原子 | 本批／缓冲／已提交；整批 conflict | duplicates／conflict 测试 |
| R2-05 | P1 | 淘汰后静默重执行旧 batch | CacheEntry complete／evicted／expired | cache eviction／TTL |
| R2-06 | P1 | 快照缺 altitudeDatum 等 | 补输出字段；确认与有效 sources 分离 | height datum 测试 |
