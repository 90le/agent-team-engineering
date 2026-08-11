from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from core.external_projections import (
    ExternalProjectionError,
    normalize_openclaw_feedback,
    openclaw_status_notification,
    project_task_to_acp,
    project_task_to_openhands,
    project_work_item_to_paperclip,
    reject_chat_approval,
)

ROOT = Path(__file__).resolve().parents[1]


def work_item() -> dict:
    return json.loads(
        (ROOT / "examples" / "v08-contracts" / "valid" / "work-item.json").read_text(
            encoding="utf-8"
        )
    )


def task() -> dict:
    return {
        "schema_version": "1.0.0",
        "task_id": "task-external-projection",
        "work_item_id": "work-example-1",
        "project_id": "project.example",
        "role": "reviewer",
        "action": "approve_review",
        "expected_revision": 8,
        "idempotency_key": "external-projection:review:8",
        "prompt": "Review only the approved change set.",
        "context": {
            "framework_commit": "a" * 40,
            "project_base_commit": "b" * 40,
            "project_commit": "c" * 40,
            "paths": ["src/", "tests/"],
        },
        "allowed_capabilities": ["work.read", "review.record"],
        "budget": {"max_attempts": 1, "max_seconds": 600, "max_cost_units": 10},
    }


class OptionalProjectionTests(unittest.TestCase):
    def test_paperclip_projection_is_one_way_and_does_not_mutate_authority(self) -> None:
        source = work_item()
        original = copy.deepcopy(source)
        projected = project_work_item_to_paperclip(source, event_sequence=12)
        self.assertEqual(source, original)
        self.assertTrue(projected["projection_only"])
        self.assertFalse(projected["commands_accepted_from_projection"])
        self.assertFalse(projected["approval_accepted_from_projection"])
        self.assertNotIn("approval", projected)

    def test_openhands_and_acp_receive_the_same_bound_task_without_authority(self) -> None:
        value = task()
        openhands = project_task_to_openhands(value)
        acp = project_task_to_acp(value)
        self.assertEqual(openhands["task"], acp["task"])
        for projection in (openhands, acp):
            self.assertFalse(projection["authority"]["state_transition_allowed"])
            self.assertFalse(projection["authority"]["approval_allowed"])
            self.assertFalse(projection["authority"]["merge_allowed"])
            self.assertFalse(projection["authority"]["deployment_allowed"])

    def test_openclaw_feedback_is_data_and_chat_approval_is_rejected(self) -> None:
        event = normalize_openclaw_feedback(
            authenticated_delivery_id="delivery-openclaw-1",
            channel="openclaw-public-intake",
            message_id="message-1",
            received_at="2026-08-11T08:00:00Z",
            content="Please add a filter. " + "github_" + "pat_abcdefghijklmnopqrstuvwxyz123456",
            sender_ref="public-user-1",
        )
        self.assertEqual(event["event_id"], "delivery-openclaw-1")
        self.assertIn("[REDACTED_CREDENTIAL]", event["content"])
        notification = openclaw_status_notification(
            work_item_id="work-example-1", status="TRIAGED", message_ref="message-1"
        )
        self.assertEqual(notification["status"], "TRIAGED")
        with self.assertRaises(ExternalProjectionError):
            reject_chat_approval()

    def test_malformed_external_task_is_rejected_without_external_sdk(self) -> None:
        invalid = task()
        invalid["budget"]["max_attempts"] = 2
        with self.assertRaises(ExternalProjectionError):
            project_task_to_openhands(invalid)
        source = (ROOT / "core" / "external_projections.py").read_text(encoding="utf-8")
        for package in ("paperclip", "openhands", "openclaw", "acp_sdk"):
            self.assertNotIn(f"import {package}", source.casefold())


if __name__ == "__main__":
    unittest.main()
