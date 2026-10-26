# TASK-009 attempt-001 审查收尾记录

日期：2026-10-26（Asia/Shanghai）  
项目：TASK-009 三维工作台交互专项（attempt-001，含 R1/R2）

**状态：`REVIEW_PASSED_AWAITING_FREEZE`**

裁决依据：`D:\zwyl\02_algo_project\multi_source_data_fusion\review_zip\TASK-009-attempt-001-Independent-Review-PASS-and-Closeout.md`  
该文件 SHA-256：`31fe1f7e89bd124ccde20fcd789854abdad9e375a28af1ec85d94d04b2fa1e2e`（7834 字节）

独立审查结论：**REVIEW_PASSED_AWAITING_FREEZE**。R2-01、R2-02 可关闭；R1 已通过修复保留。不再开启新的 UI 整改轮次。

**本地联调候选状态仍为 `CONDITIONAL_READY`。** 本结论不是公司 Broker、现场三源精度或生产容量验收，也不授权 commit、tag、push、冻结、合并或开始下一阶段。

本步仅只读核对并写本收尾记录；未改业务代码/配置，未重跑测试，未重打审查包。

---

## 1. 工作树与基线（只读）

| 项 | 值 |
|---|---|
| 工作树 | `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task008` |
| HEAD | `badcaf8c00262bb35098ea308ce667b8fb16d138` |
| 裁决要求的基线 | `badcaf8c00262bb35098ea308ce667b8fb16d138` |
| 基线 tag | `task-007-multisensor-v1-map-r2-reviewed` → 剥皮对象 `badcaf8c00262bb35098ea308ce667b8fb16d138` |
| 基线匹配 | **一致**（HEAD == badcaf8；tag^{} == badcaf8） |
| 工作区 | dirty（TASK-008/009 过程未提交变更仍在）；本轮只新增本收尾记录 |

未执行 commit / tag / push / 冻结 / 合并。未 reset、未清理 dirty、未重新整合主分支。

---

## 2. 最终候选包身份（只读复核）

| 项 | 裁决值 | 本轮实测 | 匹配 |
|---|---|---|---|
| 文件 | `TASK-009-attempt-001-rework-r2-review-bundle.zip` | 同左 | — |
| 绝对路径 | — | `D:\zwyl\02_algo_project\multi_source_data_fusion\review_zip\TASK-009-attempt-001-rework-r2-review-bundle.zip` | — |
| 字节 | 6457621 | 6457621 | **是** |
| SHA-256 | `82d5536a0e9104def9ba2194c1bf8d5adebc31c93a388ab5041b433aa4bc80c7` | 同左 | **是** |
| ZIP 项数 | 285；反斜杠 0 | 285；backslash=0 | **是** |
| MANIFEST | 283 项、0 bad | 283 行、0 bad | **是** |
| 包外解压记录 | `TASK-009-attempt-001-rework-r2-unpack_verify.json` 指向上述最终包 | zipSha/bytes 与最终包一致；pass=true | **是** |

未重打 ZIP。

---

## 3. 源码指纹（工作树 + 最终包内；与裁决 §3 一致）

| 文件 | SHA-256 | 工作树 | 包内 |
|---|---|---|---|
| `demo/workbench/app.js` | `67c11ee3f5a8d9d345cab111504f34dcdeb2ba9b5465d809de560e29fb98733f` | **是** | **是** |
| `demo/workbench/track3d.js` | `1f933bf2e0050319e9d88a3d87cc7739a55c2d88ee89da18fcb928c331845bc6` | **是** | **是** |
| `demo/workbench/ux_query.js` | `2876d466401b54e2caee1b96aae34b63dc0eb933d44b176cb30cd8afe10eb99c` | **是** | **是** |
| `demo/workbench/ux_panel.js` | `f2713a7553b6e5ecb216839e1623e4f75bddb071030106cc8cb94f175ec8e632` | **是** | **是** |
| `demo/workbench/ux_helpers.js` | `7702bd07e1dc739b9ff477b98e495d6888825c6a822475025f591aa8c5020eb8` | **是** | **是** |
| `demo/workbench/canvas.js` | `15e8268e1743873d672fff35c2fd3c48d46326023d49f5d45c5cde73d6365cb6` | **是** | **是** |
| `demo/workbench/styles.css` | `9db094ded8ed8ad6a9191f76459e0c57809da3a2e306e9412fce23a5d9188e18` | **是** | **是** |
| `demo/workbench/index.html` | `26717ad5a67972c670ff27335ec1d752481c4021d42d9660399f1d3c80d5b483` | **是** | **是** |
| `src/fusion_mvp/multisensor.py` | `f4dfbc6379a5c58d0fd75b73e476e0bc07e6a7587c0cff9346527eb10ebcfa66` | **是** | **是** |
| `config/fusion.yaml` | `e25f3560d59935763f21370055fe8cd4f764da2a39b2ad001fe58e70477df518` | **是** | **是** |
| `src/fusion_mvp/api.py` | `12ce8bd706f01de7797f0360cb8883b53c3a90cfd4f2714410f7f44ab1a86f66` | **是** | **是** |
| `src/fusion_mvp/workbench/mqtt_stream_job.py` | `1390adf09ce03ab7cc6ad3cb679aea7fb08d9d28a7bb5d0ec2e4a7f5bc771bf5` | **是** | **是** |
| `src/fusion_mvp/integration/mqtt_bridge.py` | `d5daeeb9abc40cb5cf640a8dc7063f64cf912e12be139747664ffe48b7d93a51` | **是** | **是** |

---

## 4. TASK-008 收尾记录（禁止改写；本轮只读确认未变）

| 项 | 裁决要求 | 本轮实测 |
|---|---|---|
| 路径（主仓） | `TASK-008-review-closeout-record.md` | `D:\zwyl\02_algo_project\multi_source_data_fusion\TASK-008-review-closeout-record.md` |
| 字节 | 6512 | 6512 |
| SHA-256 | `1fe1eda82732ebdef6d7c7c176961045a014e39725baacf7668967cf6e8be0ab` | 同左 |
| 工作树副本 | — | 同哈希/同字节，未改写 |

TASK-008 状态保持 `REVIEW_PASSED_AWAITING_FREEZE`。

---

## 5. 证据来源差异（裁决 §2.3，原样保留；非新整改项）

1. **包内较早解压记录 ≠ 最终包依据**  
   包内 `reports/task009/r2/evidence/unpack_verify_summary.json` 指向较早包：**6455051** 字节 / SHA-256 `057b76b29e50e9bee3ad356d2b52b658f9e438e83af606676b97e3cc7c88a2bb`。  
   **不采用**它作为最终包解压通过依据。本次依据为包外 `TASK-009-attempt-001-rework-r2-unpack_verify.json`（指向 6457621 / `82d5536a…`）以及审查方对最终包的独立清单/定向复测（本收尾未重跑定向探针，仅只读身份核对）。

2. **正式 UI 脚本哈希与结果内 probeSha256 不一致**  
   - 正式结果 `probeSha256`=`cc58f8a6fb3146f0e491e984cf12953fed25621f2f6c098587c2033791f04e45`  
   - 当前包内 `formal_ui_r2.mjs` SHA-256=`6919ca494cefcc757d210700d9c0b1b61fffc4454ccd449300bd83ee3004ea16`  
   二者不相等（裁决已说明 LF 归一化后仍不等）。**不宣称**“当前脚本逐字节就是当时执行版本”。业务前端指纹相符、客户端增量账目与截图仍作功能佐证；旧日志哈希不篡改、不回写。

---

## 6. 独立验证事实（摘自裁决；本轮未重跑）

| 项目 | 独立结果（裁决原文摘要） |
|---|---|
| `r2_positive_raw_cursor.mjs` | exit 0 / pass=true |
| `r1_positive_regression.mjs` | exit 0 / pass=true |
| 原始层游标反例 | frame0 仅 O0；未来 O1 不出现；空 datum / HAE_AS_MSL 不可用 |
| 后端五文件 + TASK-008 收尾 | 相对上一候选逐字节不变（本轮指纹见 §3/§4） |
| 正式 UI 两视口 | 1920×1080@DPR1、1280×800@DPR2；PNG 尺度一致；`ms-47d72df5-0008` 121 点 / 120 边 / maxEdge≈290 |
| MQTT 短测 | UI 点击 `#btnMqttStreamStart`；runId=`20261025T224057-f09e05da`；afterSeq 18→592；点 1→120；过滤/固定点保持；短链路非长稳 |

审查方未声称访问用户 18099 重跑浏览器/真实 MQTT；未重跑全量 pytest/长稳/算法基准。本收尾亦未重跑。

---

## 7. 服务只读快照（可选）

| 端口 | 本轮只读 | 动作 |
|---|---|---|
| http://127.0.0.1:18099/ready | HTTP 可用，`status=ready`，`algorithmVersion=mvp-0.1.0+task008-3d` | 未启动新推流 / 测试发送器 |
| 已服务静态 app/track3d/ux_query/index | SHA 与 §3 一致 | 只读 |
| 18089 | 不可连（保留端口约定，未改动） | 未启动新服务 |
| Broker | 保留供用户；本轮未做联调推流 | — |

---

## 8. CONDITIONAL_READY 边界（裁决 §5，未放宽）

- 水平 KF + 独立垂直 KF；DB altitude→MSL 米为 USER_ASSUMED，非物理高程校准。
- RID/频谱 id 按公司 SN 映射；雷达 id 是设备局部号，不能冒充可信全局 SN。
- 页面展现算法真实关联/分段；不跨断点强连，不把同 SN 的多个 fusionId 自动宣称为同次飞行已补齐。
- 缓存淘汰/historyGap 与大附加正文省略仍有明确限制；不宣称历史全量可恢复。
- 公司 Broker/TLS/账号 **NOT_TESTED**；真实三源同机精度 **BLOCKED**；生产容量/长稳 **DEFERRED**；鸟类识别及约 2GB SQL 全量 **NOT_TESTED**。

---

## 9. 本轮未做动作

- 未修改业务代码 / 配置 / API / MQTT 契约
- 未重跑 pytest / 浏览器正式操作 / MQTT 短测 / 长稳
- 未重打审查包
- 未改写 TASK-008 收尾记录
- 未 commit / tag / push / 冻结 / 合并 / 生产部署 / 开始下一阶段

后续冻结或本地整合须另按用户指令执行。
