# TASK-005 attempt-001 REWORK Round1 闭环表

| 项 | 根因 | 修改文件 | 修前复现 | 修后结果 | 未测项 |
|---|---|---|---|---|---|
| R1-01 包缺源码/样例 | pack 白名单漏 `sql_stream/geo/__init__` 与 `samples/workbench` | `scripts/pack_task005_rework_round1_bundle.py`、`_verify_clean_bundle_task005.sh` | clean_bundle ModuleNotFoundError | 新包含完整 `src/`+脱敏 samples；干净解压跑 pytest 入包 | 审查侧 Py3.12≠交付 Docker3.11 差异仅记录 |
| R1-02 几何校验 | 靠名字解析 `near5`；空 checks 却 ok | `scenario_challenges.py`、`scenario.py` intent、矩阵脚本 | 5/10/30/100m geometry.ok=false；outage/swap checks=[] | intent 结构化；全档位；七机分组校验；空 checks→unverified | 无大规模随机搜索（按要求不做） |
| R1-03 身份对照 | with_id 实为混合；anon 换传感器 | 同上 + `actual_identity_sets` + UI emit 开关 | mixed 被标 with_id；2m anon 变双雷达 | both_id/both_anon/mixed；公平对照仅切 emit；审计进算法身份 | 雷达仍不伪造 SN |
| R1-04 解释面板 | obs 早退；事件/拒绝无时刻与归属过滤 | `demo/workbench/app.js` | 旧解释残留；未来事件；全局拒绝归因当前目标 | 观测也刷新；当前时刻/整次分列；未提供归属进全局区 | UI 探针≠E2E（E2E 见浏览器证据） |
| R1-05 聚焦/指标 | 平铺筛选；聚焦 all；2m 不限长轴；metrics 未读 | `app.js`/`canvas.js`/`index.html`/`runner.py`/`api.py` | 筛选平铺；最近距被比例尺盖；指标不可见 | 分组 details；聚焦选项；maxSpanM；nearDist；metrics_display UI | 真值对齐 RMSE 依赖 timeline；缺则标不可计算 |
| R1-06 运行混用 | 等旧 snapshots；导出可无下载 | `app.js` + `browser_workbench_task005.mjs` | 切 2 机仍断言旧 13 机 | 等匹配 POST；banner/runId；强制下载重导 | 慢响应反例以 reqToken 丢弃旧响应覆盖 |

## 冻结

engine/kalman/mapping/models/config 未改门限消 FAIL。原始 FAIL 保留。

## 状态

REVIEW_READY · attempt-001 · 禁止 commit/tag/push/下一阶段 · TASK-004 仍待确认 · 真实三源 BLOCKED · 现场精度/2GB NOT_TESTED
