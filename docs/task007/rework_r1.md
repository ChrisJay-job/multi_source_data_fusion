# TASK-007 REWORK R1

状态：REVIEW_READY。未 commit、未打 tag、未 push、未冻结、未合并。

附件 `REVIEW_AND_REWORK_R1.md` 不在工作区。下面八项按当条指令的顺序关闭。原有验收断言没有删除，也没有放宽。

| 项 | 修复 | 证据 |
|---|---|---|
| R1 多目标误合并 | 已确认航迹不再按距离合并。同一探测器上仍活跃的另一个本地号不能占到同一条全局航迹 | `test_r1_tracked_targets_do_not_merge_when_they_approach` 同向接近到约 20 米仍是 2 条航迹 |
| R2 主来源失效切换 | 有 SN 时，主来源超过 `primary_fresh_s` 未更新则改由下一级来源更新位置，`fusionId` 不变 | `test_r2_stale_primary_source_hands_off_without_new_id` |
| R3 lost 恢复 | `lost` / `coasting` 收到可关联观测后回到 `tracked` 并发 `track_reacquired`。超过终止时间的航迹从内存删除，不复活 | `test_r3_lost_track_is_reacquired` |
| R4 轨迹丢点 | 本批 `trajectoryUpdates` 不再按 500 条截断。历史存储上限只裁剪已返回过的 `committedHistory`，并打 `history_capped` | `test_r4_batch_trajectory_is_not_truncated`：30 个点全部返回，历史保留 5 |
| R5 内存边界 | 观测哈希、幂等缓存、重排缓冲和会话都有上限。被挤出的 batch 重试返回 `idempotency_expired`。终止航迹移出内存。过期会话在下次访问时删除 | `test_r5_memory_bounds_drop_old_state_and_report_it` |
| R6 离线语义 | 离线按 `measurementTime` 排序后回放，抽样时保留最后一帧。摘要写明最后一帧目标数不是总目标数 | `test_r6_offline_sorts_and_keeps_the_last_snapshot` |
| R7 验收测试 | 新增 R1–R6 测试。原 A01–A15 断言保留。全量 239 passed，1 warning，52.94 秒。HTTP 冒烟通过 | `reports/task007/pytest_full_r1.log`，`task007_http_smoke_evidence.json` |
| R8 部署交付 | 联调包在 `D:\zwyl\task007_r1_fresh` 解压后构建。`127.0.0.1:18097/ready` 返回 `multisensor-v1`。包内冒烟通过。验证容器已删除，`fusion-task006-api` 仍在 18089 | `reports/task007/fresh_unzip_ready.json`，`fresh_unzip_verify.json`，`image.json` |

`importer.py` 与 legacy `engine.py` 仍是 Round5 哈希。真实同机精度仍是 BLOCKED。鸟类/无人机识别 NOT_TESTED。约 2GB SQL NOT_TESTED。Asia/Shanghai 未确认。

全新目录镜像 `sha256:8c763d809ca4b92c1408af9b9c43612230d58c2eec6c6ed02202bdb6c080f81b`，大小 205197367 字节。镜像不打进 zip。包哈希写在包外。
