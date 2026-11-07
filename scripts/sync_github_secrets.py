"""
Automatically encrypts and uploads the 6 required secrets from your local `.env`
file directly into GitHub Actions Repository Secrets (`dondeestakoko/ytb_stories`).
"""
import base64
import os
from pathlib import Path
import subprocess
import requests
from dotenv import load_dotenv
from nacl import encoding, public

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

REPO = "dondeestakoko/ytb_stories"
SECRET_NAMES = [
    "GEMINI_API_KEY",
    "POLLINATIONS_API_KEY",
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
    "TIKTOK_COOKIES_JSON",
]


def _get_git_credentials() -> tuple[str, str]:
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=True,
    )
    creds = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    return creds.get("username", ""), creds.get("password", "")


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pub_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(pub_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def main() -> None:
    auth = _get_git_credentials()

    pk_resp = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        auth=auth,
        timeout=20,
    )
    pk_resp.raise_for_status()
    pk_data = pk_resp.json()
    key_id = pk_data["key_id"]
    public_key = pk_data["key"]

    for name in SECRET_NAMES:
        val = os.getenv(name, "").strip()
        if not val:
            print(f"[SKIP] {name} is empty in .env")
            continue

        encrypted_value = _encrypt_secret(public_key, val)
        put_resp = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
            auth=auth,
            json={
                "encrypted_value": encrypted_value,
                "key_id": key_id,
            },
            timeout=20,
        )
        put_resp.raise_for_status()
        print(f"[OK] Uploaded secret {name} to {REPO} (HTTP {put_resp.status_code})")


if __name__ == "__main__":
    main()
