# TASK-003 attempt-001 首轮复审 / Round1整改

日期：2026-10-19。裁决：**REWORK_REQUIRED**。继续attempt-001 / Round1；不另开attempt-002；不冻结、不commit/tag/push，不开始下一阶段。保留TASK-001/002标签与本轮已有布局成果。

## 1. 已验证进展与范围

审查包SHA-256：`952182a63de37fec1d201e43b4add6001e86ac48768d3779f1a3b4be2627f90b`，一致。

独立原测试 **83 passed，14.86s**，含原76项；Python3.12.14，依赖按requirements.txt，提交方Docker3.11须复跑。独立复跑：原四机、显式20s换号四机、七机的当前评估均PASS，四机各197观测，七机375观测。默认七机、无隐藏换号、匿名目标评估、布局有实际进展。

但新增雷达接续绕过门控/分配；融合历史和结果面板仍未达到用户要求。新增2项Python回归 **2 failed，0.60s**；执行实际JS的Node探针复现历史和结果显示缺陷。Node为DOM/canvas桩，非浏览器E2E；审查方本次未独立运行浏览器，只审阅提交方脚本与报告。

## 2. R1-01 换号接续不能依赖仿真编号猜身份：P0

### 复现与根因

engine._radar_base_tid用正则剥离`-vN`，将`radar-C-v2`等当同一“家族”。新的handoff分支仅检查扩展欧氏距离，然后直接_apply_update，绕过LSA与创新门控。

附件相同位置/时间序列，仅把新雷达ID从`new-id`改成`R-v2`：新观测距旧位置约150m、间隔1s；普通路径输出2目标，后缀路径输出1目标并发radar_id_swap_handoff。设备ID是未规定语义的字符串，其拼写不应改变物理匹配结果。

其次，_radar_has_continuity只要同设备有较新雷达绑定也可返回true，而不要求属于该观测的连续轨迹；该逻辑可给外来目标放宽创新上限/降低成本。首次绑定90m硬门也是新增经验常数，不能仅凭四机特定距离判根因已修。

### 修复约束

- 通用算法把sourceTrackId当不透明标识；显式厂家换号/前后轨迹关系只有在接口/适配层有真实可证契约时才能利用。不得读取仿真label/truth或凭`-v2`习惯推断物理身份。
- 换号使用可观测的时间间隔、预测位置/速度、完整可用创新门控、连续性/候选竞争与必要确认，歧义应保留而非强绑。
- 换号/重门控失败/旧绑定/新LSA使用一致门控策略；handoff不能成为绕过门控的捷径。handoff缓存须有有效期和设备会话边界，避免历史条目永久占用或复用。
- 对输入轨迹号做任意一一重命名，保留同一个轨迹ID在多帧内的相等关系，结果归属应等价；特别把原四机的`radar-C`→`7319`、其后换号→`2048`，D的号另映射。保留四机与其他种子/近邻正反例，不只是让后缀形式通过。
- 不允许通过禁用雷达、调小门限让全部雷达分裂、移动用户航线或借真值强绑凑通过；D/G等正常雷达绑定仍要成功。

## 3. R1-02 handoff破坏设备内一对一分配：P0

附件同设备同事件时刻，两条新雷达来源轨迹`R-v2`与`R-v3`，位置20m、30m，都被handoff到旧R所在的同一个fusionId；发生2次handoff、最终只有1个目标。handoff循环没有占用集合，且第一条处理会改写绑定，让第二条继续匹配同一家族。

统一整个设备/微批的占用与竞争：旧绑定、接续、新关联都纳入一对一约束。多候选竞争不得按遍历次序连续写同一KF，不得靠覆盖旧来源键消失一条观测。补交换数组顺序的反例与普通数字ID版；若确有设备同物理目标重复航迹的业务语义，须明示处理规则，不能默认两观测就是同一对象。

## 4. R1-03 融合历史仍然是散点补丁：P0

独立七机run：250个快照。实际canvas仅启用fused，关闭current/pred/raw/truth/plan后，Node记录：**历史线0条、粉色点1个**。原始四机“只有点”的根因尚未解决。

当前仍按展示快照positionMode拆历史，仅把run.length==1从丢弃改成画点。快照中位置本来就是displayStateTime的预测副本；没有独立记录真实KF提交更新位置，不能用“stateTime标签”把预测坐标变为提交历史。

按TASK-003原要求：

1. 在真实主位置更新发生时记录不可变提交历史：fusionId、segmentId、观测/更新时刻、更新后坐标、来源、关联观测等；回滚时一并回滚，去重不重复记。可在验证台会话侧收集，但必须来自真实KF更新，不能把raw线当融合线。
2. 提交历史与展示预测分别返回/绘制。隐藏预测时，多个有效更新的默认七机仍应有可读历史轨迹，不能只有当前标记/孤立点。
3. 分段规则明确，短间隔提交点的历史连线可显示，但不跨真实长断点/重新建轨伪造连续性；不能把预测点改画实线。不要仅要求相邻展示帧mode相同才画线。
4. 当前标记开关独立。断点、预测、重现场景保留；绘图命令与算法更新坐标逐一核对。

提交方浏览器draw_cmds_fused>0无效：采集的是stroke/fill/fillText/beginPath总数，包含网格；日志未在目标帧清空，也未跳到有充分历史的时刻。没有轨迹也能PASS。必须在实际中后段时刻清空日志，只统计融合历史线/坐标段，逐目标证明有更新历史且不含预测位置。

## 5. R1-04 结果面板接口没接对：P0/P1

Node向实际renderResultPanels输入正常评估响应形状：entity_check.status=FAIL，false_merges含A/C错绑。页面显示“评估（仿真）：—”，异常区“当前时刻无明显异常条目”。

根因：

- verdict读evaluation.verdict/status，而实际在evaluation.entity_check.status。
- renderAnomalies读evaluation.issues/anomalies，没有接false_merges/attribution_errors/duplicate_targets/undetermined/entity_check.details。
- 事件格式化猜e.detail或顶层sourceTrackId，实际事件附加字段在payload；source_bound通常只有payload.key，不能用缺失字段推断“无错误”。
- activeSourcesOnTrack没有以tr.sources为活跃依据，confirmed记录筛完后又fallback到全部rows；输入算法sources=[]、一条一小时前的confirmed雷达绑定，页面仍显示活跃radar。

修复：

- 单一适配器读取真实响应schema，显示PASS/FAIL/UNDETERMINED/NOT_TESTED；区分整次评估与当前时刻状态，不预知未来却写“当前”。
- 接入结构化评估错误与payload，生成可读归属异常，点击跳到记录时刻并突出相关目标/观测；用必有异常fixture验收，不以“none”写note当通过。
- 活跃来源尊重sources和快照时效；历史sourceTracks另列“历史/候选/失效”，主位置来源直接用positionSource，不凭RID优先猜当前贡献。
- 逐飞机匹配用明确显示映射/时间归属，不以sourceTrackId子串当通用身份。仿真标签可供显示/评估，不能流入算法。

## 6. 动态评估与浏览器补齐

expected_sources_from_scenario已去掉固定name，匿名归属已增加，认可。但仍是每机启用源集合+一个全局启发式窗口，不是根据实际起飞/停源/周期的逐时刻期望。补停源/起飞偏移/短时长场景的明确验收规则；无有效窗口应不可评估，不给无意义missing_entity。不能把所有场景名一样的期望换成所有时间段一样的期望。

现test_user_four_no_c_to_a_misbind对status枚举任取其一是兜底断言，应替换为明确归属/数量/来源约束；D测试只检查存在也不足以证明D三源正确。保留正常四机/显式换号/七机测试，加强“来源归属且唯一”，不要只检查总体数目。

浏览器两分辨率无横溢出是有效证据，保留。edit_g只记note(speedBefore)，未断言修改G不改其他机；anomaly_click=none未测跳转；未测真实拖点、保存/重载与源数据开关；按原清单补实际结果断言。观测检查器需展示实际标准字段和缺失标记；未实现项如实写NOT_TESTED，不整项PASS。

## 7. 运行附件与回传

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_task003_review.py -q
PYTHONPATH=src python /path/to/make_seven_probe_run.py /tmp/seven_run.json
node /path/to/probe_task003_ui.cjs /path/to/project /tmp/seven_run.json
```

JS当前打印证据，不以exit0表示通过；整改时加严格行为断言。Python含2个明确失败反例，不含真实设备数据。本包不含截图或大文件。源码ZIP中bundle_sha256.txt出现重复条目，仅报告文件重复；下次去重条目，避免解压提示，实际包哈希以上述为准。

优先统一雷达门控/设备内一对一，再记录真实提交历史、接对结果schema与时效，最后补交互与动态期望。保持布局与原83项成果。提交 `TASK-003-attempt-001-rework-round1-review-bundle.zip`：完整修后代码/测试/修前后日志、opaque-ID及竞争反例、真实历史绘图证据、结果/异常/来源时效浏览器断言、闭环表、Git状态和哈希。不包含2GB原始数据。

停在REVIEW_READY。未commit/tag/push、不冻结、不扩范围。真实三源关联BLOCKED、现场精度/全量2GB NOT_TESTED不变。
