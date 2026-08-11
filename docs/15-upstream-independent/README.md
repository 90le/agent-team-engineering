# v0.8 未发布开发预览

状态：W1–W3 本地开发快照；分支 `proposal/upstream-independent-v0.8`；尚未发布。当前稳定版本仍是 `v0.7.0`。

本章是普通维护者和无历史聊天 AI 接手 v0.8 的最短入口。它证明 Agent Team 可以拥有供应商中立的核心契约、可替换端口和可恢复 Native 控制器，而不把 OpenClaw、OpenHands、Paperclip、模型厂商或 SCM 厂商变成唯一权威。

## 已实现的范围

| 工作包 | 交付物 | 证明范围 |
|---|---|---|
| W1 | 严格核心 Schema、契约注册表、摘要规则、v0.7 单向导入 | 团队、角色、工作流、工作项、计划、批准、运行、证据和命令/事件可移植、可验证 |
| W2 | 十个显式 Adapter Port、能力协商、确定性 Fake | 平台实现可以替换；描述符不能隐式加载代码或扩大权限 |
| W3 | SQLite Native Controller、CLI、故障注入与无网络完整场景 | revision、准确批准、nonce、租约、outbox、幂等、恢复、预算、证据和审计链可执行 |

Native 场景固定结束在经过测试和独立复核的 `DRAFT_PR_READY`。Draft PR、身份、SCM、Runner、CI 和通知都是确定性 Fake；不会联网、调用模型、运行不可信代码或写入真实仓库。

## 接手阅读顺序

1. 阅读 [ADR-0009](../adr/ADR-0009-vendor-neutral-core-and-replaceable-ports.md)，确认核心与外部平台边界。
2. 阅读 [核心契约与迁移](core-contracts-and-migration.md)。
3. 阅读 [Adapter Port SDK](adapter-port-sdk.md)。
4. 阅读 [Native Controller 与一致性验收](native-controller-and-conformance.md)。
5. 检查 `contracts/core-contracts.json`、`contracts/native-reference-workflow.json` 和 `acceptance/v08-native-conformance.json`；机器文件优先于聊天摘要。
6. 运行下方验证，确认分支和工作树，再提出修改。

## 本地试用

要求 Python 3.11+ 和 Git；不需要第三方 Python 包或外部账户。

```bash
git switch proposal/upstream-independent-v0.8

./agent-team native contract-validate \
  --contract team_spec \
  --file examples/v08-contracts/valid/team-spec.json

./agent-team native demo --database /tmp/agent-team-native.sqlite3
./agent-team native status --database /tmp/agent-team-native.sqlite3
./agent-team native verify --database /tmp/agent-team-native.sqlite3
```

`demo` 可对同一数据库安全重放；相同命令和 effect 不应生成重复事件或外部执行。测试数据库是本地派生状态，不要提交到 Git，也不要用于生产资料。

## 尚未获批的边界

- Gate B：专用、一次性、隔离 Runner 与恶意代码逃逸测试。
- Gate C：专用 Private 测试仓库、最小权限真实身份和真实外部写入。
- Gate D：合并到 `main`、版本升级、标签、Release 和对外稳定能力声明。
- 生产模型、OpenClaw/OpenHands/Paperclip 接入、自动 merge 和生产部署均不在 W1–W3 内。

不要把本分支的 `factory-package.json` 版本号 `0.7.0` 误解为 v0.8 已发布：`status=DEVELOPMENT` 表示这是建立在最新稳定基线上的未发布源快照。只有 Gate D 才能同步修改 `VERSION`、包版本、状态、Changelog 发布段和标签。
