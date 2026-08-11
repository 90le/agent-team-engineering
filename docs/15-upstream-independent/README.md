# v0.8 供应商中立核心

状态：`v0.8.0` 的 L1 参考实现。它是可发布、可安装、可验证的 Factory 核心，不是已经连接账号和生产仓库的无人值守开发公司。

本章是维护者和无历史聊天 AI 接手 v0.8 的最短入口。核心资产由 Markdown/JSON/Git、严格契约和 Native Controller 组成；OpenClaw、OpenHands、Paperclip、Codex、Claude、GitHub 和 Runner 都在可替换边界之外。

## v0.8 实际交付

| 工作包 | 已交付 | 证据边界 |
|---|---|---|
| W1 | Team、Role、Workflow、WorkItem、Plan、Approval、Run、Evidence 和命令/事件契约 | 严格 Schema、规范摘要、正反例、v0.7 单向迁移 |
| W2 | 十个显式 Adapter Port 和能力协商 | 无动态插件加载；外部 SDK 不是安装依赖 |
| W3 | SQLite Native Controller 与故障恢复 | revision、准确批准、nonce、租约、outbox、预算、审计链和稳定重放 |
| W4 | Native OCI 计划器、Runner 候选和一次性 Runner 探针 | 本机安全拒绝；真实探针只能在 GitHub 托管临时 Worker 运行 |
| W5 | GitHub Actions 身份、准确摘要、仓库/base/path 绑定和提案写入器 | 只允许 Issue、提案分支、文件提交和 Draft PR；没有 merge/deploy API |
| W6 | Codex、Claude 和 Generic CLI 路由 | 同一结构化结果契约、独立短会话、固定超时和最小环境 |
| W7 | Paperclip、OpenHands、ACP、OpenClaw 可选投影 | 不安装外部产品；删除投影不影响 Native 权威和恢复 |
| W8 | 中英文采用入口、安全/恢复文档、SBOM、溯源和发布门禁 | 只公开已证明的 L1 能力 |

## 能力等级

- `L1 reference`：本发布已经达到。离线 Native 闭环可重复执行；真实外部边界有契约、负例和受限实验工具。
- `L2 controlled pilot`：需要新的 Private Team Instance、专用测试仓库、身份、模型预算和隔离 Worker；属于 v0.9 采用项目，v0.8 不会自动创建。
- `L3 production`：还需要 SLO、值守、威胁评审、密钥轮换、备份恢复演练和业务责任人；属于 v1.0 路线。

因此，v0.8 可以帮助用户生成团队、共享上下文、验证工作流和搭建受治理集成，但不会因为安装成功就自动读取用户反馈、修改业务代码、合并或上线。

## 本地验证

要求 Python 3.11+ 和 Git，无第三方 Python 运行依赖：

```bash
git checkout v0.8.0

./agent-team native contract-validate \
  --contract team_spec \
  --file examples/v08-contracts/valid/team-spec.json

./agent-team native demo --database /tmp/agent-team-native.sqlite3
./agent-team native status --database /tmp/agent-team-native.sqlite3
./agent-team native verify --database /tmp/agent-team-native.sqlite3
```

`demo` 固定停在 `DRAFT_PR_READY`，使用确定性 Fake，不联网、不调用模型、不运行不可信代码、不写真实仓库。对同一数据库重放不会重复事件或外部 effect。

完整发布验收：

```bash
python3 tools/agent_team.py validate
python3 -m unittest discover -s tests -v
python3 tools/release_audit.py --since-tag v0.7.0
tools/cold-start.sh
tools/release-smoke.sh
```

## 阅读顺序

1. [ADR-0009](../adr/ADR-0009-vendor-neutral-core-and-replaceable-ports.md)：为什么自有核心、外部可替换。
2. [核心契约与迁移](core-contracts-and-migration.md)：权威数据和 v0.7 导入。
3. [Adapter Port SDK](adapter-port-sdk.md)：接口、能力和故障语义。
4. [Native Controller 与一致性](native-controller-and-conformance.md)：状态、事务和恢复。
5. [Runner、SCM、Agent 与外部平台边界](runner-scm-and-agent-boundaries.md)：W4–W7 的安全实现。
6. [采用路线](adoption-and-integration.md)：从生成文件团队到受控自动化。
7. `contracts/`、`acceptance/`、`sbom/` 和 `supply-chain/`：机器文件优先于聊天摘要。

## 永远保持关闭的默认项

- 业务仓库外部写入、模型账号、OpenClaw 频道和平台凭据不会自动配置。
- PVE、NAS、生产 Linux 或带生产挂载的 Host 不是不可信代码 Runner。
- 聊天消息、模型文本和平台管理员身份都不是 `ApprovalGrant`。
- Factory 没有自动 merge、Release 或生产 deploy 的团队命令。
- Gate E（真实 v0.9 试点）和 Gate F（v1.0 生产接入）不是 v0.8 发布授权的一部分。
