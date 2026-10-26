# TASK-010 attempt-001 发布与交接记录（R1 修订）

日期：2026-10-26（Asia/Shanghai）  
**状态：`RELEASE_HANDOFF_R1_AWAITING_REVIEW`**（代码已整合、镜像已构建、公司未部署）

权威字段命名（避免 tip 自引用循环）：

| 字段 | 含义 | 本轮值 |
|---|---|---|
| `runtimeCodeCommit` | 运行代码/镜像锁定点 | `665613e3e152620e1c0eb1853638d19fab9d7cbd` |
| `documentationCommit` | 文档修正提交（推送后写入包外核对文件） | 见包外/审查包 `REMOTE_HEAD.txt`；**勿**在正文内嵌「必须等于本文件自身 SHA」 |
| `remoteMainAtVerification` | 核对时刻的 `origin/main` | 见同次 `REMOTE_HEAD.txt`（只读 `git ls-remote`） |

**部署镜像标签固定为 `fusion-integration:665613e`（对应 runtimeCodeCommit）。** 更晚的文档 tip **没有**对应新镜像；不要寻找 `523ac31`/`14e8f85` 等文档 tip 的镜像标签。

历史 tip 备注：曾短暂写过「最终远程=14e8f85…」——那是文档迭代中的中间 tip，**不是**运行代码锁。以本表字段 + 包外远程核对为准。

---

## 1. Git（脱敏）

| 项 | 值 |
|---|---|
| 整合 worktree | `multi_source_data_fusion_wt_task010_integ` |
| 远程 | `github.com/ChrisJay-job/multi_source_data_fusion`（本轮首次创建并推送 `main`） |
| 推送 | 普通 push；未 force |
| 基线 tag | `task-007-multisensor-v1-map-r2-reviewed` → `badcaf8…` 保留 |
| `runtimeCodeCommit` 为 main 祖先 | 是（`git merge-base --is-ancestor`） |
| 锁之后仅文档变更 | `docs/integration/task010/RELEASE_RECORD.md`（及本 R1 发布说明类文件） |

运行指纹证据：`reports/task010/r1/evidence/runtime_fingerprint_check.json`（工作树字节=SOURCE_LOCK；Git blob 在 665613e↔HEAD 对 13 锁文件 + 27 个 `src/**/*.py` **无变更**）。Windows 检出 CRLF 时工作树 SHA 与 Git blob SHA 可能不同，属换行符，非算法改动。

---

## 2. 镜像（复用，不重建）

| 项 | 值 |
|---|---|
| 标签 | `fusion-integration:665613e` |
| Image ID | `sha256:b8ee13d44f0c2fd2e5b83c688e7ad05d1887e7abd86da093a98e3e0069a3cc44` |
| 导出 gzip SHA-256 | `5d4e812396df973914396f6a76be3aa4ead8b2d648302f01d4e9bf4b625fec7a` |
| 字节 | 130314919 |
| 架构 | linux/amd64 |

R1 **未**重建、**未**重新导出镜像。

---

## 3. 已执行验证（见 RELEASE_VERIFICATION；非改写 VALIDATION.json）

| 项 | 结果 | 对应代码锁 |
|---|---|---|
| pytest Linux 3.11 | 312 passed / 2 skipped | 665613e |
| Docker 构建 + 18199 HTTP 冒烟 | ready/process/flush/replay；静态 app.js=SOURCE_LOCK | 665613e |
| MQTT 制品短测 | **NOT_TESTED** | — |
| 公司 Linux | **未部署** | — |
| 18199 R1 只读复取 | **STOPPED_OR_UNAVAILABLE**（沿用原冒烟记录，不新起服务） | — |

`VALIDATION.json` 保留为**输入材料准备验证/历史参考**（dockerBuild=NOT_TESTED_IN_THIS_WORKSPACE 等），勿当作本发布执行结果。

---

## 4. 交付制品

| 制品 | 说明 |
|---|---|
| 清洁源码 tar（R1） | `reports/task010/artifacts/TASK-010-attempt-001-linux-source-665613e-r1.tar.gz`（运行代码锁 665613e + 更新交接文档；**不含** `.env.integration` / 本机 data）。**SHA/字节见包外** `TASK-010-attempt-001-linux-source-665613e-r1.sha256.txt` / `.bytes.txt` 与 `reports/task010/r1/evidence/clean_source_tar_meta.json`（避免把 tar 哈希写进会被打进 tar 的正文造成循环） |
| 原源码 tar | 保留不覆盖：`…-665613e.tar.gz` / `c24768d2…` / 1092966（含本机测试 `.env.integration`，勿当公司配置） |
| 镜像 gzip | 复用上表 hash（不重建） |
| 审查包 R1 | `review_zip/TASK-010-attempt-001-release-handoff-r1-review-bundle.zip`（包外 SHA/字节） |

---

## 5. 权威入口与两条部署路径

1. 文档入口：本目录 `00_README.md` / `01_LINUX_DEPLOY.md`  
2. 字段：`02_API_FIELD_DICTIONARY.md`  
3. 流程：`03_REALTIME_INTEGRATION.md`  
4. 工作台：服务 `/` 或 `/demo/workbench`（workers=1）

**路径 A（推荐联调）：** 核对镜像 gzip SHA → `docker load` → `.env` 中 `FUSION_IMAGE=fusion-integration:665613e` → **不要**再 `compose build` 覆盖。  
**路径 B：** 清洁源码 + `compose build`（结果应自证；本轮交付以已验 665613e 镜像为准）。

`cp deploy/integration/env.integration.example deploy/integration/.env.integration` 后编辑；chmod 600。公司参数待填写。

飞行后断点补齐接口**未实现**。见 `05_POSTFLIGHT_AND_GAPS.md`。

---

## 6. 真实样本（Git 远程只读结论）

| 路径 | 远程 main 树 | 首次进入 | 说明 |
|---|---|---|---|
| `samples/task007/5_rid_pp5_leida1_simp.csv` | **包含**（跟踪） | `badcaf8…`（2026-10-24，TASK-006/007 基线整合，**早于**本轮 TASK-010） | 历史真实导出样本；本轮**未新增** |
| `samples/task007/5_leida_rid_pp.csv` | **包含** | 同上 | 同上 |

清洁 Linux 源码交付包：**排除**上述样本。  
仓库可见性（GitHub API 无授权会话）：**NOT_VERIFIED**（HTTP 403）。未自动改权限/filter-repo/强推。

文案口径：勿再说笼统「未提交客户数据」；精确为「本轮未新增真实样本；远程 main 已含早于本轮的历史 samples/task007 两文件；源码 tar 排除」。

---

## 7. 未做

未改算法、未重跑全量/MQTT/长稳、未重建镜像、未公司生产部署、未开其他阶段、未 force。
