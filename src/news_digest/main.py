"""Local dry-run CLI. Live adapters are intentionally configured by deployment code."""

import argparse
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .auth import OAuthManager
from .cloud import FirestoreEditionStore, SecretManagerTokenStore
from .compose import DigestComposer
from .config import ComplianceRegistry
from .dedupe import cluster_articles
from .http import KakaoHttpTransport, KakaoOAuthHttpRefresher, UrllibHttpClient
from .kakao import KakaoClient, validate_messages
from .pipeline import DigestPipeline
from .rank import rank_clusters
from .sources import GdeltAdapter, NaverAdapter
from .summarize import summarize


def _env(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "")
    if required and not value:
        raise RuntimeError("required environment variable is missing: " + name)
    return value


def collect_and_compose() -> List[str]:
    """Lawful deterministic production path; configured sources still fail closed."""
    registry = ComplianceRegistry.from_path(Path(os.environ.get(
        "SOURCE_REGISTRY", "config/sources.yaml")))
    http = UrllibHttpClient()
    adapters = []
    naver_id, naver_secret = _env("NAVER_CLIENT_ID", False), _env("NAVER_CLIENT_SECRET", False)
    if naver_id and naver_secret:
        adapters.append(NaverAdapter(registry, http, naver_id, naver_secret,
                                     os.environ.get("NEWS_QUERY", "정치 경제 사회")))
    if os.environ.get("ENABLE_GDELT", "false").lower() == "true":
        adapters.append(GdeltAdapter(registry, http,
                                     os.environ.get("GDELT_QUERY", "politics economy society")))
    if not adapters:
        raise RuntimeError("no compliant source adapter configured")
    today = datetime.now(timezone.utc).date()
    articles = [article for adapter in adapters for article in adapter.collect(today)]
    items = [summarize(cluster) for cluster in rank_clusters(cluster_articles(articles))]
    return list(DigestComposer().compose(items, today.isoformat()).messages)


def run_cloud() -> int:
    project = _env("GOOGLE_CLOUD_PROJECT")
    messages_file = os.environ.get("NEWS_DIGEST_MESSAGES_FILE")
    messages = _read_messages(Path(messages_file)) if messages_file else collect_and_compose()
    live = os.environ.get("NEWS_DIGEST_LIVE_SEND", "false").lower() == "true"
    store = FirestoreEditionStore(project)
    token_store = SecretManagerTokenStore(project, _env("KAKAO_TOKEN_SECRET"))
    oauth = OAuthManager(token_store, KakaoOAuthHttpRefresher(
        _env("KAKAO_CLIENT_ID"), _env("KAKAO_CLIENT_SECRET", False)))
    pipeline = DigestPipeline(store, oauth, KakaoClient(KakaoHttpTransport()),
                              lambda: datetime.now(timezone.utc))
    result = pipeline.run(os.environ.get("CLOUD_RUN_EXECUTION", socket.gethostname()),
                          messages, dry_run=not live)
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    return 0 if result.status in ("dry_run", "acknowledged", "missed") else 2


def _read_messages(path: Path) -> List[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("messages file must contain a JSON string list")
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Kakao digest without network I/O")
    parser.add_argument("command", nargs="?", choices=("run",))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--messages", type=Path,
                        help="JSON file containing a list of final Kakao message strings")
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.messages:
            os.environ["NEWS_DIGEST_MESSAGES_FILE"] = str(args.messages)
        if args.dry_run:
            os.environ["NEWS_DIGEST_LIVE_SEND"] = "false"
        return run_cloud()
    if not args.dry_run or args.messages is None:
        parser.error("local validation requires --dry-run --messages")
    try:
        payload = _read_messages(args.messages)
    except ValueError as exc:
        parser.error(str(exc))
    envelopes = validate_messages(payload)
    print(json.dumps({"status": "dry_run", "messages": len(envelopes),
                      "characters": sum(len(item.text) for item in envelopes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
