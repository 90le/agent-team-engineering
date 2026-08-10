# Agent Team Engineering

`agent-team-engineering` 是一个供应商中立、默认安全停止的多智能体软件团队工厂。它负责把版本化契约、角色、权限、工作流、Skill、适配器接口和实例模板组合成可以审阅、复制、升级与恢复的团队，而不是用一组提示词假装已经拥有自动化团队。

当前版本为 `0.5.0`。不可变的 `v0.1.0` 是参考内核，`v0.2.0` 建立声明式实例，`v0.3.0` 增加可重启的SQLite控制平面，`v0.4.0` 建立版本化适配器、绑定人工批准与隔离执行边界；`v0.5.0` 增加可验证安装、结构化Doctor、摘要绑定升级计划、外部恢复包、升级/回滚崩溃恢复和真正只读的项目接入包。真实账号、网络客户端、进程执行和生产部署仍然默认关闭。

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
python3 tools/cross_ai_takeover.py
```

从 [AI-BOOTSTRAP.md](AI-BOOTSTRAP.md) 开始接管；产品阶段、架构、安全、生命周期和适配器边界分别见[项目定位](docs/00-project-positioning/vision-and-scope.md)、[参考架构](docs/02-architecture/reference-architecture.md)、[威胁模型](docs/03-security/threat-model.md)、[安装升级与接入](docs/11-lifecycle/installation-upgrade-and-adoption.md)与[适配器SDK](docs/10-adapters/sdk-isolation-and-approval.md)。

## 安装精确发布

正式实例生命周期操作使用干净annotated tag或由其生成的可验证安装副本：

```bash
python3 tools/agent_team.py factory install \
  --output /opt/agent-team-factory-v0.5.0

python3 /opt/agent-team-factory-v0.5.0/tools/agent_team.py factory verify \
  --root /opt/agent-team-factory-v0.5.0
```

开发分支可以运行验证和测试，但不能应用实例升级。安装目标必须不存在；清单绑定源提交、标签、文件模式、逐文件摘要与整树摘要。

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

Factory管理文件发生漂移会导致失败；允许用户维护的seeded文件只产生警告。普通配置生命周期见[实例生成与治理](docs/08-factory/instance-lifecycle.md)，版本迁移、恢复与回滚见[安装升级与接入](docs/11-lifecycle/installation-upgrade-and-adoption.md)。

升级先生成实例外的摘要绑定计划，经人工审阅后才创建外部恢复包并切换；支持从 `v0.2.0`、`v0.3.0`、`v0.4.0` 到 `v0.5.0`：

```bash
python3 tools/agent_team.py instance upgrade plan \
  --root /path/to/team-instance \
  --output /safe/upgrade-plan.json

python3 tools/agent_team.py instance upgrade apply \
  --root /path/to/team-instance \
  --plan /safe/upgrade-plan.json \
  --recovery /safe/recovery-before-v0.5
```

## 启动持久控制平面

控制平面数据库按实例 `runtime.state_location` 创建并被Git排除：

```bash
python3 tools/agent_team.py runtime init \
  --instance /path/to/team-instance

python3 tools/agent_team.py runtime status \
  --instance /path/to/team-instance

python3 tools/agent_team.py runtime audit-verify \
  --instance /path/to/team-instance
```

反馈写入、任务租约、状态转换、暂停、对账和备份命令见[持久化与故障恢复](docs/09-control-plane/persistence-and-recovery.md)。非owner角色没有匹配租约不能提交状态；人工owner批准不能由Agent身份代替。

## 检查适配器契约

```bash
python3 tools/agent_team.py adapter catalog
```

目录只显示非秘密Manifest摘要，不导入Manifest中的entrypoint。v0.4提供无网络的Recording、GitHub映射和`local-dry-run`参考实现，用于证明Schema、项目目标绑定、幂等/对账、秘密作用域和Runner计划；它们不会自动连接账号或执行代码。启用某个实例绑定仍需显式实现注册、最小权限身份、外部`secret.*`引用和单独验收。

## 接入已有项目

接入提案必须生成在目标仓库外，分析过程不会修改目标仓库：

```bash
python3 tools/agent_team.py adopt-project \
  --repo /path/to/existing-project \
  --output /tmp/project-adoption-proposal \
  --provider github \
  --locator owner/repository

python3 tools/agent_team.py adoption verify \
  --root /tmp/project-adoption-proposal
```

提案和候选实例配置都不能写入目标仓库；候选项目固定为 `proposal-only`，不会启用适配器或提升自治。所有者审阅后，才决定是否在目标项目的独立提案分支加入入口和门禁。

## 当前边界

- 不保存密码、Token、私钥、生产配置、用户数据、运行数据库或Runner工作区。
- 模型建议没有授权效力；结构化批准、工具策略和状态机负责强制边界。
- 本版本提供可重启控制平面库与本机管理CLI，但尚未提供常驻守护进程、高可用集群或真实远程身份客户端；owner工作流转换已强制要求`ApprovalVerifier`和短期绑定断言，CLI只提供本地HMAC参考验证路径。
- 生命周期写操作要求POSIX `fcntl`、人工停止所有Writer和静止运行库；暂停状态本身不证明进程已停止。文件切换是锁最后提交的逻辑原子性，不是多文件物理原子事务。
- `execution-request` 是生产Runner必须满足的契约，`local-dry-run`只返回`PLANNED`，不构成容器、VM或微虚拟机沙箱。
- OpenClaw、GitHub、模型、Runner和部署端必须分别绑定，默认全部禁用。
- 仓库当前保持Private；未来公开需要独立内容与许可证审查。
