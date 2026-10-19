# TASK-003 attempt-001 Round4复审 / Round5整改

日期：2026-10-19。结论：**REWORK_REQUIRED**。继续现分支 attempt-001 / Round5；不冻结、不 commit/tag/push、不进入下一阶段。

## 1. 已认可的闭环

提交包实际 SHA-256 为 `a86d86a5b0dd1bb5019ed0f2d06402d072d4c0b52a09ab12657d396ea0fb5618`，与外部回传一致。

- 上轮原始生命周期三反例独立重跑 **3 passed，5.39s**：正常终止、起始无检测、lost/stale 伪装新鲜实测。
- 原始 JS episode 探针仍为两条各 2 点虚线；历史探针预测线/终止后提交线均保留。
- 浏览器脚本审计确认：已捕获真实运行请求 G speed=13.5；真实鼠标点选；FAIL 面板和 pinned 目标硬断言；两视口 JSON summary 为 hardFail=0 / not_tested=0 / notes=0。认可这些补证，下一轮不要求整套 UI 重测。
- 历史资源边界仍保留；不开展五源、3D、新 UI 或数据存储改造。

全量独立回归原始输出见 `full_pytest.log`，摘要见 `independent_verification.json`。独立环境 Python 3.12 + requirements.txt；交付方 Docker 3.11 结果保留。复审未独立运行真实浏览器，浏览器仅审计提交脚本和 JSON；Node 为实际产品 JS 加桩。

## 2. 剩余 P0：评估契约仍有三条静默 PASS 路径

附件 `test_evaluator_contract_round5.py`，独立 **3 failed，6.06s**。所有注入仅修改 evaluator 的快照副本，不改算法输入或引擎，不向关联过程泄漏真值。

| ID | 场景/注入 | 当前行为 | 正确要求 |
|---|---|---|---|
| R5-01 | 单 RID、80 秒、12–50 秒停源；仅清空 processingTime=42/43 秒的 tracks | 整次 PASS | 此时 frontier=40/41，距最后观测11秒仅29/30秒，未达到 >30 的终止条件，提前消失必须被捕获 |
| R5-02 | 默认单 RID，15–20 秒快照同时删除 trackStatus 和 positionMode | 整次 PASS | 必填字段缺失必须报契约错误，不能因不在 outage 就跳过 |
| R5-03 | 默认单 RID，15–20 秒原本 sources=[rid] 改为 []，历史 sourceTracks 保留 | 整次 PASS | 活跃来源缺失不能用历史绑定补成当前在线 |

### R5-01 生命周期与显示时钟仍混用

`evaluator.py::_eval_clock` 使用 max(processingTime,watermark)，`reports/task003_rework_round4/lifecycle_contract.md` 也写同样规则。但当前 engine.py 明确：

- realtime cutoff = processingTime − reorder_window；frontier = max(旧水位, cutoff)。
- `_advance_lifecycle(frontier, mutate_filter=True)` 后 `_snapshots(display_time=pt)`。
- `_snapshots` 中 `now = event_watermark ...`，active sources 按 now 检查；显示位置副本另按 processing/display 时间预测与 stale。

因此生命周期/来源新鲜度沿 frontier，显示预测沿 processing 时间。用一个最大时钟判所有状态不符合源码事实。本反例中算法原始42/43秒快照仍有 lost 目标（测试已硬断言），评估却按31/32秒间隔允许消失。

请分别使用 **lifecycle_clock** 和 **display_clock**，按各自配置阈值推导 trackStatus、positionMode、sources 的允许值，边界必须精确。更正文档。不要通过扩大状态集合、任意容忍“时钟偏差”或改已冻结的引擎时钟规则让测试通过。

独立预期的最后观测应按该阶段实际已交付且已到对应 frontier 的观测推导，不能把缓冲区尚未提交或未来接收的观测提前算入。引擎存在拒绝/歧义时说明是否可评估，不以被验证输出直接充当真值。

### R5-02 字段校验被分支条件绕过

当前仅在 `st_name is None and "status" in tr` 时记 missing_trackStatus_field；同时缺 trackStatus 和 status 则不报。随后仅当 use_life 或超过 fresh_or_predict 带才查枚举，正常活跃期缺失字段就可以整次 PASS。

把快照结构/类型/枚举校验放在分阶段业务判断之前，适用于所有应评估轨迹。trackStatus、positionMode 等必填字段缺失、空值、非法枚举都不得静默放行；保留可空字段的合法 null。不要用旧字段默认值或历史数据填造已缺失的必填输出。

### R5-03 历史绑定再次代替活跃来源

当前 full 检查 `have = active_srcs or _bound_sources(tr)`：sources=[] 时回退 sourceTracks，恰好掩盖了来源全部不在线。文档刚区分了活跃来源与历史绑定，判断逻辑仍没有遵守。

来源归属可以查 sourceTracks；活跃集合只查 sources，并基于各来源 lastSeen、来源 TTL、frontier 推导预期。不得以非空历史绑定覆盖 sources 的合法空集合。按采样周期/停报/恢复确认动态确定应有活跃集合，不要反过来在慢周期时强制每一源永远在线。

## 3. 本轮范围与完整闭环要求

本轮集中修评估器/契约/回归。保留七机、历史与 episode 显示、UI 原生交互、来源 ID 和 LSA 已通过成果，不推倒引擎、不扩展业务。

建议先将快照字段校验、时间轴选择、活跃来源判定做成清楚的独立规则，再由阶段检查调用，避免继续在不同分支打补丁。

必须有以下正反断言：

1. 附件三反例从修前失败变通过，失败明细指出字段、期望/实际、frontier/display 时刻、last observation、阈值。
2. 终止边界前/恰好/之后，realtime 与 replay 各自时钟；终止前缺失失败，正常终止移除不失败。
3. 活跃期和停源期的必填字段缺失/非法值均不能 PASS；合法 null 可空字段不误报。
4. 活跃来源非空、全部过期、单源过期但另一源仍鲜活、恢复待确认、慢周期等正例；删除应鲜活 sources 必须捕获，保留历史 sourceTracks 不得掩盖。
5. 旧反例/回归保留，不靠整体降成 NOT_TESTED 避免失败。已知确定故障应 FAIL；缺输入证据/无法判定才明确未测或未判定。

浏览器不重跑整套无关链路；若评估结果展示契约变动，只补一条正常/失败明细展示即可。现有绘图坐标证据仍较弱：fused 用任一 sample 匹配任一历史点、pred 仅存在性；可登记为精确逐点验收未覆盖，不能宣称已完成所有目标全部坐标比对。无需因此重写 UI。

## 4. 验证和回传

```sh
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m pytest /path/to/test_evaluator_contract_round5.py -q
```

提交修前/修后日志、原回归、时间边界和字段/来源正反例、修正后的生命周期契约、闭环表、完整源码/测试、源码哈希和 Git 状态。

回传 `TASK-003-attempt-001-rework-round5-review-bundle.zip`，外部给最终包 SHA-256；停在 REVIEW_READY。禁止 commit/tag/push/冻结，不开始 TASK-004。真实三源关联 **BLOCKED**；现场精度、约 2GB 全量 SQL **NOT_TESTED** 不变。
