#!/usr/bin/env python3
"""
Push all 5 Social Optimize tiers to Whop as products + plans.

Usage:
    pip install whop-sdk
    python scripts/push_whop_products.py

Requires env vars (or edit the values below):
    WHOP_API_KEY        — your Account API key
    WHOP_COMPANY_ID     — your Whop company/business ID
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whop_sdk import Whop

API_KEY = os.getenv(
    "WHOP_API_KEY",
    "apik_hHvRSw1u64Z3c_C5535154_C_30d86cec65dd125d10e1915f67ba91c228933dfaedc6ef48887427d8416a9b",
)
COMPANY_ID = os.getenv("WHOP_COMPANY_ID", "")

PRODUCTS = {
    "free": {
        "title": "Social Optimize — Free",
        "description": "3 AI videos per month. Basic AI generation, vertical reframe, animated captions. No credit card required.",
        "price": 0.0,
        "billing_period_days": None,
        "videos_per_month": 3,
    },
    "starter": {
        "title": "Social Optimize — Starter",
        "description": "10 AI videos per month. 8-platform publishing, scheduling, analytics, no watermark.",
        "price": 9.99,
        "billing_period_days": 30,
        "videos_per_month": 10,
    },
    "creator": {
        "title": "Social Optimize — Creator",
        "description": "30 AI videos per month. AI Clipper, batch creation, Studio 56, virality scoring.",
        "price": 29.0,
        "billing_period_days": 30,
        "videos_per_month": 30,
    },
    "pro": {
        "title": "Social Optimize — Pro",
        "description": "100 AI videos per month. Hollywood AI, multi-language, team seats, advanced analytics.",
        "price": 79.0,
        "billing_period_days": 30,
        "videos_per_month": 100,
    },
    "agency": {
        "title": "Social Optimize — Agency",
        "description": "200 AI videos per month. White-label, API access, 10 team seats, dedicated account manager.",
        "price": 199.0,
        "billing_period_days": 30,
        "videos_per_month": 200,
    },
}

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://socialoptimize.online")


def main():
    if not COMPANY_ID:
        print("ERROR: Set WHOP_COMPANY_ID env var or edit this script.")
        print("\nTrying to find your company ID...")
        client = Whop(api_key=API_KEY)
        try:
            companies = client.companies.list()
            for c in companies.data if hasattr(companies, "data") else companies:
                print(f"  Found: {getattr(c, 'id', '?')} — {getattr(c, 'title', '?')}")
            print("\nSet WHOP_COMPANY_ID to one of the IDs above and re-run.")
        except Exception as e:
            print(f"  Could not list companies: {e}")
        sys.exit(1)

    client = Whop(api_key=API_KEY)
    results = {}

    for tier_key, tier in PRODUCTS.items():
        print(f"\n{'='*60}")
        print(f"Creating: {tier['title']} (${tier['price']}/{'mo' if tier['billing_period_days'] else 'free'})")
        print(f"{'='*60}")

        # 1. Create product
        try:
            product = client.products.create(
                company_id=COMPANY_ID,
                title=tier["title"],
                description=tier["description"],
                visibility="visible",
            )
            product_id = product.id
            print(f"  Product created: {product_id}")
        except Exception as e:
            print(f"  Product creation failed: {e}")
            results[tier_key] = {"error": str(e)}
            continue

        # 2. Create plan
        try:
            if tier["price"] == 0:
                plan = client.plans.create(
                    company_id=COMPANY_ID,
                    product_id=product_id,
                    plan_type="one_time",
                    initial_price=0.0,
                    currency="usd",
                    unlimited_stock=True,
                )
            else:
                plan = client.plans.create(
                    company_id=COMPANY_ID,
                    product_id=product_id,
                    plan_type="renewal",
                    initial_price=tier["price"],
                    renewal_price=tier["price"],
                    billing_period=tier["billing_period_days"],
                    currency="usd",
                    unlimited_stock=True,
                    trial_period_days=7,
                )
            plan_id = plan.id
            print(f"  Plan created: {plan_id}")
        except Exception as e:
            print(f"  Plan creation failed: {e}")
            results[tier_key] = {"product_id": product_id, "error": str(e)}
            continue

        # 3. Create checkout configuration
        try:
            checkout = client.checkout_configurations.create(
                plan_id=plan_id,
                metadata={"tier": tier_key, "source": "social_optimize"},
                redirect_url=f"{APP_BASE_URL}/whop/success?tier={tier_key}",
            )
            checkout_url = getattr(checkout, "purchase_url", None) or f"https://whop.com/checkout/{plan_id}"
            print(f"  Checkout created: {checkout_url}")
        except Exception as e:
            checkout_url = f"https://whop.com/checkout/{plan_id}"
            print(f"  Checkout config note ({e}), fallback URL: {checkout_url}")

        results[tier_key] = {
            "product_id": product_id,
            "plan_id": plan_id,
            "checkout_url": checkout_url,
            "status": "created",
        }

    # 4. Set up webhook
    print(f"\n{'='*60}")
    print("Setting up webhook...")
    print(f"{'='*60}")
    try:
        webhook_url = f"{APP_BASE_URL}/whop/webhook"
        webhook = client.webhooks.create(
            url=webhook_url,
            resource_id=COMPANY_ID,
            events=[
                "membership_went_valid",
                "membership_went_invalid",
                "membership_cancel_at_period_end_changed",
                "payment_succeeded",
                "payment_failed",
                "payment_created",
            ],
        )
        print(f"  Webhook created: {webhook.id} -> {webhook_url}")
        results["webhook"] = {"id": webhook.id, "url": webhook_url}
    except Exception as e:
        print(f"  Webhook failed: {e}")
        results["webhook"] = {"error": str(e)}

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for tier_key, r in results.items():
        if tier_key == "webhook":
            continue
        status = "OK" if r.get("status") == "created" else "FAIL"
        print(f"  [{status}] {tier_key:10s} product={r.get('product_id', 'FAILED'):24s} plan={r.get('plan_id', 'FAILED')}")
        if r.get("checkout_url"):
            print(f"           checkout: {r['checkout_url']}")

    # Save IDs for .env
    print(f"\n{'='*60}")
    print("Add these to your .env or settings DB:")
    print(f"{'='*60}")
    for tier_key, r in results.items():
        if tier_key == "webhook":
            continue
        if r.get("product_id"):
            print(f"WHOP_{tier_key.upper()}_PRODUCT_ID={r['product_id']}")
        if r.get("plan_id"):
            print(f"WHOP_{tier_key.upper()}_PLAN_ID={r['plan_id']}")

    # Save to JSON for reference
    out_path = os.path.join(os.path.dirname(__file__), "whop_products_created.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to: {out_path}")


if __name__ == "__main__":
    main()
