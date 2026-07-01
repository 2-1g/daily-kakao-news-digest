"""Editorial ranking with adaptive count and soft composition directions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .models import EventCluster


@dataclass(frozen=True)
class RankConfig:
    minimum_score: float = 0.36
    max_items: int = 10
    max_publisher_share: float = 0.5
    domestic_target: float = 0.6
    investment_target: float = 0.4


@dataclass(frozen=True)
class EditorialMetrics:
    item_count: int
    publisher_count: int
    max_publisher_share: float
    domestic_share: float
    investment_share: float
    insufficient_source_diversity: bool


def editorial_metrics(selected: Iterable[EventCluster], approved_publishers: Iterable[str] = ()) -> EditorialMetrics:
    items = tuple(selected)
    counts = {publisher: sum(c.primary.publisher == publisher for c in items)
              for publisher in {c.primary.publisher for c in items}}
    total = len(items)
    approved = set(approved_publishers)
    return EditorialMetrics(
        total, len(counts), max(counts.values(), default=0) / total if total else 0.0,
        sum(c.region == "domestic" for c in items) / total if total else 0.0,
        sum(c.investment_relevance for c in items) / total if total else 0.0,
        bool(items) and len(counts) == 1 and len(approved) < 2,
    )


def rank_clusters(clusters: Iterable[EventCluster], now: datetime | None = None,
                  config: RankConfig = RankConfig()) -> tuple[EventCluster, ...]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    scored = sorted(((score_cluster(c, now), c) for c in clusters),
                    key=lambda pair: (-pair[0], pair[1].event_id))
    candidates = [(score, cluster) for score, cluster in scored if score >= config.minimum_score]
    eligible_publishers = {cluster.primary.publisher for _, cluster in candidates}
    chosen: list[EventCluster] = []
    publisher_counts: dict[str, int] = {}
    while candidates and len(chosen) < config.max_items:
        best_index = max(range(len(candidates)), key=lambda i: (
            candidates[i][0] + _balance_bonus(candidates[i][1], chosen, config),
            candidates[i][1].event_id))
        _, cluster = candidates.pop(best_index)
        publisher = cluster.primary.publisher
        projected = publisher_counts.get(publisher, 0) + 1
        if chosen and projected / (len(chosen) + 1) > config.max_publisher_share:
            continue
        chosen.append(cluster)
        publisher_counts[publisher] = projected
    # A multi-source pool must never silently become a single-publisher edition.
    if len(eligible_publishers) > 1 and len({c.primary.publisher for c in chosen}) < 2:
        return ()
    return tuple(chosen)


def score_cluster(cluster: EventCluster, now: datetime) -> float:
    age_hours = max(0.0, (now - cluster.primary.published_at.astimezone(timezone.utc)).total_seconds() / 3600)
    recency = max(0.0, 1.0 - age_hours / 48.0)
    confirmation = min(1.0, len(cluster.independent_publishers) / 3.0)
    diversity = min(1.0, len({a.publisher for a in cluster.articles}) / 4.0)
    impact = float(cluster.primary.metadata.get("impact", "0.5"))
    core = 1.0 if cluster.category in {"politics", "economy", "society"} else 0.25
    return recency * .25 + confirmation * .25 + impact * .25 + core * .15 + diversity * .10


def _balance_bonus(cluster: EventCluster, chosen: list[EventCluster], config: RankConfig) -> float:
    if not chosen:
        return 0.0
    domestic_share = sum(c.region == "domestic" for c in chosen) / len(chosen)
    investment_share = sum(c.investment_relevance for c in chosen) / len(chosen)
    return (.04 if cluster.region == "domestic" and domestic_share < config.domestic_target else 0) + \
           (.03 if cluster.investment_relevance and investment_share < config.investment_target else 0)
