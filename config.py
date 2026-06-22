import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

# Subdirectories
VIDEOS_DIR = OUTPUT_DIR / "videos"
AUDIO_DIR = OUTPUT_DIR / "audio"
THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"
SCRIPTS_DIR = OUTPUT_DIR / "scripts"

for d in [VIDEOS_DIR, AUDIO_DIR, THUMBNAILS_DIR, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Google Flow / Veo 2
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Higgsfield AI
HIGGSFIELD_API_KEY = os.getenv("HIGGSFIELD_API_KEY", "")  # format: "key:secret"
# MCP auth token — used by the https://mcp.higgsfield.ai/mcp HTTP client.
# Falls back to HIGGSFIELD_API_KEY (key portion) if not set separately.
HIGGSFIELD_MCP_TOKEN = os.getenv("HIGGSFIELD_MCP_TOKEN", "")

# YouTube
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8080")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_CHANNEL_URL = f"https://www.youtube.com/channel/{YOUTUBE_CHANNEL_ID}" if YOUTUBE_CHANNEL_ID else ""
YOUTUBE_TOKEN_FILE = BASE_DIR / "youtube_token.json"
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# TikTok
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")

# Instagram
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")

# Video settings
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en-US")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "en-US-AriaNeural")
VIDEO_WIDTH = int(os.getenv("DEFAULT_VIDEO_WIDTH", "1920"))
VIDEO_HEIGHT = int(os.getenv("DEFAULT_VIDEO_HEIGHT", "1080"))
SHORT_WIDTH = int(os.getenv("SHORT_VIDEO_WIDTH", "1080"))
SHORT_HEIGHT = int(os.getenv("SHORT_VIDEO_HEIGHT", "1920"))

# Content limits (seconds)
SHORTS_MAX_DURATION = 60
LONG_VIDEO_MIN_DURATION = 180
PODCAST_MIN_DURATION = 300

AVAILABLE_VOICES = [
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-US-DavisNeural",
    "en-GB-SoniaNeural",
    "en-AU-NatashaNeural",
]

# AI Video providers
AI_VIDEO_PROVIDERS = ["none", "higgsville", "google_flow", "both"]

HIGGSVILLE_MODELS = {
    # Kling
    "kling3_0":               "Kling 3.0 — Multi-shot, 4K, audio",
    "kling3_0_turbo":         "Kling 3.0 Turbo — Fast text-to-video",
    "kling2_6":               "Kling 2.6 — Cinematic + physics",
    # Google Veo (via Higgsville)
    "veo3_1":                 "Google Veo 3.1 — Ultra-realistic",
    "veo3":                   "Google Veo 3 — Cinematic, broad creative",
    "veo3_1_lite":            "Veo 3.1 Lite — Fast, budget",
    # Higgsfield Cinema
    "cinematic_studio_3_0":        "Cinema Studio 3.0 — Best quality",
    "cinematic_studio_video_v2":   "Cinema Studio 2 — Genre control",
    "cinematic_studio_video":      "Cinema Studio — Dramatic",
    # ByteDance
    "seedance_2_0":           "Seedance 2.0 — Identity-consistent",
    "seedance_1_5":           "Seedance 1.5 Pro — Reliable motion",
    # Others
    "minimax_hailuo":         "Minimax Hailuo — Natural physics",
    "wan2_7":                 "Wan 2.7 — Audio-synced",
    "wan2_6":                 "Wan 2.6 — Stylized, experimental",
    "grok_video_v15":         "Grok Imagine 1.5 — Cinematic",
    "grok_video":             "Grok Imagine — Versatile",
}

