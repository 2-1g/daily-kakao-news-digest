# Source compliance approval

Collection fails closed unless every used entry in `config/sources.yaml` is
explicitly approved and unexpired. Checked-in approvals are short-lived review
records, not permanent permission; expiry is a safe deployment blocker.

For each source, an accountable operator must review the current upstream terms
and record:

1. owner and permitted API/RSS mechanism;
2. exactly which metadata/snippet fields may be fetched;
3. attribution and original-link requirements;
4. retention period (the default design retains no article body);
5. terms URL, review date, expiry date, and reviewer evidence.

Only after that review may the operator set `approved: true` and a future
`expires_on`. Approval is a legal/operational decision, not something the
application can infer. Re-run the test suite after every registry change. Never
approve scraping article pages: the adapters are designed for structured
metadata/snippets only.

Before each deployment, verify that at least one configured adapter has valid
credentials and a current approval. If not, keep the Scheduler disabled and
live sending false.
