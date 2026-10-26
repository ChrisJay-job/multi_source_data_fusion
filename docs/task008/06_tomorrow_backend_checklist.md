# 明日后端对接清单

本地模拟可先行；下列项未确认前真实联调标 **NOT_TESTED**。

## 连接

- [ ] Broker 地址 / 端口 / MQTT 3.1.1 或 5（本实现默认 3.1.1）
- [ ] TLS 是否启用与证书
- [ ] 算法专用账号与 ACL（仅 input/result/ack/control/status）
- [ ] 是否允许 retain 仅 status

## Topic 与信封

- [ ] 最终前缀与 tenant/site 命名
- [ ] 确认 `schemaVersion=fusion-mqtt.v1` 或公司版本号
- [ ] 输入/输出 JSON 各一份实样（含拒绝与空增量）
- [ ] 后端对 ack.status 枚举的处理表

## 时间与坐标

- [ ] measurementTime / receivedAt 时区与语义
- [ ] 坐标系（WGS84？）与速度/航向单位
- [ ] 高度基准现场确认（本仓库文件侧：`database_altitude_msl_v1`）

## 身份

- [ ] RID / 频谱 SN 命名空间与映射是否与 `confirmed_sn_v1` 一致
- [ ] 雷达 local id 字段
- [ ] session / flight 归属与结束规则（run.end ≠ 飞行结束）

## 容量

- [ ] 现场峰值观测/秒、batch/秒、设备数、活跃目标数
- [ ] 后端结果去重键：messageId；点：sessionId+epoch+pointId

## 联调日不要做

- 把模拟器称为公司后端已通过
- 未授权探测客户网络
- 未实现虚拟时钟时宣称倍速联调
