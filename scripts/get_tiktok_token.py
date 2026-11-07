"""
One-time local helper to generate your TIKTOK_REFRESH_TOKEN (Official TikTok Content Posting API).

Usage:
  1. Create an app at https://developers.tiktok.com/
  2. Enable "Content Posting API" and add scope `video.publish`
  3. Set Redirect URI to `http://localhost:8085/callback/`
  4. Run: python scripts/get_tiktok_token.py
"""
import os
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "http://localhost:8085/callback/"
AUTH_CODE: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>TikTok Auth Successful! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        return


def main() -> None:
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip() or input("Enter TIKTOK_CLIENT_KEY: ").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip() or input("Enter TIKTOK_CLIENT_SECRET: ").strip()

    auth_url = (
        "https://www.tiktok.com/v2/auth/authorize/?"
        + urllib.parse.urlencode(
            {
                "client_key": client_key,
                "scope": "user.info.basic,video.publish",
                "response_type": "code",
                "redirect_uri": REDIRECT_URI,
                "state": "ytb_stories_init",
            }
        )
    )

    print(f"\nOpening browser for TikTok login:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8085), _CallbackHandler)
    print("Waiting for redirect on http://localhost:8085/callback/ ...")
    while AUTH_CODE is None:
        server.handle_request()

    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": AUTH_CODE,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    print("\n" + "=" * 70)
    print("SUCCESS! Copy these 3 values into your GitHub Repository Secrets:")
    print("=" * 70)
    print(f"TIKTOK_CLIENT_KEY={client_key}")
    print(f"TIKTOK_CLIENT_SECRET={client_secret}")
    print(f"TIKTOK_REFRESH_TOKEN={data.get('refresh_token')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
