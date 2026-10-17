# REWORK Round3 变更清单

## 源码

- `src/fusion_mvp/engine.py` — R3-01 空缓冲水位；R3-02 同刻主源稳定排序；lifecycle `mutate_filter=False` 语义
- `config/fusion.yaml` — `primary_source_order: [rid, spectrum, radar]`
- `tests/test_round3_regressions.py` — 审查附带 2 项（未削弱）

## 运行配置（包内保留）

- `pytest.ini`（`testpaths=tests`，避免收集 `review_zip`）
- `docker-compose.yml`、`demo/index.html`

## 未改

- Round1／Round2 证据目录保留不覆盖
- 原始 2GB SQL 不入包
- 不引入五源／复杂滤波／仿真编辑器
