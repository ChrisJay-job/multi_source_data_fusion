# TASK-008 后端联调交接（R10 候选）

> **历史说明 → 当前权威入口：** 三方联调、Linux 部署、字段字典与发布指纹以  
> [`docs/integration/task010/`](../integration/task010/00_README.md) 及 `RELEASE_RECORD.md` 为准。  
> 本文保留 TASK-008 R10 时期接口/运行说明，默认 profile / 审查状态可能过时；勿将旧全量 302/312 pytest 包装为当前发布结果。

**状态（历史）：** 本地功能联调候选 · **非**审查冻结 / **非**生产验收  
**基线：** `badcaf8` / tag `task-007-multisensor-v1-map-r2-reviewed`  
**治理（历史）：** 后续已完成 TASK-008/009 审查收尾；整合发布见 TASK-010  
**本轮（历史）：** 关闭 R10-01～02（保留 R9 修复）。

---

## 1. URL

| 入口 | URL |
| --- | --- |
| 正式工作台 | **http://127.0.0.1:18099/** |
| 轻量控制 | **http://127.0.0.1:18099/demo/workbench/control.html** |
| 旧已审页 | http://127.0.0.1:18089/（勿改） |

### 事件传输（R10）

- 响应仍有条数/UTF-8 字节预算。  
- 大 result：**瘦身 tracks（去掉 committedHistory）** 并保留 trajectoryUpdates / altitudeUpdates / rejected / 证据；必要时 `shardOffset` 分片。  
- **禁止** body-less oversized stub 推进游标冒充完整。  
- 缓存前缀淘汰 → `historyGap`；游标到尾但缺口时**不得**称画面完整。  
- 逐 ID：`GET /v1/workbench/mqtt-stream/{runId}/ledger`

### 停止 / 重开

- stop 须真实 drained；无 drained ≠ 正常 stopped。  
- 重开/第二观察者：自动切到真实数据页并显示「继续显示」；用正式按钮，勿依赖注入 poll。

### 时钟

- MQTT 推流固定 **1× 墙钟**。事件缓存按入队 UTF-8 字节累计，禁止全缓冲反复 JSON 序列化。

---

## 2. 本地 MQTT

Broker `127.0.0.1:1883` · `fusion_local` / `fusion_local_dev_only` · `TASK008_HTTP_BASE=http://127.0.0.1:18099`

---

## 3. 公司约定（保留）

`database_altitude_msl_v1` · `company_source_id_sn_v1` · HTTP+MQTT 双通道

---

## 4. R10 联合摘要

- run `20261025T110822-069d0fd0`：~131s 仍 running；late_after_frontier **0**；stopped+drained；双观察者 UI continue；重开有真实点且 gap 明示  
- 证据：`reports/task008/r10/evidence/browser/`

---

## 5. 仍 BLOCKED / DEFERRED / NOT_TESTED

公司 Broker/TLS、30min 长稳、现场精度、生产容量

---

## 6. 治理

**AWAITING_INDEPENDENT_REVIEW**。禁止 commit/tag/push/冻结/合并/下一阶段。
