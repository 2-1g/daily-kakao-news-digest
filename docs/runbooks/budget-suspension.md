# Budget alert and suspension

The local model guard rejects a request whose estimate would exceed $0.10 per
run. The $5 monthly cloud/model budget is asynchronous and cannot be enforced
as a synchronous billing cutoff.

- **50%:** inspect source/model request counts and forecast month-end spend.
- **80%:** reduce optional model work and prepare to suspend.
- **100%:** disable the Scheduler job, verify no Cloud Run execution is active,
  and record a budget-suspension incident.

Do not delete state, secrets, or the Cloud Run Job during suspension. Resume
only after the operator approves a new billing period or budget and verifies
the local per-run guard in dry-run mode. Treat delayed billing data explicitly;
budget alerts are notification evidence, not proof that spend stopped exactly
at the threshold.
