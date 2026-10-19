# TASK-003 attempt-001：默认七机、轨迹可视化与关联诊断

日期：2026-10-19。项目：`d:\zwyl\02_algo_project\multi_source_data_fusion`。
目标：用户打开页面后可直接使用七种来源组合，不反复添加飞机；能看到真实融合历史并理解结果，修复用户四机场景暴露的误关联与评估问题。本文件是实施指令，不仅产出方案。

## 1. 基线与执行边界

- TASK-002已本地冻结：commit `5749a24022e85fe41efcecf29374683cc8eb3d39`，tag `task-002-fusion-validation-workbench-v1`。TASK-001 tag及历史保留。
- 先读项目manifest/治理入口，记录branch/HEAD/工作区；从上述commit创建独立分支`task-003-workbench-usability-and-association`。不要修改旧tag、回退历史或清理无关未跟踪文件。已有同名分支则核实基线后继续，不覆盖成果。
- 新任务TASK-003 / attempt-001。按项目实际Flow2Spec路由执行；知识库未命中不等于任务不可实施，不编造业务topic。
- 本轮授权新分支上的源码、测试、场景、文档与页面修改，包括为已复现误关联作必要算法修复；不得在旧冻结标签上“原地改完仍称同一版本”。不扩五源、不全量灌2GB、不外部部署。
- 保留TASK-002原76项和真实文件/映射/队列/分页能力。测试入口因重构变化可迁移，但不得删除行为约束或缩小反例。

## 2. 默认七架飞机：明确用户要求

页面首次打开、点击“恢复默认七机”时，自动载入下列七机，提供可直接运行的航线、速度与来源参数，无需用户手动添加。

| 飞机 | 默认来源组合 | 预期输出 |
|---|---|---|
| A | RID | A单源目标 |
| B | spectrum | B单源目标 |
| C | radar | C匿名单源目标，不伪造SN |
| D | RID+spectrum | D两个来源归到同一个目标 |
| E | RID+radar | E两个来源归到同一个目标 |
| F | spectrum+radar | F两个来源归到同一个目标 |
| G | RID+spectrum+radar | G三个来源归到同一个目标 |

- UI可显示“频谱（spectrum）”“雷达（radar）”；组合一目了然。来源开关和显示图层开关分离。
- 默认场景使用新的明确名称，如`seven_aircraft_combinations`，不要把四机/七机仍叫three_aircraft_primary。原三机预置保留在预置列表。
- 默认航线清晰分开且易在自适应画布中查看；可用7条间隔约300米、长度约400–600米的平行航线作为基础演示，参数固定且保存种子。此间距仅服务基本演示，不能用改间距来修用户原四机误关联。
- 默认无丢点、无失联、无延迟/乱序/时钟偏差、无隐式换号；位置噪声可保留RID/频谱/雷达现有有说明的默认值。全部默认值可见、可保存重载。
- 支持选择任一飞机修改航线/来源、增删飞机；七机模板不是数量上限。重置提示会覆盖未保存编辑，导入自定义场景时不自动追加七机。
- 已有同机RID/频谱可共享可信仿真SN；不同飞机不得共享SN。雷达观测仅携带来源航迹键，不注入真值标签。界面给匿名目标显示“C（仿真标签）”可以，但须与设备SN区分。
- 基础可分离场景的显式稳定区间内，输出7个正确且唯一的实体，来源分别对应上表；单源也有效，不要求三源齐全才建轨。

## 3. 用户已复现问题：先保留失败证据

本文件附录含用户导出的原四机JSON，原样保存为独立回归样例。原名/notes与实际配置不一致本身就是问题，不在修前证据里偷偷改正。

原配置：seed=20261019，duration=40；A仅RID，B仅spectrum，C仅radar，D三源。旧代码realtime独立复现：delivered=197、processed_updates=134、snapshots=75。

已查证：

1. 仅开融合估计、关闭预测等层，实际绘图命令为历史线0条、当前标记2个。按positionMode拆历史后，单点段被舍弃；这不是最终轨迹交付效果。
2. t≈39s的`radar-C-v2`被绑定到SN-A-001；快照pt≈43s仍可见。评估记录TRUTH-A/TRUTH-C误关联。这是实际关联错误，不是仅画错颜色。
3. runner按场景名称硬编码原ABC期望；四机改了配置还继续按C三源/3机判断，造成missing_entity/extra_entities等错误口径。
4. generator把雷达换号时刻null强制替换20s，且对所有雷达生效，属于用户未启用的隐藏行为。

先运行附录原样场景，保存修前输入/生成观测/过程快照/误绑定事件和简要摘要。fusionId含会话随机量，反例按来源键与归属判断，不锁死某个随机fusionId。

## 4. 算法关联与动态评估修复

### 4.1 误关联根因与修复

- 追溯radar-C-v2何时建候选/接续/绑定A，记录候选距离、时间、创新残差、运动连续性、已有绑定与确认状态，解释选错原因。缺失诊断可新增，但不要伪造置信度数值。
- 用航迹连续性、换号接续、门控/歧义等实际证据修复；不允许直接把C排除、不允许凭truth映射绑定，不允许单纯收紧全局阈值到所有雷达不参与来凑通过。
- 修后既要避免C错绑A，也要保持D/G等可关联来源正常融合。困难数据无法确定时保留候选/独立目标或明确不可判定，不能盲目绑定。
- 保持RID优先等现行产品策略，若需改动必须说明原因、作用范围和回归证据。多源归属成功不等于所有位置等权平均；UI应如实显示当前主位置来源和其他来源用途。

### 4.2 无隐藏换号

null表示未配置换号，不自动在20s换号。原有“雷达换号预置”显式写换号时间；基础默认七机不换号。
保留“附录原配置在旧代码默认20s时的已观测行为”作为修前证据；修后另建显式20s换号版本复验，不能仅去掉隐藏换号后就宣称换号误关联已修。

### 4.3 评估适配自定义场景

- 根据实际飞机列表、来源启用、起飞/停源/确认期定义预期，不按name固定ABC或7台。区分计划存在、实际有观测、预期稳定可见的时间区间。
- 评估匿名C时用时间/来源观测归属等评估侧元数据，不能因aircraftId为空就判missing；真值仍不进入算法请求。
- 稳定区间逐帧检查正确实体、来源归属、重复/丢失、ID切换；历史误绑恢复后不抹掉。
- 允许用户改变来源后重新运行，评估规则相应改变；无规则/无真值标NOT_TESTED，不默认PASS。歧义保持UNDETERMINED。
- 四机原场景、显式换号四机、默认七机、修改来源/删增飞机后的自定义场景都要验证。不要只为默认种子写特殊分支。

## 5. 轨迹显示：用户应能看懂

- 图层明确区分：计划航线、仿真真值历史、RID/频谱/雷达原始观测、算法提交更新历史、当前位置、展示预测历史。图例始终可见。
- 融合结果默认显示“历史轨迹＋当前位置＋目标标签”；75帧运行结束不能因模式交替而只剩几个点。刚起步/仅1点时允许单点。
- 历史以算法实际更新记录及stateTime为依据，与displayStateTime的预测分开保存。去重不能丢实际轨迹段，不能仅靠连续两帧positionMode相同才画线。
- 预测虚线、实测更新轨迹实线；隐藏预测时，保留已提交更新历史，不把预测点换成实线或跨长失联断段乱连。不同fusionId、来源键、trackSegmentId不可串线。
- 必要短间隔历史连接的含义/断段策略明确；恢复/换号时展示轨迹段和事件，不能用连线假装已重识别。
- 默认简洁可读：突出融合轨迹，原始观测较淡；按目标筛选或选择飞机后一键对比该目标的各源与融合。避免七机全层全开导致混乱。保留“全部图层”高级查看。
- 匿名雷达目标可读名称与完整ID分层展示，不能所有标签截成同样的F前缀。仿真标签与算法ID清楚区别。
- 播放、暂停、单步、倍速、seek、当前计数/详情与时刻一致；不得显示未来原始观测/真值。计划航线作为明确标注的未来计划可全程显示。

## 6. 布局与输入分层

不新增前端框架/地图服务订阅，优先在现有工程内整理组件和布局。

- 左侧为紧凑飞机列表A–G：名称、来源组合、状态；只编辑当前选中飞机，不将七机全部参数纵向铺开。
- 配置面板采用抽屉/宽面板和标签页：基本信息、航线、传感器、高级故障。避免多层嵌套滚动和横向溢出；常用运行/保存/重置按钮始终易找到。
- 中央为轨迹画布与时间轴；右侧为结果摘要/选中目标来源归属/异常。完整JSON、事件流放默认收起的调试区，不能占据主要信息位置。
- 基本输入：名称/可信仿真SN、速度、起飞时间、航线和来源开关。
- 高级模拟：各源周期、噪声、系统偏差、延迟、乱序、时钟偏差、丢点、失联区间、显式雷达换号。未支持项不得显示为已生效。
- 观测检查器完整显示送入算法的Observation字段和值，包括空值/生成方式；标明“自动生成”“人工配置”“未提供/待设备确认”。当前生成器对altitude/speed/heading等为空时必须看得见，不能拿飞机运动速度冒充设备实际上报速度。
- 接口完整字段规格与设备能力确认表保留并同步；不要求用户手工填写每个观测ID、每秒时间/坐标，也不把模拟面板当设备协议文档。新增可选量只在确实实现时标支持，不扩测向-only/3D等范围。

## 7. 可解释的结果面板

默认可直接看懂：

- 当前时刻：预期可见飞机数、算法目标数、各目标来源组合与主位置来源。
- 整次评估：PASS/FAIL/UNDETERMINED/NOT_TESTED，明确是仿真评估而非现场准确率。
- 逐飞机表：A–G/自定义飞机，期望来源、实际关联来源、当前fusionId、状态、异常。
- 点击异常跳到对应时刻并突出相关来源/目标。四机反例应能表达“C雷达在约39s关联到了A”，不只输出source_bound或一屏JSON。
- 明确区分“已接收/已绑定/用于本次位置更新/候选/已过期”，不能将sourceTracks里的历史记录全当当前活跃融合来源。
- 无真值真实文件只显示可观察行为、数据质量和绑定状态；不生成真值对照/虚假正确率，不展示没有依据的百分比置信度。

## 8. 验收与交付

保留原76项回归。新增与本次缺陷相关的有效行为测试和真实浏览器断言，至少覆盖：

1. 首开默认7机及全部七组合，恢复默认；原三机预置/自定义导入仍可用。
2. 七机基础稳定区间7个正确且唯一目标，单源雷达不伪造SN，双/三源均归属正确；源显示开关不改变算法输入。
3. 附录四机与显式20s换号反例修前/后对照，C不误绑A、D多源仍正常。固定用户种子复现并补少量明确其他种子/近邻运动反例，不以无限随机扫描替代根因分析。
4. 仅融合层显示实际历史轨迹；实测/预测交替仍有历史，关闭预测不隐藏提交历史或伪造连线，长断段不硬连。检查实际绘图命令/坐标段，不只开关布尔或截图。
5. 选择G编辑仅改变G；真实鼠标加点/拖动/删除点；改参数不丢失；保存重载七机/四机结果一致。
6. 自定义改来源、删机/加机后评估按实际配置；匿名单源、同键同刻歧义和真实误绑正反例保留。
7. 1366×768和1920×1080实际浏览器检查：主要操作可见、无横向溢出、无需滚过全部七机参数；结果表/异常跳时刻可操作；无JS错误。
8. 真实文件单/多文件映射、UTC模板、筛选/分页/正式回放、快照计数回归不退化。无需重跑全量2GB。

先完成并自测，再回传 `TASK-003-attempt-001-review-bundle.zip`。包含完整修后源码/依赖/运行配置、原样用户四机场景与显式换号版、七机默认与测试场景、根因与修复说明、测试修前后日志、真实浏览器结果断言/截图、接口/设备字段确认说明、闭环表、Git状态及源码哈希。不包含2GB原始数据/真实上传/密钥/依赖缓存。不要要求用户手动打包。

页面继续使用现有Docker/18089环境并说明启动方法，不影响其他项目。停在**REVIEW_READY**，**禁止commit、tag、push、冻结或开始下一阶段**。
真实三源关联仍BLOCKED，现场精度和全量2GB SQL仍NOT_TESTED，除非另有真实证据；本轮合成修复不改变这些边界。

## 附录：用户原样四机场景

以下JSON须原样落为 `samples/workbench/user_four_aircraft_20261019.json`。保存其原name用于复现旧评估问题；新UI可另外设置可读标题和稳定scenarioId，不用重写原样fixture。

原附件SHA-256：`39e50ac9a96c957a09f687081f3d39f179391f6a04ac9a01272242cd32142b82`。下列仅压缩JSON排版，语义与原文件一致；如原附件已在本机，优先保留原字节副本。

```json
{"name":"three_aircraft_primary","seed":20261019,"duration_s":40,"algorithmHint":"mvp-0.1.0","notes":"首要验收：A仅RID、B仅频谱、C三源；稳定后3个实体且C同源归并","aircraft":[{"label":"A","truth_id":"TRUTH-A","rid_sn":"SN-A-001","speed_mps":10,"takeoff_offset_s":0,"waypoints":[{"x_m":0,"y_m":0,"dwell_s":0},{"x_m":400,"y_m":40,"dwell_s":0}],"sources":{"rid":{"period_s":1,"pos_noise_m":3,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":true},"spectrum":{"period_s":1,"pos_noise_m":5,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":false},"radar":{"period_s":1,"pos_noise_m":5,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":false}}},{"label":"B","truth_id":"TRUTH-B","rid_sn":"SN-B-002","speed_mps":10,"takeoff_offset_s":0.5,"waypoints":[{"x_m":0,"y_m":200,"dwell_s":0},{"x_m":400,"y_m":240,"dwell_s":0}],"sources":{"rid":{"period_s":1,"pos_noise_m":5,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":false},"spectrum":{"period_s":1.2,"pos_noise_m":8,"bias_east_m":2,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":true},"radar":{"period_s":1,"pos_noise_m":5,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":false}}},{"label":"C","truth_id":"TRUTH-C","rid_sn":"SN-C-003","speed_mps":11,"takeoff_offset_s":1,"waypoints":[{"x_m":50,"y_m":100,"dwell_s":0},{"x_m":450,"y_m":120,"dwell_s":0}],"sources":{"rid":{"period_s":1,"pos_noise_m":3,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":false},"spectrum":{"period_s":1.5,"pos_noise_m":10,"bias_east_m":0,"bias_north_m":-3,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":false},"radar":{"period_s":2,"pos_noise_m":15,"bias_east_m":0,"bias_north_m":0,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"clock_bias_s":0,"outage":[],"radar_id_swap_at_s":null,"enabled":true}}},{"label":"D","truth_id":"TRUTH-D","rid_sn":"SN-X-4","speed_mps":12,"takeoff_offset_s":0,"waypoints":[{"x_m":0,"y_m":160,"dwell_s":0},{"x_m":300,"y_m":160,"dwell_s":0}],"sources":{"rid":{"enabled":true,"period_s":1,"pos_noise_m":3,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"outage":[],"radar_id_swap_at_s":null},"spectrum":{"enabled":true,"period_s":1,"pos_noise_m":8,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"outage":[],"radar_id_swap_at_s":null},"radar":{"enabled":true,"period_s":2,"pos_noise_m":15,"delay_s":0,"drop_prob":0,"reorder_window_s":0,"outage":[],"radar_id_swap_at_s":null}}}]}
```
