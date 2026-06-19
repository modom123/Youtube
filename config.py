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

# YouTube
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8080")
YOUTUBE_TOKEN_FILE = BASE_DIR / "youtube_token.json"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

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
AI_VIDEO_PROVIDERS = ["none", "higgsfield", "google_flow", "both"]

HIGGSFIELD_MODELS = {
    "kling-v2":    "Kling v2 (Best quality)",
    "kling-v1.6":  "Kling v1.6 (Faster)",
    "wan-t2v":     "Wan T2V (Open source)",
    "hunyuan-t2v": "HunyuanVideo (Tencent)",
    "mochi":       "Mochi (Genmo)",
    "luma-dream":  "Luma Dream Machine",
}

