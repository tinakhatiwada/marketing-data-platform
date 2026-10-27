"""Authentication helpers.

Google (GA4 Data API + Google Ads API) uses OAuth2. The pipeline runs unattended,
so it stores a long-lived *refresh token* (obtained once, via a consent flow) and
exchanges it for short-lived access tokens, caching each until shortly before it
expires.

Meta uses a long-lived System User access token. If an app secret is configured
we also send `appsecret_proof`, which Meta recommends for server-side calls.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from adpulse.http import HttpClient

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleOAuth2:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        http: HttpClient | None = None,
        clock=time.time,
    ):
        missing = [n for n, v in [("GOOGLE_CLIENT_ID", client_id),
                                  ("GOOGLE_CLIENT_SECRET", client_secret),
                                  ("GOOGLE_REFRESH_TOKEN", refresh_token)] if not v]
        if missing:
            raise ValueError(f"Missing Google OAuth settings: {', '.join(missing)}")
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._http = http or HttpClient(name="google-oauth", max_retries=3)
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def access_token(self) -> str:
        # Refresh a minute early so a token never expires mid-pagination.
        if self._token is None or self._clock() >= self._expires_at - 60:
            data = self._http.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                },
            )
            self._token = data["access_token"]
            self._expires_at = self._clock() + float(data.get("expires_in", 3600))
        return self._token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}"}


def meta_appsecret_proof(access_token: str, app_secret: str) -> str:
    return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()
