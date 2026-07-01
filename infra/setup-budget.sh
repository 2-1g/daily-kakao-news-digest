#!/bin/sh
set -eu
: "${GOOGLE_CLOUD_BILLING_ACCOUNT:?set GOOGLE_CLOUD_BILLING_ACCOUNT}"
: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
BUDGET_USD="${NEWS_DIGEST_MONTHLY_BUDGET_USD:-5}"
echo "Creating asynchronous 50/80/100% alerts; this is NOT a hard stop."
gcloud billing budgets create \
  --billing-account="$GOOGLE_CLOUD_BILLING_ACCOUNT" \
  --display-name="daily-kakao-news-digest-${GOOGLE_CLOUD_PROJECT}" \
  --budget-amount="${BUDGET_USD}USD" \
  --filter-projects="projects/${GOOGLE_CLOUD_PROJECT}" \
  --threshold-rule=percent=0.50 \
  --threshold-rule=percent=0.80 \
  --threshold-rule=percent=1.00
echo "Verify recipients, then follow docs/runbooks/budget-suspension.md manually at 100%."
