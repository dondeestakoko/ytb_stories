from pathlib import Path
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
from src.tts_generator import SceneAudioResult, SubtitleCue


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


def _create_scene_videoclip(
    image_path: Path,
    scene: StoryScene,
    scene_audio: SceneAudioResult,
    target_size: Tuple[int, int],
) -> VideoClip:
    """Builds a Ken Burns animated VideoClip with burned-in subtitles for a single scene."""
    width, height = target_size
    duration = scene_audio.duration
    motion = scene.camera_motion

    base_img = Image.open(image_path).convert("RGB")
    if base_img.size != (width, height):
        base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)

    # Pre-upscale by 14% for smooth pan/zoom without resolution loss
    scale_max = 1.14
    up_w, up_h = int(round(width * scale_max)), int(round(height * scale_max))
    upscaled_img = base_img.resize((up_w, up_h), Image.Resampling.LANCZOS)
    upscaled_np = np.array(upscaled_img)

    # Pre-render subtitle strips once for this scene
    rendered_cues: List[Tuple[float, float, int, np.ndarray, np.ndarray]] = []
    if BURN_SUBTITLES:
        for cue in scene_audio.subtitles:
            y_top, sub_rgb, sub_alpha = _prerender_subtitle_strip(cue.text, target_size)
            rendered_cues.append((cue.start, cue.end, y_top, sub_rgb, sub_alpha))

    def make_frame(t: float) -> np.ndarray:
        progress = min(max(t / max(duration, 0.001), 0.0), 1.0)
        # Smoothstep easing so camera acceleration/deceleration feels gentle
        eased = progress * progress * (3.0 - 2.0 * progress)

        if motion == "pan_right":
            x0 = int(round((up_w - width) * eased))
            y0 = (up_h - height) // 2
            frame = upscaled_np[y0 : y0 + height, x0 : x0 + width].copy()
        elif motion == "pan_left":
            x0 = int(round((up_w - width) * (1.0 - eased)))
            y0 = (up_h - height) // 2
            frame = upscaled_np[y0 : y0 + height, x0 : x0 + width].copy()
        else:
            # zoom_in or zoom_out
            zoom_factor = (
                1.0 + (scale_max - 1.0) * eased
                if motion == "zoom_in"
                else scale_max - (scale_max - 1.0) * eased
            )
            crop_w = int(round(width / zoom_factor))
            crop_h = int(round(height / zoom_factor))
            x0 = (width - crop_w) // 2
            y0 = (height - crop_h) // 2
            cropped = base_img.crop((x0, y0, x0 + crop_w, y0 + crop_h))
            frame = np.array(cropped.resize((width, height), Image.Resampling.BILINEAR))

        # Burn in active subtitle cue if enabled
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
    for scene in story_pkg.scenes:
        clip = _create_scene_videoclip(
            image_path=img_map[scene.scene_number],
            scene=scene,
            scene_audio=audio_map[scene.scene_number],
            target_size=target_size,
        )
        clips.append(clip)

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
        f"[4/5] Stitching [{lang.upper()}] dual videos with MoviePy "
        "(Ken Burns effect + burned-in subtitles)..."
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
