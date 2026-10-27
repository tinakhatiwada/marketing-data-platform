"""One-time helper: get a Google OAuth2 refresh token for GA4 + Google Ads.

1. In Google Cloud Console create an OAuth client of type "Desktop app".
2. Run:  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python scripts/get_google_refresh_token.py
3. Approve in the browser with a Google account that can read the GA4 properties
   and the Google Ads accounts. Paste the printed token into Secret Manager / .env.

Uses the loopback redirect flow with PKCE; nothing is stored on disk.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import os
import secrets
import urllib.parse
import webbrowser

import requests

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/adwords",
]
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/"


def main() -> None:
    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    state = secrets.token_urlsafe(16)

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge.decode(), "code_challenge_method": "S256", "state": state,
    })
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            result.update(query)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done - you can close this tab.")

        def log_message(self, *args):
            pass

    print(f"Opening browser. If it doesn't open, visit:\n{url}\n")
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", PORT), Handler) as server:
        server.handle_request()

    if result.get("state") != state or "code" not in result:
        raise SystemExit(f"Authorisation failed: {result.get('error', 'state mismatch')}")

    token = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    token.raise_for_status()
    print("GOOGLE_REFRESH_TOKEN=" + token.json()["refresh_token"])


if __name__ == "__main__":
    main()
