"""
One-time helper to authorize and save your POLLINATIONS_API_KEY (`sk_...`) into `.env`
using the Pollinations Device Flow (https://enter.pollinations.ai/api/device/code).
"""
from pathlib import Path
import re
import time
import webbrowser
import requests

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _save_pollinations_key_to_env(api_key: str) -> None:
    if not ENV_PATH.exists():
        return
    content = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^POLLINATIONS_API_KEY=.*$", content, flags=re.MULTILINE):
        updated = re.sub(
            r"^POLLINATIONS_API_KEY=.*$",
            f"POLLINATIONS_API_KEY={api_key}",
            content,
            flags=re.MULTILINE,
        )
    else:
        updated = content.rstrip() + f"\nPOLLINATIONS_API_KEY={api_key}\n"
    ENV_PATH.write_text(updated, encoding="utf-8")


def main() -> None:
    resp = requests.post(
        "https://enter.pollinations.ai/api/device/code",
        json={"client_id": "ytb-stories-cli"},
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    verify_url = data["verification_uri_complete"]
    print("\nOpening browser for Pollinations authorization...")
    print(f"URL:       {verify_url}")
    print(f"User code: {data['user_code']}\n")
    webbrowser.open(verify_url)

    interval = int(data.get("interval", 5))
    while True:
        time.sleep(interval)
        poll = requests.post(
            "https://enter.pollinations.ai/api/device/token",
            json={"device_code": data["device_code"]},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if poll.status_code == 200:
            sk_key = poll.json()["access_token"]
            _save_pollinations_key_to_env(sk_key)
            print("=" * 70)
            print("SUCCESS! Saved POLLINATIONS_API_KEY to .env!")
            print(f"POLLINATIONS_API_KEY={sk_key}")
            print("=" * 70)
            return
        err = poll.json().get("error")
        if err == "authorization_pending":
            continue
        raise RuntimeError(f"Pollinations device auth failed: {poll.json()}")


if __name__ == "__main__":
    main()
