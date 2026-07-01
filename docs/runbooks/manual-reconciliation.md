# Manual reconciliation of ambiguous delivery

`unknown` means Kakao may have accepted a message but the application cannot
prove it. Automatic resend or continuation is forbidden.

1. Suspend the Scheduler job if another invocation is imminent.
2. Read the immutable edition hash and per-message checkpoints. Never edit the
   frozen content/order while reconciling.
3. Inspect Kakao "나와의 채팅" for the edition marker and ordered message
   numbers. Compare only metadata/counts; do not copy message content into logs.
4. If every frozen message is visibly present, mark each as acknowledged using
   the reconciliation CLI with operator identity and an audit reason.
5. If any status remains uncertain, leave the edition `unknown` and accept a
   missed/partial briefing. Do not resend it.
6. Resume Scheduler only after the edition is terminal and preserve the audit
   event, operator, timestamp, and observed evidence.

An acknowledged edition rerun is a no-op. A stale `pending` checkpoint is
promoted to `unknown`, never interpreted as unsent.
# Adapter operation

> **Implementation status:** no reconciliation CLI is currently exposed. Do
> not edit Firestore by hand: that can bypass transition validation and audit
> fields. Until an authenticated operator command is implemented and tested,
> leave the edition `unknown`, keep automatic delivery suspended, and accept the
> missed briefing.

The future operator-authorized persistence command must call
`reconcile_unknown_as_acknowledged(run_date, position, now, reason)`. A nonempty
audit reason is mandatory. The operation only supports `unknown` to
`acknowledged`; it cannot return a message to `pending` or authorize resend.
