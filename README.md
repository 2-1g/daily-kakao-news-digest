# Daily Kakao News Digest

This repository implements the approved daily personal news-digest plan in
small, testable slices. The current slice provides typed source records and a
fail-closed compliance registry plus Naver, RSS, and GDELT metadata adapters.

## Safety boundary

- Only explicitly approved, unexpired registry entries may run.
- Adapters consume permitted metadata/snippets only; they never fetch article
  pages or retain article bodies.
- Credentials are injected by callers and are never read from repository files.
- Network clients are injected, so unit tests make no live requests.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`config/sources.yaml` is JSON-compatible YAML so it can be loaded with the
Python standard library. Its sample entries are intentionally unapproved until
an operator verifies current terms and fills every required compliance field.

