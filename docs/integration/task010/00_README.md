# 多源融合：Linux 联调交接包

日期：2026-10-26。读者：算法、后端、前端、部署同事。

本目录为 TASK-010 联调交接权威入口（由交接包落入仓库）。发布状态、运行代码锁、镜像指纹以同目录 `RELEASE_RECORD.md` 与 `RELEASE_VERIFICATION.json` 为准；最新 `origin/main` tip 以包外 `REMOTE_HEAD.txt` 为准（避免文档自引用提交循环）。`VALIDATION.json` 仅为输入材料历史参考。

**推荐：按完整 release commit 与镜像指纹部署到 Linux 隔离联调实例。保留 HTTP，MQTT 作为适配通道。**

| 文件 | 谁先看 | 内容 |
|---|---|---|
| `RELEASE_RECORD.md` | 全员 | 本轮整合/推送/镜像/验证事实与限制 |
| `CURSOR_TASK-010_EXECUTION.md` | 用户 → Cursor | 已获授权的本地整合、远程推送、部署制品与验证要求 |
| `01_LINUX_DEPLOY.md` | 部署/算法 | Docker Compose 模板、端口、持久化、启动、升级和回滚 |
| `02_API_FIELD_DICTIONARY.md` | 后端/前端/算法 | HTTP、MQTT、所有规范字段的类型、必选性、含义及单位 |
| `03_REALTIME_INTEGRATION.md` | 三方 | 架构、实时/结束流程图、调用、落库和绘图规则、联调步骤 |
| `04_ALGORITHM_AND_OPERATIONS.md` | 算法/后端/部署 | 算法逻辑、生命周期、并发、性能边界、重试、恢复和告警 |
| `05_POSTFLIGHT_AND_GAPS.md` | 产品/算法/后端 | 当前结束/回放接口、同 SN 归档与缺口补齐的真实能力边界 |
| `06_TEAM_ACCEPTANCE.md` | 三方负责人 | 必须确认的环境参数、责任分工、验收用例和故障排查 |
| `../../../deploy/integration/` | Cursor/部署 | Linux 部署模板（Dockerfile / compose / env.example） |
| `../../../examples/integration/build_examples.py` | 后端/算法 | 生成当前时刻的合成 HTTP/MQTT 请求；默认只写文件、不连网络 |

## 本次能做与不能冒充的能力

| 能力 | 现状 |
|---|---|
| HTTP 实时 process；MQTT 实时适配；海拔独立 KF；逐点观测来源 | 已实现，进入公司环境仍需联调 |
| 后端接 MQTT result，落库后转发前端 | 算法已给 result；公司后端/前端消费需按本文实现/核验 |
| 同一会话的短暂丢失、重现、门内关联 | 已有生命周期与关联逻辑；不保证任意长时间/任意运动可重识别 |
| run.end 排空尾部 | 已实现；不等于后端消费落库全部成功，更不等于补齐缺口 |
| replay 历史重放 | 已实现，临时会话重建，非平滑器/非在线状态恢复 |
| 飞行后专用航段拼接、跨长缺口补点、最终航线版本接口 | **未实现**。不能提供一个虚构 URL 让后端调用 |
| 公司 Broker/TLS、真实三源同机精度、生产容量/长稳 | 尚未完成相应验收 |

今天部署后可以先按真实 HTTP/MQTT 实时契约开展三方联调。后处理未实现项应作为单独需求继续开发；当前可先持久化分段、按可信 SN 分组展示，并明确缺口。不要用一条实线掩盖没有观测的时段。

## 联调前的三个决定

1. 算法部署为团队维护的 API 服务 + MQTT 适配器；不把算法源码库交给后端进程随意 import，也不重复运行多份同会话核心。
2. 设备数据进入公司后端/采集网关，后端清洗后供入算法；浏览器不承担唯一的实时数据中转。公司暂时已走前端中转时，也必须由后端可靠落库/重发，关浏览器不能停业务链。
3. DB `altitude` 按约定当海拔 MSL 米（USER_ASSUMED），不是距地高度；设备真实基准待确认。RID/频谱 id→业务 SN；雷达 id→设备局部号。

最终入口、提交号、镜像 digest、Linux 地址、Broker 参数、账号和公司前端 topic，由 Cursor 生成的发布记录与团队环境确认表补齐。占位符不是已确认环境。
