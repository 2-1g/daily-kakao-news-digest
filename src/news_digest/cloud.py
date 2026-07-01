"""Lazy-loaded Google Cloud persistence adapters.

SDK imports happen only at construction so local tests and dry-run composition do
not require Google packages or application-default credentials.
"""

import json
from datetime import date, datetime
from typing import Any, Dict, Optional

from .auth import OAuthToken
from .state import DeliveryRecord, DeliveryStatus, Edition, InMemoryEditionStore


def token_to_json(token: OAuthToken) -> bytes:
    return json.dumps({
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "access_expires_at": token.access_expires_at.isoformat(),
        "refresh_expires_at": token.refresh_expires_at.isoformat() if token.refresh_expires_at else None,
    }, separators=(",", ":")).encode()


def token_from_json(raw: bytes) -> OAuthToken:
    data = json.loads(raw.decode())
    return OAuthToken(str(data["access_token"]), str(data["refresh_token"]),
                      datetime.fromisoformat(data["access_expires_at"]),
                      datetime.fromisoformat(data["refresh_expires_at"])
                      if data.get("refresh_expires_at") else None)


class SecretManagerTokenStore:
    """Versioned token secret using Secret Manager's atomic version alias."""

    def __init__(self, project_id: str, secret_id: str, client: Any = None,
                 active_alias: str = "active", alias_cas: Any = None) -> None:
        if client is None:
            from google.cloud import secretmanager  # type: ignore
            client = secretmanager.SecretManagerServiceClient()
        self.client, self.project_id, self.secret_id = client, project_id, secret_id
        self.active_alias = active_alias
        self.alias_cas = alias_cas
        self.parent = "projects/%s/secrets/%s" % (project_id, secret_id)

    def active_version(self) -> str:
        response = self.client.access_secret_version(
            request={"name": self.parent + "/versions/" + self.active_alias})
        return response.name.rsplit("/", 1)[-1]

    def read(self, version: str) -> OAuthToken:
        response = self.client.access_secret_version(
            request={"name": self.parent + "/versions/" + version})
        return token_from_json(bytes(response.payload.data))

    def create(self, token: OAuthToken) -> str:
        response = self.client.add_secret_version(
            request={"parent": self.parent, "payload": {"data": token_to_json(token)}})
        return response.name.rsplit("/", 1)[-1]

    def verify(self, version: str) -> None:
        self.read(version)

    def compare_and_set_active(self, expected: str, new: str) -> bool:
        if self.alias_cas is not None:
            return bool(self.alias_cas(expected, new))
        secret = self.client.get_secret(request={"name": self.parent})
        aliases = dict(getattr(secret, "version_aliases", {}))
        if str(aliases.get(self.active_alias)) != str(expected):
            return False
        if (self.client.__class__.__module__.startswith("google.") and
                not getattr(secret, "etag", None)):
            raise RuntimeError("Secret Manager CAS requires a resource etag")
        aliases[self.active_alias] = int(new)
        secret.version_aliases = aliases
        # update_secret honors the etag present on the resource and rejects a
        # concurrent alias update rather than overwriting it.
        self.client.update_secret(request={"secret": secret,
                                           "update_mask": {"paths": ["version_aliases"]}})
        return True

    def mark_successful_use(self, version: str) -> None:
        # Successful use is operational evidence; Cloud Logging records it. No secret mutation.
        self.verify(version)

    def retire(self, version: str) -> None:
        self.client.disable_secret_version(
            request={"name": self.parent + "/versions/" + version})


def edition_to_dict(edition: Edition) -> Dict[str, Any]:
    return {
        "run_date": edition.run_date.isoformat(), "lease_owner": edition.lease_owner,
        "lease_expires_at": edition.lease_expires_at.isoformat(),
        "delivery_started_at": edition.delivery_started_at.isoformat() if edition.delivery_started_at else None,
        "content_hash": edition.content_hash, "messages": list(edition.messages), "missed": edition.missed,
        "deliveries": {str(k): {"position": v.position, "text": v.text, "status": v.status.value,
                                  "updated_at": v.updated_at.isoformat(),
                                  "reconciliation_reason": v.reconciliation_reason}
                       for k, v in edition.deliveries.items()},
    }


def edition_from_dict(data: Dict[str, Any]) -> Edition:
    deliveries = {int(k): DeliveryRecord(int(v["position"]), str(v["text"]),
                  DeliveryStatus(v["status"]), datetime.fromisoformat(v["updated_at"]),
                  v.get("reconciliation_reason")) for k, v in data.get("deliveries", {}).items()}
    return Edition(date.fromisoformat(data["run_date"]), str(data["lease_owner"]),
                   datetime.fromisoformat(data["lease_expires_at"]),
                   datetime.fromisoformat(data["delivery_started_at"])
                   if data.get("delivery_started_at") else None,
                   data.get("content_hash"), tuple(data.get("messages", ())), deliveries,
                   bool(data.get("missed", False)))


class FirestoreEditionStore(InMemoryEditionStore):
    """Firestore-backed adapter with document-level optimistic transactions.

    The in-memory state machine remains the single transition authority. Each
    operation reloads the document, applies one guarded transition, and persists
    it. Firestore clients supplied in tests need only ``collection/document/get/set``.
    """

    def __init__(self, project_id: str, collection: str = "news_digest_editions",
                 client: Any = None, transaction_runner: Any = None) -> None:
        super().__init__()
        if client is None:
            from google.cloud import firestore  # type: ignore
            client = firestore.Client(project=project_id)
        self.client, self.collection = client, collection
        self.transaction_runner = transaction_runner

    def _doc(self, run_date: date) -> Any:
        return self.client.collection(self.collection).document(run_date.isoformat())

    def _load(self, run_date: date) -> None:
        snapshot = self._doc(run_date).get()
        if getattr(snapshot, "exists", False):
            self._editions[run_date] = edition_from_dict(snapshot.to_dict())

    def _save(self, run_date: date) -> None:
        self._doc(run_date).set(edition_to_dict(self._editions[run_date]))

    def _atomic(self, run_date: date, mutation: Any) -> Any:
        """Apply one state-machine transition in a Firestore transaction."""
        if self.transaction_runner is not None:
            return self.transaction_runner(self._doc(run_date), run_date, mutation, self)
        if not hasattr(self.client, "transaction"):
            # Lightweight injected fakes can exercise serialization without the
            # Google SDK. Production clients always take the transactional path.
            self._load(run_date)
            local = InMemoryEditionStore()
            if run_date in self._editions:
                local._editions[run_date] = self._editions[run_date]
            result = mutation(local)
            self._editions[run_date] = local._editions[run_date]
            self._save(run_date)
            return result
        from google.cloud import firestore  # type: ignore
        document = self._doc(run_date)
        transaction = self.client.transaction()

        @firestore.transactional
        def apply(current: Any) -> Any:
            snapshot = document.get(transaction=current)
            local = InMemoryEditionStore()
            if getattr(snapshot, "exists", False):
                local._editions[run_date] = edition_from_dict(snapshot.to_dict())
            result = mutation(local)
            current.set(document, edition_to_dict(local._editions[run_date]))
            self._editions[run_date] = local._editions[run_date]
            return result

        return apply(transaction)

    def acquire(self, run_date: date, owner: str, now: datetime, ttl: Any = None) -> Edition:
        return self._atomic(run_date, lambda local: local.acquire(run_date, owner, now, ttl)
                            if ttl else local.acquire(run_date, owner, now))

    def heartbeat(self, run_date: date, owner: str, now: datetime, ttl: Any = None) -> None:
        self._atomic(run_date, lambda local: local.heartbeat(run_date, owner, now, ttl)
                     if ttl else local.heartbeat(run_date, owner, now))

    def mark_missed(self, run_date: date, owner: str) -> None:
        self._atomic(run_date, lambda local: local.mark_missed(run_date, owner))

    def freeze(self, run_date: date, owner: str, messages: Any) -> str:
        return self._atomic(run_date, lambda local: local.freeze(run_date, owner, messages))

    def begin(self, run_date: date, owner: str, position: int, now: datetime) -> None:
        self._atomic(run_date, lambda local: local.begin(run_date, owner, position, now))

    def resolve(self, run_date: date, owner: str, position: int, status: DeliveryStatus, now: datetime) -> None:
        self._atomic(run_date, lambda local: local.resolve(run_date, owner, position, status, now))

    def recover_stale_pending(self, run_date: date, now: datetime, stale_after: Any = None) -> int:
        return self._atomic(run_date, lambda local: local.recover_stale_pending(run_date, now, stale_after)
                            if stale_after else local.recover_stale_pending(run_date, now))

    def reconcile_unknown_as_acknowledged(self, run_date: date, position: int,
                                          now: datetime, reason: str) -> None:
        self._atomic(run_date, lambda local: local.reconcile_unknown_as_acknowledged(
            run_date, position, now, reason))
