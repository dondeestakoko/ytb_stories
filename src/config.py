import os
import random
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
IMAGES_16X9_DIR = OUTPUT_DIR / "images_16x9"
IMAGES_9X16_DIR = OUTPUT_DIR / "images_9x16"

# Ensure directories exist
for directory in (OUTPUT_DIR, AUDIO_DIR, IMAGES_16X9_DIR, IMAGES_9X16_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Gemini LLM settings (gemini-3.8-flash is the current recommended Flash model)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

# Edge-TTS settings (100% Free, no API key needed)
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-AriaNeural").strip()
TTS_RATE = os.getenv("TTS_RATE", "-5%").strip()

# Image generation settings (Pollinations Gen API: https://gen.pollinations.ai)
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations").strip().lower()
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "").strip()
POLLINATIONS_IMAGE_MODEL = os.getenv(
    "POLLINATIONS_IMAGE_MODEL", "black-forest-labs/flux.1-schnell"
).strip()
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY", "").strip()

# Video rendering settings
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "24"))
YOUTUBE_SIZE = (1920, 1080)  # Horizontal 16:9 for YouTube
TIKTOK_SIZE = (1080, 1920)   # Vertical 9:16 for TikTok
BURN_SUBTITLES = os.getenv("BURN_SUBTITLES", "true").strip().lower() == "true"

# YouTube API settings
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
YOUTUBE_PRIVACY_STATUS = os.getenv("YOUTUBE_PRIVACY_STATUS", "public").strip()
YOUTUBE_MADE_FOR_KIDS = os.getenv("YOUTUBE_MADE_FOR_KIDS", "false").strip().lower() == "true"
YOUTUBE_UPLOAD_SHORT = os.getenv("YOUTUBE_UPLOAD_SHORT", "true").strip().lower() == "true"

# TikTok Upload settings
TIKTOK_UPLOAD_MODE = os.getenv("TIKTOK_UPLOAD_MODE", "auto").strip().lower()
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
TIKTOK_REFRESH_TOKEN = os.getenv("TIKTOK_REFRESH_TOKEN", "").strip()
TIKTOK_PRIVACY_LEVEL = os.getenv("TIKTOK_PRIVACY_LEVEL", "PUBLIC_TO_EVERYONE").strip()
TIKTOK_COOKIES_JSON = os.getenv("TIKTOK_COOKIES_JSON", "").strip()

# Curated pools for automatic daily theme generation
PROTAGONISTS = [
    "a brave little red fox named Finn wearing a cosy blue scarf",
    "a curious baby owl named Ollie with oversized round spectacles",
    "a gentle golden retriever puppy named Sunny with a floppy ear",
    "a shy little hedgehog named Pip who loves collecting shiny pebbles",
    "a cheerful baby elephant named Barnaby with a bright yellow rain hat",
    "a clever little squirrel named Hazel carrying a tiny lantern",
    "a kind-hearted sea turtle named Shelly swimming in a coral lagoon",
    "a playful red panda named Mochi wearing a small green backpack",
    "a tiny field mouse named Milo with a patchwork vest",
    "a friendly little bear cub named Barnaby who loves honeybees",
    "a brave little penguin named Pippin sliding on rainbow ice",
    "a daydreaming bunny named Clover with long velvety ears",
]

SETTINGS = [
    "the Whispering Willow Forest during golden autumn",
    "Crystal Creek Meadow under a starry firefly sky",
    "the Cozy Cloudtop Village high above the misty mountains",
    "Sunbeam Valley where giant sunflowers touch the clouds",
    "the Enchanted Berry Woods after a gentle morning rain",
    "Starlight Cove where glowing seashells wash ashore",
    "Moonbeam Orchard filled with silver-leafed apple trees",
    "the mossy Lantern Bridge across Babbling Brook",
]

MORALS = [
    "true bravery means helping a friend even when you feel a little scared",
    "sharing what you have makes every adventure twice as joyful",
    "patience and kindness can solve problems that rushing never could",
    "listening carefully to others helps you discover hidden wonders",
    "being honest and admitting a mistake brings everyone closer together",
    "even the smallest creature can make a big difference in the world",
    "curiosity and asking questions turn ordinary days into magical journeys",
    "believing in your own unique gifts is better than trying to copy others",
]


def get_daily_story_seed_theme(custom_theme: str | None = None) -> str:
    """Returns a unique daily story prompt combining character, setting, and moral."""
    if custom_theme:
        return custom_theme

    today_ordinal = datetime.now(timezone.utc).toordinal()
    rng = random.Random(today_ordinal + random.randint(0, 1000))

    protagonist = rng.choice(PROTAGONISTS)
    setting = rng.choice(SETTINGS)
    moral = rng.choice(MORALS)

    return (
        f"Write a heartwarming 300-word children's story about {protagonist} "
        f"in {setting}, learning that {moral}."
    )
