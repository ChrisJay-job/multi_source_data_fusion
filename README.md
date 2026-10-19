# 三源融合 MVP（RID / 频谱 / 雷达）

1–2 天可运行、可回放、可检查的最小实现。原始 SQL **只读**；需要库时用隔离端口 `25432`。

## 环境

- Docker（本机 WindowsApps Python 为占位，推荐容器）
- 勿连生产库 / 已占用 `5432`/`15432`

## 启动 API／验证台

```bash
docker compose up api
# 宿主端口 18089；占用时改 docker-compose.yml
```

或：

```bash
docker run --rm -p 127.0.0.1:18089:18089 -v "%CD%":/work -w /work -e PYTHONPATH=/work/src python:3.11-slim bash -c "pip install -q -r requirements.txt && uvicorn fusion_mvp.api:app --host 0.0.0.0 --port 18089"
```

- 验证台：<http://127.0.0.1:18089/>
- 旧演示：<http://127.0.0.1:18089/demo>
- 健康：<http://127.0.0.1:18089/ready>

TASK-001 基线 tag：`task-001-three-source-fusion-mvp-v1` → commit `a80553fd…`（本地，未 push）。  
TASK-002：**FROZEN（本地）** tag `task-002-fusion-validation-workbench-v1`（分支 `task-002-fusion-validation-workbench`，未 push）。  
冻结记录：`reports/task002_freeze/freeze_record.md`。  
验证边界保留：真实三源关联 **BLOCKED**；现场精度 **NOT_TESTED**；全量约 2GB SQL **NOT_TESTED**。

## 测试

```bash
docker run --rm -v "%CD%":/work -w /work -e PYTHONPATH=/work/src python:3.11-slim bash -c "pip install -q -r requirements.txt && pytest -q"
```

## 数据体检 / 真实抽样回放

```bash
docker run --rm -v "%CD%":/work -w /work python:3.11-slim python scripts/inspect_insert_dump.py /work/data/aircraft_flight_data.sql --out-json /work/reports/data_profile.json --sample-dir /work/samples/real

docker run --rm -v "%CD%":/work -w /work -e PYTHONPATH=/work/src python:3.11-slim bash -c "pip install -q -r requirements.txt && python scripts/replay_real_samples.py"
```

## 隔离 Postgres（可选，全量导入慎用）

```bash
docker compose up -d postgres
# 确认无 DROP 副作用后再对 127.0.0.1:25432 导入；不要把 2GB 一次灌进模型上下文
```

## Flow2Spec

已用 CLI：`flow2spec version` / `config` / `doctor`。任务根：`.task/chriswork400/`。
