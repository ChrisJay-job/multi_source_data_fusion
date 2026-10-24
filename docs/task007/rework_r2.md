# TASK-007 REWORK R2

状态：REVIEW_READY。未 commit、未打 tag、未 push、未冻结、未合并。

## 读取的正式文件

附件包：

`D:\zwyl\02_algo_project\multi_source_data_fusion\review_zip\TASK-007-attempt-001-Independent-Review-Rework-R2.zip`

SHA-256 `3b4852939f16bc320d8591df7bc670b1b9342c07c1963ef65da4e0829e2b23e5`，49402 字节。

解压到 `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task006\review_zip\TASK-007-rework-r2\`。与 `MANIFEST.sha256` 一致的文件：

| SHA-256 | 路径 |
|---|---|
| f2b339b2209a254a91329259b6d4e30054887d35d6714d5e86592449da18ffb3 | REVIEW_AND_REWORK_R2.md |
| d32203f86317af4c32594398da5f23472805ddd247c7391915bf97f963118a41 | reference/REVIEW_AND_REWORK_R1.md |
| ec0dc181650d0218ae8d3378c0da1e3dbb0b40b5e92e214d95394b64e550d288 | test_task007_independent_review.py |
| d413006f227a6d64b12c5b3abbc85984fb84dc69239b9fbdf5f01decd60e7863 | test_task007_r2_review.py |
| 372f60fecf1c19152565ed1b7aab3ff8adf3eb087c2c82d7f70155afc6200afb | evaluate_task007_fixtures.py |

两份回归已原样放进 `tests/`。`importer.py` 仍是 `2421fc472d8458cc3355545fe966d501a57257d693bc025ef8de53b60eb0601c`。legacy `engine.py` 仍是 `f98a036d74dd6acb358328e5159cf5c5ed843b7c6050945ce9ac8d2c4d20275b`。

## 逐项

| 项 | 结果 | 证据 |
|---|---|---|
| R2-01 扫描竞争 | 生成编号不再互相排斥。完整 scan 整组分配。同 SN 换号保持 fusionId。缺编号样例回到 3 条确认目标，360/360，每实体 1 个 fusionId | 本轮前三个回归；`reports/task007/fixture_truth_r2.json` 的 missing_local_ids。对照审查记录的修复前 15 条确认、313/360 |
| R2-02 KF 时钟 | 只绑定的 secondary 不改 `state_time`，也不把 lost 续成 tracked | `test_kf_state_clock_agrees_with_state_after_secondary_binding` |
| R2-03 幂等与内部边界 | 窗口内淘汰的 batch 不再被当成新请求。失败回滚恢复 cache。时间集合、consumed、binding 有上限。超过 `max_idempotency_ids` 返回 `idempotency_capacity` | 本轮两个缓存回归，以及 `test_r2_internal_counters_stay_bounded`、`test_r2_idempotency_capacity_rejects_without_forgetting` |
| R2-04 离线 | 按绝对时刻排序。`maxSnapshots=1` 只返回末帧。时间保留微秒 | 上轮三个 R6 回归 |
| R2-05 验收与打包 | A04 用分离真值位置。A05 检查三目标归属和覆盖。A06 用真值区分真实目标与杂波。samples 打进审查包。容量记录是 2 秒、100 条/秒、10 个延迟样本 | 工作树全量 256 passed，1 warning，49.23 秒。`reports/task007/pytest_full_r2.log`，`capacity_smoke.json` |
| R2-06 交付说明 | replay 不恢复实时会话。Linux 脚本以 `/ready` 为准。权威入口是 `docs/task007/00_交付入口.md` | `docs/task007/RUN.md`，`scripts/task007_*.sh` |

上轮已通过的两目标不合并、主源失效切换、lost 恢复、600 点可恢复、cache 上限仍在 15 个独立回归里，本轮一起通过。

真值覆盖：single 72/72；three 360/360；missing 360/360；clutter 真实目标 360/360 且最后确认 3 条；crossing 492/492，真值 RMSE 0.984 米。没有实体混在同一个 fusionId 上。

真实 JSON 仍是扫描 28、有效 26、拒绝 2，记录索引 10 和 17，原因 `position_placeholder_0_0`。完整 Excel 与约 2GB SQL 不在包内。真实同机精度 BLOCKED。鸟类识别 NOT_TESTED。Asia/Shanghai 未确认。

没有 `scanId` 时，同一探测器的 50 毫秒桶是一组竞争，不是跨设备身份。单批轨迹增量不截断；`committedHistory` 最多 80 点。

## 全新解压

审查包解压到工作树外的检查目录后，用交付镜像里的 Python 3.11 与已安装的 `requirements.txt` 跑全量：254 passed，2 skipped，1 warning，42.28 秒。两项跳过是未打进包的完整 Excel，不记为通过。独立回归文件随包在 `review_zip/TASK-007-rework-r2/`。

联调包解压到 `D:\zwyl\task007_r2_delivery`，`FUSION_PORT=18097`，`docker compose -f docker-compose.task007.yml -p fusion-task007-r2 up -d --build`。容器 `fusion-task007-api`。`/ready` 含 `multisensor-v1`。`configSha256` `c05f1751c0c2e89efe5b3c06ecdead6dc360fd1251ee42f0d0aca7365fbb88df`。`multisensorModuleSha256` `90770bb7f6a9dfa1c04c7f2b7d29f6344ae92dec02b7192940230ba6e71cec83`。process、空 tick、replay、reset 均为 HTTP 200。`maxSnapshots=1` 的回放只返回 1 帧。验证后删除该 compose 项目。`fusion-task006-api` 仍在 18089。没有停止其他项目容器。

本次检查的镜像索引是 `sha256:7f972e0706f7007853dd9ae1b67cf1cdccff81d3c05f4e46b032e19caaf28c2e`，205198827 字节。R1 的 `8c763d80…` 和 `f19cecdc…` 是更早两次构建的索引，不是这次检查。镜像不在 zip 里。

