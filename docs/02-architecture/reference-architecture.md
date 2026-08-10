# 参考架构

## 五层模型

1. 核心协议：工作项、任务信封、审核决定、测试证据、发布候选和审计事件。
2. 控制平面：确定性状态机、权限策略、租约、幂等、预算、重试和暂停。
3. 团队能力包：角色、Skill、工作流、风险分级和质量门禁。
4. 平台适配器：消息、代码托管、AI提供者、Runner和部署接口。
5. 项目与环境覆盖层：产品原则、实际架构、命令、基础设施和秘密引用。

## 稳定接口

适配器只接收和产生 `schemas/` 定义的结构化对象。核心流程不认识 OpenClaw 会话、GitHub Label 或某个模型的专用消息格式；适配器负责映射。

角色能力和工具权限只在团队包 JSON 中定义，参考控制器在运行时加载，不在模型提示词或代码中维护第二份权限事实。

## 状态与并发

每个工作项具有单调递增 `revision`。执行者必须提交 `expected_revision`；过期写入被拒绝。副作用必须携带幂等键，重试不能重复创建 Issue、PR 或部署。

## 上下文

所有角色使用同一个框架提交和项目提交，但只加载职责需要的文件。`tools/agent_team.py export-context` 可为无文件访问的 AI 生成带 SHA-256 的最小包。搜索与向量索引只能从这些源文件重建。

## 运行配置

参考模拟器与v0.3控制平面仅依赖Python标准库。控制平面使用SQLite事务保存工作项、幂等记录、租约、暂停状态、outbox和哈希链审计；该实现面向单实例与有限并发Worker，不宣称多节点高可用。未来替换持久引擎不得改变开放契约、修订检查和角色分离原则。OpenClaw是消息与协调适配器，不是默认安全边界。

控制平面先在一个事务中提交状态与待执行outbox记录，再由Worker领取外部副作用。进程在提交前中断时两者都不生效；提交后中断时outbox仍可恢复。外部提供者仍需接受幂等键，因为进程可能在副作用成功后、确认写回前中断。

## Factory、实例与项目

Factory发布通用实现和迁移；实例锁定明确Factory版本，保存团队自己的非秘密配置和项目绑定；目标项目继续拥有产品事实与源码。实例只能通过适配器操作目标项目，不能把仓库写权限解释为合并或生产权限。

实例由 `.agent-team/instance.json` 声明，`.agent-team/instance.lock.json` 绑定Factory版本、源修订、契约摘要和生成文件摘要。Factory管理文件漂移时安全停止；用户维护文件允许自定义但会报告差异。详细决定见 [ADR-0003](../adr/ADR-0003-factory-instance-project-boundaries.md)。

持久状态与恢复决定见 [ADR-0004](../adr/ADR-0004-sqlite-control-plane-and-outbox.md)。

决策依据见 [ADR-0001](../adr/ADR-0001-vendor-neutral-core.md)、[ADR-0002](../adr/ADR-0002-authority-runtime-separation.md)、[ADR-0003](../adr/ADR-0003-factory-instance-project-boundaries.md) 和 [ADR-0004](../adr/ADR-0004-sqlite-control-plane-and-outbox.md)。
