"""Hard authorization rules; prompts and role personas cannot override these checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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


PACK_ROOT = Path(__file__).resolve().parents[1] / "team-packs" / "software-delivery"


def _load_policy() -> tuple[dict[str, frozenset[str]], dict[str, ToolPolicy]]:
    team = json.loads((PACK_ROOT / "team-pack.json").read_text(encoding="utf-8"))
    tools = json.loads((PACK_ROOT / "tool-policy.json").read_text(encoding="utf-8"))
    capabilities = {
        role["id"]: frozenset(role.get("capabilities", [])) for role in team.get("roles", [])
    }
    tool_policies = {
        role_id: ToolPolicy(
            allowed=frozenset(policy.get("allowed", [])),
            denied=frozenset(policy.get("denied", [])),
        )
        for role_id, policy in tools.get("roles", {}).items()
    }
    return capabilities, tool_policies


ROLE_CAPABILITIES, ROLE_TOOLS = _load_policy()


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
