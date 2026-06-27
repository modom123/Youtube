"""Run Hollywood to configure Stripe webhooks — credentials from env only."""
import sys
import os
sys.path.insert(0, '/home/user/Youtube')

# Load .env into environment
from pathlib import Path
env_file = Path('/home/user/Youtube/.env')
for line in env_file.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

import importlib  # noqa: E402
import config  # noqa: E402
importlib.reload(config)

stripe_set = bool(os.environ.get('STRIPE_SECRET_KEY', ''))
print(f"Stripe key loaded: {stripe_set}")

from generators.hollywood_agent import chat  # noqa: E402

message = """Set up the Stripe webhook endpoint. Use the STRIPE_SECRET_KEY from os.environ (already loaded).

Steps:
1. Call list_stripe_webhooks — get the stripe_api_key from os.environ['STRIPE_SECRET_KEY']
2. Create webhook at https://socialoptimize.online/billing/webhook if it doesn't exist, with events:
   checkout.session.completed, customer.subscription.created, customer.subscription.updated,
   customer.subscription.deleted, invoice.payment_succeeded, invoice.payment_failed
3. Report the webhook ID and signing secret"""

print("\n🎬 Hollywood running...\n")
result = chat(message=message, history=[], user_id=1)
print(result)
