# Social Optimize Machine

Turn any topic into a complete, publish-ready content package in minutes.

## What it does

Give it a topic → it generates:
- **AI Script** (via Claude) — title, description, narration, hashtags, keywords
- **Voiceover** (edge-tts) — natural-sounding AI narration in any voice
- **Stock Media** (Pexels API) — relevant video clips and images
- **Thumbnail** — eye-catching branded thumbnail
- **Final Video** — fully assembled MP4 with audio, visuals, and branding
- **Auto-publishes** to YouTube, TikTok, and Instagram

## Supported Formats

| Format | Duration | Aspect Ratio | Best For |
|--------|----------|--------------|----------|
| `short` | ~55s | 9:16 Portrait | YouTube Shorts, TikTok |
| `reel` | ~30s | 9:16 Portrait | Instagram Reels |
| `long` | ~8 min | 16:9 Landscape | YouTube Videos |
| `podcast` | ~10 min | 16:9 Landscape | YouTube Podcasts |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Edit .env with your keys

# 3. Check configuration
python main.py setup

# 4. Create your first video!
python main.py create "The Future of Electric Cars" --format short --dry-run
```

## Usage

### Create a single video

```bash
# Short video (TikTok/Shorts style)
python main.py create "5 Morning Habits That Changed My Life" -f short -p youtube -p tiktok

# Long YouTube video
python main.py create "Complete Python Tutorial for Beginners" -f long -p youtube --privacy unlisted

# Podcast episode
python main.py create "The Rise of AI in Healthcare" -f podcast -p youtube

# Instagram Reel
python main.py create "Quick Healthy Breakfast Ideas" -f reel --dry-run

# Custom voice and audience
python main.py create "Stock Market Basics" \
  -f long \
  -p youtube \
  --audience "beginner investors aged 20-35" \
  --voice en-US-GuyNeural \
  --style ocean \
  --privacy private
```

### BLITZ mode — all formats at once

```bash
# Creates short + long + podcast versions simultaneously
python main.py blitz "Top 10 Travel Destinations 2025" -p youtube -p tiktok
```

### Other commands

```bash
python main.py jobs        # List past jobs
python main.py voices      # List available TTS voices
python main.py setup       # Check API key configuration
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--format / -f` | `short`, `long`, `podcast`, `reel` | `short` |
| `--platforms / -p` | `youtube`, `tiktok`, `instagram` | (none) |
| `--audience / -a` | Target audience description | `general public` |
| `--voice / -v` | TTS voice name | `en-US-AriaNeural` |
| `--style / -s` | Thumbnail style | `fire` |
| `--privacy` | `private`, `unlisted`, `public` | `private` |
| `--instructions / -i` | Extra AI instructions | - |
| `--dry-run` | Generate but skip upload | `false` |
| `--cleanup` | Delete stock files after | `false` |

## API Keys Required

### Must Have
- **Anthropic API** — [console.anthropic.com](https://console.anthropic.com)

### For Stock Media (Recommended)
- **Pexels API** — [pexels.com/api](https://www.pexels.com/api/) (free)

### For Publishing
| Platform | Where to Get | Notes |
|----------|-------------|-------|
| YouTube | [Google Cloud Console](https://console.cloud.google.com) | Enable YouTube Data API v3, create OAuth 2.0 credentials |
| TikTok | [developers.tiktok.com](https://developers.tiktok.com) | Apply for Content Posting API access |
| Instagram | [developers.facebook.com](https://developers.facebook.com) | Requires Instagram Business account + Meta app |

## Output Structure

Each job creates a directory under `./output/`:

```
output/
└── 20240101_120000_future-of-ai_short/
    ├── script.json          ← AI-generated script
    ├── voiceover.mp3        ← TTS narration
    ├── thumbnail.jpg        ← Generated thumbnail
    ├── video.mp4            ← Final assembled video
    ├── manifest.json        ← Full job metadata + publish results
    └── stock/
        ├── stock_videos/    ← Downloaded Pexels clips
        └── stock_images/    ← Downloaded Pexels images
```

## Architecture

```
main.py                    ← CLI entry point
social_optimize.py         ← Main orchestrator pipeline
config.py                  ← Environment + settings
generators/
  script_generator.py      ← Claude AI script generation
  audio_generator.py       ← edge-tts voiceover
  media_fetcher.py         ← Pexels stock media
  thumbnail_generator.py   ← Pillow thumbnail creation
  video_generator.py       ← MoviePy video assembly
publishers/
  youtube_publisher.py     ← YouTube Data API v3
  tiktok_publisher.py      ← TikTok Content Posting API
  instagram_publisher.py   ← Meta Graph API
utils/
  file_manager.py          ← Job directories, manifests
  logger.py                ← Rich-powered console output
```

## Multi-Platform Deployment

The app ships for every environment from one codebase.

### Web (PWA) — already live
The Flask app is a full **Progressive Web App**. Users can install it from any browser:
- **Chrome/Edge desktop** → address bar "Install" button
- **Safari on iPhone/iPad** → Share → Add to Home Screen
- **Android Chrome** → Install prompt appears automatically

### Desktop — Electron (macOS · Windows · Linux)

```bash
cd desktop
npm install

# Run locally (connects to production URL)
npm start

# Build distributable
npm run build:mac      # → .dmg + .zip (Intel + Apple Silicon)
npm run build:win      # → .exe installer + portable
npm run build:linux    # → .AppImage + .deb + .rpm
```

The desktop app bundles as a standalone installer. On macOS you get a native `.dmg`, on Windows an NSIS installer, on Linux an AppImage.

### Mobile — Expo (iOS · Android)

Requires [EAS CLI](https://docs.expo.dev/eas/) and an Expo account.

```bash
cd mobile
npm install
npm install -g eas-cli

# Set your project ID in app.json → extra.eas.projectId

# Run in simulator/emulator
npm run ios         # Xcode + iOS simulator required
npm run android     # Android Studio + emulator required

# Build for distribution
npm run build:ios       # → .ipa for App Store
npm run build:android   # → .aab for Google Play

# Submit to stores
npm run submit:ios
npm run submit:android
```

Update the `APP_URL` in `mobile/src/constants/index.ts` to point to your deployed backend before building.

## Tips

- Start with `--dry-run` to see content without uploading
- Use `--privacy private` when testing uploads
- Short videos work best under 60 seconds (YouTube Shorts requirement)
- For Instagram, you need to host the final video on a CDN first — the Meta API does not accept local files
- Run `python main.py voices` to browse all available TTS voices
- Add `--instructions "focus on humor and memes"` to customize the AI's style
