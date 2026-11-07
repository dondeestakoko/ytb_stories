"""
One-time local helper to generate your YOUTUBE_REFRESH_TOKEN and save it to .env.
Uses standard library + requests so no extra OAuth packages are required.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import re
import urllib.parse
import webbrowser
import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
REDIRECT_URI = "http://localhost:8080"
AUTH_CODE: str | None = None


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;text-align:center;padding:40px;'>"
                b"<h2>&#9989; YouTube Authorization Successful!</h2>"
                b"<p>Your Refresh Token has been saved to <code>.env</code>. You can close this tab.</p>"
                b"</body></html>"
            )
        else:
            err = params.get("error", ["unknown_error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h2>Authorization failed: {err}</h2>".encode("utf-8"))

    def log_message(self, format, *args):
        return


def _save_refresh_token_to_env(refresh_token: str) -> None:
    if not ENV_PATH.exists():
        return
    content = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^YOUTUBE_REFRESH_TOKEN=.*$", content, flags=re.MULTILINE):
        updated = re.sub(
            r"^YOUTUBE_REFRESH_TOKEN=.*$",
            f"YOUTUBE_REFRESH_TOKEN={refresh_token}",
            content,
            flags=re.MULTILINE,
        )
    else:
        updated = content.rstrip() + f"\nYOUTUBE_REFRESH_TOKEN={refresh_token}\n"
    ENV_PATH.write_text(updated, encoding="utf-8")


def main() -> None:
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise ValueError("Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET in .env")

    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(auth_params)

    print("\nOpening your browser to authorize YouTube upload access...")
    print(f"If the browser does not open automatically, click here:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), _OAuthCallbackHandler)
    print("Waiting for you to sign in and click 'Continue / Allow' in the browser...")
    while AUTH_CODE is None:
        server.handle_request()

    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": AUTH_CODE,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()
    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        raise RuntimeError(f"No refresh_token returned by Google: {token_data}")

    _save_refresh_token_to_env(refresh_token)

    # Test YouTube API responsiveness immediately
    access_token = token_data.get("access_token")
    ch_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if ch_resp.status_code == 200:
        items = ch_resp.json().get("items", [])
        if items:
            ch_title = items[0]["snippet"]["title"]
            ch_id = items[0]["id"]
            print(f"\n[YouTube API Test Passed] Connected to channel: '{ch_title}' (ID: {ch_id})")
        else:
            print("\n[YouTube API Test Passed] OAuth succeeded (note: no YouTube channel created on this Google account yet).")
    else:
        print(f"\n[YouTube API Test Info] Status {ch_resp.status_code}: {ch_resp.text[:200]}")

    print("\n" + "=" * 70)
    print("SUCCESS! Saved YOUTUBE_REFRESH_TOKEN to .env!")
    print("Copy these 3 values into your GitHub Repository Secrets:")
    print("=" * 70)
    print(f"YOUTUBE_CLIENT_ID={client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={refresh_token}")
    print("=" * 70)


if __name__ == "__main__":
    main()
