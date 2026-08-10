# Factory安装、实例升级、恢复与项目接入

- 文档ID：`ATE-OPS-011`
- 适用版本：Factory `0.7.0`
- 适用对象：项目所有者、运维人员、Codex、Claude、Kimi、OpenClaw Agent及其他接管者

本文是Factory分发、实例版本迁移和已有项目接入的规范操作入口。执行实例升级、恢复或回滚时，同时使用 `skills/upgrade-agent-team-instance/SKILL.md`；普通实例配置与控制平面管理使用 `manage-agent-team-factory`。

## 对象与权威边界

| 对象 | 权威内容 | 不能替代 |
|---|---|---|
| Factory Git仓库 | 通用源码、历史、已发布标签和评审证据 | 可执行安装副本的完整性清单 |
| Factory安装副本 | 某个精确发布的文件、模式、摘要和来源证明 | Git历史、签名身份或开发工作树 |
| Agent Team实例 | 团队非秘密配置、Factory版本锁、项目绑定和实例运维证据 | Factory源码、目标项目源码、秘密或运行数据库 |
| 外部恢复包 | 一次Factory文件切换前的受控文件和锁 | SQLite备份、目标项目Git备份、秘密备份或整机灾备 |
| 目标项目仓库 | 产品事实、架构、源码、测试、Issue、PR和发布历史 | 团队实例或Factory通用实现 |

不要在这五类对象之间复制权威文件来“同步”。绑定依靠版本、提交、Schema和SHA-256摘要，而不是同名目录。

## 安装一个可执行的Factory发布

开发工作树适合评审和测试；长期运行或执行实例迁移时，优先使用不可变安装副本。正式安装只接受同时满足以下条件的源：

- Git工作树干净，包括未跟踪文件检查；
- `HEAD`正好被与 `factory-package.json` 版本相同的注释标签 `v<version>` 指向；
- 标签对象类型是annotated tag，而不是lightweight tag；
- 发布树只含普通Git blob，文件路径、单文件和总大小均在限制内。

注释标签提供确定的Git来源绑定，但不等同于密码学签名。采用者仍需从受信仓库和审核过的提交取得标签。

发布者必须在推送不可移动标签前执行 `tools/release-smoke.sh`。该门禁在隔离克隆内模拟与 `VERSION` 一致的annotated tag，运行完整仓库验证、正式安装、安装完整性、Doctor及实例生成；若同名标签已经存在，它必须是指向当前提交的注释标签，否则失败。模拟通过不能替代GitHub主分支CI和推送后从远端标签重新克隆验收。

```bash
python3 tools/agent_team.py factory install \
  --output /opt/agent-team-factory-v0.7.0

python3 /opt/agent-team-factory-v0.7.0/tools/agent_team.py factory verify \
  --root /opt/agent-team-factory-v0.7.0

python3 /opt/agent-team-factory-v0.7.0/tools/agent_team.py doctor
```

安装目标必须不存在，并位于源仓库外。Factory先在目标父目录创建专用临时树，写入发布提交中的文件，生成 `.factory-installation.json`，逐文件验证路径、模式、大小和SHA-256，再通过原子目录重命名发布。失败不会覆盖同名现有路径。

安装验证拒绝缺失、篡改、额外文件、符号链接、模式变化及未声明缓存。CLI禁止写入Python字节码，保持安装树可重复验证。不要在安装目录中编辑文档、运行开发工具、存放日志或生成缓存；需要改变Factory时发布新版本并安装到新目录。

## Doctor的判定语义

```bash
python3 tools/agent_team.py doctor
python3 tools/agent_team.py doctor --instance /path/to/team-instance
```

Doctor只读检查Python、Git、POSIX `fcntl`生命周期锁、仓库契约、Factory来源、契约摘要、默认关闭的生产接入，以及可选实例的锁、漂移、生命周期日志和SQLite审计状态。

- `PASS`：该检查满足当前契约。
- `WARN`：可继续只读或开发工作，但在安装、升级或生产采用前必须审阅，例如工作树不是精确发布标签、实例有seeded自定义或运行库尚未初始化。
- `FAIL`：退出码为1，禁止生命周期写操作，例如安装完整性失败、实例managed漂移、审计失败或存在中断日志。

Doctor不是外部服务健康检查，也不会证明Worker已经停止、GitHub身份有效或生产环境可回滚。

## 升级前置条件

`v0.7.0`实现从 `0.2.0`、`0.3.0`、`0.4.0`、`0.5.0`、`0.5.1`、`0.6.0` 到 `0.7.0` 的显式迁移。以后每个目标版本必须单独声明可接受来源；能够读取旧实例不代表存在升级路径。

执行计划以外的任何生命周期动作前必须满足：

1. 人工所有者批准精确实例路径、源/目标版本、维护窗口、恢复位置和回退意图。
2. 使用干净注释标签或 `factory verify` 通过且 `release_verified=true` 的Factory安装副本。
3. 操作系统支持POSIX `fcntl`，实例路径和权威文件不是符号链接。
4. 停止所有会写实例或运行库的调度器、Worker和适配器进程。数据库 `paused=true` 不证明这些进程已停止。
5. 运行库存在时，先由owner暂停，再验证审计链、活动租约为0，且outbox没有 `PENDING`、`FAILED`、`CLAIMED` 外部效果；运行库不存在时不要为升级而初始化。
6. `doctor --instance` 与 `instance validate` 没有错误，且 `runtime/.factory-lifecycle-journal.json` 不存在。

## 生成并审阅升级计划

```bash
python3 tools/agent_team.py instance upgrade plan \
  --root /path/to/team-instance \
  --output /safe/change-records/upgrade-plan.json
```

计划必须写在实例外。它绑定绝对实例路径、实例ID、源配置与锁摘要、源/目标Factory版本、目标修订、契约摘要、目标锁摘要、每个新增/替换/删除动作以及保留的seeded文件。所有者至少审阅：

- 路径和实例ID是否是预期对象；
- 源/目标版本与来源修订；
- managed文件的逐项动作是否合理；
- seeded自定义是否全部列为保留；
- 是否出现不应由Factory管理的目标项目、秘密、数据库或用户数据。

计划内容、实例锁或Factory发生任何变化后，原计划会被判定为陈旧。不要编辑计划规避检查，应重新生成并重新审批。

## 应用升级及事务模型

选择一个不存在、位于实例外的恢复目录。建议它处于独立备份或不同故障域，而不是与实例共用唯一磁盘。

```bash
python3 tools/agent_team.py instance upgrade apply \
  --root /path/to/team-instance \
  --plan /safe/change-records/upgrade-plan.json \
  --recovery /safe/recovery/instance-v0.4-before-v0.7.0
```

执行顺序如下：

1. 重新计算计划、锁、Factory来源和运行静止状态；任一变化都在写入前停止。
2. 在实例同级外部临时目录准备目标内容。
3. 在实例外原子生成恢复包，重新验证清单、摘要和权限。
4. 创建 `runtime/.factory-lifecycle-journal.json`，记录 `PREPARED` 状态和恢复包绝对路径。
5. 逐文件原子替换或删除Factory-managed内容，每步刷新日志。
6. 最后写入目标 `.agent-team/instance.lock.json`，作为逻辑提交标记。
7. 完整实例验证通过后记录 `VERIFIED`，删除事务日志和临时树。

这是“锁最后提交、混合状态拒绝运行”的逻辑原子性，不是多个文件在文件系统层同时瞬间切换。进程或主机在任意文件之间退出时，日志和外部恢复包允许保守地回到操作前版本；在恢复完成前，所有runtime命令都会拒绝运行。

升级只迁移Factory锁定的生成文件。它保留被用户修改的seeded文件，不升级SQLite Schema，不复制目标项目，不处理秘密，也不替代运行库备份。

## 中断恢复

发现生命周期日志后不要删除、编辑、移动文件、运行 `relock` 或手工补齐半套内容。保持所有写入进程停止并执行：

```bash
python3 tools/agent_team.py instance recovery-inspect \
  --bundle /path/from/lifecycle-journal

python3 tools/agent_team.py instance recover \
  --root /path/to/team-instance
```

恢复命令验证日志操作类型、实例ID、计划ID、源/目标锁摘要及恢复包。升级中断时恢复到升级前版本；回滚中断时恢复到回滚前版本。它允许文件处于已知的转换前或转换后摘要，但拒绝第三种“操作后漂移”，避免覆盖其他人的新修改。恢复成功、实例验证通过并清理受信临时树后，才删除日志。

日志、恢复包或当前摘要不一致时必须人工调查，不能靠删除日志恢复运行。

## 主动回滚与救援包

成功升级后需要返回旧版本时，先验证升级产生的原始恢复包，并为当前版本选择一个新的、空的外部救援目录：

```bash
python3 tools/agent_team.py instance recovery-inspect \
  --bundle /safe/recovery/instance-v0.4-before-v0.7.0

python3 tools/agent_team.py instance rollback \
  --root /path/to/team-instance \
  --recovery /safe/recovery/instance-v0.4-before-v0.7.0 \
  --rescue /safe/recovery/instance-v0.7.0-before-rollback
```

回滚在变更前捕获当前版本救援包并创建同样的事务日志，因而回滚失败或进程中断也能恢复到回滚前版本。回滚完成后，原始恢复包可返回旧版，救援包可重新返回新版。两者都应保留到所有者验收和保留策略允许清理为止。

恢复包目录必须为 `0700`，清单和备份文件必须为 `0600`；文件、总容量、路径、重复项、符号链接和未声明内容均受限制。它只含本次Factory转换涉及的文件，不应被描述成实例或业务的完整备份。

## 只读接入已有项目

项目接入分为“生成提案”和“所有者另行采用”，Factory不直接改目标仓库：

```bash
python3 tools/agent_team.py adopt-project \
  --repo /path/to/existing-project \
  --output /safe/proposals/project-a \
  --provider github \
  --locator owner/project-a \
  --default-branch main \
  --project-id project-a

python3 tools/agent_team.py adoption verify \
  --root /safe/proposals/project-a

python3 tools/agent_team.py adoption compose \
  --base-config examples/team-instance/input/instance.json \
  --proposal /safe/proposals/project-a \
  --output /safe/candidates/instance-with-project-a.json
```

发现阶段只读取根目录技术标记、AI入口、Git身份和GitHub工作流名称；Git命令设置 `GIT_OPTIONAL_LOCKS=0`，不刷新目标索引。提案与候选配置都必须位于目标仓库外且目标路径不存在。提案包绑定项目ID、provider、locator、默认分支、源提交、dirty状态、逐文件摘要和 `target_repository_mutated=false`。

组合只向候选实例配置增加一个 `mode=proposal-only` 项目，不启用适配器、不提升自治等级、不授予merge或部署权限。目标仓库后续是否加入入口、分支门禁和项目政策，必须由所有者在目标仓库的独立提案分支决定。

## 验收与证据清单

一次生命周期变更至少保留：

- 人工所有者、批准时间、精确范围和维护窗口；
- Factory安装ID、版本、源提交、标签和树摘要；
- 变更前后实例提交、实例ID、锁摘要和契约摘要；
- 升级计划、恢复包ID及其独立存储位置；
- Worker停止、运行暂停、租约/outbox静止和审计head证据；
- apply、validate、Doctor、单元/项目测试结果；
- 是否恢复或回滚、救援包ID、最终接受决定；
- 运行恢复后与外部提供者的对账结论。

换用另一台设备或另一种AI时，接管者必须能仅凭Git发布、实例仓库、本章、对应Skill和外部资产清单复述上述边界并完成一次无生产副作用的演练。聊天历史不能作为必需输入。

## 已知限制

- 生命周期写操作当前要求支持 `fcntl` 的POSIX平台，不提供Windows写入回退。
- 锁只协调使用本Factory协议的本机生命周期命令；它不会停止未受治理的外部进程。
- 当前迁移按单实例执行，不是多节点高可用或分布式事务。
- 文件逻辑提交不包含SQLite、目标项目、外部提供者状态、Runner制品或秘密。
- 项目接入只产生可审阅材料，不自动创建远程仓库、分支保护、PR、真实适配器或生产团队。
