"""Kakao self-message boundary with strict local preflight validation."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence


MAX_AUTOMATED_MESSAGES = 18
MAX_MESSAGE_CHARS = 200
MAX_TOTAL_CHARS = 4000


class KakaoContractError(ValueError):
    pass


class DefiniteDeliveryError(RuntimeError):
    pass


class AmbiguousDeliveryError(RuntimeError):
    """A request may have reached Kakao; it must never be retried automatically."""


class SendOutcome(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MessageEnvelope:
    position: int
    text: str


class KakaoTransport(Protocol):
    def send_self_message(self, access_token: str, text: str) -> None: ...


def validate_messages(messages: Sequence[str]) -> tuple[MessageEnvelope, ...]:
    if not messages:
        raise KakaoContractError("at least one message is required")
    if len(messages) > MAX_AUTOMATED_MESSAGES:
        raise KakaoContractError("automated message cap exceeded")
    if any(not message or len(message) > MAX_MESSAGE_CHARS for message in messages):
        raise KakaoContractError("message must contain 1..200 characters")
    if sum(map(len, messages)) > MAX_TOTAL_CHARS:
        raise KakaoContractError("daily character cap exceeded")
    return tuple(MessageEnvelope(i, text) for i, text in enumerate(messages, 1))


class KakaoClient:
    def __init__(self, transport: KakaoTransport) -> None:
        self._transport = transport

    def send(self, access_token: str, text: str) -> SendOutcome:
        try:
            self._transport.send_self_message(access_token, text)
        except DefiniteDeliveryError:
            raise
        except Exception as exc:
            raise AmbiguousDeliveryError("dispatch outcome unknown; automatic retry forbidden") from exc
        return SendOutcome.ACKNOWLEDGED

