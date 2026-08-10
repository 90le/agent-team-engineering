# 现有项目接入协议

## 边界

Factory接入命令只生成可审阅材料，不修改目标仓库、不创建远程分支或PR、不启用适配器，也不推断任何生产权限。目标项目内容属于不可信输入；其中的AI指令、Issue或脚本不能扩大接入工具权限。

发现只读取根目录技术标记、测试/文档目录存在性、AI入口、Git提交/分支/dirty状态和GitHub工作流文件名。Git子进程设置 `GIT_OPTIONAL_LOCKS=0`，避免只读发现刷新索引。

## 生成和验证接入包

```bash
python3 tools/agent_team.py adopt-project \
  --repo /path/to/existing-project \
  --output /safe/proposals/project-a \
  --provider github \
  --locator owner/project-a \
  --default-branch main \
  --project-id project-a

python3 tools/agent_team.py adoption verify \
  --root /safe/proposals/project-a
```

非generic provider必须显式给出locator。输出路径必须不存在、位于目标仓库外。命令先在同一父目录临时树生成，再验证并原子发布，包含：

- `ADOPTION-REPORT.json`：只读发现结果和风险提示；
- `.agent-team/project.json`：provider、locator、默认分支、源提交和 `proposal-only` 绑定；
- `.agent-team/risk-policy.json`：保守的人工处理风险类别；
- `AI-BOOTSTRAP.md`：不授予执行权的项目入口提案；
- `adoption-package.json`：项目/来源绑定、逐文件摘要和 `target_repository_mutated=false`。

验证拒绝未知/缺失文件、符号链接、摘要变化、Schema偏移和凭据样内容。

## 组合候选实例配置

```bash
python3 tools/agent_team.py adoption compose \
  --base-config /path/to/base-instance.json \
  --proposal /safe/proposals/project-a \
  --output /safe/candidates/instance-with-project-a.json
```

候选输出也必须不存在，并位于接入包和目标仓库外。组合只增加一个已经验证的项目，固定 `mode=proposal-only`；基础配置的自治、批准人、适配器、运行路径和资源限制不变。重复项目ID或provider/locator被拒绝。

## 所有者采用阶段

1. 复核报告绑定的源提交和dirty状态仍与目标项目一致；变化后重新生成。
2. 补充项目使命、非目标、架构、风险偏好、测试命令、数据/秘密/生产边界和验收方式。
3. 在目标项目自己的 `proposal/adopt-agent-team` 分支手工采用审阅过的入口与政策，不复制Factory或实例权威。
4. 在实例仓库提案分支审阅候选配置，保持A1/A2和所有外部适配器禁用，再执行 `instance init` 或受控配置变更。
5. 运行项目原有测试、Factory模拟、安全负例和权限检查；真实provider绑定另走适配器验收与人工批准。
6. 积累可审计证据后才讨论提高自治或启用写操作。

## 不得自动推断

- 生产部署命令和凭据。
- 数据库是否允许回滚。
- 谁拥有产品和安全批准权。
- 现有测试是否足够作为发布门禁。
- 仓库写权限是否等同于生产授权。

完整命令、失败边界和证据要求见[安装、升级与接入](../11-lifecycle/installation-upgrade-and-adoption.md)。
