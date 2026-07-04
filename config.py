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
PIXABAY_API_KEY = ""  # Disabled — Pixabay's API terms prohibit automated/AI-pipeline use
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Google Flow / Veo 2
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # "Adam" — deep male narrator
# Highest-quality multilingual model for narration. Override to
# "eleven_turbo_v2_5" for faster/cheaper synthesis at a small quality cost.
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")

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
    "https://www.googleapis.com/auth/youtube.force-ssl",  # needed to read/reply to comments
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
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "en-US-Studio-O")
VIDEO_WIDTH = int(os.getenv("DEFAULT_VIDEO_WIDTH", "1280"))
VIDEO_HEIGHT = int(os.getenv("DEFAULT_VIDEO_HEIGHT", "720"))
SHORT_WIDTH = int(os.getenv("SHORT_VIDEO_WIDTH", "720"))
SHORT_HEIGHT = int(os.getenv("SHORT_VIDEO_HEIGHT", "1280"))

# Content limits (seconds)
SHORTS_MAX_DURATION = 60
LONG_VIDEO_MIN_DURATION = 180
PODCAST_MIN_DURATION = 300

# Single canonical voice catalog used across every studio (Create, Studio,
# Hollywood, Ad Lab, Batch, Settings). 10 premium ElevenLabs voices — 5 female,
# 5 male — each carrying a same-gender Google Neural2 and edge-tts fallback so
# a user's choice never silently flips gender (or drops to a robotic espeak
# voice) when ElevenLabs is unavailable.
#
# `id` is the ElevenLabs voice_id — the primary, high-quality source. The
# `google`/`edge` keys are graceful, gender-matched degradations used only when
# ElevenLabs can't be reached. These IDs are ElevenLabs' stable premade library.
VOICE_CATALOG = [
    # ── Female ────────────────────────────────────────────────────────────────
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",    "gender": "Female", "style": "Calm & Narrative",     "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Studio-O",  "edge": "en-US-AriaNeural"},
    {"id": "XrExE9yKIg1WjnnlVkGX", "name": "Matilda",   "gender": "Female", "style": "Warm & Friendly",      "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Neural2-F", "edge": "en-US-JennyNeural"},
    {"id": "XB0fDUnXU5powFXDhCwa", "name": "Charlotte", "gender": "Female", "style": "Expressive & Engaging", "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Neural2-H", "edge": "en-US-AriaNeural"},
    {"id": "oWAxZDx7w5VEj9dCyTzz", "name": "Grace",     "gender": "Female", "style": "Soft & Soothing",      "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Neural2-G", "edge": "en-US-JennyNeural"},
    {"id": "ThT5KcBeYPX3keUQqHPh", "name": "Dorothy",   "gender": "Female", "style": "Bright & Pleasant",    "locale": "en-GB", "provider": "elevenlabs", "google": "en-GB-Neural2-A", "edge": "en-GB-SoniaNeural"},
    # ── Male ──────────────────────────────────────────────────────────────────
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",      "gender": "Male",   "style": "Deep & Authoritative", "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Studio-Q",  "edge": "en-US-GuyNeural"},
    {"id": "nPczCjzI2devNBz1zQrb", "name": "Brian",     "gender": "Male",   "style": "Rich Narration",       "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Neural2-A", "edge": "en-US-GuyNeural"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni",    "gender": "Male",   "style": "Warm & Well-Rounded",  "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Neural2-D", "edge": "en-US-DavisNeural"},
    {"id": "JBFqnCBsd6RMkjVDRZzb", "name": "George",    "gender": "Male",   "style": "Warm Storyteller",     "locale": "en-GB", "provider": "elevenlabs", "google": "en-GB-Neural2-B", "edge": "en-GB-RyanNeural"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh",      "gender": "Male",   "style": "Young & Energetic",    "locale": "en-US", "provider": "elevenlabs", "google": "en-US-Neural2-I", "edge": "en-US-DavisNeural"},
]
for _v in VOICE_CATALOG:
    _v["label"] = f"{_v['name']} — {_v['style']} ({_v['gender']})"
del _v

# Back-compat aliases — both now point at the same single catalog.
AVAILABLE_VOICES = [v["id"] for v in VOICE_CATALOG]

# ── Voice resolution ────────────────────────────────────────────────────────
# Any identifier a caller might hold — an ElevenLabs id, a friendly name
# ("Marcus"), a legacy Google voice id ("en-US-Studio-O"), or an edge voice
# ("en-US-GuyNeural") — resolves to the right {elevenlabs, google, edge} triple
# so every fallback layer stays the SAME gender the user picked.
_VOICE_BY_EL     = {v["id"]: v for v in VOICE_CATALOG}
_VOICE_BY_NAME   = {v["name"].lower(): v for v in VOICE_CATALOG}
_VOICE_BY_GOOGLE = {v["google"]: v for v in VOICE_CATALOG}
_VOICE_BY_EDGE   = {v["edge"]: v for v in VOICE_CATALOG}

# Gender of legacy voice ids that are no longer in the catalog, so an old
# persona/DB value still maps to a same-gender ElevenLabs voice.
_LEGACY_VOICE_GENDER = {
    "en-US-Studio-O": "Female", "en-US-Journey-F": "Female", "en-US-Neural2-C": "Female",
    "en-US-Neural2-F": "Female", "en-US-Neural2-G": "Female", "en-US-Neural2-H": "Female",
    "en-US-AriaNeural": "Female", "en-US-JennyNeural": "Female", "en-GB-SoniaNeural": "Female",
    "en-AU-NatashaNeural": "Female",
    "en-US-Studio-Q": "Male", "en-US-Journey-D": "Male", "en-US-Neural2-A": "Male",
    "en-US-Neural2-D": "Male", "en-US-Neural2-I": "Male",
    "en-US-GuyNeural": "Male", "en-US-DavisNeural": "Male", "en-GB-RyanNeural": "Male",
}


def _looks_like_google_voice(v: str) -> bool:
    return isinstance(v, str) and v.startswith(("en-", "en_")) and any(
        tag in v for tag in ("Neural2", "Studio", "Journey", "Wavenet", "Standard")
    )


def _looks_like_edge_voice(v: str) -> bool:
    return isinstance(v, str) and v.startswith("en-") and v.endswith("Neural")


def resolve_voice(voice: str) -> dict:
    """Resolve any voice identifier to {elevenlabs, google, edge, name, gender}.

    ElevenLabs is the primary, highest-quality source; google/edge are
    gender-matched fallbacks. Accepts ElevenLabs ids, friendly names, and
    legacy Google/edge voice ids so nothing stored before this change breaks.
    """
    v = voice or DEFAULT_VOICE
    entry = (
        _VOICE_BY_EL.get(v)
        or _VOICE_BY_NAME.get(str(v).lower())
        or _VOICE_BY_GOOGLE.get(v)
        or _VOICE_BY_EDGE.get(v)
    )
    if entry:
        return {"elevenlabs": entry["id"], "google": entry["google"],
                "edge": entry["edge"], "name": entry["name"], "gender": entry["gender"]}

    # Unknown/legacy id — preserve gender where we can, else use a neutral narrator.
    gender = _LEGACY_VOICE_GENDER.get(v)
    base = _VOICE_BY_NAME["rachel"] if gender == "Female" else _VOICE_BY_NAME["adam"]
    return {
        "elevenlabs": base["id"],
        "google": v if _looks_like_google_voice(v) else base["google"],
        "edge":   v if _looks_like_edge_voice(v)   else base["edge"],
        "name": base["name"],
        "gender": gender or base["gender"],
    }

# SMTP (for email notifications — all optional, silently skipped if not set)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@socialoptimize.online")

TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.getenv("TWILIO_FROM_NUMBER", "")

# Google Cloud TTS voice (Studio > Journey > Neural2 quality order)
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "en-US-Studio-O")
GOOGLE_TTS_VOICES = VOICE_CATALOG  # back-compat alias — single source of truth

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

