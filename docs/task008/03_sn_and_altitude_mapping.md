# SN 与高度映射（TASK-008 / R6-v5）

## 高度：`database_altitude_msl_v1`

| 项 | 约定 |
|----|------|
| 源字段 | 数据库/CSV 列 `altitude` |
| 语义 | **海拔高度 MSL（米）**（本版公司输入约定） |
| 写出 | `altitude` 数值 + `altitudeDatum: "MSL"`；元数据 `altitudeBasis=USER_ASSUMED`、`altitude_datum_not_verified` |
| 明确不做 | 不把 `height` 当海拔；不做 geoid/DEM 物理换算；不声称设备基准已核实 |

缺测保持 `null`（不填 0）。RID 协议未知哨兵 `-1000` → 空海拔。HTTP 与 MQTT 同规则。

## SN：`company_source_id_sn_v1`（公司默认）

| 源 | sourceTrackId | aircraftId |
|----|---------------|------------|
| RID | 原始 id 字符串 | 同 id（业务 SN） |
| 频谱（pp） | 原始 id 字符串 | 同 id（业务 SN） |
| 雷达 | 原始 id 字符串 | 空（局部目标 ID，不作 SN） |

`source_data` 中其它 SN 仅作证据；与业务 id 不同时记冲突，不静默覆盖。共享实现：`resolve_aircraft_id` / `apply_company_source_id_sn_v1`（importer + CSV MQTT sender）。

## SN：`confirmed_sn_v1`（旧夹具可选）

| 源 | 确认路径 | 缺失 |
|----|----------|------|
| RID | `source_data.identification1.idType == "Serial_Number"` 且存在 `uasIdAsString` | `aircraftId=null`，标记 unconfirmed |
| 频谱 | `source_data.serialNumber` | null / absent |
| 雷达 | 无 SN | 恒为 null |

旧「原始 id 当 SN」复选框仅对 `confirmed_sn_v1` 生效；公司模板不再依赖该勾选。

样本：`samples/task007/5_rid_pp5_leida1_simp.csv`、`5_leida_rid_pp.csv`。扫描证据：`reports/task008/r6/evidence/company_mapping_scan.json`。
