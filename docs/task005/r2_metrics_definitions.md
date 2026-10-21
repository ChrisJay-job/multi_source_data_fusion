# TASK-005 Round2 指标定义与更新指南

## 位置误差（评估侧，永不入引擎）

| 指标 | 定义 | 范围 |
|---|---|---|
| `position_rmse_m_committed` | 末个 `committedHistory` 点 lat/lon vs 真值最近邻（max_gap=0.75s） | **末点**，非全程历史 |
| `position_rmse_m_display` | 顶层 lat/lon @ `displayStateTime` vs 真值 | 与已提交分列 |
| 不可计算 | 估计时刻超出真值时间跨度，或 gap>容差 | `error_m=null`，不报 0 |

## ID 交换（Round3 口径）

| 字段 | 定义 |
|---|---|
| `id_exchange_count` | 连续可映射帧上，两真值 fusionId **互为对换** 的次数 |
| `recreate_count` | 同真值换 fusionId 但无对换伙伴（拆轨/重建） |
| 统计范围 | 仅 `aircraftId→sn_to_truth` 可映射子集；匿名/未映射不在内 |
| 不可计算→`null` | 无快照；或 `frames_mapped<2`（全匿名/无映射/仅一帧可映射）——**禁止用 0** |
| 可测→数值 | ≥2 可映射帧时：稳定为真实 0；互换为 1；重建计入 `recreate_count` |

不再使用 `attribution_errors.reason` 含 swap/exchange 字串的启发式。有快照≠已完成测量。

## 覆盖率

| 字段 | 定义 |
|---|---|
| `last_snapshot_entity_coverage` | 末快照已映射真值实体数 / 期望稳定实体数 |
| 别名 `association_coverage` | 同值；**不是**观测正确关联比例 |
| 缺期望分母 | `null` + 说明；禁止 `len(bound)/len(bound)` |

## 快照计数 `counts_at`

| 字段 | 含义 |
|---|---|
| `delivered` | 已接收观测数（至本帧） |
| `processed_updates` | 主位置更新（hits 增量） |
| `processed_observations` | 可靠冲刷观测数；暂无法证明时为 `null`→UI「未提供可靠计数」 |
| `source_binds` | `source_bound` 事件 |
| `bind_only` | `secondary_bind_only` 事件 |
| `pending_buffer` / `rejected` | 缓冲 / 拒绝 |

矩阵若输出 `metrics_display`，沿用本定义；算法 FAIL 行保留，不调参。
