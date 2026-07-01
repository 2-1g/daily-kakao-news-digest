"""Kakao-safe Korean digest composition without quota padding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import DigestItem


DISCLAIMER = "※ 정보 제공용이며 투자 권유가 아닙니다."


@dataclass(frozen=True)
class ComposedDigest:
    messages: tuple[str, ...]

    @property
    def total_chars(self) -> int:
        return sum(len(message) for message in self.messages)


class DigestComposer:
    def __init__(self, max_messages: int = 18, max_chars: int = 200, max_total: int = 4000) -> None:
        self.max_messages, self.max_chars, self.max_total = max_messages, max_chars, max_total

    def compose(self, items: Iterable[DigestItem], edition: str = "오늘") -> ComposedDigest:
        items = tuple(items)
        bodies = ["📰 %s 주요 뉴스" % edition]
        for item in items:
            source = item.sources[0]
            facts = " ".join(("[분석] " if c.analysis else "") + c.text for c in item.clauses)
            body = self._fit_item(item.headline, facts, source.publisher, source.url)
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
        return ComposedDigest(tuple(numbered))

    def _fit_item(self, headline: str, facts: str, publisher: str, url: str) -> str | None:
        """Compress prose, never a URL, so displayed links remain usable."""
        suffix = "\n%s · %s" % (publisher, url)
        payload_limit = self.max_chars - 8  # reserve stable room for "[18/18] "
        if len(suffix) + 12 > payload_limit:
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
