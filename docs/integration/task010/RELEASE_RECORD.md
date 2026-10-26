# TASK-010 attempt-001 发布与交接记录

日期：2026-10-26（Asia/Shanghai）  
**状态：`MAIN_INTEGRATED_REMOTE_VERIFIED_HANDOFF_READY`**

本记录为联调部署权威入口。公司 Linux / Broker / TLS / 前端 topic 参数仍为待填写；**未**宣称公司生产已上线。

---

## 1. Git 操作结果

| 项 | 值 |
|---|---|
| 工作整合树 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task010_integ`（隔离 worktree，未动 TASK-004/005/006 dirty） |
| 业务提交线 | `task-008-mqtt-realtime-and-point-inspection` |
| 业务 commit | `73182f5d8846c209b5d2a0eb888863deefa5edf7`（已审 TASK-008/009 + TASK-010 文档/部署） |
| 测试对齐 commit | `665613e3e152620e1c0eb1853638d19fab9d7cbd`（TASK-007 回归适配；**代码/指纹锁定点**） |
| 本发布记录 commit | （见推送后 tip；仅文档，算法指纹仍同 665613e） |
| **最终 remote `origin/main`** | 以 `git ls-remote origin refs/heads/main` 回读为准（本轮已成功创建并推送 `main`） |
| 远程 | `https://github.com/ChrisJay-job/multi_source_data_fusion.git`（此前无 heads；本次**新建**并推送 `main`） |
| 推送 | 普通 push；**未** `--force` |
| 基线 tag | `task-007-multisensor-v1-map-r2-reviewed` → `badcaf8…` 保留；本轮**未**新建冻结 tag |

保护：主仓 task-004 dirty、TASK-005/006 worktree 未切换/未清理；未提交 passwd、客户数据、真实 `.env`、审查大 ZIP。

---

## 2. 业务指纹（与 TASK-009 锁一致）

锁定 commit `665613e` 上 13 文件 SHA 与 `SOURCE_LOCK.json` 一致（`fp13=true`）。全文见该 JSON。

---

## 3. 验证结果（合并后一次收敛）

| 项 | 结果 |
|---|---|
| Python 3.11 全量 pytest（Linux 容器） | **312 passed, 2 skipped**；`reports/task010/evidence/pytest_full.log` |
| Compose `config --quiet` | 通过 |
| Docker Linux 镜像 | `fusion-integration:665613e`；Id `sha256:b8ee13d44f0c2fd2e5b83c688e7ad05d1887e7abd86da093a98e3e0069a3cc44`；**linux/amd64** |
| HTTP 冒烟（环回 **18199**，未动 18099） | `/ready` 指纹匹配；process/flush/replay HTTP 200；海拔样例 `MSL`；静态 app.js SHA 匹配 |
| OpenAPI | `reports/task010/evidence/openapi.json` |
| MQTT 制品级短测 | **NOT_TESTED**（1883 TCP 可达，未在隔离 tenant 跑适配器以免碰现有联调 Broker） |
| 公司 Linux 部署 | **未执行** |

---

## 4. 交付制品

| 制品 | 路径 | SHA-256 | 字节 |
|---|---|---|---|
| Linux 源码包 | `reports/task010/artifacts/TASK-010-attempt-001-linux-source-665613e.tar.gz` | `c24768d2d2728eb7733a25efa7849d83aa4b728d0aab819df7eb56ed38ebf4fe` | 1092966 |
| 验证镜像 gzip | `reports/task010/artifacts/fusion-integration-665613e.tar.gz` | `5d4e812396df973914396f6a76be3aa4ead8b2d648302f01d4e9bf4b625fec7a` | 130314919 |
| 审查交接 ZIP | `review_zip/TASK-010-attempt-001-integration-release-review-bundle.zip` | 见包外 `.sha256.txt` / `.bytes.txt` | — |

源码包 `COMMIT.txt` 指向代码锁定 `665613e3e152620e1c0eb1853638d19fab9d7cbd`。镜像无 registry RepoDigest（本地构建）；`docker load` 使用导出 tar.gz。

---

## 5. 权威入口与 5 分钟冒烟

1. 部署：`01_LINUX_DEPLOY.md` + `deploy/integration/`  
2. 字段/API：`02_API_FIELD_DICTIONARY.md`  
3. 三方流程：`03_REALTIME_INTEGRATION.md`  
4. 前端工作台：服务 `/` 或 `/demo/workbench`（workers=1）  
5. 指纹：本文件 + `SOURCE_LOCK.json`

顺序：`docker load` 或 compose build → 填 `.env.integration`(600) → `config --quiet` → `up fusion-core` → `GET /ready` → 合成 examples → process/flush/replay → 可选 mqtt profile。

**飞行后补齐接口未实现。** `run.end` 仅排空；`replay` 临时重放。分段归档 + 按可信 SN 展示缺口。见 `05_POSTFLIGHT_AND_GAPS.md`。

---

## 6. 待环境确认

公司 Linux 主机/架构/端口、Broker、TLS 终止、tenant/site、前端 topic、网关鉴权、数据目录责任人。

## 7. 未做

未公司生产部署、未强推、未改已审算法指纹、未新增断点补齐算法、未开其他阶段、未建冻结 tag。
