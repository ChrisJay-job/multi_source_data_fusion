# 时钟语义（TASK-008）

| 字段 | 含义 | 本轮默认 |
|------|------|----------|
| `measurementTime` | 观测发生时刻 | CSV `created_at` + 统一 wall-clock rebase offset |
| `receivedAt` | 后端收到时刻 | 发送器默认代理为 rebase 后的 measurementTime，并在 rawRef 保留原始时刻 |
| `processingTime` | 算法处理水位时刻 | **适配层**创建不可变 work item 时写入 UTC now；同 work item 重试不变 |
| `sentAt` | MQTT 信封发送时刻 | 发布当下 UTC |
| `originalMeasurementTime` | 文件原始时刻 | 仅 rawRef；不送入算法时钟 |

## 1x 发送

发送器按相邻行原始 `created_at` 差值 `sleep`（单段上限 30s）。`--speed` 仅允许 `1.0`；其它值直接拒绝，避免“只缩短 sleep、其它时钟不跟”的假倍速。

## 模拟时钟 vs 真实时钟

- `clockMode=wallclock_rebase_1x`：历史文件平移到“现在”播放，相对间隔保留。
- 虚拟倍速时钟（measurement / processing / tick 同速推进）**未实现**；实现前禁止声称支持非 1x。

## 禁止

- 把六月 `measurementTime` 原样配十月 `processingTime` 而不 rebase。
- 把所有观测时间改成发送瞬间而丢掉相对间隔。
- 适配器删除或伪造 `scanId` / `positionStdM`。
