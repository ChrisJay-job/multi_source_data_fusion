# TASK-003 attempt-001 REVIEW_READY

状态：**REVIEW_READY**（未 commit / tag / push / 冻结）。

## 启动

```bash
docker compose up api
# 或已有 fusion-mvp-workbench → http://127.0.0.1:18089/
```

## 测试

- Docker Python 3.11：`pytest -q` → **83 passed**（原 76 + TASK-003 7 项及相关迁移）
- 浏览器：`node scripts/browser_workbench_task003.mjs` → 1366×768 / 1920×1080 全绿

## 关键路径

- 指令：`review_zip/TASK-003_attempt-001_Seven_Aircraft_Usability_and_Association.md`
- 样例：`samples/workbench/user_four_aircraft_20261019.json`、`…_explicit_swap20.json`
- 七机：`scenarios/seven_aircraft_combinations.json` + preset
- 根因：`reports/task003/rootcause_and_fix.md`
