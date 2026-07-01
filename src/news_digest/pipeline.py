"""Delivery orchestration; collection/editorial stages are injected."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Sequence

from .auth import OAuthManager
from .kakao import (AmbiguousDeliveryError, DefiniteDeliveryError, KakaoClient,
                    validate_messages)
from .state import (DeliveryBlocked, DeliveryStatus, InMemoryEditionStore,
                    edition_window_open, kst_run_date)


@dataclass(frozen=True)
class RunResult:
    status: str
    sent: int = 0
    content_hash: str = ""
    reason: str = ""


class DigestPipeline:
    def __init__(self, store: InMemoryEditionStore, oauth: OAuthManager,
                 kakao: KakaoClient, clock: Callable[[], datetime],
                 event_sink: Optional[Callable[..., None]] = None,
                 stage_lease_ttl: timedelta = timedelta(minutes=20)) -> None:
        self.store, self.oauth, self.kakao, self.clock = store, oauth, kakao, clock
        self.event_sink = event_sink or (lambda *args, **kwargs: None)
        self.stage_lease_ttl = stage_lease_ttl

    def run(self, owner: str, messages: Sequence[str], dry_run: bool = False) -> RunResult:
        now = self.clock()
        run_date = kst_run_date(now)
        edition = self.store.acquire(run_date, owner, now)
        self.store.heartbeat(run_date, owner, self.clock(), self.stage_lease_ttl)
        self.store.recover_stale_pending(run_date, now)
        if edition.missed:
            return RunResult("missed")
        if edition.delivery_started_at is None and not edition_window_open(now):
            self.store.mark_missed(run_date, owner)
            return RunResult("missed")
        if not messages:
            self.event_sink("digest_run_suppressed", status="suppressed",
                            edition_id=edition.edition_id,
                            reason="insufficient_diversity", message_count=0)
            return RunResult("suppressed", reason="insufficient_diversity")
        envelopes = validate_messages(messages)
        self.store.heartbeat(run_date, owner, self.clock(), self.stage_lease_ttl)
        digest = self.store.freeze(run_date, owner, [item.text for item in envelopes])
        if dry_run:
            self.event_sink("digest_run_complete", status="dry_run",
                            edition_id=edition.edition_id, message_count=len(envelopes),
                            character_count=sum(len(item.text) for item in envelopes))
            return RunResult("dry_run", content_hash=digest)
        if any(r.status == DeliveryStatus.UNKNOWN for r in edition.deliveries.values()):
            raise DeliveryBlocked("unknown dispatch requires manual reconciliation")
        rotation = self.oauth.valid_access_token(now)
        token = rotation.token.access_token
        sent = 0
        authenticated = False
        for envelope in envelopes:
            self.store.heartbeat(run_date, owner, self.clock(), self.stage_lease_ttl)
            existing = edition.deliveries.get(envelope.position)
            if existing and existing.status == DeliveryStatus.ACKNOWLEDGED:
                continue
            self.store.begin(run_date, owner, envelope.position, now)
            try:
                self.kakao.send(token, envelope.text)
            except AmbiguousDeliveryError:
                self.store.resolve(run_date, owner, envelope.position, DeliveryStatus.UNKNOWN, self.clock())
                self.event_sink("digest_delivery_status", status="unknown",
                                edition_id=edition.edition_id, position=envelope.position)
                return RunResult("unknown", sent, digest)
            except DefiniteDeliveryError:
                # Delivery has begun, so even a definite rejection is terminal for this
                # frozen edition. Record a blocking state rather than leaving stale pending.
                self.store.resolve(run_date, owner, envelope.position, DeliveryStatus.REJECTED, self.clock())
                # A first authenticated-use rejection cannot prove a newly
                # rotated token. Roll back its pointer, but never resend this
                # message: the durable REJECTED edition remains terminal.
                if not authenticated:
                    self.oauth.rollback_unproven(rotation)
                self.event_sink("digest_delivery_status", status="failed",
                                edition_id=edition.edition_id, position=envelope.position)
                return RunResult("terminal_delivery_failure", sent, digest)
            self.store.resolve(run_date, owner, envelope.position,
                               DeliveryStatus.ACKNOWLEDGED, self.clock())
            if not authenticated:
                self.oauth.mark_successful_use(rotation.active_version)
                authenticated = True
            sent += 1
        self.event_sink("digest_run_complete", status="acknowledged",
                        edition_id=edition.edition_id, sent=sent,
                        message_count=len(envelopes), character_count=sum(len(x.text) for x in envelopes))
        return RunResult("acknowledged", sent, digest)
