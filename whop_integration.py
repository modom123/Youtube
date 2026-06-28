"""
Whop Marketplace Integration — sell Social Optimize clipper as a Whop product.

Handles:
1. Product/plan creation on Whop marketplace
2. Webhook processing for membership events (grant/revoke access)
3. Checkout link generation for embedding in our app
4. Usage tracking and metered billing per clip
5. Whop App iframe integration for embedding our clipper inside Whop
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, request, jsonify, redirect, render_template, current_app
from flask_login import login_required, current_user

import config
import database as db

logger = logging.getLogger(__name__)

whop_bp = Blueprint("whop", __name__, url_prefix="/whop")

WHOP_API_KEY = os.getenv("WHOP_API_KEY", "")
WHOP_WEBHOOK_SECRET = os.getenv("WHOP_WEBHOOK_SECRET", "")
WHOP_COMPANY_ID = os.getenv("WHOP_COMPANY_ID", "")

# ── Product tiers we sell on Whop ────────────────────────────────────────────

WHOP_PRODUCTS = {
    "clipper_basic": {
        "name": "AI Clipper — Basic",
        "description": "Turn any video into 5 viral shorts per month. AI scene detection, auto-captions, virality scoring.",
        "price_cents": 1900,
        "billing_period": "month",
        "clips_per_month": 30,
        "features": [
            "5 clipping jobs/month (up to 10 clips each)",
            "AI-powered viral moment detection",
            "Auto-reframe to 9:16, 16:9, 1:1",
            "Animated captions",
            "Hook text overlays",
            "Download as MP4 or ZIP",
        ],
    },
    "clipper_pro": {
        "name": "AI Clipper — Pro",
        "description": "Unlimited clipping with premium features. Perfect for agencies and power creators.",
        "price_cents": 4900,
        "billing_period": "month",
        "clips_per_month": -1,
        "features": [
            "Unlimited clipping jobs",
            "Up to 15 clips per job",
            "Priority processing queue",
            "AI-powered viral moment detection",
            "All output formats (9:16, 16:9, 1:1, 4:5)",
            "Animated captions + hook overlays",
            "Batch download ZIP",
            "Trim & re-cut editor",
            "Publish to 8 platforms",
            "API access",
        ],
    },
    "clipper_payg": {
        "name": "AI Clipper — Pay Per Clip",
        "description": "Pay only for what you use. $0.50 per clip generated.",
        "price_cents": 50,
        "billing_period": None,
        "clips_per_month": 0,
        "features": [
            "$0.50 per clip — no monthly fee",
            "AI-powered viral moment detection",
            "Auto-reframe & captions",
            "Download as MP4",
        ],
    },
}


def _get_whop_client():
    """Get authenticated Whop SDK client."""
    api_key = WHOP_API_KEY or config.__dict__.get("WHOP_API_KEY", "")
    if not api_key:
        return None
    try:
        from whop_sdk import Whop
        return Whop(api_key=api_key)
    except ImportError:
        logger.warning("whop-sdk not installed, run: pip install whop-sdk")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# 1. SETUP — Create products & plans on Whop
# ═════════════════════════════════════════════════════════════════════════════

@whop_bp.route("/setup", methods=["POST"])
@login_required
def whop_setup():
    """Admin endpoint: create our products and plans on Whop marketplace."""
    user = db.get_user(current_user.id)
    if not user or not user.get("is_admin"):
        return jsonify({"error": "Admin only"}), 403

    client = _get_whop_client()
    if not client:
        return jsonify({"error": "Whop API key not configured"}), 400

    company_id = WHOP_COMPANY_ID
    if not company_id:
        return jsonify({"error": "WHOP_COMPANY_ID not set"}), 400

    results = {}

    for tier_key, tier in WHOP_PRODUCTS.items():
        try:
            product = client.products.create(
                company_id=company_id,
                name=tier["name"],
                description=tier["description"],
                visibility="visible",
            )

            plan_params = {
                "company_id": company_id,
                "product_id": product.id,
                "plan_type": "renewal" if tier["billing_period"] else "one_time",
                "initial_price": tier["price_cents"],
                "currency": "usd",
            }
            if tier["billing_period"]:
                plan_params["billing_period"] = tier["billing_period"]
                plan_params["renewal_price"] = tier["price_cents"]

            plan = client.plans.create(**plan_params)

            results[tier_key] = {
                "product_id": product.id,
                "plan_id": plan.id,
                "status": "created",
            }

            _save_whop_ids(tier_key, product.id, plan.id)

        except Exception as e:
            results[tier_key] = {"error": str(e)}
            logger.error("Failed to create Whop product %s: %s", tier_key, e)

    # Set up webhook for membership events
    try:
        webhook_url = f"{config.APP_BASE_URL}/whop/webhook"
        webhook = client.webhooks.create(
            company_id=company_id,
            url=webhook_url,
            events=[
                "membership.went_valid",
                "membership.went_invalid",
                "membership.cancelled",
                "payment.succeeded",
                "payment.failed",
            ],
        )
        results["webhook"] = {"id": webhook.id, "url": webhook_url}
    except Exception as e:
        results["webhook"] = {"error": str(e)}

    return jsonify({"ok": True, "results": results})


def _save_whop_ids(tier_key: str, product_id: str, plan_id: str):
    """Persist Whop product/plan IDs in the settings table."""
    with db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"whop_{tier_key}_product_id", product_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"whop_{tier_key}_plan_id", plan_id),
        )
        conn.commit()


def _get_whop_plan_id(tier_key: str) -> Optional[str]:
    """Retrieve stored Whop plan ID."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (f"whop_{tier_key}_plan_id",),
        ).fetchone()
    return row["value"] if row else None


# ═════════════════════════════════════════════════════════════════════════════
# 2. CHECKOUT — Generate payment links
# ═════════════════════════════════════════════════════════════════════════════

@whop_bp.route("/checkout/<tier>")
@login_required
def whop_checkout(tier):
    """Generate a Whop checkout link for the given tier."""
    if tier not in WHOP_PRODUCTS:
        return jsonify({"error": f"Unknown tier: {tier}"}), 400

    client = _get_whop_client()
    if not client:
        return jsonify({"error": "Whop not configured"}), 400

    plan_id = _get_whop_plan_id(tier)
    if not plan_id:
        return jsonify({"error": "Product not set up on Whop yet. Run /whop/setup first."}), 400

    try:
        checkout = client.checkout_configurations.create(
            plan={"id": plan_id},
            currency="usd",
            metadata={
                "user_id": str(current_user.id),
                "tier": tier,
                "source": "social_optimize",
            },
            redirect_url=f"{config.APP_BASE_URL}/whop/success?tier={tier}",
        )
        return jsonify({"checkout_url": checkout.url if hasattr(checkout, "url") else f"https://whop.com/checkout/{checkout.id}"})
    except Exception as e:
        logger.error("Checkout creation failed: %s", e)
        return jsonify({"error": str(e)}), 500


@whop_bp.route("/success")
@login_required
def whop_success():
    """Landing page after successful Whop purchase."""
    tier = request.args.get("tier", "clipper_basic")
    return render_template("whop_success.html", tier=tier, product=WHOP_PRODUCTS.get(tier, {}))


# ═════════════════════════════════════════════════════════════════════════════
# 3. WEBHOOKS — Handle membership events from Whop
# ═════════════════════════════════════════════════════════════════════════════

@whop_bp.route("/webhook", methods=["POST"])
def whop_webhook():
    """Process Whop webhook events for membership lifecycle."""
    payload = request.get_data()
    signature = request.headers.get("X-Whop-Signature", "")

    if WHOP_WEBHOOK_SECRET and not _verify_webhook(payload, signature):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return jsonify({"error": "Invalid JSON"}), 400

    event_type = event.get("event") or event.get("action", "")
    data = event.get("data", {})

    logger.info("Whop webhook: %s", event_type)

    if event_type == "membership.went_valid":
        _handle_membership_activated(data)
    elif event_type in ("membership.went_invalid", "membership.cancelled"):
        _handle_membership_deactivated(data)
    elif event_type == "payment.succeeded":
        _handle_payment_succeeded(data)
    elif event_type == "payment.failed":
        _handle_payment_failed(data)

    return jsonify({"ok": True})


def _verify_webhook(payload: bytes, signature: str) -> bool:
    """Verify Whop webhook signature."""
    if not WHOP_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        WHOP_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _handle_membership_activated(data: dict):
    """Grant clipper access when membership becomes valid."""
    metadata = data.get("metadata", {})
    user_id = metadata.get("user_id")
    tier = metadata.get("tier", "clipper_basic")
    membership_id = data.get("id", "")
    email = data.get("email", "")

    if user_id:
        uid = int(user_id)
    elif email:
        user = db.get_user_by_email(email)
        uid = user["id"] if user else None
    else:
        logger.warning("Whop membership activated but no user_id or email found")
        return

    if not uid:
        logger.warning("Could not find user for Whop membership %s", membership_id)
        return

    clips_per_month = WHOP_PRODUCTS.get(tier, {}).get("clips_per_month", 30)

    with db.get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO whop_subscriptions
            (user_id, membership_id, tier, status, clips_remaining, activated_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?)
        """, (uid, membership_id, tier, clips_per_month,
              datetime.now(timezone.utc).isoformat(),
              datetime.now(timezone.utc).isoformat()))
        conn.commit()

    logger.info("Whop access granted: user=%s tier=%s membership=%s", uid, tier, membership_id)


def _handle_membership_deactivated(data: dict):
    """Revoke clipper access when membership ends."""
    membership_id = data.get("id", "")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE whop_subscriptions SET status='inactive', updated_at=? WHERE membership_id=?",
            (datetime.now(timezone.utc).isoformat(), membership_id),
        )
        conn.commit()
    logger.info("Whop access revoked: membership=%s", membership_id)


def _handle_payment_succeeded(data: dict):
    """Log successful payment."""
    metadata = data.get("metadata", {})
    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO whop_payments (membership_id, amount_cents, currency, status, whop_payment_id, created_at)
            VALUES (?, ?, ?, 'succeeded', ?, ?)
        """, (
            data.get("membership_id", ""),
            data.get("amount", 0),
            data.get("currency", "usd"),
            data.get("id", ""),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()


def _handle_payment_failed(data: dict):
    """Log failed payment."""
    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO whop_payments (membership_id, amount_cents, currency, status, whop_payment_id, created_at)
            VALUES (?, ?, ?, 'failed', ?, ?)
        """, (
            data.get("membership_id", ""),
            data.get("amount", 0),
            data.get("currency", "usd"),
            data.get("id", ""),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# 4. ACCESS CONTROL — Check if user has Whop clipper access
# ═════════════════════════════════════════════════════════════════════════════

def check_whop_access(user_id: int) -> dict:
    """Check if a user has active Whop clipper subscription."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM whop_subscriptions WHERE user_id=? AND status='active' ORDER BY activated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()

    if not row:
        return {"has_access": False, "tier": None, "clips_remaining": 0}

    return {
        "has_access": True,
        "tier": row["tier"],
        "clips_remaining": row["clips_remaining"],
        "membership_id": row["membership_id"],
        "unlimited": row["clips_remaining"] == -1,
    }


def use_whop_clip(user_id: int) -> bool:
    """Decrement clip count for a Whop user. Returns False if no clips left."""
    access = check_whop_access(user_id)
    if not access["has_access"]:
        return False
    if access["unlimited"]:
        return True

    with db.get_conn() as conn:
        result = conn.execute(
            "UPDATE whop_subscriptions SET clips_remaining = clips_remaining - 1, updated_at=? WHERE user_id=? AND status='active' AND clips_remaining > 0",
            (datetime.now(timezone.utc).isoformat(), user_id),
        )
        conn.commit()
        return result.rowcount > 0


# ═════════════════════════════════════════════════════════════════════════════
# 5. WHOP APP IFRAME — Embed our clipper inside Whop
# ═════════════════════════════════════════════════════════════════════════════

@whop_bp.route("/app")
def whop_app_iframe():
    """Serve our clipper inside Whop's iframe. Whop passes user info via query params."""
    membership_id = request.args.get("membership_id", "")
    user_id = request.args.get("user_id", "")

    return render_template("whop_app.html",
                           membership_id=membership_id,
                           whop_user_id=user_id)


@whop_bp.route("/app/validate", methods=["POST"])
def whop_app_validate():
    """Validate that a Whop user has access (called from iframe)."""
    data = request.json or {}
    membership_id = data.get("membership_id", "")

    if not membership_id:
        return jsonify({"valid": False, "error": "No membership ID"}), 400

    client = _get_whop_client()
    if not client:
        return jsonify({"valid": True, "tier": "clipper_basic"})

    try:
        membership = client.memberships.retrieve(membership_id)
        is_valid = membership.status in ("active", "trialing", "completed")
        return jsonify({
            "valid": is_valid,
            "tier": _membership_to_tier(membership),
            "status": membership.status,
        })
    except Exception as e:
        logger.error("Whop membership validation failed: %s", e)
        return jsonify({"valid": False, "error": str(e)}), 500


def _membership_to_tier(membership) -> str:
    """Map a Whop membership to our tier key."""
    product_id = getattr(membership, "product_id", "")
    with db.get_conn() as conn:
        for tier_key in WHOP_PRODUCTS:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (f"whop_{tier_key}_product_id",),
            ).fetchone()
            if row and row["value"] == product_id:
                return tier_key
    return "clipper_basic"


# ═════════════════════════════════════════════════════════════════════════════
# 6. MARKETPLACE LISTING API — Provide data for Whop storefront
# ═════════════════════════════════════════════════════════════════════════════

@whop_bp.route("/api/products")
def whop_api_products():
    """Public endpoint: return our product catalog for Whop listing."""
    products = []
    for tier_key, tier in WHOP_PRODUCTS.items():
        products.append({
            "id": tier_key,
            "name": tier["name"],
            "description": tier["description"],
            "price_cents": tier["price_cents"],
            "billing_period": tier["billing_period"],
            "features": tier["features"],
            "clips_per_month": tier["clips_per_month"],
        })
    return jsonify({"products": products})


@whop_bp.route("/api/stats")
@login_required
def whop_api_stats():
    """Admin endpoint: revenue and subscriber stats from Whop."""
    user = db.get_user(current_user.id)
    if not user or not user.get("is_admin"):
        return jsonify({"error": "Admin only"}), 403

    with db.get_conn() as conn:
        active = conn.execute(
            "SELECT COUNT(*) as c FROM whop_subscriptions WHERE status='active'"
        ).fetchone()["c"]
        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) as total FROM whop_payments WHERE status='succeeded'"
        ).fetchone()["total"]
        by_tier = conn.execute(
            "SELECT tier, COUNT(*) as c FROM whop_subscriptions WHERE status='active' GROUP BY tier"
        ).fetchall()

    return jsonify({
        "active_subscribers": active,
        "total_revenue_cents": total_revenue,
        "total_revenue_usd": f"${total_revenue / 100:.2f}",
        "by_tier": {row["tier"]: row["c"] for row in by_tier},
    })


# ═════════════════════════════════════════════════════════════════════════════
# 7. DATABASE TABLES
# ═════════════════════════════════════════════════════════════════════════════

def init_whop_tables():
    """Create Whop-related tables if they don't exist."""
    with db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whop_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                membership_id TEXT UNIQUE,
                tier TEXT DEFAULT 'clipper_basic',
                status TEXT DEFAULT 'active',
                clips_remaining INTEGER DEFAULT 30,
                activated_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whop_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                membership_id TEXT,
                amount_cents INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'usd',
                status TEXT DEFAULT 'pending',
                whop_payment_id TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
