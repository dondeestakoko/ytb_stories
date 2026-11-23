import base64
import hashlib
import io
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import List
import requests
from PIL import Image, ImageDraw, ImageFilter

from src.config import (
    IMAGE_PROVIDER,
    IMAGES_16X9_DIR,
    IMAGES_9X16_DIR,
    POLLINATIONS_API_KEY,
    POLLINATIONS_IMAGE_MODEL,
    TIKTOK_SIZE,
    TOGETHER_API_KEY,
    YOUTUBE_SIZE,
)
from src.story_generator import StoryPackage, StoryScene

# Tracks whether the paid/quest Pollinations key returned HTTP 402 (balance $0.0000)
# so subsequent scenes go straight to the free Classic endpoint without wasted calls.
_GEN_API_BALANCE_EXHAUSTED = False
_LAST_CLASSIC_SUCCESS_TS = 0.0

SHOT_FRAMINGS = [
    "Wide establishing storybook shot",
    "Medium dynamic action shot",
    "Expressive close-up character shot",
    "Side-angle adventure shot",
    "Warm joyful medium-wide shot",
    "Magical nighttime wide shot",
]


@dataclass
class SceneImages:
    scene_number: int
    youtube_16x9_path: Path
    tiktok_9x16_path: Path


def _story_seed(title: str, scene_number: int) -> int:
    """Deterministic base seed per story with a distinct offset per scene so CDN never caches duplicate images."""
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()
    base = int(digest[:8], 16) % 900_000
    return base + (scene_number * 137)


def _build_concise_scene_prompt(story_pkg: StoryPackage, scene: StoryScene) -> str:
    """
    Places the unique scene action FIRST (inside CLIP's 77-token window) so every scene
    generates a visibly distinct illustration while preserving character and world DNA.
    """
    framing = SHOT_FRAMINGS[(scene.scene_number - 1) % len(SHOT_FRAMINGS)]
    action = scene.visual_prompt.strip().rstrip(".")
    character = story_pkg.character_visual_anchor.strip().rstrip(".")
    world = getattr(story_pkg, "world_visual_anchor", "").strip().rstrip(".")

    # Avoid duplicating character description if Gemini already included it in scene.visual_prompt
    if character[:35].lower() in action.lower():
        core = f"{framing}: {action}"
    else:
        core = f"{framing}: {action}. Character: {character}"

    if world:
        core = f"{core}. Setting: {world}"

    return (
        f"{core}, centered subject, 3D Pixar children's storybook illustration, "
        "warm magical lighting, vibrant colors, no text, no watermark"
    )


def _parse_retry_after_seconds(error_text: str, default_wait: int = 46) -> int:
    """Extracts 'Retry after XXs' from Pollinations rate-limit JSON responses."""
    match = re.search(r"Retry after\s+(\d+)\s*s", error_text, flags=re.IGNORECASE)
    if match:
        return max(int(match.group(1)) + 4, 8)
    return default_wait


def _fetch_pollinations_image(prompt: str, width: int, height: int, seed: int) -> Image.Image:
    """
    Downloads an AI-generated illustration from Pollinations:
      1. Tries `gen.pollinations.ai` if POLLINATIONS_API_KEY has remaining balance.
      2. Automatically falls back to the 100% free `image.pollinations.ai` endpoint,
         respecting its '1 image every 45 seconds per IP' cooldown so all 6 scenes succeed.
    """
    global _GEN_API_BALANCE_EXHAUSTED, _LAST_CLASSIC_SUCCESS_TS

    # Keep prompt under 650 chars so the URL never gets truncated or rejected by CDN
    trimmed_prompt = prompt[:650].strip()
    encoded_prompt = urllib.parse.quote(trimmed_prompt, safe="")

    # 1. Try gen.pollinations.ai once if key is configured and still has balance
    if POLLINATIONS_API_KEY and not _GEN_API_BALANCE_EXHAUSTED:
        model_chain = urllib.parse.quote(POLLINATIONS_IMAGE_MODEL, safe=",/")
        gen_url = (
            f"https://gen.pollinations.ai/image/{encoded_prompt}"
            f"?model={model_chain}&width={width}&height={height}&seed={seed}"
        )
        try:
            resp = requests.get(
                gen_url,
                headers={
                    "Authorization": f"Bearer {POLLINATIONS_API_KEY}",
                    "User-Agent": "YtbStoriesDailyBot/1.0",
                },
                timeout=75,
            )
            if resp.status_code == 200 and len(resp.content) > 4096:
                return Image.open(io.BytesIO(resp.content)).convert("RGB")
            if resp.status_code in (401, 402, 403):
                print(
                    f"        [Pollinations Info] Key balance exhausted or unauthorized "
                    f"(HTTP {resp.status_code}). Switching to free Classic endpoint with 45s pacing."
                )
                _GEN_API_BALANCE_EXHAUSTED = True
        except Exception as exc:
            print(f"        [Pollinations Info] gen.pollinations.ai error ({exc}), switching to Classic endpoint.")

    # 2. Free Classic endpoint (`image.pollinations.ai`) — enforces 1 image / 45s per IP
    classic_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&seed={seed}&model=flux&nologo=true"
    )

    # Proactively wait if less than 46 seconds have elapsed since the last Classic image download
    if _LAST_CLASSIC_SUCCESS_TS > 0:
        elapsed = time.time() - _LAST_CLASSIC_SUCCESS_TS
        if elapsed < 46.0:
            wait_gap = int(46.5 - elapsed) + 1
            print(f"        [Rate-Limit Pacing] Waiting {wait_gap}s before next free image request...")
            time.sleep(wait_gap)

    last_err: Exception | None = None
    for attempt in range(8):
        try:
            resp = requests.get(
                classic_url,
                headers={"User-Agent": f"Mozilla/5.0 YtbStoriesBot/1.0 (scene-seed-{seed})"},
                timeout=90,
            )
            if resp.status_code == 200 and len(resp.content) > 4096:
                _LAST_CLASSIC_SUCCESS_TS = time.time()
                return Image.open(io.BytesIO(resp.content)).convert("RGB")

            body_preview = resp.text[:240]
            last_err = RuntimeError(f"HTTP {resp.status_code}: {body_preview}")

            if resp.status_code in (402, 429):
                wait_sec = _parse_retry_after_seconds(resp.text, default_wait=46)
            elif resp.status_code in (500, 502, 503, 504):
                wait_sec = _parse_retry_after_seconds(resp.text, default_wait=15)
            else:
                wait_sec = 12 * (attempt + 1)

            print(
                f"        [Retry {attempt + 1}/8] Pollinations rate/load limit "
                f"(HTTP {resp.status_code}). Waiting {wait_sec}s..."
            )
            time.sleep(wait_sec)
        except Exception as exc:
            last_err = exc
            wait_sec = 12 * (attempt + 1)
            print(f"        [Retry {attempt + 1}/8] Network error ({exc}). Waiting {wait_sec}s...")
            time.sleep(wait_sec)

    raise RuntimeError(f"Pollinations image generation failed after 8 retries: {last_err}")


def _fetch_together_image(prompt: str, width: int, height: int, seed: int) -> Image.Image:
    """Optional Together AI Flux.1-schnell provider."""
    if not TOGETHER_API_KEY:
        raise ValueError("TOGETHER_API_KEY is required when IMAGE_PROVIDER=together")

    resp = requests.post(
        "https://api.together.xyz/v1/images/generations",
        headers={
            "Authorization": f"Bearer {TOGETHER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "black-forest-labs/FLUX.1-schnell",
            "prompt": prompt[:800],
            "width": width,
            "height": height,
            "steps": 4,
            "seed": seed,
            "n": 1,
            "response_format": "b64_json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    b64_data = resp.json()["data"][0]["b64_json"]
    return Image.open(io.BytesIO(base64.b64decode(b64_data))).convert("RGB")


def _generate_fallback_storybook_canvas(width: int, height: int, seed: int) -> Image.Image:
    """Creates a dreamy illustrated gradient backdrop if the image API is unreachable."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    palettes = [
        ((28, 37, 89), (118, 75, 162), (247, 168, 116)),
        ((19, 78, 94), (67, 137, 162), (235, 211, 142)),
        ((44, 62, 80), (189, 107, 115), (253, 200, 148)),
    ]
    top_c, mid_c, bot_c = palettes[seed % len(palettes)]
    for y in range(height):
        ratio = y / max(height - 1, 1)
        if ratio < 0.5:
            t = ratio * 2.0
            r = int(top_c[0] * (1 - t) + mid_c[0] * t)
            g = int(top_c[1] * (1 - t) + mid_c[1] * t)
            b = int(top_c[2] * (1 - t) + mid_c[2] * t)
        else:
            t = (ratio - 0.5) * 2.0
            r = int(mid_c[0] * (1 - t) + bot_c[0] * t)
            g = int(mid_c[1] * (1 - t) + bot_c[1] * t)
            b = int(mid_c[2] * (1 - t) + bot_c[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img.filter(ImageFilter.GaussianBlur(radius=2))


def _derive_aspect_ratios_from_master(
    master_img: Image.Image,
) -> tuple[Image.Image, Image.Image]:
    """
    Derives both 16:9 (1920x1080) and 9:16 (1080x1920) frames from a single 1280x1280
    master square illustration so we only need 6 API calls per story instead of 12.
    """
    w, h = master_img.size

    # 16:9 horizontal crop from centered 16:9 band
    crop_h_16x9 = int(round(w * 9 / 16))
    y0_16x9 = max(0, (h - crop_h_16x9) // 2)
    img_16x9 = master_img.crop((0, y0_16x9, w, y0_16x9 + crop_h_16x9)).resize(
        YOUTUBE_SIZE, Image.Resampling.LANCZOS
    )

    # 9:16 vertical crop from centered 9:16 band
    crop_w_9x16 = int(round(h * 9 / 16))
    x0_9x16 = max(0, (w - crop_w_9x16) // 2)
    img_9x16 = master_img.crop((x0_9x16, 0, x0_9x16 + crop_w_9x16, h)).resize(
        TIKTOK_SIZE, Image.Resampling.LANCZOS
    )

    return img_16x9, img_9x16


def _fetch_master_square_image(prompt: str, seed: int) -> Image.Image:
    master_size = (1280, 1280)
    try:
        if IMAGE_PROVIDER == "together" and TOGETHER_API_KEY:
            return _fetch_together_image(prompt, master_size[0], master_size[1], seed)
        return _fetch_pollinations_image(prompt, master_size[0], master_size[1], seed)
    except Exception as exc:
        print(f"        [Warning] Using fallback storybook canvas due to error: {exc}")
        return _generate_fallback_storybook_canvas(master_size[0], master_size[1], seed)


def generate_scene_images(story_pkg: StoryPackage) -> List[SceneImages]:
    """
    Generates 6 distinct scene illustrations (1 master 1280x1280 image per scene,
    adapted to both 16:9 YouTube and 9:16 Shorts/TikTok) while respecting free rate limits.
    """
    print(
        f"[3/5] Generating 6 distinct scene illustrations (adapted to 16:9 & 9:16) "
        f"via {IMAGE_PROVIDER}..."
    )
    results: List[SceneImages] = []

    for scene in story_pkg.scenes:
        scene_seed = _story_seed(story_pkg.title, scene.scene_number)
        scene_prompt = _build_concise_scene_prompt(story_pkg, scene)

        yt_path = IMAGES_16X9_DIR / f"scene_{scene.scene_number}_16x9.png"
        tt_path = IMAGES_9X16_DIR / f"scene_{scene.scene_number}_9x16.png"

        print(f"      Scene {scene.scene_number}/6: Generating master illustration (seed={scene_seed})...")
        master_img = _fetch_master_square_image(prompt=scene_prompt, seed=scene_seed)
        yt_img, tt_img = _derive_aspect_ratios_from_master(master_img)

        yt_img.save(yt_path, format="PNG")
        tt_img.save(tt_path, format="PNG")

        results.append(
            SceneImages(
                scene_number=scene.scene_number,
                youtube_16x9_path=yt_path,
                tiktok_9x16_path=tt_path,
            )
        )

    print("      All 6 scenes (6x 16:9 + 6x 9:16) generated and saved.")
    return results
