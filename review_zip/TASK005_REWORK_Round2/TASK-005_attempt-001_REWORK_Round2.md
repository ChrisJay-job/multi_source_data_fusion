# TASK-005 attempt-001：REWORK_REQUIRED / Round2

继续 attempt-001，不开 attempt-002。本轮只处理以下四项剩余问题，保留 Round1 已完成内容；不改冻结算法，不追求高难算法全 PASS。

## 1. 已通过部分及复核边界

- 本次包 SHA-256：b325b245d9858704de760dab3c74cf36600f727c23cba8e4cce798d84ac42cba，与回传一致。
- 137 条入包文件哈希匹配；engine.py、kalman.py、mapping.py、models.py、config/fusion.yaml 与已审查 TASK-003 Round6 字节一致。
- 原 ZIP 直接解压运行全部 tests，无需补源码或样例：审查侧 **163 passed / 1 warning，56.07s**。环境为 Python3.12 + requirements 直接依赖固定版本，交付方另有 Docker3.11 输出。打包缺源码/样例问题本轮关闭。
- 独立计算33个挑战预置几何均通过；提交矩阵140行几何均 verified，硬例 FAIL 保留。原距离档位错误关闭，不要求重新设计场景。
- both_id/both_anon 的来源组合及按源身份开关已有实质修复；分组和运行标识也已有实现，不推倒重做。
- 未直接访问用户本机浏览器；独立浏览器 E2E NOT_TESTED。本包 UI 复现调用实际源码函数，标明函数级；另检查了交付方两视口截图及脚本，不把截图等同于完整交互验证。

## 2. R2-01｜P1：位置误差的坐标与时间不一致，ID交换统计缺少实际测量

### 2.1 位置误差反例

附件 audit_metrics_and_pair.py / metrics_pair_audit.json 调用真实 evaluator.position_errors：

- 真值 t=0 时在0m，t=2 时在20m。
- 目标 stateTime=t=0，committedHistory 最后提交点是0m；displayStateTime=t=2，顶层 latitude/longitude 是预测的20m。
- 正确提交误差=0m，正确展示预测误差也=0m。
- 当前 mode="committed" 返回 **20m**：它按 stateTime 选真值，却仍拿顶层展示预测坐标比较。

这符合冻结引擎真实契约：_snapshots 使用 KF 副本外推顶层坐标，同时保留原 stateTime。API 的 run/scenario 确实在取得 truth_timeline 后调用此 helper 并展示 RMSE；所以问题不是“没有RMSE”，而是已提交误差的语义错误。runner 中的 metrics 又总令 ttl=None，离线矩阵与 API 输出口径也不统一。

修复范围限评估侧/接口展示：

1. 已提交误差必须使用 committedHistory 对应提交时刻与提交坐标；展示预测误差使用顶层坐标及 displayStateTime，两者分列，不修改冻结 engine。
2. 明确统计范围（末个提交点还是全程提交历史）、匹配分母及时间对齐方法。建议沿用本轮范围先正确完成末点，不能把末点数值标成全程。
3. 真值时间必须覆盖估计时间。允许有明确定义容差的最近邻或插值，超出真值时间范围不能用端点当成精确同刻真值。无有效匹配显示不可计算及原因，不当成0。
4. runner/API使用共同的评估函数或等价一致契约；将真值只送评估侧，绝不送入算法。
5. 反例测试：上面0/20m例分别得到0；有真实位置偏差时得到对应非零误差；没有同刻真值不虚报；检查 API 与矩阵的同一指标定义一致。

### 2.2 ID交换和覆盖率

runner 的 id_exchange_count 仅统计 attribution_errors.reason 是否含 swap/exchange/id 字串。它没有跟踪连续时间上“同一真值对应哪个 fusionId”的变化；当前评估器主要 reason 为 foreign_source_bound、ambiguous_key_undetermined，页面显示 ID交换≈0 不能证明没有交换。

以时间序列真实匹配实现并定义 ID交换规则，分清跨机交换、同机断后重建/拆轨、不可判定；不依赖原因文案。暂未实现时必须 null+未实现说明，不能输出测量值0，更不能将此项标为已验收。用已知发生/未发生交换的人工小序列验证。

现有 association_coverage 是末快照已映射真值实体数/期望实体数，应明确命名为“末快照实体覆盖率”，不要让人理解为观测正确关联比例；去掉缺分母时回退 len(bound_truths) 产生100%的自分母。缺少期望实体时按说明返回不可计算。如保留“关联覆盖率”名称，需另按已定义的有效观测/绑定单位真实计算。

## 3. R2-02｜P1：J/K近距视图使用了H/I交叉的距离和时刻

附件 metrics_pair_audit.json 与 ui_audit.json：

- seven_plus_challenges_with_id 全图最近对=H/I，距离≈0m，时间≈14s。
- 其中 near_parallel_spacing 检查的 J/K 最近距离=2m，时间=0s。
- btnZoomNear 选 J/K，却把全图 geo.min_truth_distance_at_s=14 作为缩放时间，并将整个 geo 传给 updateNearDist；页面因此显示“0.00m，对=H/I”。传入 labels 并不能覆盖 geo 中已有的 pair。
- 只断言 scale>2 或文字含“真值最近距”不能发现错误；缩放时刻与当前播放时刻不一致还可能让当前目标落在视野外。

修复：

1. 按当前聚焦的两架飞机计算/读取该对专属距离和时刻。全图最小值可保留，但单独明确标记，不能冒充近距对的结果。
2. “2m局部放大”围绕当前播放时刻该对位置；若选择跳至最近时刻，则同步时间轴，并明确这是主动跳转。不能镜头看14s、轨迹还停0s且不解释。
3. 近距面板标明选中对、距离及统计范围。初始帧、飞行中、末帧都能看到该对或清楚说明为何不可见。
4. 回归：扩展13机时聚焦 J/K 显示2.00m、对=J/K；H/I单独聚焦显示交叉结果。两视口断言目标坐标投影在画布内、两条真值线实际可分辨，不能只测比例尺数字。

## 4. R2-03｜P1：接收计数仍被改名为处理计数，来源绑定冒充仅绑定

真实小场景反例：realtime 第一个快照 received/delivered=1、pending_buffer=1、processed_updates=0、tracks=0，观测尚未冲刷水位。app.updateTransport 却显示“已处理观测数=1”。原因是直接取 c.delivered_at_t。

同函数把 c.binds_at_t（source_binds）写成“仅绑定事件”，但 source_bound 与 secondary_bind_only 并非同一事件。后者的独立全程计数 coll.counts.bind_only 已有，不能换名借用前者。

修复：

1. 明确接收、重复、仍缓冲、拒绝、已实际进入处理、主位置更新、仅绑定、来源新绑定的定义与时间范围，不把接收数当处理数。
2. 能提供可靠当前快照计数就写入 counts_at；暂不能可靠测量的字段显示“未提供可靠计数”，不要用近似值/帧号替代。
3. 不要求修改冻结引擎；允许在 runner 的已有响应/事件收集层补齐可证明的统计。避免用单一差值公式假装覆盖拒绝、重复、冲刷和回滚所有情况。
4. 测试首帧全缓冲显示处理0或明确未提供，后续空批冲刷的计数变化，重复/拒绝，以及 source_bound 与 secondary_bind_only 分离。页面和API字段含义一致。

## 5. R2-04｜P1：切换运行或空快照时，旧目标检查器仍残留

附件 ui_audit.json 调用实际 updateTransport：当前快照 tracks=[]，detail 被设为“当前时刻无目标”，但 inspector 和 explainAssoc 仍是旧运行内容。传入上次选中目标时，函数甚至先调用旧目标解释，随后仅令 pinnedDetail=null，并未清空可见检查器。

交付方 Round1 viewport_1366.png 同样显示：当前是两机 N2a/N2b、新 run #3、首帧无目标，底部检查器仍显示机=A、SN-A-001 及旧 fusionId。运行banner已隔离不代表所有面板都已隔离。

修复：

1. 新 run 应用时清除/验证旧 pinnedDetail，原始观测也要校验 observationId 属于当前 run。不能跨运行保留另一个目标的解释。
2. 当前快照无匹配目标、目标终止或回退到建轨前时，inspector、explainAssoc、detail、assoc同步清空/显示“当前时刻无目标”。若需要历史详情，应另明确标“历史选择”，不能标当前。
3. 原始观测点击仍保持正确解释，时间轴推进后按当前选择类型更新，不回退至其他目标而不提示。
4. 真实浏览器按“选中A→切两机→运行→首帧空缓冲→前后拖时间轴→点击观测”测试，硬断言所有详情没有旧 A/SN-A/fusionId；同时确认新运行有目标时可正确查看。

## 6. 执行顺序与回传

1. 先跑本包两个小探针确认修前现象，然后为四项补有意义的反例并修正。注意探针 JSON 是缺陷观测记录，不是期望全 true 的合格标准。
2. 不重做已经关闭的打包/全档几何/身份模式；不扩展算法或额外大规模随机场景。
3. 新旧回归通过后，浏览器仅聚焦本轮四项及原有基本流程。矩阵若包含本轮变化指标则更新对应输出，保留原始算法 FAIL，不以调参消除。
4. 最终完整包继续做干净解压验证，不能从旧仓库补依赖；保留163条已有测试并补本轮有效回归。
5. 交付 TASK-005-attempt-001-rework-round2-review-bundle.zip：源码、有效测试、四项修前/修后证据、指标定义与更新指南、闭环表、浏览器结果、冻结哈希、外置ZIP SHA。不要只附本轮差分而缺基础运行文件。
6. 完成仅 REVIEW_READY，不 commit/tag/push/冻结/进入下一阶段；TASK-004保持待外部确认。真实三源关联 BLOCKED，现场精度及2GB全量 NOT_TESTED 保持。

## 7. 审查证据目录

- verified_summary.json / independent_full_pytest.log：已通过事实及环境边界。
- audit_metrics_and_pair.py / metrics_pair_audit.json：真实误差helper反例、13机分组距离、首帧缓冲计数。
- audit_ui.cjs / ui_audit.json：真实app函数的面板残留与计数/距离显示反例（非浏览器E2E）。
