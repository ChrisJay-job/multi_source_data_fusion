# TASK-003 attempt-001 Round2复审 / Round3整改

日期：2026-10-19。结论：**REWORK_REQUIRED**。继续现有 attempt-001 / Round3；不冻结、不 commit/tag/push、不进入下一阶段。

## 已认可并保留

收到的 Round2 包 SHA-256 为 `cd76ad39ce17e5f54dd729ebd38965d236d8800b2eaa65f197f77095a89bbade`，与外部回传一致。

独立运行 `PYTHONPATH=src python -m pytest tests -q`：**88 passed，1 warning，43.89s**。复审环境 Python 3.12，requirements.txt 固定依赖；交付方 Docker 3.11 的验证单独保留。engine.py 与上一轮一致；不透明来源 ID、一对一关联和原回归须保留。

独立运行上一轮原始 `probe_history_round2.cjs`：预测历史虚线 1 条、目标终止后提交历史 1 条，均通过。原始“末四帧散点”和“终止后历史消失”两个反例闭环。单次停源最终恢复后漏目标反例也已纳入并通过。

以下是原需求未覆盖完的剩余行为，非扩大五源/真实设备接入范围。本轮新增 Python **2 failed，0.97s**，Node 预测分段反例失败。复审未独立运行真实浏览器；浏览器结论来自包内脚本和 JSON 审计，Node 为实际产品 JS 加 DOM/canvas 桩。

## R3-01 分阶段评估仍漏掉中间阶段：P0

依据：`src/fusion_mvp/workbench/scenario.py:576–604` 只取全局 `earliest_interrupt` 和 `latest_end`，生成首次停源前及最后恢复后两段；中间的多次恢复、停源行为没有实体完整性/生命周期检查。`evaluator.py` 仍使用同一个固定 expected_stable_entities 集合，不能表达各机各源的动态预期。

附件 `test_phase_coverage_round3.py` 两个可运行反例均仅在 evaluator 输入副本中注入故障，不改算法输入、不让真值参与关联：

| 场景 | 注入故障 | 当前结果 | 应有结论 |
|---|---|---|---|
| 单 RID，55 秒，12–18 / 32–38 秒两次停源 | 24–29 秒恢复期所有目标消失 | PASS，只查 8–11 / 42–53 秒 | 不能整次 PASS；恢复后的缺失须被捕获 |
| 单 RID，55 秒，12–38 秒停源 | 20–28 秒目标提前消失 | PASS，只查 8–11 / 42–53 秒 | 按已配置生命周期核查；未达到终止阈值不应无说明消失 |

未注入故障的相同两场景均为 PASS，24 秒均有 1 个目标，见 `phase_baselines.json`。第二例不是要求停源时仍上报 RID，也不要求 lost 目标继续有新定位；要求验证其状态和保留时限。若产品另行明确不输出 lost，应同步修订输出契约和评估，本轮不能静默跳过验证后给整次 PASS。

修复要求：

1. 按每机起飞、每源启用/采样周期、全部 outage 边界和恢复生成阶段预期，不能只用最早/最晚两个极值。重叠/连续 outage 正确合并；每次有效恢复均应覆盖。
2. 活跃期检查实体/来源/唯一性，停源期检查允许的预测、stale、lost、终止状态与时效；确认时间要考虑采样周期、事件水位和来源 TTL，不能固定 4 秒一概强求全源在线。
3. 输出覆盖窗口、每阶段结果和未测原因。确定错误 -> FAIL；必要阶段覆盖不足 -> NOT_TESTED/明确部分未测，不得凭两端片段命名整次 PASS。阶段结果须独立计算再聚合，避免前一阶段 FAIL 导致后面正常阶段也被写成 FAIL。
4. 保留全过程错误归属/重复目标检查、单次恢复漏目标测试及本附件两反例。补错峰起飞、慢周期、多次/重叠停源正例与故障例；不得靠放宽检查掩盖漏目标。

## R3-02 预测历史跨实测更新串线：P1

依据：`demo/workbench/canvas.js` pred 分支先跳过所有非 predicted 快照，再按 `fusionId||trackSegmentId` 聚集全部预测点；`flushRuns` 只有超过 8 秒才断线。主轨迹段不变、期间已恢复实测时，两个独立预测片段会被错误连接。

附件 `probe_prediction_episodes.cjs`：同一融合目标，1、2 秒为预测，3、4 秒为实测，5、6 秒再预测。期望两条各 2 点虚线，实际 **一条 4 点虚线**，把 2 秒直接连到 5 秒。该段不代表算法在 3–4 秒输出过预测历史，显示会误导。

修复：保留快照序列中预测状态的进入/退出边界，按实际预测 episode 再分段，不仅按目标/trackSegmentId 和大时间差。若从最近提交点锚定预测段，锚点须来自该段合法起点；不同目标、重生段、实测恢复前后不得串线。逐点核对实际坐标与 displayStateTime，测试保持关 pred 清除虚线、fused 实线不变、跳回旧时刻无未来点、终止后提交历史仍在。

## R3-03 浏览器证据验证了测试替身，不能算产品交互 PASS：P1

本轮不是没有运行 Playwright，而是关键断言对象失真。依据 `scripts/browser_workbench_task003_round2.mjs` 与对应 browser_evidence.json：

- 脚本约 289–300 行直接覆盖 `anomalyList.innerHTML` 并自写 `onclick`，自写处理器设置 `__r2SeekedIdx` 后再用它断言跳转。这样产品原生 `renderAnomalies` 和点击处理器即使失效也能通过。`fail_readable` 又读取这段手工写入的“误关联”文本，不证明产品 FAIL 面板渲染。
- G 的“修改成功”是 `note(speed=13)`；“其他飞机未变”只比较不包含速度/航点的列表文字。没有断言完整 draft 配置、运行请求/生成观测，也未保存重载。
- 拖动前未进入绘制航线状态，且 `routeEdit?.points?.length || 0` 对未创建编辑器同样返回 0；不能证明编辑状态拖动不增点。
- `obs_inspector` 为 note；实际 JSON 两视口都是 `hasSource=false / hasTime=false / sample=点击轨迹点查看`。这项应是未测，不能计入闭环 PASS。
- `end_committed_history` 最终帧仍有 7 个目标，不能证明“终止后”。历史线只按颜色数量判断、混有多次重画日志，未逐目标核对坐标。独立 Node 已证明基础终止反例修复，此处仍需完成原要求的真实浏览器链路。

请只修正/补全这条关键验收链，不必重测无影响的全部导入队列功能：

1. 实际点击选择 G、进入航线编辑，改速度和航点；读取完整场景证明仅 G 对应字段变化；运行请求或返回观测反映变化，保存导出后通过页面加载并再次核对。
2. 编辑状态真实鼠标拖动，比较前后既有航点数组；正常点击确实能加点作为正对照，不能因为编辑器不存在就通过。
3. 有明确预测/实测切换和目标终止的 fixture，通过正常运行/加载入口送入。清空日志后单次 draw，按目标和片段断言坐标/样式、开关、终止后无当前点但有历史；不是只统计总 stroke 数。
4. 可注入确定 FAIL 的评估数据 fixture，但须由产品原生渲染器创建异常项和 handler。禁止测试重建 DOM/替换 onclick/以自写跳转代替产品。真实点击后断言时间轴、当前帧、对应目标详情/突出显示及真实 FAIL 面板。
5. 实际点击一个观测点，检查详情里的 observationId/source/detectorId/sourceTrackId/measurementTime、坐标单位、可空字段、生成/映射方式等与所点原始对象一致。来源没给的字段可 null，但须明确含义。
6. 1366×768 / 1920×1080 两视口保留无横溢出和主要操作可达检查。未执行项标 NOT_TESTED；note 不能计成断言通过。

fixture 注入产品数据层和只读绘图 instrumentation 是允许的；自行实现产品应有行为再验证自身是不允许的。不能通过增加测试专用替代业务逻辑来制造 PASS。

## 历史资源边界

当前主状态每条记录完整 committed_updates，每帧响应携带完整历史；前端再逐帧扫描。基础功能修复可保留，不要求本轮改分布式架构；但须补历史保留/查询范围、数据规模限制和小规模资源验证记录。全量 2GB 未测不变，不宣称该路径已适合大文件完整历史。若实现增量索引/缓存，必须保证回放倒退和目标终止仍正确。

## 验证与回传

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_phase_coverage_round3.py -q
node /path/to/probe_prediction_episodes.cjs /path/to/project
```

先记录上述反例修前结果，保留本轮已通过的 88 项和历史探针；源码改动后按影响回归，补真实浏览器有效断言。交付完整源码/测试、修前后日志、阶段计划和结果、预测段坐标证据、浏览器脚本/JSON、闭环表、Git 状态和源码哈希。外部回传最终 ZIP 哈希，无需包内自指。

回传 `TASK-003-attempt-001-rework-round3-review-bundle.zip`，停在 REVIEW_READY。真实三源同目标关联 **BLOCKED**；现场精度、约 2GB 全量 SQL **NOT_TESTED**。本轮不改变既有分支和 TASK-001/TASK-002 冻结标签，不 commit/tag/push。
