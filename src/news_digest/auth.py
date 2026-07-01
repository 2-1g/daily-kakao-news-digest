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
    def retire(self, version: str) -> None: ...


@dataclass(frozen=True)
class RotationResult:
    token: OAuthToken
    active_version: str
    previous_version: Optional[str] = None


class OAuthManager:
    def __init__(self, store: VersionedTokenStore, refresher: TokenRefresher) -> None:
        self._store = store
        self._refresher = refresher

    def valid_access_token(self, now: Optional[datetime] = None) -> RotationResult:
        now = now or datetime.now(timezone.utc)
        active = self._store.active_version()
        token = self._store.read(active)
        if token.refresh_expires_at is not None and token.refresh_expires_at <= now:
            raise ReauthorizationRequired("refresh token expired; operator reauthorization required")
        if not token.access_expiring(now):
            self._store.mark_successful_use(active)
            return RotationResult(token, active)
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
        self._store.verify(new_version)
        if not self._store.compare_and_set_active(active, new_version):
            # A concurrent rotation won. The new version is unreferenced and safe to retire.
            self._store.retire(new_version)
            winner = self._store.active_version()
            return RotationResult(self._store.read(winner), winner)
        self._store.mark_successful_use(new_version)
        # Prior version is intentionally retained; an operator/grace-period task retires it.
        return RotationResult(refreshed, new_version, active)


class InMemoryTokenStore:
    """Deterministic test implementation of the Secret Manager pointer contract."""

    def __init__(self, token: OAuthToken) -> None:
        self.versions = {"1": token}
        self.active = "1"
        self.successful = set()  # type: set[str]
        self.retired = set()  # type: set[str]

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

    def retire(self, version: str) -> None:
        if version == self.active:
            raise AuthenticationError("cannot retire active token version")
        self.retired.add(version)

