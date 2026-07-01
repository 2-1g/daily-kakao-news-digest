"""GDELT DOC discovery adapter; publisher URLs remain sources of record."""

import json
from datetime import date, datetime, timezone
from typing import Sequence
from urllib.parse import urlencode

from news_digest.models import ArticleCandidate
from .base import CompliantAdapter, require_success


class GdeltAdapter(CompliantAdapter):
    source_id = "gdelt-doc"
    requested_fields = ("title", "url", "domain", "seendate", "language", "sourcecountry")

    def __init__(self, registry, http, query: str) -> None:
        super().__init__(registry, http)
        self.query = query

    def collect(self, today: date) -> Sequence[ArticleCandidate]:
        self.policy(today)
        url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(
            {"query": self.query, "mode": "artlist", "format": "json"})
        payload = json.loads(require_success(self.http.get(url, {})).decode("utf-8"))
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise ValueError("GDELT articles must be a list")
        return tuple(self._article(item) for item in articles)

    def _article(self, item: object) -> ArticleCandidate:
        if not isinstance(item, dict):
            raise ValueError("GDELT article must be an object")
        seen = str(item.get("seendate", ""))
        published = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return ArticleCandidate(self.source_id, str(item.get("domain", "")), str(item.get("title", "")),
                                str(item.get("url", "")), published,
                                language=str(item.get("language", "")) or None,
                                region=str(item.get("sourcecountry", "")) or None)

