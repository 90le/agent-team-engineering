# Agent Team Engineering

`agent-team-engineering` 是一个供应商中立、默认安全停止的多智能体软件团队工厂。它负责把版本化契约、角色、权限、工作流、Skill、适配器接口和实例模板组合成可以审阅、复制、升级与恢复的团队，而不是用一组提示词假装已经拥有自动化团队。

当前开发版本为 `0.2.0`。不可变的 `v0.1.0` 是已经验收的参考内核；`v0.2.0` 在此基础上增加声明式团队实例、版本锁、原子生成、漂移检测和严格校验。真实外部写操作、长期控制器和生产部署仍然默认关闭。

## 三种仓库不要混淆

| 仓库 | 拥有什么 | 不拥有什么 |
|---|---|---|
| Factory仓库（本仓库） | 通用契约、控制器、CLI、团队包、Skill、适配器SDK、模板和迁移 | 某个用户的秘密、运行数据库和业务事实 |
| Instance仓库 | 某个团队的非秘密配置、策略覆盖、版本锁、项目绑定、运维文档和验收证据 | Factory源码、业务源码和秘密值 |
| Target项目仓库 | 产品原则、架构、源码、测试、Issue、PR和发布历史 | 通用Factory实现和团队运行数据库 |

一个实例可以管理多个目标项目。目标项目不是第三个Agent Team产品仓库。

## 验证Factory

要求 Python 3.11+ 和 Git，无第三方 Python 运行依赖：

```bash
python3 tools/agent_team.py doctor
python3 tools/agent_team.py validate
python3 -m unittest discover -s tests -v
python3 tools/agent_team.py simulate
python3 tools/agent_team.py simulate --approve-production
```

从 [AI-BOOTSTRAP.md](AI-BOOTSTRAP.md) 开始接管；产品阶段、架构和安全边界分别见[项目定位](docs/00-project-positioning/vision-and-scope.md)、[参考架构](docs/02-architecture/reference-architecture.md)与[威胁模型](docs/03-security/threat-model.md)。

## 创建一个安全的实例骨架

示例配置默认禁用所有外部适配器，自治上限为 `A2`：

```bash
python3 tools/agent_team.py instance init \
  --config examples/team-instance/input/instance.json \
  --output /tmp/example-agent-team-instance

python3 tools/agent_team.py instance validate \
  --root /tmp/example-agent-team-instance

python3 tools/agent_team.py instance inspect \
  --root /tmp/example-agent-team-instance
```

`init` 只接受不存在的新目录，先在同一文件系统的临时目录生成和校验，成功后才原子切换；它不会覆盖已有文件。实例配置修改后必须先校验，再显式更新锁：

```bash
python3 tools/agent_team.py instance relock \
  --root /tmp/example-agent-team-instance
```

Factory管理文件发生漂移会导致失败；允许用户维护的 seeded 文件只产生警告。完整生命周期见[实例生成与治理](docs/08-factory/instance-lifecycle.md)。

## 接入已有项目

接入提案必须生成在目标仓库外，分析过程不会修改目标仓库：

```bash
python3 tools/agent_team.py adopt-project \
  --repo /path/to/existing-project \
  --output /tmp/project-adoption-proposal
```

所有者审阅提案后，才决定是否在目标项目的提案分支加入 `.agent-team/`、入口和GitHub门禁。

## 当前边界

- 不保存密码、Token、私钥、生产配置、用户数据、运行数据库或Runner工作区。
- 模型建议没有授权效力；结构化批准、工具策略和状态机负责强制边界。
- 本版本能生成和验证实例，但还不是常驻运行的生产控制平面。
- OpenClaw、GitHub、模型、Runner和部署端必须分别绑定，默认全部禁用。
- 仓库当前保持Private；未来公开需要独立内容与许可证审查。
