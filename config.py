import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", os.urandom(32).hex())
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://socialoptimize.online")

# ── Persistent data directory ─────────────────────────────────────────────────
# Locally this is the project root; on Render it's the mounted disk at /data
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent))

# ── Stripe ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY       = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY  = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")

STRIPE_PRICE_STARTER  = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_CREATOR  = os.getenv("STRIPE_PRICE_CREATOR", "")
STRIPE_PRICE_AGENCY   = os.getenv("STRIPE_PRICE_AGENCY", "")

# ── Subscription tiers ───────────────────────────────────────────────────────
TIERS = {
    "free": {
        "label": "Free Trial",
        "price_monthly": 0,
        "videos_per_month": 2,
        "higgsfield_credits": 0,
        "stripe_price_id": None,
        "features": ["2 videos/month", "All 8 platforms", "Pexels stock media", "Basic scripts"],
    },
    "starter": {
        "label": "Starter",
        "price_monthly": 29,
        "videos_per_month": 15,
        "higgsfield_credits": 150,
        "stripe_price_id": STRIPE_PRICE_STARTER,
        "features": ["15 videos/month", "All 8 platforms", "150 AI video credits", "5-agent pipeline"],
    },
    "creator": {
        "label": "Creator",
        "price_monthly": 79,
        "videos_per_month": 50,
        "higgsfield_credits": 500,
        "stripe_price_id": STRIPE_PRICE_CREATOR,
        "features": ["50 videos/month", "500 AI video credits", "All platforms", "Studio 56"],
    },
    "agency": {
        "label": "Agency",
        "price_monthly": 199,
        "videos_per_month": -1,
        "higgsfield_credits": 2000,
        "stripe_price_id": STRIPE_PRICE_AGENCY,
        "features": ["Unlimited videos", "2000 AI video credits", "Priority processing", "All features"],
    },
}

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = DATA_DIR / "output"

# Subdirectories
VIDEOS_DIR     = OUTPUT_DIR / "videos"
AUDIO_DIR      = OUTPUT_DIR / "audio"
THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"
SCRIPTS_DIR    = OUTPUT_DIR / "scripts"

for d in [VIDEOS_DIR, AUDIO_DIR, THUMBNAILS_DIR, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Model routing by subscription tier ───────────────────────────────────────
# Free tier uses Haiku (cheapest Claude) to keep costs near zero.
# Paid tiers get Sonnet for quality scripts and agents.
TIER_CLAUDE_MODEL = {
    "free":    "claude-haiku-4-5-20251001",
    "starter": "claude-sonnet-4-6",
    "creator": "claude-sonnet-4-6",
    "agency":  "claude-sonnet-4-6",
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Google Flow / Veo 2
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Higgsfield AI — single token used by both the CLI and MCP HTTP client
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
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# TikTok
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")

# Instagram
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")

# Facebook / Meta (shared app for Facebook + Instagram)
FACEBOOK_APP_ID      = os.getenv("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET  = os.getenv("FACEBOOK_APP_SECRET", "")
FACEBOOK_PAGE_ID     = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")

# Twitter/X
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")

# LinkedIn
LINKEDIN_CLIENT_ID     = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_ACCESS_TOKEN  = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_ID     = os.getenv("LINKEDIN_PERSON_ID", "")

# Pinterest
PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BOARD_ID = os.getenv("PINTEREST_BOARD_ID", "")

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

# SMTP (for email notifications — all optional, silently skipped if not set)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@socialoptimize.online")

TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.getenv("TWILIO_FROM_NUMBER", "")

# Google Cloud TTS Neural2 voices
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "en-US-Neural2-C")
GOOGLE_TTS_VOICES = [
    {"id": "en-US-Neural2-A", "name": "US Male A", "locale": "en-US"},
    {"id": "en-US-Neural2-C", "name": "US Female C", "locale": "en-US"},
    {"id": "en-US-Neural2-D", "name": "US Male D", "locale": "en-US"},
    {"id": "en-US-Neural2-F", "name": "US Female F", "locale": "en-US"},
    {"id": "en-US-Neural2-G", "name": "US Female G", "locale": "en-US"},
    {"id": "en-US-Neural2-H", "name": "US Female H", "locale": "en-US"},
    {"id": "en-US-Neural2-I", "name": "US Male I", "locale": "en-US"},
    {"id": "en-US-Neural2-J", "name": "US Male J", "locale": "en-US"},
    {"id": "en-GB-Neural2-A", "name": "UK Female A", "locale": "en-GB"},
    {"id": "en-GB-Neural2-B", "name": "UK Male B", "locale": "en-GB"},
    {"id": "en-AU-Neural2-A", "name": "AU Female A", "locale": "en-AU"},
    {"id": "en-AU-Neural2-B", "name": "AU Male B", "locale": "en-AU"},
]

# Cloud Translation supported languages
TRANSLATION_LANGUAGES = {
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Simplified)",
    "ar": "Arabic", "hi": "Hindi", "it": "Italian", "ru": "Russian",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "sv": "Swedish",
}

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

