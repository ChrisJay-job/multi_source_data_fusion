# TASK-008 MQTT 适配 — 运行说明（R1 隔离版）

> **历史说明 → 当前权威入口：** Linux/Compose 部署与联调以  
> [`docs/integration/task010/`](../integration/task010/01_LINUX_DEPLOY.md) 为准。  
> 本文保留本地 18099 / Broker 隔离联调步骤；审查前「禁止 commit」约束已被 TASK-010 授权取代。

工作树：`multi_source_data_fusion_wt_task008`。

**隔离硬约束**：原已审查服务继续占用 **18089**，本轮新版本 HTTP 使用 **18099**；MQTT Broker 只绑定 **127.0.0.1:1883**。不要停止或替换 18089。

## 1. 依赖

```bash
pip install -r requirements.txt
# 含 paho-mqtt==2.1.0
```

## 2. 本地 Broker（127.0.0.1 only）

```bash
# 生成本地口令文件（一次）
docker run --rm -v "%CD%/config:/mosquitto/config" eclipse-mosquitto:2.0.20 \
  mosquitto_passwd -b -c /mosquitto/config/passwd_task008 fusion_local fusion_local_dev_only

docker compose -f docker-compose.task008.yml up -d
```

确认映射为 `127.0.0.1:1883→1883`；不要动 18089。

## 3. 启动隔离 HTTP 核心（新版本，18099）

```bash
set PYTHONPATH=src
uvicorn fusion_mvp.api:app --host 127.0.0.1 --port 18099
```

健康检查：`curl http://127.0.0.1:18099/ready`  
工作台入口：`http://127.0.0.1:18099/`（别名 `/demo/workbench/` 同页）。

写入围栏：MQTT 适配器在 `/v1/fusion/process` 上携带 `X-Fusion-Channel: mqtt`，并按**会话**持久携带 `X-Fusion-Write-Generation`（首次成功 claim 后记住 gen=1；移交后更新为新代际）。核心按 session 原子维护 owner+generation+retired_max。

- 已治理的 MQTT 会话：缺代际或旧代际 → 409（`write_generation_required` / `write_generation_mismatch` / `write_generation_retired`）。
- 纯 HTTP/default（从未 MQTT 接管、owner=http 且 gen=1）可省略代际头以保持兼容。
- `owner=none` 释放会保留 `retired_max`，旧代际不能复活；下一 claim 从 retired_max+1 起。
- 适配器代际按 session 隔离：A 移交不会改 B 的请求头。

写权转移（MQTT→HTTP→MQTT，同 session，不 reset）：

```bash
# 查当前 owner/generation
curl http://127.0.0.1:18099/v1/fusion/session/<sessionId>/write-owner

# 正式移交（bumps generation；旧 generation 失效）
curl -X POST http://127.0.0.1:18099/v1/fusion/session/<sessionId>/write-owner ^
  -H "Content-Type: application/json" ^
  -d "{\"owner\":\"http\",\"fromOwner\":\"mqtt\",\"expectedGeneration\":1,\"reason\":\"broker_down_http_fallback\"}"
# 别名：POST /v1/fusion/session/<sessionId>/handover

# 失败示例：缺代际 / 旧代际
curl -X POST http://127.0.0.1:18099/v1/fusion/process ^
  -H "Content-Type: application/json" -H "X-Fusion-Channel: mqtt" ^
  -d "{...}"   # → 409 write_generation_required（会话已有 owner）
```

适配器侧也可发 control：`writeOwner=http` + `handover=true`（适配器调用上述核心 API 并按 session 更新本地代际）。Broker 不可用时仍可用 HTTP 路径接管；核心不重启。不得用 reset/新 session 代替连续回退。

旧 HTTP 兼容示例（仍用 legacy / multisensor-v1，不启用海拔映射）：见 `01_schema_examples.md`。

## 4. 启动 MQTT 适配（指向 18099）

```bash
# 可选：复制 config/task008.env.example 并改 TASK008_HTTP_BASE
set PYTHONPATH=src
set TASK008_HTTP_BASE=http://127.0.0.1:18099
python -m fusion_mvp.integration
```

默认 `fusionProfile` 示例为 **multisensor-3d-v1**（见 sender / schema 样例）；旧剖面仍可显式指定。

## 5. 接收器（模拟后端）

```bash
python scripts/task008_mqtt_result_receiver.py
```

## 6. CSV 1x 发送（与文件页共用 database_altitude_msl_v1）

```bash
python scripts/task008_csv_mqtt_sender.py ^
  --csv samples/task007/5_rid_pp5_leida1_simp.csv ^
  --fusion-profile multisensor-3d-v1 ^
  --altitude-mapping database_altitude_msl_v1 ^
  --source-timezone Asia/Shanghai ^
  --max-rows 50

# 非 1x 会被拒绝：
python scripts/task008_csv_mqtt_sender.py --csv ... --speed 2
# → exit 2 REFUSED
```

较大样本：`samples/task007/5_leida_rid_pp.csv`（建议先 `--max-rows 50` 冒烟）。

## 文档索引

| 文件 | 内容 |
|------|------|
| `00_contract_fusion_mqtt_v1.md` | Topic / 处理链 / 幂等 |
| `01_schema_examples.md` | JSON 样例 |
| `02_clock.md` | 时钟与 1x |
| `03_sn_and_altitude_mapping.md` | SN / MSL 映射 |
| `04_http_mqtt_parity.md` | HTTP↔MQTT |
| `05_recovery.md` | 恢复边界 |
| `06_tomorrow_backend_checklist.md` | 明日对接 |
| `07_vertical_altitude_fusion.md` | 垂直滤波语义 |
| `08_performance_and_limits.md` | 性能门槛与本轮实测记录 |
