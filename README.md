# 可移植多智能体软件团队工程

`agent-team-engineering` 是一个供应商中立的多智能体软件交付参考工程。它把协议、状态机、岗位权限、审批、证据和审计作为稳定核心，把 OpenClaw、GitHub、Codex、Claude 等作为可替换适配器。

当前版本是 `0.1.0` 参考实现：可以离线验证仓库、模拟“反馈到发布”流程、检查安全负例、为现有代码仓库生成只读接入提案，并执行不依赖历史聊天的 Git 冷启动测试。它不会连接或部署任何生产系统。

## 快速验证

要求 Python 3.11+ 和 Git，无第三方 Python 依赖：

```bash
python3 tools/agent_team.py doctor
python3 tools/agent_team.py validate
python3 -m unittest discover -s tests -v
python3 tools/agent_team.py simulate
python3 tools/agent_team.py simulate --approve-production
```

从 [AI-BOOTSTRAP.md](AI-BOOTSTRAP.md) 开始接管；架构和安全边界分别见 [参考架构](docs/02-architecture/reference-architecture.md) 与 [威胁模型](docs/03-security/threat-model.md)。

## 项目接入

先在目标仓库外生成提案，工具不会修改被分析仓库：

```bash
python3 tools/agent_team.py adopt-project \
  --repo /path/to/existing-project \
  --output /tmp/project-adoption-proposal
```

审阅输出后，才由项目所有者决定是否把 `.agent-team/`、入口文档和 GitHub 门禁加入目标项目。

## 边界

- 仓库不保存密码、Token、私钥、生产配置、用户数据或运行数据库。
- 模型建议没有授权效力；工具策略和工作流状态机负责强制执行。
- 本版本提供参考模拟器，不是无人监管的生产发布控制器。
- 任何环境都必须单独绑定秘密、Runner、代码托管和发布接口。
