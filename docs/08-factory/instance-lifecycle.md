# 实例生成与治理

## 输入和输出

Factory只从通过 `schemas/team-instance.schema.json` 及安全语义检查的JSON生成实例。输入必须声明所有者、团队包、自治上限、批准人、项目、适配器、运行路径和资源限制。配置只能记录 `secret.*` 引用，不能记录秘密值。

生成结果分为三类：

| 类型 | 示例 | 变更规则 |
|---|---|---|
| authority | `.agent-team/instance.json` | 人工审阅后修改，再校验并显式relock |
| managed | `AI-BOOTSTRAP.md`、平台薄入口 | 由Factory维护；漂移是错误，升级不能静默覆盖 |
| seeded | `README.md`、`docs/README.md`、`.gitignore` | 首次提供，采用者可以修改；漂移只警告 |

锁文件记录Factory版本、源修订、源是否脏、契约SHA-256、团队包版本、配置摘要及生成文件摘要。锁是可核验绑定，不是秘密存储。

## 初始化

```bash
python3 tools/agent_team.py instance init \
  --config examples/team-instance/input/instance.json \
  --output /new/path/team-instance
```

安全性质：

- 输出路径必须位于Factory仓库外且尚不存在。
- 在输出路径同一文件系统的专用临时目录生成。
- 生成后先完整验证，再使用原子目录重命名发布。
- 任一步失败都只清理本次创建的临时目录，不触碰既有路径。
- 同一Factory工作树和相同输入产生相同内容；锁会明确记录源提交和dirty状态。

## 配置修改和重新锁定

编辑 `.agent-team/instance.json` 后，普通验证会以“配置在锁定后变化”失败。这是为了避免未审阅配置被运行时悄悄采用。

```bash
python3 tools/agent_team.py instance relock --root /path/to/team-instance
python3 tools/agent_team.py instance validate --root /path/to/team-instance
```

`relock` 仍会执行Schema、安全语义、秘密扫描和managed文件完整性检查；它不会替换生成文件、升级Factory或启用适配器。配置变更应在实例仓库提案分支中提交并由所有者审核。

## 默认安全策略

- 初始化自治上限不超过 `A2`。
- 所有者必须同时在计划和生产批准名单中。
- 生产批准必须保持人工要求。
- 所有适配器示例默认禁用。
- 适配器ID必须存在于当前Factory目录并支持所绑定slot，config必须通过Manifest引用的Schema；启用声明凭据的适配器时必须提供外部`secret.*`引用。
- 同一provider/locator不能伪装成两个项目；外部操作还必须通过Manifest项目作用域与项目mode、默认分支检查。
- 状态、工作区和制品路径必须是实例内的安全相对路径，并被Git忽略。
- `.env`、密钥、数据库及凭据模式进入实例Git区域时验证失败。

## 升级边界

`relock`只能接受同一Factory版本下经过验证的声明式配置变化，不能修改锁中的Factory版本、替换managed文件或冒充迁移。

v0.5提供从v0.2、v0.3、v0.4到v0.5的显式迁移：先在实例外输出摘要绑定计划，人工审阅后创建外部恢复包，再逐项迁移managed文件并最后提交目标锁。用户修改过的seeded文件原样保留。运行库存在时必须暂停、审计通过且无活动租约/未决外部效果；操作者还必须另外停止所有Writer进程。

升级和回滚使用 `runtime/.factory-lifecycle-journal.json` 记录崩溃恢复状态；日志存在时不得运行实例或手工删除。恢复命令返回当前操作开始前版本。完整安装、计划、应用、恢复、回滚和证据协议见[Factory安装、实例升级、恢复与项目接入](../11-lifecycle/installation-upgrade-and-adoption.md)。任何不兼容Schema变化仍需要新ADR、主版本和显式迁移。
