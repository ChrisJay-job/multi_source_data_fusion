# TASK-002 attempt-001 Round2 复审 / Round3 整改

日期：2026-10-17。结论：**REWORK_REQUIRED**。继续 attempt-001 / Round3，不另开 attempt-002，不冻结 TASK-002，不改动 TASK-001 融合核心基线。

## 已通过与审查范围

审查包 SHA-256 `a58cc6db7e66e8c6d1e95569bb8af9fd9c7fe2ef117d1d5f32104e4266b6dd55` 与回传一致。
独立运行 `PYTHONPATH=src python3 -m pytest tests -q`：**63 passed，5.11s**。Python 3.12.14，依赖按 requirements.txt；提交方 Docker 3.11 须复跑锁定环境。上一轮4个回归均通过；原 Node 探针的 only A 融合点、隐藏预测历史两项也通过。engine.py 与上一轮逐字节一致。

本轮增加4个 Python 反例：**4 failed，0.72s**。运行实际 app.js/canvas.js 的 Node 探针另复现5个操作问题。Node 使用 DOM/canvas 桩，不冒称浏览器 E2E。本次审阅提交方 Playwright 源码与 JSON，未独立运行其浏览器。

认可已修：中间错绑恢复不再抹掉历史错误、最终重复实体使验收失败、空批更新计数、SQL默认候选映射、融合筛选、预测历史分段、内部缓存文件过滤。不要回退这些修复。

## R3-01 航线编辑仍会改错飞机或增加意外航点：P0

1. 页面选择 B，点击“画线”，`btnRouteAdd` 内再次 `refreshRouteAcSelect()` 重建选项，选择恢复首项，实际编辑 A。探针中 B 首点 x=99，实际送入编辑器的是 A 的 x=1。保留当前选中飞机，添加/删除/重载后使用明确飞机标识同步选择；不要每次点击重置为0。
2. 开始编辑2个航点，按下第一点→拖动→松开→click，`_onClick` 的 add 模式无条件追加，点数变3。拖动改点与单击加点必须区分；移动超过阈值或拖动已存在点后抑制随后 click。用实际浏览器鼠标事件验证，不能只直接调用 startRouteEdit。
3. 编辑回调 `renderEditor()` 会重建表单；开始画线前先提交已有速度/起飞/来源开关等未保存输入，防止画线时丢失。本项为静态检查风险，需补完整操作断言。

验收：选择 B→改 B 航点→A 不变；拖动点数不变；空白处单击加1点；停止编辑后不再改航线；再次运行请求和生成观测均反映修改。

## R3-02 only A 仍保留所有飞机真值/计划线：P1

`_allowedByFilter` truth/plan 分支中 `entry.truths.has('TRUTH-'+t)` 与待绘制 obj 无关。A 的 entry 含 TRUTH-A，所以检查 TRUTH-B 也返回 true。探针：only A 时 B 的 truth 与 plan 都允许绘制。

修正为待绘制对象在选中飞机映射中的精确成员判断。补 raw/truth/plan/fused/pred 全图层的绘图命令断言，含 A/B/C 与同名子串干扰目标。保留上一轮已通过的融合筛选。

## R3-03 全过程评估仍存在假通过和误报：P0

附件3个 evaluator 反例：

- 稳定窗口 t1/t2/t3 中，A 在 t1、t3 存在，t2 缺失，结果仍 PASS。当前每帧核查错绑/重复，但期望实体/来源完整性只取窗口末帧；必须在明确稳定区间逐帧检查。当前窗口没有匹配帧时也不能回退末帧后声称通过。
- 雷达 D/R 在12:00属于A、12:10属于B，两个时间不重叠，两个fusionId与trackSegmentId分离；当前把全程来源键对应真值集合揉在一起，两帧均报 ambiguous_key/false_merge。按观测事件时刻、来源轨迹段和有效绑定区间建立真值对应；不能靠所有同键真值全局并集。信息不足时报告不可判定，不凭未来观测认定过去错绑。补真正跨目标误绑对照，防止为了消除误报漏报。
- `expected_stable_entities=None` 且有输入数据时，仍返回 entity_check.status=PASS/ok=true。当前只有空输入才改 NOT_TESTED。没有场景期望规则须明确 NOT_TESTED（或将“未发现已知错误”独立为诊断字段），不能宣称实体完整性验收通过。其他预置场景要么补规则，要么保持此限制。

保留中间错绑/最终重复反例；稳定期允许确认、TTL、来源周期等需显式定义，不能通过删帧或放宽规则掩盖错误。

## R3-04 多文件与映射模板操作不完整：P1

Node 执行实际页面事件处理器复现：

- 第一次回放后 multiQueue 非空，用户重新选择 new.csv 再点多文件回放，仍发送旧 data/old.csv。页面没有添加/移除/清空队列的实际入口。提供明确队列操作或新选择时重建，逐文件显示映射和来源；支持不同文件分别配置后合并。同一队列再次运行应尊重用户明确操作，不能静默忽略新选择。
- btnLoadMap 只恢复 field_map，没有恢复 source_timezone、assume_utc_naive、treat_raw_id_as_aircraftId。UTC 模板在 Asia/Shanghai 页面加载后仍使用 Asia/Shanghai；时间可偏移8小时。缺失于新模板的旧字段映射也应清空。完整恢复模板语义，页面明确显示当前配置；source/固定detector/time_unit等若支持也须一致。

验收需实际上传两/三个具有不同列名、不同来源的脱敏文件，逐个配置→预览→加入/移除→同钟回放；更换选择后请求不能含意外旧文件。保存UTC模板→切换上海→加载模板→核对标准化时间和请求，而不只检查表单存在。

## R3-05 上轮明确要求尚未闭环的原范围：P1

不得在闭环表整项标 PASS。无需扩展产品范围，但须把以下已有要求完成并提供证据：

- **有界读取**：import_tabular 的 JSON 仍先 read_text 再查32MB上限。附件第4个 Python 反例阻止读取超限文件，当前失败。把大小检查前移。错误样例仍无限 errors.append，需独立累计总数、仅保存固定数量样例；无有效数据的大文件也不能积累全部错误。
- **窗口和分页**：run/import 先按 maxRows 截前缀，再做时间过滤，后段时间窗可能永远读不到；分页仍积累 offset+limit 后切片。提供内存有界的筛选/窗口读取，按选定窗口计数和限制输出，不要求一次全量回放2GB。页面仍缺时间/设备/区域筛选。maxRows已标截取，这是改进；多文件摘要也要逐文件标截取范围/限制，不冒称完整覆盖。
- **时间轴统计**：countsUpTo 仍直接返回最终整次 counts，内部note未在页面显示，页面只加 @快照号。按当前时刻记录累计计数；若同时展示全程汇总要明确标签，不能让最终统计看似当前计数。回拖到无目标帧时详情/归属应清空，不能保留未来帧。
- **接口文档**：receivedAt 文档写缺失null，但实现仍代理为measurementTime并标记；watermark公式仍未区分模式。频谱 heading 数值合法不等于已确认运动航向。将已实现行为、设备待确认能力、未支持能力分别写准确；按原要求提供后端/设备可逐字段确认的规格与表，不能将推测变成协议。

## R3-06 浏览器证据需覆盖结果

提交的脚本确实比上一轮增加了断言，only A 的融合模型、单步与来源开关请求可作为局部证据；但 pred_layer_off 仍只检查布尔开关；未实际画线、拖点、保存重载、上传合成文件或本地SQL到轨迹。field_map_form=14、local_no_meta、时区默认值不是导入闭环证据。

补实际交互：B画线/拖动不增点、only A所有图层绘制、预测历史坐标段开关、不同文件/模板合成、实际SQL预览到原始和融合轨迹、保存重载场景、回拖统计和详情。断言检查生成结果或绘图命令，并对失败非0退出。未执行项如实标 NOT_TESTED/BLOCKED，不整项PASS。

## 交付与停止条件

附件用法：

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_task002_round3.py -q
node /path/to/probe_ui_round3.cjs /path/to/project
```

Node探针当前打印实际与期望值，不以退出码0代表通过；整改时补严格断言并保留原反例。可重构入口，但保留行为约束。Python反例为合成数据，不需原2GB SQL。

优先修错机画线、评估真实性，再闭环模板/队列/大文件与浏览器。保留63项与TASK-001基线，禁止真值进入算法、调核心门限凑演示或删反例。回传 `TASK-002-attempt-001-rework-round3-review-bundle.zip`，含完整源码、测试、修前/后日志、逐项证据及已知限制。停在 REVIEW_READY，未审查前不冻结。

真实三源关联：BLOCKED。现场精度：NOT_TESTED。这里的合成测试与软件操作验证不替代真实同目标共现和现场标定。
