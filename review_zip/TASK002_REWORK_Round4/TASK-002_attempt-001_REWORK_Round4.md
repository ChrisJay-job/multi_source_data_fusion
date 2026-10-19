# TASK-002 attempt-001 Round3复审与Round4整改

日期：2026-10-17。结论：**REWORK_REQUIRED**。继续 attempt-001 / Round4；不另开 attempt-002，不冻结 TASK-002。仅闭环已有需求，不扩五源、不修改 TASK-001 核心门限。

## 一、认可本轮进展

审查包 SHA-256：`cfb0d6a6273933182ba26e5683a258f29dc8cb6f8dc9c0e34e649bd4891e5916`，核验一致。

独立执行原测试：**67 passed，4.70s**。审查环境 Python 3.12.14，沿用已安装 requirements.txt 依赖；提交环境 Docker Python 3.11，需锁定环境复跑。上一轮4个Python反例已通过，提交方Round3 Node探针独立复跑也通过。engine.py与Round2一致。

已确认修复：B选择画线、拖动防加点逻辑、A真值/计划精确筛选、评估函数接收稳定窗口后逐帧核查、无期望标NOT_TESTED、JSON超限预检、表格导入错误样例有界、空帧清除详情、代理receivedAt文档说明。

但函数局部通过不等于页面调用闭环。新增 **4个Python反例全部失败（1.50s）**，新增Node探针复现 **3项页面逻辑问题**。附件提供源码和原始输出。Node使用DOM/网络桩运行实际提交JS，不冒称浏览器E2E。本次审阅提交方Playwright脚本和报告，未独立运行浏览器。

## 二、R4-01 多文件队列仍被覆盖：P0

### 根因与复现

`btnRunMulti` 只要 fileInput.files 非空，就无条件调用 `uploadFilesToQueue(files,{replace:true})`。`__wbNewFilesSelected` 虽有设置，运行时完全未用于判断。

正常流程：RID文件按映射A加入→雷达文件按映射B加入→队列显示两文件→点击合成。由于fileInput仍保留雷达文件，整个已配置队列被清空，只重新上传最后选择文件；之前的文件和映射消失。用户移除一项后也可能被当前选择重新加回。现有反例只证明“新文件替换旧文件”，未证明真正的多次加入合成。

### 修复与验收

- 明确一种操作语义：回放执行当前队列；选择文件、加入队列、替换队列、移除/清空分别生效。若保留“未加入文件快捷运行”，只能在明确空队列路径使用，并在页面解释，不能覆盖已配置队列。
- 每文件映射、时区、来源、上限在入队时保存独立副本；回放请求与可见队列一致。
- 上传失败不能用 `data/${f.name}` 猜路径后冒充入队成功；仅接受服务端成功返回的stored_as，并显示失败项。
- 真实浏览器分别选择两种不同列名文件→分别配置→加入→移除/重加→运行，断言请求包含正确文件与各自映射，回放观测确实包含两源且数量正确。再测同次多选3文件。

## 三、R4-02 UTC模板实际页面保存路径仍不正确：P1

页面 mappingFromForm 在选择 assume_utc 时返回 `source_timezone:null, assume_utc_naive:true`；这是正常保存格式。但 btnLoadMap 把恢复时区逻辑放在 `source_timezone != null` 条件内，导致此模板加载时跳过恢复。Asia/Shanghai页面加载它后仍是上海时区，时间有偏移风险。

Round3浏览器脚本直接API保存时手工把source_timezone改成字符串assume_utc，绕过了页面真实保存格式，不能证明“页面保存→重载”已修好。

先按 assume_utc_naive 解析；命名时区/null/严格带时区模式均应完整恢复。补**页面保存按钮→切换设置→页面加载按钮→标准化样例时间对照**，不得手改API体避开真实路径。保持已有字段缺项清空和raw-id开关恢复。

## 四、R4-03 稳定窗口检查未接入，时间归属仍查错时钟：P0

### 1. 页面仍未使用稳定窗口

runner.run_batch_replay 调evaluate_run不传 stable_window；run_scenario_bundle也没有建立或传递窗口。因此Round3新增函数用例虽证明“显式传窗可逐帧验收”，页面W01仍只验证最终实体完整性。附件spy复现实际主场景调用参数为None。

为主场景明确稳定区间（确认期后、预期停源前等），沿场景→runner→evaluator传递并返回评估报告；在稳定期逐帧核验实体数量、来源归属/要求与唯一性。其他预置规则未定义时继续NOT_TESTED。若换实现，可替换参数探针为等价页面行为断言，但不能退回只看末帧。

### 2. 复用键按processingTime查询造成未来真值污染

新_build_key_intervals已按时间分段，这是进展；但_snapshot_attribution仍用快照processingTime查来源键真值，没有使用该sourceTracks.lastSeen所指向的已绑定观测。

附件有效时序：雷达D/R测量t1属于A，t3复用给B；快照pt=t4、watermark=t2，仍绑定lastSeen=t1的A来源。t3观测还在前沿之外，评估却按pt4判为B，误报A混入B。修复需要按绑定观测时间/来源段/已提交前沿确认有效对应，不能按展示时钟重标旧绑定，也不能把全程所有delivered观测当已应用。

保留“真正误绑不能漏报”对照；同步时刻多真值、重复号缺段等无法唯一判定时明确不可判定，不以排序取最后一条作为答案。不要将真值传入融合算法。

## 五、R4-04 真实文件窗口和SQL有界仍未完成：P1

这些在Round2/3已明确，不是新增范围。Round3闭环表仅写JSON/计数标签PASS，不能代表整个R3-05完成。

1. **窗口先后顺序错误**：run/import先_load_observations(maxRows)截前缀，后_filter_obs_window。附件3行文件，maxRows=1，选择第3行所在时间窗，返回400/no_valid_observations，实际窗口有数据。应流式扫描/索引定位，在选定条件内累计上限。支持文件后段窗口，多文件同理，时间比较解析成统一时刻，不能比较原始RFC3339字符串。
2. **SQL错误样例仍无限存**：import_tabular改了，import_sql_stream仍每条errors.append。附件100个坏SQL行在内部保留100条错误；现汇总虽然只输出20条，内存仍无界。独立总错误数+固定样例上限，保留总数100；大文件无有效点也不能积累全部错误。
3. **分页和筛选原范围**：dataset_observations仍先累计offset+limit再切片；页面仍没有时间/设备/区域选择。补可用的有界窗口/游标读取与页面筛选，不要求全量2GB单次传到浏览器。摘要显示实际条件、扫描/接受/拒绝、返回范围及截取标志，多文件逐项说明。

## 六、R4-05 当前时刻计数仍为推算：P1

countsUpTo从全程rejected逐条读r.time/r.measurementTime，但正式Rejected只有observationId/reason/detail/rawRef。时间为空时逻辑直接计入，因此未来发生的拒绝在首帧就显示。附件JS探针：观测receivedAt=t10、快照t0，rejected_at_t仍为1。

不要通过新增“当前/全程”文字替代真实对齐。每次batch/tick/flush后，在快照记录已知累计计数/批级拒绝归属和事件，页面取该快照；回拖不得预知未来。replay以实际调度投递为准，不能固定按receivedAt估算。当前更新/待处理等若未提供，不用最终值冒充。

## 七、浏览器覆盖与文档收尾

- B加点是实际鼠标点击证据，认可。拖动段却在page.evaluate直接调用内部_onDown/_onMove，并手改suppressClick，未测试真实mouse up事件链及CSS缩放。改为真实鼠标down/move/up，断言坐标变化且点数不变；保留加点/拖动/再加点连续操作。
- only-A筛选模型证据认可；预测历史开关、不同真实文件合成、本地SQL预览→原始/融合轨迹、场景保存重载仍缺完整操作证据。按原清单补实测，失败非0退出；未测项如实标NOT_TESTED，不整项PASS。
- receivedAt文档已校准，认可。watermark仍写单一processingTime−window公式，需区分realtime/replay。逐字段接口输出/事件/缺失处理和设备能力确认表按原范围收尾；频谱heading语义待确认，数值合法不能当厂家确认。不要编造设备能力。

## 八、执行和回传

先在Docker3.11保留附件修前证据，再修复并补行为测试。保持原67项，不删除或弱化前轮反例。附件运行：

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_task002_round4.py -q
node /path/to/probe_ui_round4.cjs /path/to/project
```

JS探针当前3项均FAIL并以1退出。可重构UI/API入口，保留用户操作与真实性约束；不要靠测试桩或修改fixture绕过正常页面路径。

回传 `TASK-002-attempt-001-rework-round4-review-bundle.zip`：源码/测试/修前修后日志、逐项闭环证据、实际浏览器断言、本地SQL与多文件端到端报告、已知限制、Git状态/哈希。不含2GB数据。停在REVIEW_READY，未审查不冻结。

真实三源关联仍 **BLOCKED**；现场精度仍 **NOT_TESTED**。软件MVP与可视验证台不替代真实同目标共现验证。
