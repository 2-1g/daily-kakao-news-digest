"""Dependency-injected Kakao OAuth refresh and recoverable token rotation."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Protocol


class AuthenticationError(RuntimeError):
    """Safe terminal authentication failure."""


class ReauthorizationRequired(AuthenticationError):
    """The operator must repeat the OAuth bootstrap flow."""


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: Optional[datetime] = None

    def access_expiring(self, now: datetime, margin: timedelta = timedelta(minutes=5)) -> bool:
        return self.access_expires_at <= now + margin

    def refresh_expiring(self, now: datetime, margin: timedelta = timedelta(days=7)) -> bool:
        return self.refresh_expires_at is not None and self.refresh_expires_at <= now + margin


class TokenRefresher(Protocol):
    def refresh(self, refresh_token: str) -> OAuthToken: ...


class VersionedTokenStore(Protocol):
    """Secret payload versions plus an authoritative, atomic pointer."""

    def active_version(self) -> str: ...
    def read(self, version: str) -> OAuthToken: ...
    def create(self, token: OAuthToken) -> str: ...
    def verify(self, version: str) -> None: ...
    def compare_and_set_active(self, expected: str, new: str) -> bool: ...
    def mark_successful_use(self, version: str) -> None: ...
    def rollback_if_unproven(self, candidate: str, previous: str) -> bool: ...
    def unproven_previous(self, active: str) -> Optional[str]: ...
    def retire(self, version: str) -> None: ...


@dataclass(frozen=True)
class RotationResult:
    token: OAuthToken
    active_version: str
    previous_version: Optional[str] = None


class OAuthManager:
    def __init__(self, store: VersionedTokenStore, refresher: TokenRefresher,
                 event_sink: Optional[Callable[..., None]] = None) -> None:
        self._store = store
        self._refresher = refresher
        self._event_sink = event_sink or (lambda *args, **kwargs: None)

    def _phase(self, version: str, phase: str, **details: str) -> None:
        recorder = getattr(self._store, "record_rotation_phase", None)
        if recorder:
            recorder(version, phase, details)

    def mark_successful_use(self, version: str) -> None:
        """Mark only after Kakao has accepted an authenticated request."""
        self._store.mark_successful_use(version)

    def rollback_unproven(self, rotation: RotationResult) -> bool:
        """CAS-rollback only the candidate created by this run.

        Delivery is never retried here; the caller persists the failed dispatch
        first and a later run remains blocked by the frozen edition state.
        """
        if rotation.previous_version is None:
            return False
        rolled_back = self._store.rollback_if_unproven(
            rotation.active_version, rotation.previous_version)
        self._event_sink("oauth_rotation_rollback", candidate=rotation.active_version,
                         previous=rotation.previous_version,
                         status="rolled_back" if rolled_back else "skipped")
        return rolled_back

    def valid_access_token(self, now: Optional[datetime] = None) -> RotationResult:
        now = now or datetime.now(timezone.utc)
        active = self._store.active_version()
        token = self._store.read(active)
        if token.refresh_expires_at is not None and token.refresh_expires_at <= now:
            raise ReauthorizationRequired("refresh token expired; operator reauthorization required")
        if token.refresh_expiring(now):
            self._event_sink("oauth_refresh_expiry_warning", version=active,
                             expires_at=token.refresh_expires_at,
                             days_remaining=max(0, (token.refresh_expires_at - now).days))
        if not token.access_expiring(now):
            context_reader = getattr(self._store, "unproven_previous", None)
            previous = context_reader(active) if context_reader else None
            return RotationResult(token, active, previous)
        try:
            refreshed = self._refresher.refresh(token.refresh_token)
        except ReauthorizationRequired:
            raise
        except Exception as exc:
            raise AuthenticationError("token refresh failed safely") from exc

        # Kakao may omit a new refresh token. Keep the old one in that case.
        if not refreshed.refresh_token:
            refreshed = replace(refreshed, refresh_token=token.refresh_token,
                                refresh_expires_at=token.refresh_expires_at)
        new_version = self._store.create(refreshed)
        self._phase(new_version, "candidate_created", previous=active)
        self._store.verify(new_version)
        self._phase(new_version, "candidate_verified", previous=active)
        if not self._store.compare_and_set_active(active, new_version):
            # A concurrent rotation won. The new version is unreferenced and safe to retire.
            self._store.retire(new_version)
            self._phase(new_version, "cas_lost_retired", previous=active)
            winner = self._store.active_version()
            return RotationResult(self._store.read(winner), winner)
        try:
            self._phase(new_version, "active_pending_validation", previous=active)
        except Exception:
            # Do not leave a newly active candidate without durable phase proof.
            self._store.rollback_if_unproven(new_version, active)
            raise
        # Prior version is intentionally retained; an operator/grace-period task retires it.
        return RotationResult(refreshed, new_version, active)


class InMemoryTokenStore:
    """Deterministic test implementation of the Secret Manager pointer contract."""

    def __init__(self, token: OAuthToken) -> None:
        self.versions = {"1": token}
        self.active = "1"
        self.successful = set()  # type: set[str]
        self.retired = set()  # type: set[str]
        self.rotation_phases = {}  # type: dict[str, tuple[str, dict[str, str]]]

    def active_version(self) -> str:
        return self.active

    def read(self, version: str) -> OAuthToken:
        if version in self.retired:
            raise AuthenticationError("token version retired")
        return self.versions[version]

    def create(self, token: OAuthToken) -> str:
        version = str(max(map(int, self.versions)) + 1)
        self.versions[version] = token
        return version

    def verify(self, version: str) -> None:
        self.read(version)

    def compare_and_set_active(self, expected: str, new: str) -> bool:
        if self.active != expected:
            return False
        self.active = new
        return True

    def mark_successful_use(self, version: str) -> None:
        self.successful.add(version)
        phase = self.rotation_phases.get(version)
        details = phase[1] if phase else {}
        self.record_rotation_phase(version, "successful_use", details)

    def rollback_if_unproven(self, candidate: str, previous: str) -> bool:
        phase = self.rotation_phases.get(candidate)
        if (self.active != candidate or candidate in self.successful or
                previous not in self.versions or previous in self.retired):
            return False
        self.active = previous
        details = dict(phase[1] if phase else {})
        details["previous"] = previous
        self.record_rotation_phase(candidate, "rolled_back", details)
        return True

    def unproven_previous(self, active: str) -> Optional[str]:
        phase = self.rotation_phases.get(active)
        if active in self.successful or not phase:
            return None
        previous = phase[1].get("previous")
        return previous if previous and previous != active else None

    def retire(self, version: str) -> None:
        if version == self.active:
            raise AuthenticationError("cannot retire active token version")
        self.retired.add(version)

    def record_rotation_phase(self, version: str, phase: str,
                              details: dict[str, str]) -> None:
        self.rotation_phases[version] = (phase, details)


def kakao_authorization_url(client_id: str, redirect_uri: str,
                            state: str, scope: str = "talk_message") -> str:
    """Build an attended Kakao consent URL without exposing any secret."""
    from urllib.parse import urlencode
    if not client_id or not redirect_uri or not state:
        raise ValueError("client_id, redirect_uri, and state are required")
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri,
                       "response_type": "code", "scope": scope, "state": state})
    return "https://kauth.kakao.com/oauth/authorize?" + query
