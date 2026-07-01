"""Deterministic normalization for lawful article metadata."""

from __future__ import annotations

from dataclasses import replace
from datetime import timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import ArticleCandidate


TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referrer"}


def normalize_url(url: str) -> str:
    """Return a stable citation URL without common tracking parameters."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and not ((parts.scheme == "http" and parts.port == 80) or
                           (parts.scheme == "https" and parts.port == 443)):
        host += ":%d" % parts.port
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in TRACKING_KEYS and not key.lower().startswith("utm_")]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(sorted(query)), ""))


def normalize_article(article: ArticleCandidate) -> ArticleCandidate:
    published = article.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return replace(
        article,
        publisher=article.publisher.strip().lower().removeprefix("www."),
        title=" ".join(article.title.split()),
        url=normalize_url(article.url),
        published_at=published.astimezone(timezone.utc),
        language=(article.language or "und").lower(),
        region=_region(article.region),
    )


def _region(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"kr", "korea", "south korea", "domestic", "대한민국", "한국"}:
        return "domestic"
    return "overseas"
