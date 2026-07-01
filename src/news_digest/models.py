"""Typed domain records shared by source adapters."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional, Tuple


class SourceMechanism(str, Enum):
    API = "api"
    RSS = "rss"


@dataclass(frozen=True)
class ArticleCandidate:
    source_id: str
    publisher: str
    title: str
    url: str
    published_at: datetime
    snippet: Optional[str] = None
    language: Optional[str] = None
    region: Optional[str] = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.publisher.strip():
            raise ValueError("source_id and publisher are required")
        if not self.title.strip() or not self.url.startswith(("http://", "https://")):
            raise ValueError("title and absolute http(s) URL are required")


@dataclass(frozen=True)
class CollectionBatch:
    source_id: str
    articles: Tuple[ArticleCandidate, ...]


@dataclass(frozen=True)
class EventCluster:
    """Articles describing one event, with syndication lineage retained."""

    event_id: str
    articles: Tuple[ArticleCandidate, ...]
    independent_publishers: Tuple[str, ...]
    syndicated_publishers: Tuple[str, ...] = ()
    category: str = "general"
    region: str = "overseas"
    investment_relevance: bool = False

    @property
    def primary(self) -> ArticleCandidate:
        return self.articles[0]


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    text: str
    publisher: str
    url: str


@dataclass(frozen=True)
class GroundedClause:
    text: str
    evidence_ids: Tuple[str, ...]
    analysis: bool = False


@dataclass(frozen=True)
class DigestItem:
    event_id: str
    headline: str
    clauses: Tuple[GroundedClause, ...]
    sources: Tuple[Evidence, ...]
    category: str = "general"
    region: str = "overseas"
    investment_relevance: bool = False
