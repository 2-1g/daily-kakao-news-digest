"""Edition lease and conservative delivery state machine."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from threading import RLock
from typing import Dict, Optional, Sequence
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


class StateConflict(RuntimeError):
    pass


class DeliveryBlocked(StateConflict):
    pass


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


@dataclass
class DeliveryRecord:
    position: int
    text: str
    status: DeliveryStatus
    updated_at: datetime
    reconciliation_reason: Optional[str] = None
    reconciliation_operator: Optional[str] = None


@dataclass
class Edition:
    run_date: date
    lease_owner: str
    lease_expires_at: datetime
    delivery_started_at: Optional[datetime] = None
    content_hash: Optional[str] = None
    messages: tuple[str, ...] = ()
    deliveries: Dict[int, DeliveryRecord] = field(default_factory=dict)
    missed: bool = False
    edition_id: str = ""
    terminal_status: Optional[str] = None


def edition_hash(messages: Sequence[str]) -> str:
    canonical = json.dumps(list(messages), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def kst_run_date(now: datetime) -> date:
    return now.astimezone(KST).date()


def edition_window_open(now: datetime, closes_at: time = time(9, 0)) -> bool:
    return now.astimezone(KST).time().replace(tzinfo=None) <= closes_at


class InMemoryEditionStore:
    """Transactional semantics suitable for tests and local dry runs."""

    def __init__(self) -> None:
        self._editions: Dict[date, Edition] = {}
        self._lock = RLock()

    def acquire(self, run_date: date, owner: str, now: datetime,
                ttl: timedelta = timedelta(minutes=5)) -> Edition:
        with self._lock:
            current = self._editions.get(run_date)
            if current is None:
                current = Edition(run_date, owner, now + ttl)
                current.edition_id = f"digest-{run_date.isoformat()}-0800-kst"
                self._editions[run_date] = current
            elif current.lease_owner != owner:
                if current.lease_expires_at > now or current.delivery_started_at is not None:
                    raise StateConflict("edition lease unavailable")
                current.lease_owner = owner
                current.lease_expires_at = now + ttl
            return current

    def heartbeat(self, run_date: date, owner: str, now: datetime,
                  ttl: timedelta = timedelta(minutes=5)) -> None:
        with self._lock:
            edition = self._owned(run_date, owner)
            edition.lease_expires_at = now + ttl

    def mark_missed(self, run_date: date, owner: str) -> None:
        with self._lock:
            self._owned(run_date, owner).missed = True

    def freeze(self, run_date: date, owner: str, messages: Sequence[str]) -> str:
        with self._lock:
            edition = self._owned(run_date, owner)
            digest = edition_hash(messages)
            if edition.content_hash is not None and edition.content_hash != digest:
                raise StateConflict("edition content is immutable")
            edition.content_hash = digest
            edition.messages = tuple(messages)
            return digest

    def begin(self, run_date: date, owner: str, position: int, now: datetime) -> None:
        with self._lock:
            edition = self._owned(run_date, owner)
            if edition.content_hash is None:
                raise StateConflict("freeze content before delivery")
            if any(r.status == DeliveryStatus.UNKNOWN for r in edition.deliveries.values()):
                raise DeliveryBlocked("unknown dispatch requires manual reconciliation")
            if edition.terminal_status:
                raise DeliveryBlocked("edition is terminal: " + edition.terminal_status)
            existing = edition.deliveries.get(position)
            if existing and existing.status == DeliveryStatus.ACKNOWLEDGED:
                return
            if existing:
                raise DeliveryBlocked("message already pending or unknown")
            edition.delivery_started_at = edition.delivery_started_at or now
            edition.deliveries[position] = DeliveryRecord(
                position, edition.messages[position - 1], DeliveryStatus.PENDING, now)

    def resolve(self, run_date: date, owner: str, position: int,
                status: DeliveryStatus, now: datetime) -> None:
        if status not in (DeliveryStatus.ACKNOWLEDGED, DeliveryStatus.UNKNOWN,
                          DeliveryStatus.REJECTED):
            raise ValueError("invalid terminal delivery status")
        with self._lock:
            record = self._owned(run_date, owner).deliveries[position]
            if record.status != DeliveryStatus.PENDING:
                raise StateConflict("only pending delivery can resolve")
            record.status, record.updated_at = status, now
            if status == DeliveryStatus.REJECTED:
                edition = self._owned(run_date, owner)
                edition.terminal_status = "failed"

    def recover_stale_pending(self, run_date: date, now: datetime,
                              stale_after: timedelta = timedelta(minutes=5)) -> int:
        with self._lock:
            edition = self._editions[run_date]
            changed = 0
            for record in edition.deliveries.values():
                if record.status == DeliveryStatus.PENDING and record.updated_at + stale_after <= now:
                    record.status, record.updated_at = DeliveryStatus.UNKNOWN, now
                    changed += 1
            return changed

    def reconcile_unknown_as_acknowledged(self, run_date: date, position: int,
                                          now: datetime, reason: str,
                                          operator: str = "operator") -> None:
        """Operator-only reconciliation after inspecting Kakao self-chat.

        Persistent adapters should bind this operation to operator IAM and retain
        ``reason`` in their audit log. It deliberately cannot authorize a resend.
        """
        if not reason.strip():
            raise ValueError("an operator audit reason is required")
        if not operator.strip():
            raise ValueError("an operator identity is required")
        with self._lock:
            edition = self._editions[run_date]
            record = edition.deliveries[position]
            if record.status != DeliveryStatus.UNKNOWN:
                raise StateConflict("only unknown delivery can be reconciled")
            record.status = DeliveryStatus.ACKNOWLEDGED
            record.updated_at = now
            record.reconciliation_reason = reason.strip()
            record.reconciliation_operator = operator.strip()

    def get(self, run_date: date) -> Optional[Edition]:
        return self._editions.get(run_date)

    def _owned(self, run_date: date, owner: str) -> Edition:
        edition = self._editions[run_date]
        if edition.lease_owner != owner:
            raise StateConflict("edition is owned by another worker")
        return edition
