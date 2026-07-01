"""Delivery orchestration; collection/editorial stages are injected."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from .auth import OAuthManager
from .kakao import AmbiguousDeliveryError, KakaoClient, validate_messages
from .state import (DeliveryBlocked, DeliveryStatus, InMemoryEditionStore,
                    edition_window_open, kst_run_date)


@dataclass(frozen=True)
class RunResult:
    status: str
    sent: int = 0
    content_hash: str = ""


class DigestPipeline:
    def __init__(self, store: InMemoryEditionStore, oauth: OAuthManager,
                 kakao: KakaoClient, clock: Callable[[], datetime]) -> None:
        self.store, self.oauth, self.kakao, self.clock = store, oauth, kakao, clock

    def run(self, owner: str, messages: Sequence[str], dry_run: bool = False) -> RunResult:
        now = self.clock()
        run_date = kst_run_date(now)
        edition = self.store.acquire(run_date, owner, now)
        self.store.recover_stale_pending(run_date, now)
        if edition.missed:
            return RunResult("missed")
        if edition.delivery_started_at is None and not edition_window_open(now):
            self.store.mark_missed(run_date, owner)
            return RunResult("missed")
        envelopes = validate_messages(messages)
        digest = self.store.freeze(run_date, owner, [item.text for item in envelopes])
        if dry_run:
            return RunResult("dry_run", content_hash=digest)
        if any(r.status == DeliveryStatus.UNKNOWN for r in edition.deliveries.values()):
            raise DeliveryBlocked("unknown dispatch requires manual reconciliation")
        token = self.oauth.valid_access_token(now).token.access_token
        sent = 0
        for envelope in envelopes:
            existing = edition.deliveries.get(envelope.position)
            if existing and existing.status == DeliveryStatus.ACKNOWLEDGED:
                continue
            self.store.begin(run_date, owner, envelope.position, now)
            try:
                self.kakao.send(token, envelope.text)
            except AmbiguousDeliveryError:
                self.store.resolve(run_date, owner, envelope.position, DeliveryStatus.UNKNOWN, self.clock())
                return RunResult("unknown", sent, digest)
            self.store.resolve(run_date, owner, envelope.position,
                               DeliveryStatus.ACKNOWLEDGED, self.clock())
            sent += 1
        return RunResult("acknowledged", sent, digest)

