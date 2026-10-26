# 恢复与边界（TASK-008 MQTT 适配）

## 适配器重启

SQLite inbox/outbox 持久化：

1. 启动后重订阅 `input` / `control`
2. 对 `pending` / `processing` inbox 按 session 继续串行处理
3. 对 `pending` outbox 在 MQTT 重连后重发（QoS1）；接收器按 `messageId` 去重落库
4. 同 ID 同内容历史重送 → `duplicate`，不重算

**不是**算法 KF 状态恢复。

## 算法进程重启

内存 Store 丢失 → epoch 变化或会话消失。适配检测到业务错误后可发 `status.state_recovery_required`。  
**本轮不**用临时 replay 假装恢复了实时 Store；人工步骤：新 session 或约定 reset 后重送。

## Broker 重启 / 断线

- 客户端 `clean_session=false` + 有界重连退避
- LWT/status retain 提示 offline
- 已持久 inbox 在重连后继续；不因 fallback HTTP 偷偷跳过队列领先（切换须显式）

## 队列 / 磁盘

`TASK008_MAX_INBOX` 满 → 不入 inbox，ack=`capacity`，status=`backpressure`。不静默丢且不 ACK 为业务完成。

## run.end

对指定 session 给出 inbox 账目与排空信号；**不**重置其它 session；**不**等于飞行最终航线修复完成。

## 已知非目标

- 多 worker 共享内存会话  
- 跨进程自动 KF 恢复  
- 公司生产 Broker / TLS ACL（参数未授权前不探测）
