# Linux 联调部署、升级和回滚

**本包deploy目录是按源码准备的模板，尚不是在你公司Linux实跑的镜像。Cursor须按执行文件实建验证、填写发布commit/镜像ID后交付；用户负责在目标Linux执行部署。** 只启动隔离联调实例，不替换正在服务客户的生产实例。

## 1. 部署形态

一个 fusion-core（Python3.11 / uvicorn workers=1）+ 一个 fusion-mqtt-adapter，连接公司批准的Broker，后端/前端使用自己的业务服务。当前旧 docker-compose.task008.yml **只启动Broker**，不能用它代替完整算法部署。

建议目录：

```text
/srv/fusion-integration/releases/<full-commit>/    本次源码与deploy/integration/
/srv/fusion-integration/shared/data/              持久业务/队列目录
```

发布目录按完整commit保存，代码/config固化在镜像；运行data不放镜像。不要把真实凭据、客户SQL/CSV、SQLite、审查大包、浏览器缓存commit到远程。真实.env只留目标机权限600文件。

Linux应具 Docker Engine/Compose v2、可用磁盘、NTP同步、镜像/依赖获取渠道。x86_64与ARM镜像不能混用；核对uname -m及镜像架构。Python科学计算依赖需有对应wheel；离线机器提前在同架构准备镜像/依赖，禁止临场把Windows虚拟环境复制到Linux。

## 2. 部署前确认表

| 项 | 确认方式 |
|---|---|
| 源码 | 完整release commit等于已推送main；config/模块SHA等于交接锁 |
| 镜像 | imageId/RepoDigest、架构、导出文件SHA及字节；不能把旧镜像标签当新版本 |
| 端口 | `ss -lntp` 查18099，Linux用空闲隔离端口；不停止现有服务腾端口 |
| Broker | 实际私网host/port、协议、账号、ACL、报文限制、保留/会话策略；先用隔离tenant/site |
| TLS | 当前适配器无原生TLS配置；TLS-only不能直接改端口；先HTTP或另行适配 |
| 数据路径 | 可写持久目录、备份、剩余空间；SQLite WAL需与数据库同目录保存 |
| 对外访问 | 默认仅127.0.0.1。通过已有受控网关/SSH隧道给同事；若绑定公司私网IP，限制来源地址 |
| 身份 | 每实例clientId唯一；账号只授权该tenant/site topic；core写API由网关鉴权 |

## 3. 文件放置

源码根下建立 `deploy/integration/`，放Dockerfile.integration、compose.integration.yml、env.integration.example。

```bash
cd /srv/fusion-integration/releases/REPLACE_FULL_COMMIT
cp deploy/integration/env.integration.example deploy/integration/.env.integration
chmod 600 deploy/integration/.env.integration
```

编辑.env：填真实Broker/tenant/site/clientId；FUSION_IMAGE含本发布commit；FUSION_DATA_DIR用上面的持久路径。不要把示例账户当公司凭据。默认FUSION_BIND_IP=127.0.0.1；公司网关反代/SSH访问不必开放公网。

准备持久目录（有权限的部署人员执行，确认路径仅属于新联调实例）：

```bash
sudo install -d -o 10001 -g 10001 -m 750 /srv/fusion-integration/shared/data
```

不要对整个/srv或其他项目目录递归chown。Dockerfile已经创建/app/scenarios；场景草稿不属于正式业务永久数据。上传/队列路径位于/app/data持久卷。

## 4. 构建与启动

下面命令统一显式指定env文件，避免Compose把另一个目录的.env误当配置。`config --quiet`只验证，不打印密码。

```bash
docker compose --env-file deploy/integration/.env.integration -f deploy/integration/compose.integration.yml -p fusion-integration config --quiet
docker compose --env-file deploy/integration/.env.integration -f deploy/integration/compose.integration.yml -p fusion-integration build fusion-core
docker compose --env-file deploy/integration/.env.integration -f deploy/integration/compose.integration.yml -p fusion-integration up -d fusion-core
curl --fail http://127.0.0.1:18099/ready
```

离线镜像路径：先核对交付镜像tar SHA→docker load→设置.env同一镜像名；load后不要再build覆盖。以上端口如修改，curl同步修改。

ready应含 supportedProfiles 的multisensor-3d-v1、stateOwner=single-process-SessionStore；configSha256=`e25f3560d59935763f21370055fe8cd4f764da2a39b2ad001fe58e70477df518`，multisensorModuleSha256=`f4dfbc6379a5c58d0fd75b73e476e0bc07e6a7587c0cff9346527eb10ebcfa66`。版本字符串相同但SHA不同不可直接称为本审查版本。

HTTP冒烟通过、Broker参数已确认后启适配器：

```bash
docker compose --env-file deploy/integration/.env.integration -f deploy/integration/compose.integration.yml -p fusion-integration --profile mqtt up -d
docker compose --env-file deploy/integration/.env.integration -f deploy/integration/compose.integration.yml -p fusion-integration ps
docker compose --env-file deploy/integration/.env.integration -f deploy/integration/compose.integration.yml -p fusion-integration logs --tail 100 fusion-mqtt-adapter
```

容器内的localhost是自己，不能把公司Broker误填127.0.0.1（除非同容器本地代理另有批准方案）；容器服务间HTTP用fusion-core:8000。当前不启动本地匿名Broker、不占用公司现有Broker端口。

ready不是MQTT健康：另外验证适配日志连接成功、status主题新鲜online、后端能订阅并收一批result。Broker不能连时不要说整个链路ready；HTTP仍可独立工作。

## 5. 冒烟和网页访问

用examples/build_examples.py生成合成请求。新session用于测试，先POST process（显式3D），检查无顶层error、至少有可解释输出/重排，再发送同session的flush尾批；重复原批次应幂等，换内容同ID应拒绝。见03流程与06验收。不要把公司真实消息复制进调试session后广播到客户前端。

工作台是验证工具，网页入口 `http://Linux私网地址:端口/` 仅在允许访问路径时可用。默认绑定环回时可用已有网关或：

```bash
ssh -L 18199:127.0.0.1:18099 USER@LINUX_HOST
```

浏览器访问本机18199；这只是人员调试隧道，公司后端正式调用用服务间内网地址。原Windows18099和Linux18099是不同机器，不冲突；页面关闭不会让公司业务自动结束。

## 6. 升级与回滚

1. 明确当前活跃session和未决inbox/outbox；暂停新增业务供入，正常run.end/flush并保存后端结果。不要在正在飞行时因为“发布小版本”直接重启核心。
2. 保存旧commit、镜像ID/digest、配置、只读指纹与后端账目。对SQLite做一致性备份（受控停适配器后复制含WAL/SHM的完整目录，或使用SQLite备份机制）；不要只复制活跃.db漏WAL。
3. 新版本部署到隔离实例/空闲端口，先验证，不让相同session被两套核心并行消费。确认切流计划后由后端改变路由。
4. 需要回滚时恢复旧镜像/配置及相容数据；只停本project的指定服务，不运行全局docker stop/rm/prune，不使用down -v删持久数据。
5. **无论升级还是回滚，核心重启均不自动恢复内存KF。** 要以新epoch/受控新session或明确状态恢复流程开始；后端不能把前后代际直接画为无缝同一滤波状态。适配器DB恢复只恢复队列，不恢复KF。

自动restart能拉起进程，但不能承诺在线目标状态无损。公司是否接受联调期间中断、生产需要什么SLA，须三方确认后设计持久状态/高可用。

## 7. 发布记录至少返回

完整main commit、远程main SHA（确实push成功后）、制品SHA/字节、镜像ID/digest与架构、部署实例/project名、Linux端口、Broker命名空间（凭据不进报告）、ready及静态文件指纹、冒烟结果、剩余未验收项。以此告知后端和前端“当前正在联调哪一个版本”。
