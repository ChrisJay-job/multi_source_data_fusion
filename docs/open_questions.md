# 未确认项（集中记录，不阻塞 MVP）

1. **高度基准**：DDL 写海拔米；存在 `-2` 哨兵候选；**禁三维门控**。
2. **heading**：频谱样例常与 `az`/`probeAz` 同值，**不作运动航向门控**；RID 存在 `361`。
3. **`aerial_sn`**：RID 大量为 `tcp`，语义是发现设备侧标记，**不是飞行器 SN**；RID 身份优先用 `id`/payload `uasIdAsString`。
4. **`created_at` vs `created_time`**：频谱大量 `created_time` 扎堆在导入时刻；测量时刻优先 `source_data.trackTime`，否则 `created_at`（假定）。
5. **`id` 列**：同行多时刻重复出现；是来源目标/航迹键，不是每条观测唯一键。
6. **雷达 `detector` 缺失**：部分行靠 `source_data.radarId` 回填；仍缺则拒绝。
7. **空间共现**：全库时间窗有重叠，但抽样点跨天津/珠三角等，**未证明同目标三源同步航迹**。
