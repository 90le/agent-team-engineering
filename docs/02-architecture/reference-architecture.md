# 参考架构

## 五层模型

1. 核心协议：工作项、任务信封、审核决定、测试证据、发布候选和审计事件。
2. 控制平面：确定性状态机、权限策略、租约、幂等、预算、重试和暂停。
3. 团队能力包：角色、Skill、工作流、风险分级和质量门禁。
4. 平台适配器：消息、代码托管、AI提供者、Runner和部署接口。
5. 项目与环境覆盖层：产品原则、实际架构、命令、基础设施和秘密引用。

v0.6在这五层之外提供“编译与采用入口”：Team Blueprint把2–5层的选择编译为一个Team Instance和平台原生覆盖层；Reference Runtime读取锁定蓝图并调用既有控制面，而不是创建第二套权限或工作流事实。

## 稳定接口

适配器只接收和产生 `schemas/` 定义的结构化对象。核心流程不认识 OpenClaw 会话、GitHub Label 或某个模型的专用消息格式；适配器负责映射。Manifest只描述契约，不能触发动态代码加载；宿主仅接受启动时显式注册且身份匹配的实现。操作级slot阻止同一多用途适配器跨信任入口复用权限，项目作用域把仓库、默认分支和Runner source ref限制在实例声明的目标内。

角色能力和工具权限只在团队包 JSON 中定义，参考控制器在运行时加载，不在模型提示词或代码中维护第二份权限事实。

模型路由也是适配器操作。任务信封绑定project、role、action、revision、上下文提交、能力与预算；结果必须匹配同一身份并通过Schema。Manifest entrypoint仍不会动态加载，Reference Runtime只显式注册确定性替身或CLI驱动。

## 状态与并发

每个工作项具有单调递增 `revision`。执行者必须提交 `expected_revision`；过期写入被拒绝。副作用必须携带幂等键，重试不能重复创建 Issue、PR 或部署。

## 上下文

所有角色使用同一个框架提交和项目提交，但只加载职责需要的文件。`tools/agent_team.py export-context` 可为无文件访问的 AI 生成带 SHA-256 的最小包。搜索与向量索引只能从这些源文件重建。

## 运行配置

参考模拟器、控制平面、适配器宿主和v0.5生命周期工具仅依赖Python标准库。控制平面使用SQLite事务保存工作项、幂等记录、租约、暂停状态、outbox和哈希链审计；该实现面向单实例与有限并发Worker，不宣称多节点高可用。未来替换持久引擎不得改变开放契约、修订检查和角色分离原则。OpenClaw是消息与协调适配器，不是默认安全边界。

控制平面先在一个事务中提交状态与待执行outbox记录，再由Worker领取外部副作用。Worker验证审计链，宿主再检查实例绑定、操作Schema、持久事件授权和显式实现。进程在提交前中断时两者都不生效；提交后中断时outbox仍可恢复。外部写操作必须使用提供者幂等或重试前对账；无法安全处理不确定结果的操作只能at-most-once并转人工处置。

## Factory、实例与项目

Factory发布通用实现和迁移；实例锁定明确Factory版本，保存团队自己的非秘密配置和项目绑定；目标项目继续拥有产品事实与源码。实例只能通过适配器操作目标项目，不能把仓库写权限解释为合并或生产权限。

实例由 `.agent-team/instance.json` 声明，`.agent-team/instance.lock.json` 绑定Factory版本、源修订、契约摘要和生成文件摘要。Factory管理文件漂移时安全停止；用户维护文件允许自定义但会报告差异。详细决定见 [ADR-0003](../adr/ADR-0003-factory-instance-project-boundaries.md)。

Factory发布可安装为不含Git元数据的验证副本，`.factory-installation.json` 绑定发布提交、annotated tag、文件模式、逐文件与整树摘要。实例版本迁移使用外部计划和恢复包；managed内容逐文件切换，目标锁最后提交，`runtime/.factory-lifecycle-journal.json` 使升级和回滚在中断后保守返回操作前版本。该模型提供逻辑提交与fail-closed，不宣称多文件物理原子性，也不负责停止外部Writer。

已有项目发现是独立的只读输入边界：扫描禁用Git optional locks，输出只能在目标仓库外原子发布。摘要绑定的proposal-only包可以组合到候选实例配置，但不能自行改变目标仓库、启用适配器或获得外部权限。

Team Runtime在方案批准后为writer创建独立Git worktree；source仓库必须干净。规格、workspace、commit、Draft PR、Runner Evidence和review分别持久化，崩溃后按当前revision与outbox继续。local/reference模式无网络外部写入；live与GitHub provider分别授权。协调器只到`REVIEW_APPROVED`，不会进入通用状态机后续的staging/production状态。

持久状态与恢复决定见 [ADR-0004](../adr/ADR-0004-sqlite-control-plane-and-outbox.md)，适配器和认证批准决定见 [ADR-0005](../adr/ADR-0005-versioned-adapter-host-and-bound-approval.md)，安装与事务化实例生命周期见 [ADR-0006](../adr/ADR-0006-verified-install-and-transactional-instance-lifecycle.md)，团队编译与参考运行时见 [ADR-0007](../adr/ADR-0007-team-blueprint-compiler-and-governed-reference-runtime.md)。

决策依据见[架构决策索引](../adr/README.md)。
