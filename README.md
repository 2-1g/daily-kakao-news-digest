# Daily Kakao News Digest

This repository implements the approved daily personal news-digest plan in
small, testable slices. It includes fail-closed source adapters, deterministic
editorial composition, conservative delivery state, and Google Cloud adapters.

## Safety boundary

- Only explicitly approved, unexpired registry entries may run.
- Adapters consume permitted metadata/snippets only; they never fetch article
  pages or retain article bodies.
- Credentials are injected by callers and are never read from repository files.
- Network clients are injected, so unit tests make no live requests.
- `run` defaults to a cloud dry run. Kakao delivery is impossible unless
  `NEWS_DIGEST_LIVE_SEND=true` is explicitly configured after an authorized
  smoke test.

## Commands

Local, network-free payload validation:

```bash
news-digest --dry-run --messages ./messages.json
```

Cloud Run's manifest invokes `news-digest run`. This loads Firestore and Secret
Manager adapters and either collects approved sources or reads the optional
`NEWS_DIGEST_MESSAGES_FILE`. With the checked-in manifest it freezes a dry-run
edition and sends nothing. Operators must approve current source policies and
configure `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` or `ENABLE_GDELT=true` before
the collection path can run.

The runtime service account needs access only to the configured edition
collection and named Kakao token secret. Secret Manager's `active` version
alias is the authoritative token pointer; a previous version remains enabled
for rollback/grace retirement.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`config/sources.yaml` is JSON-compatible YAML so it can be loaded with the
Python standard library. Its sample entries are intentionally unapproved until
an operator verifies current terms and fills every required compliance field.
