# TASK-005 attempt-001：REWORK_REQUIRED / Round3（仅 ID 指标收尾）

继续 attempt-001，不开 attempt-002。本轮仅修“无法测量时错误显示0次”的一个问题。不增加场景、不改关联算法、不重做已通过部分。

## 1. 本次审查结论

被审查包：TASK-005-attempt-001-rework-round2-review-bundle.zip。

SHA-256：a0302dc6ce8b41c574afe4faef5a4397c5c039edf4f59476e24c76d575d76317，与回传一致。165条入包文件哈希匹配；engine/kalman/mapping/models/config 与 Round1 冻结文件一致。

已复验关闭：

- committedHistory提交坐标与展示预测坐标正确分开；原0/20m反例现在两种正确误差均为0；越出真值范围不虚报误差。
- J/K专属距离与全图H/I距离分开，局部视图采用当前播放时间或显式同步跳转。
- “已处理观测数”暂标未提供可靠计数；source_bound与secondary_bind_only分列。
- 新run/空快照清除旧目标详情；真实app函数级反例确认不再残留旧inspector/explain内容。
- 原包直接解压独立回归：**171 passed / 1 warning，96.94s**；本轮8条聚焦测试也通过。审查侧Python3.12+requirements直接依赖固定版本，不把交付方Docker3.11日志冒充审查侧实测。浏览器证据已检查，独立本机浏览器E2E仍为NOT_TESTED。

除下述一项，不重新打开Round2的其他整改。

## 2. R3-01｜P1：无可映射身份或时间覆盖不足，仍输出“0次ID交换”

位置：src/fusion_mvp/workbench/evaluator.py 的 count_id_exchanges。

现实现只有快照完全为空时返回null；但快照非空、series不足两帧时，明确返回0，并写“可映射真值帧不足2；按0次交换计”。

本函数只用aircraftId→sn_to_truth映射。匿名两机即使有很多轨迹快照，可映射帧仍可能为0；此时0不是测得的结果。它违反上一轮“不可计算不当作0”的要求。页面会显示ID交换=0，不能据此解读匿名交叉/近距没有换轨。

### 最小复现（在项目根目录，PYTHONPATH=src）

```python
from fusion_mvp.workbench.evaluator import count_id_exchanges

anonymous = [
    {"tracks": [{"fusionId": "F1"}]},
    {"tracks": [{"fusionId": "F2"}]},
]
one_frame = [{"tracks": [{"fusionId": "F1", "aircraftId": "SN-A"}]}]

print(count_id_exchanges(anonymous))
print(count_id_exchanges(one_frame, sn_to_truth={"SN-A": "TA"}))
```

实际：第一例id_exchange_count=0、frames_mapped=0；第二例id_exchange_count=0、frames_mapped=1。

期望：两例id_exchange_count应为null，并明确原因（无可映射身份 / 无有效时间转换）。不能以0代表没有测量机会。

## 3. 允许的最小修复

1. 没有有效可映射连续转换时，相关交换/重建指标返回null+不可计算原因；保留frames_mapped等诊断值。已有快照不等于已完成测量。
2. UI、metrics_display和导出保留null，显示“不可计算”及原因，禁止再用 `?? 0`、`or 0`、格式化默认值把null转成0。
3. 对可测部分明确统计范围。当前只覆盖可靠身份可映射的目标子集，应注明此范围，不能让混合/匿名场景的未覆盖目标被包含在“已验证0交换”结论里。可只增加覆盖说明；本轮不要求实现匿名目标的新匹配算法。
4. 保留已有可靠身份序列计算：可测且稳定时为真实0，互换序列为1次互换，同机换号重建与跨机互换分开。不可计算不能削弱原始entity_check的FAIL。
5. 文档同步：不能仅写“无快照才null”，应写明缺少可映射身份/时间转换的行为。旧报表保留原始文件可以，但当前有效报表不得再宣称匿名指标0代表通过。

## 4. 验证与停止条件

补充有意义的反例：

- 无快照→null。
- 两帧以上但全匿名、映射为空→null。
- 仅一帧可映射→null。
- 两帧可靠身份稳定→0；已知互换→1；同机重建仍正确。
- mixed部分可测时明确已覆盖范围；未覆盖匿名部分不显示成全场景0。
- API→UI的null保持，原始算法FAIL保持。

先运行聚焦用例；再完成既有171条回归及新增回归。无需重跑140行算法挑战矩阵；若刷新当前指标输出，仅按新不可计算语义更新并清楚标注版本，不改原始算法判定。

浏览器只需针对本项：匿名场景显示不可计算；可靠身份可测场景显示测得数值；不要求重复整套交互。保留本轮已通过的打包、近距、计数和详情清理。

回传完整可解压运行包：TASK-005-attempt-001-rework-round3-review-bundle.zip，含修前/修后证据、测试输出、一项闭环表、更新文档、冻结哈希及外置ZIP SHA。

最终仅REVIEW_READY，不commit、tag、push、冻结或开始下一阶段。不修改冻结算法/配置门限。TASK-004仍待各端确认；真实三源关联BLOCKED，现场精度/2GB全量NOT_TESTED保持。
