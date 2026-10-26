# TASK-008 attempt-001 审查收尾记录

日期：2026-10-25（Asia/Shanghai）  
项目：TASK-008 MQTT 实时联调与逐点可视化（attempt-001）

**状态：`REVIEW_PASSED_AWAITING_FREEZE`**

裁决依据：`D:\zwyl\02_algo_project\multi_source_data_fusion\review_zip\TASK-008-attempt-001-Independent-Review-PASS-and-Closeout.md`  
该文件 SHA-256：`e2da5717f01d789e2cab6badb0b4838b9969ebbefef7989a0a2cf06fca0bd5cf`（5954 字节）

独立审查结论：**REVIEW_PASSED_AWAITING_FREEZE**。R12-01 已通过独立定向复测；R11-01 三维修复通过结论保留。TASK-008 当前约定工程范围内已知整改项可关闭。

**本地联调候选状态仍为 `CONDITIONAL_READY`。** 本结论不是公司 Broker、现场三源精度或生产容量验收，也不授权 commit、tag、push、冻结、合并或开始下一阶段。

本步仅只读核对并写本收尾记录；未改业务代码/配置，未重跑测试，未重打审查包。

---

## 1. 工作树与基线（只读）

| 项 | 值 |
|---|---|
| 工作树 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task008` |
| HEAD | `badcaf8c00262bb35098ea308ce667b8fb16d138` |
| 裁决要求的本地 main 基线 | `badcaf8c00262bb35098ea308ce667b8fb16d138` |
| 基线 tag | `task-007-multisensor-v1-map-r2-reviewed` → 剥皮对象 `badcaf8c00262bb35098ea308ce667b8fb16d138` |
| 基线匹配 | **一致**（HEAD == badcaf8；tag^{} == badcaf8） |
| 工作区 | dirty（TASK-008 过程未提交变更仍在）；本轮只新增本收尾记录 |

未执行 commit / tag / push / 冻结 / 合并。

---

## 2. 最终候选包身份（只读复核）

| 项 | 裁决值 | 本轮实测 | 匹配 |
|---|---|---|---|
| 文件 | `TASK-008-attempt-001-rework-r12-review-bundle.zip` | 同左（工作树 `review_zip/`；主仓 `review_zip/` 各有一份） | — |
| 绝对路径（工作树） | — | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task008\review_zip\TASK-008-attempt-001-rework-r12-review-bundle.zip` | — |
| 字节 | 812735 | 812735 | **是** |
| SHA-256 | `52435c4102e1fd92d6265a94c7d3d9ba83913a77f2d207268621ad10af68801e` | 同左 | **是** |
| ZIP 项数 | 226、无反斜杠、`source/` 可用 | 226、backslash=0、source/=true | **是** |
| MANIFEST | 225 项、0 bad | 225 行、0 bad | **是** |

前轮三维包 R11（引用，未重验内容）：1618624 字节，SHA-256 `71a5db647a7e423bf619fc0070522ad1c8ac3ada63a10eb185c5d34d1e8c1120`（工作树 `review_zip/` 只读字节/哈希一致）。

未重打 ZIP。

---

## 3. 冻结前源码指纹（工作树只读；与裁决 §3 一致）

| 文件 | SHA-256 | 匹配 |
|---|---|---|
| `src/fusion_mvp/workbench/mqtt_stream_job.py` | `1390adf09ce03ab7cc6ad3cb679aea7fb08d9d28a7bb5d0ec2e4a7f5bc771bf5` | **是** |
| `src/fusion_mvp/multisensor.py` | `f4dfbc6379a5c58d0fd75b73e476e0bc07e6a7587c0cff9346527eb10ebcfa66` | **是** |
| `config/fusion.yaml` | `e25f3560d59935763f21370055fe8cd4f764da2a39b2ad001fe58e70477df518` | **是** |
| `demo/workbench/track3d.js` | `0dbd9ccde5740f218a8e4d6fc2226ffc5f8bc116c11de5740edd986fd0d89c13` | **是** |
| `demo/workbench/app.js` | `e7b2c32dea0de70258a7e9a80b1bf19ba8379b2ea19240a01f8e08017e20071e` | **是** |
| `src/fusion_mvp/api.py` | `12ce8bd706f01de7797f0360cb8883b53c3a90cfd4f2714410f7f44ab1a86f66` | **是** |
| `src/fusion_mvp/integration/mqtt_bridge.py` | `d5daeeb9abc40cb5cf640a8dc7063f64cf912e12be139747664ffe48b7d93a51` | **是** |

R12 ZIP 内 `source/` 对应七文件哈希与上表及工作树一致（全部 OK）。

---

## 4. 独立验证事实（摘自裁决；本轮未重跑）

| 定向项目 | 独立结果（裁决原文摘要） |
|---|---|
| 嵌套 90k rawRef 水平更新 | 缺失必需字段=[]，pointId 保留，通过 |
| 嵌套 90k rawRef 高度更新 | 缺失必需字段=[]，altitudeUpdateId 保留，通过 |
| 多条来源 evidence | 字段/关系保留，8776B 在预算内，通过 |
| 非 ASCII 嵌套大正文 | 来源字段及高度更新 ID 保留，8187B 在预算内，通过 |
| 当前 tracks 快照回归 | XYZ/时刻/状态保留，7954B，通过 |
| 原单条大正文反例 | 8074B ≤ 262144B，通过 |
| 真正触发兜底的多小字符串 rawRef | 雷达 aircraftId=null 等必需字段与更新 ID 保留，通过 |
| 必需字段本身超过预算 | 有界返回 + transportError，nextSeq=0、incomplete，不假完成，通过 |
| 同两页结果重复归并 | pointId / altitudeUpdateId 去重通过 |

未重跑浏览器、MQTT 联合、全量 pytest 或长稳（符合 R12 预算与本收尾指令）。

### 证据引用（不重验）

- **R11**：三维 draw 复测与正式 UI 可见连续线；定向 pytest 35 项通过记录；包 SHA 见上。
- **R10**：联合短测 0 late_after_frontier、真实 drained、逐 ID 账目等提交者记录继续引用。
- **R9**：312 passed / 2 skipped 为 R9 历史版本，不包装成当前 R12 全量结果。

---

## 5. 服务只读快照（可选）

| 端口 | 本轮只读 | 动作 |
|---|---|---|
| http://127.0.0.1:18099/ready | HTTP 200，`status=ready`，`algorithmVersion=mvp-0.1.0+task008-3d` | 未启动新推流 / 测试发送器 |
| 18089 | 本轮无法连接（保留端口约定，未改动） | 未启动新服务 |
| Broker | 保留供用户；本轮未做联调推流 | — |

---

## 6. CONDITIONAL_READY 边界（裁决 §4，未放宽）

- HTTP 实时与 MQTT 双通道共用既有核心；不以多进程 worker 分裂会话。
- `multisensor-3d-v1`：水平滤波 + 独立垂直滤波；altitude→MSL 米为 USER_ASSUMED，非已做物理基准转换/校准。
- RID/频谱 id 按公司 SN 映射；雷达 id 为设备局部目标号。
- 原始散点与融合历史分开；未知/过期高度不填 0、不跨断点硬连。
- 事件缓存前缀淘汰后重开仅恢复已保留尾部并明示 historyGap；大附加正文省略为受限，非可恢复原文引用。
- 公司 Broker/TLS/账号：**NOT_TESTED**；真实三源同机精度：**BLOCKED**；长稳与生产容量：**DEFERRED**；鸟类识别与约 2GB SQL 全量：**NOT_TESTED**。

---

## 7. 本轮未做动作

- 未修改业务代码 / 配置 / 三维
- 未重跑 pytest / 浏览器 / MQTT 联合 / 长稳
- 未重打审查包
- 未 commit / tag / push / 冻结 / 合并 / 生产部署 / 开始下一阶段

后续冻结或本地整合须另按用户指令执行。
