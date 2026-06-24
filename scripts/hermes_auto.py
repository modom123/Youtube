"""
Hermes Auto Agent — fully autonomous ENV collector
====================================================
Connects to your EXISTING open Chrome browser (no new login needed).
Navigates to each portal tab, extracts API keys, pushes to Render.

STEP 1 — Launch Chrome with remote debugging (close Chrome first, then run):

  Windows:
    "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug

  Mac:
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

STEP 2 — Log into every portal in that Chrome window (Anthropic, Stripe,
         Google Cloud, TikTok, Meta, LinkedIn, Twitter, Twitch, Snapchat,
         Twilio, Pexels, Higgsfield). Just log in — don't close the tabs.

STEP 3 — Set env vars and run:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    $env:RENDER_API_KEY    = "rnd_..."
    $env:RENDER_SERVICE_ID = "srv-..."
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
CDP_URL            = os.getenv("CDP_URL", "http://localhost:9222")

PROGRESS_FILE = Path("hermes_progress.json")

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
    "SMTP_USER":            "nwtcinvestment@gmail.com",
}

TASKS = [
    {
        "key": "ANTHROPIC_API_KEY",
        "task": """
Go to https://console.anthropic.com/settings/keys.
If there is already a key named 'Social Optimize', copy its value.
Otherwise click 'Create Key', name it 'Social Optimize', then copy the full key value (starts with sk-ant-).
Return ONLY the key value, nothing else.
"""
    },
    {
        "key": "STRIPE_SECRET_KEY",
        "task": """
Go to https://dashboard.stripe.com/apikeys.
Click 'Reveal live key' for the Secret key.
Return ONLY the secret key value (starts with sk_live_), nothing else.
"""
    },
    {
        "key": "STRIPE_PUBLISHABLE_KEY",
        "task": """
Go to https://dashboard.stripe.com/apikeys.
Copy the Publishable key — it is visible without revealing (starts with pk_live_).
Return ONLY the publishable key value, nothing else.
"""
    },
    {
        "key": "STRIPE_WEBHOOK_SECRET",
        "task": """
Go to https://dashboard.stripe.com/webhooks.
Click the webhook endpoint for https://socialoptimize.online/billing/webhook.
Click 'Reveal' next to Signing secret.
Return ONLY the signing secret value (starts with whsec_), nothing else.
"""
    },
    {
        "key": "STRIPE_PRICE_CREATOR",
        "task": """
Go to https://dashboard.stripe.com/products.
Find the product named 'Creator'. Click on it.
Find the monthly Price ID (starts with price_).
Return ONLY that price ID, nothing else.
"""
    },
    {
        "key": "STRIPE_PRICE_AGENCY",
        "task": """
Go to https://dashboard.stripe.com/products.
Find the product named 'Agency'. Click on it.
Find the monthly Price ID (starts with price_).
Return ONLY that price ID, nothing else.
"""
    },
    {
        "key": "YOUTUBE_CLIENT_ID",
        "task": """
Go to https://console.cloud.google.com/apis/credentials.
Find the OAuth 2.0 Client ID for the Social Optimize app (or the first one listed).
Click on it to open details.
Return ONLY the Client ID value (ends in .apps.googleusercontent.com), nothing else.
"""
    },
    {
        "key": "YOUTUBE_CLIENT_SECRET",
        "task": """
Go to https://console.cloud.google.com/apis/credentials.
Click the same OAuth 2.0 Client.
Return ONLY the Client Secret value (starts with GOCSPX-), nothing else.
"""
    },
    {
        "key": "GOOGLE_API_KEY",
        "task": """
Go to https://console.cloud.google.com/apis/credentials.
Find an API Key in the API Keys section.
Return ONLY the key value (starts with AIza), nothing else.
"""
    },
    {
        "key": "TIKTOK_CLIENT_KEY",
        "task": """
Go to https://developers.tiktok.com/apps/.
Click on the Social Optimize app (or first app listed).
Find the Client Key.
Return ONLY the Client Key value, nothing else.
"""
    },
    {
        "key": "TIKTOK_CLIENT_SECRET",
        "task": """
Go to https://developers.tiktok.com/apps/.
Click on the Social Optimize app.
Find and reveal the Client Secret.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "FACEBOOK_APP_ID",
        "task": """
Go to https://developers.facebook.com/apps/.
Click on the Social Optimize app. Go to Settings > Basic.
Return ONLY the App ID value, nothing else.
"""
    },
    {
        "key": "FACEBOOK_APP_SECRET",
        "task": """
Go to https://developers.facebook.com/apps/.
Click on the Social Optimize app. Go to Settings > Basic.
Click Show next to App Secret.
Return ONLY the App Secret value, nothing else.
"""
    },
    {
        "key": "THREADS_APP_ID",
        "task": """
Go to https://developers.facebook.com/apps/.
Check if there is a separate Threads app. If yes, click it and return its App ID.
If no separate Threads app exists, return the same App ID as the main Facebook/Social Optimize app.
Return ONLY the App ID value, nothing else.
"""
    },
    {
        "key": "THREADS_APP_SECRET",
        "task": """
Go to https://developers.facebook.com/apps/.
Check if there is a separate Threads app. If yes, click it, go to Settings > Basic, reveal App Secret.
If no separate Threads app exists, return the same App Secret as the main Facebook/Social Optimize app.
Return ONLY the App Secret value, nothing else.
"""
    },
    {
        "key": "LINKEDIN_CLIENT_ID",
        "task": """
Go to https://www.linkedin.com/developers/apps/.
Click on the Social Optimize app. Go to the Auth tab.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "LINKEDIN_CLIENT_SECRET",
        "task": """
Go to https://www.linkedin.com/developers/apps/.
Click on the Social Optimize app. Go to the Auth tab.
Find the Primary Client Secret.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "TWITTER_CLIENT_ID",
        "task": """
Go to https://developer.twitter.com/en/portal/projects-and-apps.
Click on your app > Keys and Tokens.
Find OAuth 2.0 Client ID and Client Secret section.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "TWITTER_CLIENT_SECRET",
        "task": """
Go to https://developer.twitter.com/en/portal/projects-and-apps.
Click on your app > Keys and Tokens.
Find the OAuth 2.0 Client Secret (regenerate if needed).
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "TWITCH_CLIENT_ID",
        "task": """
Go to https://dev.twitch.tv/console/apps.
Click on the Social Optimize app.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "TWITCH_CLIENT_SECRET",
        "task": """
Go to https://dev.twitch.tv/console/apps.
Click on the Social Optimize app.
Click 'New Secret' if no secret exists, then copy it.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "SNAP_CLIENT_ID",
        "task": """
Go to https://kit.snapchat.com/manage.
Click on the Social Optimize app > Credentials.
Return ONLY the Client ID value, nothing else.
"""
    },
    {
        "key": "SNAP_CLIENT_SECRET",
        "task": """
Go to https://kit.snapchat.com/manage.
Click on the Social Optimize app > Credentials.
Find the Client Secret.
Return ONLY the Client Secret value, nothing else.
"""
    },
    {
        "key": "TWILIO_ACCOUNT_SID",
        "task": """
Go to https://console.twilio.com.
Find the Account SID on the dashboard home page.
Return ONLY the Account SID value (starts with AC), nothing else.
"""
    },
    {
        "key": "TWILIO_AUTH_TOKEN",
        "task": """
Go to https://console.twilio.com.
Click Show/Reveal next to Auth Token.
Return ONLY the Auth Token value, nothing else.
"""
    },
    {
        "key": "TWILIO_FROM_NUMBER",
        "task": """
Go to https://console.twilio.com/us1/develop/phone-numbers/manage/active.
Find the active phone number.
Return ONLY the phone number in E.164 format (e.g. +12025551234), nothing else.
"""
    },
    {
        "key": "PEXELS_API_KEY",
        "task": """
Go to https://www.pexels.com/api/.
Find your API key on the page (you should already be logged in).
Return ONLY the API key value, nothing else.
"""
    },
    {
        "key": "HIGGSFIELD_MCP_TOKEN",
        "task": """
Go to https://app.higgsfield.ai/settings or the API/token section.
Find the API token or MCP token.
Return ONLY the token value, nothing else.
"""
    },
    {
        "key": "SMTP_PASS",
        "task": """
Go to https://myaccount.google.com/apppasswords.
Create a new App Password: App = Mail, Device = Social Optimize.
Return ONLY the 16-character app password (no spaces), nothing else.
"""
    },
]


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


def check_cdp():
    """Verify Chrome is running with remote debugging enabled."""
    try:
        resp = requests.get(f"{CDP_URL}/json/version", timeout=3)
        info = resp.json()
        print(f"[✓] Connected to Chrome: {info.get('Browser', 'unknown')}")
        return True
    except Exception:
        return False


async def run():
    try:
        from browser_use import Agent, Browser, BrowserConfig
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        print("Missing dependencies. Run:")
        print("  pip install browser-use langchain-anthropic")
        return

    if not ANTHROPIC_API_KEY:
        print("[!] Set ANTHROPIC_API_KEY env var first.")
        return

    # Check if Chrome is open with remote debugging
    if not check_cdp():
        print("\n[!] Chrome is not open with remote debugging.")
        print("\nClose Chrome completely, then run this command to reopen it:")
        print()
        print('  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\\ChromeDebug')
        print()
        print("Then log into all your portals in that Chrome window, and re-run this script.")
        return

    llm = ChatAnthropic(
        model="claude-opus-4-8",
        api_key=ANTHROPIC_API_KEY,
    )

    # Connect to existing Chrome browser
    browser = Browser(
        config=BrowserConfig(
            cdp_url=CDP_URL,
        )
    )

    collected = load_progress()
    for k, v in KNOWN_VALUES.items():
        collected.setdefault(k, v)

    remaining = len([t for t in TASKS if not collected.get(t["key"])])
    print("=" * 60)
    print("  HERMES AUTO AGENT — Social Optimize")
    print(f"  Connected to your open Chrome browser")
    print(f"  {remaining} tasks remaining")
    print("=" * 60)

    for task_def in TASKS:
        key = task_def["key"]

        if collected.get(key):
            print(f"\n[✓] {key} — already collected, skipping.")
            continue

        print(f"\n[→] Fetching {key}...")

        try:
            agent = Agent(
                task=task_def["task"].strip(),
                llm=llm,
                browser=browser,
            )
            result = await agent.run()
            value = str(result).strip().split("\n")[0].strip()

            if value and len(value) > 3:
                collected[key] = value
                save_progress(collected)
                print(f"  [✓] {key} = {value[:8]}{'*' * max(0, len(value)-8)}")
            else:
                print(f"  [!] Agent returned empty value for {key}, skipping.")
        except Exception as e:
            print(f"  [✗] Error fetching {key}: {e}")

    await browser.close()

    filled  = {k: v for k, v in collected.items() if v}
    missing = [t["key"] for t in TASKS if not collected.get(t["key"])]

    print(f"\n{'='*60}")
    print(f"  Done — {len(filled)} collected, {len(missing)} missing")
    if missing:
        print(f"  Missing: {', '.join(missing)}")
    print(f"{'='*60}")

    push_to_render(filled)


if __name__ == "__main__":
    asyncio.run(run())
