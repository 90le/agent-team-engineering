# Changelog

本项目遵循语义化版本。版本标签只在仓库验证、测试、Skill校验和空目录冷启动全部通过后创建；已发布标签不移动。

## 1.0.0 — 2026-08-12

Agent Team Factory 的“可移植独立写入者权威链与可恢复宿主生命周期”版本：

- 新增严格的 `WriterTopology` 契约，并把规范 `WriterTopology → PlanRevision → ApprovalGrant` 三件套绑定为拓扑摘要 `sha256:b4b3e8ad868889082a871e3ecc7588b00ced58a0555da299061c0aae758de0dd`、计划摘要 `sha256:e8b43d51e503d3cd453627aa0249775a301e1ae14336ef866eb1cfd6980ede7a` 与批准范围摘要 `sha256:57137766d7f2c13c1b5eaecba648a67deab6d888400b609cfb1b210dc90c3b00`。PlanRevision 与 ApprovalGrant 的统一 Schema `$id` 升级为 `1.1.0`，仍兼容省略 `writer_topology` 的 `1.0.0` 文档；`1.1.0` 必须显式绑定准确拓扑或 `null`，拓扑变化会同时使计划、批准与重试身份失效。
- 新增 `./agent-team native writer-authority-validate` 离线链校验。它只证明三个本地文档的 Schema、语义、摘要和交叉绑定一致，并明确返回 `automatic_execution: false` 与 `identity_or_signature_verified: false`；它不认证批准者身份或签名，也不会启动 Agent、创建 worktree/分支、写仓库、开 PR、merge、release 或 deploy。
- Host-install plan 与 install lock 升级为完整 proposal 绑定的 `1.1.0` 生命周期：准确披露持久空 ordinary-file guard、确定性文件 stage、唯一临时元数据 scratch、旧 tombstone 删除效果和卸载保留项。v0.9 尚未执行的 host plan 必须重新 `plan → preview → confirm`；v0.9 legacy lock 仅可 `LEGACY_UNBOUND` 只读核验，禁止自动破坏性卸载。
- Apply、verify 和 uninstall 通过持久 `fcntl` guard 串行化协作中的本机 Factory 进程。源文件通过不跟随符号链接的目录描述符读取，并在独占发布前再次核对准确 SHA-256；不同计划的并发 apply 在第二次写入发生前安全停止。该机制不宣称抵抗 root、内核、文件系统、存储故障或非协作特权写入。
- Uninstall 新增 `ACTIVE → UNINSTALLING → UNINSTALLED tombstone` 状态机与只读 `uninstall-preview`。每个文件在 unlink 前重新核对内容与 inode，中断可按同摘要继续，完成后重放返回 `ALREADY_UNINSTALLED`；持久空 guard 和 tombstone 被保留，目录永不删除，因此可能留下空目录。
- Factory `1.0.0` 新增从 `0.9.0` 以及所有既有受支持版本到 `1.0.0` 的显式、摘要绑定、可恢复 Team Instance 迁移。Team Instance 升级与 host-install legacy lock 对账是两套独立生命周期，不能用普通实例迁移冒充宿主安装所有权升级。
- 新增 ADR-0012、ADR-0013、独立写入者指南、并发/延迟漂移/中断恢复负例和 v1.0 发布验收契约。GitHub Actions 的 `upload-artifact` 固定到官方 v7.0.1 提交 `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` 并使用 Node 24 运行时，消除 v0.9 精确标签门禁中的 Node 20 弃用提示。

限制：v1.0 把独立前端/后端写入者表达为 `DESIGN_ONLY` 权威，不提供持久多写入者调度器。当前 Managed 参考控制器仍只有一个源码写入 `builder`，所有宿主映射仍为 `topology_enforced=false`。Factory 不自动执行独立写入者，不自动 merge、release 或 deploy；真实身份签名、模型、账号、频道、外部 SCM、Runner 与生产权限仍需要独立认证、授权和一致性证据。

回退：`v0.9.0` 历史保持不可移动。Team Instance 从 v0.9 升级到 v1.0 时必须保留外部恢复包，并用标准 rollback 返回升级前锁；宿主投影先运行 `host verify` 与 `uninstall-preview`，只对 proposal-bound v1 lock 使用准确摘要卸载。`LEGACY_UNBOUND` v0.9 lock 只能人工对账，不能删除锁或复用旧批准强制卸载。完整发布状态必须以 [v1.0 验收契约](docs/16-release/v1.0-acceptance.md)要求的 PR、CI、annotated tag、GitHub Release、匿名安装和外部证据为准，不能仅从本节标题推断远端发布已完成。

## 0.9.0 — 2026-08-12

Agent Team Factory 的“宿主原生团队投影与安全安装生命周期”版本：

- 将公开定位从“自成一套多智能体运行时”校准为 Host-native Agent Team Factory。用户只需提供现有项目、目标和已经使用的AI工具；Factory先生成可迁移的Markdown/JSON/Skill/Git权威团队，再按目标宿主真实能力投影角色、Skills、上下文与协作说明。原有Managed控制器保留为可选的持久执行层。
- 新增严格宿主能力目录和`host list/probe`命令。描述符区分`native-verified`、`native-install-verified`、`verified-export`、`experimental-plan`、`portable`与`research-unknown`；版本探测只允许无Shell、无stdin、无凭据环境中的`--version`或`version`，超时和错误均返回稳定状态。
- 新增OpenClaw原生工作空间、workspace Skill和注册计划，以及Hermes Agent Profile distribution、SOUL、Skill bundle与Kanban swarm计划。OpenClaw 2026.7.1-2和Hermes 0.20.0均在隔离、无凭据状态目录完成创建、发现和删除验证；没有绑定频道、调用模型或启动任务，因此准确等级为`native-install-verified`。
- Codex现在把复用Skill投影到`.agents/skills`，Claude投影到`.claude/skills`；两者保持`verified-export`，不把确定性文件生成夸大为已加载或已执行。
- 新增固定Multica v0.4.23/`e0d0b3815342a80460f8a1c66c56ddfc662c7d46`的实验overlay计划，按Skills、Agents、additive Skill绑定、Squad、Squad instructions与成员顺序表达；不猜测Runtime/Workspace UUID、不使用replace-all、不启动Task。其自定义Multica License进入显式来源审计，不被错误标记为Apache-2.0，也不成为运行依赖。
- 新增`host plan/preview/confirm/apply/verify/uninstall`两阶段生命周期。第二次确认绑定团队设计、Context Lock、宿主等级、目标目录、逐文件路径与SHA-256；安装只创建缺失文件，拒绝覆盖、秘密、符号链接、陈旧来源和摘要篡改，支持同计划中断恢复、幂等重放、漂移检测和只删除未改变托管文件的精确卸载。
- 引导采用方案升级为Schema 1.1.0：第一次确认现在直接绑定完整Team Design、Design摘要、Preset摘要、Factory版本与Factory合同摘要；执行使用方案中已确认的设计，不再按可变Preset名称重新编译。v0.8.1尚未执行的1.0.0方案需重新生成并确认。
- Managed控制器与宿主投影现在可以组合：OpenClaw/Codex/Claude保留既有受治理运行时文件并补充Skill，Hermes与Multica可在同一权威团队中生成独立宿主投影。v0.9的Managed写入身份仍是单一`builder`；它不虚构已实现的前后端多写者并发控制。
- 重写中英文首页、AI采用入口、AI接管入口与创建Skill；新增宿主安装Skill、宿主支持矩阵、对话工作流、OpenClaw/Hermes/Multica指南、ADR-0011和机器可校验的v0.9宿主一致性报告。无历史AI必须先发现并解释推荐，团队创建与宿主安装各自预览、各自等待准确确认；真实宿主导入仍是第三个授权点。
- 新增从v0.8.1以及所有既有受支持版本到v0.9.0的显式实例迁移路径。Factory版本、能力包、Python包、Codex/Claude插件、SBOM与来源证明统一到0.9.0。

限制：v0.9不会读取真实宿主配置或凭据，也不会自动创建OpenClaw绑定、Hermes模型任务、Multica对象、GitHub写入、merge或deploy。Multica仍是`experimental-plan`；无法确认身份的Leda保持`research-unknown`。宿主安装管理的是文件投影，不替代各产品自己的认证、安全隔离与运行时权限。

回退：`v0.8.1`保持不可移动。先运行`host verify`；对无漂移的v0.9安装使用安装锁中的准确proposal digest执行`host uninstall`，有漂移的文件必须人工对账且不会被删除。普通Team Instance使用升级时生成的外部恢复包执行标准回滚，不删除锁、不移动标签、不复用旧摘要确认。

## 0.8.1 — 2026-08-11

Agent Team Factory 的“场景优先引导采用与生成后可用性”补丁版：

- 将公开首页、中文首页、`AI-START.md`、`create-agent-team` Skill 与自包含 `bootstrap-agent-team` 插件改为结果优先入口。普通用户只需描述团队目标；AI必须先只读发现、每轮最多询问三个高影响问题、解释推荐与备选、暴露未知项和禁用能力，不再要求用户先学会 Lite、Managed 或 Custom。
- 新增严格 `guided-adoption-plan` 契约及 `onboard inspect/plan/validate/preview/confirm/apply/guided` CLI。方案摘要覆盖发现事实、用户意图、推荐、角色、平台、准确路径、副作用与限制；草案不能应用，准确确认绑定摘要，任意篡改、陈旧源码提交、秘密样内容、符号链接、越界路径和已有输出均 fail closed。
- 明确创建团队与接入目标项目为两个独立确认点。首次确认只允许创建准确的新本地团队目录，不修改目标项目、不接触外部系统，也不授权模型、OpenClaw、SCM、Runner、merge、release 或 deploy。
- 为所有新上下文团队生成 `GETTING-STARTED.md`，扩展团队内 `AI-START.md`：用户无需记角色名，AI先解释角色路由，每轮问题上限为三，支持首任务、查看持久状态、从已核验交接继续和安全停止。平台导出同时携带该使用入口。
- 为研究/知识、内容和运营场景提供安全的多角色起始映射；Custom + Managed 未完成能力映射时明确拒绝，不用文档假装外部自动化已经存在。
- 新增完整引导采用章节、对话协议、方案契约、FAQ、ADR-0010，以及软件协作、持久反馈到 Draft PR、长期知识团队三类无历史采用示例。
- Codex/Claude/OpenClaw发现插件升级到 `0.8.1`，默认提示直接触发“检查—澄清—推荐—预览—确认—创建—教学”。README、GitHub元数据和社区入口面向公开采用者重新定位。
- 增加采用方案、摘要确认、篡改、秘密、路径、提交漂移、无覆盖、目标项目不变、CLI端到端和生成后指引测试；保留 `create --preset`、`create --design` 与已发布 v0.8.0 团队格式兼容，并新增 v0.8.0 到 v0.8.1 的显式实例升级来源。

限制：v0.8.1 改善“如何得到并使用团队”，不把 L1 参考内核变成已连接生产账号的无人公司。Managed 真实接入仍需单独的身份、最小权限、隔离 Runner、凭据、恢复与负例验收；团队固定无 merge/deploy 权限。

回退：`v0.8.0` 与 `v0.8.1` 均为不可移动 annotated tag。普通用户可检出 `v0.8.0` 使用旧的显式 preset 入口；已升级实例使用升级时生成的外部恢复包与当前救援包按标准生命周期回滚，不手工改锁或复用旧确认。

## 0.8.0 — 2026-08-11

Agent Team Factory 首个“供应商中立控制内核 + 可替换端口”的 L1 参考版：

- 接受 ADR-0009，保持 Markdown/JSON/Skill/Git 为可迁移上下文权威，Native 控制器只负责必须确定的运行状态。Ingress、Identity、SCM、Agent Executor、Sandbox、CI、State、Evidence、Notification 和 Secret 全部通过可替换 Port 连接，任何外部平台都不是唯一核心。
- 新增严格 TeamSpec、RoleContract、WorkflowSpec、WorkItem v2、PlanRevision、ApprovalGrant、Run、EvidenceBundle、AdapterDescriptor 及命令/事件契约。规范摘要、未知字段、版本冲突、权限越界和篡改均 fail closed；v0.7 只能单向导入，旧批准绝不迁移。
- 新增无第三方依赖的 Adapter Port SDK，实施版本/能力协商、deadline、cancel、health、幂等和未知副作用停止语义；描述符不会动态加载代码。
- 新增 SQLite Native 参考控制器，覆盖 optimistic revision、精确身份/计划批准、全局单次 nonce、Worker 租约、事务 outbox、retry-after、预算/超时、内容寻址证据、哈希链审计、备份、重启与孤儿恢复。
- 新增完全离线的“反馈 → 精确人工批准 → 实现 → 测试 → 独立复核 → 要求修改 → 返工 → Draft PR”场景。崩溃矩阵、重启和完整重放不重复事件或外部 effect。
- 新增一次性 OCI Runner 一致性门禁。它只允许显式确认的 GitHub-hosted 临时 Worker，三轮验证网络、挂载、凭据、进程和清理边界；发现 PVE/NAS/生产路径会在启动容器前拒绝。
- 新增精确批准绑定的 GitHub SCM 端口和持久 webhook delivery ledger。身份ID、仓库、base、路径、plan digest、TTL 不完全一致就拒绝；写入仅限反馈 Issue、提案分支/文件和未合并 Draft PR，无 merge、release、settings 或 deploy 能力。
- 新增受 Schema 约束的 Codex、Claude 和 Generic CLI 路由。进程使用 argv 而非 Shell、最小环境、明确沙箱/审批参数与不保留会话；通用协议 v0.8 只允许读取型请求。
- 新增 OpenClaw、OpenHands、Paperclip 和 ACP 纯投影边界，以及 SWE-ReX、Container Use 的可选 Runner 候选记录。上游仅使用固定 commit/许可证参考，无新增 SDK 或运行时依赖；删除任一可选平台不影响 Native 闭环。
- 新增 SPDX 2.3 SBOM、来源/候选引用清单、版本一致性审计、相对 v0.7.0 的历史凭据扫描、跨 AI takeover、干净克隆 cold start 和精确注释标签 release smoke。
- 将 Factory、能力包、Python 项目、Codex/Claude 插件统一升级到 `0.8.0` 并标记 `STABLE`。保留 v0.2–v0.7 实例的显式、可恢复升级路径。

限制：v0.8 是 L1 参考实现，不是分布式多租户平台。仓库不携带模型/GitHub 凭据，不安装 OpenClaw/OpenHands，不将本机 Host Runner 声称为安全沙箱，不提供自动 merge 或生产 deploy。真实采用必须在专用 Private 测试项目逐项开启身份、Runner、模型和 SCM 端口。

回退：`v0.8.0` 标签不移动。Factory 修复走新补丁版；普通实例使用升级前外部恢复包与当前救援包回滚。回退前必须停止 writer、备份 SQLite、验证审计链并对账已发生的 Issue/PR；不能用旧批准或手工改锁绕过 v0.8 权限。

## 0.7.0 — 2026-08-10

Agent Team Factory 的“上下文优先、普通用户可创建团队”版本：

- 新增 Team Design 与 Context Lock。`./agent-team create` 提供 `software-lite`、`software-managed`、`custom` 三个入口，把原则、项目事实、角色、Skill、工作流、知识来源和平台目标确定性编译为独立团队包；Schema、无覆盖发布、路径/秘密检查和逐文件SHA-256摘要共同保护生成资产。锁显式区分编译器管理与用户维护文件，让项目上下文、架构、知识、ADR和工作记录可通过Git评审持续演进。
- Lite软件团队内置反馈、产品、架构、前端、后端、QA、独立审核和发布交接八个完整角色；Custom支持任意用户角色和顺序，但保持context-only，不把Markdown声明解释成工具授权。
- Managed在同一上下文层下复用v0.6受治理运行时，继续强制准确人工计划批准、隔离worktree、Draft PR、声明式测试、作者/审核者分离、持久状态与恢复，并固定停在人工merge决定之前。
- 新增普通用户根CLI、交互式向导、preset发现、设计验证、团队检查和平台导出。导出必须同时携带共享权威上下文，不覆盖目标项目已有AI规则。
- 新增Codex marketplace/plugin、Claude marketplace/plugin、OpenClaw兼容Skill bundle和Generic AI入口。发现包自包含且只含Manifest、Skill与参考资料，不含MCP、hook、后台进程、凭据或隐式外部写入。
- 重写中英文README，新增`AI-START.md`、完整上下文团队指南、平台安装指南、可编译示例、ADR-0008、Apache-2.0许可证、安全策略、贡献指南和社区行为规范。
- 扩展仓库验证和安全负例，覆盖三个模式、任意角色、未知handoff、秘密、Managed映射、确定性、无覆盖、设计/文件/符号链接漂移、平台导出和v0.6运行时兼容。
- Factory、能力包和Python项目版本升级到`0.7.0`，并新增从`0.6.0`以及既有v0.2–v0.5.1实例到v0.7的显式、可恢复迁移。实例Schema、SQLite Schema和`software-delivery 0.2.0`团队包保持兼容；旧版`team create --blueprint`和运行时命令继续保留。

限制：发现插件不会自动创建模型账号、OpenClaw Gateway/频道、GitHub身份、生产Runner或常驻服务；Factory仍不提供自动merge或生产部署。Lite依赖采用平台正确隔离工具，角色文件本身不是安全沙箱。Managed仍是单机参考控制面，不宣称分布式高可用。

回退：Lite/Custom团队是普通锁定文件包，可保留v0.7 Factory或迁移为目标项目的权威文档；v0.6工具不会解释Context Lock。普通Team Instance升级必须使用升级时创建的外部恢复包和新的救援包执行标准rollback，回退前停止所有writer、备份SQLite并对账外部Issue/PR。

## 0.6.0 — 2026-08-10

Agent Team Factory 首个“团队创建器 + 可执行参考闭环”版本：

- 新增严格 Team Blueprint 与 Team Lock。`team create/validate/inspect/export` 能把一个无秘密蓝图确定性编译为锁定的 Team Instance，并生成 OpenClaw `agents.list`/workspaces、Codex `.codex/agents/*.toml`、Claude `.claude/agents/*.md` 和 Generic AI 角色包；输出与 export 都不覆盖已有路径，逐文件摘要检测漂移。
- 新增 `create-agent-team` Skill、示例蓝图、平台说明和 ADR-0007，明确 Factory、Team Instance、Target Project 的边界以及 OpenClaw、Codex、Claude、Generic AI 的准确支持范围。
- 新增 schema-bound CLI Model Router 和 `agent.invoke` 适配器。按角色绑定选择 Codex/Claude，固定项目、base commit、revision、能力、预算和结果Schema；Codex禁用项目规则并保留sandbox，Claude read-only角色使用safe/plan mode且没有Bash，模型进程使用不含继承API密钥的最小环境，所有模型结果拒绝身份漂移与凭据样证据。
- 新增可重启 Team Runtime：反馈规范化、triage、规格、人工计划批准、隔离 Git worktree、实现提交、Draft PR、声明式测试、QA 和独立 reviewer 由同一 SQLite 修订/租约/outbox/审计链约束，最终固定停止在 `REVIEW_APPROVED`，没有 team merge 或生产部署入口。
- 新增本地 owner 审批命令。操作者必须回填完整 specification scope hash，短期断言绑定 owner、动作、工作项、revision 和 evidence；本地模式明确依赖操作系统账号，远程环境必须替换为认证身份适配器。
- 新增 Runner Profile 与显式 `--allow-host-runner`。项目、本地仓库、默认分支及其准确base commit、模型模式、交付模式、Runner Profile摘要和command IDs全部进入人工批准scope；批准后、worktree创建前基线移动会安全停止。命令使用 argv 而非 Shell，以无凭据最小环境执行并保存脱敏证据。证据摘要继续绑定SQLite审计事件，篡改、自行重算摘要、失败或测试后worktree漂移都不能记录或维持CI通过。本机执行器仍不是生产沙箱。
- 新增 GitHub CLI Transport。只有实例显式启用、项目/remote/default branch 匹配且命令同时提供 `--provider github --allow-provider-writes` 时，才允许 Issue、隔离 branch push 和 Draft PR；创建使用稳定标记在重试前对账，不提供 merge。
- 新增无网络 `team demo` 冷启动：自动运行到 `SPEC_READY` 并证明实现尚未开始，准确人工计划批准后才运行 builder/tests/reviewer，最终产生本地 Draft PR 证据。端到端验收覆盖错误 hash、缺少 Runner 同意、测试失败、作者与 reviewer 分离、证据篡改、worktree/commit落盘中断恢复和重复运行无副作用。
- outbox Worker 可以按准确 effect ID 领取，避免协调器误消费无关任务；模型 at-most-once 不确定结果保持人工处置。effect lease 上限与最长模型操作统一为一小时，运行时保留安全余量。
- Factory、能力包和 Python 项目版本升级为 `0.6.0`；新增从 `0.5.1` 以及既有 v0.2/v0.3/v0.4/v0.5.0 的显式实例迁移路径。实例 Schema、锁 Schema、SQLite Schema 与 `software-delivery 0.2.0` 团队包保持兼容。

限制：v0.6 不包含常驻调度器、OpenClaw Gateway/频道自动接线、分布式多租户控制面、生产级隔离 Runner、自动 merge 或生产部署。live CLI 与 GitHub 模式必须先在采用者的临时 Private 项目验证身份、权限、沙箱和恢复路径。

回退：Team Blueprint 编译结果和 runtime worktree 是新增资产，不由旧版本解释。升级过的普通实例可使用 v0.6 升级时生成的恢复包与新救援包执行标准 rollback；SQLite Schema 未改变，但回退前仍需停止所有 writer、备份数据库并对账外部 Issue/PR。

## 0.5.1 — 2026-08-10

`v0.5.0`远端标签验收后的补丁版本：

- 修复两条开发快照安装测试对当前Git标签状态的隐式依赖。测试现在显式注入“未发布来源”身份，因此在开发分支和精确annotated tag中验证同一语义，不再把正确的发布身份误判成失败。
- 新增 `tools/release-smoke.sh` 发布门禁：在隔离的干净克隆中模拟当前精确注释标签，重跑完整验证、正式安装、安装完整性、Doctor和实例生成；GitHub CI在真实标签创建前执行该路径。
- 保留已发布的 `v0.5.0` 标签与提交，不移动、不重写；该版本的正式安装与完整性验证可工作，但从标签源码运行全套测试会出现上述两条假阴性，因此由 `v0.5.1` 取代。
- 增加从 `v0.5.0` 到 `v0.5.1` 的显式实例补丁升级路径，并继续支持v0.2、v0.3、v0.4来源；所有迁移仍要求摘要绑定计划、外部恢复包、静止运行库和可验证发布。
- Factory、能力包和Python项目版本同步更新到 `0.5.1`；实例Schema、锁Schema、SQLite Schema、团队包、适配器契约和默认安全边界均未改变。

回退：若实例已经从v0.5.0升级，使用升级时生成的恢复包和新的救援包执行标准 `instance rollback`。不要通过移动标签或手工改锁来伪造版本。

## 0.5.0 — 2026-08-10

Agent Team Factory的可安装、可迁移和可接入版本：

- 增加正式Factory安装与验证命令。仅接受干净、精确annotated tag，安装清单绑定源提交、标签、逐文件模式/大小/SHA-256和整树摘要；输出原子发布且不覆盖已有目录。
- 安装验证拒绝缺失、篡改、额外文件、符号链接和派生缓存；安装CLI禁止生成未声明Python字节码。开发快照只存在于内部测试入口，正式CLI不能绕过发布验证。
- Doctor升级为严格Schema报告，检查Python、Git、POSIX生命周期锁、仓库契约、Factory来源、契约摘要、默认关闭的生产接入，以及可选实例锁、漂移、事务日志和SQLite审计。
- 增加从v0.2/v0.3/v0.4到v0.5的显式实例升级计划。计划绑定绝对实例路径、实例/锁/契约摘要、源与目标版本、逐文件动作和保留的seeded自定义；陈旧计划在写入前失败。
- 升级只允许从精确发布执行；运行库存在时必须暂停、审计通过、无活动租约及无待处理/失败/已领取外部效果，且操作者必须另外停止所有Writer进程。
- 在变更前生成实例外、权限受限、逐文件验证的恢复包；managed文件逐项原子切换，实例锁最后提交。失败自动回到源版本，进程中断由持久生命周期日志恢复。
- 主动回滚先为当前版本生成救援包，并与升级共用事务日志；回滚失败或进程中断能恢复到回滚前版本。恢复拒绝包篡改、身份错配和操作后的第三方漂移。
- 生命周期互斥使用POSIX `fcntl`；日志位于被Git排除的 `runtime/.factory-lifecycle-journal.json`，存在时所有runtime命令安全停止。
- 现有项目接入改为摘要绑定的proposal-only包，Git发现禁用optional locks，提案和候选实例配置均禁止写入目标仓库；验证拒绝篡改、额外文件、符号链接和凭据样内容。
- 组合操作只增加一个 `proposal-only` 项目绑定，不启用适配器、不改变自治和批准政策。新增安装、升级/恢复、项目接入Schema、ADR、操作章及跨AI升级Skill。
- 增加严格Schema的跨AI接管验收配置与自动冷启动入口，验证薄平台入口、角色上下文摘要、实例生成/Doctor、目标仓库逐字节不变和proposal-only候选；报告明确自动层不能替代Claude、Kimi等模型的无历史人工重放。
- GitHub Actions发布门禁升级到Node 24世代的官方checkout/setup-python版本，并固定到已核验的完整提交SHA，避免浮动标签与Node 20退役风险。

兼容性：实例Schema、锁Schema、SQLite Schema和 `software-delivery 0.2.0` 团队包保持不变。v0.5可显式升级v0.2、v0.3、v0.4实例；用户修改的seeded文件原样保留，managed漂移会阻止升级。`relock`继续只接受配置变化，不能改变Factory版本。

限制：生命周期写操作要求POSIX `fcntl`，不支持Windows写入回退、分布式锁或多节点高可用。Factory无法自行证明外部Worker已经停止。多文件切换是锁最后提交的逻辑原子性，不是文件系统级多文件原子事务。恢复包不含SQLite、目标项目、秘密、Runner制品或外部提供者状态；项目接入也不会创建真实远程权限、PR、守护进程或生产团队。

回退：使用升级时产生的原始恢复包执行 `instance rollback`，同时指定新的救援包路径；回滚前后都保持Writer停止和运行库静止。若存在生命周期日志，先用 `instance recover` 返回操作前版本，不能删除日志。v0.5没有改变SQLite Schema，运行库仍需独立verified backup和外部效果对账。

## 0.4.0 — 2026-08-10

Agent Team Factory的适配器安全边界版本：

- 将平台Manifest升级为v2，声明配置Schema、操作slot/方向、副作用类型、投递语义、能力、项目作用域、输入/输出Schema、超时、信任边界、逻辑凭据和实现模式。
- 增加不动态导入entrypoint的显式适配器宿主；实例启用、Manifest契约、持久审计事件授权、已注册实现和秘密引用作用域必须同时通过。
- 增加outbox Worker以及`provider-idempotency`、`reconcile-before-retry`和`at-most-once`故障语义；永久契约/授权失败直接进入dead-letter。
- 未领取或调用前已过期的outbox claim不能启动适配器；Worker会把抢在dispatch前过期的claim按持久状态对账，而不是执行副作用。
- 增加无网络Recording、GitHub映射与`local-dry-run`参考实现，覆盖提供者成功后崩溃、重试对账、稳定标记和不启动进程的Runner计划。
- 宿主把仓库与Runner目标绑定到实例声明的项目、provider、mode和默认分支；OpenClaw公开反馈与owner批准使用不同slot，复用同一适配器也不能跨入口调用操作。
- 模型适配器使用新增的project-bound任务信封；原`task-envelope`契约保持不变，避免静默改变已发布Schema。
- owner工作流批准改为强制验证短期断言，并绑定身份、动作、工作项、revision和完整evidence；数据库只保存claim摘要与证据引用。
- 增加HMAC参考验证器、签名Webhook入口、隔离执行请求、默认拒绝事件授权策略、适配器实现Skill以及秘密/WAL、越权、重放和恶意Runner负例测试。
- 权威文件与边界输入改用严格JSON解析，拒绝重复对象键、`NaN`和无穷值，避免不同解析器对同一文档产生不同解释。

兼容性：实例Schema仍为 `1.0.0`，`software-delivery 0.2.0` 团队包与v0.3 SQLite Schema保持不变；v0.4可以读取并校验既有v0.2/v0.3实例，同时报告Factory版本可升级，但不能通过`relock`冒充已经完成跨版本迁移。自动升级器将在后续版本提供。第三方旧Manifest必须迁移到v2。调用owner工作流转换的集成必须提供`ApprovalVerifier`和断言，这是有意的安全收紧；暂停/恢复的受控本机入口不变。

限制：GitHub实现只映射请求并依赖调用方注入认证Transport；OpenClaw、模型和file-inbox仍是契约接口。HMAC仅供本地参考，`local-dry-run`只校验计划。版本不包含真实Token、网络守护进程、模型调用、生产沙箱、合并或部署能力。

回退：先暂停、备份并验证SQLite状态，再检出 `v0.3.0`。数据库Schema仍兼容，但v0.3不能解释v0.4实例锁和Manifest；保留v0.4实例提交、秘密引用和外部状态对账记录，不能用回退绕过已要求的认证批准。

## 0.3.0 — 2026-08-10

Agent Team Factory的持久控制平面版本：

- 增加SQLite事务状态库、数据库Schema版本和非覆盖式备份/恢复。
- 工作项状态、幂等记录、任务租约、全局暂停、事务outbox和哈希链审计在进程重启后保持一致。
- 非人工角色提交状态变化必须持有匹配身份、角色、修订和有效期的租约；人工owner批准不允许Agent冒充。
- 重复反馈、命令和外部效果按幂等键去重；相同键绑定不同请求时失败。
- outbox具备领取租约、失败重试、次数上限、dead-letter和过期领取恢复，为后续真实适配器提供副作用边界。
- 增加runtime CLI、开放审计/租约/outbox/状态Schema以及重启、并发、回滚、暂停、篡改、备份恢复和CLI端到端测试。

兼容性：实例Schema和 `software-delivery 0.2.0` 团队包保持不变。`v0.2.0` 实例可由v0.3读取并运行，只会报告Factory版本可升级；运行数据库是新建的外部派生状态。

限制：本版本的outbox尚未绑定真实GitHub、OpenClaw、模型、Runner或部署适配器；外部副作用执行仍关闭。本机CLI不构成远程身份认证，人工批准只允许在受控本机边界内演示和管理。

回退：停止控制平面并保留SQLite备份，检出 `v0.2.0`。v0.2不能运行v0.3数据库，但不会删除它；恢复v0.3时使用匹配版本打开并验证审计。

## 0.2.0 — 2026-08-10

Agent Team Factory的第一个实例生命周期版本：

- 明确Factory仓库、Private实例仓库和目标项目仓库的权威边界。
- 增加Factory包、实例清单和实例锁Schema。
- 增加原子 `instance init`、严格 `instance validate`、非秘密 `instance inspect` 和显式 `instance relock`。
- 锁定Factory源修订、dirty状态、契约摘要、团队包版本、配置摘要和生成文件摘要。
- 区分Factory-managed与user-seeded文件，并阻止已有路径覆盖、路径穿越、初始自治超过A2、取消人工生产批准及常见秘密写入。
- 增加实例管理Skill、端到端CLI测试和干净克隆中的确定性双实例对比。

兼容性：保留 `v0.1.0` 的 `doctor`、`validate`、`simulate`、`adopt-project` 和 `export-context` 命令。`v0.1.0` 没有团队实例格式，因此无需迁移现存实例。

限制：本版本尚未提供常驻持久控制平面、真实外部适配器执行或跨版本实例升级。所有外部适配器默认禁用。

回退：检出不可变标签 `v0.1.0` 即可恢复参考内核。`v0.2.0` 生成的实例不会被删除，但 `v0.1.0` 工具不能解释或运行它们。

## 0.1.0 — 2026-08-10

- 建立供应商中立契约、团队包、八个交付角色Skill、平台薄适配器、无副作用工作流模拟、现有项目只读接入和Git冷启动。
- 验证默认停在生产审批前，并覆盖作者自审、未批准生产、制品摘要不匹配、陈旧修订和提示注入等负例。
