# TASK-002 变更清单

## 新增

- `src/fusion_mvp/workbench/` — scenario／importer／runner／evaluator
- `demo/workbench/` — 验证台 UI
- `docs/interface/` — 三层接口说明 + CSV 确认表 + 正反例
- `scenarios/three_aircraft_primary.json`
- `samples/workbench/mix_ok.csv`
- `tests/test_workbench_w01_w10.py`
- `python-multipart` 依赖（上传）

## 修改

- `src/fusion_mvp/api.py` — workbench 路由；默认首页验证台
- `src/fusion_mvp/models.py` / `engine.py` — `sourceTracks.bindingStatus`
- `README.md` — 启动与 URL

## 不变

- `/v1/fusion/process` 核心语义；TASK-001 原回归保留
- 原始 SQL 只读、不入包
