import json
import time
from typing import List, Literal
import requests
from pydantic import BaseModel, Field

from src.config import GEMINI_API_KEY, GEMINI_MODEL, OUTPUT_DIR, get_daily_story_seed_theme


class StoryScene(BaseModel):
    scene_number: int = Field(
        description="Scene index from 1 to 6 in chronological order."
    )
    narration: str = Field(
        description=(
            "The narration spoken during this scene (45 to 55 words). "
            "Warm, engaging children's storytelling tone."
        )
    )
    visual_prompt: str = Field(
        description=(
            "Detailed image generation prompt for this scene. MUST repeat the main "
            "character's exact visual appearance (species, colors, clothing/accessories) "
            "so all 6 images look consistent. Style: whimsical 3D Pixar-style children's "
            "storybook illustration, warm magical lighting, vibrant colors, no text or words."
        )
    )
    camera_motion: Literal["zoom_in", "zoom_out", "pan_left", "pan_right"] = Field(
        description="Suggested Ken Burns camera movement for this scene."
    )


class StoryPackage(BaseModel):
    title: str = Field(
        description="Catchy, family-friendly YouTube video title (under 70 characters)."
    )
    moral: str = Field(
        description="The core moral lesson of the story in one short sentence."
    )
    character_visual_anchor: str = Field(
        description="Consistent visual description of the main character used across all 6 scenes."
    )
    scenes: List[StoryScene] = Field(
        description="Exactly 6 chronological scenes whose narrations form a complete ~300-word story."
    )
    youtube_description: str = Field(
        description="Engaging YouTube video description including a story summary, moral, and hashtags."
    )
    youtube_tags: List[str] = Field(
        description="10 to 15 relevant SEO tags for YouTube (e.g., kids story, bedtime story, moral stories)."
    )
    tiktok_caption: str = Field(
        description="Short, punchy TikTok caption with 5-8 trending storytelling hashtags (under 300 chars)."
    )

    @property
    def full_story_text(self) -> str:
        return "\n\n".join(scene.narration.strip() for scene in self.scenes)


SYSTEM_INSTRUCTION = """You are an award-winning children's storybook author and visual director.
Your job is to create a complete, heartwarming ~300-word children's story divided into EXACTLY 6 scenes.

Rules you MUST follow:
1. Across the 6 scenes, the combined narration must be roughly 280 to 330 words (~45-55 words per scene).
2. The story must have a clear beginning (scenes 1-2), gentle challenge/adventure (scenes 3-4), heartwarming resolution (scene 5), and clear moral takeaway (scene 6).
3. Every single scene's `visual_prompt` MUST explicitly include the full visual description of the protagonist (e.g., 'a small red fox with a cosy blue knitted scarf and bright amber eyes') because the image generator does not have memory of previous scenes.
4. Never include text, speech bubbles, letters, or watermarks in `visual_prompt`. Always specify: '3D whimsical children's book illustration, warm cinematic lighting, ultra-detailed, no text'.
5. Vary `camera_motion` across scenes (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`) to keep the video visually dynamic.
"""


def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_text_from_interactions_response(data: dict) -> str:
    """Extracts the final model_output text from an Interactions API JSON payload."""
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]

    # Walk steps in reverse to find trailing model_output text
    for step in reversed(data.get("steps", [])):
        if step.get("type") == "model_output":
            texts = [
                part.get("text", "")
                for part in step.get("content", [])
                if part.get("type") == "text" and part.get("text")
            ]
            if texts:
                return "".join(texts)

    # Legacy outputs fallback
    for out in reversed(data.get("outputs", [])):
        if out.get("text"):
            return out["text"]

    raise ValueError(f"Could not extract output_text from Interactions API response: {data}")


def _call_gemini_interactions_rest(user_input: str) -> str:
    """
    Calls the Gemini Interactions API (`v1beta/interactions`) with structured output,
    automatically retrying on transient 503 demand spikes across current Gemini 3.x Flash models.
    """
    models_to_try = list(
        dict.fromkeys(
            [
                GEMINI_MODEL,
                "gemini-3.8-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ]
        )
    )

    last_error = None
    for model_name in models_to_try:
        # 1. Try modern Interactions API first
        interactions_url = "https://generativelanguage.googleapis.com/v1beta/interactions"
        interactions_payload = {
            "model": model_name,
            "system_instruction": SYSTEM_INSTRUCTION,
            "input": user_input,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": StoryPackage.model_json_schema(),
            },
        }
        try:
            resp = requests.post(
                interactions_url,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                    "Api-Revision": "2026-05-20",
                },
                json=interactions_payload,
                timeout=45,
            )
            if resp.status_code == 200:
                return _extract_text_from_interactions_response(resp.json())
            last_error = f"Interactions HTTP {resp.status_code} ({model_name}): {resp.text[:300]}"
            print(f"      [Info] {last_error}")
        except requests.RequestException as exc:
            last_error = f"Interactions network error ({model_name}): {exc}"
            print(f"      [Info] {last_error}")

        # 2. Fallback to generateContent for the same model if needed
        gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        schema_prompt = (
            f"{user_input}\n\nReturn ONLY valid JSON matching this schema:\n"
            + json.dumps(StoryPackage.model_json_schema())
        )
        gen_payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": schema_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            resp2 = requests.post(
                gen_url,
                params={"key": GEMINI_API_KEY},
                headers={"Content-Type": "application/json"},
                json=gen_payload,
                timeout=45,
            )
            if resp2.status_code == 200:
                return resp2.json()["candidates"][0]["content"]["parts"][0]["text"]
            last_error = f"generateContent HTTP {resp2.status_code} ({model_name}): {resp2.text[:300]}"
            print(f"      [Info] {last_error}")
        except requests.RequestException as exc:
            last_error = f"generateContent network error ({model_name}): {exc}"
            print(f"      [Info] {last_error}")

        time.sleep(2)

    raise RuntimeError(f"Gemini API call failed across all models: {last_error}")


def generate_story_package(custom_theme: str | None = None) -> StoryPackage:
    """Calls Gemini using google-genai Interactions API (with automatic model fallback on 503)."""
    if not GEMINI_API_KEY:
        raise ValueError(
            "Missing GEMINI_API_KEY. Get a free API key at https://aistudio.google.com/apikey "
            "and set it in your .env file or GitHub Actions Secrets."
        )

    theme_prompt = get_daily_story_seed_theme(custom_theme)
    print(f"[1/5] Generating daily story with {GEMINI_MODEL}...")
    print(f"      Theme: {theme_prompt}")

    user_input = (
        f"{theme_prompt}\n\n"
        "Provide the complete 6-scene story package with narration, 6 self-contained "
        "visual descriptions, and YouTube + TikTok metadata."
    )

    raw_json_output: str | None = None
    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=GEMINI_API_KEY)
        for model_name in dict.fromkeys(
            [GEMINI_MODEL, "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        ):
            try:
                interaction = client.interactions.create(
                    model=model_name,
                    system_instruction=SYSTEM_INSTRUCTION,
                    input=user_input,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": StoryPackage.model_json_schema(),
                    },
                )
                raw_json_output = interaction.output_text
                if raw_json_output:
                    break
            except Exception as sdk_err:
                print(f"      [SDK Retry] {model_name}: {sdk_err}")
                continue
    except ImportError:
        raw_json_output = None

    if not raw_json_output:
        raw_json_output = _call_gemini_interactions_rest(user_input)

    story_pkg = StoryPackage.model_validate_json(_extract_json_text(raw_json_output))

    if len(story_pkg.scenes) != 6:
        raise ValueError(f"Expected 6 scenes from Gemini, got {len(story_pkg.scenes)}.")

    metadata_path = OUTPUT_DIR / "metadata.json"
    metadata_path.write_text(
        json.dumps(story_pkg.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"      Story generated: '{story_pkg.title}' ({len(story_pkg.full_story_text.split())} words)")
    print(f"      Saved metadata to {metadata_path}")
    return story_pkg
