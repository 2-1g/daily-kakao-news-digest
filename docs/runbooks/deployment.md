# Google Cloud deployment checklist

This is a reviewable procedure, not evidence that deployment occurred. No cloud
resource or live message is created by the repository checkout or test suite.

## 1. Local and project preflight

1. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
2. Build the image from `Dockerfile` and run the local network-free validator.
3. Select a non-production Google Cloud project and replace every `PROJECT_ID`,
   `REGION`, and `IMAGE_TAG` placeholder in `infra/*.yaml`; never apply the
   checked-in templates literally.
4. Enable Cloud Run, Cloud Scheduler, Firestore, Secret Manager, Artifact
   Registry, Cloud Build, and Cloud Billing Budget/notification support.
5. Create Firestore in Native mode and confirm the intended region and the
   `news_digest_editions` collection boundary.

## 2. Identities and secrets

Create distinct runtime, scheduler, bootstrap, and human-operator identities
and apply the least-privilege contract in [`../../infra/iam.md`](../../infra/iam.md).
The runtime needs Firestore access only to edition documents and Secret Manager
access only to the named active Kakao token. Do not grant Owner or Editor.

Complete the attended [OAuth bootstrap](oauth-bootstrap.md). The current repo
does not implement that bootstrap CLI, so this is a deployment blocker until a
reviewed operator tool supplies a token secret with an `active` version alias.
Do not put `KAKAO_CLIENT_SECRET`, access tokens, or refresh tokens in image
layers or manifests.

The live refresh path also requires `KAKAO_CLIENT_ID` and, when the Kakao app
uses one, `KAKAO_CLIENT_SECRET`. The checked-in manifest intentionally does not
wire those credentials. Inject them from individually scoped secrets during a
reviewed deployment; never add literal values to `infra/cloudrun-job.yaml`.

## 3. Source and cost gates

Complete [source approval](source-approval.md). Configure a USD $5/month Cloud
Billing Budget with asynchronous 50/80/100% alerts and validate the recipient.
Follow [budget suspension](budget-suspension.md) at 100%. The current pipeline
does not call an LLM; do not add one until a tested $0.10/run synchronous model
estimate guard exists.

## 4. Deploy safely

Build and push an immutable image tag, render the manifests, and inspect the
diff before applying. Keep all of these controls unchanged:

- Cloud Run `taskCount: 1`, `maxRetries: 0`, and one runtime identity;
- Scheduler `0 8 * * *`, `Asia/Seoul`, and `retryCount: 0`;
- `NEWS_DIGEST_LIVE_SEND=false`;
- no plaintext secret values in manifests.

Run a manual Cloud Run Job execution while live send remains false. Confirm a
`dry_run` result, one immutable Firestore edition/hash, no Kakao request, and no
secret in logs. Inspect the Scheduler's next fire time and ensure it resolves to
08:00 KST.

## 5. Live opt-in (external side effect)

Live sending is fail-closed and requires an explicit operator decision. Only
after source approval, OAuth, dry-run, IAM, budget alerts, and recovery
procedures pass may an operator change `NEWS_DIGEST_LIVE_SEND` to `true` for one
authorized self-message smoke test. Verify order, links, limits, acknowledgement,
and acknowledged rerun no-op. Restore `false` if any observation is ambiguous.

An injected timeout/real ambiguous send must become `unknown`; never retry it.
Follow [manual reconciliation](manual-reconciliation.md). Because the current
repo has no reconciliation CLI and this work has not performed a live smoke
test, unattended live enablement remains explicitly unverified.
