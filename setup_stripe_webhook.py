"""Directly configure Stripe webhook from .env credentials."""
import sys
import os
sys.path.insert(0, '/home/user/Youtube')

from pathlib import Path
for line in Path('/home/user/Youtube/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

import requests  # noqa: E402

STRIPE_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
TARGET_URL = "https://socialoptimize.online/billing/webhook"
EVENTS = [
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
]

headers = {"Authorization": f"Bearer {STRIPE_KEY}"}

print("🎬 STRIPE WEBHOOK SETUP\n" + "="*50)
print(f"Key prefix: {STRIPE_KEY[:12]}...")

# Step 1: List existing webhooks
print("\n[1] Checking existing webhooks...")
resp = requests.get("https://api.stripe.com/v1/webhook_endpoints", headers=headers, timeout=15)
print(f"    Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"    Error: {resp.text}")
    sys.exit(1)

data = resp.json()
existing_id = None
for wh in data.get("data", []):
    print(f"    Found: {wh['url']} [{wh['id']}]")
    if wh["url"] == TARGET_URL:
        existing_id = wh["id"]

# Step 2: Create if not exists
if existing_id:
    print(f"\n[2] Webhook already exists: {existing_id}")
else:
    print(f"\n[2] Creating webhook at {TARGET_URL}...")
    payload = {"url": TARGET_URL}
    for i, e in enumerate(EVENTS):
        payload[f"enabled_events[{i}]"] = e
    resp2 = requests.post("https://api.stripe.com/v1/webhook_endpoints", headers=headers, data=payload, timeout=15)
    print(f"    Status: {resp2.status_code}")
    if resp2.status_code != 200:
        print(f"    Error: {resp2.text}")
        sys.exit(1)
    wh = resp2.json()
    existing_id = wh["id"]
    secret = wh.get("secret", "")
    print("\n✅ WEBHOOK CREATED")
    print(f"   Webhook ID: {existing_id}")
    print(f"   Signing Secret: {secret}")
    print(f"\n⚡ Add to Render env: STRIPE_WEBHOOK_SECRET={secret}")

    # Write secret to .env
    env_content = Path('/home/user/Youtube/.env').read_text()
    if 'STRIPE_WEBHOOK_SECRET' not in env_content:
        with open('/home/user/Youtube/.env', 'a') as f:
            f.write(f"\nSTRIPE_WEBHOOK_SECRET={secret}")
        print("\n✅ Written to .env file")
