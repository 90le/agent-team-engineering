# 持久控制平面与故障恢复

## 数据边界

实例的 `.agent-team/instance.json` 声明 `runtime.state_location`。该SQLite文件、`-wal`/`-shm`、Worker目录和制品均属于运行状态，被实例 `.gitignore` 排除。数据库可能包含反馈和外部引用，按Private数据保护；秘密值仍只能位于外部秘密系统。

推荐把活动数据库放在本机具有可靠POSIX锁和断电保护的文件系统。不要直接放在NFS/SMB共享目录。备份可以复制到独立存储，但恢复时先回到受支持的本地文件系统并验证。

## 初始化与状态

```bash
python3 tools/agent_team.py runtime init --instance /path/to/instance
python3 tools/agent_team.py runtime status --instance /path/to/instance
python3 tools/agent_team.py runtime audit-verify --instance /path/to/instance
```

`init` 可重复执行同一数据库Schema，但不会升级未知的未来Schema。所有非初始化命令都要求数据库已经存在。

所有runtime命令在发现 `runtime/.factory-lifecycle-journal.json` 时拒绝运行。该日志表示Factory文件升级或回滚尚未完成；保持Worker停止和数据库暂停，使用匹配Factory的 `instance recover`，不能通过移动数据库、删除日志或relock恢复运行。

## 持久反馈、租约与转换

```bash
python3 tools/agent_team.py runtime ingest \
  --instance /path/to/instance \
  --event feedback.json \
  --idempotency-key intake:channel:message-id

python3 tools/agent_team.py runtime lease \
  --instance /path/to/instance \
  --work-item work-id \
  --actor-id agent-intake-1 \
  --role public-intake \
  --expected-revision 0 \
  --ttl-seconds 300 \
  --idempotency-key lease:work-id:revision-0:intake

python3 tools/agent_team.py runtime apply \
  --instance /path/to/instance \
  --work-item work-id \
  --action normalize \
  --actor-id agent-intake-1 \
  --role public-intake \
  --expected-revision 0 \
  --lease-id lease-id \
  --evidence evidence.json \
  --idempotency-key transition:work-id:revision-0:normalize
```

相同命令重试返回第一次已提交结果；相同幂等键携带不同请求会失败。失败转换、陈旧修订和权限拒绝在事务回滚后不会消费幂等键。非owner转换成功后自动释放租约；owner工作流批准必须同时声明 `role=owner`、`actor-kind=human`，并提供由已配置`ApprovalVerifier`验证的短期绑定断言。

HMAC参考路径需要同时提供`--approval-assertion`、权限为`0600`的`--approval-key-file`和`--approval-provider`。断言必须绑定actor、action、work item、expected revision和evidence；控制平面仅保存claim摘要、provider与证据引用，不保存签名或密钥。它用于本地契约验收，不是公网身份系统。真实接入必须由认证适配器验证人工身份与批准内容后调用核心。

## 暂停、对账与恢复顺序

```bash
python3 tools/agent_team.py runtime pause \
  --instance /path/to/instance \
  --owner-id human-owner \
  --reason "operator safety stop" \
  --idempotency-key pause:incident-id

python3 tools/agent_team.py runtime reconcile --instance /path/to/instance
python3 tools/agent_team.py runtime audit-verify --instance /path/to/instance
python3 tools/agent_team.py runtime status --instance /path/to/instance

python3 tools/agent_team.py runtime resume \
  --instance /path/to/instance \
  --owner-id human-owner \
  --reason "audit and provider state reconciled" \
  --idempotency-key resume:incident-id
```

暂停阻止新反馈、租约、转换、outbox排队和领取。已经向外部提供者发送的请求可能仍需写回结果，因此完成/失败确认和只读验证不被暂停吞掉。`reconcile` 释放过期任务租约，并把过期效果领取改为可重试或`DEAD`。

## 事务outbox

`core.control_plane.ControlPlane.queue_effect` 只接受引用同一工作项持久审计事件的效果。Worker通过 `claim_effect` 取得有期限的claim，必须在到期前调用 `complete_effect` 或 `fail_effect`；过期确认会被拒绝并等待对账回收。v0.4参考Worker在领取前验证审计链，宿主再验证实例绑定、Manifest、输入Schema、事件授权和显式实现。真实适配器必须：

- 把outbox的幂等键传给外部提供者，或在重试前按稳定外部标识对账。
- 不把claim token当成外部凭据。
- 返回脱敏、受大小限制的结构化结果，不保存响应原文和秘密。
- 在尝试上限后保留`DEAD`供人工处置，不伪造成功。

`provider-idempotency`只有在提供者按稳定key真正去重时才能使用；`reconcile-before-retry`必须先查询稳定外部标记；`at-most-once`必须把`max_attempts`限制为1。详细契约见[适配器SDK](../10-adapters/sdk-isolation-and-approval.md)。

## 验证式备份与非覆盖恢复

```bash
python3 tools/agent_team.py runtime backup \
  --instance /path/to/instance \
  --output /safe/new/path/control-plane.sqlite3
```

备份使用SQLite在线backup API，重新打开副本，验证Schema、工作项修订和完整审计链后才原子发布；目标必须不存在。建议保存工具版本、实例提交、备份SHA-256和审计head，并把备份加密复制到独立故障域。

恢复先复制实例仓库到新位置，确保配置的state路径不存在，再执行：

```bash
python3 tools/agent_team.py runtime restore \
  --instance /new/path/instance \
  --backup /verified/backup/control-plane.sqlite3
```

恢复不会覆盖现场数据库。完成后依次运行 `audit-verify`、`status`、项目/适配器对账和只读验收；未核对外部效果前保持暂停。

## 故障矩阵

| 故障点 | 恢复行为 |
|---|---|
| 状态事务提交前进程退出 | 状态、审计和幂等记录全部回滚 |
| 状态/outbox提交后、Worker领取前退出 | 下次Worker继续领取PENDING记录 |
| Worker领取后退出 | claim到期后reconcile并重试，尝试数保留 |
| 提供者成功、完成确认前退出 | 使用相同幂等键重试或先对账，不能盲目创建第二份 |
| Agent任务中断 | 租约到期并reconcile，新的Agent从当前revision接手 |
| 审计或工作项被意外改写 | `audit-verify`失败，保持暂停并从verified backup恢复调查 |
| 数据库Schema高于当前工具 | 拒绝打开，不尝试降级写入 |
| Factory升级或回滚中断 | runtime拒绝运行；验证外部恢复包并按生命周期日志返回操作前版本 |
