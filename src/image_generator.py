import base64
import hashlib
import io
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
from src.story_generator import StoryPackage


@dataclass
class SceneImages:
    scene_number: int
    youtube_16x9_path: Path
    tiktok_9x16_path: Path


def _story_seed(title: str) -> int:
    """Locks a SINGLE deterministic seed per story so character face, outfit, and style stay consistent across all 6 scenes."""
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 1_000_000


def _fetch_pollinations_image(prompt: str, width: int, height: int, seed: int) -> Image.Image:
    """
    Downloads an AI-generated illustration from Pollinations (`https://gen.pollinations.ai/image/...`)
    using publisher/model IDs (`black-forest-labs/flux.1-schnell`, `tongyi-mai/z-image-turbo`).
    """
    clean_prompt = (
        f"{prompt}, Pixar 3D storybook illustration, warm magical lighting, "
        "vibrant colors, high detail, no text, no watermark"
    )
    encoded_prompt = urllib.parse.quote(clean_prompt, safe="")

    # Use caller-selected model fallback list per gen.pollinations.ai docs
    model_chain = f"{POLLINATIONS_IMAGE_MODEL},tongyi-mai/z-image-turbo,inferenceport-ai/lightning-image-turbo"

    headers = {"User-Agent": "YtbStoriesDailyBot/1.0"}
    if POLLINATIONS_API_KEY:
        headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

    endpoints = [
        (
            f"https://gen.pollinations.ai/image/{encoded_prompt}"
            f"?model={urllib.parse.quote(model_chain, safe=',')}&width={width}&height={height}&seed={seed}"
        ),
        (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&seed={seed}&model=flux&nologo=true"
        ),
    ]

    last_err: Exception | None = None
    for attempt in range(4):
        for url in endpoints:
            try:
                resp = requests.get(url, headers=headers, timeout=90)
                if resp.status_code == 200 and len(resp.content) > 2048:
                    return Image.open(io.BytesIO(resp.content)).convert("RGB")
                last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as exc:
                last_err = exc

        wait_sec = 3 * (attempt + 1)
        print(f"        [Retry {attempt + 1}/4] Pollinations image delayed ({last_err}). Retrying in {wait_sec}s...")
        time.sleep(wait_sec)

    raise RuntimeError(f"Pollinations image generation failed after 4 retries: {last_err}")


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
            "prompt": f"{prompt}, 3D children's book illustration, warm lighting, no text",
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


def _fetch_single_image(prompt: str, target_size: tuple[int, int], seed: int) -> Image.Image:
    if target_size[0] > target_size[1]:
        gen_w, gen_h = 1280, 720
    else:
        gen_w, gen_h = 720, 1280

    try:
        if IMAGE_PROVIDER == "together" and TOGETHER_API_KEY:
            img = _fetch_together_image(prompt, gen_w, gen_h, seed)
        else:
            img = _fetch_pollinations_image(prompt, gen_w, gen_h, seed)
    except Exception as exc:
        print(f"        [Warning] Using fallback storybook canvas due to error: {exc}")
        img = _generate_fallback_storybook_canvas(target_size[0], target_size[1], seed)

    if img.size != target_size:
        img = img.resize(target_size, Image.Resampling.LANCZOS)
    return img


def generate_scene_images(story_pkg: StoryPackage) -> List[SceneImages]:
    """Generates both 16:9 (YouTube) and 9:16 (TikTok/Shorts) illustrations for all 6 scenes with a locked seed & Character DNA."""
    locked_seed = _story_seed(story_pkg.title)
    print(
        f"[3/5] Generating 6 scene illustrations in dual aspect ratios (16:9 & 9:16) "
        f"via {IMAGE_PROVIDER} ({POLLINATIONS_IMAGE_MODEL}, locked_seed={locked_seed})..."
    )
    results: List[SceneImages] = []

    for scene in story_pkg.scenes:
        full_prompt = (
            f"Consistent character design: {story_pkg.character_visual_anchor}. "
            f"Consistent world & palette: {story_pkg.world_visual_anchor}. "
            f"Current scene action: {scene.visual_prompt}. "
            "Identical protagonist face, colors, and outfit, cute 3D Pixar storybook illustration"
        )

        yt_path = IMAGES_16X9_DIR / f"scene_{scene.scene_number}_16x9.png"
        tt_path = IMAGES_9X16_DIR / f"scene_{scene.scene_number}_9x16.png"

        print(f"      Scene {scene.scene_number}/6: Generating 16:9 YouTube image (seed={locked_seed})...")
        yt_img = _fetch_single_image(
            prompt=f"{full_prompt}, wide cinematic 16:9 composition",
            target_size=YOUTUBE_SIZE,
            seed=locked_seed,
        )
        yt_img.save(yt_path, format="PNG")

        print(f"      Scene {scene.scene_number}/6: Generating 9:16 Vertical image (seed={locked_seed})...")
        tt_img = _fetch_single_image(
            prompt=f"{full_prompt}, vertical portrait 9:16 centered composition",
            target_size=TIKTOK_SIZE,
            seed=locked_seed,
        )
        tt_img.save(tt_path, format="PNG")

        results.append(
            SceneImages(
                scene_number=scene.scene_number,
                youtube_16x9_path=yt_path,
                tiktok_9x16_path=tt_path,
            )
        )

    print("      All 12 images (6x 16:9 + 6x 9:16) saved with locked character consistency.")
    return results
