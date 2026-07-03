import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://socialoptimize.online")

# ── Public media hosting (Instagram/Threads need a public video URL) ──────────
# Optional S3-compatible storage (AWS S3, Cloudflare R2, Backblaze B2).
# When unset, the app serves media itself at signed URLs under APP_BASE_URL.
S3_BUCKET             = os.getenv("S3_BUCKET", "")
S3_ACCESS_KEY_ID      = os.getenv("S3_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY_ID", ""))
S3_SECRET_ACCESS_KEY  = os.getenv("S3_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
S3_REGION             = os.getenv("S3_REGION", "auto")
S3_ENDPOINT_URL       = os.getenv("S3_ENDPOINT_URL", "")      # e.g. R2 account endpoint
S3_PUBLIC_BASE_URL    = os.getenv("S3_PUBLIC_BASE_URL", "")   # CDN / public bucket base
MEDIA_PUBLIC_BASE_URL = os.getenv("MEDIA_PUBLIC_BASE_URL", APP_BASE_URL)

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
WHOP_PLAN_FREE        = os.getenv("WHOP_PLAN_FREE", "")
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
        "description": "Get started for free — no credit card, no commitment. 3 AI videos per month with 50 credits.",
        "price_monthly": 0,
        "trial_days": 0,
        "videos_per_month": 3,
        "higgsfield_credits": 50,
        "stripe_price_id": None,
        "whop_plan_id": WHOP_PLAN_FREE,
        "features": [
            "3 AI videos/month",
            "50 Social Optimize Credits",
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
        "higgsfield_credits": 100,
        "stripe_price_id": STRIPE_PRICE_STARTER,
        "whop_plan_id": WHOP_PLAN_STARTER,
        "features": [
            "7-day free trial",
            "7 AI videos/month",
            "Publish to 5 platforms",
            "100 Social Optimize Credits/mo",
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
        "description": "Built for entrepreneurs and small businesses. 7-day free trial, then $29.99/mo.",
        "price_monthly": 29.99,
        "trial_days": 7,
        "videos_per_month": 15,
        "higgsfield_credits": 210,
        "stripe_price_id": STRIPE_PRICE_CREATOR,
        "whop_plan_id": WHOP_PLAN_CREATOR,
        "features": [
            "7-day free trial",
            "15 AI videos/month",
            "Publish to 8 platforms",
            "210 Social Optimize Credits/mo",
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
        "description": "The full creative suite for serious creators. 7-day free trial, then $79.99/mo.",
        "price_monthly": 79.99,
        "trial_days": 7,
        "videos_per_month": 50,
        "higgsfield_credits": 700,
        "stripe_price_id": STRIPE_PRICE_PRO,
        "whop_plan_id": WHOP_PLAN_PRO,
        "features": [
            "7-day free trial",
            "50 AI videos/month",
            "Publish to all 8 platforms",
            "700 Social Optimize Credits/mo",
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
        "description": "Scale your content operation. 7-day free trial, then $199.99/mo.",
        "price_monthly": 199.99,
        "trial_days": 7,
        "videos_per_month": 125,
        "higgsfield_credits": 1750,
        "stripe_price_id": STRIPE_PRICE_AGENCY,
        "whop_plan_id": WHOP_PLAN_AGENCY,
        "features": [
            "7-day free trial",
            "125 AI videos/month",
            "Publish to all 8 platforms",
            "1,750 Social Optimize Credits/mo",
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

# ── Real vendor cost basis (for unit economics / credit pricing) ────────────
# Sourced from public vendor pricing pages, checked 2026-07. These feed
# agents/sterling_business.py's cost-center audit and the credit-pricing
# formula — update here if vendor pricing or your plan tier changes.

# Anthropic Claude API — $ per million tokens (input, output).
# Source: https://platform.claude.com/docs/en/about-claude/pricing
ANTHROPIC_COST_PER_M_TOKENS = {
    "haiku":  {"input": 1.0, "output": 5.0},   # claude-haiku-4-5
    "sonnet": {"input": 3.0, "output": 15.0},  # claude-sonnet-4-6
}

# Higgsfield credits — real account data (checked via balance/transactions):
# Starter plan grants 270 credits for $15/mo -> $0.0556/credit base rate.
# Overage top-ups run $0.10-0.15/credit per https://higgsfield.ai/pricing —
# using the midpoint. Update HIGGSFIELD_COST_PER_CREDIT_BASE if you change
# Higgsfield plans.
HIGGSFIELD_COST_PER_CREDIT_BASE  = float(os.getenv("HIGGSFIELD_COST_PER_CREDIT_BASE", "0.0556"))
HIGGSFIELD_COST_PER_CREDIT_TOPUP = float(os.getenv("HIGGSFIELD_COST_PER_CREDIT_TOPUP", "0.125"))
HIGGSFIELD_MONTHLY_BASE_CREDITS  = float(os.getenv("HIGGSFIELD_MONTHLY_BASE_CREDITS", "270"))

# ElevenLabs TTS — $ per 1,000 characters. Flash/Turbo models (cheaper, used
# for short-form narration) run ~$0.05/1k chars vs $0.10 for Multilingual v2.
# Source: https://elevenlabs.io/pricing/api
ELEVENLABS_COST_PER_1K_CHARS = float(os.getenv("ELEVENLABS_COST_PER_1K_CHARS", "0.05"))

# Google Cloud APIs — checked 2026-07 via cloud.google.com/{vision,translate,natural-language}/pricing
GOOGLE_VISION_COST_PER_IMAGE      = 0.0015   # label detection, after 1,000/mo free tier
GOOGLE_TRANSLATE_COST_PER_1K_CHARS = 0.02    # Basic/Advanced NMT, $20/M chars, after 500k/mo free
GOOGLE_NLP_COST_PER_1K_UNITS      = 0.001    # entity/sentiment analysis, after 5,000/mo free

# Infrastructure — actual billed plan cost per month.
# Source: https://render.com/pricing (Standard tier) / https://supabase.com/pricing (Pro tier)
RENDER_MONTHLY_COST   = float(os.getenv("RENDER_MONTHLY_COST", "25"))
SUPABASE_MONTHLY_COST = float(os.getenv("SUPABASE_MONTHLY_COST", "25"))

# Stripe processing fees — standard US online card rate.
# Source: https://stripe.com/pricing
STRIPE_PCT_FEE  = 0.029
STRIPE_FLAT_FEE = 0.30

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

# Google Cloud Storage — used ONLY as a scratch pad for audio files that
# exceed Speech-to-Text's ~10MB inline-content limit (a real podcast episode
# at 16kHz mono routinely does: that ceiling is only ~5 minutes of audio).
# Requires a SEPARATE credential from GOOGLE_API_KEY: GCS write access needs
# a service account (API keys can't authorize bucket writes), created in
# Google Cloud Console > IAM & Admin > Service Accounts, granted the
# "Storage Object Admin" role on the target bucket, with a JSON key
# generated and pasted whole (including newlines) into
# GOOGLE_SERVICE_ACCOUNT_JSON. Leave GCS_BUCKET_NAME unset to keep this
# disabled — long-episode transcription will just raise a clear error
# instead of silently truncating.
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Anthropic Admin API — a SEPARATE key from ANTHROPIC_API_KEY, generated in
# the Anthropic Console under Settings > Admin API Keys (requires an org
# admin role). The regular API key used for actual Claude calls has no way
# to check its own spend — only the Admin API's cost report can. Anthropic
# is pay-as-you-go with no fixed monthly credit cap, so monitoring needs a
# budget number you set yourself; leave ANTHROPIC_MONTHLY_BUDGET at 0 to
# keep this disabled until you've set both.
ANTHROPIC_ADMIN_KEY = os.getenv("ANTHROPIC_ADMIN_KEY", "")
ANTHROPIC_MONTHLY_BUDGET = float(os.getenv("ANTHROPIC_MONTHLY_BUDGET", "0"))

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

# Gamma — slide-deck generation for ranking/listicle-style videos and other
# presentation output. Real REST API, not the MCP tool (that's only
# available to this chat session, not the deployed server).
# Source: https://developers.gamma.app/ — base https://public-api.gamma.app/v1.0
GAMMA_API_KEY = os.getenv("GAMMA_API_KEY", "")
GAMMA_API_BASE = "https://public-api.gamma.app/v1.0"

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
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "en-US-Journey-D")
VIDEO_WIDTH = int(os.getenv("DEFAULT_VIDEO_WIDTH", "1280"))
VIDEO_HEIGHT = int(os.getenv("DEFAULT_VIDEO_HEIGHT", "720"))
SHORT_WIDTH = int(os.getenv("SHORT_VIDEO_WIDTH", "720"))
SHORT_HEIGHT = int(os.getenv("SHORT_VIDEO_HEIGHT", "1280"))

# Content limits (seconds)
SHORTS_MAX_DURATION = 60
LONG_VIDEO_MIN_DURATION = 180
PODCAST_MIN_DURATION = 300

# Canonical studio/tool list -- single source of truth for anything that
# needs to enumerate "what studios exist" (currently /api/studios for the
# mobile app). Paths must match the real routes in app.py/templates/base.html
# exactly -- a studio listed here with a wrong path 404s for whoever calls it.
STUDIOS = [
    {"id": "create", "name": "Create", "icon": "🚀", "path": "/create",
     "desc": "Turn any topic into a complete, ready-to-post video.",
     "purpose": "The fastest way to turn any topic into a ready-to-post video — script, voiceover, visuals, and thumbnail generated automatically.",
     "how_to": [
        "Enter a topic.",
        "Pick a format (short/long/podcast/etc.), target platforms, and a voice.",
        "Click Generate — Social Optimize researches the topic, writes the script, records narration, sources visuals, and assembles the final video.",
        "Review the result and publish directly to connected platforms, or download it.",
     ]},
    {"id": "studio", "name": "The Forge", "icon": "🏭", "path": "/studio",
     "desc": "Premium YouTube video production, niche-driven.",
     "purpose": "Autonomous daily content production for a niche — for creators who want a steady stream of videos without manually starting each one.",
     "how_to": [
        "Enter your niche or channel focus.",
        "Set a target duration and budget.",
        "Click Run — five specialized AI agents handle trend research, scripting, asset planning, cost optimization, and SEO.",
        "Review the finished video and publish.",
     ]},
    {"id": "hollywood", "name": "Cinema House", "icon": "🎬", "path": "/hollywood",
     "desc": "Documentary-grade cinematic storytelling.",
     "purpose": "Premium, documentary-grade cinematic videos that mix real stock footage with AI-generated cinematic shots — built for storytelling, not quick turnarounds.",
     "how_to": [
        "Enter your topic or story.",
        "Choose duration and target audience.",
        "Generate — the Cinematic Director, Screenwriter, and Asset Curator agents plan and build a shot-by-shot production.",
        "Review the finished film, including an AI-generated thumbnail.",
     ]},
    {"id": "music", "name": "Hit Factory", "icon": "🎵", "path": "/music-studio",
     "desc": "Beats and songs that sound radio-ready.",
     "purpose": "Generate original background music, beats, or full songs with lyrics for your videos — no royalty-free library needed.",
     "how_to": [
        "Set genre, mood, tempo, and vocal style.",
        "Optionally write your own lyrics, or let AI write them.",
        "Generate — Social Optimize composes the music and can layer AI vocals on top.",
        "Download the track, or use it as background music in Editing Room.",
     ]},
    {"id": "podcast", "name": "Podcast Studio", "icon": "🎙️", "path": "/podcast-studio",
     "desc": "Record, edit, and publish podcast episodes.",
     "purpose": "Turn a topic into a full podcast episode with narration and an audiogram video, or upload your own recorded audio for show notes and a matching video.",
     "how_to": [
        "Choose 'Generate from topic' or 'Upload audio'.",
        "Set the show name, episode number, and guest info if relevant.",
        "Generate — get a scripted episode with narration and chapters, or an audiogram plus transcript for uploaded audio.",
        "Publish or schedule the episode to your platforms.",
     ]},
    {"id": "commercial", "name": "Ad Lab", "icon": "📺", "path": "/commercial",
     "desc": "Scroll-stopping product ads from a photo or clip.",
     "purpose": "Turn a product photo or clip into a scroll-stopping commercial — ad copy, script, voiceover, and video, ready to run.",
     "how_to": [
        "Upload a product photo or video.",
        "Enter the brand name, description, and target audience.",
        "Generate — Claude Vision analyzes your product, writes ad copy in five proven frameworks, and produces a finished commercial.",
        "Review the hooks/CTAs and publish, or broadcast directly to YouTube/Twitch.",
     ]},
    {"id": "clipper", "name": "Clipper", "icon": "✂️", "path": "/clipper",
     "desc": "Turn a long video into viral short clips.",
     "purpose": "Turn one long video into several short, captioned, vertical clips optimized for virality.",
     "how_to": [
        "Upload a video, paste a URL, or pick an existing job.",
        "Set how many clips you want and how long each should be.",
        "Generate — AI identifies the most engaging moments (or falls back to scene detection), then extracts, reframes, and captions each clip.",
        "Download clips individually or as a zip.",
     ]},
    {"id": "editing-room", "name": "Editing Room", "icon": "🎞️", "path": "/editing-room",
     "desc": "Assemble a polished video from your own footage.",
     "purpose": "Assemble a polished video from your own script and media — cinematic titles, lower-thirds, Ken Burns motion, and background music, without a full AI generation pipeline.",
     "how_to": [
        "Pick a studio look (Cinema House / The Forge / Ad Lab style).",
        "Write your section headings and narration, or remix an existing job.",
        "Upload your own clips/images per section, or let AI generate them.",
        "Produce — get a fully assembled, narrated video.",
     ]},
    {"id": "ranking", "name": "Ranking Studio", "icon": "🏆", "path": "/ranking-studio",
     "desc": "Top N / listicle videos via Gamma slide decks.",
     "purpose": "Turn any 'Top N' idea into a narrated countdown video with a real designed slide deck.",
     "how_to": [
        "Enter your topic and how many items to rank.",
        "Generate — Claude writes the ranked list, Gamma designs matching slides, and each slide gets its own narration.",
        "Review the finished countdown video.",
     ]},
    {"id": "batch", "name": "Batch", "icon": "📦", "path": "/batch",
     "desc": "Generate multiple videos from a topic list at once.",
     "purpose": "Generate multiple videos from a list of topics in one run — for filling out a week's worth of content at once.",
     "how_to": [
        "Add a list of topics.",
        "Set the shared format, platforms, and voice for all of them.",
        "Run — each topic goes through the full Create pipeline one after another.",
        "Review each finished video in your Jobs list.",
     ]},
    {"id": "quickpost", "name": "QuickPost", "icon": "⚡", "path": "/quickpost",
     "desc": "Turn a photo or clip into ready-to-post captions.",
     "purpose": "The fastest way to post a photo or clip you already have — AI writes platform-specific captions instantly.",
     "how_to": [
        "Upload a photo or short video.",
        "Pick your tone and which platforms you're posting to.",
        "Generate — get a tailored caption, hashtags, and a best-time-to-post suggestion for each platform.",
        "Copy the caption or publish directly.",
     ]},
]

# Single canonical voice catalog used across every studio (Create, Studio,
# Hollywood, Ad Lab, Batch, Settings). 10 distinct, highest-quality Google
# Neural2/Studio/Journey voices — 6 female, 4 male — each with a real edge-tts
# fallback of the SAME gender so a user's choice never silently flips gender
# when Google/ElevenLabs TTS is unavailable.
VOICE_CATALOG = [
    {"id": "en-US-Studio-O",  "name": "Aria",   "gender": "Female", "style": "Warm & Professional",   "locale": "en-US", "edge": "en-US-AriaNeural"},
    {"id": "en-US-Journey-F", "name": "Luna",    "gender": "Female", "style": "Conversational & Natural", "locale": "en-US", "edge": "en-US-JennyNeural"},
    {"id": "en-US-Neural2-C", "name": "Maya",    "gender": "Female", "style": "Clear & Confident",     "locale": "en-US", "edge": "en-US-JennyNeural"},
    {"id": "en-US-Neural2-F", "name": "Sophia",  "gender": "Female", "style": "Friendly & Upbeat",      "locale": "en-US", "edge": "en-US-AriaNeural"},
    {"id": "en-US-Neural2-G", "name": "Grace",   "gender": "Female", "style": "Calm & Soothing",        "locale": "en-US", "edge": "en-US-JennyNeural"},
    {"id": "en-US-Neural2-H", "name": "Nova",    "gender": "Female", "style": "Energetic & Bright",     "locale": "en-US", "edge": "en-US-AriaNeural"},
    {"id": "en-US-Studio-Q",  "name": "Marcus",  "gender": "Male",   "style": "Deep & Authoritative",   "locale": "en-US", "edge": "en-US-GuyNeural"},
    {"id": "en-US-Journey-D", "name": "Derek",   "gender": "Male",   "style": "Conversational & Natural", "locale": "en-US", "edge": "en-US-DavisNeural"},
    {"id": "en-US-Neural2-A", "name": "Atlas",   "gender": "Male",   "style": "Warm & Trustworthy",     "locale": "en-US", "edge": "en-US-GuyNeural"},
    {"id": "en-US-Neural2-I", "name": "Jaxon",   "gender": "Male",   "style": "Bold & Energetic",       "locale": "en-US", "edge": "en-US-DavisNeural"},
]
for _v in VOICE_CATALOG:
    _v["label"] = f"{_v['name']} — {_v['style']} ({_v['gender']})"
del _v

# Back-compat aliases — both now point at the same single catalog.
AVAILABLE_VOICES = [v["id"] for v in VOICE_CATALOG]

# SMTP (for email notifications — all optional, silently skipped if not set)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@socialoptimize.online")
CONTACT_NOTIFY_EMAIL = os.getenv("CONTACT_NOTIFY_EMAIL", "") or SMTP_USER

TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.getenv("TWILIO_FROM_NUMBER", "")

# Google Cloud TTS voice (Studio > Journey > Neural2 quality order)
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "en-US-Journey-D")
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

