# Deployment state

Last verified: 2026-07-02 (Asia/Seoul)

This file intentionally records no project ID, account address, secret value,
OAuth code, token, billing identifier, or production log content.

## Active production configuration

| Component | State |
|---|---|
| Cloud Run Job | Deployed in Seoul region; one task; zero platform retries |
| Cloud Scheduler | Enabled at `0 8 * * *`, timezone `Asia/Seoul` |
| Kakao delivery | Live self-message mode enabled |
| Kakao OAuth | Active token version installed in Secret Manager |
| Firestore | Native database configured for edition and delivery state |
| Budget guardrail | Monthly budget alerts configured; alerts are not a hard spending cap |
| Model summarizer | Disabled |
| Naver metadata source | Enabled |
| GDELT direct source | Temporarily disabled after rate limiting |

An authorized Kakao self-message smoke test succeeded. A Scheduler-to-Cloud-Run
invocation also succeeded using the official Cloud Run v2 job endpoint. A second
deliberate same-day invocation was rejected by the edition lease, demonstrating
duplicate protection rather than a scheduled-run failure.

## Known limitations and follow-ups

- Direct GDELT collection is disabled, so international breadth currently
  depends mainly on international reporting surfaced through the enabled search
  source. Add resilient backoff or another reviewed international source before
  promising a strict 60:40 split.
- Source policies in `config/sources.yaml` expire on 2026-08-01. Re-check the
  provider terms and update `reviewed_on` and `expires_on` before that date. The
  daily briefing automatically includes a Kakao D-7 reminder on 2026-07-25.
- The deterministic summarizer may be less fluent than a model-based Korean
  synthesis, but it avoids additional model cost and API credentials.
- Cloud Billing budget alerts notify; they do not automatically stop resources.

## Health checks

Operators can verify without reading secret payloads:

1. Scheduler state is enabled and its next run is 08:00 KST.
2. The latest Cloud Run execution completed.
3. Structured logs contain no secret-shaped fields.
4. The Kakao token secret has an `active` alias.
5. The daily Firestore edition reached `acknowledged`, `missed`, or another
   documented terminal state.

If delivery becomes `unknown`, do not rerun. Follow
[`runbooks/manual-reconciliation.md`](runbooks/manual-reconciliation.md).
