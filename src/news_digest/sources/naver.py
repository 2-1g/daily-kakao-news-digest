"""Naver News Search API adapter; metadata/snippets only."""

import html
import json
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Mapping, Sequence
from urllib.parse import urlencode

from news_digest.models import ArticleCandidate
from .base import CompliantAdapter, require_success


class NaverAdapter(CompliantAdapter):
    source_id = "naver-news"
    requested_fields = ("title", "originallink", "link", "description", "pubDate")

    def __init__(self, registry, http, client_id: str, client_secret: str, query: str) -> None:
        super().__init__(registry, http)
        if not client_id or not client_secret:
            raise ValueError("Naver credentials must be injected")
        self.headers: Mapping[str, str] = {
            "X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret,
        }
        self.query = query

    def collect(self, today: date) -> Sequence[ArticleCandidate]:
        self.policy(today)
        url = "https://openapi.naver.com/v1/search/news.json?" + urlencode({"query": self.query})
        payload = json.loads(require_success(self.http.get(url, self.headers)).decode("utf-8"))
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Naver items must be a list")
        return tuple(self._article(item) for item in items)

    def _article(self, item: object) -> ArticleCandidate:
        if not isinstance(item, dict):
            raise ValueError("Naver item must be an object")
        title = _clean(item.get("title"))
        url = _clean(item.get("originallink")) or _clean(item.get("link"))
        return ArticleCandidate(self.source_id, _publisher(url), title, url,
                                parsedate_to_datetime(_clean(item.get("pubDate"))),
                                snippet=_clean(item.get("description")), language="ko", region="domestic")


def _clean(value: object) -> str:
    return html.unescape(str(value or "")).replace("<b>", "").replace("</b>", "").strip()


def _publisher(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url).hostname or "unknown"

