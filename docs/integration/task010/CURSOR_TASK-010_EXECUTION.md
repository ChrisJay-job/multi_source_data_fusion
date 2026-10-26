# TASK-010：已审版本整合、远程提交与 Linux 联调交接

用户最新授权：现在应合并到主分支并提交远程，准备Linux部署、算法接口、三方联调、架构/流程、稳定性与飞行结束说明。**这次授权明确覆盖必要commit、主分支整合、正常push；优先于此前收尾文件的“等待另指令”。不需要再次请求相同授权。** 不执行用户Linux/客户生产部署，不强推，不自动发布到公网，不新建冻结tag。

## 0. 执行与读入

读取本包00–06文档、deploy模板、examples，与现有项目源码逐项核对；适用本仓AGENTS/治理规范，但不能把旧“未获commit/push授权”当作再次阻塞理由。当前TASK-008、009审查/收尾已通过；新工作以TASK-010记录，不改写历史结论。

当前工作树 `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task008`，HEAD/tag基线badcaf8；dirty包含已审业务改动。禁止先checkout/reset到badcaf8导致丢失TASK-008/009。

## 1. 版本锁与保护

1. 只读确认TASK-009最终包：6457621B，SHA `82d5536a0e9104def9ba2194c1bf8d5adebc31c93a388ab5041b433aa4bc80c7`；TASK-009收尾8247B / `48fb06766cda8b1857f1468ff7020a944ddeaf7e4c081498ea5d5f3505fd80fa`。TASK-008原收尾6512B / `1fe1eda82732ebdef6d7c7c176961045a014e39725baacf7668967cf6e8be0ab`。
2. 按TASK-009裁决§3核对13个源码指纹（本包字段/部署说明的后端指纹亦可交叉核对）。不通过时先保存差异，不自动拿旧包覆盖工作区；只处理明确属于此次整合的版本。
3. 检查所有worktree/branch/index/untracked/主仓dirty，记录并保护TASK-004、TASK-006等其他任务改动。只读定位不要全盘文件搜索。保存必要Git diff/文件清单到本地审计，不把密码/客户数据输出到终端或交接ZIP。
4. git remote URL仅确认host/repo归属，不泄露URL内凭据；`git fetch origin` 后检查远程main是否真的存在以及默认分支/祖先关系。此前没有origin/main是历史事实，不能假定今天已有。

## 2. 文档入库与部署资产

本包00–06作为交接文档落入 `docs/integration/task010/`；修正相对链接。deploy三个模板放 `deploy/integration/`，examples放 `examples/integration/`。本地.env只按example创建、不得commit真实值；加入明确的忽略规则，避免将客户CSV/SQL、data/SQLite、镜像tar、虚拟环境和review_zip上传。

旧 `docs/task008/BACKEND_HANDOFF.md`、RUN/样例仍写R10/待审或高度未实现，应在顶部加“历史说明→当前权威入口”或更新当前入口，避免同事读到错误默认profile/状态；保留历史测试版本事实，不将旧全量302/312包装成本发布新测。

必须保留以下真实能力边界：

- HTTP实时保留；MQTT是共享核心的适配通道；单进程内存会话，不能workers>1。
- profile显式multisensor-3d-v1；公司altitude→MSL为USER_ASSUMED；RID/频谱id为SN、雷达id为局部号；逐点证据按observationId。
- 当前没有飞行后专用长断点补齐接口。run.end只排空，replay只临时排序重放。文档的拟议后处理契约必须标未实现，禁止趁此任务增加未经验证的新算法/接口。
- 当前适配器没有原生TLS配置；不能编TASK008_TLS等不存在变量。公司参数未知以待填写标示；HTTP可先联调。
- 实际Broker、Linux地址、前端业务topic、flight/session规则需环境确认，不造假已部署。

模板允许按实建结果做最小部署修正，不改算法/配置/传输契约。特别核对Docker构建context、非root路径权限、模块PYTHONPATH、data持久化、单worker、服务间HTTP地址、非公网默认端口、日志轮转。仅处理本专项需要的镜像/compose，不动原18099/Broker和其他项目容器。

## 3. 本地提交、整合main和正常推送

1. 明确只纳入已审TASK-008/009业务文件、必要相关测试、合成fixtures、治理记录和本交接文档/部署资产。先审阅staged文件清单与diff；禁止`git add .`把所有dirty、不相关任务、真实客户样本/SQL、截图、凭据、data库和大审查包一并提交。测试可用本地真实文件，但不因此新增推送客户数据。
2. 保留相关源码模块依赖完整性，不能只挑13个指纹文件漏掉新增integration/1D KF/前端模块。按最终审查包的源码与当前diff核对依赖闭包。
3. 在现有任务分支提交这批已审代码与交接资产，可合理拆分已审业务与部署文档commit；不产生未授权业务变化。优先在隔离整合worktree合并到最新main，不切换/清理其他有dirty的worktree。祖先关系允许则快进；需要普通merge可执行，禁止rebase改写已发布历史/force push。
4. 远程main不存在但origin确为用户这个项目时，核对远端已有历史后可正常创建/推送main，不伪称之前已同步过，也不擅改远端默认分支。若远端有新改动，先合并正常解决；非本任务冲突或未知来源差异会改变已审算法时，不做猜测覆盖，保留整合分支与冲突说明，只暂停冲突步骤。
5. 推送已确认的项目origin/main，禁止`--force`，不推所有分支/tags。远端变更导致non-fast-forward，重新fetch检查，不反复盲推。
6. push后独立read回 `refs/heads/main`，确认等于本次最终main commit；只看到“命令已执行”不能称成功。网络/权限/远端归属无法核实则交付本地成果并明确PUSH_BLOCKED，不创建新remote或要求用户反复授权同一动作。
7. 若本地main被另一个含无关dirty的worktree占用，不能强改其引用使原dirty基线错位；先走安全隔离整合路径，保护原状态。遇确实无法在不影响他人修改的前提下更新local main，报告具体worktree/冲突并保留可审整合commit，不隐瞒本地/远端哪一步未完成。

本轮允许正常Git操作是用户最新授权；本文件仍禁止生产部署、强推、数据丢弃、篡改旧记录和额外阶段。发布可用完整commit+镜像digest，不必额外等待建tag才开始联调。

## 4. 验证预算（一次收敛）

- docs字段对照实际代码：Process/Replay/TargetSnapshot/动态增量/evidence/control、所有环境变量，不以旧文档代替；保存实际OpenAPI结构快照或从最终镜像导出。
- 本包examples可生成JSON、结构校验；请求只用合成SN/设备，不写客户敏感原文；现有MQTT短测证据可引用，明确版本。
- 合并完成后的最终候选执行一次Python3.11全量pytest（作为合并校验，不逐步骤重复），明确已知外部XLS skip；若原工作树有外部fixture，制品也需标注差别。仅失败/后续代码改变才重跑相关项，不跑一小时长稳。
- 最终源码实建一次Linux Docker镜像，在不影响18099/其他项目的空闲环回端口运行HTTP冒烟：ready指纹、process/flush/replay、来源和高度字段、入口静态文件；失败修部署资产后只补受影响检查。
- Compose `config --quiet`、模块导入/端口/数据持久可写。若本机仅有Windows+WSL Docker，可以在该Docker Linux容器验证，不能冒充公司Linux已部署。
- 能复用隔离Broker时，最终制品做一个极短合成MQTT收发/排空验证；不重跑75秒、完整CSV、30min soak、两视口UI（业务前端没有变化）。Broker不可用就明确该制品级测试NOT_TESTED，不能编PASS。
- 比较最终合并业务13文件哈希与已审锁，确认合并未悄悄改算法/UI。若合并冲突实质改变业务，做针对性回归并说明差异，不能继续引用旧PASS覆盖。

## 5. 交付给用户，而不是让用户手动整理

1. `docs/integration/task010/RELEASE_RECORD.md`：真实local main/remote main commit、Git操作结果、业务指纹、测试结果与明确限制；Linux/Broker参数缺失项保持待填写。
2. 可用于Linux的源码交付tar.gz，完整commit标识；只含运行必需源码/config/demo/scripts、requirements、部署/交接文档/合成例子；排除真实.env/客户文件/data库/虚拟环境/历史审查包。标准解压校验，包外SHA/字节。
3. 若用户目标机不能联网拉镜像，导出这次验证镜像tar（可压缩），给imageID/RepoDigest（若存在）、架构、SHA/字节；镜像不塞进小审查ZIP。镜像不能导出或空间不足须准确记录，不能用旧镜像冒充。
4. `TASK-010-attempt-001-integration-release-review-bundle.zip`：记录、文档、最终源码差异/文件清单、合并/推送及Docker定向验证证据、制品清单；不要把完整历史大包/镜像嵌套多次。包外SHA/字节。
5. 顶层说明给用户一条权威部署入口、后端入口、前端绘图入口和5分钟冒烟顺序；说明飞行后补齐尚无接口，现阶段分段归档怎么做。

结果状态按事实：`MAIN_INTEGRATED_REMOTE_VERIFIED_HANDOFF_READY` 或具体 `PUSH_BLOCKED` / `BUILD_BLOCKED`，并给完成项。此次不再停在“未commit未push”重复此前结论，也不宣称公司Linux已上线。完成即停止，不启动后处理补齐研发或其他阶段。
