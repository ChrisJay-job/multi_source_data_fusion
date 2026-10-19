# TASK-003 Round1 根因与修复

日期：2026-10-19。分支：`task-003-workbench-usability-and-association`。状态：**REVIEW_READY**。

## R1-01 / R1-02 雷达门控与一对一

**根因：** `_radar_base_tid` 剥离 `-vN` 做家族推断；handoff 仅距离门控后直接 `_apply_update`，绕过 LSA/创新；同批多观测可连续写同一 fusionId。

**修复：**

- 删除 ID 拼写/后缀捷径；`sourceTrackId` 为不透明字符串。
- 重门控与 LSA 使用同一 dist+innov 门控；设备微批一对一（`occupied_fids` + LSA）。
- 新雷达 ID 经门控后可替换同 detector 其他绑定键（物理接续），不读仿真 label/truth。
- 反例：`tests/test_task003_review.py`；opaque 映射 `7319`/`2048`。

## R1-03 真实提交历史

**根因：** 历史取自展示快照 `positionMode` 坐标（含预测 coast）。

**修复：** 主位置 KF 更新时追加 `Track.committed_updates`；快照字段 `committedHistory`；canvas 只画提交点，隐藏预测时仍有实线历史。

## R1-04 结果面板契约

**根因：** 读 `evaluation.verdict`；异常未接 `false_merges`；活跃源 fallback 到过期 `sourceTracks`。

**修复：** `evalVerdict`←`entity_check.status`；异常接入 false_merges/attribution/…；`activeSourcesOnTrack` 以 `tr.sources` 为准。

## 验证

- `pytest -q`：**87 passed**（Docker Python 3.11）
- Node 桩探针：`PROBE_PASS`（7 条融合历史线；FAIL+误关联；过期 radar 非活跃）

边界：真实三源 **BLOCKED**；现场精度 / 2GB SQL **NOT_TESTED**。
