# 合成调用例子

build_examples.py只生成文件，不连服务器/Broker；数据为合成，不是客户样本。先确认test tenant/site已配置且不会转发到客户前端。

```bash
python3 examples/integration/build_examples.py --out /tmp/fusion-smoke --tenant YOUR_TEST_TENANT --site YOUR_TEST_SITE
curl --fail-with-body -H 'Content-Type: application/json' -H 'X-Fusion-Channel: http' --data-binary @/tmp/fusion-smoke/http-process.json http://127.0.0.1:18099/v1/fusion/process
curl --fail-with-body -H 'Content-Type: application/json' -H 'X-Fusion-Channel: http' --data-binary @/tmp/fusion-smoke/http-flush.json http://127.0.0.1:18099/v1/fusion/process
curl --fail-with-body -H 'Content-Type: application/json' --data-binary @/tmp/fusion-smoke/http-replay.json http://127.0.0.1:18099/v1/fusion/replay
```

请求文件仅用于刚生成的新session。同一请求超时重试保持原文件；不要重新生成后仍用旧ID。HTTP三点分别取当前时刻前4/3/2秒，在新会话内供入以便观察提交与确认；HTTP flush使用同session、新batchId。

MQTT：后端/运维先订阅算法result/ack/status，再使用现有MQTT客户端向control发mqtt-run-start.json，向input发mqtt-input.json，向control发mqtt-run-end.json，均QoS1、retain=false。生成后尽快发送，不把几分钟前的实时样例直接发入已经推进的在线时钟。多批实时流应每批取真实观测时间、递增唯一ID，重发才复用原ID。

Broker host/port、账号、tenant/site必须和部署配置一致；不要把密钥复制到报告或命令历史。Linux未装MQTT CLI时可在公司现有后端客户端执行，不要求临时改变客户Broker安全配置。company TLS-only当前适配器不直接支持，详见部署/边界。

观察：result.payload.refMessageId关联输入；trajectoryUpdates pointId幂等追加；evidence里的aircraftId/SN和原始XYZ/时间可查；altitudeUpdates独立保存。run.end drained后还要确认后端已收尾落库。示例replay结果是新临时job，不能用其fusionId覆盖在线原结果。
