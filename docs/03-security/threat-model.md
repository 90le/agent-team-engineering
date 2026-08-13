# 威胁模型

## 主要资产

- 源代码、产品原则、架构与历史。
- Issue、PR、测试和发布证据。
- Runner、构建制品、部署接口和生产数据。
- GitHub、AI提供者和基础设施凭据。

## 主要威胁

| 威胁 | 强制控制 |
|---|---|
| 用户反馈中的提示注入 | 公开入口无Shell/Git/部署权，只能提交结构化反馈 |
| Agent越权 | 工具白名单和状态机检查，不依赖提示词自律 |
| 作者自审 | `author_id != reviewer_id` 硬检查 |
| 重放或并发覆盖 | 幂等键与乐观修订检查 |
| 测试后替换制品 | 测试、批准和生产绑定同一摘要 |
| PR代码窃取秘密 | 临时隔离Runner，无生产挂载和长期凭据 |
| 供应链污染 | 锁定依赖、秘密扫描、制品校验和最小权限 |
| 无界Agent循环 | 尝试次数、时间、费用上限和死信队列 |
| 审批过期 | 执行副作用前重新验证批准、策略、摘要和环境 |
| 日志泄露 | 结构化脱敏日志，不记录提示词秘密或用户原始导出 |
| 重复外部副作用 | 状态与outbox同事务，提供者接收稳定幂等键，领取有期限且失败有上限 |
| 运行状态被篡改 | SQLite文件权限、verified backup、连续修订和SHA-256审计链检测；不能把哈希链误称为外部签名 |
| Agent冒充owner | owner工作流转换必须通过`ApprovalVerifier`验证短期断言，绑定人工主体、动作、工作项、revision和evidence；只保存claim摘要与证明引用 |
| 伪造outbox或错误复用授权 | 适配器宿主要求同一工作项的持久审计事件，并由默认拒绝策略绑定事件类型、转换动作、操作和能力 |
| 适配器供应链注入 | Manifest不动态加载代码；实现必须由受信进程显式注册，且身份、Schema和实例绑定一致 |
| 凭据跨适配器泄漏 | 实例只保存`secret.*`引用，宿主按单个绑定限制解析作用域，并拒绝请求、结果、错误或数据库中的秘密值 |
| GitHub批准被换仓库、换base、扩路径或超时重放 | 外部写入在调用前逐项重算并比对actor ID、repo、base commit、path/action、plan digest、TTL与nonce；任一不同即停止 |
| Webhook重送导致重复副作用 | 持久delivery ledger先绑定provider/delivery ID与payload digest；同身份不同内容冲突，相同内容可幂等对账 |
| 合法凭据操作错误项目 | 操作级project scope把payload绑定到实例声明的project ID/locator、provider、mode、默认分支和Runner source ref |
| 被篡改或来源不明的Factory副本 | 正式安装只接受干净精确annotated tag；安装Manifest绑定提交、文件模式、逐文件与整树摘要，并拒绝额外文件、符号链接和缓存 |
| 陈旧或被替换的升级计划 | apply重新计算实例、锁、契约、目标内容和计划ID；任何差异在写入前失败 |
| 多文件迁移中进程或主机退出 | 先生成外部恢复包和持久日志，逐文件原子替换，目标锁最后提交；恢复只接受已知前/后摘要 |
| 回滚本身失败 | 回滚前捕获当前版本救援包并写事务日志；中断时返回回滚前版本 |
| 恢复材料泄露或被替换 | 恢复目录/文件强制0700/0600，绑定实例、计划、锁和逐文件摘要，拒绝额外内容及符号链接 |
| “只读接入”隐式修改目标仓库 | Git发现禁用optional locks；提案和候选输出必须位于目标仓库外且目标路径不存在 |
| 蓝图编译覆盖用户文件或静默漂移 | team create/export只接受不存在路径；blueprint与全部生成文件由team lock摘要绑定 |
| 协调器误领取其他Worker任务 | outbox支持按准确effect ID领取；未匹配任务保持PENDING |
| 模型把项目说明当成更高权限 | Codex live忽略项目规则；Claude使用safe mode；任务信封、宿主策略和状态机而非项目提示决定权限 |
| 测试命令读取主机秘密 | Runner Profile无秘密、argv不经Shell、执行环境只保留最小非秘密变量；高风险项目必须改用外部隔离Runner |
| 在PVE/NAS/生产Linux上把容器当恶意代码沙箱 | v0.8一致性探针要求显式一次性环境确认和GitHub-hosted Worker标识，并在启动容器前拒绝`/srv/appdata`、`/mnt/synology`、`/etc/pve`等生产路径 |
| 本地Codex/Claude用户配置暗中改变自动化权限 | Codex使用`--ignore-user-config`、`--ignore-rules`、显式sandbox与全局approval policy；Claude使用safe mode、显式tool集和无session persistence；两者都验证结果Schema与任务身份 |
| Agent在批准前开始修改代码 | SPEC_READY固定返回人工计划门禁；worktree只在PLAN_APPROVED后创建，scope hash不匹配不能批准 |
| GitHub写入被模型权限隐式开启 | code-hosting实例绑定、项目/remote/default branch和显式provider写入开关必须同时成立；模型slot与GitHub slot分离 |
| 自动化越过Draft PR合并上线 | Team delivery contract固定merge/production forbidden；Reference Runtime停止在独立review，未实现team merge/deploy命令 |
| 角色Markdown或Skill自行扩权 | Team Design把角色文件视为上下文声明而非授权；宿主权限、状态转换、适配器策略和人工断言仍独立校验 |
| Custom角色被误当成受治理运行时角色 | Custom模式强制Lite且`managed_role=null`；没有显式状态机映射、身份、适配器和恢复协议就不能进入Managed |
| 平台原生文件与共享上下文分叉 | 平台输出和共享权威全部进入context lock；导出必须携带`.agent-team/context/`，漂移或符号链接验证失败 |
| 插件安装隐式执行代码或获得凭据 | 官方发现包只包含Manifest、Skill和参考资料，不含MCP、hook、后台进程或秘密；创建与外部接线是两个独立动作 |
| 上下文包覆盖目标项目已有AI规则 | create/export只写不存在路径；采用者必须在提案分支人工协调已有`AGENTS.md`、`CLAUDE.md`和平台目录 |
| 恶意Team Design穿越路径、携带秘密或伪造人工门禁 | 严格Schema、相对路径检查、inline secret扫描、人工actor/approval一致性检查和无覆盖原子发布 |
| 可维护上下文被用来替换生成的角色或平台规则 | Context Lock区分管理类型；用户新增文件只允许在知识、决策和工作目录，额外根文件或生成资产自重算摘要仍会失败 |
| 可选外部平台成为唯一状态权威或无法退出 | OpenClaw/OpenHands/Paperclip/ACP只是纯投影或端口候选，核心契约不引用其SDK类型；移除投影后Native状态、审计和恢复仍能独立验证 |
| 引用上游时不可追溯或悄然增加依赖 | 候选清单绑定上游URL、commit和许可证；SPDX SBOM和source provenance进入发布门禁，当前上游只参考、不作为运行依赖 |

## 永久人工门禁

身份权限、支付、隐私、秘密、用户数据删除、破坏性数据库迁移、生产基础设施、网络、存储和备份恢复默认属于人工决策。框架升级不能静默降低这一边界。

## 环境隔离

不可信代码必须在独立、可销毁的 Runner 中执行。Runner 不得挂载生产 Docker Socket、生产数据目录、虚拟化/NAS管理密钥或任意生产SSH身份。发布接口只接受经过批准的发布编号和制品摘要，不接受任意Shell。

SQLite运行库可能含有用户反馈、摘要和外部引用，至少按采用项目的Private数据处理。它不应包含凭据值，但仍必须限制文件权限、加密异地备份并遵守保留政策。不要把运行库放在不提供正确文件锁语义的共享文件系统上。

生命周期文件互斥依赖POSIX `fcntl`，只约束遵守Factory协议的本机命令。操作者必须在升级、恢复或回滚前停止所有调度器、Worker和适配器；数据库pause不能作为进程停止证明。恢复包只保护Factory转换文件，不能替代SQLite、目标项目、秘密、外部提供者或整机灾备。

v1宿主生命周期使用持久`.agent-team/.host-lifecycle.guard`串行化apply、受保护verify和uninstall。Guard是`empty-regular-file-v1`，plan显示空内容摘要与准确旧guard/tombstone。无lock的准确空guard仅支持guard-fsync崩溃恢复，不授予删除权。规划拒绝固定元数据stage和所有metadata/initial-intent前缀；首次apply还要求投影target、确定性stage和准确per-file intent都不存在。`APPLYING`落盘后，每个文件以随机plan-bound intent inode为所有权锚，经hard link发布stage/target；intent保留到`ACTIVE`记录同一target inode后才清理。恢复必须证明intent/stage/target是同一inode，不能采纳仅字节相同的外来文件。元数据转换同样要求准确metadata intent与固定stage同inode。任何其它既有intent/stage均保留并fail closed。目录描述符、`O_NOFOLLOW`、摘要复核、独占hard-link与unlink前inode复核缩小TOCTOU窗口；POSIX `fcntl`仍只约束协作Factory进程，不能抵抗root、内核、文件系统/存储故障或其它特权写者。

CLI的暂停/恢复操作假定调用者已经通过本机操作系统权限进入可信管理边界。工作流owner转换即使声明`actor-kind=human`也不会通过，除非同时提供由已配置验证器校验的短期绑定断言。v0.4的HMAC验证器是本地参考实现；对外提供审批入口仍必须由认证适配器校验用户、会话、操作内容、有效期与一次性挑战，不能把公开IM消息或Agent自报身份直接转换成人工批准。

v0.6 `team approve-plan`进一步要求操作者回填完整规格scope hash，但其身份仍只来自本机操作系统权限。它适合单机参考和受控管理，不是互联网审批协议。OpenClaw approval relay必须与公开intake使用不同账号、频道、workspace，并把远程认证结果转换为同等绑定的短期断言。

Host Runner刻意需要单独开关，也不会继承Token、SSH Agent、云凭据或用户HOME。它仍共享主机内核和网络，不能执行恶意第三方代码；`--allow-host-runner`表示操作者接受这一参考边界，不会把它提升为生产沙箱。v0.8的Docker探针也不是长期Runner：它只用于GitHub-hosted一次性Worker上的三轮一致性证据，完成后删除容器/卷/网络，不应改为PVE或业务Linux的自建Runner。

Lite模式不等于“安全沙箱”：它移除了常驻控制器和外部副作用，却仍依赖采用平台正确隔离工具。平台把某个Markdown角色映射成Shell、网络或写权限前，必须由项目所有者重新审阅；Factory生成文件中的`allowed_tools`不是可执行授权令牌。
