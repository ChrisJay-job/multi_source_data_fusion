# fusion-mqtt.v1 契约（TASK-008）

版本：`fusion-mqtt.v1`。本地隔离 Broker 联调草案；公司参数确认前不连生产。

## Topics

前缀默认 `fusion/v1/{tenant}/{site}/`（可用 `TASK008_TOPIC_PREFIX` / tenant / site 配置）。

| Suffix | 方向 | QoS | retain | 内容 |
|--------|------|-----|--------|------|
| `input` | 后端→适配 | 1 | **false** | 规范观测批次 |
| `result` | 适配→后端 | 1 | **false** | tracks + trajectoryUpdates + events/rejected |
| `ack` | 适配→后端 | 1 | **false** | stored / processed / duplicate / conflict / … |
| `control` | 后端→适配 | 1 | **false** | run.start / run.end / flush / tick |
| `status` | 适配→后端 | 1 | true（带过期提示） | online / offline / backpressure / state_recovery_required |

## 处理链

MQTT 接收 → 有界校验 → SQLite inbox → **按 session 串行** → 不可变 HTTP work item → `POST /v1/fusion/process` → outbox → 发布 result + ack。

网络回调内不做融合计算。Broker PUBACK ≠ 算法算完；应用层区分：`stored`（inbox 持久）/ `processed`（HTTP 响应已入 outbox）/ 后端 receiver 落库。

## 幂等

- 同 `messageId` + 同内容指纹：不重算，ack=`duplicate`
- 同 `messageId` + 不同内容：ack=`conflict`，不覆盖
- work item 的 `processingTime` / observations / batchId 首次生成后固定；HTTP 超时重试用原 body

## 实现位置

- 适配：`src/fusion_mvp/integration/`
- 发送器：`scripts/task008_csv_mqtt_sender.py`
- 接收器：`scripts/task008_mqtt_result_receiver.py`
- Compose：`docker-compose.task008.yml`
