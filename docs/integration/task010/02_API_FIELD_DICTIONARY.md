# 算法接口与字段字典（已审实现）

依据：TASK-009 R2 内 `models.py`、`api.py`、`multisensor.py`、`integration/schemas.py`、`mqtt_bridge.py`。不是历史 R1/R10 说明书；文档若与运行版本冲突，先核对发布 commit/ready 指纹，不凭旧样例修改后端。每次部署导出实际 `/openapi.json`，作为该版本 HTTP 结构快照。

## 1. 通用约定与接口表

JSON UTF-8。所有规范时间使用带时区 ISO8601/RFC3339字符串，如 `2026-10-26T02:00:00.123456Z`；服务端输出通常 UTC+00:00，保留微秒，不用无时区本地字符串。经度/纬度为十进制度，需统一实际坐标系；当前核心用 pyproj 的地理坐标到局部平面转换，**不会替你自动做 GCJ02/BD09 纠偏**。现场原始坐标系仍需设备/后端确认。

距离/海拔米，speed米/秒，heading角度0≤h<360（业务按北0顺时针约定，核对设备），verticalSpeed米/秒（约定向上为正，核对设备）。null=未知；0与负海拔可有效。ID全部是字符串，不能前端转成 JS Number，尤其长数字SN/设备ID。

| HTTP 方法/路径 | 请求 | 响应/作用 |
|---|---|---|
| GET /health | 无 | status=ok，进程基础存活 |
| GET /ready | 无 | 版本、配置/模块指纹、会话数、支持profile；不证明Broker可用/精度通过 |
| POST /v1/fusion/process | ProcessRequest | ProcessResponse；实时/空tick/flush，必须选择正确profile |
| POST /v1/fusion/replay | ReplayRequest | ReplayResponse；同步临时离线重放，不恢复实时会话 |
| POST /v1/fusion/reset/{session_id} | 无body | dropped=session_id；破坏性丢会话，不代替正常结束 |
| GET /v1/fusion/session/{session_id}/write-owner | 无 | sessionId, owner, generation, retired_max |
| POST /v1/fusion/session/{session_id}/write-owner | WriteOwnerTransferRequest | 新owner/generation/retired_max及reason；别名 /handover |
| GET /docs、/openapi.json | 无 | FastAPI HTTP结构说明，不包含全部动态字典/MQTT契约 |

`/v1/workbench/*` 是文件导入/预览/仿真/测试推流/调试事件页，**不作为公司后端正式实时集成契约**。正式实时用上表 process 或 MQTT input/result；页面事件分页/缓存不是后端永久历史库。

HTTP 请求头：`Content-Type: application/json`；`X-Fusion-Channel` 为 http/mqtt，后端HTTP用http。`X-Fusion-Write-Generation` 为当前会话写权代际整数字符串；初始纯HTTP会话可省略，治理后必须正确携带。不存在本算法自带通用API Key/JWT校验；部署在受控内网/网关后，不对互联网直接开放写接口。

### ready / owner / reset 字段

| 字段 | 类型 | 解释 |
|---|---|---|
| status | string | health:ok / ready:ready；配置缺失ready返回503 |
| sessions | integer | 当前进程内会话数，非在线无人机数 |
| algorithmVersion / configVersion | string | 工程版本字符串，不唯一标识所有UI/发布变更；同时记录commit和指纹 |
| stateOwner | string | 当前为single-process-SessionStore |
| supportedProfiles | string[] | legacy、multisensor-v1、multisensor-3d-v1 |
| reorderWindowSeconds | number | 重排窗口秒，当前2 |
| configSha256 / multisensorModuleSha256 | string | 实际文件内容指纹，与交付锁一致才是本候选 |
| owner | string | none/http/mqtt；释放到none保留旧代际墓碑 |
| generation / retired_max | integer | 当前写代际/已退休最大代际；原子移交后旧写方失效 |
| dropped | string | 被reset的sessionId，仅确认丢状态操作 |

## 2. MQTT 信封和topic

适配器每实例固定一个tenant/site，topic=`{TASK008_TOPIC_PREFIX}/{TASK008_TENANT_ID}/{TASK008_SITE_ID}/{suffix}`，默认前缀fusion/v1。payload的tenantId/siteId必须匹配配置；其他站点需另外隔离部署/设计路由。

| suffix | 方向 | QoS / retain | messageType |
|---|---|---|---|
| input | 后端→算法 | 1 / false | observations |
| control | 后端→算法 | 1 / false | control |
| result | 算法→后端 | 1 / false | result |
| ack | 算法→后端 | 1 / false | ack |
| status | 算法→后端 | 1 / true | status |

| 信封字段 | 类型/必需性 | 解释 |
|---|---|---|
| schemaVersion | string 必需 | 精确fusion-mqtt.v1 |
| messageType | string 必需 | 对应topic种类；不是设备源名 |
| messageId | string 必需 | 全局业务消息ID；稳定重发，同ID不同内容冲突。不是Broker packet mid |
| tenantId / siteId | string 必需 | 业务隔离域，必须与本实例配置一致 |
| sessionId | string 必需 | 融合会话；全局status时可能为空串，不是无人机SN |
| sentAt | string 必需 | 信封发送时间；接收验证主要校验字段存在，业务应严格校时 |
| payload | object 必需 | 下述各类型业务体 |

### observations payload

| 字段 | 类型/必需性/默认 | 解释 |
|---|---|---|
| batchId | string 必需 | 本批算法幂等ID；建议与messageId对应但二者角色独立 |
| fusionProfile | string 技术可省略；业务必填 | 本次multisensor-3d-v1。省略会回落legacy，不能省略后声称三维 |
| mode | string 默认realtime | MQTT只接受realtime，不通过此字段发离线replay/flush |
| observations | object[] 必需 | 规范观测列表，最大5000；不直接发送数据库整行代替清洗 |
| clockMode | string 可选 | 重放发送器标wallclock_rebase_1x；仅说明/指纹字段，不会自动替后端平移时间或支持倍速 |

### control payload

| 字段 | 类型/必需性 | 解释 |
|---|---|---|
| action | string 必需 | run.start、run.end、tick、flush；其他action拒绝 |
| writeOwner | string 可选 | http/mqtt/none 的适配器治理控制；更推荐公司后端使用HTTP原子handover接口 |
| handover | boolean 可选 | 请求正式写权转移，须与当前owner/generation策略一致 |
| handoverPending | boolean 可选 | 适配器侧治理标记，不能凭此绕过核心围栏 |
| resume | boolean 可选 | 请求解除适配器暂停；不等于恢复KF状态，根因未解决不能盲目resume |

run.start接收/记会话治理不等于算法已经有目标；profile由观测payload携带并持久保持。run.end/flush以队首不可变HTTP工作项执行，产生尾部result，run.end完成发drained。不要自己设置control.processingTime：当前适配器自行分配。

### ack payload

| 字段 | 类型 | 解释 |
|---|---|---|
| refMessageId | string | 引用原input/control消息ID；按此关联调用，不按相邻消息猜测 |
| status | string | 下表业务处理阶段/错误 |
| detail | object | 阶段相关详情；扩展字典，不保证每条都含全部key |
| replyTo | string/null | 当前build函数保留的字段，现有适配路径未提供动态回复topic路由；不要用它自行重定向 |

| ack.status | 后端含义与处理 |
|---|---|
| stored | 已入持久队列，还未承诺融合完成 |
| processed | 核心响应已进入可靠outbox；业务仍需收到result并落库 |
| duplicate | 同消息同内容已登记；可能原result仍待交付，不能伪造新点 |
| conflict | 同ID内容冲突/其他409；查看detail.body.error区分，禁止当普通重试成功 |
| rejected | 格式/字段/4xx拒绝；修数据，保留拒绝原因 |
| capacity / idempotency_capacity | 队列或幂等容量满；上游背压，不能换ID持续冲击 |
| idempotency_expired | 响应缓存已淘汰但ID在窗口内，未重算；后端查原持久结果，不能假称新成功 |
| transient_error / error | 网络/服务/执行失败；按明细及死信标记处理 |
| state_recovery_required | 核心epoch或状态丢失，停供并按恢复手册处理 |
| draining / pending | 结束过程未完成；不更新最终飞行成功 |
| drained | run.end算法侧排空完成；不等于后端事务完成或断点补齐 |

常见detail字段：action（控制动作）、errors（校验错误数组）、reason/error/note（原因）、httpStatus（内部HTTP状态）、body（原错误体）、attempt（重试次数）、deadLetter（是否终止重试）、inboxStats（队列状态计数）、pendingResults/outboxPending（未确认结果/待发消息数）、connected（当时Broker连接）、batchId。均按具体ack存在性解析，不把缺失当0；未知扩展key原样保留用于诊断。

### result payload

当前明确输出：refMessageId、replyTo、batchId、epoch、snapshotSeq、algorithmVersion、configVersion、fusionProfile、watermark、tracks、trajectoryUpdates、altitudeUpdates、events、rejected、error。与ProcessResponse同名字段含义相同；MQTT信封已给sessionId，所以payload没有再重复sessionId。

tracks为轻快照，省略committedHistory；不能只靠tracks重建全程。trajectoryUpdates和altitudeUpdates会按观测ID增加evidence；HTTP process没有适配器这一步，要由后端原始库补查。

run.end的尾部result是内部flush结果，refMessageId可为原control messageId加`-flush`，batchId可为`ctrl-run.end-flush-<controlId>`；drained ack仍引用原control消息。tick/flush也能产生result，所以结果条数不等于原始观测数，后端不能硬编码“一条input恰有一条result”。

### status payload

| 字段 | 类型 | 解释 |
|---|---|---|
| state | string | online/offline、backpressure、state_recovery_required、run_end、stopping等；开放枚举，未知值记录 |
| expiresHintS | number | 当前60，保留消息的鲜度提示，不是Broker自动TTL或在线承诺 |
| detail | object | 如clientId/schemaVersion、lwt、会话队列与错误原因；按实际状态解析 |

## 3. 规范模型逐字段

以下表由当前 models.py/WriteOwnerTransferRequest 声明逐项生成，并补充业务解释。必选性指HTTP模型声明；原始observations实际以dict进入解析器，**经纬度/观测时刻有效、具体设备ID仍是业务硬要求**，不能因为Observation模型标Optional就发送无效位置。MQTT还要求sourceTrackId存在；核心可为缺失局部号生成临时号，但不建议公司供入依赖此回退。

### Observation

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| observationId | `str` | 必需 | 每条测量唯一字符串；同SN多点必须不同ID，重发原测量保留同ID。 |
| source | `SourceKind` | 必需 | 规范源rid/spectrum/radar；DB pp/leida由后端分别映射spectrum/radar。 |
| detectorId | `str` | 必需 | 具体设备稳定ID，不能只填radar/rid等通用源名；参与局部身份键。 |
| sourceTrackId | `str` | 必需 | 设备局部目标ID；公司RID/频谱取id（SN），雷达取设备/后端局部号。 |
| aircraftId | `Optional[str]` | 可省略，默认 `None` | 可信无人机业务SN；公司RID/频谱按id；无可信SN的雷达为null。 |
| measurementTime | `str` | 必需 | 测量发生时间，带时区ISO8601；目前DB created_at仅为已声明假设，不能冒充已核实设备时间。 |
| receivedAt | `Optional[str]` | 可省略，默认 `None` | 公司后端实际接收时间；文件模拟可代理但须rawRef说明，非核心处理时间。 |
| timeBasis | `str` | 可省略，默认 `'created_at_assumed_measure'` | 时间依据标签；保留created_at假设/真实设备时间的区别，不自动改时间。 |
| longitude | `Optional[float]` | 可省略，默认 `None` | 经度（度）；输入核心要求有限且[-180,180]，与纬度同时0/0拒绝。 |
| latitude | `Optional[float]` | 可省略，默认 `None` | 纬度（度）；输入核心要求有限且[-90,90]，源坐标系由双方统一。 |
| altitude | `Optional[float]` | 可省略，默认 `None` | 海拔米；公司DB altitude按约定MSL；null未知，0/负值可有效。 |
| altitudeDatum | `Optional[str]` | 可省略，默认 `None` | 高度基准；本次规范供入显式MSL；未知不参与有效垂直融合，不是AGL。 |
| speed | `Optional[float]` | 可省略，默认 `None` | 水平速度m/s，不是km/h；设备单位需清洗确认。 |
| heading | `Optional[float]` | 可省略，默认 `None` | 航向角度0≤h<360；约定北0顺时针，越界时核心可忽略并标质量。 |
| verticalSpeed | `Optional[float]` | 可省略，默认 `None` | 垂直速度m/s；上正下负为双方供入约定，核对设备符号。 |
| qualityFlags | `list[str]` | 可省略，默认空数组 | 开放质量标签数组；保留USER_ASSUMED/未标定/缺测等说明，不等同拒绝。 |
| rawRef | `Optional[dict[str, Any]]` | 可省略，默认 `None` | 原始记录引用与映射元信息开放字典；不表示服务自动能查原文，勿传巨型正文。 |

### Rejected

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| observationId | `Optional[str]` | 可省略，默认 `None` | 每条测量唯一字符串；同SN多点必须不同ID，重发原测量保留同ID。 |
| reason | `str` | 必需 | 明确拒绝/操作原因字符串，须保存用于逐ID对账。 |
| detail | `Optional[str]` | 可省略，默认 `None` | 可选人类可读错误详情；不是稳定的控制状态机。 |
| rawRef | `Optional[dict[str, Any]]` | 可省略，默认 `None` | 原始记录引用与映射元信息开放字典；不表示服务自动能查原文，勿传巨型正文。 |

### SourceTrackRef

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| source | `SourceKind` | 必需 | 规范源rid/spectrum/radar；DB pp/leida由后端分别映射spectrum/radar。 |
| detectorId | `str` | 必需 | 具体设备稳定ID，不能只填radar/rid等通用源名；参与局部身份键。 |
| sourceTrackId | `str` | 必需 | 设备局部目标ID；公司RID/频谱取id（SN），雷达取设备/后端局部号。 |
| aircraftId | `Optional[str]` | 可省略，默认 `None` | 可信无人机业务SN；公司RID/频谱按id；无可信SN的雷达为null。 |
| lastSeen | `str` | 必需 | 此绑定来源最近观测时间；区别于目标状态时间。 |
| bindingStatus | `Optional[Literal['candidate', 'confirmed']]` | 可省略，默认 `None` | candidate候选或confirmed确认；绑定不等于当前点实质贡献。 |
| origin | `Optional[Literal['device', 'generated']]` | 可省略，默认 `None` | device设备提供，generated算法生成局部号；generated不是真实设备身份。 |

### TargetSnapshot

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| fusionId | `str` | 必需 | 完整融合目标ID；在session/epoch内解释，不能只截末8位作为数据库主键。 |
| trackSegmentId | `str` | 必需 | 分段ID，当前实现常等于fusionId；不同段不得跨接实测实线。 |
| aircraftId | `Optional[str]` | 可省略，默认 `None` | 可信无人机业务SN；公司RID/频谱按id；无可信SN的雷达为null。 |
| longitude | `Optional[float]` | 可省略，默认 `None` | 经度（度）；输入核心要求有限且[-180,180]，与纬度同时0/0拒绝。 |
| latitude | `Optional[float]` | 可省略，默认 `None` | 纬度（度）；输入核心要求有限且[-90,90]，源坐标系由双方统一。 |
| altitude | `Optional[float]` | 可省略，默认 `None` | 海拔米；公司DB altitude按约定MSL；null未知，0/负值可有效。 |
| altitudeDatum | `Optional[str]` | 可省略，默认 `None` | 高度基准；本次规范供入显式MSL；未知不参与有效垂直融合，不是AGL。 |
| altitudeMode | `Optional[str]` | 可省略，默认 `None` | 高度measured_filtered/预测predicted/过期expired/unknown等；预测高度不等同水平未来点。 |
| altitudeStateTime | `Optional[str]` | 可省略，默认 `None` | 垂直KF状态时刻，独立于水平stateTime。 |
| lastAltitudeObservedAt | `Optional[str]` | 可省略，默认 `None` | 最近有效高度测量时间；缺测预测不会伪造新测量时间。 |
| altitudeObservationIds | `list[str]` | 可省略，默认空数组 | 高度证据观测ID列表；快照可为近期窗口，逐点直接证据以增量为准。 |
| speed | `Optional[float]` | 可省略，默认 `None` | 水平速度m/s，不是km/h；设备单位需清洗确认。 |
| heading | `Optional[float]` | 可省略，默认 `None` | 航向角度0≤h<360；约定北0顺时针，越界时核心可忽略并标质量。 |
| verticalSpeed | `Optional[float]` | 可省略，默认 `None` | 垂直速度m/s；上正下负为双方供入约定，核对设备符号。 |
| stateTime | `str` | 必需 | 水平KF最近实际更新时刻；海拔增量中则是垂直更新时刻，不能混用。 |
| lastObservedAt | `str` | 必需 | 目标最近观测时刻，和状态时钟/显示时刻分别保存。 |
| displayStateTime | `Optional[str]` | 可省略，默认 `None` | 该快照对外展示查询时刻，可晚于stateTime，预测位置不是新提交点。 |
| trackStatus | `TrackStatus` | 必需 | tentative候选/tracked确认/coasting短暂预测/lost丢失/terminated终止；具体按配置生命周期。 |
| positionMode | `PositionMode` | 必需 | measured_assisted测量辅助/predicted预测/stale过旧，决定实测或预测展示。 |
| positionSource | `Optional[SourceKind]` | 可省略，默认 `None` | 当前主要水平位置源；不是每条输入都贡献位置。 |
| sources | `list[SourceKind]` | 可省略，默认空数组 | 已绑定来源种类集合，可能含候选/历史；与当前贡献不同。 |
| sourceTracks | `list[SourceTrackRef]` | 可省略，默认空数组 | SourceTrackRef数组，列设备局部号/SN/绑定状态等。 |
| qualityFlags | `list[str]` | 可省略，默认空数组 | 开放质量标签数组；保留USER_ASSUMED/未标定/缺测等说明，不等同拒绝。 |
| aliases | `list[str]` | 可省略，默认空数组 | 被并入的融合ID别名；保留映射和原始段，不据此补造缺口。 |
| committedHistory | `list[dict[str, Any]]` | 可省略，默认空数组 | 近期水平提交历史dict数组，上限80；MQTT轻快照省略，永久全程依赖后端保存增量。 |
| identityStatus | `Optional[Literal['unknown', 'identified', 'conflict']]` | 可省略，默认 `None` | unknown未知/identified已识别/conflict身份冲突；不能隐藏冲突。 |
| objectClass | `Optional[Literal['unknown', 'drone', 'bird', 'other']]` | 可省略，默认 `None` | unknown/drone/bird/other上游类别，非本服务完成鸟类识别。 |
| fusionMethod | `Optional[Literal['primary_source', 'multi_sensor_estimate']]` | 可省略，默认 `None` | primary_source主源方法或multi_sensor_estimate多源估计；按实际输出，勿用来源数量猜。 |
| contributingSources | `list[SourceKind]` | 可省略，默认空数组 | 目标累计实际贡献来源集合，不是当前单点直接观测ID清单。 |

### FusionEvent

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| type | `str` | 必需 | 开放事件类型字符串，未知type要保留记录。 |
| time | `str` | 必需 | 事件发生时间，带时区ISO8601。 |
| fusionId | `Optional[str]` | 可省略，默认 `None` | 完整融合目标ID；在session/epoch内解释，不能只截末8位作为数据库主键。 |
| payload | `dict[str, Any]` | 可省略，默认空数组 | 事件特定扩展字典；见动态事件说明，不保证每类key一致。 |

### ProcessRequest

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| sessionId | `str` | 必需 | 持久融合会话ID；租户/站点/业务运行需全局命名，不能每个观测新建。 |
| batchId | `str` | 必需 | 本次调用的稳定批次幂等ID；重试保持body含processingTime一致。 |
| mode | `Mode` | 可省略，默认 `'realtime'` | realtime在线、replay公开process历史模式、flush排空；MQTT input仅realtime。 |
| fusionProfile | `Optional[str]` | 可省略，默认 `None` | 新联调必填multisensor-3d-v1；HTTP process省略回legacy，ReplayRequest默认二维multisensor-v1。 |
| processingTime | `str` | 必需 | 核心水位处理时刻，带时区且同session单调不倒退；HTTP重试原body不变，MQTT由适配器首次队首执行生成。 |
| observations | `list[dict[str, Any]]` | 可省略，默认空数组 | 原始规范观测dict数组；额外scanId/positionStdM/objectClass可传，见扩展字段。 |

### ProcessResponse

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| sessionId | `str` | 必需 | 持久融合会话ID；租户/站点/业务运行需全局命名，不能每个观测新建。 |
| batchId | `str` | 必需 | 本次调用的稳定批次幂等ID；重试保持body含processingTime一致。 |
| epoch | `str` | 必需 | 核心会话代际字符串；重启/reset重建可变，后端不能把不同epoch结果当同一连续KF。 |
| snapshotSeq | `int` | 必需 | 该session/epoch的快照序号整数；去重/排序须带会话范围，不按MQTT到达顺序当算法时间。 |
| algorithmVersion | `str` | 必需 | 算法工程版本字符串，同时记录部署commit与模块指纹。 |
| configVersion | `str` | 必需 | 配置逻辑版本字符串，同时记录配置SHA；不得只看字符串认定文件相同。 |
| watermark | `str` | 必需 | 已提交事件时间前沿；落后此前沿的观测可被late_after_frontier拒绝。 |
| tracks | `list[TargetSnapshot]` | 必需 | 当前TargetSnapshot数组，可能包含预测/丢失状态，不是永久轨迹点清单。 |
| rejected | `list[Rejected]` | 必需 | Rejected数组，部分观测失败也可能HTTP200；必须逐ID统计。 |
| events | `list[FusionEvent]` | 必需 | FusionEvent数组，保留身份、生命周期、质量、别名和容量信息。 |
| error | `Optional[str]` | 可省略，默认 `None` | 批次/作业级错误字符串；null才是无顶层错误，仍需看rejected。 |
| fusionProfile | `Optional[str]` | 可省略，默认 `None` | 新联调必填multisensor-3d-v1；HTTP process省略回legacy，ReplayRequest默认二维multisensor-v1。 |
| trajectoryUpdates | `list[dict[str, Any]]` | 可省略，默认空数组 | 本次释放的不可变水平提交点数组，可因重排而为空；见动态结构。 |
| altitudeUpdates | `list[dict[str, Any]]` | 可省略，默认空数组 | 无新水平点时独立垂直更新数组，稳定altitudeUpdateId去重，不生成伪XYZ。 |

### ReplayRequest

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| jobId | `str` | 必需 | 离线作业ID，重放临时会话标识；不是恢复在线session。 |
| fusionProfile | `str` | 可省略，默认 `'multisensor-v1'` | 新联调必填multisensor-3d-v1；HTTP process省略回legacy，ReplayRequest默认二维multisensor-v1。 |
| observations | `list[dict[str, Any]]` | 可省略，默认空数组 | 原始规范观测dict数组；额外scanId/positionStdM/objectClass可传，见扩展字段。 |
| maxSnapshots | `int` | 可省略，默认 `2000` | 离线最多返回快照数，至少1；只影响快照采样不裁输入/已收集trajectory。 |

### ReplayResponse

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| jobId | `str` | 必需 | 离线作业ID，重放临时会话标识；不是恢复在线session。 |
| fusionProfile | `str` | 必需 | 新联调必填multisensor-3d-v1；HTTP process省略回legacy，ReplayRequest默认二维multisensor-v1。 |
| algorithmVersion | `str` | 必需 | 算法工程版本字符串，同时记录部署commit与模块指纹。 |
| configVersion | `str` | 必需 | 配置逻辑版本字符串，同时记录配置SHA；不得只看字符串认定文件相同。 |
| summary | `dict[str, Any]` | 必需 | 离线处理统计开放字典，见summary表；不是关联精度。 |
| snapshots | `list[dict[str, Any]]` | 必需 | 离线已采样快照dict数组，末帧保留；含batchId/processingTime/watermark/tracks/altitudeUpdates。 |
| trajectory | `list[dict[str, Any]]` | 必需 | 离线全次去重水平提交点数组，结构同trajectoryUpdates；不是缺口补点。 |
| altitudeUpdates | `list[dict[str, Any]]` | 可省略，默认空数组 | 无新水平点时独立垂直更新数组，稳定altitudeUpdateId去重，不生成伪XYZ。 |
| events | `list[dict[str, Any]]` | 必需 | FusionEvent数组，保留身份、生命周期、质量、别名和容量信息。 |
| rejected | `list[dict[str, Any]]` | 必需 | Rejected数组，部分观测失败也可能HTTP200；必须逐ID统计。 |
| error | `Optional[str]` | 可省略，默认 `None` | 批次/作业级错误字符串；null才是无顶层错误，仍需看rejected。 |

### WriteOwnerTransferRequest

| 字段 | 类型 | 必需性 / 默认 | 解释 |
|---|---|---|---|
| owner | `str` | 必需 | 要转到http/mqtt/none的写权拥有方；该管理接口要受网关权限限制。 |
| fromOwner | `Optional[str]` | 可省略，默认 `None` | 可选预期原owner，防止错误移交。 |
| expectedGeneration | `Optional[int]` | 可省略，默认 `None` | 可选预期当前写代际；公司联调应显式传读到的值，竞争变化返回409。 |
| reason | `Optional[str]` | 可省略，默认 `None` | 明确拒绝/操作原因字符串，须保存用于逐ID对账。 |

### observations额外实现字段

| 字段 | 类型 / 默认 | 解释 |
|---|---|---|
| scanId | string/null | 一次设备扫描的组号；同detectorId+scanId的多目标整组分配，不能用它作SN。 |
| positionStdM | number/null | 水平位置标准差（米），正值；核心使用方差std²，缺失取各源未标定默认值。 |
| objectClass | string 默认unknown | unknown/drone/bird/other，上游提供的类别，非算法在此识别鸟类。 |


## 4. 动态增量结构（dict类型，OpenAPI无法展开）

### trajectoryUpdates[] / ReplayResponse.trajectory[] / tracks[].committedHistory[]

| 字段 | 类型 | 解释 |
|---|---|---|
| pointId | string | 水平提交点稳定ID；按session+epoch+pointId去重 |
| fusionId / trackSegmentId | string | 完整目标/分段标识；当前实现segment常与fusionId相同，消费者仍分别保存 |
| stateTime | string | 此点水平状态/测量更新时刻，非本次网络接收时刻 |
| longitude / latitude | number | 滤波后的水平位置（度） |
| altitude | number/null | 此点时刻的海拔估计/滤波值；不是最近快照高度的回填 |
| altitudeDatum | string/null | 有效垂直输出MSL；未知null |
| altitudeMode | string | measured_filtered / predicted / expired / unknown；旧二维剖面可能passthrough |
| altitudeSigmaM | number/null | 此时刻海拔标准差（米），不是精度实测值 |
| positionMode | string | 提交点通常measured_assisted；水平预测单独作为展示，非实测轨迹 |
| contributingSources | string[] | 目标状态的累计贡献来源，不等于本点直接输入的完整清单 |
| observationIds | string[] | 该水平提交使用的原始测量ID；由此追查SN/原始XYZ/时刻 |
| altitudeObservationIds | string[] | 该点垂直直接证据ID，可与水平不同/为空；预测高度不伪造本时刻观测 |
| altitudePriorNote | string/null | filter_state_may_include_earlier_measurements说明垂直滤波状态可能包含更早测量影响，不是只平均当前证据 |
| source | string | 触发该水平提交的规范源 |
| evidence | object[] 可选 | MQTT适配按声明ID补的原始证据；见下表，HTTP无此附加字段 |

### altitudeUpdates[]

| 字段 | 类型 | 解释 |
|---|---|---|
| altitudeUpdateId | string | 独立高度更新ID；不能当pointId生成XYZ点 |
| fusionId / trackSegmentId / epoch | string | 所属目标、段与核心代际 |
| stateTime | string | 本高度更新时刻 |
| altitude / altitudeDatum / altitudeMode | number/string | 垂直状态值、MSL基准、更新模式 |
| verticalSpeed | number/null | 垂直速度m/s |
| altitudeStateTime | string/null | 垂直KF状态时间 |
| lastAltitudeObservedAt | string/null | 最近有效高度测量发生时间 |
| altitudeObservationIds | string[] | 本次高度更新输入的原始观测ID |
| role | string | 当前secondary_or_vertical_only，表示无新水平提交的垂直更新 |
| source | string | 触发更新的源 |
| evidence | object[] 可选 | MQTT附加的原始证据；类型见下表 |

### evidence[]：这一融合点到底用了谁的点

| 字段 | 类型 | 解释 |
|---|---|---|
| observationId | string | 原始测量唯一ID，后端原始库查找键 |
| source / detectorId / sourceTrackId | string | 源、设备、设备局部目标号；不可只按SN回查全部点 |
| aircraftId | string/null | 可信公司SN映射；雷达无可信SN应null |
| longitude / latitude / altitude | number/null | **原始规范观测**的位置/海拔，区别于融合输出值 |
| altitudeDatum | string/null | 该原始高度基准 |
| measurementTime / receivedAt | string/null | 原始测量发生/后端接收时间 |
| scanId | string/null | 同设备扫描组号，不是无人机身份 |
| snMappingVersion | string | 从rawRef/输入/旧回退得到的映射版本；公司供入显式写company_source_id_sn_v1避免回退confirmed_sn_v1 |
| altitudeMappingVersion | string | 公司database_altitude_msl_v1；是约定版本，不是物理转换结果 |
| role | string | position_update / altitude_update / position_and_altitude_update |
| roles | string[] 可选 | 同观测同时用于两轴时保留两角色；不能覆盖成单角色 |
| rawRef | object/null | 原始记录引用/来源说明，开放字典；建议只放可回查键/映射假设，不塞巨型原文 |

rawRef建议字段：databaseTable/rowKey（公司自定义可回查原件引用）、snMappingVersion、altitudeMappingVersion、altitudeMappingAssumption=USER_ASSUMED、originalMeasurementTime、simulatedMeasurementTime、timeOffsetSeconds、file/line等发送器来源信息。它们是审计元信息，算法不自动读取公司数据库、下载URL或执行高程转换；不要把原文省略标记当成可恢复下载链接。

## 5. events 与错误

FusionEvent.type 为开放字符串，time为事件时刻、fusionId可null、payload为事件特定字典。常见类别：轨迹创建/确认/丢失/重获/终止，来源绑定/主源变化，identity_ambiguous/身份冲突，alias、capacity、altitude_innovation_rejected。以实际事件字符串为准，消费者未知type需保留并显示诊断，不能因未知type丢整条result。

payload的常见key含observationId、source/detectorId/sourceTrackId、候选IDs、reason、创新距离/门限、aliasOf等。`alias`中的payload.aliasOf是被并入的旧ID，事件fusionId是保留ID；不要反向覆盖。若业务要把某类事件当控制信号，需按当前源码进一步锁定该type的payload结构，不能把任意扩展字段当强制存在。

| HTTP状态/错误 | 业务处理 |
|---|---|
| 200 + rejected非空 | 批次业务响应成功，但部分观测被拒绝；逐ID记录 |
| 400 invalid_processing_time / processing_time_not_monotonic | 处理时钟非法/倒退；修生产时钟，原超时重试保留原body |
| 409 batch_id_conflict / observation_id_conflict | 相同ID不同内容，查原数据，不覆盖 |
| 409 session_mode_conflict / session_profile_conflict | 同会话模式/profile冲突，不能在在线会话临时改剖面 |
| 409 idempotency_expired / idempotency_capacity | 缓存结果已淘汰或幂等容量满；不代表重算成功 |
| 409 write_owner_* / write_generation_* | 双通道写权或代际错误，正式handover/修headers |
| 413 too_many_observations | 请求条数超限；实时合理小批，离线不能随意分块后硬拼 |
| 422 unsupported_profile / FastAPI校验错误 | 修字段/profile；FastAPI detail可能是数组，业务error detail也可能是对象 |
| 500 batch_rollback | 批次失败回滚；用原ID原body重试并报警 |
| 503 ready not_ready | 服务配置未就绪，禁止正常供入 |

核心 rejected.reason 示例：unknown_source、missing_detector_id、detector_id_not_specific、invalid_measurement_time、future_timestamp、late_after_frontier、non_finite_position、position_out_of_range、position_placeholder_0_0、scan_closed、max_tracks。qualityFlags 可能说明heading被忽略、标准差未标定等，不全部代表拒绝。

## 6. replay summary / snapshots

| summary字段 | 类型 | 解释 |
|---|---|---|
| input | integer | 输入行数 |
| processed | integer | 内部批次实际处理行数；结合拒绝看，不代表全部有效 |
| valid / rejected / unprocessed | integer | 当前实现按拒绝ID估算valid、拒绝记录数、未处理行数；不是精度/关联正确率 |
| by_source | object | 规范源→输入条数 |
| time_range | string[2]/null | 有效输入时间最小/最大 |
| tracks_in_last_snapshot | integer | 最后快照目标数 |
| distinct_fusion_ids | integer | 历史快照和别名ID数，不是唯一实体真值 |
| last_snapshot_track_count_is_not_total_targets | boolean | 明确末帧数不等于全程目标总数 |
| trajectory_points / altitude_updates | integer | 输出水平提交点/独立高度更新数 |
| note | string | 正常sorted_replay_not_rts_smoother；采样/失败说明 |
| offline_vs_realtime | string | 离线排序后flush，实时拒前沿之前观测的说明 |
| error（错误分支） | string | unsupported_profile / too_many_observations等，不能仅凭空结果判成功 |

snapshots[]字段：batchId（该内部批次）、processingTime（该次处理时间）、watermark（水位）、tracks（TargetSnapshot[]）、altitudeUpdates（该次独立高度更新）。maxSnapshots只控制快照采样，末帧保留；不能用采样快照数估算处理点数。
