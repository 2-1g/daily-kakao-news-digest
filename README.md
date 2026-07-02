# Daily Kakao News Digest

This repository implements the executable core of the approved daily personal
news-digest plan. It includes fail-closed source adapters, deterministic
editorial composition, conservative delivery state, and Google Cloud adapters.

## Current readiness

The personal production deployment completed its authorized Kakao self-message
smoke test and is scheduled for 08:00 Asia/Seoul. A fresh checkout remains safe
and does not deploy or send anything by itself. See the sanitized
[deployment state](docs/DEPLOYMENT_STATE.md) for the current operational status;
never copy credentials or production logs into this public repository.

Future maintainers should start with:

- [project context](docs/PROJECT_CONTEXT.md)
- [deployment state](docs/DEPLOYMENT_STATE.md)
- [change guide](docs/CHANGE_GUIDE.md)

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

Create a virtual environment and install the package (cloud extras are required
only for the Cloud Run path):

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
# Cloud adapters: python -m pip install -e '.[cloud]'
```

Local, network-free payload validation (the file is a JSON list of final Kakao
message strings):

```bash
news-digest --dry-run --messages ./messages.json
```

This command validates only message count/length and performs no collection,
Firestore, Secret Manager, OAuth, or Kakao network call. `news-digest run
--dry-run` is different: it constructs cloud adapters and therefore requires
Google credentials and configured source credentials (or
`NEWS_DIGEST_MESSAGES_FILE`).

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

Operational procedures:

- [Google Cloud deployment checklist](docs/runbooks/deployment.md)
- [source compliance approval](docs/runbooks/source-approval.md)
- [Kakao OAuth bootstrap limitations](docs/runbooks/oauth-bootstrap.md)
- [manual `unknown` reconciliation](docs/runbooks/manual-reconciliation.md)
- [budget alerts and suspension](docs/runbooks/budget-suspension.md)

Attended operations:

```bash
news-digest oauth-url --redirect-uri "$KAKAO_REDIRECT_URI"
news-digest oauth-exchange --redirect-uri "$KAKAO_REDIRECT_URI" # hidden code prompt
news-digest reconcile --edition-id YYYY-MM-DD --message-index N \
  --reason "observed evidence" --operator "$USER"
```

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`config/sources.yaml` is JSON-compatible YAML so it can be loaded with the
Python standard library. Its approvals are deliberately short-lived and must
be re-reviewed before their recorded expiry date.

The default uses deterministic extractive summaries. Model synthesis requires
an explicit opt-in, nano/mini names, API key, and reviewed price JSON. Evidence
IDs remain schema-validated and failures fall back deterministically. The local
estimator rejects a run above `$0.10` before any model request. The `$5/month`
budget remains an asynchronous alert plus manual suspension, not a hard cap.
