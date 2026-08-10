---
name: deploy-and-rollback
description: Deploy an already built and verified immutable artifact through a restricted release interface, monitor health, and roll back to a known-good digest when policy allows. Use for staging or production release execution only after required checks and approvals; never use to edit source, rebuild artifacts, run arbitrary Shell, or infer authorization from chat.
---

# Deploy and Roll Back

1. Re-read current work-item state, expected revision, risk policy, approval and expiry immediately before the side effect.
2. Verify the approval is issued by an authorized identity and binds the exact environment, action and artifact digest.
3. Confirm staging used the same digest and required evidence is still valid.
4. Invoke only the restricted deployment API with an idempotency key; never substitute an arbitrary command.
5. Record deployment identity, digest, environment, start/end time and health evidence.
6. Observe the configured health window. Mark success only after explicit verification.
7. On a qualifying failure, deploy the recorded known-good digest and verify recovery. Treat database rollback as a separate approved plan.

Stop without side effects on stale revision, missing approval, digest mismatch, expired evidence, unhealthy dependencies or unavailable recovery path. Never read secrets into context, modify source, rebuild the artifact or operate infrastructure outside the approved release scope.
