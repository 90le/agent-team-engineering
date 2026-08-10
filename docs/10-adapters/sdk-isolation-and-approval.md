# 适配器SDK、隔离执行与认证批准

## v0.4交付了什么

v0.4提供一个不动态加载插件的Python参考宿主、版本化Manifest、操作输入/输出Schema、事件授权策略、受限秘密解析、outbox Worker、绑定批准验证器、签名Webhook边界和Runner隔离请求。

它不包含真实Token、OpenClaw插件、GitHub认证客户端、模型调用、容器沙箱或生产部署。参考`AdapterHost`执行outbound outbox；inbound Manifest是映射契约，当前只有签名反馈解析边界，不是通用入站守护进程。`adapter catalog` 只读取数据，不导入Manifest中的entrypoint：

```bash
python3 tools/agent_team.py adapter catalog
```

## 五层放行条件

| 层 | 权威 | 失败结果 |
|---|---|---|
| 实例绑定 | `.agent-team/instance.json` 的slot、adapter ID、enabled、config和 `secret_refs` | 未启用或slot不匹配即拒绝 |
| 适配器契约 | `adapters/*/adapter.json` 的操作、方向、投递语义和Schema | 未声明操作、输入/输出偏移即拒绝 |
| 项目作用域 | Manifest的`project_scope`与实例`projects`的ID/locator、provider、mode和默认分支 | 未声明目标、observe模式写入或分支偏移即拒绝 |
| 持久事件授权 | `policies/adapter-authority.json` 把操作能力绑定到同一工作项的审计事件/转换 | 仅有outbox记录也不执行 |
| 显式实现 | 受信进程启动时注册的 `Adapter` 对象 | Manifest字符串不会变成代码执行权 |

Worker首先验证整条审计链，再领取outbox效果。宿主拒绝未领取或在调用前已经过期的claim，还会验证操作只能从其声明的slot调用，并按`project_scope`把payload目标绑定到实例声明的项目；GitHub草稿PR的base必须等于项目默认分支，Runner的抽象source ref必须绑定同一project ID。宿主使用受计算的request ID、原outbox幂等键和claim截止时间，结果只允许结构化、受大小限制且不含凭据的JSON。

Manifest超时会传入request deadline，但Python进程内宿主不能抢占一个卡死实现；真实Transport/SDK必须设置连接与请求超时，并由进程监督器终止失控Worker。显式注册意味着实现代码属于受信计算基；宿主可以限制它得到的输入与秘密引用，却不能阻止恶意实现自行记录已经解析到的秘密，因此生产实现仍需代码审核、最小权限和进程隔离。

适配器应只抛出稳定的typed错误。Worker对意外异常只持久化`ADAPTER_UNEXPECTED_FAILURE`，不保存异常文本或提供者原始响应；调试证据必须经过独立脱敏，不能通过扩大数据库日志来获取。

## 投递语义

- `provider-idempotency`：外部提供者真正按稳定key去重，Worker才可重试。
- `reconcile-before-retry`：第二次尝试前必须使用稳定外部标记查询。已存在则直接确认，确认不存在才可再写。
- `at-most-once`：不可安全去重或对账的操作必须 `max_attempts=1`；结果不确定时进入人工处置，不盲目重放。
- `read-only`：只能配合read效果，不能伪装写操作。

GitHub参考适配器将 `issue.create` 和草稿 `pull-request.create` 映射到注入的Transport，在正文放入同时绑定幂等键与不可变操作内容的稳定标记用于对账。GitHub官方文档明确创建Issue需要Issues write权限、创建PR需要Pull requests write权限，GitHub App应选择最小权限：[Issues REST](https://docs.github.com/en/rest/issues/issues)、[Pull requests REST](https://docs.github.com/en/rest/pulls/pulls)、[GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)。参考Manifest不提供合并或默认分支直推操作。

## 人工批准不是一个布尔值

`ApprovalVerifier` 验证的断言同时绑定：

- 身份提供者和 `human.*` 主体；
- `approve_plan` 或 `approve_production` 动作；
- 工作项和当前revision；
- 完整evidence摘要，因此生产批准绑定确切制品摘要；
- 签发时间、短期过期时间、nonce和外部证据ref。

控制平面只持久化提供者、证据引用和claim摘要，不保存签名或秘密。已成功提交的同一幂等请求可在断言过期后重放已保存结果；新请求不能使用过期断言。HMAC实现只是本地参考验证器；真实IM接入需要身份认证、会话分离、一次性挑战和审计证据。

v0.4依赖单实例revision和幂等记录阻止本地重复提交，不提供跨两个同时可写恢复副本的全局nonce库。灾难恢复或主备切换必须保证单写者，并在恢复后先暂停和对账。

CLI参考路径要求断言、provider和HMAC密钥文件同时提供；密钥必须是非符号链接的普通文件，并禁止group/other访问（通常为`0600`）。不要把密钥或断言签名写入实例Git、命令输出或恢复包。

OpenClaw官方安全文档说明它默认是个人助手信任模型，不是多个对抗用户的安全隔离边界：[OpenClaw Gateway Security](https://docs.openclaw.ai/gateway/security)。因此公开反馈入口与owner控制入口必须使用不同Agent、会话、凭据和工具策略，公开会话不能获得应用编辑、Git、Shell或部署能力。

## Runner契约不等于沙箱

`execution-request` 只允许预注册 `command_id` 和argv，并强制只读源码、临时workspace、无特权、无Docker Socket、无生产挂载、有界超时和默认无网络。网络allowlist的字符串检查不能防止DNS rebinding；真实执行器还必须在网络层锁定解析后地址。

GitHub同样警告自托管Runner不保证临时干净，不可把日志脱敏当成真正安全边界：[Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)、[Compromised runners](https://docs.github.com/en/actions/concepts/security/compromised-runners)。生产实现需用每任务销毁的VM/微虚拟机或等价隔离，不能直接在PVE宿主、Linux生产容器或挂载群晖业务数据的环境里运行不可信PR。

## 实现一个新适配器

1. 使用 `implement-agent-team-adapter` Skill，先提案Manifest、Schema、授权事件和故障语义。
2. 通过显式注入的Transport/SDK客户端实现 `execute` 和 `reconcile`；不动态导入Manifest entrypoint。
3. 用假Transport做契约测试，覆盖“提供者成功、本地确认前崩溃”。
4. 证明输入、输出、异常和数据库都不会保存凭据。
5. 在独立实例变更里绑定测试账号、最小权限、秘密引用、暂停/回退和所有者验收；不在Factory通用版本里启用真实写入。
