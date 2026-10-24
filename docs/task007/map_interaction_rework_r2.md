# TASK-007 地图交互 REWORK R2

日期：2026-10-24。状态：**待独立审查**。

指令：`review_zip/TASK-007-attempt-001-Map-Interaction-Independent-Review-REWORK-R2.md`  
SHA-256：`1d09dbb3a299164880cd9ba122fea8c59b806ad5492a5c76215b15041061f379`

## 关闭表

| ID | 结果 | 证据 |
| --- | --- | --- |
| MI-R2-01 绘制路径并集 | **PASS**（81/81、400/400；首点送入 `_poly`） | `r2/draw_probe_result.json`；两视口 `r2/browser*/browser_result.json` |
| MI-R2-02 审查包 fixture 闭包 | **PASS**（全新解压 pytest 见原始日志） | `r2/pytest_extract.log`；`r2/isolated_repro.json` |

保留：R1 锚点／归属隔离／current-only 适配／拖动；算法指纹未改。

## 绘图修复

`draw()` fused HISTORY 取消「最长一份 committedHistory」；按 fusionId\|\|segment 跨快照并集去重（`_commitPointKey`），再经既有 `GAP_MS` 断线绘制。与 `collectFusionTrackPoints` / `fitToData` 同口径。

## 打包

白名单补入 `samples/workbench`、`samples/task006`、`review_zip/TASK-007-approved-round5/TASK-007/examples`。完整 XLS 若缺席仍按既有 skip；普通 JSON/CSV 不得豁免。

## 指纹

- multisensor.py：`f5d919551c5ebc921d617a314d8a6be86f818ffe1c6a5a95400097ffa662d6e2`
- fusion.yaml：`ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342`
