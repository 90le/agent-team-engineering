# OpenClaw 映射边界

公开用户消息先转成 `FeedbackEvent`，再调用窄接口进入控制平面。原始消息不直接传给拥有代码或部署工具的 Agent。

公开入口与所有者控制入口必须使用不同信任边界；示例 JSON 只描述所需安全属性，实际字段要根据安装版本映射并重新验证。

## 两个入口不能合并

| 入口 | 允许产生 | 永远不允许 |
|---|---|---|
| public intake | 签名并去重的`FeedbackEvent` | Shell、Git写入、秘密、Agent派生、审批和部署 |
| owner control（`approval` slot） | 认证后的状态查询、暂停和短期绑定批准断言 | 从公开`intake` slot继承身份、任意Shell、直接生产操作 |

OpenClaw官方说明其Gateway采用个人助手信任模型，并不提供敌对多租户安全隔离：[Gateway Security](https://docs.openclaw.ai/gateway/security)。因此应使用不同Agent、会话、凭据、allowlist和工具策略；仅靠不同提示词或频道名称不构成隔离。

公开消息即使通过Webhook认证，也仍是不可信数据。`event_id`必须绑定认证delivery ID并由控制平面幂等写入。owner聊天消息本身也不是批准：认证适配器要把主体、动作、work item、revision、evidence摘要、有效期、nonce和外部证明ref绑定成断言，再交给`ApprovalVerifier`。v0.4不提供可直接部署的OpenClaw插件或真实身份配置。
