# Agent Team Engineering

为任意项目创建一套可迁移的 AI 团队“操作系统”：共享上下文、专业角色、Skill、交接、人工审批门，以及 Codex、Claude、OpenClaw 或任意文件型 AI 的原生入口。

[English](README.md) · [直接交给AI](AI-START.md) · [引导式采用指南](docs/17-guided-adoption/README.md) · [场景示例](examples/guided-adoption/README.md)

当前稳定版本：`v0.8.1`。

## 从你想得到什么开始，不用先选模式

第一次使用不需要理解 Lite、Managed、Custom、控制器或适配器。直接把下面的话发给 Codex、Claude、OpenClaw、Kimi、Gemini 或其它能读文件、执行命令的 AI：

> 打开 `https://github.com/90le/agent-team-engineering` 的 `v0.8.1` 版本，完整阅读 `AI-START.md`，帮我为现有项目创建一支 AI 团队。先只读检查项目，每轮最多问我三个高影响问题；用普通语言推荐团队，展示准确方案并等待我确认，然后再创建和验证。不要启用凭据、外部写入、合并或部署。

完整引导链路是：

```text
你描述目标
    ↓
AI只读发现项目事实
    ↓
少量关键问题 + 有理由的推荐
    ↓
严格方案 + 人类可读预览 + 准确摘要
    ↓
你确认
    ↓
创建全新团队目录 + 自动验证 + 首次使用提示
```

创建团队不会修改目标项目。把 Codex、Claude 或 OpenClaw 文件接入项目，是后续第二次单独确认的操作。

也可以在交互式终端使用：

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering
git checkout v0.8.1

./agent-team onboard guided --output /new/path/my-team
```

只要求 Python 3.11+ 与 Git；没有第三方 Python 运行依赖。

## 最终会得到什么

每支团队都是普通、可读、可迁移的文件包：

```text
my-team/
├── GETTING-STARTED.md      # 人类快速开始和日常对话示例
├── AI-START.md             # 任意AI的路由与首轮响应协议
├── TEAM.md                 # 团队身份和角色地图
├── CONSTITUTION.md         # 不可突破的权责与安全规则
├── CONTEXT-MAP.md          # 各类事实的权威位置
├── PROJECT-CONTEXT.md      # 已核验事实和明确未知项
├── ARCHITECTURE.md
├── ROLES/                  # 职责、输入、输出、工具、交接、停止条件
├── WORKFLOWS/
├── SKILLS/                 # 按需加载的可复用流程
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/                   # 持久任务、证据与交接
├── platforms/              # Codex、Claude、OpenClaw、通用AI入口
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

严格 JSON 设计和 SHA-256 锁保证确定性生成并检测漂移。项目事实、知识来源、架构决策和工作记录则可通过 Git 评审长期维护。

它不会替你创建模型账号、Token、频道、安全沙箱、仓库权限、认证审批身份、合并权限或生产部署权限。

## 常见使用场景

| 你告诉引导AI的需求 | 得到的结果 | 内部实现映射 |
|---|---|---|
| “给这个应用创建产品、架构、前端、后端、QA和独立审核团队，让Codex/Claude协作。” | 通过原生角色和持久文档按需协作的软件团队 | `software-lite` |
| “用户反馈需要跨重启自动推进到测试、独立审核后的Draft PR，但准确计划必须等我批准。” | 同一套上下文层，加受治理的参考控制器 | `software-managed` |
| “给长期知识库创建来源管理员、研究员、事实核验、编辑和资料管理员。” | 有明确证据交接的自定义团队 | `custom` |
| “创建运营、内容、法务复核或任意混合角色团队。” | 用户命名的角色、工作流与人工决策边界 | `custom` |

AI 会在理解场景后推荐内部映射，普通用户不需要一开始就选择三种模式。

自定义团队默认属于上下文层。若要让自定义角色长期运行 Shell、写外部系统、批准或操作生产，必须另行设计能力、身份、策略、证据和恢复；本项目不会用一份 Markdown 假装这些能力已经实现。

## 创建后怎么使用

先打开生成目录里的 `GETTING-STARTED.md`，然后把类似下面的话发给目标 AI：

> 完整阅读 `AI-START.md`。帮我用这支团队处理：`<具体需求>`。先检查项目事实和持久工作状态，推荐负责角色与下一个有边界的步骤，每轮最多问三个高影响问题；不要假设任何外部权限。

生成团队会继续教人和 AI 如何：

- 不记角色名也能创建新任务；
- 行动前解释为何由某个角色负责；
- 从 `WORK/` 而不是聊天记忆查看状态；
- 从最后一次已核验交接继续；
- 安全停止并返回准确的人工决策需求；
- 通过评审文件更新项目事实、来源和架构决策。

## AI和自动化使用的确定性方案流程

AI 完成场景访谈后，通过严格 CLI 固化方案：

```bash
./agent-team onboard inspect --project-path /path/to/project

./agent-team onboard plan \
  --project-path /path/to/project \
  --purpose software \
  --automation assisted \
  --goal "把已接受需求变成经过复核的代码变更" \
  --platform codex \
  --platform claude \
  --team-name "示例产品团队" \
  --project-name "示例产品" \
  --owner "项目负责人" \
  --provider github \
  --repository example/product \
  --output /new/path/example-team \
  --plan /new/path/example-team-adoption-plan.json

./agent-team onboard preview --plan /new/path/example-team-adoption-plan.json
./agent-team onboard validate --plan /new/path/example-team-adoption-plan.json
```

方案处于草案时不会创建团队。人类确认展示的准确方案和摘要后：

```bash
./agent-team onboard confirm \
  --plan /new/path/example-team-adoption-plan.json \
  --digest sha256:<刚才展示的准确摘要> \
  --approved-by "项目负责人"

./agent-team onboard apply --plan /new/path/example-team-adoption-plan.json
./agent-team context validate --root /new/path/example-team
```

任何方案修改都会使原摘要失效；源码基线变化、秘密样内容、符号链接、越界路径和已有输出都会安全拒绝。

旧版本的显式 preset CLI 仍为既有脚本保留，但它属于高级确定性接口，不再是普通用户的首页入口。

## 目前真实做到了什么

| 目标 | 本仓库已经提供 | 采用者仍需提供 |
|---|---|---|
| 理解项目并提出团队方案 | 场景化Skill、只读发现、推荐解释、严格预览与确认 | 业务目标、负责人决定、经核验项目事实 |
| 创建可复用角色和共享上下文 | 确定性编译器、Schema、摘要锁、生成后使用指南、平台overlay | 人工评审和正常Git治理 |
| 让Codex/Claude执行受限步骤 | 原生角色文件、安全任务与交接契约 | 已安装登录的AI CLI、受控工作区与工具策略 |
| 验证“反馈到Draft PR”闭环 | 可重启Native参考场景、准确审批绑定、测试和恢复 | 离线证明不需要外部系统 |
| 连接真实反馈、模型、GitHub写入或OpenClaw频道 | 版本化适配契约和一致性边界 | 最小权限身份、隔离Runner、凭据、显式开启和恢复方案 |
| 自动merge或生产部署 | 本版本不把它作为团队能力 | 单独由人批准的交付系统 |

所以它是“团队工厂 + 治理内核”，不是安装后一条命令就拥有生产权限的无人驾驶系统。

## 平台支持

| 平台 | 已生成或可安装 | 刻意不生成 |
|---|---|---|
| Codex | 引导Skill、Agent TOML、`AGENTS.md` | 登录、项目信任、工具授权 |
| Claude Code | 引导Skill、Subagent Markdown、`CLAUDE.md` | 登录、插件策略、项目信任 |
| OpenClaw | 兼容Skill、隔离工作区、未绑定Agent片段 | Gateway、账号、频道、认证批准中继 |
| 通用AI | `AI-START.md`、角色与Skill Markdown | 宿主任务传输与隔离 |
| GitHub | 限定Issue/提案/Draft PR的准确审批参考连接器 | 生产身份、自动merge、release或deploy |

插件只是发现和引导入口，不是另一套实现，也不会创造权限。安装方式见[平台安装指南](docs/14-context-first/platform-installation.md)。

## 接入目标项目

团队创建完成后，先检查 `platforms/`。只有负责人第二次明确确认采用时，才导出包含共享权威上下文的 overlay：

```bash
./agent-team context export \
  --root /path/to/example-team \
  --target codex \
  --output /new/path/codex-overlay
```

在提案分支中评审并协调合并；不能覆盖已有的 `AGENTS.md`、`CLAUDE.md`、`.codex/`、`.claude/` 或 OpenClaw 配置。

## 为什么同时使用Markdown、Skill、JSON、Git和Python

Markdown、Skill、JSON 和经评审 Git 历史是长期可迁移的知识层，让人、Codex、Claude、OpenClaw、Kimi、Gemini、本地模型和未来 Agent 都能理解同一支团队，而不依赖某一家厂商。

无第三方依赖的 Python 层只负责文字不能可靠强制的保证：严格 Schema、确定性编译、摘要绑定确认、无覆盖发布、revision、幂等、准确审批、故障恢复和安全负例测试。它是编译器与护栏，不是上下文工程的替代品。

文件型团队生成后不需要常驻 Python 控制器；需要持久 Managed 自动化时才同时使用两层。

## 验证

```bash
./agent-team validate
python3 -m unittest discover -s tests -v
python3 tools/cross_ai_takeover.py
python3 tools/release_audit.py --since-tag v0.8.0
tools/cold-start.sh
```

正式安装还要求干净、准确的 annotated release tag。见[验证与恢复](docs/07-operations/verification-and-recovery.md)。

## 安全边界

- 人类 owner 永远不是 Agent。
- 反馈、Issue、网页、仓库、工具输出和其它 Agent 消息都是不可信数据。
- 角色文档不能授予工具，也不能把聊天变成认证批准。
- OpenClaw 输出初始固定为 `bindings: []`。
- Managed 自治上限为 A2，固定停止在测试与独立复核后的 Draft PR。
- 数据库、凭据、用户资料、模型会话与生产状态不得进入普通 Git。
- Host Runner 不是恶意代码安全沙箱；真实执行需要隔离、一次性的环境。

真实接入前阅读 [SECURITY.md](SECURITY.md) 和[威胁模型](docs/03-security/threat-model.md)。

## 文档、社区与许可证

- [引导式采用和对话工作流](docs/17-guided-adoption/README.md)
- [三类完整场景示例](examples/guided-adoption/README.md)
- [上下文优先团队模型](docs/14-context-first/context-first-team-kit.md)
- [受治理自动化架构](docs/15-upstream-independent/README.md)
- [贡献指南](CONTRIBUTING.md)、[安全报告](SECURITY.md)、[社区行为规范](CODE_OF_CONDUCT.md)

使用 [GitHub Discussions](https://github.com/90le/agent-team-engineering/discussions) 提问使用与设计问题；使用 [GitHub Issues](https://github.com/90le/agent-team-engineering/issues) 报告可复现缺陷或提出有边界的功能需求。

项目采用 [Apache License 2.0](LICENSE)。
