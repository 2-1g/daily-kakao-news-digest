"""Evidence-bound synthesis protocol with a deterministic safe fallback."""

from __future__ import annotations

import json
from typing import Mapping

from .models import DigestItem, Evidence, EventCluster, GroundedClause


FORBIDDEN_ADVICE = ("매수", "매도", "사야", "팔아", "추천 종목", "투자하세요")


def build_evidence(cluster: EventCluster) -> tuple[Evidence, ...]:
    return tuple(Evidence("E%d" % (index + 1), article.snippet or article.title,
                          article.publisher, article.url)
                 for index, article in enumerate(cluster.articles))


def synthesis_prompt(cluster: EventCluster) -> str:
    evidence = build_evidence(cluster)
    payload = [{"id": e.evidence_id, "text": e.text, "publisher": e.publisher, "url": e.url}
               for e in evidence]
    return ("다음 허용된 근거만 사용하라. 사실 문장마다 evidence_ids를 붙이고 추측하지 마라. "
            "투자 매수/매도 추천을 하지 마라. 분석은 analysis=true로 명시하라. JSON만 반환하라.\n" +
            json.dumps({"headline": cluster.primary.title, "evidence": payload}, ensure_ascii=False))


def parse_synthesis(cluster: EventCluster, raw: str) -> DigestItem:
    data = json.loads(raw)
    evidence = build_evidence(cluster)
    available = {item.evidence_id for item in evidence}
    headline = data.get("headline")
    clauses_data = data.get("clauses")
    if not isinstance(headline, str) or not headline.strip() or not isinstance(clauses_data, list):
        raise ValueError("malformed synthesis")
    clauses = []
    for raw_clause in clauses_data:
        if not isinstance(raw_clause, Mapping):
            raise ValueError("malformed clause")
        text = raw_clause.get("text")
        ids = raw_clause.get("evidence_ids")
        analysis = raw_clause.get("analysis", False)
        if not isinstance(text, str) or not isinstance(ids, list) or not ids or not set(ids) <= available:
            raise ValueError("every factual clause requires valid evidence")
        if any(term in text for term in FORBIDDEN_ADVICE):
            raise ValueError("investment recommendation rejected")
        if not isinstance(analysis, bool):
            raise ValueError("analysis flag must be boolean")
        clauses.append(GroundedClause(text.strip(), tuple(ids), analysis))
    if not clauses:
        raise ValueError("empty synthesis")
    return DigestItem(cluster.event_id, headline.strip(), tuple(clauses), evidence,
                      cluster.category, cluster.region, cluster.investment_relevance)


def deterministic_fallback(cluster: EventCluster) -> DigestItem:
    evidence = build_evidence(cluster)
    primary = evidence[0]
    text = " ".join(primary.text.split())
    return DigestItem(cluster.event_id, cluster.primary.title,
                      (GroundedClause(text, (primary.evidence_id,)),), evidence,
                      cluster.category, cluster.region, cluster.investment_relevance)


def summarize(cluster: EventCluster, response: str | None = None) -> DigestItem:
    if response:
        try:
            return parse_synthesis(cluster, response)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    return deterministic_fallback(cluster)
