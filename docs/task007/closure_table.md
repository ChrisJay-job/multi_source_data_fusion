# TASK-007 attempt-001 收口

状态：REVIEW_READY。未 commit、未打 tag、未 push、未冻结、未合并。

| 项 | 状态 | 证据 |
|---|---|---|
| A01 legacy 不回退 | VERIFIED_PASS | `tests/test_task007_multisensor.py`，全量 233 passed |
| A02 六设备冷启动一条航迹 | VERIFIED_PASS | 同上，以及 `reports/task007/task007_http_smoke_evidence.json` |
| A03 三目标不串轨 | VERIFIED_PASS | 同上 |
| A04 交叉身份与位置 | VERIFIED_PASS | 评估真值只在测试中使用，未送入算法 |
| A05 无本地航迹号 | VERIFIED_PASS | `offline_missing_local_ids.json` |
| A06 孤立点不确认，unknown 不当成无人机 | VERIFIED_PASS | `offline_clutter.json` |
| A07 重发与同帧约束 | VERIFIED_PASS | 测试 |
| A08 重排、未来时间、空 tick | VERIFIED_PASS | 测试 |
| A09 短间隙、换号、补 SN | VERIFIED_PASS | 测试 |
| A10 幂等、409、413、422、回滚、会话隔离 | VERIFIED_PASS | 测试与 HTTP 冒烟 |
| A11 多源进入位置估计 | VERIFIED_PASS | 测试 |
| A12 实时与离线因果输入一致 | VERIFIED_PASS | 测试 |
| A13 真实 JSON 与浏览器 | VERIFIED_PASS | 28/26/2；`reports/task007/browser/` |
| A14 启动、ready、样例、回放、reset | VERIFIED_PASS | `reports/task007/runtime_consistency.json` |
| A15 合成容量记录 | VERIFIED_PASS | `reports/task007/capacity_smoke.json`。不是客户容量承诺 |
| 真实多设备同机精度 | BLOCKED | 无同机真值 |
| 现场鸟/无人机识别 | NOT_TESTED | |
| 约 2GB SQL | NOT_TESTED | |
| JSON/XLS 导入 | 保持 Round5 | `importer.py` 哈希未变 |
| R1–R8 | VERIFIED_PASS | `docs/task007/rework_r1.md`。全量 239 passed |

legacy 融合核心 `engine.py` 哈希仍是 Round5 的 `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b`。新剖面在 `src/fusion_mvp/multisensor.py`。
