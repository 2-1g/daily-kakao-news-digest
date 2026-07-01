# Budget alert and suspension

The opt-in model path estimates all requests locally and rejects the entire run
before network I/O if an explicit price table would exceed $0.10. It also
enforces a per-request ceiling. Prices must be reviewed when models or rates
change.

The $5 monthly budget remains asynchronous and cannot enforce a synchronous
cutoff. Create its notification thresholds with:

```bash
GOOGLE_CLOUD_BILLING_ACCOUNT=... GOOGLE_CLOUD_PROJECT=... infra/setup-budget.sh
```

The script does **not** suspend services. Verify the notification recipient.

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
