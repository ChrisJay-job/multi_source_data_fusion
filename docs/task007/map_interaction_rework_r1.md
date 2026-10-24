# TASK-007 地图交互 REWORK R1

日期：2026-10-24。状态：**待独立审查**。

指令：`review_zip/TASK-007-attempt-001-Map-Interaction-Independent-Review-REWORK-R1.md`  
SHA-256：`8d43c0a600ad15e6508dbbb23370e2e7e8a20906d033d2c1b58f10af95205d25`

## 关闭表

| ID | 输入 | 断言 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| MI-R1-01 | 同三元组跨 fusionId 观测 | 选中 B 不含 A 观测几何 | **PASS** | `r1/independent_counterexamples.json` → binding_reuse |
| MI-R1-02 | 两帧 80 点滚动历史 | 并集 81 点且保留首点 | **PASS** | 同上 → rolling_history |
| MI-R1-03 | 仅 current 图层 | 当前点距中心 ≤1 内部 px | **PASS** | 同上 → current_only_fit |
| MI-R1-04 | 两视口真实鼠标/UI/仿真编辑 | 全部步骤 pass，无 console error | **PASS** | `r1/browser/browser_result.json` |
| MI-R1-05 | 全新解压隔离服务 | 静态/算法 SHA 与包一致；浏览器指向隔离 URL | **PASS** | `r1/isolated_repro.json` |

保留：wheel 锚点修复；R6 算法指纹未改。

## 交互语义（适配可见）

- **current**：仅当前播放帧标记  
- **fused**：已发生 committedHistory（多帧并集去重）  
- **pred**：预测历史（同绘制规则）  
- **源图层**：measurementTime ≤ 播放时刻（与绘制一致，不含未来）  
- **查看航迹**：仅融合 committed（+current）；`obsPts` 仅在 observationId 被该目标 commits 声明时另计，不混入融合点数  

## 复现（隔离）

见包内 `README_MAP_INTERACTION_R1.md`。不要使用用户既有 18089；使用 `FUSION_PORT` 空闲端口与唯一 compose project。

## 未改范围

multisensor / fusion.yaml / importer / engine / kalman / API 契约 / CSV。大样全页性能、252MB、三源同机精度仍为 NOT_TESTED。
