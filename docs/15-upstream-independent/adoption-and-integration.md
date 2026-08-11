# 从生成团队到受控自动化

v0.8 支持三条采用路线。先从最小路线开始；“角色更多”不等于“权限更大”。

## 路线 A：文件化团队

适合大多数用户。Factory 生成 Markdown 上下文、角色、Skill、工作流和平台发现文件，用户在 Codex、Claude、OpenClaw 或其它 AI 中按需使用。没有 Controller、账号或后台服务。

```bash
./agent-team create --guided --output /new/path/my-team
./agent-team context validate --root /new/path/my-team
```

把生成目录放入独立 Git 仓库或目标项目的提案分支，补充 `PROJECT-CONTEXT.md`、`ARCHITECTURE.md`、知识来源和 ADR。任何 AI 都先读生成包的 `AI-START.md`。

## 路线 B：离线受治理参考

适合评估状态机、准确批准、角色分离和恢复。运行 Native demo，使用 Fake 端口验证完整反馈到 Draft PR 状态，不接真实业务系统。

```bash
./agent-team native demo --database /safe/test/native.sqlite3
./agent-team native verify --database /safe/test/native.sqlite3
```

数据库属于派生运行状态，不进入普通 Git；按操作文档制作 SQLite 备份并验证摘要。

## 路线 C：受控自动化试点

这是采用工程，不是一个安装开关。至少需要：

1. 新建 Private Team Instance，指定 owner、目标测试项目和最大 A2 自治。
2. 为反馈入口、批准身份、SCM、模型、Runner、CI、通知逐个选择适配器并完成能力协商。
3. 使用专用测试仓库、仓库范围身份和一次性 Worker；禁止生产挂载和长期凭据进入执行环境。
4. 运行错误摘要、重放、权限撤销、超时、残留、恢复和卸载演练。
5. 人工验收后只开放到经测试、独立复核的 Draft PR；merge 和 production deploy 仍由项目自身流程决定。

OpenClaw 可以收集反馈和发送通知，但公开入口与 owner 控制入口必须是不同 Agent、会话、凭据和工具策略。Codex、Claude、OpenHands 或 ACP 可以成为 AgentExecutor；它们都不能绕过 Controller。

## 交给任意 AI 的采用提示

> 克隆 `https://github.com/90le/agent-team-engineering` 并检出 `v0.8.0`。先完整阅读 `AI-START.md`。只读检查我的项目，推荐文件化团队、离线参考或受控试点；在新目录生成并验证团队。不要自动创建凭据、外部写入、OpenClaw bindings、Host Runner、merge 或 deploy。若我要求试点，先输出逐端口权限、威胁、恢复和人工门禁清单，等待逐项授权。

## 迁移与复刻

可迁移资产是普通文件和 Git：团队包、项目上下文、角色、Skill、工作流、ADR、Schema 与锁。运行数据库、凭据、会话、临时 workspace 和提供者状态不随包复制。新设备或新 AI 应从已验证 Git 提交冷启动，重新发现本机能力，再连接外部系统。
