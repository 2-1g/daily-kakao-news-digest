"""Standard-library HTTP adapters used by source, OAuth, and Kakao clients."""

import json
from datetime import datetime, timedelta, timezone
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .auth import OAuthToken, ReauthorizationRequired
from .kakao import DefiniteDeliveryError
from .sources.base import HttpResponse


class UrllibHttpClient:
    def get(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=20) as response:
                return HttpResponse(response.status, response.read(), dict(response.headers))
        except HTTPError as exc:
            return HttpResponse(exc.code, exc.read(), dict(exc.headers))


class KakaoHttpTransport:
    endpoint = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

    def send_self_message(self, access_token: str, text: str) -> None:
        template = {"object_type": "text", "text": text,
                    "link": {"web_url": "https://developers.kakao.com",
                             "mobile_web_url": "https://developers.kakao.com"}}
        body = urlencode({"template_object": json.dumps(template, ensure_ascii=False)}).encode()
        request = Request(self.endpoint, data=body,
                          headers={"Authorization": "Bearer " + access_token,
                                   "Content-Type": "application/x-www-form-urlencoded"},
                          method="POST")
        try:
            with urlopen(request, timeout=20) as response:
                if response.status < 200 or response.status >= 300:
                    raise DefiniteDeliveryError("Kakao rejected message")
        except HTTPError as exc:
            raise DefiniteDeliveryError("Kakao rejected message with status %d" % exc.code) from exc
        # URLError/timeouts deliberately bubble and become ambiguous in KakaoClient.


class KakaoOAuthHttpRefresher:
    endpoint = "https://kauth.kakao.com/oauth/token"

    def __init__(self, client_id: str, client_secret: str = "") -> None:
        self.client_id, self.client_secret = client_id, client_secret

    def refresh(self, refresh_token: str) -> OAuthToken:
        fields = {"grant_type": "refresh_token", "client_id": self.client_id,
                  "refresh_token": refresh_token}
        if self.client_secret:
            fields["client_secret"] = self.client_secret
        request = Request(self.endpoint, data=urlencode(fields).encode(), method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (400, 401):
                raise ReauthorizationRequired("Kakao refresh grant rejected") from exc
            raise
        now = datetime.now(timezone.utc)
        refresh_expiry = payload.get("refresh_token_expires_in")
        return OAuthToken(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload.get("refresh_token", "")),
            access_expires_at=now + timedelta(seconds=int(payload["expires_in"])),
            refresh_expires_at=(now + timedelta(seconds=int(refresh_expiry))
                                if refresh_expiry is not None else None),
        )


class KakaoOAuthCodeExchanger:
    """Attended authorization-code exchange; token values are never logged."""

    endpoint = "https://kauth.kakao.com/oauth/token"

    def __init__(self, client_id: str, redirect_uri: str, client_secret: str = "") -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.client_secret = client_secret

    def exchange(self, code: str) -> OAuthToken:
        if not code.strip():
            raise ValueError("authorization code is required")
        fields = {"grant_type": "authorization_code", "client_id": self.client_id,
                  "redirect_uri": self.redirect_uri, "code": code.strip()}
        if self.client_secret:
            fields["client_secret"] = self.client_secret
        request = Request(self.endpoint, data=urlencode(fields).encode(), method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ReauthorizationRequired("Kakao authorization-code grant rejected") from exc
        now = datetime.now(timezone.utc)
        refresh_expiry = payload.get("refresh_token_expires_in")
        return OAuthToken(
            str(payload["access_token"]), str(payload["refresh_token"]),
            now + timedelta(seconds=int(payload["expires_in"])),
            now + timedelta(seconds=int(refresh_expiry)) if refresh_expiry is not None else None,
        )
