# TASK-003 attempt-001 Round3复审 / Round4整改

日期：2026-10-19。结论：**REWORK_REQUIRED**。继续现有 attempt-001 / Round4，不冻结、不 commit/tag/push，不开始下一阶段。

## 已闭环，保留成果

Round3 包外部 SHA-256 `8d5dfe40707a3ddb175f75158876e28ab67fd03416d1a07294854dcc44449e4c`，与实际附件一致。

- 上一轮原始两项阶段覆盖反例，独立重跑 **2 passed，3.50s**：中间恢复漏目标、停源期间提前消失不再整次 PASS。
- 原始预测 episode Node 探针通过：**两条各 2 点虚线**，不再跨中间实测串线。
- 原始历史探针通过：预测历史虚线 1 条、目标终止后提交历史 1 条。
- 浏览器脚本确已去掉自写异常 DOM/onclick，改用产品原生 renderAnomalies/renderResultPanels 和点击 handler。认可 G 编辑、导出重载、正反拖动控制、终止空帧、原生异常跳转等证据的改进。
- 历史资源边界说明已提交：单 run 内完整历史、无服务端分页/增量索引、2GB 全量资源未测。保留这一限制，不要求本轮改存储架构。

全量独立回归结论见同包 `independent_verification.json` 和 `full_pytest.log`。独立环境 Python 3.12 + requirements.txt；提交方 Docker 3.11 结果须保留。复审没有独立运行真实浏览器，浏览器结论为提交脚本/JSON审计；Node 为产品实际 JS 加桩，不冒称浏览器 E2E。

## R4-01 生命周期评估没有遵守真实输出契约：P0

问题集中在 evaluator，不要求重写引擎。附件 `test_lifecycle_contract_round4.py` 独立复现 **3 failed，3.01s**。

| 反例 | 输入/故障 | 当前裁决 | 应有行为 |
|---|---|---|---|
| 正常终止后重建 | 单 RID，80 秒，12–50 秒停源，无故障注入 | outage_0 FAIL，恢复段 PASS；首次缺失报在 44 秒 | 超过配置 terminate_s 后当前 tracks 可正常移除，不能判漏目标 |
| 起始无检测 | 单 RID，40 秒，0–10 秒停源，无故障注入 | outage_0 无快照 -> FAIL，恢复段 PASS | 尚无观测时不要求已建轨；缺阶段证据可 NOT_TESTED，不能无依据判算法失败 |
| 应失联却伪装新鲜实测 | 单 RID，55 秒，12–38 秒停源；仅在 evaluator 输入副本中把 26–29 秒原本 lost/stale 改为 tracked/measured、sources=[rid] | 整次 PASS | 必须捕获状态/定位模式/来源时效不符，不能整次 PASS |

前两例是自然运行，不修改引擎或评估快照。第三例仅修改评估输入副本，原始状态断言确为 `(lost, stale)`，不向融合算法传真值。正常运行证据见 `normal_lifecycle_evidence.json`。

### 明确根因

1. `src/fusion_mvp/models.py` 的 TargetSnapshot 字段是 **trackStatus**；engine._snapshots 输出也是 trackStatus。evaluator.py 约 414 行却读 `tr.get("status")`，标准接口上为空，后面的 `if st_name and ...` 直接跳过验证。
2. 即使改字段，ALLOWED_LIFE 只是一个宽泛状态集合，还混入 positionMode 名称，没有基于时间推导应有状态。合法枚举 `tracked` 也可能在当前失联时刻是错误状态，不能只校验是否属于集合。
3. `matched` 为空时无条件 missing_entity；引擎 `_snapshots` 明确不输出 terminated 目标。要求当前帧必须有“terminated marker”与真实输出契约冲突。终止事件/历史用于核查，不应强迫引擎永远返回已终止实体来迁就 evaluator。
4. 当前阶段仍是全场景所有源 outage 的并集：一个飞机某源停报，便把其他仍工作的飞机和来源也置入宽松 lifecycle 模式。需按实体/来源生成动态预期，不能整个窗口一律只查“存在”。

### 本轮修复范围

1. 写清并落实独立评估契约：每个 truth 何时尚未出现、已建立、允许预测、stale/lost、允许终止消失、恢复待确认、重新可见。按目标/来源计算，不能用统一“停源阶段允许任何状态”替代。
2. 使用真实 **trackStatus** 和 positionMode；缺失字段/非法枚举不能静默计 PASS。检查时间相关的正确性，包括来源是否仍新鲜。输出 sources 为活跃源；历史 sourceTracks 保留过期绑定不能证明当前在线。
3. 时间轴要与冻结的引擎契约对齐：生命周期及来源时效沿已提交 frontier/watermark，显示预测使用 processing/display 时间。不要简单以 processingTime 代替所有事件时钟。阈值来自运行配置：当前 predict_horizon_s/coast_s=4、lost_s=12、terminate_s=30，注意边界比较符。
4. 评估预期应依据场景、交付观测/时间、水位和配置独立推导，不能直接把待验证的算法 trackStatus/sources 当正确答案，也不能把未来观测提前用于当前关联归属。存在关联歧义或缺信息时明确 UNDETERMINED/NOT_TESTED。
5. 终止前提前消失仍须失败；超过允许终止时限的正常缺席须允许；起始尚未有首条观测不强求实体。恢复确认后重新检查存在/唯一性/来源，不要求强制延续原 fusionId（除非接口另外承诺身份连续）。
6. 所有 outage 边界保留，但每阶段按每机每源给出预期。某源停报时，其他飞机/其他活跃来源仍要完整检查；长周期、错峰起飞、重叠停源、短恢复间隔不得静默逃逸成整次 PASS。
7. 阶段状态独立计算后聚合，保留 Round3 已修的阶段互不污染行为；无快照区分“本来不要求目标/无适用证据”与“应有输出却缺失”，不能统一 FAIL 或统一 PASS。覆盖不足仍明确未测。

### 必须保留/新增的验证

- 保留原 92 项、之前两轮 Node 历史/episode 探针和两个阶段漏目标反例。
- 修过附件三例，前两例不准通过增加假目标、禁止正常终止、无限延长 TTL 来解决；第三例不准只识别测试常量或异常组合，必须真实按时间契约判定。
- 补对应正例：正常失联转 stale/lost/终止/恢复；边界前后；起始无检测；多机仅一机停源时另一机漏目标或错误失联能够被捕获。
- 报告中列出 expected/actual、时间轴、阈值来源和失败原因，让页面 FAIL 能解释为什么错。

## 浏览器证据口径补齐：保留已通过交互，不重跑整套无关功能

本轮认可产品原生 handler 已被调用。剩余证据仍需如实划分：

- 当前观测检查器测试直接调用 `map.onPick(target,"obs")`，证明回调到详情渲染，**不等于真实鼠标命中轨迹点**。补一次实际点选（可先通过投影计算屏幕坐标），断言选中 observationId/source/measurementTime 与目标一致；无需把已通过的回调测试作废。
- `run_reflects_g_speed` 用 `runState.scenario || draftScenario` 取值，后者只是输入草稿。改为核对实际请求体或返回生成观测，避免草稿正确但请求未采用仍 PASS。
- 预测/融合线当前仅断言存在并记录两个 sample，尚未与快照坐标逐点核对。可在既有受控 fixture 中补一次按目标/episode 的坐标断言，不要求每种预置重新全量浏览器回放。
- 异常跳转 JSON 已显示跳到正确时刻且 pinned 对象正确，认可此证据；建议将 pinnedDetail 的目标 ID 以及 FAIL 面板直接写成硬断言，避免 `或异常条目存在` 代替面板通过。
- `hardFail=0` 不等于所有项已测，汇总同时列 NOT_TESTED/note 数和关键未测项。不得用测试自写 DOM/handler 代替产品行为。

若上述无新增业务问题，作为验收证据补齐即可，不引出 UI 重设计、全量队列回归或新功能。

## 回传

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_lifecycle_contract_round4.py -q
```

先记录附件反例修前，修复后保留正反例与解释性阶段输出。回传 `TASK-003-attempt-001-rework-round4-review-bundle.zip`，含完整代码/测试、修前后日志、生命周期预期契约及配置引用、浏览器有效补证、闭环表、源码哈希和 Git 状态；外部给最终 ZIP 哈希。

停在 REVIEW_READY，不 commit/tag/push、不冻结，不开始 TASK-004。真实三源同目标关联 **BLOCKED**；现场精度、约 2GB SQL 全量 **NOT_TESTED** 不变。原 TASK-001/TASK-002 标签和当前分支保留。
