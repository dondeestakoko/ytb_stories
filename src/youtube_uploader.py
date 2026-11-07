import json
from pathlib import Path
import time
import requests

from src.config import (
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_MADE_FOR_KIDS,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_REFRESH_TOKEN,
)
from src.story_generator import StoryPackage

YOUTUBE_TOKEN_URI = "https://oauth2.googleapis.com/token"
YOUTUBE_RESUMABLE_UPLOAD_URI = "https://www.googleapis.com/upload/youtube/v3/videos"


def refresh_youtube_access_token() -> str:
    """Exchanges YOUTUBE_REFRESH_TOKEN for a fresh OAuth2 access_token via REST."""
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        raise ValueError(
            "Missing YouTube OAuth credentials (YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
            "or YOUTUBE_REFRESH_TOKEN). Run `python scripts/get_youtube_token.py` once locally."
        )

    resp = requests.post(
        YOUTUBE_TOKEN_URI,
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"YouTube OAuth token refresh failed ({resp.status_code}): {resp.text}")
    token_data = resp.json()
    return token_data["access_token"]


def upload_to_youtube(video_path: Path, story_pkg: StoryPackage) -> str | None:
    """Uploads the 16:9 story video to YouTube Data API v3 using Resumable Upload (1,600 quota units)."""
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        print("      [YouTube] Skipping upload: YouTube OAuth credentials not configured.")
        return None

    print(f"      [YouTube] Refreshing OAuth2 token and uploading {video_path.name}...")
    access_token = refresh_youtube_access_token()

    metadata = {
        "snippet": {
            "title": story_pkg.title[:100],
            "description": (
                f"{story_pkg.youtube_description}\n\n"
                f"Moral of the story: {story_pkg.moral}\n\n"
                "#KidsStories #BedtimeStories #MoralStories #ChildrensStory"
            ),
            "tags": story_pkg.youtube_tags[:20],
            "categoryId": "1",  # 1 = Film & Animation
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": YOUTUBE_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": YOUTUBE_MADE_FOR_KIDS,
        },
    }

    video_size = video_path.stat().st_size

    # Step 1: Initialize resumable upload session
    init_resp = requests.post(
        YOUTUBE_RESUMABLE_UPLOAD_URI,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(video_size),
            "X-Upload-Content-Type": "video/mp4",
        },
        data=json.dumps(metadata),
        timeout=30,
    )
    if init_resp.status_code != 200 or "Location" not in init_resp.headers:
        raise RuntimeError(
            f"YouTube resumable upload init failed ({init_resp.status_code}): {init_resp.text}"
        )

    upload_url = init_resp.headers["Location"]

    # Step 2: Upload video file in 8MB chunks with retry
    chunk_size = 8 * 1024 * 1024
    response_json = None

    with open(video_path, "rb") as f:
        offset = 0
        while offset < video_size:
            chunk = f.read(chunk_size)
            end_byte = offset + len(chunk) - 1
            for retry in range(4):
                put_resp = requests.put(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {offset}-{end_byte}/{video_size}",
                    },
                    data=chunk,
                    timeout=180,
                )
                if put_resp.status_code in (200, 201):
                    response_json = put_resp.json()
                    break
                elif put_resp.status_code == 308:
                    pct = int(((end_byte + 1) / video_size) * 100)
                    print(f"      [YouTube] Upload progress: {pct}%")
                    break
                elif put_resp.status_code in (500, 502, 503, 504) and retry < 3:
                    wait_sec = 2 ** (retry + 1)
                    print(f"      [YouTube] Transient HTTP {put_resp.status_code}, retrying in {wait_sec}s...")
                    time.sleep(wait_sec)
                else:
                    raise RuntimeError(
                        f"YouTube video upload failed ({put_resp.status_code}): {put_resp.text}"
                    )
            offset += len(chunk)

    if not response_json or "id" not in response_json:
        raise RuntimeError(f"YouTube upload finished without video ID: {response_json}")

    video_id = response_json["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"      [YouTube] Successfully uploaded! URL: {video_url}")
    return video_url
