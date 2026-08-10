# ADR-0007：团队蓝图编译器与受治理参考运行时

- 状态：Accepted
- 日期：2026-08-10
- 决策范围：Factory `0.6.0`

## 背景

已有版本具备角色、Skill、状态机、SQLite、outbox、人工批准和适配器契约，但使用者仍需自行把这些零件翻译成 OpenClaw、Codex、Claude 或其他 AI 的配置，也没有一条可执行路径证明“反馈到经审核 Draft PR”真的闭环。仅提供架构文档会让使用者误以为仓库已经是一支运行中的团队，或反过来误以为它只是一套提示词。

## 决策

Factory 增加两个相互分离但由同一蓝图约束的产品层：

1. `team create` 把严格、无秘密的团队蓝图编译为一个版本锁定的 Team Instance，并生成 OpenClaw、Codex、Claude 与 Generic AI 的原生覆盖层。编译输出只写入不存在的新目录，逐文件摘要进入 `team.lock.json`，任何漂移都使验证失败。
2. `team run` 提供可重启的参考协调器。它复用 SQLite、修订、租约、outbox、适配器宿主和审计链，执行反馈规范化、Agent 分析、规格、人工批准、隔离 worktree 开发、Draft PR、声明式测试和独立复核，并固定停止在 `REVIEW_APPROVED`。它没有 merge 或生产部署子命令。

运行时分为两种模型模式和两种交付模式：

- `reference` 使用无网络、确定性的模型替身，用于冷启动、验收和教学；
- `live` 通过显式注册的路由器调用本机 Codex 或 Claude CLI，不动态加载 Manifest entrypoint；
- `local` 只产生本地 Issue/Draft PR 证据；
- `github` 只有同时启用实例绑定并传入 `--allow-provider-writes` 时，才允许创建 GitHub Issue、推送隔离分支和创建 Draft PR。

人工计划批准不接受 Agent 消息或普通聊天文本。CLI 要求操作者回填规格的完整 SHA-256，并用短期断言绑定 owner、动作、工作项、revision 和 evidence。该本地方式只把操作系统账号视为身份边界；远程审批必须替换为真实认证适配器。

测试命令由 Team Instance 外的严格 Runner Profile 声明，以 argv 数组直接执行，不经过 Shell，不继承凭据环境，并需要单独的 `--allow-host-runner`。本机 Runner 只是显式参考执行器，不等价于容器、VM 或微虚拟机隔离；不可信第三方代码必须使用满足 `execution-request` 契约的外部沙箱。

## 平台含义

- Codex 与 Claude 既有可安装的原生角色配置，也有参考运行时的直接 CLI 驱动。
- OpenClaw 获得隔离 workspace、Agent 列表、ACP 角色映射和空 bindings 的安全配置片段；频道、账号和审批身份必须在目标 OpenClaw 实例中单独接入。参考协调器不伪装成 OpenClaw Gateway。
- Generic AI 使用结构化任务/结果信封与逐角色 Markdown，可由其他 AI 或自建框架实现相同接口。

## 后果

优点：

- 使用者可以从一份蓝图重复生成跨平台团队，而不是复制一组易漂移提示词；
- 干净设备可以在没有聊天记忆、账号或网络写入的情况下重放完整人机门禁；
- live 模式与 provider 写入分别授权，模型能力不能隐式获得 GitHub 权限；
- 作者、QA、reviewer 身份和证据在持久状态中可检查。

代价与限制：

- v0.6 不是常驻队列守护进程、OpenClaw 插件、分布式调度器或高可用控制面；采用者需要为长期运行增加受监管服务封装；
- Codex/Claude 本机 CLI 的认证与进程隔离属于采用环境责任，不能把参考运行时当作处理恶意仓库的生产沙箱；
- 自动化最终停在 Draft PR 后的独立复核，merge 与上线仍由目标项目自己的保护规则和人工权限负责；
- 现有 Team Instance 升级到 v0.6 只更新 Factory 管理文件，不会自动启用模型、GitHub 或 Runner。

## 被否决方案

- 只发布角色提示词：不能提供持久状态、权限、恢复或可执行验收。
- 把所有平台逻辑写进核心：会破坏供应商中立与可迁移性。
- 让模型文本代表批准：无法证明人工身份、批准范围和 revision。
- 默认启用 GitHub 与本机命令：会把示例配置变成真实副作用和代码执行入口。
- 在 Factory 内实现自动 merge/生产部署：超出 A2 边界，也无法替代目标仓库与基础设施的独立保护。
