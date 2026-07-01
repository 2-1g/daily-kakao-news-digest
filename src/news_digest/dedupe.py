"""Conservative, deterministic same-event clustering."""

import hashlib
import re
from collections import defaultdict
from typing import Iterable, List, Set

from .models import ArticleCandidate, EventCluster
from .normalize import normalize_article


TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
STOP = {"관련", "대한", "오늘", "속보", "단독", "정부", "기자", "뉴스", "발표"}


def headline_tokens(title: str) -> Set[str]:
    return {token.lower() for token in TOKEN.findall(title) if token not in STOP}


def cluster_articles(articles: Iterable[ArticleCandidate], threshold: float = 0.58) -> tuple[EventCluster, ...]:
    normalized = sorted((normalize_article(a) for a in articles),
                        key=lambda a: (a.published_at, a.publisher, a.url), reverse=True)
    groups: List[List[ArticleCandidate]] = []
    for article in normalized:
        tokens = headline_tokens(article.title)
        destination = None
        best = threshold - 1e-12
        for group in groups:
            score = max((_similarity(tokens, headline_tokens(other.title)) for other in group), default=0)
            if score > best:
                best, destination = score, group
        if destination is None:
            groups.append([article])
        else:
            destination.append(article)
    return tuple(_to_cluster(group) for group in groups)


def _similarity(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _to_cluster(articles: List[ArticleCandidate]) -> EventCluster:
    unique = []
    seen_urls = set()
    for article in articles:
        if article.url not in seen_urls:
            unique.append(article)
            seen_urls.add(article.url)
    lineage = defaultdict(list)
    for article in unique:
        lineage[article.metadata.get("syndication_id", "")].append(article.publisher)
    syndicated = sorted({publisher for key, publishers in lineage.items() if key and len(publishers) > 1
                         for publisher in publishers[1:]})
    independent = sorted({a.publisher for a in unique} - set(syndicated))
    primary = unique[0]
    signature = "|".join(sorted(headline_tokens(primary.title)))
    event_id = hashlib.sha256(signature.encode()).hexdigest()[:16]
    metadata = primary.metadata
    return EventCluster(event_id, tuple(unique), tuple(independent), tuple(syndicated),
                        metadata.get("category", "general"), primary.region or "overseas",
                        metadata.get("investment_relevance", "false").lower() == "true")
