"""
Hermes Auto Agent — fully autonomous ENV collector
====================================================
Uses browser-use (AI-powered browser automation) to log into each portal,
navigate to API keys, extract values, and push them to Render.

Install:
    pip install browser-use langchain-anthropic requests python-dotenv
    playwright install chromium

Run:
    set ANTHROPIC_API_KEY=sk-ant-...
    set RENDER_API_KEY=rnd_...
    set RENDER_SERVICE_ID=srv-...
    python hermes_auto.py
"""

from __future__ import annotations
import asyncio
import json
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
RENDER_API_KEY     = os.getenv("RENDER_API_KEY", "")
RENDER_SERVICE_ID  = os.getenv("RENDER_SERVICE_ID", "")

PROGRESS_FILE = Path("hermes_progress.json")

# Pre-filled — no need to fetch these
KNOWN_VALUES = {
    "APP_BASE_URL":         "https://socialoptimize.online",
    "DATA_DIR":             "/data",
    "STRIPE_PRICE_STARTER": "to_1TlkYi7KDACoEjUuan10vFS5",
    "YOUTUBE_REDIRECT_URI": "https://socialoptimize.online/oauth/youtube/callback",
    "TWITTER_REDIRECT_URI": "https://socialoptimize.online/oauth/twitter/callback",
    "THREADS_REDIRECT_URI": "https://socialoptimize.online/oauth/threads/callback",
    "TWITCH_REDIRECT_URI":  "https://socialoptimize.online/oauth/twitch/callback",
    "SNAP_REDIRECT_URI":    "https://socialoptimize.online/oauth/snapchat/callback",
    "SMTP_HOST":            "smtp.gmail.com",
    "SMTP_PORT":            "587",
}

# ── Credentials the agent needs to log in ────────────────────────────────────
# Fill these in once — the agent will use them to log into each portal.
CREDENTIALS = {
    "anthropic_email":    os.getenv("CRED_ANTHROPIC_EMAIL", ""),
    "anthropic_password": os.getenv("CRED_ANTHROPIC_PASSWORD", ""),

    "stripe_email":       os.getenv("CRED_STRIPE_EMAIL", ""),
    "stripe_password":    os.getenv("CRED_STRIPE_PASSWORD", ""),

    "google_email":       os.getenv("CRED_GOOGLE_EMAIL", "nwtcinvestment@gmail.com"),
    "google_password":    os.getenv("CRED_GOOGLE_PASSWORD", ""),

    "tiktok_email":       os.getenv("CRED_TIKTOK_EMAIL", ""),
    "tiktok_password":    os.getenv("CRED_TIKTOK_PASSWORD", ""),

    "meta_email":         os.getenv("CRED_META_EMAIL", ""),
    "meta_password":      os.getenv("CRED_META_PASSWORD", ""),

    "linkedin_email":     os.getenv("CRED_LINKEDIN_EMAIL", ""),
    "linkedin_password":  os.getenv("CRED_LINKEDIN_PASSWORD", ""),

    "twitter_email":      os.getenv("CRED_TWITTER_EMAIL", ""),
    "twitter_password":   os.getenv("CRED_TWITTER_PASSWORD", ""),

    "twitch_email":       os.getenv("CRED_TWITCH_EMAIL", ""),
    "twitch_password":    os.getenv("CRED_TWITCH_PASSWORD", ""),

    "snapchat_email":     os.getenv("CRED_SNAPCHAT_EMAIL", ""),
    "snapchat_password":  os.getenv("CRED_SNAPCHAT_PASSWORD", ""),

    "twilio_email":       os.getenv("CRED_TWILIO_EMAIL", ""),
    "twilio_password":    os.getenv("CRED_TWILIO_PASSWORD", ""),

    "pexels_email":       os.getenv("CRED_PEXELS_EMAIL", ""),
    "pexels_password":    os.getenv("CRED_PEXELS_PASSWORD", ""),

    "higgsfield_email":   os.getenv("CRED_HIGGSFIELD_EMAIL", ""),
    "higgsfield_password":os.getenv("CRED_HIGGSFIELD_PASSWORD", ""),
}

# ── Tasks: one per ENV var ────────────────────────────────────────────────────
TASKS = [
    {
        "key": "ANTHROPIC_API_KEY",
        "task": f"""
Go to https://console.anthropic.com.
Log in with email '{CREDENTIALS['anthropic_email']}' and password '{CREDENTIALS['anthropic_password']}'.
Navigate to Settings > API Keys.
Create a new API key named 'Social Optimize'.
Copy the full API key value (starts with sk-ant-).
Return ONLY the key value, nothing else.
"""
    },
    {
        "key": "STRIPE_SECRET_KEY",
        "task": f"""
Go to https://dashboard.stripe.com/login.
Log in with email '{CREDENTIALS['stripe_email']}' and password '{CREDENTIALS['stripe_password']}'.
Navigate to Developers > API Keys.
Click 'Reveal live key' for the Secret key.
Return ONLY the secret key value (starts with sk_live_), nothing else.
"""
    },
    {
        "key": "STRIPE_PUBLISHABLE_KEY",
        "task": f"""
Go to https://dashboard.stripe.com/apikeys (you may already be logged in).
Find the Publishable key (starts with pk_live_).
Return ONLY the publishable key value, nothing else.
"""
    },
    {
        "key": "STRIPE_WEBHOOK_SECRET",
        "task": f"""
Go to https://dashboard.stripe.com/webhooks.
Click the webhook endpoint for https://socialoptimize.online/billing/webhook.
Click 'Reveal' next to Signing secret.
Return ONLY the signing secret value (starts with whsec_), nothing else.
"""
    },
    {
        "key": "STRIPE_PRICE_CREATOR",
        "task": f"""
Go to https://dashboard.stripe.com/products.
Find the product named 'Creator'.
Click on it, find the monthly Price ID (starts with price_).
Return ONLY that price ID, nothing else.
"""
    },
    {
        "key": "STRIPE_PRICE_AGENCY",
        "task": f"""
Go to https://dashboard.stripe.com/products.
Find the product named 'Agency'.
Click on it, find the monthly Price ID (starts with price_).
Return ONLY that price ID, nothing else.
"""
    },
    {
        "key": "PEXELS_API_KEY",
        "task": f"""
Go to https://www.pexels.com/api/.
Log in with email '{CREDENTIALS['pexels_email']}' and password '{CREDENTIALS['pexels_password']}'.
Find your API key on the page.
Return ONLY the API key value, nothing else.
"""
    },
    {
        "key": "HIGGSFIELD_MCP_TOKEN",
        "task": f"""
Go to https://app.higgsfield.ai.
Log in with email '{CREDENTIALS['higgsfield_email']}' and password '{CREDENTIALS['higgsfield_password']}'.
Navigate to Settings or API section.
Find the API token or MCP token.
Return ONLY the token value, nothing else.
"""
    },
    {
        "key": "YOUTUBE_CLIENT_ID",
        "task": f"""
Go to https://console.cloud.google.com/apis/credentials.
Log in with Google account '{CREDENTIALS['google_email']}' and password '{CREDENTIALS['google_password']}'.
Find the OAuth 2.0 Client ID for the Social Optimize app (or the first one listed).
Click on it to open details.
Return ONLY the Client ID value (ends in .apps.googleusercontent.com), nothing else.
"""
    },
    {
        "key": "YOUTUBE_CLIENT_SECRET",
        "task": f"""
On the same Google Cloud credentials page (https://console.cloud.google.com/apis/credentials),
click the same OAuth 2.0 Client.
Return ONLY the Client Secret value (starts with GOCSPX-), nothing else.
"""
    },
    {
        "key": "GOOGLE_API_KEY",
        "task": f"""
On https://console.cloud.google.com/apis/credentials,
find an API Key in the API Keys section.
Return ONLY the key value (starts with AIza), nothing else.
"""
    },
    {
        "key": "TIKTOK_CLIENT_KEY",
        "task": f"""
Go to https://developers.tiktok.com/apps/.
Log in with email '{CREDENTIALS['tiktok_email']}' and password '{CREDENTIALS['tiktok_password']}'.
Click on the Social Optimize app (or first app listed).
Find the Client Key.
Return ONLY the Client Key value, nothing else.
"""
    },
    {
        "key": "TIKTOK_CLIENT_SECRET",
        "task": f"""
On the same TikTok developer app page,
find the Client Secret (reveal it if needed).
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "FACEBOOK_APP_ID",
        "task": f"""
Go to https://developers.facebook.com/apps/.
Log in with email '{CREDENTIALS['meta_email']}' and password '{CREDENTIALS['meta_password']}'.
Click on the Social Optimize app.
Go to Settings > Basic.
Return ONLY the App ID value, nothing else.
"""
    },
    {
        "key": "FACEBOOK_APP_SECRET",
        "task": f"""
On the same Facebook app Settings > Basic page,
click Show next to App Secret.
Return ONLY the App Secret value, nothing else.
"""
    },
    {
        "key": "THREADS_APP_ID",
        "task": f"""
On https://developers.facebook.com/apps/,
check if there is a separate Threads app. If yes, click it and return its App ID.
If no separate app, return the same value as FACEBOOK_APP_ID.
Return ONLY the App ID value, nothing else.
"""
    },
    {
        "key": "THREADS_APP_SECRET",
        "task": f"""
Same as above — return the App Secret for the Threads app.
If using the same Facebook app, return that same App Secret.
Return ONLY the value, nothing else.
"""
    },
    {
        "key": "LINKEDIN_CLIENT_ID",
        "task": f"""
Go to https://www.linkedin.com/developers/apps/.
Log in with email '{CREDENTIALS['linkedin_email']}' and password '{CREDENTIALS['linkedin_password']}'.
Click on the Social Optimize app.
Go to the Auth tab.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "LINKEDIN_CLIENT_SECRET",
        "task": f"""
On the same LinkedIn app Auth tab,
find the Primary Client Secret.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "TWITTER_CLIENT_ID",
        "task": f"""
Go to https://developer.twitter.com/en/portal/projects-and-apps.
Log in with email '{CREDENTIALS['twitter_email']}' and password '{CREDENTIALS['twitter_password']}'.
Click on your app > Keys and Tokens.
Find OAuth 2.0 Client ID and Client Secret section.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "TWITTER_CLIENT_SECRET",
        "task": f"""
On the same Twitter app Keys and Tokens page,
find the OAuth 2.0 Client Secret (regenerate if needed).
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "TWITCH_CLIENT_ID",
        "task": f"""
Go to https://dev.twitch.tv/console/apps.
Log in with email '{CREDENTIALS['twitch_email']}' and password '{CREDENTIALS['twitch_password']}'.
Click on the Social Optimize app.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "TWITCH_CLIENT_SECRET",
        "task": f"""
On the same Twitch app page,
click 'New Secret' if no secret exists, then copy it.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "SNAP_CLIENT_ID",
        "task": f"""
Go to https://kit.snapchat.com/manage.
Log in with email '{CREDENTIALS['snapchat_email']}' and password '{CREDENTIALS['snapchat_password']}'.
Click on the Social Optimize app > Credentials.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "SNAP_CLIENT_SECRET",
        "task": f"""
On the same Snapchat app Credentials page,
find the Client Secret.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "TWILIO_ACCOUNT_SID",
        "task": f"""
Go to https://console.twilio.com.
Log in with email '{CREDENTIALS['twilio_email']}' and password '{CREDENTIALS['twilio_password']}'.
Find the Account SID on the dashboard home page.
Return ONLY the Account SID value (starts with AC), nothing else.
"""
    },
    {
        "key": "TWILIO_AUTH_TOKEN",
        "task": f"""
On the Twilio console home page,
click Show/Reveal next to Auth Token.
Return ONLY the Auth Token value, nothing else.
"""
    },
    {
        "key": "TWILIO_FROM_NUMBER",
        "task": f"""
Go to https://console.twilio.com/us1/develop/phone-numbers/manage/active.
Find the active phone number.
Return ONLY the phone number in E.164 format (e.g. +12025551234), nothing else.
"""
    },
    {
        "key": "SMTP_PASS",
        "task": f"""
Go to https://myaccount.google.com/apppasswords.
Log in with Google account '{CREDENTIALS['google_email']}' and password '{CREDENTIALS['google_password']}'.
Create a new App Password: App = Mail, Device = Social Optimize.
Return ONLY the 16-character app password (no spaces), nothing else.
"""
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# RENDER PUSH
# ─────────────────────────────────────────────────────────────────────────────

def push_to_render(env_vars: dict):
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print("\n[!] Set RENDER_API_KEY and RENDER_SERVICE_ID env vars.")
        save_dotenv(env_vars)
        return
    print(f"\n[→] Pushing {len(env_vars)} env vars to Render...")
    headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"}
    payload = [{"key": k, "value": v} for k, v in env_vars.items()]
    resp = requests.put(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars",
        headers=headers, json=payload, timeout=30,
    )
    if resp.status_code in (200, 201):
        print(f"[✓] {len(env_vars)} env vars pushed to Render!")
    else:
        print(f"[✗] Render error {resp.status_code}: {resp.text}")
        save_dotenv(env_vars)


def save_dotenv(env_vars: dict):
    out = Path("env.render")
    out.write_text("\n".join(f"{k}={v}" for k, v in env_vars.items()))
    print(f"[✓] Saved to {out.resolve()}")


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {}


def save_progress(data: dict):
    PROGRESS_FILE.write_text(json.dumps(data, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def run():
    try:
        from browser_use import Agent
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        print("Missing dependencies. Run:")
        print("  pip install browser-use langchain-anthropic")
        return

    if not ANTHROPIC_API_KEY:
        print("[!] Set ANTHROPIC_API_KEY env var first.")
        return

    llm = ChatAnthropic(
        model="claude-opus-4-8",
        api_key=ANTHROPIC_API_KEY,
    )

    collected = load_progress()
    # Seed known values
    for k, v in KNOWN_VALUES.items():
        collected.setdefault(k, v)
    # Seed SMTP_USER
    collected.setdefault("SMTP_USER", CREDENTIALS["google_email"])

    print("=" * 60)
    print("  HERMES AUTO AGENT — Social Optimize")
    print(f"  {len([t for t in TASKS if not collected.get(t['key'])])} tasks remaining")
    print("=" * 60)

    for task_def in TASKS:
        key = task_def["key"]

        if collected.get(key):
            print(f"\n[✓] {key} — already collected, skipping.")
            continue

        print(f"\n[→] Fetching {key}...")

        try:
            agent = Agent(task=task_def["task"].strip(), llm=llm)
            result = await agent.run()
            # browser-use returns the final answer as a string
            value = str(result).strip().split("\n")[0].strip()

            if value and len(value) > 3:
                collected[key] = value
                save_progress(collected)
                print(f"  [✓] {key} = {value[:8]}{'*' * max(0, len(value)-8)}")
            else:
                print(f"  [!] Agent returned empty value for {key}, skipping.")
        except Exception as e:
            print(f"  [✗] Error fetching {key}: {e}")

    # Summary
    filled   = {k: v for k, v in collected.items() if v}
    missing  = [t["key"] for t in TASKS if not collected.get(t["key"])]

    print(f"\n{'='*60}")
    print(f"  Done — {len(filled)} collected, {len(missing)} missing")
    if missing:
        print(f"  Missing: {', '.join(missing)}")
    print(f"{'='*60}")

    push_to_render(filled)


if __name__ == "__main__":
    asyncio.run(run())
