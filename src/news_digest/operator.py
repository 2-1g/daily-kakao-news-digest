"""Attended operator commands. Scheduled runtime must never invoke this module."""

import getpass
import json
import secrets
from datetime import date, datetime, timezone
from typing import Optional

from .auth import kakao_authorization_url
from .cloud import FirestoreEditionStore, SecretManagerTokenStore
from .http import KakaoOAuthCodeExchanger


def authorization_url(client_id: str, redirect_uri: str, state: Optional[str] = None) -> str:
    return kakao_authorization_url(client_id, redirect_uri, state or secrets.token_urlsafe(24))


def bootstrap_token(project_id: str, secret_id: str, client_id: str, redirect_uri: str,
                    client_secret: str = "", code: Optional[str] = None,
                    replace_active: bool = False) -> str:
    authorization_code = code or getpass.getpass("Kakao authorization code: ")
    token = KakaoOAuthCodeExchanger(client_id, redirect_uri, client_secret).exchange(
        authorization_code)
    store = SecretManagerTokenStore(project_id, secret_id)
    version = store.install_bootstrap_token(token, replace_active=replace_active)
    # Return metadata only. Token and authorization code must never enter stdout/logs.
    return json.dumps({"status": "stored", "secret": secret_id, "version": version})


def reconcile_delivery(project_id: str, edition_id: str, message_index: int,
                       reason: str, operator: str) -> str:
    try:
        run_date = date.fromisoformat(edition_id)
    except ValueError as exc:
        raise ValueError("edition id must be an ISO date (YYYY-MM-DD)") from exc
    if message_index < 1:
        raise ValueError("message index must be >= 1")
    store = FirestoreEditionStore(project_id)
    store.reconcile_unknown_as_acknowledged(run_date, message_index,
                                             datetime.now(timezone.utc), reason, operator)
    return json.dumps({"status": "acknowledged", "edition_id": edition_id,
                       "message_index": message_index, "operator": operator},
                      ensure_ascii=False, sort_keys=True)
