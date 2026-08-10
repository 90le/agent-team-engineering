---
name: triage-work-item
description: Classify, deduplicate, risk-score, and propose a disposition for normalized software feedback or GitHub issues. Use when a product triage role must compare a work item with product principles, identify missing evidence, label risk and scope, or recommend accept, duplicate, reject, clarify, or owner review without writing code.
---

# Triage Work Item

1. Verify the work item is normalized and the expected revision is current.
2. Compare the problem with authoritative product principles, target users and explicit non-goals.
3. Search existing work items using stable identifiers and semantics; cite a canonical item for duplicates.
4. Score user value, frequency, strategic fit, confidence, effort uncertainty and risk separately. Do not hide uncertainty in one numeric score.
5. Classify security, identity, payments, privacy, deletion, database, infrastructure and secret-related work as requiring owner review.
6. Return one proposed disposition: `ACCEPT`, `DUPLICATE`, `REJECT`, `CLARIFY`, or `NEEDS_OWNER`, with evidence and unanswered questions.

Do not modify source code, close disputed feedback, approve product scope, merge a PR or deploy. Stop when product principles are absent or contradictory.
