"""Kakao-safe Korean digest composition without quota padding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import DigestItem, Evidence


DISCLAIMER = "※ 정보 제공용이며 투자 권유가 아닙니다."


@dataclass(frozen=True)
class ComposedDigest:
    messages: tuple[str, ...]
    insufficient_source_diversity: bool = False
    reason: str | None = None

    @property
    def total_chars(self) -> int:
        return sum(len(message) for message in self.messages)


class DigestComposer:
    def __init__(self, max_messages: int = 18, max_chars: int = 200, max_total: int = 4000) -> None:
        self.max_messages, self.max_chars, self.max_total = max_messages, max_chars, max_total

    def compose(self, items: Iterable[DigestItem], edition: str = "오늘") -> ComposedDigest:
        items = tuple(items)
        if not items:
            return ComposedDigest((), False, "no_qualifying_news")
        bodies = ["📰 %s 주요 뉴스" % edition]
        all_publishers = {source.publisher for item in items for source in item.sources}
        insufficient = bool(items) and len(all_publishers) < 2
        if insufficient:
            return ComposedDigest((), True, "insufficient_diversity")
        for item in items:
            facts = " ".join(("[분석] " if c.analysis else "") + c.text for c in item.clauses)
            cited_ids = {evidence_id for clause in item.clauses for evidence_id in clause.evidence_ids}
            sources = tuple(source for source in item.sources if source.evidence_id in cited_ids)
            body = self._fit_item(item.headline, facts, sources)
            if body:
                bodies.append(body)
            if len(bodies) >= self.max_messages - 1:
                break
        bodies.append(DISCLAIMER)
        numbered = self._number(bodies)
        while (sum(len(message) for message in numbered) > self.max_total or
               any(len(message) > self.max_chars for message in numbered)):
            oversize = next((i for i, message in enumerate(numbered)
                             if len(message) > self.max_chars), len(bodies) - 2)
            if oversize in (0, len(bodies) - 1):
                raise ValueError("mandatory message exceeds Kakao limit")
            bodies.pop(oversize)
            numbered = self._number(bodies)
        return ComposedDigest(tuple(numbered), False, None)

    def _fit_item(self, headline: str, facts: str,
                  sources: Sequence[Evidence]) -> str | None:
        """Compress prose, never a URL, so displayed links remain usable."""
        payload_limit = self.max_chars - 8  # reserve stable room for "[18/18] "
        # Keep at least two independent corroborating citations when they fit;
        # discard only citations whose URL itself makes a Kakao-safe item impossible.
        suffix = ""
        seen_publishers = set()
        for source in sources:
            if source.publisher in seen_publishers:
                continue
            candidate = "\n%s · %s" % (source.publisher, source.url)
            if len(suffix + candidate) + 12 <= payload_limit:
                suffix += candidate
                seen_publishers.add(source.publisher)
        if not suffix:
            return None
        available = payload_limit - len(suffix)
        headline = self._clip(headline, min(len(headline), max(12, available // 2)))
        fact_space = available - len(headline) - 1
        facts = self._clip(facts, fact_space) if fact_space > 5 else ""
        return headline + (("\n" + facts) if facts else "") + suffix

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[:max(1, limit - 1)].rstrip() + "…"

    @staticmethod
    def _number(bodies: list[str]) -> list[str]:
        total = len(bodies)
        return ["[%d/%d] %s" % (index, total, body) for index, body in enumerate(bodies, 1)]
