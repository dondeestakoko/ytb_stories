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
    YOUTUBE_UPLOAD_SHORT,
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


def upload_to_youtube(
    video_path: Path,
    story_pkg: StoryPackage,
    is_short: bool = False,
    access_token: str | None = None,
    lang: str = "en",
) -> str | None:
    """
    Uploads a story video to YouTube Data API v3 using Resumable Upload (1,600 quota units).
    - Supports both English (`lang='en'`) and French (`lang='fr'`).
    - When `is_short=False`: uploads the normal 16:9 horizontal video.
    - When `is_short=True`: uploads the 9:16 vertical video as a YouTube Short (#Shorts).
    - Sets `selfDeclaredMadeForKids` (default False = 'Non, elle n'est pas conçue pour les enfants'
      and no 18+ age restriction, preserving comments and monetization).
    """
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        print("      [YouTube] Skipping upload: YouTube OAuth credentials not configured.")
        return None

    lang_code = "fr" if lang == "fr" else "en"
    label = f"YouTube [{lang_code.upper()}] Short (9:16)" if is_short else f"YouTube [{lang_code.upper()}] Normal Video (16:9)"
    if not access_token:
        print(f"      [{label}] Refreshing OAuth2 token...")
        access_token = refresh_youtube_access_token()

    print(f"      [{label}] Uploading {video_path.name} (selfDeclaredMadeForKids={YOUTUBE_MADE_FOR_KIDS})...")

    if lang_code == "fr":
        base_title = (getattr(story_pkg, "title_fr", "") or story_pkg.title).strip()
        desc_text = getattr(story_pkg, "youtube_description_fr", "") or story_pkg.youtube_description
        moral_line = f"Morale de l'histoire : {getattr(story_pkg, 'moral_fr', '') or story_pkg.moral}"
        base_tags = getattr(story_pkg, "youtube_tags_fr", None) or story_pkg.youtube_tags
        base_hashtags = "#Histoire #Conte #Morale #HistoireDuSoir #FableAnimee"
    else:
        base_title = story_pkg.title.strip()
        desc_text = story_pkg.youtube_description
        moral_line = f"Moral of the story: {story_pkg.moral}"
        base_tags = story_pkg.youtube_tags
        base_hashtags = "#Storytime #MoralStories #BedtimeStories #AnimatedStory #Fables"

    if is_short:
        if "#shorts" not in base_title.lower():
            title = f"{base_title[:91].rstrip()} #Shorts"
        else:
            title = base_title[:100]
        hashtags = f"#Shorts {base_hashtags}"
        tags = list(dict.fromkeys(["Shorts", "YouTube Shorts"] + base_tags))[:20]
    else:
        title = base_title[:100]
        hashtags = base_hashtags
        tags = base_tags[:20]

    metadata = {
        "snippet": {
            "title": title,
            "description": (
                f"{desc_text}\n\n"
                f"{moral_line}\n\n"
                f"{hashtags}"
            ),
            "tags": tags,
            "categoryId": "1",  # 1 = Film & Animation
            "defaultLanguage": lang_code,
            "defaultAudioLanguage": lang_code,
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
    video_url = (
        f"https://www.youtube.com/shorts/{video_id}"
        if is_short
        else f"https://www.youtube.com/watch?v={video_id}"
    )
    print(f"      [{label}] Successfully uploaded! URL: {video_url}")
    return video_url


def upload_both_to_youtube(
    normal_video_path: Path,
    short_video_path: Path,
    story_pkg: StoryPackage,
    lang: str = "en",
    access_token: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Uploads BOTH for a given language (`en` or `fr`):
      1. The 16:9 horizontal video as a normal YouTube video.
      2. The 9:16 vertical video as a YouTube Short (#Shorts).
    Reuses a single OAuth access_token refresh across uploads.
    """
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        print("      [YouTube] Skipping upload: YouTube OAuth credentials not configured.")
        return None, None

    if not access_token:
        access_token = refresh_youtube_access_token()

    normal_url = upload_to_youtube(
        video_path=normal_video_path,
        story_pkg=story_pkg,
        is_short=False,
        access_token=access_token,
        lang=lang,
    )

    short_url = None
    if YOUTUBE_UPLOAD_SHORT:
        short_url = upload_to_youtube(
            video_path=short_video_path,
            story_pkg=story_pkg,
            is_short=True,
            access_token=access_token,
            lang=lang,
        )

    return normal_url, short_url
