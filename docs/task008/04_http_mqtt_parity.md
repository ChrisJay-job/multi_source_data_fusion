# HTTP ↔ MQTT 对等与回退

## 共核

MQTT 适配**只**调用存活 HTTP：`POST {TASK008_HTTP_BASE}/v1/fusion/process`。

- 同一 `sessionId` / `batchId` / `fusionProfile` / observations / 固定 `processingTime`
- 不在适配层复制第二套 KF
- Broker 或适配停止时，HTTP 核心可独立继续服务

## 字段投影

| HTTP ProcessResponse | MQTT result.payload |
|----------------------|---------------------|
| tracks（含 committedHistory） | tracks **去掉** committedHistory |
| trajectoryUpdates | 原样 + 按 observationId 回填 evidence |
| events / rejected / epoch / watermark / versions | 透出 |
| error | 透出；并映射到 ack status |

## 错误映射（摘要）

| HTTP | MQTT ack.status |
|------|-----------------|
| 200 | processed（另有先行 stored） |
| 409 | conflict |
| 400 / 422 | rejected |
| 413 | capacity |
| 5xx / 传输失败 | transient_error（有界重试） |
| idempotency_expired | idempotency_expired（不改 ID 重跑） |

## 同 session 所有权

同 session 输入在适配层串行队列；跨 session 有限并发（`TASK008_MAX_SESSION_WORKERS`）。  
**不要**让 HTTP 调用方与 MQTT 队列对同一 session 无序双写；切换所有权须：暂停入流 → 排空/登记未完成 → 确认水位 → 再切换（本轮文档要求；运维切换 checklist 见明日对接清单）。

## 回退

1. 停适配进程 / 断 Broker  
2. 后端改直连 HTTP process（相同 profile 与 ID）  
3. 算法进程未重启时身份连续；已重启则 epoch 变化，需 `state_recovery_required` 人工恢复（本轮不做自动 KF 重建）
