import json
import math
from pathlib import Path
import tempfile
import requests

from src.config import (
    TIKTOK_CLIENT_KEY,
    TIKTOK_CLIENT_SECRET,
    TIKTOK_COOKIES_JSON,
    TIKTOK_PRIVACY_LEVEL,
    TIKTOK_REFRESH_TOKEN,
    TIKTOK_UPLOAD_MODE,
)
from src.story_generator import StoryPackage

TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"


def _refresh_tiktok_access_token() -> tuple[str, str | None]:
    """Exchanges TIKTOK_REFRESH_TOKEN for a fresh access_token via TikTok OAuth v2."""
    resp = requests.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": TIKTOK_REFRESH_TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "access_token" not in payload:
        raise RuntimeError(f"TikTok OAuth refresh failed: {payload}")
    return payload["access_token"], payload.get("refresh_token")


def _upload_via_official_api(video_path: Path, story_pkg: StoryPackage) -> str:
    """Uploads the 9:16 video using TikTok's official Content Posting API v2."""
    print(f"      [TikTok-Official] Refreshing OAuth2 token and uploading {video_path.name}...")
    access_token, _ = _refresh_tiktok_access_token()

    video_size = video_path.stat().st_size
    # TikTok requires chunk_size between 5MB and 64MB (or exact video_size if < 64MB)
    chunk_size = video_size if video_size <= 60 * 1024 * 1024 else 10 * 1024 * 1024
    total_chunk_count = math.ceil(video_size / chunk_size)

    caption = f"{story_pkg.title} - {story_pkg.tiktok_caption}"[:2200]

    # Try configured privacy level first; fallback to SELF_ONLY if app is still unaudited
    privacy_candidates = [TIKTOK_PRIVACY_LEVEL]
    if "SELF_ONLY" not in privacy_candidates:
        privacy_candidates.append("SELF_ONLY")

    init_data = None
    for privacy in privacy_candidates:
        init_resp = requests.post(
            TIKTOK_VIDEO_INIT_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "post_info": {
                    "title": caption,
                    "privacy_level": privacy,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunk_count,
                },
            },
            timeout=30,
        )
        body = init_resp.json()
        err_code = body.get("error", {}).get("code", "ok")
        if init_resp.status_code == 200 and err_code == "ok":
            init_data = body["data"]
            if privacy != TIKTOK_PRIVACY_LEVEL:
                print(
                    "      [TikTok-Official] Note: App is unaudited, posted with privacy_level=SELF_ONLY."
                )
            break
        elif "unaudited" in str(err_code).lower() and privacy != "SELF_ONLY":
            print(
                f"      [TikTok-Official] {err_code} with {privacy}; retrying with SELF_ONLY..."
            )
            continue
        else:
            raise RuntimeError(f"TikTok video init failed: {body}")

    if not init_data:
        raise RuntimeError("TikTok video init returned no data.")

    upload_url = init_data["upload_url"]
    publish_id = init_data["publish_id"]

    with open(video_path, "rb") as f:
        for chunk_idx in range(total_chunk_count):
            chunk_bytes = f.read(chunk_size)
            start_byte = chunk_idx * chunk_size
            end_byte = start_byte + len(chunk_bytes) - 1
            put_resp = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk_bytes)),
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{video_size}",
                },
                data=chunk_bytes,
                timeout=120,
            )
            put_resp.raise_for_status()

    print(f"      [TikTok-Official] Upload complete! publish_id={publish_id}")
    return f"tiktok://publish/{publish_id}"


def _upload_via_cookies(video_path: Path, story_pkg: StoryPackage) -> str:
    """Uploads the 9:16 video using browser cookies via tiktok-uploader."""
    print(f"      [TikTok-Cookies] Uploading {video_path.name} via browser session cookies...")
    from tiktok_uploader.upload import upload_video

    caption = f"{story_pkg.title} {story_pkg.tiktok_caption}"[:400]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tmp_cookie_file:
        cookie_path = Path(tmp_cookie_file.name)
        # Support either Netscape cookies.txt format or JSON cookie list
        raw = TIKTOK_COOKIES_JSON.strip()
        if raw.startswith("["):
            cookies_list = json.loads(raw)
            lines = ["# Netscape HTTP Cookie File"]
            for c in cookies_list:
                domain = c.get("domain", ".tiktok.com")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure", True) else "FALSE"
                expiry = int(c.get("expirationDate", 2147483647))
                name = c.get("name", "")
                value = c.get("value", "")
                lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")
            tmp_cookie_file.write("\n".join(lines))
        else:
            tmp_cookie_file.write(raw)

    try:
        upload_video(
            filename=str(video_path),
            description=caption,
            cookies=str(cookie_path),
            headless=True,
        )
    finally:
        cookie_path.unlink(missing_ok=True)

    print("      [TikTok-Cookies] Successfully uploaded video to TikTok!")
    return "tiktok://cookie-upload/success"


def upload_to_tiktok(video_path: Path, story_pkg: StoryPackage) -> str | None:
    """
    Uploads the 9:16 story video to TikTok.
    Supports Official Content Posting API, Cookie fallback, or automatic fallback.
    """
    has_official = bool(TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN)
    has_cookies = bool(TIKTOK_COOKIES_JSON)

    if TIKTOK_UPLOAD_MODE == "official":
        if not has_official:
            raise ValueError("TIKTOK_UPLOAD_MODE=official requires TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and TIKTOK_REFRESH_TOKEN.")
        return _upload_via_official_api(video_path, story_pkg)

    if TIKTOK_UPLOAD_MODE == "cookies":
        if not has_cookies:
            raise ValueError("TIKTOK_UPLOAD_MODE=cookies requires TIKTOK_COOKIES_JSON.")
        return _upload_via_cookies(video_path, story_pkg)

    # Auto mode: prefer official API if configured, otherwise cookies, or fallback on error
    if has_official:
        try:
            return _upload_via_official_api(video_path, story_pkg)
        except Exception as exc:
            print(f"      [TikTok] Official API failed ({exc}).")
            if has_cookies:
                print("      [TikTok] Falling back to cookie-based uploader...")
                return _upload_via_cookies(video_path, story_pkg)
            raise

    if has_cookies:
        return _upload_via_cookies(video_path, story_pkg)

    print("      [TikTok] Skipping upload: Neither Official TikTok OAuth credentials nor TIKTOK_COOKIES_JSON configured.")
    return None
