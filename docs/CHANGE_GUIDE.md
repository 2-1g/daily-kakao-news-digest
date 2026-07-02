# Change guide

Use this guide when starting a new coding session. Ask the agent to read
`AGENTS.md`, `docs/PROJECT_CONTEXT.md`, and `docs/DEPLOYMENT_STATE.md` before
changing code or cloud configuration.

## Example request

> In the `daily-kakao-news-digest` repository, read the project context and
> deployment state first. Change the delivery time to 07:30 KST, update tests
> and documentation, deploy safely, and verify the Scheduler's next run. Do not
> expose or commit secrets.

## Common changes

| Desired change | Primary surface | Required verification |
|---|---|---|
| Delivery time | Cloud Scheduler cron and timezone | Describe Scheduler and inspect next run |
| Topic priorities or ratios | ranking/composition configuration and tests | Editorial metrics and representative fixtures |
| Message length/count | composer plus Kakao contract tests | Local validation and unit tests |
| Add a news source | adapter plus `config/sources.yaml` | Terms review, permitted fields, attribution, failure behavior |
| Improve summaries | summarizer implementation/configuration | Evidence coverage, cost ceiling, fallback behavior |
| Change Kakao app | attended OAuth bootstrap | Hidden credential handling and one authorized smoke test |

## Change protocol

1. Read the context and current deployment state; do not infer production state
   solely from manifests.
2. Keep credentials in Secret Manager and inspect staged changes for leaks.
3. Add or update regression tests before behavior-changing edits when coverage
   is missing.
4. Run the targeted tests and the full test suite.
5. Deploy an immutable image and retain zero platform retries.
6. Verify the cloud state and update `DEPLOYMENT_STATE.md` without adding
   sensitive identifiers or logs.
7. Commit and push only after a secret scan.

## Source-policy renewal

The `expires_on` field is deliberately short-lived so the application fails
closed if provider terms, fields, or attribution rules have not been reviewed
recently. Extending it does not itself cost money. To renew:

1. Review the provider's current official terms and API documentation.
2. Confirm the same metadata fields and retention behavior are still allowed.
3. Record the new review date and a reasonable next review deadline.
4. Run source-policy and adapter tests, then deploy the updated image.

Do not extend the date mechanically without reviewing the terms.

The scheduled digest sends a D-7 Kakao reminder. Kakao's self-message API does
not expose replies to this application, so replying in self-chat cannot approve
or mutate configuration. In the current immutable-image deployment,
`config/sources.yaml` is bundled into the container; a reviewed date change
therefore requires a new image and Cloud Run Job deployment.
