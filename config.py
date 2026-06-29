import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://socialoptimize.online")

# ── Persistent data directory ─────────────────────────────────────────────────
# Locally this is the project root; on Render it's the mounted disk at /data
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent))

# ── Secret key: stable across restarts ───────────────────────────────────────
# Priority: SECRET_KEY env var > persisted key file > new random key (dev only)
def _load_secret_key() -> str:
    env_key = os.getenv("SECRET_KEY", "")
    if env_key:
        return env_key
    key_file = DATA_DIR / ".secret_key"
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            stored = key_file.read_text().strip()
            if len(stored) >= 32:
                return stored
        new_key = os.urandom(32).hex()
        key_file.write_text(new_key)
        return new_key
    except Exception:
        return os.urandom(32).hex()

SECRET_KEY = _load_secret_key()

# ── Stripe ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY       = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY  = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")

STRIPE_PRICE_STARTER  = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_CREATOR  = os.getenv("STRIPE_PRICE_CREATOR", "")
STRIPE_PRICE_PRO      = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_AGENCY   = os.getenv("STRIPE_PRICE_AGENCY", "")

# ── Whop ─────────────────────────────────────────────────────────────────────
WHOP_API_KEY          = os.getenv("WHOP_API_KEY", "")
WHOP_WEBHOOK_SECRET   = os.getenv("WHOP_WEBHOOK_SECRET", "")
WHOP_PLAN_STARTER     = os.getenv("WHOP_PLAN_STARTER", "")
WHOP_PLAN_CREATOR     = os.getenv("WHOP_PLAN_CREATOR", "")
WHOP_PLAN_PRO         = os.getenv("WHOP_PLAN_PRO", "")
WHOP_PLAN_AGENCY      = os.getenv("WHOP_PLAN_AGENCY", "")

# ── Gumroad ───────────────────────────────────────────────────────────────────
GUMROAD_ACCESS_TOKEN    = os.getenv("GUMROAD_ACCESS_TOKEN", "")
GUMROAD_WEBHOOK_SECRET  = os.getenv("GUMROAD_WEBHOOK_SECRET", "")
GUMROAD_PRODUCT_STARTER = os.getenv("GUMROAD_PRODUCT_STARTER", "")
GUMROAD_PRODUCT_CREATOR = os.getenv("GUMROAD_PRODUCT_CREATOR", "")
GUMROAD_PRODUCT_PRO     = os.getenv("GUMROAD_PRODUCT_PRO", "")
GUMROAD_PRODUCT_AGENCY  = os.getenv("GUMROAD_PRODUCT_AGENCY", "")

# ── LemonSqueezy ──────────────────────────────────────────────────────────────
LEMONSQUEEZY_API_KEY        = os.getenv("LEMONSQUEEZY_API_KEY", "")
LEMONSQUEEZY_WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
LEMONSQUEEZY_STORE_ID       = os.getenv("LEMONSQUEEZY_STORE_ID", "")
LEMONSQUEEZY_VARIANT_STARTER = os.getenv("LEMONSQUEEZY_VARIANT_STARTER", "")
LEMONSQUEEZY_VARIANT_CREATOR = os.getenv("LEMONSQUEEZY_VARIANT_CREATOR", "")
LEMONSQUEEZY_VARIANT_PRO     = os.getenv("LEMONSQUEEZY_VARIANT_PRO", "")
LEMONSQUEEZY_VARIANT_AGENCY  = os.getenv("LEMONSQUEEZY_VARIANT_AGENCY", "")

# ── AppSumo ───────────────────────────────────────────────────────────────────
APPSUMO_API_KEY         = os.getenv("APPSUMO_API_KEY", "")
APPSUMO_WEBHOOK_SECRET  = os.getenv("APPSUMO_WEBHOOK_SECRET", "")
APPSUMO_PRODUCT_ID      = os.getenv("APPSUMO_PRODUCT_ID", "")

# ── PayPal ────────────────────────────────────────────────────────────────────
PAYPAL_CLIENT_ID        = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET    = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_WEBHOOK_ID       = os.getenv("PAYPAL_WEBHOOK_ID", "")
PAYPAL_MODE             = os.getenv("PAYPAL_MODE", "sandbox")
PAYPAL_PLAN_STARTER     = os.getenv("PAYPAL_PLAN_STARTER", "")
PAYPAL_PLAN_CREATOR     = os.getenv("PAYPAL_PLAN_CREATOR", "")
PAYPAL_PLAN_PRO         = os.getenv("PAYPAL_PLAN_PRO", "")
PAYPAL_PLAN_AGENCY      = os.getenv("PAYPAL_PLAN_AGENCY", "")

# ── Affiliate Program ────────────────────────────────────────────────────────
AFFILIATE_COMMISSION_PCT  = float(os.getenv("AFFILIATE_COMMISSION_PCT", "20"))
AFFILIATE_COOKIE_DAYS     = int(os.getenv("AFFILIATE_COOKIE_DAYS", "30"))

# ── Testing / bypass flags ───────────────────────────────────────────────────
# Set BYPASS_USAGE_GATE=1 on Render while testing to skip video-count limits.
BYPASS_USAGE_GATE = os.getenv("BYPASS_USAGE_GATE", "0") not in ("", "0", "false", "no")

# ── Subscription tiers ───────────────────────────────────────────────────────
TIERS = {
    "free": {
        "label": "Free",
        "description": "Get started for free — no credit card, no commitment. 3 AI videos per month with 10 credits.",
        "price_monthly": 0,
        "trial_days": 0,
        "videos_per_month": -1,
        "higgsfield_credits": 10,
        "stripe_price_id": None,
        "features": [
            "3 AI videos/month",
            "10 Social Optimize Credits",
            "5-agent AI pipeline",
            "Publish to 3 platforms",
            "Content Calendar",
            "Pexels stock media library",
            "Quick Post from photo/video",
            "Basic AI script writing",
            "Hashtag suggestions",
            "The Cut",
            "Community support",
        ],
    },
    "starter": {
        "label": "Starter",
        "description": "Essential tools to start growing your brand — just $9.99/mo.",
        "price_monthly": 9.99,
        "trial_days": 7,
        "videos_per_month": 7,
        "higgsfield_credits": 50,
        "stripe_price_id": STRIPE_PRICE_STARTER,
        "whop_plan_id": WHOP_PLAN_STARTER,
        "features": [
            "7-day free trial",
            "7 AI videos/month",
            "Publish to 5 platforms",
            "50 Social Optimize Credits/mo",
            "5-agent AI pipeline",
            "Content calendar & scheduling",
            "The Cut",
            "Template Library",
            "Hashtag research",
            "Quick Post from photo/video",
            "Pexels stock media library",
            "Email support",
        ],
    },
    "creator": {
        "label": "Creator",
        "description": "Built for entrepreneurs and small businesses. 14-day free trial, then $29.99/mo.",
        "price_monthly": 29.99,
        "trial_days": 14,
        "videos_per_month": 15,
        "higgsfield_credits": 150,
        "stripe_price_id": STRIPE_PRICE_CREATOR,
        "whop_plan_id": WHOP_PLAN_CREATOR,
        "features": [
            "14-day free trial",
            "15 AI videos/month",
            "Publish to 8 platforms",
            "150 Social Optimize Credits/mo",
            "5-agent AI pipeline",
            "The Forge — production suite",
            "Ad Lab — photo → ad",
            "Hit Factory",
            "Quick Post from photo/video",
            "Batch Generator",
            "Content calendar & scheduling",
            "Template Library",
            "Hashtag research",
            "Email support",
        ],
    },
    "pro": {
        "label": "Pro",
        "description": "The full creative suite for serious creators. 14-day free trial, then $79.99/mo.",
        "price_monthly": 79.99,
        "trial_days": 14,
        "videos_per_month": 50,
        "higgsfield_credits": 500,
        "stripe_price_id": STRIPE_PRICE_PRO,
        "whop_plan_id": WHOP_PLAN_PRO,
        "features": [
            "14-day free trial",
            "50 AI videos/month",
            "Publish to all 8 platforms",
            "500 Social Optimize Credits/mo",
            "Everything in Creator",
            "The Forge — full production suite",
            "Cinema House — cinematic AI",
            "Hit Factory — DJ & beat maker",
            "The Scalpel — auto-clip to shorts",
            "Documentary & Animation formats",
            "Competitor & trend analysis",
            "Multi-language (15 languages)",
            "Batch create 30 videos at once",
            "Advanced analytics & reporting",
            "The Cut — full editing suite",
            "Priority support",
        ],
    },
    "agency": {
        "label": "Agency",
        "description": "Scale your content operation. 14-day free trial, then $199.99/mo.",
        "price_monthly": 199.99,
        "trial_days": 14,
        "videos_per_month": 125,
        "higgsfield_credits": 2000,
        "stripe_price_id": STRIPE_PRICE_AGENCY,
        "whop_plan_id": WHOP_PLAN_AGENCY,
        "features": [
            "14-day free trial",
            "125 AI videos/month",
            "Publish to all 8 platforms",
            "2,000 Social Optimize Credits/mo",
            "Everything in Pro",
            "The Scalpel — unlimited clips",
            "Team management (5 seats)",
            "White-label exports",
            "SMS/WhatsApp outreach (Twilio)",
            "Contacts / CRM",
            "API access",
            "Dedicated account manager",
            "24/7 priority support",
        ],
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
    "starter": "claude-haiku-4-5-20251001",
    "creator": "claude-sonnet-4-6",
    "pro":     "claude-sonnet-4-6",
    "agency":  "claude-sonnet-4-6",
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY      = os.getenv("QWEN_API_KEY", "")       # Alibaba DashScope
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")       # Groq (Llama 3.3 70B) — free tier
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "") # OpenRouter — free models available
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
PEXELS_API_KEY = ""  # Removed — use Pixabay instead

# Google Flow / Veo 2
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # "Adam" — deep male narrator

# Hit Factory providers
SUNO_COOKIE = os.getenv("SUNO_COOKIE", "")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
MUBERT_KEY = os.getenv("MUBERT_KEY", "")
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY", "")

# Higgsfield AI — bearer token for REST + MCP API calls
HIGGSFIELD_MCP_TOKEN = (
    os.getenv("HIGGSFIELD_MCP_TOKEN")
    or os.getenv("HIGGSFIELD_TOKEN")
    or os.getenv("HIGGSVILLE_TOKEN")
    or os.getenv("HIGGSVILLE_MCP_TOKEN")
    or os.getenv("HIGGSFIELD_API_KEY")
    or ""
)
HIGGSFIELD_MCP_URL = os.getenv("HIGGSFIELD_MCP_URL", "https://mcp.higgsfield.ai/mcp")

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

# Twitter/X  (OAuth 2.0 — create app at developer.twitter.com)
TWITTER_CLIENT_ID     = os.getenv("TWITTER_CLIENT_ID", "")
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET", "")
TWITTER_REDIRECT_URI  = os.getenv("TWITTER_REDIRECT_URI", "https://socialoptimize.online/oauth/twitter/callback")

# Threads  (add Threads product to your Facebook App at developers.facebook.com)
THREADS_APP_ID     = os.getenv("THREADS_APP_ID", "")
THREADS_APP_SECRET = os.getenv("THREADS_APP_SECRET", "")
THREADS_REDIRECT_URI = os.getenv("THREADS_REDIRECT_URI", "https://socialoptimize.online/oauth/threads/callback")

# Twitch  (create app at dev.twitch.tv/console)
TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
TWITCH_REDIRECT_URI  = os.getenv("TWITCH_REDIRECT_URI", "https://socialoptimize.online/oauth/twitch/callback")

# Snapchat  (create app at kit.snapchat.com)
SNAP_CLIENT_ID     = os.getenv("SNAP_CLIENT_ID", "")
SNAP_CLIENT_SECRET = os.getenv("SNAP_CLIENT_SECRET", "")
SNAP_REDIRECT_URI  = os.getenv("SNAP_REDIRECT_URI", "https://socialoptimize.online/oauth/snapchat/callback")

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
VIDEO_WIDTH = int(os.getenv("DEFAULT_VIDEO_WIDTH", "1280"))
VIDEO_HEIGHT = int(os.getenv("DEFAULT_VIDEO_HEIGHT", "720"))
SHORT_WIDTH = int(os.getenv("SHORT_VIDEO_WIDTH", "720"))
SHORT_HEIGHT = int(os.getenv("SHORT_VIDEO_HEIGHT", "1280"))

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

# Google Cloud TTS voices (Studio > Journey > Neural2 quality order)
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "en-US-Studio-O")
GOOGLE_TTS_VOICES = [
    {"id": "en-US-Studio-O", "name": "US Male Studio O (Best)", "locale": "en-US"},
    {"id": "en-US-Studio-Q", "name": "US Male Studio Q (Best)", "locale": "en-US"},
    {"id": "en-US-Journey-D", "name": "US Male Journey D", "locale": "en-US"},
    {"id": "en-US-Journey-F", "name": "US Female Journey F", "locale": "en-US"},
    {"id": "en-US-Journey-O", "name": "US Male Journey O", "locale": "en-US"},
    {"id": "en-US-Neural2-A", "name": "US Male Neural2 A", "locale": "en-US"},
    {"id": "en-US-Neural2-C", "name": "US Female Neural2 C", "locale": "en-US"},
    {"id": "en-US-Neural2-D", "name": "US Male Neural2 D", "locale": "en-US"},
    {"id": "en-US-Neural2-F", "name": "US Female Neural2 F", "locale": "en-US"},
    {"id": "en-US-Neural2-G", "name": "US Female Neural2 G", "locale": "en-US"},
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

