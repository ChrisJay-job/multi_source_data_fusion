# TASK-007 attempt-001 审查收尾记录

日期：2026-10-24（Asia/Shanghai）  
项目：无 SN 多设备融合新剖面、实时/离线接口、合成场景回归与联调交付

**状态：`REVIEW_PASSED_AWAITING_FREEZE`**

裁决依据：`D:\zwyl\02_algo_project\multi_source_data_fusion\review_zip\TASK-007-attempt-001-R6-Independent-Review-PASS-and-Closeout.md`  
该文件 SHA-256：`7494817797c63330f2cbe8d0ae888789457e4d18b2b8137a9107c19d1390c8c0`（7110 字节）

独立审查结论：REVIEW_PASS。建议治理状态：REVIEW_PASSED_AWAITING_FREEZE。

通过范围：当前 TASK-007 无 SN 多设备融合新剖面、实时/离线接口、合成场景回归与联调交付的**工程审查**。R6-01 已关闭；前轮已知整改项未复现回归。本结论不升级为客户现场精度验收，不授权 commit、tag、push、冻结、合并或下一阶段。

## 1. 分支与工作区（只读）

| 项 | 值 |
|---|---|
| 工作树 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task006` |
| 分支 | `task-006-real-excel-import-and-cooccurrence` |
| HEAD | `6abc39d400c4cde60e0c56147e0442212f032b65` |
| 工作区 | 未提交。相对该 HEAD 仍有 TASK-006/TASK-007 过程中的已修改与未跟踪文件。本轮只新增本收尾记录，未改业务源码、配置或测试 |

收尾记录写入前后，git 仍为上述 dirty baseline；未执行 commit/tag/push/冻结/合并。

## 2. 通过对象：固定为 R6 两个包

| 包 | 绝对路径（工作树根，主仓根各有一份） | 字节数 | SHA-256 |
|---|---|---:|---|
| 审查包 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task006\TASK-007-attempt-001-rework-r6-review-bundle.zip` | 7723412 | `03f971b5d71069823836da16966ec847f460e921b366eb13527402f02f912588` |
| 联调包 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task006\TASK-007-integration-delivery-r6.zip` | 284370 | `3519c74a8e5910b68de68b8bbacabfdffdbb811206461c2f58eef0a21f7db476` |

本轮收尾前只读复核：两包字节数与 SHA-256 与裁决文件一致；未重打 ZIP。

### 源码指纹（工作树只读复核，与裁决文件一致）

| 文件 | SHA-256 |
|---|---|
| `src/fusion_mvp/multisensor.py` | `f5d919551c5ebc921d617a314d8a6be86f818ffe1c6a5a95400097ffa662d6e2` |
| `config/fusion.yaml` | `ab2d9b4f7f7ab893fad8a07e7e8ba4da30b4b1f70a9b43153202a6f74cca7342` |
| `src/fusion_mvp/workbench/importer.py` | `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c` |
| `src/fusion_mvp/engine.py` | `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b` |
| `src/fusion_mvp/kalman.py` | `a0e52d4b44c5fbf4b8e00a5627cf0369542e7065c7618a6cd17fa46b98b5a8ae` |

后三项仍与已通过的 Round5 基线一致。legacy 仍默认，`multisensor-v1` 显式启用。

## 3. 独立验证结果（摘自裁决文件；本轮未重跑）

| 检查 | 独立结果 |
|---|---|
| R6 审查包干净解压全量 pytest | **277 passed、2 skipped、1 warning，102.50 秒** |
| 六轮 34 个正式独立回归 | **34 passed、1 warning，2.78 秒** |
| R6 追加组合核查 | **72/72 通过** |
| 两包清单与公共文件一致性 | 通过 |
| 联调包 TestClient 冒烟 | ready、replay、空 tick、reset 均为 HTTP 200 |
| 默认 4097 行加 flush | 4097 已处理、4097 有效、0 拒绝、0 未处理、4097 轨迹点、保留最终快照 |

两项跳过因完整 XLS 未附带，不计为通过。独立环境：Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0、Pydantic 2.14.1。

提交包另有 Cursor 侧 Python 3.11.16、锁定依赖环境下的全新解压日志：277 passed、2 skipped、1 warning，52.46 秒（`reports/task007/r6/pytest_fresh_unzip_r6.log`）。两种结果一致；本轮未重跑。

### R6-01 关闭依据（摘要）

pending slot 的未来观测锚点不再当作已提交 KF 状态时间；通过 `_slot_predicted_xy` 按速度/航向投影到待比较观测时刻后再做距离门。真实 KF 负 dt 保护、身份/航向约束、强制列一对一、重叠扫描等待仍由原回归覆盖。

### 分离真值（合成样例，不外推现场精度）

| 合成场景 | 目标观测覆盖 | 最后确认目标数 | 混用实体 ID |
|---|---:|---:|---|
| single_target | 72/72 | 1 | 无 |
| three_targets | 360/360 | 3 | 无 |
| missing_local_ids | 360/360 | 3 | 无 |
| clutter 中真实目标 | 360/360 | 3 | 无 |
| crossing | 492/492 | 2 | 无 |

crossing RMSE 0.98385 米（最大约 2.412 米），仅代表该合成样例。

## 4. 交付证据与使用口径

| 项 | 路径 |
|---|---|
| 权威交付入口 | `docs/task007/00_交付入口.md` |
| 启动说明 | `docs/task007/RUN.md` |
| 本轮实现说明 | `docs/task007/rework_r6.md` |
| 本轮原始证据 | `reports/task007/r6/` |
| 34 独立回归新鲜解压日志 | `reports/task007/r6/pytest_34_independent_fresh.log` |
| HTTP/ready/inspect | `reports/task007/r6/http/` |
| 镜像说明 | `reports/task007/r6/image.json`（索引 `sha256:7a33322ae9cb98c8c40f1686f1e5112aefde9babc73c71c3996ebbd667c56e83`，端口 18101，无源码挂载） |

可将 R6 联调包作为当前受控前后端接口联调版本，按权威入口对接。状态在单进程内存；重启/reset/过期后会话消失；离线 replay 不恢复实时 `MS_STORE`。

### 独立环境 vs Cursor 记录（须区分）

| 来源 | 内容 |
|---|---|
| 独立审查 | Python 3.12 干净解压全量与 34 回归、72 组合、联调包 TestClient；未连接 Windows 本机端口、未在此重建 Docker、未重跑浏览器 |
| Cursor 提交记录 | Python 3.11 全新解压日志、18101 Docker 部署原始 HTTP、两视口 28/26/2 浏览器证据；验证项目已拆除；开发容器仍在 `127.0.0.1:18089` |

## 5. 仍 BLOCKED / NOT_TESTED / 限制

- 真实三源同机精度：**BLOCKED**
- 鸟类识别、约 2GB SQL、现场字段精度：**NOT_TESTED**
- Asia/Shanghai：待设备确认
- 默认噪声未标定；单进程内存，无 Redis；不将未实现的马氏距离关联、RTS 或鸟类识别写成已具备能力
- 本文件不启动现场验收或下一阶段

## 6. 本轮未执行

- 未修改业务源码、配置或测试
- 未重新跑测试，未重新构建/重启服务，未重打 R6 审查包/联调包
- 未覆盖历史证据
- 未 commit、未 tag、未 push
- 未冻结、未合并
- 未开始下一阶段

后续本地冻结须另行明确授权。本记录与裁决文件本身都不构成该授权。
