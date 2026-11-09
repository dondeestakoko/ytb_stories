import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List
import edge_tts
from moviepy.editor import AudioFileClip

from src.config import AUDIO_DIR, OUTPUT_DIR, TTS_RATE, TTS_VOICE, TTS_VOICE_FR
from src.story_generator import StoryPackage


@dataclass
class SubtitleCue:
    start: float  # Seconds relative to the scene start
    end: float    # Seconds relative to the scene start
    text: str


@dataclass
class SceneAudioResult:
    scene_number: int
    audio_path: Path
    duration: float
    subtitles: List[SubtitleCue]


def _format_srt_timestamp(seconds: float) -> str:
    """Converts float seconds into SRT timestamp format HH:MM:SS,mmm."""
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _build_proportional_subtitles(text: str, duration: float, words_per_cue: int = 6) -> List[SubtitleCue]:
    """Splits narration into readable 5-7 word phrases timed proportionally to word character length."""
    words = text.strip().split()
    if not words:
        return []

    chunks: List[str] = []
    for i in range(0, len(words), words_per_cue):
        chunks.append(" ".join(words[i : i + words_per_cue]))

    total_chars = sum(max(len(c), 1) for c in chunks)
    cues: List[SubtitleCue] = []
    cursor = 0.0
    for chunk in chunks:
        weight = max(len(chunk), 1) / total_chars
        chunk_dur = duration * weight
        cues.append(
            SubtitleCue(
                start=cursor,
                end=min(duration, cursor + chunk_dur),
                text=chunk,
            )
        )
        cursor += chunk_dur
    return cues


async def _synthesize_scene_async(
    scene_number: int,
    text: str,
    voice: str,
    rate: str,
    lang: str = "en",
) -> SceneAudioResult:
    audio_path = AUDIO_DIR / f"scene_{scene_number}_{lang}.mp3"
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)

    word_events: List[tuple[float, float, str]] = []
    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset and duration are in 100-nanosecond ticks (1e-7 seconds)
                start_sec = chunk["offset"] / 10_000_000.0
                dur_sec = chunk["duration"] / 10_000_000.0
                word_events.append((start_sec, start_sec + dur_sec, chunk["text"]))

    # Measure exact MP3 duration via MoviePy
    with AudioFileClip(str(audio_path)) as clip:
        exact_duration = float(clip.duration)

    # Group word events into 6-word subtitle cues, or fall back to proportional timing
    cues: List[SubtitleCue] = []
    if word_events:
        group_size = 6
        for i in range(0, len(word_events), group_size):
            group = word_events[i : i + group_size]
            start_t = group[0][0]
            end_t = group[-1][1]
            # Extend end slightly to next group's start for smooth reading
            if i + group_size < len(word_events):
                end_t = max(end_t, word_events[i + group_size][0] - 0.05)
            else:
                end_t = max(end_t, exact_duration - 0.1)
            phrase = " ".join(w[2] for w in group)
            cues.append(SubtitleCue(start=start_t, end=min(end_t, exact_duration), text=phrase))
    else:
        cues = _build_proportional_subtitles(text, exact_duration, words_per_cue=6)

    return SceneAudioResult(
        scene_number=scene_number,
        audio_path=audio_path,
        duration=exact_duration,
        subtitles=cues,
    )


async def _generate_all_audio_async(
    story_pkg: StoryPackage,
    lang: str = "en",
) -> List[SceneAudioResult]:
    voice = TTS_VOICE_FR if lang == "fr" else TTS_VOICE
    results: List[SceneAudioResult] = []
    for scene in story_pkg.scenes:
        narration_text = (
            getattr(scene, "narration_fr", "") or scene.narration
            if lang == "fr"
            else scene.narration
        )
        res = await _synthesize_scene_async(
            scene_number=scene.scene_number,
            text=narration_text,
            voice=voice,
            rate=TTS_RATE,
            lang=lang,
        )
        print(
            f"      [{lang.upper()}] Scene {scene.scene_number} audio: {res.duration:.2f}s "
            f"({len(res.subtitles)} subtitle cues) -> {res.audio_path.name}"
        )
        results.append(res)
    return results


def generate_narration_and_subtitles(
    story_pkg: StoryPackage,
    lang: str = "en",
) -> tuple[List[SceneAudioResult], Path]:
    """Generates MP3 audio for all 6 scenes using free edge-tts (EN or FR) and writes an .srt file."""
    voice = TTS_VOICE_FR if lang == "fr" else TTS_VOICE
    print(
        f"[2/5] Synthesizing [{lang.upper()}] voice narration with edge-tts "
        f"(voice={voice}, rate={TTS_RATE})..."
    )
    scene_audios = asyncio.run(_generate_all_audio_async(story_pkg, lang=lang))

    srt_filename = "subtitles.srt" if lang == "en" else f"subtitles_{lang}.srt"
    srt_path = OUTPUT_DIR / srt_filename
    srt_lines: List[str] = []
    cue_index = 1
    global_offset = 0.0

    for scene_audio in scene_audios:
        for cue in scene_audio.subtitles:
            abs_start = global_offset + cue.start
            abs_end = global_offset + cue.end
            srt_lines.append(str(cue_index))
            srt_lines.append(f"{_format_srt_timestamp(abs_start)} --> {_format_srt_timestamp(abs_end)}")
            srt_lines.append(cue.text)
            srt_lines.append("")
            cue_index += 1
        global_offset += scene_audio.duration

    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    total_duration = sum(s.duration for s in scene_audios)
    print(f"      [{lang.upper()}] Total narration duration: {total_duration:.2f}s | SRT saved to {srt_path}")
    return scene_audios, srt_path
