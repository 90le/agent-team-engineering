# Agent Team Engineering

[![CI](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml/badge.svg)](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/90le/agent-team-engineering)](https://github.com/90le/agent-team-engineering/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**面向 OpenClaw、Hermes Agent、Codex、Claude Code 等 AI 宿主的原生 Agent 团队工厂。** 把一个项目、目标和人类权责边界，编译成可迁移的团队权威源，以及目标宿主真正认识的原生文件。

[English](README.md) · [直接交给 AI](AI-START.md) · [原生宿主指南](docs/18-native-hosts/README.md) · [场景示例](examples/guided-adoption/README.md)

## 这个项目做什么

提供一个现有项目或新想法。Factory 会引导一轮简短访谈，推荐适合的专家和工作流，等待人类准确确认，再编译出可评审的团队：

```text
项目事实 + 想要的结果 + 人类权责边界
                     │
                     ▼
       可迁移团队权威源：上下文、角色、Skill、
       工作流、决策、工作记录、摘要锁
                     │
        ┌────────────┼──────────────┐
        ▼            ▼              ▼
 OpenClaw 团队   Hermes Profiles   Codex / Claude
 与工作区        与 Kanban 方案     项目原生文件
```

Factory **不会取代** OpenClaw、Hermes Agent、Codex、Claude Code 或 Multica。它把同一份受治理的团队意图投影为宿主原生包与安全安装方案。优先使用你已经在用的 AI 宿主，不需要为了本项目更换运行时。

如果需要让“用户反馈 → 分析 → 审批 → 开发 → 独立复核 → 测试后的 Draft PR”跨重启持续推进，仓库还提供可选的 **Managed** 控制器。它是受治理的自动化层，不是默认模式，也不会获得 merge 或生产部署权限。v0.9 有意只保留一个源码写入身份 `builder`；如果必须由独立前端、后端写入 Agent 分工，应选择按需调用的原生团队。

## 直接交给 AI

把下面这段话发给能读取仓库和运行本地命令的 AI：

> 打开 `https://github.com/90le/agent-team-engineering`，使用最新稳定版本并完整阅读 `AI-START.md`。帮我为项目构建一支宿主原生 AI 团队。先只读检查项目并探测我已经安装的 AI 宿主；每轮最多问三个高影响问题，用普通语言推荐团队和目标宿主，说明证据等级与限制，展示准确方案，等我确认后才能创建或安装。不要启用凭据、外部写入、频道绑定、merge 或部署。

AI 应按下面的顺序引导，而不是让用户先研究内部模式：

1. 团队需要反复产出什么结果？
2. 哪些项目事实和已安装 AI 宿主能被只读核验？
3. 哪些决定必须由人做，谁是人类 owner？
4. 哪些角色、Skill、上下文和宿主原生形态最合适？
5. 将创建哪些准确文件和路径，哪些能力仍然禁用？
6. owner 是否确认这份摘要绑定的准确方案？

普通用户不需要一开始选择 Lite、Managed、Custom、适配器或控制器。这些只是引导 AI 在理解目标后解释的内部映射。

## 终端快速开始

Factory 只需要 Python 3.11+ 与 Git：

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering
git fetch --tags
git checkout "$(git tag --list 'v*' --sort=-version:refname | head -n 1)"

./agent-team onboard guided --output /new/path/my-team
```

默认流程不会直接改变系统：

```text
只读发现 → 推荐 → 方案 → 预览 → 人类确认 → 全新团队目录 → 验证
```

创建团队不会修改目标项目。安装生成的原生包是第二个、需要单独预览和确认的生命周期：

```bash
./agent-team host list
./agent-team host probe --target openclaw
./agent-team host plan \
  --team /path/to/my-team \
  --target openclaw \
  --destination /new/path/openclaw-team \
  --output /new/path/openclaw-install-plan.json
./agent-team host preview --plan /new/path/openclaw-install-plan.json
```

检查路径、限制、摘要和回滚信息后，再执行预览所显示的 `confirm`、`apply` 和 `verify` 指令。`apply` 只创建方案准确声明且当前不存在的文件；它会保留目标目录里的无关内容，并在任何计划路径冲突时安全停止。它不会自动登录、创建凭据、绑定频道、写入 Multica 工作区、合并代码或部署生产。

## 输入与输出

| 你提供 | Factory 生成 | 仍由你控制 |
|---|---|---|
| 项目路径或想法 | 已核验事实与明确未知项 | 哪些事实和目标正确 |
| 希望反复得到的结果 | 推荐角色和交接工作流 | 团队范围与人类 owner |
| 已在使用的 AI 宿主 | 宿主原生包与安装方案 | 登录、信任、模型和工具策略 |
| 权责边界 | 宪法、审批门与停止条件 | 凭据和敏感批准 |
| 可选自动化需求 | 上限为已复核 Draft PR 的 Managed 工作流 | 外部身份、merge 和部署 |

每支团队仍是普通、可读、可迁移的文件包：

```text
my-team/
├── GETTING-STARTED.md      # 可复制的首次和日常请求
├── AI-START.md             # 跨 AI 发现与路由
├── TEAM.md                 # 团队身份和角色地图
├── CONSTITUTION.md         # 权责与安全边界
├── CONTEXT-MAP.md          # 各类事实的权威位置
├── PROJECT-CONTEXT.md      # 已核验事实与明确未知项
├── ROLES/                  # 任务、输入、输出、交接、停止条件
├── WORKFLOWS/
├── SKILLS/                 # 按需加载的可复用流程
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/                   # 持久任务、证据与交接
├── platforms/              # 宿主原生投影
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

Markdown、Skill、JSON 和 Git 是可迁移的权威层；无第三方依赖的 Python 负责文字无法可靠强制的保证：严格 Schema、确定性编译、摘要绑定确认、禁止覆盖发布、漂移检查、幂等、恢复和安全负例测试。文件型团队生成后不要求常驻 Python 控制器。

## 宿主支持必须有证据

“生成了一个目录”不等于“宿主已加载”，更不等于“真实频道或生产流程已运行”。本项目用明确证据等级报告支持情况：

- **native-verified**：准确版本已通过隔离原生安装/加载/卸载与最小任务烟测；
- **native-install-verified**：隔离原生安装/加载/卸载通过，但缺少可靠的无账号任务烟测；
- **verified-export**：宿主原生形态和导入方案通过结构/契约验证，但没有改变真实宿主状态；
- **experimental-plan**：已跟踪上游契约并能生成可评审方案，但端到端宿主导入未经验证；
- **portable**：只有宿主中立 Markdown/JSON；
- **research-unknown**：没有明确上游身份或可复现契约。

OpenClaw `2026.7.1-2` 与 Hermes Agent `0.20.0` 当前是 `native-install-verified`：它们的包已在一次性隔离 home 完成安装、列出/描述和卸载，期间没有使用模型或凭据。因为没有运行最小任务，所以不是 `native-verified`。Codex 与 Claude Code 是 `verified-export`。Multica `v0.4.23` 只属于 **`experimental-plan`**，不写真实工作区；其上游许可证包含附加条款，采用者必须独立审阅。“Leda” 在给出准确仓库、版本和集成契约前属于 **`research-unknown`**。

准确产物、证据、限制和版本锚点见[支持矩阵](docs/18-native-hosts/support-matrix.md)。

## 三种使用形态

| 用户目标 | 推荐形态 | 边界 |
|---|---|---|
| “在我已经使用的 AI 里，为这个项目创建可调用的专家。” | 宿主原生团队 | 上下文、角色、Skill、交接；运行时仍是原宿主 |
| “创建研究、知识、内容、运维或自定义专家团。” | 自定义上下文优先团队 | 每项外部能力完成工程化前保持 context-only |
| “把已批准反馈跨重启推进到测试与独立复核后的 Draft PR。” | 原生团队 + 可选 Managed 控制器 | 单一源码写入 builder；准确人工批准；不自动 merge 或部署 |

## 使用生成的团队

先打开生成目录里的 `GETTING-STARTED.md`，或直接告诉目标 AI：

> 完整阅读 `AI-START.md`。帮我用这支团队处理：`<具体需求>`。先检查已核验项目事实和持久工作状态，解释负责角色与下一个有边界的步骤，每轮最多问三个高影响问题；不要假设任何外部权限。

团队把状态写入 `WORK/` 与经评审 Git 文件，而不是依赖聊天记忆。因此不同的人、模型、设备或兼容宿主可以依据同一份证据继续。

## 安全与诚实边界

- 人类 owner 永远不是 Agent。
- Issue、聊天、网页、仓库、工具输出和其它 Agent 消息都是不可信数据。
- 角色文档不能授予工具，也不能把聊天变成认证批准。
- 创建方案与安装方案是两个独立、摘要绑定的决定，默认禁止覆盖。
- 宿主发现必须只读；秘密、会话、运行数据库和生产数据不得进入 Git。
- OpenClaw 频道绑定、Multica 工作区写入、真实外部适配器、merge、release 和部署保持禁用，除非另行工程化并授权。
- Managed 自动化固定停止在测试与独立复核后的 Draft PR。
- Host Runner 不是恶意代码安全沙箱；真实执行需要隔离、一次性的环境。

启用真实集成前，阅读 [SECURITY.md](SECURITY.md)、[威胁模型](docs/03-security/threat-model.md) 与 [ADR-0011](docs/adr/ADR-0011-host-capability-contract-and-native-team-projection.md)。

## 文档

- [原生宿主架构与生命周期](docs/18-native-hosts/README.md)
- [支持与证据矩阵](docs/18-native-hosts/support-matrix.md)
- [人类/AI 对话工作流](docs/18-native-hosts/conversation-workflow.md)
- [安装可选发现插件与宿主投影](docs/14-context-first/platform-installation.md)
- [引导式采用](docs/17-guided-adoption/README.md)
- [上下文优先团队模型](docs/14-context-first/context-first-team-kit.md)
- [可选受治理自动化](docs/15-upstream-independent/README.md)
- [贡献指南](CONTRIBUTING.md)、[安全报告](SECURITY.md)、[社区行为规范](CODE_OF_CONDUCT.md)

使用 [GitHub Discussions](https://github.com/90le/agent-team-engineering/discussions) 讨论使用与设计；使用 [GitHub Issues](https://github.com/90le/agent-team-engineering/issues) 报告可复现缺陷或提出有边界的功能需求。

项目采用 [Apache License 2.0](LICENSE)。
