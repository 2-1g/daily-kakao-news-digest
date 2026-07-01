"""Evidence-bound synthesis protocol with a deterministic safe fallback."""

from __future__ import annotations

import json
import re
from typing import Mapping

from .models import DigestItem, Evidence, EventCluster, GroundedClause


FORBIDDEN_ADVICE = ("매수", "매도", "사야", "팔아", "추천 종목", "투자하세요")
WORD = re.compile(r"[0-9A-Za-z가-힣]+(?:[.,][0-9]+)?%?")
NUMBER = re.compile(r"(?<![0-9A-Za-z가-힣])\d+(?:[.,]\d+)?%?")
NEGATION = re.compile(r"(?<![가-힣])(?:안|못)(?![가-힣])|않[가-힣]*|아니[가-힣]*|없[가-힣]*")
PARTICLES = ("에서", "으로", "는", "은", "이", "가", "을", "를", "와", "과", "도", "에")


def build_evidence(cluster: EventCluster) -> tuple[Evidence, ...]:
    return tuple(Evidence("E%d" % (index + 1), article.snippet or article.title,
                          article.publisher, article.url)
                 for index, article in enumerate(cluster.articles))


def synthesis_prompt(cluster: EventCluster) -> str:
    evidence = build_evidence(cluster)
    payload = [{"id": e.evidence_id, "text": e.text, "publisher": e.publisher, "url": e.url}
               for e in evidence]
    return ("다음 허용된 근거만 사용하라. 사실 문장은 근거의 원문 구절을 그대로 또는 "
            "조사만 바꿔 짧게 인용하고 문장마다 evidence_ids를 붙여라. 숫자·고유명사·부정을 "
            "바꾸거나 합치지 마라. 투자 매수/매도 추천을 하지 마라. 분석은 analysis=true로 "
            "분리하되 근거에 없는 전망을 추가하지 마라. JSON만 반환하라.\n" +
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
        cited = [item.text for item in evidence if item.evidence_id in ids]
        if not any(_claim_supported(text, source, analysis) for source in cited):
            raise ValueError("clause is not extractively supported by one cited evidence item")
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


def _tokens(text: str) -> tuple[str, ...]:
    result = []
    for raw in WORD.findall(text.lower()):
        token = raw
        for particle in PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                token = token[:-len(particle)]
                break
        result.append(token)
    return tuple(result)


def _markers(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in pattern.finditer(text))


def _claim_supported(claim: str, evidence: str, analysis: bool) -> bool:
    claim_tokens = _tokens(claim)
    evidence_tokens = _tokens(evidence)
    if not claim_tokens:
        return False
    # Numeric and negation changes are high-risk semantic flips even when almost
    # every other character overlaps. Requiring identical markers also rejects
    # laundering a negative source into a positive summary by omission.
    if _markers(NUMBER, claim) != _markers(NUMBER, evidence):
        return False
    if _markers(NEGATION, claim) != _markers(NEGATION, evidence):
        return False

    # V1 intentionally accepts only an ordered, near-extractive token sequence.
    # The only normalization is Korean case-particle removal. This trades recall
    # for a deterministic guarantee: entities and predicates cannot be invented
    # merely because enough unrelated words overlap. Analysis is labelled by the
    # structured flag, but receives no weaker factual-grounding threshold.
    cursor = 0
    for token in claim_tokens:
        try:
            cursor = evidence_tokens.index(token, cursor) + 1
        except ValueError:
            return False
    return True
