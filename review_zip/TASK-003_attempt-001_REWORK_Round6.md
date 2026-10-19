# TASK-003 attempt-001 Round5复审 / Round6整改

日期：2026-10-19。结论：**REWORK_REQUIRED**。继续现分支 attempt-001 / Round6。本轮仅修评估器的活跃来源集合及对应测试/契约，不改融合引擎，不重做前端，不扩展需求。

## 1. 本轮已认可

附件实际 SHA-256 `d59f37628dfd2224807b0b83fc3b85871113acf0696f8917b927b0c5f7e5aaaa`，一致。

- 独立全量回归 **122 passed，1 warning，53.08s**，见 `full_pytest.log`。
- 上轮原始三个反例独立 **3 passed，1.10s**，见 `previous_counterexamples.log`。
- lifecycle/display 双时钟分离、状态字段前置校验、取消用 sourceTracks 掩盖空 sources 的修复均保留。
- 本轮源码相对 Round4 的变更集中在 evaluator；既有引擎/轨迹/前端交互不要求重做。浏览器本轮不独立执行，沿用已审计证据；提交方已如实登记精确逐点坐标尚未覆盖，认可此限制说明。

独立环境 Python 3.12 + requirements.txt；保留提交方 Docker Python 3.11 的回归记录。此次没有新增 UI 或真实设备验收要求。

## 2. 唯一剩余整改项：活跃来源集合判定仍漏掉部分停源的两种错误

附件 `test_partial_outage_sources_round6.py`：独立 **2 failed，1.48s**。全部只在 evaluator 输入快照副本注入 sources 错误，不改融合算法输入、不向关联泄漏真值。

场景为默认 D 单机 **RID+spectrum**，45 秒，RID 在 12–30 秒停报，spectrum 持续正常。RID 最后观测为 11 秒；RID TTL=2.5 秒。

| 反例 | 以 frontier 为准的时段 | 原始输出与故障注入 | 当前评估 |
|---|---|---|---|
| premature_rid_removal | 12–13 秒 | 原始 sources 含 RID+spectrum；TTL 尚未到期，注入删除 RID | PASS，漏判提前失活 |
| expired_rid_kept_active | 18–22 秒 | 原始 sources 仅 spectrum；RID 已过期，注入添加 RID | PASS，漏判伪活跃 |

测试硬断言原始来源集合符合上述条件，防止空测。无故障同场景 **PASS**，见 `normal_partial_outage.json`；不应把该正常场景修成 FAIL。

这两例是同一项既定需求的双向验证：活跃源必须与 TTL/实际已提交观测相符，不仅要求“所有应有来源是实际来源的子集”。

## 3. 根因与修复要求

### 3.1 停报不等于立即过期

`_expected_active_sources` 先调用 `_expected_sources_at`，把当前处于 outage 的源从候选集中立即删掉，再算 TTL。因此在 outage 开始后的 TTL 宽限期内，评估预期已经不含 RID，而引擎仍正确把它保留为活跃。

以 `engine._active_sources` 为真实契约：只要 confirmed 绑定的 `frontier − lastSeen ≤ limit`，仍为活跃。outage 的含义是停止生成新观测，不是撤销最近一条已接收观测的有效期。

修复：从实体已启用/已产生有效观测的来源，按截止该快照 frontier 的最后有效观测和相应 TTL 推导活跃集合。outage 影响后续是否有观测，不能直接把已有未过期来源置为不活跃。计划来源/正在发报来源/当前活跃来源三个含义在文档中写清楚。

### 3.2 只检查子集会放过多报的活跃源

当前 full 检查是 `need_active and not need_active.issubset(have)`：只查缺少应有来源，不查多报已过期来源。只有“所有观测都老化”分支才拒绝非空 sources；当 spectrum 持续更新时，整机总 gap 很小，过期 RID 就逃过检查。

修复：逐来源核查应有与实际活跃集合，检查 **missing_active** 与 **unexpected_active** 两方向。源身份/确认状态无法确定时说明不可判定原因，不能用放宽全体集合来掩盖。确定的过期/未启用来源不得算在线。sourceTracks 仍只做归属，不得回填 sources。

集合核查应适用于 full/lifecycle 两种阶段，不能因为全源计划停报便直接 continue 跳过 TTL 宽限期的来源核查；也不能把“有其他源正在更新”当作该源在线的证据。

### 3.3 保留已修规则，避免再拆分补丁

- 生命周期用 watermark/frontier，显示用 processingTime，不改冻结的引擎时钟。
- 必填字段校验保留，空 sources 是合法值但必须符合当时预期。
- 判定尽量集中在一个逐来源规则中，供各阶段调用。不要在 outage/full 分支分别维护相互矛盾的活跃源判断。
- lastSeen/最后有效观测仅来自截至当前已交付且已到对应 frontier 的证据。不能用未来接收数据、缓冲区尚未提交数据或待验证输出本身制造正确答案。必要的缺信息按明确边界报告。

## 4. 测试收口范围

1. 保留原 122 项和上轮原始三反例；附件两反例修前失败 -> 修后捕获 FAIL。
2. 同一部分停源场景无故障正例继续 PASS。
3. 在 TTL 前/恰好/之后分别断言实际活跃集合；RID 与 spectrum/radar 使用各自阈值，测试不得只断言 helper 返回某个集合而不验证最终 evaluator 能捕获故障。
4. 全源停报后的 TTL 宽限期、部分源停报但其他源正常、慢周期自然暂时无活跃、恢复后重新活跃分别保留正例。异常多报/漏报源有明确错误字段。
5. 当前 `test_outage_schedule_excludes_source_from_active` 把 outage 内“已有新鲜观测也必须不活跃”写成预期，与引擎 TTL 契约冲突。修改为合理的观测时间线和 TTL 断言，说明变更原因；不能为了保留测试数量保留错误规则。

本轮不再要求浏览器整套回归；若错误详情格式改变，仅验证结果面板可读即可。不开新 attempt，不扩大到真实三源关联或 2GB 性能。无需新增功能或重建项目。

## 5. 回传

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_partial_outage_sources_round6.py -q
```

回传 `TASK-003-attempt-001-rework-round6-review-bundle.zip`，包含完整代码/测试、修前后日志、正常和故障来源时间线、更新后的活跃源契约、闭环表、源码哈希和 Git 状态；外部回传最终 ZIP SHA-256。

停在 REVIEW_READY，禁止 commit/tag/push/冻结，不开始下一阶段。真实三源同目标关联 **BLOCKED**；现场精度、约 2GB 全量 SQL **NOT_TESTED** 不变。保留 TASK-001/TASK-002 冻结标签和既有成果。
