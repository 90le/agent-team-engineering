# GitHub 对象映射

| 核心对象 | GitHub载体 |
|---|---|
| FeedbackEvent | Issue 创建请求的来源记录 |
| WorkItem | Issue 与控制器状态引用 |
| Change specification | Issue正文或版本化规格文件 |
| Structured result | PR、评论或Check结果 |
| Test evidence | Required status check |
| Release candidate | Commit、制品摘要与Deployment |
| Approval event | 绑定修订和摘要的外部检查或受保护环境决定 |

GitHub Label和看板列是状态投影，不是控制器状态的唯一权威。Webhook必须使用交付ID或事件ID去重。

## v0.4参考实现

`core.reference_adapters.GitHubReferenceAdapter`只实现：

- `issue.create` → `POST /repos/{owner}/{repo}/issues`；
- `pull-request.create` → `POST /repos/{owner}/{repo}/pulls`，且`draft`必须为`true`。

正文会加入同时绑定outbox幂等键和不可变操作内容的稳定HTML标记。提供者成功而本地确认前崩溃时，重试必须先按标记查询；参考实现依赖实例注入的`GitHubTransport`，不包含网络、认证或Token。它不提供合并、默认分支直推、Release或Deployment操作。

创建Issue需要Issues write权限，创建PR需要Pull requests write权限；实例应使用仓库范围GitHub App并只授予所需权限。依据：[Issues REST](https://docs.github.com/en/rest/issues/issues)、[Pull requests REST](https://docs.github.com/en/rest/pulls/pulls)、[选择GitHub App权限](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)。逻辑角色仍需分开的分支保护、required checks和控制平面门禁，不能把一个粗粒度GitHub权限解释成所有角色授权。

Webhook接入必须在解析JSON前验证`X-Hub-Signature-256`的HMAC-SHA256，使用常量时间比较，并以认证后的delivery ID去重：[验证Webhook交付](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)。
