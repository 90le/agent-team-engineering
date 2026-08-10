"""Hard authorization rules; prompts and role personas cannot override these checks."""

from __future__ import annotations

from dataclasses import dataclass

from core.models import Actor, RiskLevel, WorkItem


class PolicyError(RuntimeError):
    """Base class for denied actions."""


class PermissionDenied(PolicyError):
    pass


class SeparationOfDutiesViolation(PolicyError):
    pass


@dataclass(frozen=True)
class ToolPolicy:
    allowed: frozenset[str]
    denied: frozenset[str]


ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "public-intake": frozenset({"feedback.normalize", "feedback.queue"}),
    "triage": frozenset({"work.triage"}),
    "product": frozenset({"spec.write"}),
    "builder": frozenset({"implementation.start", "pr.open"}),
    "qa": frozenset({"ci.record", "staging.accept"}),
    "reviewer": frozenset({"review.approve"}),
    "release": frozenset({"staging.deploy", "production.deploy"}),
    "operations": frozenset({"production.verify", "production.rollback", "work.close"}),
    "owner": frozenset({"plan.approve", "production.approve"}),
}

ROLE_TOOLS: dict[str, ToolPolicy] = {
    "public-intake": ToolPolicy(
        allowed=frozenset({"feedback.submit"}),
        denied=frozenset({"shell", "git.write", "github.write", "deploy", "secrets.read"}),
    ),
    "builder": ToolPolicy(
        allowed=frozenset({"workspace.write", "git.branch", "git.commit", "pr.create"}),
        denied=frozenset({"git.main.push", "pr.merge", "deploy", "secrets.read"}),
    ),
    "reviewer": ToolPolicy(
        allowed=frozenset({"repository.read", "pr.comment", "check.report"}),
        denied=frozenset({"author.branch.write", "pr.merge", "deploy"}),
    ),
    "release": ToolPolicy(
        allowed=frozenset({"artifact.read", "staging.deploy", "production.deploy-approved"}),
        denied=frozenset({"source.write", "artifact.build", "shell.arbitrary"}),
    ),
}


UNTRUSTED_DIRECTIVE_MARKERS = (
    "ignore previous",
    "ignore all instructions",
    "system prompt",
    "执行命令",
    "运行shell",
    "读取密码",
    "curl http",
    "docker.sock",
)

CRITICAL_MARKERS = ("删除所有数据", "泄露密钥", "关闭审计", "绕过审批")
HIGH_MARKERS = ("密码", "权限", "支付", "生产数据库", "删除用户", "pve", "群晖")
MEDIUM_MARKERS = ("数据库", "接口变更", "登录", "迁移", "依赖升级")


def require_capability(actor: Actor, capability: str) -> None:
    if capability not in ROLE_CAPABILITIES.get(actor.role, frozenset()):
        raise PermissionDenied(f"{actor.role} lacks capability {capability}")


def require_tool(actor: Actor, tool: str) -> None:
    policy = ROLE_TOOLS.get(actor.role)
    if not policy or tool not in policy.allowed or tool in policy.denied:
        raise PermissionDenied(f"{actor.role} cannot use tool {tool}")


def require_independent_reviewer(actor: Actor, item: WorkItem) -> None:
    if item.author_id and actor.id == item.author_id:
        raise SeparationOfDutiesViolation("the change author cannot approve the same change")


def contains_untrusted_directive(content: str) -> bool:
    lowered = content.casefold()
    return any(marker.casefold() in lowered for marker in UNTRUSTED_DIRECTIVE_MARKERS)


def infer_risk(content: str) -> RiskLevel:
    lowered = content.casefold()
    if any(marker.casefold() in lowered for marker in CRITICAL_MARKERS):
        return RiskLevel.CRITICAL
    if any(marker.casefold() in lowered for marker in HIGH_MARKERS):
        return RiskLevel.HIGH
    if any(marker.casefold() in lowered for marker in MEDIUM_MARKERS):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
