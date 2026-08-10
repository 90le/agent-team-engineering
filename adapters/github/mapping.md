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
