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
TASK-002：**FROZEN（本地）** tag `task-002-fusion-validation-workbench-v1` → `5749a240…`（未 push）。  
TASK-003：**FROZEN（本地）** tag `task-003-workbench-usability-and-association-v1`（未 push）。七机可用性、轨迹显示与关联评估契约见 `reports/task003*`；冻结记录 `TASK-003-local-freeze-record.md`。  
TASK-005：**本地冻结** tag `task-005-hard-scenarios-and-explainable-workbench-v1`（未 push）。高难合成场景与可解释验证台；候选包 Round3；冻结记录 `TASK-005-local-freeze-record.md`。  
验证边界保留（TASK-005 同口径）：验证台软件与已登记合成场景可本地冻结，**不**表示困难场景算法全通过或现场精度达标；困难合成场景保留每例实际 PASS/FAIL/不可计算；ID 交换仅可靠身份可映射子集；已提交/展示位置误差分列（末点≠全程）；真实三源同目标关联 **BLOCKED**；现场精度 **NOT_TESTED**；约 2GB 全量 SQL **NOT_TESTED**；TASK-004 仍待设备/后端外部确认（phase1 未开始）。不代表客户/现场验收通过。

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
