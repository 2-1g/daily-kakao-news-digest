"""Publisher-provided RSS/Atom adapter without article-page fetching."""

from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Sequence
from xml.etree import ElementTree

from news_digest.models import ArticleCandidate
from .base import CompliantAdapter, require_success


class RssAdapter(CompliantAdapter):
    requested_fields = ("title", "link", "description", "published")

    def __init__(self, registry, http, source_id: str, feed_url: str, publisher: str) -> None:
        super().__init__(registry, http)
        self.source_id, self.feed_url, self.publisher = source_id, feed_url, publisher

    def collect(self, today: date) -> Sequence[ArticleCandidate]:
        self.policy(today)
        root = ElementTree.fromstring(require_success(self.http.get(self.feed_url, {})))
        entries = root.findall(".//item") or root.findall("{*}entry")
        return tuple(self._article(node) for node in entries)

    def _article(self, node) -> ArticleCandidate:
        title = _text(node, "title")
        link_node = node.find("link") or node.find("{*}link")
        url = (link_node.get("href") if link_node is not None else None) or _text(node, "link")
        published = _text(node, "pubDate") or _text(node, "published") or _text(node, "updated")
        description = _text(node, "description") or _text(node, "summary") or None
        return ArticleCandidate(self.source_id, self.publisher, title, url, _date(published), snippet=description)


def _text(node, name: str) -> str:
    found = node.find(name) or node.find("{*}%s" % name)
    return "" if found is None or found.text is None else found.text.strip()


def _date(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

