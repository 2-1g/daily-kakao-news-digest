# Project context

## Purpose

Daily Kakao News Digest is a private-use news briefing delivered to the owner's
KakaoTalk self-chat. It reduces manual news browsing and supports general
awareness plus personal investment research. It is not investment advice.

## Editorial intent

- General world awareness and investment relevance are weighted roughly 60:40.
- Domestic and international coverage targets roughly 60:40 when the available
  evidence supports it.
- Politics, economics, and society receive the most attention. Entertainment
  and sports are secondary unless unusually important.
- The main briefing should normally be readable within about 20 minutes, with
  a smaller supplementary section readable within about 5 minutes.
- Item counts are flexible. Do not manufacture filler on quiet days or omit
  major developments merely to meet a fixed count.
- Avoid dependence on one publisher. Preserve publisher attribution and links,
  and distinguish sourced facts from synthesis.

## System shape

1. Cloud Scheduler invokes one Cloud Run Job at 08:00 Asia/Seoul.
2. Approved metadata APIs provide article candidates; article bodies are not
   scraped or retained.
3. Candidates are normalized, clustered, ranked, summarized, and composed into
   Kakao-safe message chunks.
4. Firestore stores the daily edition, lease, and delivery checkpoints to
   prevent unsafe automatic retries.
5. Secret Manager stores source credentials and the versioned Kakao OAuth token.
6. Kakao's self-message API delivers the briefing.

The default summarizer is deterministic and extractive. Optional model-based
synthesis is disabled until separately configured and cost-reviewed.

## Safety invariants

- This repository is public. Never commit credentials, OAuth codes or tokens,
  personal identifiers, billing data, or production logs.
- Live delivery must remain single-task with platform retries disabled.
- An ambiguous Kakao delivery is never retried automatically.
- A source may run only while its registry policy is approved and unexpired.
- Source-policy expiry is a review control, not a subscription or billing date.

## Where to look next

- Current operation: [`DEPLOYMENT_STATE.md`](DEPLOYMENT_STATE.md)
- Common modifications: [`CHANGE_GUIDE.md`](CHANGE_GUIDE.md)
- Deployment procedure: [`runbooks/deployment.md`](runbooks/deployment.md)
- OAuth recovery: [`runbooks/oauth-bootstrap.md`](runbooks/oauth-bootstrap.md)
- Source review: [`runbooks/source-approval.md`](runbooks/source-approval.md)
