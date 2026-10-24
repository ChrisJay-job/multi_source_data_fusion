# TASK-007 地图缩放与真实航迹聚焦专项整改

日期：2026-10-24。状态：**待独立审查**（未冻结 / 未 commit / 未合并）。

正式指令：`review_zip/TASK-007-attempt-001-地图缩放与航迹聚焦专项整改.md`  
SHA-256：`619a1d96f12a2e12c611b12997a344f17e833f17e03ebaf53ab49723a941a40f`（13118 bytes）

## 1. 根因

1. **滚轮无锚点**：`MapView` wheel 仅 `scale *= 0.9/1.1`，不调整 `ox/oy`，目标在偏离世界原点时被推出画布。
2. **聚焦偏仿真**：`fitToLabels` / `focusChallengeGroup` 依赖 scenario 标签与 `truth_polyline`；真实 `fusionId` 无可靠定位。
3. **拖动收尾弱**：仅 canvas 上的 mouseup；拖出画布释放易粘连，拖动易误触发 click 拾取。

## 2. 修改范围（仅前端交互）

| 文件 | 作用 |
| --- | --- |
| `demo/workbench/canvas.js` | `computeZoomAt` / `zoomAt`、Pointer Events 拖动、真实 `fusionId` 定位与航迹适配、可见范围 `fitToData`、选中态、比例尺 CSS px |
| `demo/workbench/app.js` | 定位／查看航迹入口、适配可见 vs 显示全部并适配、`__wb` 测试钩子 |
| `demo/workbench/index.html` | 按钮文案与 `focusStatus` |
| `scripts/task007_map_zoom_unit.mjs` | 锚点／互逆／限幅自动验证 |
| `scripts/task007_map_interaction_browser.mjs` | 1920×1080 / 1280×800 浏览器验收 |

**未改**：`multisensor.py`、`fusion.yaml`、importer、engine、kalman、后端 API、CSV 原始数据。

## 3. 交互说明

- **滚轮**：以鼠标下世界点为锚；`ZOOM_FACTOR=1.1` 互逆步进；处理 `deltaMode`；`deltaY=0` 无操作；`MIN_SCALE=1e-4` / `MAX_SCALE=200`。
- **拖动**：Pointer capture；CSS 像素阈值区分点击；拖出释放／cancel／失焦结束；拖动后抑制一次 click。
- **定位**：选中真实 `fusionId` 当前时刻位置居中；比例过大无意义时落到约 400 m 局部跨度；不改播放进度。
- **查看航迹**：仅收集截止播放时刻的 `committedHistory` + 绑定观测 + 当前位置；单点／直线可聚焦；当前无位置但有历史会提示；无历史不静默 fit 全图。
- **适配可见**：尊重勾选与图层，不清空过滤、不改时刻。
- **显示全部并适配**：显式清空勾选后再总览。

## 4. 浏览器访问入口

- 现有服务（工作树已挂载）：**http://127.0.0.1:18089/**
- 静态校验：`/workbench-static/canvas.js` 须含 `computeZoomAt`；`/workbench-static/app.js` 须含 `locateSelectedTrack`。
- 路径：真实文件回放 → 选 CSV → 预览 → 剖面 `multisensor-v1` → 回放融合 → 目标列表或检查器「定位／查看航迹」。

## 5. 测试摘要

| 项 | 结果 | 证据 |
| --- | --- | --- |
| zoom 锚点 20 步（中心／四角／偏原点） | PASS，误差 ≤ 1 CSS px | `reports/task007/map_interaction/zoom_unit_results.json` |
| 互逆恢复、deltaY=0、限幅 | PASS | 同上 |
| 两视口浏览器（1920×1080、1280×800） | PASS | `reports/task007/map_interaction/browser/browser_result.json` + PNG |
| 真实小样 `5_rid_pp5_leida1_simp.csv` | PASS（导入 472，拒 (0,0)×2） | 浏览器结果；SHA 匹配 |
| 大样 `5_leida_rid_pp.csv` | **NOT_TESTED** 全页性能（样本已入包核对 SHA） | 按指令用小样完成交互验收 |
| pytest | 279 passed | docker `fusion-task006-api` |
| 三源同机精度 | **NOT_TESTED**（本轮非目标；样本空间分离） | — |

## 6. 基线指纹（保持）

- `multisensor.py`：`f5d919551c5ebc921d617a314d8a6be86f818ffe1c6a5a95400097ffa662d6e2`
- `fusion.yaml`：`ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342`
- Round5 importer / engine / kalman：未改（见审查包 `source_sha256.txt`）

## 7. 剩余限制

- 大 CSV 全量页面流畅度未做性能验收。
- 本轮不新增自动跟随；手动缩放后播放／seek 不重置视角（已测）。
- 航线编辑依赖仿真侧既有入口；浏览器烟雾确认聚焦按钮仍可用，未重做完整路点编辑回归套件。
