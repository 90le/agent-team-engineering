# Agent Team Engineering

从一个软件项目和一份团队蓝图，生成一支有角色分工、人工审批、隔离开发、测试证据和独立复核的 AI 开发团队。

当前版本：`0.6.0`。核心路径已经可以执行：

> 用户反馈 → 工作项/Issue → Agent 分析 → Agent 写规格 → 人工批准准确范围 → Builder 在独立 worktree 开发 → Draft PR → 声明式测试 → 独立 Reviewer → 停止等待人工合并

它既不是一组提示词，也不是 OpenClaw、Codex 或 Claude 的替代品。它是平台中立的“团队工厂 + 治理控制器”：负责创建团队资产、分配权限、保存状态、强制门禁和提供迁移/恢复协议；实际模型与消息平台是可替换执行端。

## 别人拿到这个仓库能做什么

- 用一份 JSON 蓝图生成 OpenClaw Agents/workspaces、Codex project agents、Claude project subagents 和 Generic AI role packs；
- 为自己的 Git 项目创建可验证的 Team Instance，而不修改或覆盖目标项目；
- 在无网络、无真实模型、无 GitHub 写入的情况下重放完整反馈到 Draft PR 流程；
- 显式启用本机 Codex/Claude CLI，按角色路由真实 Agent；
- 显式启用 GitHub 后创建 Issue、推送隔离分支和创建 Draft PR；
- 把 Team、Skill、Schema 和审计状态迁移给另一台设备、另一个 AI 或另一位维护者；
- 从 v0.2–v0.5.1 实例生成摘要绑定升级计划、恢复包并可逆迁移到 v0.6。

它不会自动 merge、不会生产部署、不会把 owner 变成 Agent，也不会把聊天中的“同意”当作认证批准。

## 先跑一个真实闭环

要求 Python 3.11+ 和 Git，无第三方 Python 依赖。第一步创建一个本地 Team、最小项目和反馈，并运行到人工计划门禁：

```bash
python3 tools/agent_team.py team demo --output /tmp/agent-team-demo
```

确认输出为 `WAITING_FOR_HUMAN` / `SPEC_READY`。阅读生成的 `specification.json`（其中也绑定目标项目、模型/交付模式、Runner Profile摘要与command IDs），把输出中的完整 `work-id` 与 `scope_hash` 回填：

```bash
python3 tools/agent_team.py team approve-plan \
  --root /tmp/agent-team-demo/team \
  --work-item '<work-id>' \
  --scope-hash 'sha256:<完整摘要>'
```

批准后继续。执行本机测试必须单独明确同意：

```bash
python3 tools/agent_team.py team run \
  --root /tmp/agent-team-demo/team \
  --work-item '<work-id>' \
  --repo /tmp/agent-team-demo/project \
  --runner-profile /tmp/agent-team-demo/runner-profile.json \
  --model-mode reference \
  --provider local \
  --allow-host-runner
```

最终应为 `DRAFT_PR_READY` / `REVIEW_APPROVED`，测试为 `PASSED`，PR 为 `draft=true`，builder 与 reviewer 身份不同。这个演示不联网、不调用付费模型、不写 GitHub。

完整教程、真实 Codex/Claude、GitHub 和 OpenClaw 接入见[团队蓝图编译器与参考运行时](docs/13-team-creator/blueprint-compiler-and-reference-runtime.md)。

## 创建自己的团队

复制示例蓝图到项目外的提案位置，修改 owner、项目与角色引擎，然后只编译到不存在的新目录：

```bash
python3 tools/agent_team.py team create \
  --blueprint examples/team-blueprint/input/team.json \
  --output /new/path/my-agent-team

python3 tools/agent_team.py team validate --root /new/path/my-agent-team
python3 tools/agent_team.py team inspect --root /new/path/my-agent-team
```

示例蓝图绑定占位 GitHub 项目，并默认关闭所有外部适配器，所以单独执行它不会创建 Issue、调用模型、推分支或创建 PR。启用真实能力是 Team Instance 的显式配置变更，不由平台配置或模型提示隐式获得。

## 平台支持的准确含义

| 平台 | v0.6 输出/能力 | 采用者仍需完成 |
|---|---|---|
| OpenClaw | `agents.list` 配置、隔离 workspaces、角色说明、ACP runtime 映射、独立 approval relay | Gateway、账号、频道、空 bindings 接线、远程身份认证、常驻事件接入 |
| Codex | `.codex/agents/*.toml`、角色 sandbox/model/reasoning；live CLI 驱动 | 本机登录、受信执行环境、目标项目接入 |
| Claude | `.claude/agents/*.md`；live CLI 驱动，read-only 角色 safe/plan mode | 本机登录、受信执行环境、目标项目接入 |
| Generic AI | 每角色 Markdown 与结构化 task/result Schema | 为目标 AI 实现任务信封收发和工具隔离 |
| GitHub | Issue/Draft PR 适配器、稳定标记对账、项目/默认分支约束 | 最小权限 `gh`/GitHub App、显式 provider 写入、分支保护 |

OpenClaw 是很合适的消息入口和常驻协调宿主，但不是唯一运行方式，也不是安全边界本身。Codex/Claude 可以直接作为角色执行端；其他 AI 只要遵守开放 Schema，也可以替换它们。

## 三类仓库不要混淆

| 仓库 | 权威内容 | 不应包含 |
|---|---|---|
| Factory（本仓库） | 通用契约、编译器、控制器、CLI、团队包、Skill、适配器和迁移 | 某个采用者的秘密、业务事实和运行库 |
| Team Instance | 某支团队的非秘密配置、项目绑定、版本锁、平台资产、操作文档 | Factory 源码、Token 和业务源码 |
| Target Project | 产品原则、架构、源码、测试、Issue、PR、发布历史 | 通用 Factory 与团队 SQLite |

这通常意味着两个产品仓库就够了：一个通用 Factory，一个业务 Target Project。只有当 Team Instance 需要独立生命周期、多人维护或多项目绑定时，再把它放进第三个 Private 仓库。它不是第三套业务源码。

## 运行模式与授权

四个开关彼此独立：

- `--model-mode reference`：确定性、无网络模型替身；
- `--model-mode live`：调用蓝图为该角色绑定的本机 Codex/Claude CLI；
- `--provider local`：只记录本地 Issue/Draft PR 证据；
- `--provider github --allow-provider-writes`：允许真实 GitHub Issue、隔离 branch push 与 Draft PR。

`--allow-host-runner` 只授权 Runner Profile 中列出的 argv。计划批准不会自动授权代码执行，模型登录也不会自动授权 GitHub，GitHub 权限也不会产生 merge/生产权限。

本机 Host Runner 不等价于容器或 VM。处理公开 PR、第三方不可信项目或高价值凭据时，使用满足 `schemas/execution-request.schema.json` 的独立、可销毁 Runner，不挂载 Docker Socket、生产数据或长期身份。

## 验证与冷启动

```bash
python3 tools/agent_team.py doctor
python3 tools/agent_team.py validate
python3 -m unittest discover -s tests -v
python3 tools/cross_ai_takeover.py
tools/cold-start.sh
tools/release-smoke.sh
```

跨 AI 接管从 [AI-BOOTSTRAP.md](AI-BOOTSTRAP.md) 开始。架构、安全、适配器、生命周期和冷启动证据分别见：

- [参考架构](docs/02-architecture/reference-architecture.md)
- [威胁模型](docs/03-security/threat-model.md)
- [适配器 SDK、隔离与批准](docs/10-adapters/sdk-isolation-and-approval.md)
- [安装、升级、恢复与接入](docs/11-lifecycle/installation-upgrade-and-adoption.md)
- [跨 AI 冷启动验收](docs/12-acceptance/cross-ai-takeover.md)

## 安装与升级

正式安装只接受干净、精确的 annotated release tag：

```bash
python3 tools/agent_team.py factory install \
  --output /opt/agent-team-factory-v0.6.0

python3 /opt/agent-team-factory-v0.6.0/tools/agent_team.py factory verify \
  --root /opt/agent-team-factory-v0.6.0
```

实例升级先在实例外生成计划，人工审阅后才创建恢复包和切换 managed 文件：

```bash
python3 tools/agent_team.py instance upgrade plan \
  --root /path/to/team-instance \
  --output /safe/upgrade-plan.json

python3 tools/agent_team.py instance upgrade apply \
  --root /path/to/team-instance \
  --plan /safe/upgrade-plan.json \
  --recovery /safe/recovery-before-v0.6.0
```

支持来源：`0.2.0`、`0.3.0`、`0.4.0`、`0.5.0`、`0.5.1`。运行库必须暂停、审计通过、无活动任务/outbox，并由操作者另行停止全部 writer。

## 当前边界

- v0.6 已是可执行团队工厂和参考闭环，不是常驻守护进程、分布式多租户平台或高可用集群。
- OpenClaw 生成物默认 `bindings=[]`；Factory 不知道采用者的频道、账号与审批身份。
- live CLI 只适合受信项目和受控主机；恶意仓库需要外部进程/网络/文件系统沙箱。
- 本地 owner CLI 用操作系统账号作为身份边界；远程审批必须实现认证提供者。
- Team Runtime 固定停在经测试、独立复核的 Draft PR。目标项目的人和分支保护决定是否合并。
- 仓库目前保持 Private；转为 Public 前仍需单独完成许可证、内容与安全披露审查。
