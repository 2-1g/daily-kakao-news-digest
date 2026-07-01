"""Conservative, deterministic same-event clustering."""

import hashlib
import re
from collections import defaultdict
from typing import Iterable, List, Set

from .models import ArticleCandidate, EventCluster
from .normalize import normalize_article


TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
STOP = {"관련", "대한", "오늘", "속보", "단독", "정부", "기자", "뉴스", "발표"}

CATEGORY_TERMS = {
    "politics": {"대통령", "국회", "정당", "선거", "외교", "정치", "장관", "법안"},
    "economy": {"경제", "증시", "금리", "환율", "물가", "수출", "기업", "주가", "은행", "부동산"},
    "society": {"사회", "교육", "의료", "복지", "사건", "재난", "노동", "법원"},
    "sports": {"스포츠", "축구", "야구", "농구", "올림픽", "경기", "선수"},
    "entertainment": {"연예", "배우", "가수", "영화", "드라마", "아이돌", "공연"},
}
INVESTMENT_TERMS = CATEGORY_TERMS["economy"] | {"실적", "매출", "반도체", "채권", "원유", "관세"}
DOMESTIC_TERMS = {"한국", "국내", "서울", "코스피", "코스닥", "한국은행", "국회", "대통령"}


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
    category = _classify_category(unique)
    region = _classify_region(unique)
    investment_relevance = _classify_investment(unique, category)
    return EventCluster(event_id, tuple(unique), tuple(independent), tuple(syndicated),
                        category, region, investment_relevance)


def _article_text(article: ArticleCandidate) -> str:
    fields = [article.title, article.snippet or ""]
    fields.extend(str(value) for key, value in article.metadata.items()
                  if key in {"section", "category", "keywords", "country", "sourcecountry"})
    return " ".join(fields).lower()


def _classify_category(articles: List[ArticleCandidate]) -> str:
    explicit = str(articles[0].metadata.get("category", "")).lower()
    if explicit in CATEGORY_TERMS or explicit == "general":
        return explicit
    text = " ".join(_article_text(article) for article in articles)
    scores = {category: sum(text.count(term) for term in terms)
              for category, terms in CATEGORY_TERMS.items()}
    best = max(scores, key=lambda category: (scores[category], category))
    return best if scores[best] else "general"


def _classify_region(articles: List[ArticleCandidate]) -> str:
    explicit = articles[0].region or str(articles[0].metadata.get("region", ""))
    country = str(articles[0].metadata.get("sourcecountry", articles[0].metadata.get("country", ""))).lower()
    text = " ".join(_article_text(article) for article in articles)
    if country in {"kr", "kor", "korea", "south korea", "대한민국"} or any(term in text for term in DOMESTIC_TERMS):
        return "domestic"
    if explicit.lower() in {"domestic", "overseas"}:
        return explicit.lower()
    return "overseas"


def _classify_investment(articles: List[ArticleCandidate], category: str) -> bool:
    explicit = str(articles[0].metadata.get("investment_relevance", "")).lower()
    if explicit in {"true", "false"}:
        return explicit == "true"
    text = " ".join(_article_text(article) for article in articles)
    return category == "economy" or any(term in text for term in INVESTMENT_TERMS)
