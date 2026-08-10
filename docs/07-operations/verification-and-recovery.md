# 验证、恢复和停止机制

## 日常验证

```bash
tools/verify.sh
```

验证包括结构、JSON、链接、秘密模式、Skill、角色引用、单元测试和两种模拟路径。

## 冷启动

提交后运行：

```bash
tools/cold-start.sh
```

脚本从当前 Git 仓库克隆到独立临时目录，重新执行验证、测试、完整模拟和 `git fsck`。未提交文件不会进入克隆，因此该测试只能针对明确提交。

## 故障和恢复

- 修订冲突：拒绝过期结果，重新读取当前工作项。
- 外部服务失败：按幂等键重试，达到上限后进入人工队列。
- Runner 中断：销毁工作区，从最后已记录状态重新派发。
- 生产健康失败：只回滚到已知健康的制品摘要；数据库迁移另行处理。
- 安全事件：停止入口、撤销Agent凭据、保留审计、人工调查。

系统必须提供全局停止开关；停止后不得丢弃已持久化状态或伪造成功结果。

## v0.3持久状态

实例控制平面使用 `runtime pause` 进入全局安全停止；已完成的幂等请求仍可回放查询结果，新转换和新outbox领取被拒绝。恢复前先运行 `runtime reconcile`、`runtime audit-verify` 和 `runtime status`，再由人工owner说明原因执行 `runtime resume`。

使用 `runtime backup` 通过SQLite在线备份API产生一致副本，备份在发布前会重新打开并验证审计。`runtime restore` 只写入不存在的目标数据库，不覆盖现场；先在新路径验证再切换。完整命令和故障矩阵见[持久化与故障恢复](../09-control-plane/persistence-and-recovery.md)。
