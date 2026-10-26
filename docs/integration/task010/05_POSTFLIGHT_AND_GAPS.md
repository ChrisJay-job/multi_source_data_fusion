# 飞行结束、同机归档和断点补齐

## 先区分三个问题

| 问题 | 当前是否支持 | 正确做法 |
|---|---|---|
| 尾部2秒缓冲还有点没输出 | 支持 | run.end / mode=flush 排空 |
| 用数据库保存的观测重新算历史 | 支持 | POST /v1/fusion/replay；新临时会话 |
| 长时间失联、换 fusionId 或换雷达号后，事后拼接并补出缺失路径 | 没有专用接口/保证 | 不能把上面两接口当补齐；按本文件后续需求设计 |

**现在没有一个可交给后端调用的“postflight-stitch/finalize”接口。以下先给已实现调用，再列后续设计，所有拟议字段/流程均非当前公开契约。**

## 1. 现在飞行结束怎么调用

若某 session 整体结束：

1. 后端停止该 session 的新供入，持久保存全部原始规范观测与未决批次。
2. MQTT 向 control 发 action=run.end，采用唯一 messageId；等待 draining→drained，接收 flush result。HTTP通道则向 process 发新batchId、mode=flush、同session/profile、当前processingTime、observations=[]。
3. 后端核对 result/拒绝/剩余账目、去重落库，产生自己的“原始观测归档版本”和“实时融合结果版本”。算法drained只代表算法侧边界，不代表后端已收到一切。
4. 前端最终结果从后端数据库读取/订阅。按可信SN及业务飞行关联多个segment，不将缺口画实测实线。无SN雷达先按session/detectorId/sourceTrackId/fusionId保留，不能按同一个字符串跨设备合并。

多目标共享session时，不能因为一架飞机结束就清掉整会话。业务flightId归后端；目前API没有正式flight结束消息。其余飞机继续用原session。

## 2. 需要离线重新计算时

调用 `POST /v1/fusion/replay`：

```json
{
  "jobId": "tenant-site-flight-review-unique-id",
  "fusionProfile": "multisensor-3d-v1",
  "observations": [],
  "maxSnapshots": 1
}
```

这里 observations 必须放入从后端持久化的真实规范观测，空数组仅展示结构；maxSnapshots=1只保留末帧快照，不截断已处理输入，trajectory仍是整次该job提交的点。单次最多20000条，超限413。不要任意切块各算再直接拼结果，这会丢跨块关联状态；更大规模需单独离线作业方案。

返回新的job/epoch相关轨迹，fusionId/pointId可能与实时版本不同；按observationId和后端job/flight版本关联。实时与离线结果分别落库，不覆盖原件。此函数按时间排序并flush，不是RTS平滑器，不自动生成缺测时段的测量，也不会把状态注回在线session。

## 3. 你的“相同 SN 航线接起来”想法如何落实

方向合理：同一架无人机在同一次飞行中断联后重现，应让用户在一个飞行详情里看到前后各段。但需要分开“身份归并”与“缺口估计”：

- 可信RID/频谱SN相同，是身份关联的强证据；仍需结合租户、站点、业务flight、时间和运动可达性，避免把同SN跨天不同飞行混在一起，或把重复/伪装SN冲突硬合并。
- 雷达号只是设备局部跟踪，丢失换号后不能仅靠ID判断同机。需要时空/速度/方向/重叠设备证据，含糊时保留多段/候选。
- 中间没有测量时不能恢复真实飞行路径。可以做估计插值，但必须标记estimated与方法、区间/不确定性，用虚线展示；不能冒充实测点或填原始SN来源证据。
- 长缺口、速度不可达、高度不兼容、多目标交叉/相同SN冲突时应拒绝自动补齐或转人工审核。

**今天可交付的低风险过渡：后端按“可信SN + 业务飞行”分组已有段，前端同一详情展示所有段与断联起止/持续时长，用明确缺口标记；不补造中间坐标。** 这是公司后端/前端归档功能，不能写成算法补齐已实现。

## 4. 后续专门开发的建议契约（未实现，不可直接调用）

独立任务再实现异步后处理job，别让一次长历史任务阻塞实时session。所需字段和行为应先由三方确认：

| 对象 | 拟议内容 |
|---|---|
| 请求标识 | jobId / tenantId / siteId / businessFlightId / algorithmVersion / inputVersion |
| 输入 | 完整规范观测或可校验存储引用、实时segments、时间范围、可信SN证据 |
| 策略 | 最大可估计缺口、允许速度/加速度/转弯/高度变化、SN冲突策略、是否仅分组或生成估计点 |
| 作业状态 | accepted/running/succeeded/failed/partial，进度、错误、取消与幂等 |
| 输出 | finalFlightId、原segment映射、别名、真实点、估计点、未连接原因、证据与质量标签 |
| 估计点 | generated=true、method、from/toPointId、时刻/位置/高度、uncertainty；不得伪造observationId |
| 版本与审计 | 原始实时版本保留；最终版本可追溯、可回退、可人工修正 |

明确“不根据SN把所有段无条件连成一条线”的验收用例：短缺口可达、长缺口拒绝、同SN不同飞行不合并、雷达换号歧义不强接、多目标交叉不混号、高度缺失不填0、估计与实测视觉可区分、相同job重试不重复生成。

用户想要的这部分应继续排入单独开发与审查。本次main整合、部署、文档不能暗中加一个未经验证的补齐算法；公司同事必须据此安排当次联调期望。
