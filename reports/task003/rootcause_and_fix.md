# TASK-003 根因与修复说明

日期：2026-10-19。分支：`task-003-workbench-usability-and-association`（基线 TASK-002 冻结 `5749a240…` / tag `task-002-fusion-validation-workbench-v1`）。

## 修前证据（附录四机，隐藏 20s 换号仍生效）

见 `reports/task003/pre_fix/`：

- delivered=197，processed_updates=134，snapshots=75（与指令一致）
- `radar-C-v2` 出现于约 t=21s（null→强制 20s）
- t≈39–43s：`radar-C-v2` 绑定到 `SN-A-001`（TRUTH-A）
- 评估仍按 name=`three_aircraft_primary` 硬编码 ABC 期望 → 匿名单源 C 记 missing、D 记 extra

## 根因

1. **隐藏换号**：`generate_observations` 在 `radar_id_swap_at_s is None` 时强制 20s，用户未启用仍换号。
2. **关联**：换号后新 `sourceTrackId` 走 LSA；RID 锚点航迹 innov 上限更松（11），远距匿名雷达可被吸到 A；缺同 base 航迹接续。
3. **评估**：`run_scenario_bundle` 按场景名写死期望；匿名雷达无 SN 时 `fusion_to_truth` 不归到 TRUTH-C。
4. **显示**：融合历史按 `positionMode` 分段且 `run.length < 2` 丢弃单点，结束帧只剩标记。

## 修复（算法侧，无 truth 绑定）

| 项 | 做法 |
|---|---|
| 无隐藏换号 | null = 不换号；显式 `radar_id_swap_at_s` 才换号 |
| 换号接续 | 同 detector + 同 base（去 `-vN`）几何门内 → `radar_id_swap_handoff`，退役旧 key |
| 防误绑 | 无连续性的 RID 航迹：innov≤8，且 `dist>90` 禁止首绑；连续性/handoff 优先降代价 |
| 动态评估 | 由飞机列表推导期望来源；匿名轨用源键一致真值归并 |
| 七机默认 | preset `seven_aircraft_combinations`；C `rid_sn=null` |

未改全局门限到「雷达不参与」；未用 truth 映射做绑定。

## 修后对照

| 场景 | 结果 |
|---|---|
| 附录四机（无换号） | 无 A←radar-C；entity PASS |
| 显式 20s 换号四机 | 无 A←radar-C；C 单实体 handoff；D 三源保留；entity PASS |
| 默认七机 | 稳定窗 7 实体 PASS |
| 原 76 + 本轮 | **83 passed**（Docker Python 3.11） |

真实三源关联仍 **BLOCKED**；现场精度 / 全量 2GB SQL 仍 **NOT_TESTED**。
