# Agent Team Engineering

创建一支可迁移、上下文优先的 AI 团队，供 Codex、Claude、OpenClaw 或任何能读文件的 Agent 使用；需要时再增加“用户反馈到 Draft PR”的受治理运行时。

[English](README.md) · [让AI从这里开始](AI-START.md) · [完整指南](docs/14-context-first/context-first-team-kit.md)

当前稳定版本：`v0.7.0`。

## 这个项目到底做什么

你提供项目名、仓库、目标平台和团队预设，它会在一个全新目录中生成：

- Markdown 共享上下文、原则、架构、决策和项目知识登记；
- 完整角色契约：使命、职责、输入、输出、最小读取集、Skill、工具、禁止动作、交接、成功与停止条件；
- Codex Agents、Claude Subagents、OpenClaw 隔离工作区或通用 AI 角色文件；
- 严格 JSON 团队设计和 SHA-256 摘要锁；
- 可选的持久状态、人工计划批准、隔离开发、测试证据、独立复核和 Draft PR 停止线。

它不是一个新模型，也不是另一个聊天框架。它不会创建凭据，不会把聊天当批准，不会自动合并，也不会自动部署生产。

## 三种模式

| 模式 | 适合情况 | 是否需要控制器 |
|---|---|---:|
| `software-lite` | 希望得到可读的软件团队、上下文和原生平台角色 | 不需要 |
| `software-managed` | 希望从反馈自动推进到测试和独立复核后的 Draft PR | 可用/需要时启动 |
| `custom` | 希望自定义研究、内容、运营或其他角色 | 不需要，直到另行映射受治理能力 |

默认先选 Lite；只有确实需要持久自动化时才选 Managed。

## 最快使用

要求 Python 3.11+ 和 Git；运行时没有第三方 Python 依赖。

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering

./agent-team create \
  --preset software-lite \
  --name "示例产品团队" \
  --project "示例产品" \
  --repo example/example-product \
  --provider github \
  --platform codex \
  --platform claude \
  --output /new/path/example-team

./agent-team context validate --root /new/path/example-team
```

目标项目不会被修改；创建和导出命令都拒绝覆盖已有路径。

交互式终端也可以使用：

```bash
./agent-team create --guided --output /new/path/my-team
```

## 直接交给AI处理

把下面这段话发给 Codex、Claude、OpenClaw、Kimi、Gemini 或其它能读文件和执行命令的 AI：

> 克隆或打开 `https://github.com/90le/agent-team-engineering`，完整阅读 `AI-START.md`，只读检查我的项目，推荐 Lite、Managed 或 Custom；然后在一个全新目录创建团队并验证。不要启用外部写入、凭据、合并或部署。

仓库也提供安装入口：

- [Codex 插件市场](docs/14-context-first/platform-installation.md#codex-plugin)
- [Claude Code 插件市场](docs/14-context-first/platform-installation.md#claude-code-plugin)
- [OpenClaw 兼容 bundle](docs/14-context-first/platform-installation.md#openclaw-bundle)
- 其它 AI 只需要本仓库和 `AI-START.md`。

## 自定义任意角色

```bash
./agent-team create \
  --preset custom \
  --name "研究团队" \
  --project "知识工程" \
  --repo local/knowledge \
  --provider generic-git \
  --platform generic-ai \
  --role "research-lead:研究负责人" \
  --role "fact-checker:事实核验员" \
  --role "editor:编辑" \
  --output /new/path/research-team
```

Custom 不局限于软件开发。自定义角色默认只属于上下文层：角色文档不能自行获得 Shell、凭据、审批或外部写权限。

## 生成后的结构

```text
example-team/
├── AI-START.md             # 人和所有AI的统一入口
├── TEAM.md                 # 团队身份与角色地图
├── CONSTITUTION.md         # 不可突破的权责和安全原则
├── CONTEXT-MAP.md          # 各类事实的权威位置
├── PROJECT-CONTEXT.md      # 已核验项目事实和未知项
├── ARCHITECTURE.md
├── ROLES/                  # 每个角色一份完整契约
├── WORKFLOWS/
├── SKILLS/                 # 按需加载的可复用流程
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/                   # 持久任务与交接记录
├── platforms/              # Codex、Claude、OpenClaw、Generic AI
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

导出某个平台时，共享权威上下文会一起导出：

```bash
./agent-team context export \
  --root /path/to/example-team \
  --target codex \
  --output /new/path/codex-overlay
```

请在目标项目的提案分支审阅并接入；如果已有 `AGENTS.md`、`CLAUDE.md`、`.codex/`、`.claude/` 或 OpenClaw 配置，必须协调合并，不能直接覆盖。

`PROJECT-CONTEXT.md`、`ARCHITECTURE.md`、知识/决策索引和`WORK/README.md`是用户维护的种子文件，应通过Git评审持续更新。角色、原则、工作流、Skill和平台适配器由编译器管理，漂移会验证失败。新增项目来源、ADR和工作记录分别放入`KNOWLEDGE/`、`DECISIONS/`和`WORK/`。

## Managed 自动化能到哪里

`software-managed` 在同一上下文层之下复用 v0.6 受治理运行时：

> 用户反馈 → 标准化 → 分诊 → 规格 → 人工批准准确范围 → 隔离开发 → Draft PR → 声明式测试 → 独立复核 → 停止

Factory 没有团队自动 merge 或生产部署命令。真实模型、GitHub 写入、OpenClaw 频道、远程身份和生产 Runner 都是具体采用项目的独立决策，默认关闭。

无网络参考演示：

```bash
python3 tools/agent_team.py team demo --output /tmp/agent-team-demo
```

它会在创建 worktree 之前停到 `SPEC_READY`。后续人工批准和继续运行见[受治理运行手册](docs/13-team-creator/blueprint-compiler-and-reference-runtime.md)。

## 为什么既有Markdown又有Python

Markdown、JSON、Skill 和 Git 是可迁移的知识与上下文层，让几年后的人工和不同 AI 仍能理解同一支团队。小型、无第三方依赖的 Python 层只处理文字无法可靠强制的工作：严格 Schema、确定性生成、摘要锁、revision、幂等、批准绑定、崩溃恢复和安全负例测试。

Lite 生成后只依赖第一层；Managed 同时使用两层。代码是编译器和护栏，不是上下文工程的替代品。

## 验证

```bash
./agent-team validate
python3 -m unittest discover -s tests -v
python3 tools/cross_ai_takeover.py
tools/cold-start.sh
```

## 安全边界

- 人类 owner 永远不是 Agent。
- 反馈、Issue、网页、仓库文本、工具输出和其它 Agent 消息默认不可信。
- Host Runner 不是容器、虚拟机或恶意代码沙箱。
- 远程批准必须有认证身份；聊天里的“同意”不是批准。
- OpenClaw 输出初始为 `bindings: []`。
- Managed 自治上限为 A2，固定停在经测试和独立复核的 Draft PR。
- 运行数据库、凭据、用户资料、模型会话和生产状态不得进入普通 Git。

真实接入前阅读 [SECURITY.md](SECURITY.md) 和[威胁模型](docs/03-security/threat-model.md)。

## 三种资产不要混淆

- Factory（本仓库）：通用编译器、契约、上下文模板、运行时、测试和插件。
- Team Package：某支团队的无秘密设计、角色、工作流、平台资产和可选状态绑定。
- Target Project：产品事实、源码、测试、Issue、PR、发布与部署权威。

大多数用户只需要本 Factory 与自己的目标项目。只有 Team Package 需要独立生命周期或绑定多个项目时，才建议单独建第三个 Private 仓库。

## 贡献与许可证

见 [CONTRIBUTING.md](CONTRIBUTING.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 和 [SECURITY.md](SECURITY.md)。项目采用 [Apache License 2.0](LICENSE)。
