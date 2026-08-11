# Runner、SCM、Agent 与外部平台边界

本章描述 v0.8 W4–W7 已实现的边界。它们是核心之外的可替换接口，不是安装后自动启动的后台服务。

## 一次性 Runner

`core/runner_conformance.py` 只生成固定 OCI argv，不启动进程。参考计划要求不可变 `sha256` 镜像 ID、非 root、只读根文件系统、只读源码、临时 workspace、无网络、移除 capabilities、`no-new-privileges`、CPU/内存/PID/超时限制，并禁止生产挂载和容器内 Docker Socket。

真实探针位于 `tools/disposable_runner_probe.py`，只能由 `.github/workflows/disposable-runner.yml` 在 `runner.environment=github-hosted` 时运行。若检测到 `/srv/appdata`、`/mnt/synology` 或 `/etc/pve`，探针在拉取镜像或启动容器前失败。三轮测试必须全部证明：非 root、源码只读、workspace 可写且临时、根只读、无生产挂载、无 Socket、无继承秘密、断网、资源限制、超时终止和零残留。

Native OCI 是参考计划器；SWE-ReX 和 Container Use 保持实验候选。候选更丰富不等于获得更大权限。

## GitHub SCM 与人工计划

`core/github_scm.py` 把以下值绑定后才允许写入：

- GitHub Actions 认证 actor ID 和当前 workflow run；
- 人工输入的准确 `PlanRevision.plan_digest`；
- 专用仓库、逻辑 repository ID、默认分支和准确 base commit；
- 单个允许路径、提案分支、预算、有效期和 `ApprovalGrant.scope_digest`。

任何错误摘要、错误 actor、错误仓库、移动的 base、越路径或过期批准都会在写入前失败。公开类只提供 `ensure_issue`、`ensure_branch`、`ensure_file` 和 `ensure_draft_pull_request`，没有 merge、release、settings 或 deploy 方法。每个对象带稳定标记；重跑先对账，不创建重复 Issue、分支、提交或 PR。

GitHub Webhook 在解析 JSON 前验证 HMAC-SHA256，delivery ID、事件类型和仓库必须匹配；SQLite ledger 只保存摘要和去重元数据，不保存完整消息正文。

真实写入只能在专用、无生产数据的测试仓库内验收。首次运行与完全相同的第二次运行必须分别保留“创建”和“对账、零新增”报告。专用仓库工作流模板与步骤见 [`examples/github-scm-conformance/`](../../examples/github-scm-conformance/README.md)。业务仓库采用属于新的 Gate E/F 决定。

## Codex、Claude 与 Generic CLI

`core/agent_drivers.py` 为每个角色创建短期、Schema-bound 任务：

- Codex 使用全局 `--ask-for-approval never` 后再进入 `exec --ephemeral`，同时启用 `--ignore-user-config`、`--ignore-rules` 和明确 `read-only`/`workspace-write` 沙箱；不会使用危险绕过参数。
- Claude 使用 `--safe-mode --no-session-persistence`；只读角色为 plan 模式且没有 Bash/Edit/Write。
- Generic CLI 使用操作员显式登记的固定 argv；任务 JSON 从标准输入进入，严格结果 JSON 从标准输出返回；v0.8 参考只允许只读角色。

所有路径都使用最小环境，不继承常见 API Key 环境变量；输出限制为 1 MiB，并核对 task/work item/role/action/revision。模型输出只是证据，不能转移状态或批准自身产物。作者与审核者的身份分离由 Controller 强制，不依赖提示词。

本发布不在生产 Linux 上运行真实模型任务。连接真实账号和不可信仓库需要专用 Worker 和单独预算授权。

## 可选平台

| 平台 | v0.8 采用的窄能力 | 明确不采用 |
|---|---|---|
| Paperclip | WorkItem/状态单向投影 | 外部 DB、层级、预算或任务状态成为核心权威 |
| OpenHands | 受限 AgentExecutor 任务/结果边界 | no-sandbox Host 执行和平台内部状态权威 |
| ACP | 可替换 Agent session transport 投影 | 协议 session 充当人工身份或批准 |
| OpenClaw | 认证 delivery 的反馈数据和状态通知 | 聊天作为批准、敌对多租户隔离或核心状态 |

这些投影在 `core/external_projections.py` 中是纯函数，不导入外部 SDK、不联网、不启动进程、不保存状态。删除任何描述符或不注册适配器时，Native Controller 和契约仍可独立运行。
