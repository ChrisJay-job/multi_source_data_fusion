# TASK-008 性能与边界（R1 实测）

## 已跑（隔离 18099 / 本机 Broker）

| 项 | 结果 | 证据 |
|---|---|---|
| 全量 pytest | **302 passed / 2 skipped**（完整 XLS 外部 skip） | `reports/task008/r1/pytest_full.log` |
| 官方 probes | 全部 `pass: true` | `reports/task008/r1/probe_results.json` |
| HTTP `/ready` + 3d import | 200，MSL，有垂直输出 | `http_ready.json` / `http_import_3d.json` |
| 合成垂直 RMSE | ≈1.69 m（20 点爬升/下降） | `vertical_rmse.json` |
| 120s @5Hz×5 目标 | p95≈45ms，rejects=0 | `soak_120s.json` |
| 1800s @5Hz×5 目标 | 见 `soak_30min.json` | 同左 |
| MQTT CSV 短链路 | inbox done=9，receiver result=9，含 altitudeUpdates | `mqtt_e2e_summary.json` |
| 两视口浏览器 | 1920×1080 DPR1 + 1280×800 DPR2 | `viewports/` |

## 仍不声称

| 项 | 状态 |
|---|---|
| 公司生产 Broker 联调 | NOT_TESTED |
| 客户现场三源同机精度 | BLOCKED |
| p95≤200ms / E2E≤3s | 本机合成达到 p95≤200ms；公司链路未测，不作交付承诺 |

## 已知限制

- 算法进程内存会话；重启 → `state_recovery_required`，本轮不自动重建 KF。
- 幂等容量有界（`max_idempotency_ids=24576`，TTL 1800s）；TTL 过期先清理再判容量。
- 会话按空闲 TTL 回收。
- 本机 Mosquitto 因 Docker Desktop 单文件挂载 chown 限制改为 `allow_anonymous true` 且仅绑定 `127.0.0.1`。
