from __future__ import annotations

import unittest

from core.models import FeedbackEvent, WorkflowState
from core.simulation import create_work_item, run_feedback_to_release


def sample_event() -> FeedbackEvent:
    return FeedbackEvent(
        event_id="feedback-test-1",
        channel="test-im",
        message_id="message-1",
        received_at="2026-08-10T00:00:00Z",
        content="移动端反馈卡片间距太小，希望更容易阅读。",
        sender_ref="test-user",
    )


class WorkflowSimulationTests(unittest.TestCase):
    def test_default_simulation_pauses_before_production(self) -> None:
        item = run_feedback_to_release(sample_event())
        self.assertEqual(item.state, WorkflowState.PROD_APPROVAL_PENDING)
        self.assertIsNone(item.production_approved_by)
        self.assertIsNotNone(item.artifact_digest)

    def test_explicit_demo_approval_completes_flow(self) -> None:
        item = run_feedback_to_release(sample_event(), approve_production=True)
        self.assertEqual(item.state, WorkflowState.CLOSED)
        self.assertEqual(item.production_approved_by, "owner-demo")
        self.assertEqual(item.revision, len(item.audit))
        self.assertEqual(
            [event.sequence for event in item.audit], list(range(1, len(item.audit) + 1))
        )

    def test_feedback_identity_is_idempotent(self) -> None:
        first = create_work_item(sample_event())
        second = create_work_item(sample_event())
        self.assertEqual(first.id, second.id)


if __name__ == "__main__":
    unittest.main()
