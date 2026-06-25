# Hermes Agent — Render ENV Filler

## Setup (one time)
```bash
pip install playwright python-dotenv requests
playwright install chromium
```

## Before running — get two values from Render:

1. **RENDER_API_KEY**
   - Render Dashboard → Account Settings → API Keys → Create API Key

2. **RENDER_SERVICE_ID**
   - Open your Social Money service in Render
   - Copy the ID from the URL: `dashboard.render.com/web/srv-XXXXXXXXXX`
   - It starts with `srv-`

```bash
export RENDER_API_KEY=rnd_xxxxxxxxxxxxxxxxxxxxxxxx
export RENDER_SERVICE_ID=srv-xxxxxxxxxxxxxxxxxxxxxxxx
```

## Run
```bash
cd scripts
python hermes_fill_env.py
```

## What it does
1. Opens a real Chromium browser window
2. Navigates to each portal in sequence (13 tabs total)
3. Displays instructions for each key
4. Waits for you to paste the value
5. Saves progress to `hermes_progress.json` after each value
   — if it crashes, re-run and it resumes where it left off
6. At the end, pushes ALL values to Render via API in one shot
7. Triggers a redeploy automatically

## Portals visited (in order)
1. console.anthropic.com — ANTHROPIC_API_KEY
2. dashboard.stripe.com/apikeys — STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY
3. dashboard.stripe.com/webhooks — STRIPE_WEBHOOK_SECRET
4. dashboard.stripe.com/products — STRIPE_PRICE_CREATOR, STRIPE_PRICE_AGENCY
5. pexels.com/api — PEXELS_API_KEY
6. app.higgsfield.ai/settings — HIGGSFIELD_MCP_TOKEN
7. console.cloud.google.com — YOUTUBE_CLIENT_ID/SECRET, GOOGLE_API_KEY
8. developers.tiktok.com — TIKTOK_CLIENT_KEY/SECRET
9. developers.facebook.com — FACEBOOK_APP_ID/SECRET, THREADS_APP_ID/SECRET
10. linkedin.com/developers — LINKEDIN_CLIENT_ID/SECRET
11. developer.twitter.com — TWITTER_CLIENT_ID/SECRET
12. dev.twitch.tv/console — TWITCH_CLIENT_ID/SECRET
13. kit.snapchat.com — SNAP_CLIENT_ID/SECRET
14. console.twilio.com — TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
15. myaccount.google.com/apppasswords — SMTP_USER, SMTP_PASS

## Pre-filled automatically (no action needed)
- APP_BASE_URL
- DATA_DIR
- STRIPE_PRICE_STARTER
- All redirect URIs
- SMTP_HOST / SMTP_PORT
