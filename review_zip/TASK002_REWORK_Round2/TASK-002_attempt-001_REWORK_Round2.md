# TASK-002 attempt-001 Round1复审与Round2整改

日期：2026-10-17｜裁决：**REWORK_REQUIRED**｜继续attempt-001，不开attempt-002，不冻结TASK-002，保持TASK-001基线。

## 1. 已验证进展与证据边界

审查包SHA-256：`887d0c6bda705fefa4a5c557d9a84da41e003f44d210b4e1cc207496c4e49caa`，与回传一致。

本轮独立执行原测试 **59 passed**，上一轮7个针对用例已修复。新增4项端到端/时间过程回归 **4 failed**；另用Node执行实际canvas.js，确认2项绘图缺陷。审查环境Python 3.12.14，第三方依赖按requirements.txt锁定；提交方Docker为3.11，须在其锁定环境复跑。

源码与提交截图证明页面有改善：分组观测、历史线、播放起点、命名时区、SQL基础解析、重解析原文件、绑定状态及编辑参数表单均已增加。但“闭环表全部PASS”仍不成立。

已审阅提交方Playwright脚本、JSON和截图；本次未独立运行浏览器。Node结果仅为绘图逻辑执行，不冒称浏览器E2E。

## 2. R2-01 目标勾选和预测图层仍画错：P0

### 实际复现

`canvas.js`的fused过滤只接受fusionId或aircraftId精确命中。用户勾选“A”时，目标的aircraftId是SN-A-001，fusionId是F-A，两者均不等于A；因此A的融合点和融合历史全部被隐藏。raw/truth使用包含关系判断，形成“看得到A原始线但看不到A融合结果”的不一致。

融合历史无条件合并全部positionMode点画紫色实线。取消pred只隐藏当前预测点和额外速度延伸线，过去预测点仍留在实线中。现有虚线是前端用speed/heading额外推2秒画的，并不是算法返回的实际预测轨迹片段。

### 修复

1. 建立明确标签→飞机身份→来源轨迹键→融合实体的显示映射。仿真真值映射只供显示/评估，不传入算法；真实数据按实际来源键与融合结果关联。不要用任意子串匹配，避免A误中其他编号。
2. 每个图层统一使用同一目标筛选规则，包含plan/truth/raw/fused/pred。plan分支当前筛选if为空体，仍画所有飞机的计划线。
3. 历史数据保留每段positionMode及trackSegmentId等，measured_assisted实线、predicted虚线；隐藏预测应移除整个预测历史，不在两侧实测点间伪造一条实线跨过去。
4. 不自行多画两秒“算法预测”。速度方向提示若确有用途，独立标注“方向示意”，不计入算法轨迹或误差。
5. 按当前时刻显示累计计数，当前代码仍展示全程最终counts；选择目标后时间推进应保持所选详情，不每步强制跳第一条track。

附件 `probe_render_round2.cjs`：only A时融合点0/历史线0；pred=false时仍有包含3个点的紫色实线。将其更新为真实断言回归并提供修前/修后输出。

## 3. R2-02 SQL“可解析”尚不等于页面“可导入”：P0

### 实际复现

用项目25列Navicat VALUES语句和页面默认映射（仅明确Asia/Shanghai）：扫描到1条INSERT，但标准观测0条，bad_measurement_time/missing_time。

`_default_mapping`预置measurementTime→measurementTime、sourceTrackId→sourceTrackId、detectorId→detectorId；真实SQL字段是created_at/id/detector。`import_sql_stream`靠setdefault补别名，因标准键已存在而不会生效。上一轮只测token解析或手工模板，未覆盖页面实际调用路径。

### 修复

1. 按文件格式和已识别schema提供真正的映射选择/预览：真实SQL默认候选created_at→measurementTime、id→sourceTrackId、detector→detectorId；映射确认后执行，不能静默覆盖用户显式选择。
2. 频谱detector可能在source_data.deviceId，时间可能在source_data.trackTime；支持字段路径及可靠JSON解析，不根据列名断言语义已确认。未知SN继续null，不把aerial_sn=tcp当飞行器身份。
3. 补页面端到端：选择data文件→源时区/字段映射→预览样例→有效/拒绝计数→运行→出现原始与融合轨迹。无有效数据不能只显示ok=true或空画布。
4. 固定25列格式必须严格校验，不以len>=3后缺列补null冒充合法行；不支持语法明确计数和原因。

## 4. R2-03 评估只看最终一帧，仍存在假通过：P0

当前evaluate_run新增了来源键核查，修复了“最终错绑”反例，但仍只取snapshots[-1]。

新增复现：第一帧把B的雷达错绑到A，第二帧解除恢复正常；结果false_merges与attribution_errors为空、entity_check仍true。另一反例：同一真值最终有两个fusionId，duplicate_targets非空，但entity_check仍true。

修复：

- 按时间过程评估误绑定、误合并、重复实体与ID变化；初始确认期/稳定评估区间显式定义。历史错误恢复不能抹掉，来源号跨飞行复用按时间分段，不把全程同键所有真值揉成一组。
- W01要求稳定区间A/B/C分别唯一且来源归属正确，不只挑最好的一个matched目标；确定重复实体必须使相应验收失败。
- 汇总状态与细项一致；有错误不能总栏PASS。无真值的真实导入继续不报准确率；其他预置场景没有期望规则时标NOT_TESTED而不是默认ok=true。
- 增加“中间错绑后恢复”“最终重复实体”“多个时段雷达号复用”反例；保留正常W01测试。

## 5. R2-04 调度计数仍遗漏空批处理：P1，本轮必修

两个有效RID观测分别t=0和t=10，realtime/time_step_s=1。第一条在中途空批成熟并成功更新，第二条最终flush更新；实际2条均处理，但counts.processed_updates=1，rejected=0/pending=0。

根因：runner在tick空批只收events，没有累计位置更新/绑定/拒绝；最终flush也未完整累计所有类别。当前通过“在库轨迹hits之差”计数仍会受终止清理/归并影响。

统一每次process返回结果的采集路径：非空批、tick和flush都经过同一个收集器。使用明确逐观测处理结果或可靠仪表，不因轨迹清理减少累计量。输出累计接收唯一数、主位置更新、仅绑定、明确拒绝、待处理以及重复接收，定义守恒范围，区分源事件次数与观测条数。

## 6. R2-05 还未完成的用户操作：按原范围补齐

这些是原已确认需求，不是本轮扩展：

- **图上画航线**：当前航点编辑是直接写JSON。补添加/选择飞机后在画布点击加点、拖动改点、删除点及停留配置，JSON保留作高级导入导出；Canvas CSS尺寸与内部像素坐标须正确换算。
- **真实字段映射**：页面mappingFromForm仍把列名写死，无法将不同设备列名映射到标准字段。提供逐字段下拉/路径选择、原始预览、单位/时区/高度基准确认及模板保存/读取。
- **多个真实文件同一回放**：fileInput只取files[0]，run/import只有一个path。支持RID/频谱/雷达分别导入后组合数据集，同一时钟归并；不同文件默认imp-行号ID须带文件命名空间，避免碰撞。
- **真实数据筛选**：补时间段、设备/目标、区域选择后回放。当前5000行上限必须标为截取/抽样并报告范围，不能当完整文件。提供有界分段/窗口路径，不要求一次HTTP载入2GB。
- **大文件有界**：JSON大小检查必须在read_text之前；错误样例有界、总错误独立计数。分页目前重新解析并积累offset+limit行，前端也一次接收全部观测/快照，应真正限制内存和响应大小，不能以“流式读文件”代表全链路有界。
- **文件列表**：过滤自身.meta.json等内部元数据，不把缓存和源文件混在待回放列表。

接口文档也需校准：positionMode实际为measured_assisted/predicted/stale，不是measured；watermark区分realtime与replay；导入receivedAt实际仍赋mt+代理标记，与文档“无则null”不一致；原始频谱航向未确认不能因数值合法就当运动航向。补完整响应/事件字段和逐来源能力表，当前概述不能替代后端可实施的字段规格。

## 7. 浏览器证据必须有结果断言

现有脚本的filter_only_fused/hide_pred/only_A/only_rid都是操作后直接log(true)。截图停在首帧，此时realtime还没有融合目标，“仅融合”实际是空画布。step使用afterStep>=mid，未前进也可通过；rerun_after_edit在固定等待后直接写true。真实文件只切换tab，没有上传/映射/回放验证。

保留已做浏览器自动化，补以下实测：

1. 跳到有A/B/C实际融合实体的中间时刻，only A后仅A的原始/真值/融合保留；检查绘图模型或可验证DOM/图层命令，不只截图。
2. 跳到确有预测历史的区间，pred开/关验证对应历史段出现/消失，实测线不受影响；与算法返回坐标对照。
3. 图上画/改航线，关闭C某来源再运行，核对HTTP请求和生成观测确实变化；数据源开关与显示开关分别测试。
4. 保存/重载场景、改时区/列名映射模板、分别导入三源文件合成回放、从本地选择SQL到出现轨迹的完整链路。
5. 暂停后时间不动，单步严格前进，拖动后详情/事件/计数对齐；任何控制失败使脚本非0退出。

截图是辅助，断言必须判定实际结果。无法运行的项标BLOCKED/NOT_TESTED，不自动PASS。

## 8. 执行与回传

保留修复进展，优先R2-01显示真实性、R2-02导入链路、R2-03评估，再统一计数和补齐操作。新增4项Python回归及Node探针随包，先在Docker 3.11保存修前结果；可随数据集接口重构入口但保留行为断言。

原59项及TASK-001基线保持；不要改核心门限或用真值强绑凑场景。不要只把新增4项变绿就宣称完整范围通过。

回传 `TASK-002-attempt-001-rework-round2-review-bundle.zip`，含完整代码/测试/运行文件、修前修后日志、各项闭环证据、实测浏览器断言与截图、接口/能力表、场景、脱敏导入样例、Git状态和哈希。原2GB数据不入包。停在REVIEW_READY，不冻结。

真实三源关联仍无同步同目标证据：BLOCKED；现场精度：NOT_TESTED，不改成两项都已可用。
