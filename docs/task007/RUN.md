# TASK-007 启动说明

本机已经在跑的容器是 `fusion-task006-api`，端口 `127.0.0.1:18089`。这是本机开发入口，远端不要访问这个回环地址。

- 从解压后的目录启动：`powershell -File scripts/task007_up.ps1`。脚本会等 `/ready` 真正返回 `multisensor-v1` 才算成功。
- Linux：`sh scripts/task007_up.sh`，检查 `sh scripts/task007_health.sh`，冒烟 `sh scripts/task007_smoke.sh`，停止 `sh scripts/task007_down.sh`。
- 本机 `18089` 若已被开发容器占用，先设置 `$env:FUSION_PORT="18097"` 再启动。
- 健康检查：`powershell -File scripts/task007_health.ps1`。`/ready` 必须包含 `multisensor-v1`。
- 停止：`powershell -File scripts/task007_down.ps1`。只停止 `fusion-task007`，不删其他项目或数据库卷。
- 镜像：`docker build -f Dockerfile.task007 -t fusion-task007:attempt001 .`。大镜像不放进 zip。
- 状态在单进程内存中。重启后实时会话消失。离线 `POST /v1/fusion/replay` 只在临时会话里重建历史，不写回 `MS_STORE`。要继续实时融合，用新的 `sessionId` 重新调用 `POST /v1/fusion/process`。不要用多个 worker 拆同一个会话。
- 冒烟：`python tools/integration_smoke.py --base-url <可达地址>`。服务未声明 `multisensor-v1` 时脚本会失败，不会改跑 legacy。
