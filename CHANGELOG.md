# Changelog

本项目遵循语义化版本。版本标签只在仓库验证、测试、Skill校验和空目录冷启动全部通过后创建；已发布标签不移动。

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
