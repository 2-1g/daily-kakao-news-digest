# IAM contract

Use separate runtime, scheduler, bootstrap, and operator identities. Do not grant
project-wide Editor/Owner to an application identity.

| Identity | Required access | Explicitly excluded |
|---|---|---|
| `news-digest-runtime` | Firestore document read/write for edition and rotation metadata; Secret Manager accessor on the active Kakao token only; logs writer | secret version creation/destruction, OAuth bootstrap authorization codes, unrelated credentials, Cloud Run administration |
| `news-digest-scheduler` | `run.jobs.run` on this job only; service-account token creation for itself | Firestore, secrets, other jobs |
| `news-digest-bootstrap` | access to Kakao bootstrap client secret and permission to add a candidate token version | runtime execution, unrelated secrets |
| human operator | deploy job/config, inspect structured status, transactionally reconcile unknown sends, suspend scheduler, rotate/retire versions | routine application execution with bootstrap credentials |

Recommended controls:

- Bind Secret Manager access at the individual-secret level.
- Keep the bootstrap identity disabled except during an attended bootstrap or
  reauthorization session.
- Restrict Firestore to the edition, lease, delivery checkpoint, and token
  pointer collections used by the package.
- Set Cloud Scheduler retry count and Cloud Run Job `maxRetries` to zero. The
  application owns pre-delivery recovery; delivery ambiguity is never retried.
- Do not put token values, article bodies, or OAuth authorization codes in
  manifests, images, Firestore, or structured logs.
- Before deployment, replace every `PROJECT_ID`, `REGION`, and `IMAGE_TAG`
  placeholder and inspect the rendered IAM policy.
