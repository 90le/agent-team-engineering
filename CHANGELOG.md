# Changelog

本项目遵循语义化版本。版本标签只在仓库验证、测试、Skill校验和空目录冷启动全部通过后创建；已发布标签不移动。

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
