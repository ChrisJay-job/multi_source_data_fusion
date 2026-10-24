# TASK-007 attempt-001 地图交互专项收尾记录

日期：2026-10-24（Asia/Shanghai）  
专项：地图缩放、真实航迹定位/查看、连续拖动、总览语义，以及已发生融合历史完整绘制与审查包测试复现

**状态：`REVIEW_PASSED_AWAITING_FREEZE`**

裁决依据：`D:\zwyl\02_algo_project\multi_source_data_fusion\review_zip\TASK-007-attempt-001-Map-Interaction-R2-Independent-Review-PASS-and-Closeout.md`  
该文件 SHA-256：`0b632fa4a236e07491e45dbb7b525f011717d3ef213cd0aca86622ddc2b3a8bf`（7395 字节）

独立审查结论：PASS。本专项治理状态：`REVIEW_PASSED_AWAITING_FREEZE`。  
本记录不覆盖既有 `TASK-007-review-closeout-record.md`（算法 R6 收尾另存）。不授权 commit、tag、push、冻结、合并或下一阶段。

## 1. 分支与工作区（只读）

| 项 | 值 |
|---|---|
| 工作树 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task006` |
| 分支 | `task-006-real-excel-import-and-cooccurrence` |
| HEAD | `6abc39d400c4cde60e0c56147e0442212f032b65` |
| 工作区 | dirty（`git status --porcelain` 约 127 行）。相对该 HEAD 仍有 TASK-006/TASK-007 过程改动与未跟踪文件。本轮仅新增本收尾记录，未改业务源码、配置、测试或样本，未重跑测试，未重打包 |

未宣称工作树干净；未执行 git add/commit/tag/push。

## 2. 通过对象：地图交互 R2 审查包

| 项 | 值 |
|---|---|
| 包名 | `TASK-007-attempt-001-map-interaction-rework-r2-review-bundle.zip` |
| 绝对路径 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task006\TASK-007-attempt-001-map-interaction-rework-r2-review-bundle.zip` |
| 字节 | 28913582（与裁决一致） |
| SHA-256 | `c1b83d25c1a64a88fe12746a02cbbabfe754ca36898240ed4b9d866808f9001f`（与裁决一致） |
| 包内 `source_sha256.txt` | 222 条（只读清点与裁决相符） |

本轮未重打 ZIP。

## 3. MI-R2 关闭依据（裁决 + 包内证据路径）

| 项目 | 裁决 | 依据摘要 |
|---|---|---|
| MI-R2-01 实际绘图完整性 | CLOSED | 独立 draw 探针：81/81、400/400，首点送入绘图。提交证据：`reports/task007/map_interaction/r2/draw_probe_result.json`（及 extract 复测记录） |
| MI-R2-02 fixture 闭包 | CLOSED | 全新解压完整收集 279 项：277 通过、2 跳过、0 失败，退出码 0。提交日志：`reports/task007/map_interaction/r2/pytest_extract.log` |
| 跨 fusionId 隔离 | VERIFIED_PASS | R1 反例保留；源三元组复用不混入他目标观测 |
| 历史收集 | VERIFIED_PASS | 收集器 81/81，保留首点 |
| current-only 适配 | VERIFIED_PASS | 当前点居中偏差 0 |
| 滚轮锚点 | VERIFIED_PASS | CSS 1200/900/600 × 20 步，最大误差约 7.96e-13 CSS px |
| 小 delta 连续缩放 | VERIFIED_PASS | 1px ≈ 1.000953556，100px = 1.1 |

绘制源码取消 longest-history-only；按 fusionId/segment 合并已发生提交并保留 GAP_MS。不以蓝色观测线替代粉色融合线声明通过。

## 4. 指纹核对（工作树只读，与裁决一致）

| 文件 | SHA-256 |
|---|---|
| `demo/workbench/canvas.js`（最终前端） | `bc1c9f397271f664b9a23c319c59068ab5a819ff47e4ca22b90d47f72deaa2b2` |
| `src/fusion_mvp/multisensor.py` | `f5d919551c5ebc921d617a314d8a6be86f818ffe1c6a5a95400097ffa662d6e2` |
| `config/fusion.yaml` | `ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342` |
| `src/fusion_mvp/workbench/importer.py` | `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c` |
| `src/fusion_mvp/engine.py` | `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b` |
| `src/fusion_mvp/kalman.py` | `a0e52d4b44c5fbf4b8e00a5627cf0369542e7065c7618a6cd17fa46b98b5a8ae` |
| `src/fusion_mvp/api.py` | `f4711452103d1085c9eb27b06bb6e777a1aed33b1600eb720289fccf7277a6bb` |

## 5. 独立与交付环境测试结果

| 主体 | 环境 | 结果 |
|---|---|---|
| 独立审查方 | 全新解压；Python 3.12.14 + 包内 requirements 固定版本；`pytest tests/ -q --tb=short -rs` + JUnit | tests=279，failures=0，errors=0，skipped=2 → **277 passed**，退出码 0，约 69.159 s |
| Cursor 交付记录 | 全新解压；Python 3.11 docker；`pytest_extract.log` | **277 passed，2 skipped，1 warning**，约 51.06 s，退出码 0 |

跳过（不计通过，既有外部完整 XLS 边界）：

- `test_detect_ole_xls`：`full XLS not linked in this environment`
- `test_page_late_and_mixed_sources`：`full XLS not linked`

上轮普通 JSON/CSV/仿真 fixture 缺失导致的 20 项失败已消除。

## 6. 浏览器与隔离证据（提交审阅，非本轮重跑）

权威目录：`reports/task007/map_interaction/r2/browser_isolated/`

| 项 | 值 |
|---|---|
| 视口 | 1920×1080 DPR=1；1280×800 DPR=2 |
| BASE | `http://127.0.0.1:18122`（隔离；本轮记录称已清理隔离项目） |
| 样本 SHA-256 | `32772531c62f4643503892fd31ce1e9e477eff86e482b17eb75b40f107d2d34b` |
| 图层 | 关闭 RID/频谱/雷达；仅 fused + current；列表「查看航迹」 |
| 静态 canvas | 两视口均为 `bc1c9f397271f664b9a23c319c59068ab5a819ff47e4ca22b90d47f72deaa2b2` |
| `browser_result.json` | `pass: true`（只读复核） |

验证主体边界：浏览器 / Docker / Windows 本机步骤由 Cursor 提交；审查方核验脚本、记录、截图与静态指纹，并独立运行 Node 反例与完整 Python 测试。审查方未在用户电脑浏览器或 Docker 中重新实操。旧 R1 混合版本证据已归档，不作为本轮依据。

## 7. 用户入口只读核对（18089）

| 项 | 结果 |
|---|---|
| 入口 | `http://127.0.0.1:18089/` |
| `/health` | `{"status":"ok"}` |
| `/workbench-static/canvas.js` SHA-256 | `bc1c9f397271f664b9a23c319c59068ab5a819ff47e4ca22b90d47f72deaa2b2` |
| 与最终前端指纹 | **一致**（无「运行资源版本不一致」） |

本轮未部署、未改容器。

## 8. 通过范围与仍存边界

**通过范围（本专项）：** 鼠标锚点缩放、真实航迹定位/查看、连续拖动、总览语义、已发生融合历史完整绘制、本包测试复现；状态 `REVIEW_PASSED_AWAITING_FREEZE`。

**不随本次 PASS 自动转为通过：**

- 真实三源同机关联与位置精度（缺正向现场真值验收）
- 雷达较多大样全量前端性能、约 252 MB 响应优化
- 鸟类识别、约 2GB SQL（NOT_TESTED）
- 设备实际时间语义与 Asia/Shanghai（待设备侧确认）

本专项通过不等于 TASK-007 全部客户现场算法验收完成，不等于代码已提交或合并；亦不替代算法 R6 收尾记录中的联调冻结条件。

## 9. 本轮动作与禁止项

已执行：只读核对裁决文件、R2 包字节/哈希、工作树与 18089 指纹、证据路径；新建本文件。

未执行：业务代码修改、重跑测试、重打包、commit、tag、push、冻结、合并、部署替换、下一阶段。
