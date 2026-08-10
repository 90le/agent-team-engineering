# ADR-0005：版本化适配器主机、事件授权与绑定批准

- 状态：Accepted
- 日期：2026-08-10

## 背景

v0.3已能持久化工作项和outbox，但如果Worker仅根据一个字符串选择插件，那么Manifest、输入/输出、凭据、审计事件和运行隔离仍只是文档约定。另一方面，`kind=human` 只是结构化声明，不能证明调用者真是所有者。

## 决策

1. 每个适配器使用 `adapter.schema.json` v2 Manifest，显式定义版本、配置Schema、操作slot、方向、副作用类型、投递语义、能力、项目作用域、超时、输入/输出Schema、信任边界和逻辑凭据类型。
2. 核心不根据Manifest字符串动态导入代码。宿主只接受进程启动时显式注册、身份一致的实现。
3. 外部操作必须同时通过实例启用、操作slot、配置/输入Schema、实例项目作用域、`policies/adapter-authority.json` 事件授权和输出Schema。默认拒绝。
4. Worker在领取效果前验证审计链；提供者写入按 `provider-idempotency`、`reconcile-before-retry` 或 `at-most-once` 处理，不把“重试”默认等同于“可重复写”。
5. 适配器只能通过实例绑定的 `secret.*` 引用请求外部秘密解析；请求、结果、异常和审计不保存秘密值。
6. owner计划和生产批准在持久控制平面中必须有 `ApprovalVerifier` 和短期绑定断言。参考HMAC验证器用于本地契约和测试，不替代真实身份提供者。
7. Runner只接受声明式隔离请求。v0.4的 `local-dry-run` 只验证并记录计划，不启动进程，不被宣称为真实沙箱。

## 后果

平台可替换性从文档升级为可验证契约，缺失授权、Schema偏移、凭据泄露和错误重试会在副作前停止。代价是每个真实适配器都需要Manifest、Schema、事件授权、对账方法和负例测试。参考GitHub实现只提供经测试的映射和注入式Transport，OpenClaw仍是契约适配器；连接真实网络、凭据和生产Runner仍需实例级变更授权。
