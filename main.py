import argparse
import sys
from pathlib import Path

from src.config import STORY_LANGUAGES
from src.image_generator import generate_scene_images
from src.story_generator import StoryPackage, StoryScene, generate_story_package
from src.tiktok_uploader_client import upload_to_tiktok
from src.tts_generator import generate_narration_and_subtitles
from src.video_maker import stitch_dual_videos
from src.youtube_uploader import refresh_youtube_access_token, upload_both_to_youtube


def _get_sample_story_package() -> StoryPackage:
    """Built-in bilingual sample story for zero-key smoke testing (--mock-story)."""
    return StoryPackage(
        title="Finn the Brave Little Fox and the Whispering Bridge",
        title_fr="Finn le Petit Renard Courageux et le Pont des Murmures",
        moral="Being brave means helping a friend even when you feel scared.",
        moral_fr="Être courageux, c'est aider un ami même quand on a un peu peur.",
        character_visual_anchor=(
            "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
            "and a cosy sky-blue knitted scarf"
        ),
        world_visual_anchor=(
            "the golden Whispering Woods in autumn with warm sunbeams, soft green moss, "
            "and a gentle sparkling stream"
        ),
        scenes=[
            StoryScene(
                scene_number=1,
                narration=(
                    "Little Finn was a red fox with a soft blue scarf. "
                    "He loved playing in the sunny woods. "
                    "But Finn was afraid of the tall wooden bridge over the stream."
                ),
                narration_fr=(
                    "Le petit Finn était un renard roux avec une écharpe bleue. "
                    "Il aimait jouer dans la forêt ensoleillée. "
                    "Mais Finn avait peur du grand pont de bois sur la rivière."
                ),
                visual_prompt=(
                    "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
                    "and a cosy sky-blue knitted scarf walking along a sunny autumn forest path towards "
                    "an old wooden bridge"
                ),
                camera_motion="zoom_in",
            ),
            StoryScene(
                scene_number=2,
                narration=(
                    "One windy day, a big gust blew through the trees. "
                    "Finn saw his tiny friend Pip the hedgehog on the bridge. "
                    "Pip was holding his basket of berries and shaking with fear."
                ),
                narration_fr=(
                    "Un jour de grand vent, les arbres ont commencé à bouger. "
                    "Finn a vu son petit ami Pip le hérisson sur le pont. "
                    "Pip tenait son panier de baies et tremblait de peur."
                ),
                visual_prompt=(
                    "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
                    "and a cosy sky-blue knitted scarf watching a tiny hedgehog holding a berry basket "
                    "in the middle of a wooden bridge while autumn leaves swirl"
                ),
                camera_motion="pan_right",
            ),
            StoryScene(
                scene_number=3,
                narration=(
                    "Finn's heart went thump, thump, thump. "
                    "His little paws felt wobbly as he looked at the water. "
                    "Then he took a big breath and decided to help his friend."
                ),
                narration_fr=(
                    "Le cœur de Finn battait très fort, boum, boum, boum. "
                    "Ses petites pattes tremblaient devant l'eau qui coulait. "
                    "Alors il a pris une grande inspiration pour aller aider son ami."
                ),
                visual_prompt=(
                    "Close-up of Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
                    "and a cosy sky-blue knitted scarf taking a brave deep breath at the edge of the wooden bridge"
                ),
                camera_motion="zoom_in",
            ),
            StoryScene(
                scene_number=4,
                narration=(
                    "Step by step, Finn walked onto the wooden bridge. "
                    "He did not look down at the rushing water. "
                    "He smiled at Pip and held out a warm paw."
                ),
                narration_fr=(
                    "Pas à pas, Finn a marché doucement sur le pont de bois. "
                    "Il ne regardait pas l'eau en bas. "
                    "Il a souri à Pip et lui a tendu une patte chaleureuse."
                ),
                visual_prompt=(
                    "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
                    "and a cosy sky-blue knitted scarf reaching out a gentle paw to help a tiny hedgehog "
                    "on the wooden bridge in golden sunlight"
                ),
                camera_motion="pan_left",
            ),
            StoryScene(
                scene_number=5,
                narration=(
                    "Together, Finn and Pip walked safely back to the soft grass. "
                    "Pip was so happy that he shared his sweet blackberries with Finn. "
                    "Little fireflies began to glow all around them."
                ),
                narration_fr=(
                    "Ensemble, Finn et Pip sont revenus en sécurité sur l'herbe douce. "
                    "Pip était si heureux qu'il a partagé ses mûres sucrées avec Finn. "
                    "De petites lucioles ont commencé à briller tout autour d'eux."
                ),
                visual_prompt=(
                    "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
                    "and a cosy sky-blue knitted scarf happily sharing blackberries with a tiny hedgehog "
                    "on a mossy riverbank surrounded by glowing fireflies"
                ),
                camera_motion="zoom_out",
            ),
            StoryScene(
                scene_number=6,
                narration=(
                    "That night, Finn curled up under the bright stars. "
                    "The bridge did not feel scary anymore. "
                    "Finn learned that being kind makes your heart super brave."
                ),
                narration_fr=(
                    "Cette nuit-là, Finn s'est blotti sous les belles étoiles brillantes. "
                    "Le pont ne lui faisait plus peur du tout. "
                    "Finn avait compris que la gentillesse rend le cœur très courageux."
                ),
                visual_prompt=(
                    "Finn, a cute little red fox cub with bright amber eyes, fluffy white-tipped tail, "
                    "and a cosy sky-blue knitted scarf curled peacefully under a starry night sky "
                    "with glowing fireflies in the forest"
                ),
                camera_motion="zoom_in",
            ),
        ],
        youtube_description=(
            "Join Finn the Brave Little Fox in this heartwarming bedtime moral story! "
            "When his friend Pip gets stuck on the bridge, Finn learns what true courage really means."
        ),
        youtube_description_fr=(
            "Rejoignez Finn le Petit Renard Courageux dans cette douce histoire morale du soir ! "
            "Quand son ami Pip est bloqué sur le pont, Finn découvre le secret du vrai courage."
        ),
        youtube_tags=[
            "bedtime story",
            "moral stories",
            "brave fox story",
            "animated storybook",
            "fables",
            "storytime",
        ],
        youtube_tags_fr=[
            "histoire pour dormir",
            "conte moral",
            "histoire du soir",
            "fable animée",
            "petit renard",
            "conte",
        ],
        tiktok_caption=(
            "Finn the Brave Little Fox learns the secret of true courage! 🦊✨ "
            "#bedtimestories #moralstory #storytime #fables #wholesome"
        ),
        tiktok_caption_fr=(
            "Finn le Petit Renard découvre le secret du vrai courage ! 🦊✨ "
            "#histoirepourdormir #conte #morale #histoiredusoir #fable"
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated Daily Bilingual (EN + FR) Story Generator for YouTube (16:9 + Shorts 9:16) & TikTok."
    )
    parser.add_argument(
        "--theme",
        type=str,
        default=None,
        help="Optional custom story theme. If omitted, invents a 100%% unique character, world & moral.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Generate story, narration, images, and MP4 videos without uploading.",
    )
    parser.add_argument(
        "--mock-story",
        action="store_true",
        help="Use built-in 6-scene Brave Fox bilingual story without calling Gemini.",
    )
    args = parser.parse_args()

    print("=" * 76)
    print("  DAILY BILINGUAL STORY PIPELINE (ENGLISH + FRENCH | 16:9 NORMAL + 9:16 SHORT)")
    print("=" * 76)

    # Step 1: Generate the unique 6-scene bilingual story & metadata
    if args.mock_story:
        print("[1/5] Using built-in 6-scene bilingual Brave Fox story (--mock-story)...")
        story_pkg = _get_sample_story_package()
    else:
        story_pkg = generate_story_package(custom_theme=args.theme)

    # Step 2: Generate 6x 16:9 and 6x 9:16 scene illustrations ONCE (with locked seed + Character DNA)
    scene_images = generate_scene_images(story_pkg)

    # Step 3 & 4: For each configured language (en, fr), synthesize TTS narration + stitch 16:9 & 9:16 videos
    rendered_videos: dict[str, tuple[Path, Path, Path]] = {}
    for lang in STORY_LANGUAGES:
        scene_audios, srt_path = generate_narration_and_subtitles(story_pkg, lang=lang)
        yt_mp4, tt_mp4 = stitch_dual_videos(
            story_pkg=story_pkg,
            scene_images=scene_images,
            scene_audios=scene_audios,
            lang=lang,
        )
        rendered_videos[lang] = (yt_mp4, tt_mp4, srt_path)

    # Step 5: Upload Normal (16:9) + Short (9:16) for each language to YouTube, plus TikTok
    if args.skip_upload:
        print("[5/5] Skipping upload (--skip-upload enabled).")
    else:
        print(f"[5/5] Uploading videos for languages {STORY_LANGUAGES} to YouTube (Normal + Short) and TikTok...")
        try:
            yt_access_token = refresh_youtube_access_token()
        except Exception as exc:
            print(f"      [YouTube Auth Warning] {exc}")
            yt_access_token = None

        for lang, (yt_mp4, tt_mp4, _) in rendered_videos.items():
            try:
                normal_url, short_url = upload_both_to_youtube(
                    normal_video_path=yt_mp4,
                    short_video_path=tt_mp4,
                    story_pkg=story_pkg,
                    lang=lang,
                    access_token=yt_access_token,
                )
                print(
                    f"      [{lang.upper()} YouTube Summary] Normal: {normal_url or 'Not uploaded'} | "
                    f"Short: {short_url or 'Not uploaded'}"
                )
            except Exception as exc:
                print(f"      [{lang.upper()} YouTube ERROR] {exc}")

        # Upload primary vertical video to TikTok
        first_lang = STORY_LANGUAGES[0]
        try:
            tt_result = upload_to_tiktok(rendered_videos[first_lang][1], story_pkg)
            print(f"      [TikTok Summary] {tt_result or 'Not uploaded'}")
        except Exception as exc:
            print(f"      [TikTok ERROR] {exc}")

    print("=" * 76)
    print("  PIPELINE FINISHED SUCCESSFULLY!")
    for lang, (yt_mp4, tt_mp4, srt_path) in rendered_videos.items():
        print(f"  - [{lang.upper()}] YouTube 16:9 : {yt_mp4}")
        print(f"  - [{lang.upper()}] Short 9:16   : {tt_mp4}")
        print(f"  - [{lang.upper()}] Subtitles    : {srt_path}")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
