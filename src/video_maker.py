import math
from pathlib import Path
import random
from typing import Dict, List, Tuple
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips

from src.config import (
    BURN_SUBTITLES,
    OUTPUT_DIR,
    TIKTOK_SIZE,
    VIDEO_FPS,
    YOUTUBE_SIZE,
)
from src.image_generator import SceneImages
from src.story_generator import StoryPackage, StoryScene
from src.tts_generator import SceneAudioResult


def _load_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads a clean bold sans-serif font across Windows, macOS, and Ubuntu runners."""
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for path in candidate_paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=font_size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def _prerender_subtitle_strip(
    text: str,
    frame_size: Tuple[int, int],
) -> Tuple[int, np.ndarray, np.ndarray]:
    """
    Pre-renders a subtitle cue onto a compact RGBA strip to alpha-blend onto frames.
    Returns (y_top, rgb_array, alpha_array_float32).
    """
    width, height = frame_size
    is_vertical = height > width
    font_size = 44 if is_vertical else 42
    max_chars_per_line = 26 if is_vertical else 46
    strip_height = 240 if is_vertical else 180
    bottom_margin = 180 if is_vertical else 50

    font = _load_font(font_size)
    wrapped_lines = textwrap.wrap(text.strip(), width=max_chars_per_line) or [text.strip()]
    multiline_text = "\n".join(wrapped_lines)

    overlay = Image.new("RGBA", (width, strip_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    bbox = draw.multiline_textbbox((0, 0), multiline_text, font=font, align="center", spacing=8)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_x, pad_y = 32, 18
    box_x0 = max(20, (width - text_w) // 2 - pad_x)
    box_y0 = max(8, (strip_height - text_h) // 2 - pad_y)
    box_x1 = min(width - 20, (width + text_w) // 2 + pad_x)
    box_y1 = min(strip_height - 8, (strip_height + text_h) // 2 + pad_y)

    # Rounded dark pill background for readability
    draw.rounded_rectangle(
        [box_x0, box_y0, box_x1, box_y1],
        radius=20,
        fill=(15, 18, 28, 185),
    )

    text_x = (width - text_w) // 2
    text_y = (strip_height - text_h) // 2 - bbox[1]

    # Crisp outline + warm white/gold text
    draw.multiline_text(
        (text_x, text_y),
        multiline_text,
        font=font,
        fill=(255, 250, 220, 255),
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
        align="center",
        spacing=8,
    )

    rgba = np.array(overlay)
    rgb = rgba[:, :, :3]
    alpha = (rgba[:, :, 3:4].astype(np.float32)) / 255.0
    y_top = max(0, height - strip_height - bottom_margin)
    return y_top, rgb, alpha


def _build_glow_stamp(radius: int, color_rgb: Tuple[int, int, int]) -> np.ndarray:
    """
    Pre-computes a radial Gaussian glow stamp of shape (2*r+1, 2*r+1, 3) in float32
    for fast additive blending of Disney fireflies and fairy-dust sparkles.
    """
    size = 2 * radius + 1
    y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    dist_sq = (x * x + y * y) / max(float(radius * radius), 1.0)
    # Soft outer halo + bright core
    falloff = np.exp(-3.2 * dist_sq) * (dist_sq <= 1.0)
    stamp = np.zeros((size, size, 3), dtype=np.float32)
    stamp[:, :, 0] = falloff * color_rgb[0]
    stamp[:, :, 1] = falloff * color_rgb[1]
    stamp[:, :, 2] = falloff * color_rgb[2]
    return stamp


def _init_disney_particles(scene_number: int, width: int, height: int, count: int = 26) -> List[dict]:
    """Spawns deterministic floating Disney fireflies and magic dust particles for a scene."""
    rng = random.Random(scene_number * 9973 + width)
    stamps = [
        _build_glow_stamp(7, (255, 240, 175)),   # Small warm gold sparkle
        _build_glow_stamp(12, (255, 225, 130)),  # Medium golden firefly
        _build_glow_stamp(19, (255, 248, 210)),  # Large soft foreground bokeh
    ]
    particles: List[dict] = []
    for _ in range(count):
        stamp = rng.choices(stamps, weights=[0.5, 0.35, 0.15])[0]
        particles.append(
            {
                "x0": rng.uniform(0.05 * width, 0.95 * width),
                "y0": rng.uniform(0.08 * height, 0.92 * height),
                "vy": rng.uniform(14.0, 34.0),          # Upward floating speed (px/sec)
                "sway_amp": rng.uniform(12.0, 38.0),    # Horizontal sine sway amplitude (px)
                "sway_freq": rng.uniform(0.7, 1.6),     # Horizontal sway frequency (rad/sec)
                "twinkle_freq": rng.uniform(1.8, 3.8),  # Brightness pulse frequency
                "phase": rng.uniform(0.0, 2.0 * math.pi),
                "base_intensity": rng.uniform(0.45, 0.92),
                "stamp": stamp,
                "radius": stamp.shape[0] // 2,
            }
        )
    return particles


def _build_sunlight_band(width: int, height: int) -> Tuple[int, np.ndarray]:
    """
    Pre-computes a warm golden Disney top-sunlight glow strip covering the top 30% of the frame.
    Returns (band_height, sun_glow_float32).
    """
    band_h = max(64, int(height * 0.28))
    y_norm = np.linspace(0.0, 1.0, band_h, dtype=np.float32)[:, None]
    x_norm = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    # Soft warm sunbeams emanating from the upper-left/center canopy
    radial = np.exp(-2.8 * (y_norm * y_norm + 0.35 * (x_norm - 0.3) ** 2))
    sun_band = np.zeros((band_h, width, 3), dtype=np.float32)
    sun_band[:, :, 0] = radial * 36.0  # Warm golden R
    sun_band[:, :, 1] = radial * 27.0  # Warm golden G
    sun_band[:, :, 2] = radial * 8.0   # Subtle amber B
    return band_h, sun_band


def _create_scene_videoclip(
    image_path: Path,
    scene: StoryScene,
    scene_audio: SceneAudioResult,
    target_size: Tuple[int, int],
    prev_image_path: Path | None = None,
) -> VideoClip:
    """
    Builds a Disney-style 2.5D Living-Scene VideoClip with:
      1. 2.5D floating camera + sinusoidal breathing rhythm
      2. Animated twinkling fireflies & fairy-dust bokeh particles
      3. Pulsing golden sunlight rays
      4. Smooth 0.40s visual cross-dissolve from previous scene (preserving exact audio sync)
      5. Burned-in subtitles
    """
    width, height = target_size
    duration = scene_audio.duration
    motion = scene.camera_motion

    base_img = Image.open(image_path).convert("RGB")
    if base_img.size != (width, height):
        base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)

    # Pre-upscale by 16% for smooth 2.5D pan/zoom + breathing motion
    scale_max = 1.16
    up_w, up_h = int(round(width * scale_max)), int(round(height * scale_max))
    upscaled_img = base_img.resize((up_w, up_h), Image.Resampling.LANCZOS)
    upscaled_np = np.array(upscaled_img)

    # Optional previous scene frame for seamless 0.40s visual cross-dissolve at scene start
    prev_frame_np: np.ndarray | None = None
    dissolve_duration = 0.40
    if prev_image_path is not None and prev_image_path.exists():
        prev_img = Image.open(prev_image_path).convert("RGB")
        if prev_img.size != (width, height):
            prev_img = prev_img.resize((width, height), Image.Resampling.LANCZOS)
        prev_frame_np = np.array(prev_img, dtype=np.float32)

    # Initialize Disney 2.5D particles and pulsing sunlight band
    particles = _init_disney_particles(scene.scene_number, width, height, count=26)
    sun_band_h, sun_band_rgb = _build_sunlight_band(width, height)

    # Pre-render subtitle strips once for this scene
    rendered_cues: List[Tuple[float, float, int, np.ndarray, np.ndarray]] = []
    if BURN_SUBTITLES:
        for cue in scene_audio.subtitles:
            y_top, sub_rgb, sub_alpha = _prerender_subtitle_strip(cue.text, target_size)
            rendered_cues.append((cue.start, cue.end, y_top, sub_rgb, sub_alpha))

    margin_x = max(1, up_w - width)
    margin_y = max(1, up_h - height)

    def make_frame(t: float) -> np.ndarray:
        progress = min(max(t / max(duration, 0.001), 0.0), 1.0)
        # Smoothstep camera easing + gentle sinusoidal "living camera" breathing
        eased = progress * progress * (3.0 - 2.0 * progress)
        breath_sin = math.sin(2.0 * math.pi * t / 3.2)
        breath_cos = math.cos(2.0 * math.pi * t / 4.4)

        if motion == "pan_right":
            x_norm = min(max(0.08 + 0.84 * eased + 0.03 * breath_cos, 0.0), 1.0)
            y_norm = min(max(0.50 + 0.14 * breath_sin, 0.0), 1.0)
            x0 = int(round(margin_x * x_norm))
            y0 = int(round(margin_y * y_norm))
            frame = upscaled_np[y0 : y0 + height, x0 : x0 + width].copy()
        elif motion == "pan_left":
            x_norm = min(max(0.92 - 0.84 * eased + 0.03 * breath_cos, 0.0), 1.0)
            y_norm = min(max(0.50 + 0.14 * breath_sin, 0.0), 1.0)
            x0 = int(round(margin_x * x_norm))
            y0 = int(round(margin_y * y_norm))
            frame = upscaled_np[y0 : y0 + height, x0 : x0 + width].copy()
        else:
            # zoom_in or zoom_out combined with gentle vertical/horizontal floating drift
            base_zoom = (
                1.0 + (scale_max - 1.0) * eased
                if motion == "zoom_in"
                else scale_max - (scale_max - 1.0) * eased
            )
            zoom_factor = min(max(base_zoom + 0.008 * breath_sin, 1.0), scale_max)
            crop_w = int(round(width / zoom_factor))
            crop_h = int(round(height / zoom_factor))
            rem_x = max(0, width - crop_w)
            rem_y = max(0, height - crop_h)
            x0 = int(round(rem_x * (0.5 + 0.12 * breath_cos)))
            y0 = int(round(rem_y * (0.5 + 0.12 * breath_sin)))
            cropped = base_img.crop((x0, y0, x0 + crop_w, y0 + crop_h))
            frame = np.array(cropped.resize((width, height), Image.Resampling.BILINEAR))

        # Layer 2: Pulsing golden Disney sunlight rays in upper canopy
        sun_pulse = 0.55 + 0.45 * math.sin(2.0 * math.pi * t / 3.8 + scene.scene_number)
        top_slice = frame[:sun_band_h, :, :].astype(np.float32)
        top_slice += sun_band_rgb * sun_pulse
        frame[:sun_band_h, :, :] = np.clip(top_slice, 0, 255).astype(np.uint8)

        # Layer 3: Animated floating Disney fireflies & fairy-dust bokeh particles
        for p in particles:
            twinkle = 0.40 + 0.60 * (0.5 + 0.5 * math.sin(p["twinkle_freq"] * t + p["phase"]))
            intensity = p["base_intensity"] * twinkle
            if intensity < 0.08:
                continue

            px = int(round(p["x0"] + p["sway_amp"] * math.sin(p["sway_freq"] * t + p["phase"]))) % width
            py = int(round((p["y0"] - p["vy"] * t) % height))
            r = p["radius"]

            x_min, x_max = max(0, px - r), min(width, px + r + 1)
            y_min, y_max = max(0, py - r), min(height, py + r + 1)
            if x_min >= x_max or y_min >= y_max:
                continue

            sx_min = x_min - (px - r)
            sx_max = sx_min + (x_max - x_min)
            sy_min = y_min - (py - r)
            sy_max = sy_min + (y_max - y_min)

            patch = frame[y_min:y_max, x_min:x_max, :].astype(np.float32)
            patch += p["stamp"][sy_min:sy_max, sx_min:sx_max, :] * intensity
            frame[y_min:y_max, x_min:x_max, :] = np.clip(patch, 0, 255).astype(np.uint8)

        # Layer 4: Smooth 0.40s visual cross-dissolve from previous scene (zero audio drift)
        if prev_frame_np is not None and t < dissolve_duration:
            alpha = min(max(t / dissolve_duration, 0.0), 1.0)
            blended_scene = prev_frame_np * (1.0 - alpha) + frame.astype(np.float32) * alpha
            frame = np.clip(blended_scene, 0, 255).astype(np.uint8)

        # Layer 5: Burn in active subtitle cue if enabled
        if rendered_cues:
            for start_t, end_t, y_top, sub_rgb, sub_alpha in rendered_cues:
                if start_t <= t <= end_t:
                    strip_h = sub_rgb.shape[0]
                    region = frame[y_top : y_top + strip_h, :, :].astype(np.float32)
                    blended = region * (1.0 - sub_alpha) + sub_rgb * sub_alpha
                    frame[y_top : y_top + strip_h, :, :] = blended.astype(np.uint8)
                    break

        return frame

    audio_clip = AudioFileClip(str(scene_audio.audio_path))
    video_clip = VideoClip(make_frame, duration=duration).set_audio(audio_clip)
    return video_clip


def _render_complete_video(
    story_pkg: StoryPackage,
    scene_images: List[SceneImages],
    scene_audios: List[SceneAudioResult],
    target_size: Tuple[int, int],
    output_filename: str,
    use_vertical: bool,
) -> Path:
    img_map: Dict[int, Path] = {
        si.scene_number: (si.tiktok_9x16_path if use_vertical else si.youtube_16x9_path)
        for si in scene_images
    }
    audio_map: Dict[int, SceneAudioResult] = {
        sa.scene_number: sa for sa in scene_audios
    }

    clips: List[VideoClip] = []
    prev_img_path: Path | None = None
    for scene in story_pkg.scenes:
        curr_img_path = img_map[scene.scene_number]
        clip = _create_scene_videoclip(
            image_path=curr_img_path,
            scene=scene,
            scene_audio=audio_map[scene.scene_number],
            target_size=target_size,
            prev_image_path=prev_img_path,
        )
        clips.append(clip)
        prev_img_path = curr_img_path

    final_clip = concatenate_videoclips(clips, method="compose")
    output_path = OUTPUT_DIR / output_filename

    final_clip.write_videofile(
        str(output_path),
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        preset="veryfast",
        threads=4,
        logger="bar",
    )

    # Cleanly close clips to release file handles on Windows
    final_clip.close()
    for clip in clips:
        if clip.audio is not None:
            clip.audio.close()
        clip.close()

    return output_path


def stitch_dual_videos(
    story_pkg: StoryPackage,
    scene_images: List[SceneImages],
    scene_audios: List[SceneAudioResult],
    lang: str = "en",
) -> Tuple[Path, Path]:
    """
    Renders both:
      1. 16:9 Horizontal video for YouTube Normal Video (`final_story[_fr]_youtube_16x9.mp4`)
      2. 9:16 Vertical video for YouTube Shorts & TikTok (`final_story[_fr]_tiktok_9x16.mp4`)
    """
    suffix = "" if lang == "en" else f"_{lang}"
    yt_filename = f"final_story{suffix}_youtube_16x9.mp4"
    tt_filename = f"final_story{suffix}_tiktok_9x16.mp4"

    print(
        f"[4/5] Stitching [{lang.upper()}] Disney 2.5D animated videos with MoviePy "
        "(floating camera + magical fireflies + sunlight rays + cross-dissolves + subtitles)..."
    )

    print(f"      -> Rendering [{lang.upper()}] YouTube 16:9 video ({YOUTUBE_SIZE[0]}x{YOUTUBE_SIZE[1]})...")
    youtube_video_path = _render_complete_video(
        story_pkg=story_pkg,
        scene_images=scene_images,
        scene_audios=scene_audios,
        target_size=YOUTUBE_SIZE,
        output_filename=yt_filename,
        use_vertical=False,
    )

    print(f"      -> Rendering [{lang.upper()}] Vertical 9:16 video ({TIKTOK_SIZE[0]}x{TIKTOK_SIZE[1]})...")
    tiktok_video_path = _render_complete_video(
        story_pkg=story_pkg,
        scene_images=scene_images,
        scene_audios=scene_audios,
        target_size=TIKTOK_SIZE,
        output_filename=tt_filename,
        use_vertical=True,
    )

    if lang == "en":
        legacy_path = OUTPUT_DIR / "final_story.mp4"
        legacy_path.write_bytes(youtube_video_path.read_bytes())

    print(f"      [{lang.upper()}] YouTube 16:9 video ready: {youtube_video_path}")
    print(f"      [{lang.upper()}] Vertical 9:16 video ready: {tiktok_video_path}")
    return youtube_video_path, tiktok_video_path
