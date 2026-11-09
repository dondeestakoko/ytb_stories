from datetime import datetime, timezone
import json
import time
from typing import List, Literal
import requests
from pydantic import BaseModel, Field

from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OUTPUT_DIR,
    POLLINATIONS_API_KEY,
    STORY_HISTORY_FILE,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
)


class StoryScene(BaseModel):
    scene_number: int = Field(
        description="Scene index from 1 to 6 in chronological order."
    )
    narration: str = Field(
        description=(
            "English narration spoken during this scene (38 to 48 words). "
            "MUST use very simple, clear Age 4-7 vocabulary and short 6-10 word sentences "
            "so young children and beginners can understand every single word easily."
        )
    )
    narration_fr: str = Field(
        description=(
            "French narration spoken during this scene (38 to 48 words). "
            "MUST use very simple, natural, warm French for ages 4-7 with short 6-10 word "
            "sentences and everyday words (phrases très simples et claires pour les enfants)."
        )
    )
    visual_prompt: str = Field(
        description=(
            "Detailed English image generation prompt for this scene's action and pose. "
            "MUST repeat the protagonist's exact Character DNA (species, exact colors, "
            "eyes, and exact clothing/accessory) word-for-word so all 6 scenes look identical."
        )
    )
    camera_motion: Literal["zoom_in", "zoom_out", "pan_left", "pan_right"] = Field(
        description="Suggested Ken Burns camera movement for this scene."
    )


class StoryPackage(BaseModel):
    title: str = Field(
        description="Catchy, simple English YouTube video title (under 65 characters)."
    )
    title_fr: str = Field(
        description="Catchy, simple French YouTube video title (under 65 characters)."
    )
    moral: str = Field(
        description="The core moral lesson of the story in one simple English sentence."
    )
    moral_fr: str = Field(
        description="The core moral lesson of the story in one simple French sentence."
    )
    character_visual_anchor: str = Field(
        description=(
            "STRICT CHARACTER DNA SHEET used across all 6 scenes: exact character name, "
            "exact species/appearance, exact fur/feather/skin color, eye color, and 1-2 "
            "signature clothing items with fixed colors (e.g., 'Lumi, a tiny chubby white "
            "arctic bunny with soft snowy fur, big round sapphire-blue eyes, rosy cheeks, "
            "wearing a bright cherry-red knitted sweater with a gold star button')."
        )
    )
    world_visual_anchor: str = Field(
        description=(
            "STRICT ENVIRONMENT & LIGHTING DNA used across all 6 scenes so the background "
            "color palette and mood stay consistent (e.g., 'a sunlit pastel meadow with "
            "glowing lavender flowers, soft golden-hour sunlight, and mint-green hills')."
        )
    )
    scenes: List[StoryScene] = Field(
        description="Exactly 6 chronological scenes forming a complete, simple ~250-word story."
    )
    youtube_description: str = Field(
        description="Engaging English YouTube video description with story summary and moral."
    )
    youtube_description_fr: str = Field(
        description="Engaging French YouTube video description with story summary and moral."
    )
    youtube_tags: List[str] = Field(
        description="10 to 15 relevant English SEO tags for YouTube (e.g., bedtime story, moral stories, animated fable, storytime)."
    )
    youtube_tags_fr: List[str] = Field(
        description="10 to 15 relevant French SEO tags for YouTube (e.g., histoire pour dormir, conte moral, fable animée, histoire du soir)."
    )
    tiktok_caption: str = Field(
        description="Short English TikTok caption with 5-8 hashtags (under 280 chars)."
    )
    tiktok_caption_fr: str = Field(
        description="Short French TikTok caption with 5-8 hashtags (under 280 chars)."
    )

    @property
    def full_story_text(self) -> str:
        return "\n\n".join(scene.narration.strip() for scene in self.scenes)

    @property
    def full_story_text_fr(self) -> str:
        return "\n\n".join(scene.narration_fr.strip() for scene in self.scenes)


SYSTEM_INSTRUCTION = """You are a world-class children's storybook author (in both English and French) and 3D animation art director.
Your job is to create a 100% ORIGINAL, heartwarming children's fable divided into EXACTLY 6 scenes, written in BOTH English and French.

CRITICAL RULES YOU MUST FOLLOW:
1. VERY SIMPLE LANGUAGE (AGE 4-7 LEVEL):
   - Use short, clear sentences (6 to 10 words per sentence).
   - Use simple, everyday words that a 5-year-old child or language learner immediately understands.
   - Avoid complex metaphors, rare adjectives, or long clauses.
   - Each scene's `narration` (English) and `narration_fr` (French) must be 38 to 48 words (~240-280 words total across 6 scenes).
2. STRICT VISUAL CONSISTENCY ACROSS ALL 6 SCENES:
   - Define a detailed `character_visual_anchor` (exact species, body shape, fur/skin color, eye color, and 1-2 distinctive clothing items with exact colors).
   - Define a `world_visual_anchor` (consistent environment, lighting, and color palette).
   - Every single scene's `visual_prompt` MUST copy the protagonist's exact physical description from `character_visual_anchor` so the image generator draws the exact same character in scenes 1 through 6.
   - Never include text, letters, speech bubbles, or watermarks in `visual_prompt`.
3. NEVER REPEAT PAST STORIES:
   - Invent a completely fresh protagonist, animal/magical creature, name, setting, problem, and moral lesson that does NOT overlap with any story in the provided history blocklist.
4. Vary `camera_motion` across scenes (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`).
"""


def load_story_history() -> List[dict]:
    """Loads previously generated stories from `data/story_history.json`."""
    if not STORY_HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(STORY_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"      [History] Could not read {STORY_HISTORY_FILE}: {exc}")
    return []


def fetch_recent_youtube_titles() -> List[str]:
    """
    Fetches the last 25 uploaded video titles directly from the user's YouTube channel
    (costs only 2 quota units) so we never repeat a story even across fresh environments.
    """
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        return []
    try:
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "refresh_token": YOUTUBE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if token_resp.status_code != 200:
            return []
        access_token = token_resp.json().get("access_token")
        headers = {"Authorization": f"Bearer {access_token}"}

        ch_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "contentDetails", "mine": "true"},
            headers=headers,
            timeout=15,
        )
        if ch_resp.status_code != 200:
            return []
        items = ch_resp.json().get("items", [])
        if not items:
            return []
        uploads_playlist = (
            items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        )
        if not uploads_playlist:
            return []

        pl_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "snippet",
                "playlistId": uploads_playlist,
                "maxResults": 25,
            },
            headers=headers,
            timeout=15,
        )
        if pl_resp.status_code != 200:
            return []
        titles = [
            it.get("snippet", {}).get("title", "").strip()
            for it in pl_resp.json().get("items", [])
            if it.get("snippet", {}).get("title")
        ]
        return titles
    except Exception:
        return []


def save_story_to_history(story_pkg: StoryPackage) -> None:
    """Appends the newly generated story to `data/story_history.json`."""
    history = load_story_history()
    history.append(
        {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "title": story_pkg.title,
            "title_fr": story_pkg.title_fr,
            "character": story_pkg.character_visual_anchor,
            "moral": story_pkg.moral,
        }
    )
    # Keep the most recent 200 stories
    history = history[-200:]
    STORY_HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_infinite_theme_prompt(custom_theme: str | None = None) -> str:
    """Builds a prompt that enforces infinite variety and blocks all previous stories."""
    history = load_story_history()
    channel_titles = fetch_recent_youtube_titles()

    blocked_lines: List[str] = []
    for entry in history[-40:]:
        blocked_lines.append(
            f"- Title: '{entry.get('title')}' / '{entry.get('title_fr', '')}' | "
            f"Character: {entry.get('character')} | Moral: {entry.get('moral')}"
        )
    for yt_title in channel_titles:
        if not any(yt_title in line for line in blocked_lines):
            blocked_lines.append(f"- Previously uploaded YouTube video: '{yt_title}'")

    blocklist_section = (
        "\n".join(blocked_lines)
        if blocked_lines
        else "- Finn the Little Red Fox and the Whispering Bridge"
    )

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
    if custom_theme:
        base_request = f"Create a heartwarming, very simple children's story about: {custom_theme}."
    else:
        base_request = (
            f"Today is {today_str}. Invent a brand-new, creative animal or magical creature "
            "protagonist (with a unique name and signature outfit), a magical setting, and "
            "an inspiring moral lesson for young children."
        )

    return (
        f"{base_request}\n\n"
        "PAST STORIES BLOCKLIST (DO NOT repeat any of these characters, animal species, titles, or plots):\n"
        f"{blocklist_section}\n\n"
        "Provide the complete 6-scene bilingual (English + French) story package with "
        "very simple Age 4-7 sentences, strict Character DNA & World DNA visual descriptions, "
        "and YouTube + TikTok metadata in both English and French."
    )


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

    for step in reversed(data.get("steps", [])):
        if step.get("type") == "model_output":
            texts = [
                part.get("text", "")
                for part in step.get("content", [])
                if part.get("type") == "text" and part.get("text")
            ]
            if texts:
                return "".join(texts)

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
                timeout=60,
            )
            if resp.status_code == 200:
                return _extract_text_from_interactions_response(resp.json())
            last_error = f"Interactions HTTP {resp.status_code} ({model_name}): {resp.text[:300]}"
            print(f"      [Info] {last_error}")
        except requests.RequestException as exc:
            last_error = f"Interactions network error ({model_name}): {exc}"
            print(f"      [Info] {last_error}")

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
                timeout=60,
            )
            if resp2.status_code == 200:
                return resp2.json()["candidates"][0]["content"]["parts"][0]["text"]
            last_error = f"generateContent HTTP {resp2.status_code} ({model_name}): {resp2.text[:300]}"
            print(f"      [Info] {last_error}")
        except requests.RequestException as exc:
            last_error = f"generateContent network error ({model_name}): {exc}"
            print(f"      [Info] {last_error}")

        time.sleep(2)

    if POLLINATIONS_API_KEY:
        schema_prompt = (
            f"{user_input}\n\nReturn ONLY valid JSON matching this schema:\n"
            + json.dumps(StoryPackage.model_json_schema())
        )
        try:
            polli_resp = requests.post(
                "https://gen.pollinations.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {POLLINATIONS_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-3.8-flash,google/gemini-3.5-flash-lite,openai/gpt-5.4-nano",
                    "messages": [
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": schema_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if polli_resp.status_code == 200:
                return polli_resp.json()["choices"][0]["message"]["content"]
            last_error = f"Pollinations Chat HTTP {polli_resp.status_code}: {polli_resp.text[:300]}"
        except requests.RequestException as exc:
            last_error = f"Pollinations Chat network error: {exc}"

    raise RuntimeError(f"Gemini API call failed across all models: {last_error}")


def generate_story_package(custom_theme: str | None = None) -> StoryPackage:
    """Calls Gemini to generate a unique bilingual (EN + FR) 6-scene story package."""
    if not (GEMINI_API_KEY or POLLINATIONS_API_KEY):
        raise ValueError(
            "Missing GEMINI_API_KEY (and POLLINATIONS_API_KEY). Get a free API key at "
            "https://aistudio.google.com/apikey and set it in your .env file or GitHub Actions Secrets."
        )

    user_input = _build_infinite_theme_prompt(custom_theme)
    print(f"[1/5] Generating unique bilingual (EN + FR) story with {GEMINI_MODEL}...")

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

    # Save to persistent story history so this character/plot is never repeated
    save_story_to_history(story_pkg)

    metadata_path = OUTPUT_DIR / "metadata.json"
    metadata_path.write_text(
        json.dumps(story_pkg.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"      Story EN: '{story_pkg.title}' ({len(story_pkg.full_story_text.split())} words)\n"
        f"      Story FR: '{story_pkg.title_fr}' ({len(story_pkg.full_story_text_fr.split())} words)"
    )
    print(f"      Character DNA: {story_pkg.character_visual_anchor}")
    print(f"      Saved metadata to {metadata_path} and updated {STORY_HISTORY_FILE.name}")
    return story_pkg
