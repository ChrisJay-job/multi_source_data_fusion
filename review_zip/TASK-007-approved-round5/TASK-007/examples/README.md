# 输入样例说明

除 `../reference/` 用户原件外，本目录全部是明确的**合成输入**，不能当作现场精度证据。

| 文件 | 用途 |
|---|---|
| realtime_single_target.jsonl | 12个连续批次，2 RID+2频谱+2雷达同时观测一个无SN目标；每行一个完整HTTP请求 |
| offline_single_target.json | 同一无SN单目标的离线输入 |
| offline_three_targets.json | 六设备同时观测三个相互分离的无SN目标，设备本地编号不作为跨设备身份 |
| offline_missing_local_ids.json | 部分设备连局部目标号都没有；新profile必须允许通过位置观测跟踪 |
| offline_clutter.json | 三个目标外加每帧两雷达各5个孤立随机杂波；稳定unknown目标不能冒充已识别无人机 |
| offline_crossing.json | 两目标反向交叉，结合历史运动评价；交叉附近仅位置存在歧义，不能只看最后目标数 |
| evaluation_truth_DO_NOT_SEND_TO_ALGORITHM.json | 独立评估真值，禁止向算法请求传入；用于Cursor补充有意义的准确性测试 |

时间为固定的2026-10-24示例时刻，直接做离线回放可用。实时不能把固定旧时间配当前processingTime强行发送；`../tools/integration_smoke.py` 会自动平移观测到当前时间并按实际时钟发送。

示例字段对应目标新profile。旧服务拒绝新字段或不声明新profile时不算实现失败原因已解决，必须先完成TASK-007。

本包未提供伪造的预期融合经纬度、fusionId和置信度。Cursor必须运行算法后保存真实响应，评估器只从本目录独立truth计算指标。
