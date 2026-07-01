# Budget alert and suspension

The approved design requires a local model guard to reject a request whose
estimate would exceed $0.10 per run. **No model call or model-cost guard is
currently implemented**, so adding a model is forbidden until that guard and
its tests exist. The $5 monthly cloud/model budget is asynchronous and cannot
be enforced as a synchronous billing cutoff. The repository also does not
provision a Billing Budget resource; an operator must configure and verify it
in the target billing account.

- **50%:** inspect source/model request counts and forecast month-end spend.
- **80%:** reduce optional model work and prepare to suspend.
- **100%:** disable the Scheduler job, verify no Cloud Run execution is active,
  and record a budget-suspension incident.

Configure notifications at 50%, 80%, and 100% of USD $5/month (excluding
taxes) in Cloud Billing Budgets. Route them to an operator-observed email or
Pub/Sub notification channel, then exercise a test notification where the
platform supports it. Billing export and alerts can lag, so they do not prevent
spend synchronously.

Do not delete state, secrets, or the Cloud Run Job during suspension. Resume
only after the operator approves a new billing period or budget and verifies
the local per-run guard in dry-run mode. Treat delayed billing data explicitly;
budget alerts are notification evidence, not proof that spend stopped exactly
at the threshold.
