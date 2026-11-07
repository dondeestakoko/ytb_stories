# Automated Daily Children's Story Generator (YouTube 16:9 + TikTok 9:16)

A 100% hands-off, **$0.00/video** Python pipeline and GitHub Actions automation that generates a unique ~300-word moral children's story every day, synthesizes expressive voice narration with word-level subtitles, generates 6 consistent 3D storybook scenes in **both 16:9 (YouTube) and 9:16 (TikTok)**, applies smooth **Ken Burns pan/zoom animation**, and uploads simultaneously to **YouTube** and **TikTok** at randomized daily times.

---

## 1. Exact APIs Needed (100% Free Stack)

| Pipeline Stage | Service / Library Used | Cost | Required GitHub Secret(s) |
| :--- | :--- | :--- | :--- |
| **1. Story, 6 Scene Prompts & SEO Metadata** | **Google Gemini API (`gemini-3.8-flash`)** via `google-genai` SDK *(note: replaces deprecated `gemini-2.5-flash`)* | **$0.00** (Free tier at [Google AI Studio](https://aistudio.google.com/apikey)) | `GEMINI_API_KEY` |
| **2. Voice Narration + Word Timestamps (`.srt`)** | **`edge-tts`** (Microsoft Edge Neural TTS — `en-US-AriaNeural`) | **$0.00** (No API key needed; extracts exact timestamps natively without Whisper) | *None* |
| **3. 12 Storybook Images (6x 16:9 + 6x 9:16)** | **Pollinations.ai (`model=flux`)** *(Optional fallback: Together AI `FLUX.1-schnell`)* | **$0.00** (No API key needed for Pollinations) | *None* *(or optional `TOGETHER_API_KEY`)* |
| **4. Animation & Video Stitching** | **MoviePy + Pillow + FFmpeg** (Ken Burns zoom/pan + burned-in subtitles) | **$0.00** (Runs on GitHub Actions Ubuntu runner) | *None* |
| **5. YouTube Upload (16:9)** | **YouTube Data API v3** (OAuth 2.0 Refresh Token — 1,600 / 10,000 free daily quota points) | **$0.00** | `YOUTUBE_CLIENT_ID`<br>`YOUTUBE_CLIENT_SECRET`<br>`YOUTUBE_REFRESH_TOKEN` |
| **6. TikTok Upload (9:16)** | **Official TikTok Content Posting API v2** *OR* **`tiktok-uploader` (Browser Cookies)** | **$0.00** | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`<br>*(or `TIKTOK_COOKIES_JSON`)* |

---

## 2. How Daily Random Timing Works (Anti-Detection)

To ensure your accounts never post at a robotic, predictable timestamp:
1. **Self-Mutating Cron Schedule**: After every daily run, [`scripts/randomize_cron.py`](scripts/randomize_cron.py) rewrites the `cron:` expression inside [`.github/workflows/daily_story.yml`](.github/workflows/daily_story.yml) to a **new random hour and minute** between `11:00 UTC` and `21:59 UTC` for the next day and commits it with `[skip ci]`.
2. **In-Run Random Jitter**: When triggered by the daily cron schedule, the workflow sleeps for an additional random **1 to 20 minutes** before executing `main.py`, adding second-level jitter.
3. **Simultaneous Publishing**: Step 5 in [`main.py`](main.py) uses a `ThreadPoolExecutor` to upload `final_story_youtube_16x9.mp4` to YouTube and `final_story_tiktok_9x16.mp4` to TikTok at the exact same time.

---

## 3. One-Time Setup Guide (5 Minutes)

### Step A: Get Your Free `GEMINI_API_KEY`
1. Go to [Google AI Studio API Keys](https://aistudio.google.com/apikey).
2. Click **Create API Key** and copy it.

### Step B: Get Your `YOUTUBE_REFRESH_TOKEN`
1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a new project.
2. Navigate to **APIs & Services -> Library**, search for **YouTube Data API v3**, and click **Enable**.
3. Go to **APIs & Services -> OAuth consent screen**:
   - Choose **External**, fill in an app name (e.g., `Daily Story Uploader`), and under **Test users**, add your YouTube account's email address.
4. Go to **APIs & Services -> Credentials**:
   - Click **Create Credentials -> OAuth client ID** -> Choose **Desktop app**.
   - Copy your **Client ID** and **Client Secret**.
5. On your computer, run the included helper script once:
   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\pip install -r requirements.txt
   # macOS/Linux: .venv/bin/pip install -r requirements.txt
   python scripts/get_youtube_token.py
   ```
   A browser tab will open. Log into your YouTube channel, click **Allow**, and the terminal will print your `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN`.

### Step C: Set Up TikTok Authentication (Choose Either Option)

- **Option 1 — Official TikTok Content Posting API (Recommended for long-term stability):**
  1. Create an app at [TikTok for Developers](https://developers.tiktok.com/), add the **Content Posting API** product (`video.publish` scope), and set Redirect URI to `http://localhost:8085/callback/`.
  2. Run `python scripts/get_tiktok_token.py` locally to get your `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REFRESH_TOKEN`.
  *(Note: If your TikTok developer app has not gone through audit yet, the uploader automatically falls back to `SELF_ONLY` private/draft mode so you can tap "Public" in the TikTok app in 1 second).*

- **Option 2 — Cookie-Based Upload (Posts Public immediately without developer app review):**
  1. Install the **Cookie-Editor** or **Get cookies.txt LOCALLY** browser extension while logged into `tiktok.com`.
  2. Export your TikTok cookies as **JSON** (or Netscape `cookies.txt` format) and save the content as the `TIKTOK_COOKIES_JSON` secret in GitHub.

### Step D: Add Secrets to GitHub Actions
In your GitHub repository, go to **Settings -> Secrets and variables -> Actions -> New repository secret** and add:
- `GEMINI_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` *(or `TIKTOK_COOKIES_JSON`)*

---

## 4. Local Testing & Manual Triggers

- **Zero-Key Smoke Test (Tests Edge-TTS + Pollinations Flux + MoviePy Dual Video Rendering using the built-in Brave Fox story):**
  ```bash
  python main.py --mock-story --skip-upload
  ```
- **Full AI Generation Without Uploading:**
  ```bash
  python main.py --skip-upload
  ```
- **Manual Run on GitHub Actions:**
  Go to your repository's **Actions** tab -> **Daily Story Generator (YouTube + TikTok)** -> **Run workflow**.
