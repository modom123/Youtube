"""
Hermes Agent — Render Environment Variable Filler
===================================================
Automates opening every API portal, collecting credentials,
then bulk-sets them all in Render via the Render API.

Requirements:
    pip install playwright python-dotenv requests
    playwright install chromium

Usage:
    python hermes_fill_env.py

The script will:
  1. Open each portal tab in sequence
  2. Pause and prompt you (or your agent) to copy the value
  3. After all values are collected, push them all to Render in one shot
"""

from __future__ import annotations
import json
import os
import sys
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — fill these in before running
# ─────────────────────────────────────────────────────────────────────────────

RENDER_API_KEY      = os.getenv("RENDER_API_KEY", "")       # Render → Account → API Keys
RENDER_SERVICE_ID   = os.getenv("RENDER_SERVICE_ID", "")    # URL: dashboard.render.com/web/srv-XXXXXXXX

# Pre-known values (already confirmed)
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

# ─────────────────────────────────────────────────────────────────────────────
# PORTAL DEFINITIONS
# Each entry: (env_var_name, portal_url, instruction, optional_selector)
# ─────────────────────────────────────────────────────────────────────────────

PORTALS = [
    # ── Anthropic ────────────────────────────────────────────────────────────
    {
        "tab": "Anthropic",
        "url": "https://console.anthropic.com/settings/keys",
        "vars": [
            {
                "key": "ANTHROPIC_API_KEY",
                "instruction": "Click 'Create Key', name it 'Social Money', copy the sk-ant-... value.",
            }
        ],
    },

    # ── Stripe ───────────────────────────────────────────────────────────────
    {
        "tab": "Stripe API Keys",
        "url": "https://dashboard.stripe.com/apikeys",
        "vars": [
            {
                "key": "STRIPE_SECRET_KEY",
                "instruction": "Click 'Reveal live key' for the Secret key (sk_live_...).",
            },
            {
                "key": "STRIPE_PUBLISHABLE_KEY",
                "instruction": "Copy the Publishable key (pk_live_...) — visible without revealing.",
            },
        ],
    },
    {
        "tab": "Stripe Webhook",
        "url": "https://dashboard.stripe.com/webhooks",
        "vars": [
            {
                "key": "STRIPE_WEBHOOK_SECRET",
                "instruction": "Click your webhook endpoint → 'Reveal' the Signing secret (whsec_...).",
            }
        ],
    },
    {
        "tab": "Stripe Products",
        "url": "https://dashboard.stripe.com/products",
        "vars": [
            {
                "key": "STRIPE_PRICE_CREATOR",
                "instruction": "Click Creator product → copy the Price ID (price_...) for the monthly price.",
            },
            {
                "key": "STRIPE_PRICE_AGENCY",
                "instruction": "Click Agency product → copy the Price ID (price_...) for the monthly price.",
            },
        ],
    },

    # ── Pexels ────────────────────────────────────────────────────────────────
    {
        "tab": "Pexels API",
        "url": "https://www.pexels.com/api/new/",
        "vars": [
            {
                "key": "PEXELS_API_KEY",
                "instruction": "Log in, go to 'Your API Key' — copy the key.",
            }
        ],
    },

    # ── Higgsfield ────────────────────────────────────────────────────────────
    {
        "tab": "Higgsfield",
        "url": "https://app.higgsfield.ai/settings",
        "vars": [
            {
                "key": "HIGGSFIELD_MCP_TOKEN",
                "instruction": "Go to Settings → API / Token — copy your MCP token.",
            }
        ],
    },

    # ── Google Cloud ─────────────────────────────────────────────────────────
    {
        "tab": "Google Cloud Credentials",
        "url": "https://console.cloud.google.com/apis/credentials",
        "vars": [
            {
                "key": "YOUTUBE_CLIENT_ID",
                "instruction": "Click your OAuth 2.0 Client → copy Client ID (ends in .apps.googleusercontent.com).",
            },
            {
                "key": "YOUTUBE_CLIENT_SECRET",
                "instruction": "On the same page, copy the Client Secret (GOCSPX-...).",
            },
            {
                "key": "GOOGLE_API_KEY",
                "instruction": "Copy an API Key from the list (AIza...) — make sure YouTube Data API v3 + Cloud TTS are enabled.",
            },
        ],
    },

    # ── TikTok ────────────────────────────────────────────────────────────────
    {
        "tab": "TikTok Developers",
        "url": "https://developers.tiktok.com/apps/",
        "vars": [
            {
                "key": "TIKTOK_CLIENT_KEY",
                "instruction": "Click your app → copy the Client Key.",
            },
            {
                "key": "TIKTOK_CLIENT_SECRET",
                "instruction": "On the same page, reveal and copy the Client Secret.",
            },
        ],
    },

    # ── Meta (Facebook + Instagram + Threads) ─────────────────────────────────
    {
        "tab": "Meta Developers",
        "url": "https://developers.facebook.com/apps/",
        "vars": [
            {
                "key": "FACEBOOK_APP_ID",
                "instruction": "Click your app → Settings → Basic → copy App ID.",
            },
            {
                "key": "FACEBOOK_APP_SECRET",
                "instruction": "On the same Settings → Basic page, click 'Show' next to App Secret.",
            },
            {
                "key": "THREADS_APP_ID",
                "instruction": "If Threads is a separate app, click it and copy its App ID. Otherwise same as FACEBOOK_APP_ID.",
            },
            {
                "key": "THREADS_APP_SECRET",
                "instruction": "Same app as above — copy its App Secret. Otherwise same as FACEBOOK_APP_SECRET.",
            },
        ],
    },

    # ── LinkedIn ─────────────────────────────────────────────────────────────
    {
        "tab": "LinkedIn Developers",
        "url": "https://www.linkedin.com/developers/apps/",
        "vars": [
            {
                "key": "LINKEDIN_CLIENT_ID",
                "instruction": "Click your app → Auth tab → copy Client ID.",
            },
            {
                "key": "LINKEDIN_CLIENT_SECRET",
                "instruction": "On the same Auth tab, copy Client Secret.",
            },
        ],
    },

    # ── X (Twitter) ───────────────────────────────────────────────────────────
    {
        "tab": "Twitter Developer Portal",
        "url": "https://developer.twitter.com/en/portal/projects-and-apps",
        "vars": [
            {
                "key": "TWITTER_CLIENT_ID",
                "instruction": "Click your app → Keys and Tokens → OAuth 2.0 Client ID and Client Secret → copy Client ID.",
            },
            {
                "key": "TWITTER_CLIENT_SECRET",
                "instruction": "On the same page, copy Client Secret (regenerate if needed).",
            },
        ],
    },

    # ── Twitch ────────────────────────────────────────────────────────────────
    {
        "tab": "Twitch Dev Console",
        "url": "https://dev.twitch.tv/console/apps",
        "vars": [
            {
                "key": "TWITCH_CLIENT_ID",
                "instruction": "Click your app → copy Client ID.",
            },
            {
                "key": "TWITCH_CLIENT_SECRET",
                "instruction": "Click 'New Secret' if needed → copy Client Secret.",
            },
        ],
    },

    # ── Snapchat ──────────────────────────────────────────────────────────────
    {
        "tab": "Snap Kit",
        "url": "https://kit.snapchat.com/manage",
        "vars": [
            {
                "key": "SNAP_CLIENT_ID",
                "instruction": "Click your app → Credentials → copy Client ID.",
            },
            {
                "key": "SNAP_CLIENT_SECRET",
                "instruction": "On the same page, copy Client Secret.",
            },
        ],
    },

    # ── Twilio ────────────────────────────────────────────────────────────────
    {
        "tab": "Twilio Console",
        "url": "https://console.twilio.com",
        "vars": [
            {
                "key": "TWILIO_ACCOUNT_SID",
                "instruction": "Copy Account SID from the dashboard homepage (AC...).",
            },
            {
                "key": "TWILIO_AUTH_TOKEN",
                "instruction": "Click 'Show' next to Auth Token — copy it.",
            },
        ],
    },
    {
        "tab": "Twilio Phone Numbers",
        "url": "https://console.twilio.com/us1/develop/phone-numbers/manage/active",
        "vars": [
            {
                "key": "TWILIO_FROM_NUMBER",
                "instruction": "Copy your active phone number in E.164 format (+1...).",
            }
        ],
    },

    # ── Gmail SMTP ────────────────────────────────────────────────────────────
    {
        "tab": "Gmail App Password",
        "url": "https://myaccount.google.com/apppasswords",
        "vars": [
            {
                "key": "SMTP_USER",
                "instruction": "Enter your Gmail address (nwtcinvestment@gmail.com).",
            },
            {
                "key": "SMTP_PASS",
                "instruction": "Create App Password → App: Mail, Device: Social Money → copy the 16-char password.",
            },
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def prompt_value(key: str, instruction: str) -> str:
    """Pause and ask the agent/user to provide the value for a key."""
    print(f"\n{'─'*60}")
    print(f"  ENV VAR : {key}")
    print(f"  ACTION  : {instruction}")
    print(f"{'─'*60}")
    value = input(f"  Paste value for {key}: ").strip()
    return value


def open_tab(page: Page, url: str, tab_name: str) -> bool:
    """Navigate to url. Returns False if browser was closed."""
    print(f"\n[→] Opening {tab_name}: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        time.sleep(1)
        return True
    except Exception as e:
        print(f"  [!] Browser error: {e}")
        return False


def save_progress(collected: dict, path: Path):
    path.write_text(json.dumps(collected, indent=2))
    print(f"  [✓] Progress saved to {path}")


def load_progress(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# RENDER API — push env vars
# ─────────────────────────────────────────────────────────────────────────────

def push_to_render(env_vars: dict):
    """Push all collected env vars to Render via the REST API."""
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print("\n[!] RENDER_API_KEY or RENDER_SERVICE_ID not set.")
        print("    Set them as environment variables before running:")
        print("    export RENDER_API_KEY=rnd_xxxxxxxx")
        print("    export RENDER_SERVICE_ID=srv-xxxxxxxx")
        _save_dotenv(env_vars)
        return

    print(f"\n[→] Pushing {len(env_vars)} env vars to Render service {RENDER_SERVICE_ID}...")

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Render API: PUT /services/{id}/env-vars (replaces all)
    payload = [{"key": k, "value": v} for k, v in env_vars.items()]

    resp = requests.put(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars",
        headers=headers,
        json=payload,
        timeout=30,
    )

    if resp.status_code in (200, 201):
        print(f"[✓] All {len(env_vars)} env vars pushed to Render successfully!")
        print("    Trigger a redeploy in the Render dashboard to apply changes.")
    else:
        print(f"[✗] Render API error {resp.status_code}: {resp.text}")
        _save_dotenv(env_vars)


def _save_dotenv(env_vars: dict):
    """Fallback: save to .env.render file for manual upload."""
    out = Path("env.render")
    lines = [f"{k}={v}" for k, v in env_vars.items()]
    out.write_text("\n".join(lines))
    print(f"\n[✓] Saved to {out.resolve()} — paste these into Render manually.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    progress_file = Path("hermes_progress.json")
    collected: dict = load_progress(progress_file)

    # Merge pre-known values
    for k, v in KNOWN_VALUES.items():
        if k not in collected:
            collected[k] = v

    print("=" * 60)
    print("  HERMES AGENT — Render Env Var Filler")
    print("  Social Money · socialoptimize.online")
    print("=" * 60)

    already_done = [k for k in collected if k in KNOWN_VALUES or collected[k]]
    if already_done:
        print(f"\n  Resuming — {len(already_done)} values already collected.")

    with sync_playwright() as pw:

        def new_browser():
            b = pw.chromium.launch(headless=False, slow_mo=100)
            ctx = b.new_context(viewport={"width": 1400, "height": 900})
            pg = ctx.new_page()
            return b, pg

        browser, page = new_browser()

        for portal in PORTALS:
            tab_name = portal["tab"]
            needs_visit = any(
                not collected.get(v["key"]) for v in portal["vars"]
            )
            if not needs_visit:
                print(f"\n[✓] {tab_name} — already collected, skipping.")
                continue

            # Reopen browser if it was closed
            try:
                page.evaluate("1")  # ping — raises if browser dead
            except Exception:
                print("\n[!] Browser was closed — reopening...")
                try:
                    browser.close()
                except Exception:
                    pass
                browser, page = new_browser()

            ok = open_tab(page, portal["url"], tab_name)
            if not ok:
                # Browser died mid-navigation — reopen and retry once
                try:
                    browser.close()
                except Exception:
                    pass
                browser, page = new_browser()
                ok = open_tab(page, portal["url"], tab_name)
                if not ok:
                    print(f"  [!] Could not open {tab_name}, skipping.")
                    continue

            for var in portal["vars"]:
                key = var["key"]
                if collected.get(key):
                    print(f"  [✓] {key} already collected, skipping.")
                    continue

                value = prompt_value(key, var["instruction"])
                if value:
                    collected[key] = value
                    save_progress(collected, progress_file)
                else:
                    print(f"  [!] Skipped {key} — re-run to fill later.")

        try:
            browser.close()
        except Exception:
            pass

    # Summary
    filled = {k: v for k, v in collected.items() if v}
    skipped = [k for k, v in collected.items() if not v]

    print(f"\n{'='*60}")
    print(f"  COLLECTION COMPLETE")
    print(f"  Filled  : {len(filled)} vars")
    print(f"  Skipped : {len(skipped)} vars")
    if skipped:
        print(f"  Missing : {', '.join(skipped)}")
    print(f"{'='*60}")

    # Push to Render
    confirm = input("\nPush all env vars to Render now? (y/n): ").strip().lower()
    if confirm == "y":
        push_to_render(filled)
    else:
        _save_dotenv(filled)


if __name__ == "__main__":
    main()
