import argparse
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path

from src.image_generator import generate_scene_images
from src.story_generator import StoryPackage, StoryScene, generate_story_package
from src.tiktok_uploader_client import upload_to_tiktok
from src.tts_generator import generate_narration_and_subtitles
from src.video_maker import stitch_dual_videos
from src.youtube_uploader import upload_to_youtube


def _get_sample_story_package() -> StoryPackage:
    """Built-in sample story about a brave fox for zero-key smoke testing (--mock-story)."""
    return StoryPackage(
        title="Finn the Brave Little Fox and the Whispering Bridge",
        moral="True bravery means helping a friend even when your paws are trembling.",
        character_visual_anchor=(
            "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
            "and a cosy sky-blue knitted scarf"
        ),
        scenes=[
            StoryScene(
                scene_number=1,
                narration=(
                    "Deep in the golden Whispering Woods lived a little red fox named Finn, "
                    "who wore a cosy blue scarf everywhere he went. Finn loved exploring mossy paths, "
                    "but he was always nervous around the high wooden bridge over Babbling Brook."
                ),
                visual_prompt=(
                    "Finn, a cute little red fox cub with a sky-blue knitted scarf walking along "
                    "a glowing autumn forest path towards an old wooden bridge, warm sunlight"
                ),
                camera_motion="zoom_in",
            ),
            StoryScene(
                scene_number=2,
                narration=(
                    "One breezy afternoon, a sudden gust of wind swept across the valley. "
                    "In the middle of the creaky wooden bridge, Finn spotted Pip, a tiny hedgehog, "
                    "clinging tightly to his basket of berries as the planks swayed."
                ),
                visual_prompt=(
                    "A tiny hedgehog holding a berry basket in the middle of a swaying wooden bridge "
                    "over a sparkling stream while autumn leaves swirl in the wind"
                ),
                camera_motion="pan_right",
            ),
            StoryScene(
                scene_number=3,
                narration=(
                    "Finn's heart thumped like a little drum, and his paws felt wobbly. "
                    "He looked at the rushing water below, then looked at his frightened friend. "
                    "Taking a deep breath, Finn whispered that bravery means helping even when you feel scared."
                ),
                visual_prompt=(
                    "Close-up of Finn the little red fox cub in his sky-blue scarf taking a brave breath "
                    "at the edge of the wooden bridge, determined warm expression"
                ),
                camera_motion="zoom_in",
            ),
            StoryScene(
                scene_number=4,
                narration=(
                    "Step by careful step, Finn trotted onto the wooden planks. "
                    "He kept his eyes fixed on Pip instead of the swirling water underneath. "
                    "When he reached the center, he gently steadied the berry basket and offered a warm paw."
                ),
                visual_prompt=(
                    "Finn the little red fox cub in a sky-blue scarf reaching out a paw to help "
                    "a tiny hedgehog on the wooden bridge, golden sunbeams breaking through clouds"
                ),
                camera_motion="pan_left",
            ),
            StoryScene(
                scene_number=5,
                narration=(
                    "Together, the fox and the hedgehog walked safely to the mossy riverbank. "
                    "Pip cheered with gratitude and shared his sweetest blackberries with Finn, "
                    "while fireflies began to twinkle beneath the ancient willow trees."
                ),
                visual_prompt=(
                    "Finn the little red fox cub in a sky-blue scarf and a tiny hedgehog happily "
                    "sharing blackberries on a mossy riverbank surrounded by glowing fireflies"
                ),
                camera_motion="zoom_out",
            ),
            StoryScene(
                scene_number=6,
                narration=(
                    "That evening, as Finn curled up under the starry sky, the bridge didn't seem "
                    "scary anymore. He had discovered a wonderful secret: courage isn't the absence "
                    "of fear, it is the kindness that makes you step forward anyway."
                ),
                visual_prompt=(
                    "Finn the little red fox cub in a sky-blue scarf curled peacefully under a starry "
                    "night sky with glowing fireflies in the forest, magical bedtime atmosphere"
                ),
                camera_motion="zoom_in",
            ),
        ],
        youtube_description=(
            "Join Finn the Brave Little Fox in this heartwarming bedtime moral story for kids! "
            "When his friend Pip gets stuck on the swaying bridge, Finn learns what true courage really means."
        ),
        youtube_tags=[
            "kids story",
            "bedtime story",
            "moral stories for kids",
            "brave fox story",
            "children stories",
            "animated storybook",
            "fables for kids",
        ],
        tiktok_caption=(
            "Finn the Brave Little Fox learns the secret of true courage! 🦊✨ "
            "#bedtimestories #kidsstory #moralstory #storytime #fables #wholesome"
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated Daily Children's Story Generator for YouTube (16:9) & TikTok (9:16)."
    )
    parser.add_argument(
        "--theme",
        type=str,
        default=None,
        help="Optional custom story theme. If omitted, picks a unique daily character & moral.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Generate story, narration, images, and both MP4 videos without uploading.",
    )
    parser.add_argument(
        "--mock-story",
        action="store_true",
        help="Use built-in 6-scene Brave Fox story (allows testing TTS, Flux images, and MoviePy without GEMINI_API_KEY).",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  DAILY CHILDREN'S STORY AUTOMATION PIPELINE (YOUTUBE 16:9 + TIKTOK 9:16)")
    print("=" * 72)

    # Step 1: Generate the 6-scene story & metadata
    if args.mock_story:
        print("[1/5] Using built-in 6-scene Brave Fox story (--mock-story)...")
        story_pkg = _get_sample_story_package()
    else:
        story_pkg = generate_story_package(custom_theme=args.theme)

    # Step 2: Generate voice narration + exact per-scene durations + SRT subtitles
    scene_audios, srt_path = generate_narration_and_subtitles(story_pkg)

    # Step 3: Generate 6x 16:9 (YouTube) and 6x 9:16 (TikTok) scene illustrations
    scene_images = generate_scene_images(story_pkg)

    # Step 4: Stitch both 16:9 and 9:16 videos with Ken Burns animation + burned-in subtitles
    youtube_mp4, tiktok_mp4 = stitch_dual_videos(
        story_pkg=story_pkg,
        scene_images=scene_images,
        scene_audios=scene_audios,
    )

    # Step 5: Upload simultaneously to YouTube and TikTok
    if args.skip_upload:
        print("[5/5] Skipping upload (--skip-upload enabled).")
    else:
        print("[5/5] Uploading simultaneously to YouTube (16:9) and TikTok (9:16)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            yt_future = executor.submit(upload_to_youtube, youtube_mp4, story_pkg)
            tt_future = executor.submit(upload_to_tiktok, tiktok_mp4, story_pkg)

            try:
                yt_result = yt_future.result()
            except Exception as exc:
                print(f"      [YouTube ERROR] {exc}")
                yt_result = None

            try:
                tt_result = tt_future.result()
            except Exception as exc:
                print(f"      [TikTok ERROR] {exc}")
                tt_result = None

        print(f"      Summary -> YouTube: {yt_result or 'Not uploaded'} | TikTok: {tt_result or 'Not uploaded'}")

    print("=" * 72)
    print("  PIPELINE FINISHED SUCCESSFULLY!")
    print(f"  - YouTube 16:9 Video : {youtube_mp4}")
    print(f"  - TikTok 9:16 Video  : {tiktok_mp4}")
    print(f"  - Subtitles (.srt)   : {srt_path}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
