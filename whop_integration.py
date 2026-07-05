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
WHOP_APP_API_KEY = os.getenv("WHOP_APP_API_KEY", "")
WHOP_WEBHOOK_SECRET = os.getenv("WHOP_WEBHOOK_SECRET", "")
WHOP_COMPANY_ID = os.getenv("WHOP_COMPANY_ID", "")

# ── Product tiers we sell on Whop ────────────────────────────────────────────

WHOP_PRODUCTS = {
    "free": {
        "name": "Social Optimize — Free",
        "description": "3 AI videos per month. Basic AI generation, vertical reframe, animated captions.",
        "price": 0.0,
        "billing_period": None,
        "videos_per_month": 3,
        "features": [
            "3 AI videos/month",
            "Basic AI generation",
            "Auto-reframe to 9:16",
            "Animated captions",
            "Download as MP4",
            "YouTube publishing",
        ],
    },
    "starter": {
        "name": "Social Optimize — Starter",
        "description": "10 AI videos per month. 8-platform publishing, scheduling, analytics, no watermark.",
        "price": 9.99,
        "billing_period": "month",
        "videos_per_month": 10,
        "features": [
            "10 AI videos/month",
            "Publish to 8 platforms",
            "Scheduling & auto-publish",
            "50 Social Optimize Credits",
            "Basic analytics",
            "No watermark",
        ],
    },
    "creator": {
        "name": "Social Optimize — Creator",
        "description": "30 AI videos per month. The Scalpel, batch creation, The Forge, virality scoring.",
        "price": 29.0,
        "billing_period": "month",
        "videos_per_month": 30,
        "features": [
            "30 AI videos/month",
            "The Scalpel — viral moment detection",
            "Batch video creation",
            "The Forge production suite",
            "200 Social Optimize Credits",
            "Virality scoring",
            "Priority rendering",
        ],
    },
    "pro": {
        "name": "Social Optimize — Pro",
        "description": "100 AI videos per month. Cinema House, multi-language, team seats, advanced analytics.",
        "price": 79.0,
        "billing_period": "month",
        "videos_per_month": 100,
        "features": [
            "100 AI videos/month",
            "Cinema House — cinematic AI",
            "Multi-language support",
            "500 Social Optimize Credits",
            "Team seats included",
            "Advanced analytics",
            "All output formats (9:16, 16:9, 1:1, 4:5)",
            "Commercial license",
        ],
    },
    "agency": {
        "name": "Social Optimize — Agency",
        "description": "200 AI videos per month. White-label, API access, 10 team seats, dedicated account manager.",
        "price": 199.0,
        "billing_period": "month",
        "videos_per_month": 200,
        "features": [
            "200 AI videos/month",
            "White-label exports",
            "Full API access",
            "1000 Social Optimize Credits",
            "10 team seats",
            "Dedicated account manager",
            "Custom integrations",
            "Priority support",
        ],
    },
}


def _get_whop_client(use_app_key: bool = False):
    """Get authenticated Whop SDK client.

    use_app_key=True for member-facing operations (iframe validation, experience access).
    use_app_key=False (default) for admin/account operations (setup, stats, memberships).
    """
    if use_app_key:
        api_key = WHOP_APP_API_KEY or config.__dict__.get("WHOP_APP_API_KEY", "")
    else:
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
                title=tier["name"],
                description=tier["description"],
                visibility="visible",
            )

            if tier["price"] == 0:
                plan = client.plans.create(
                    company_id=company_id,
                    product_id=product.id,
                    plan_type="one_time",
                    initial_price=0.0,
                    currency="usd",
                    unlimited_stock=True,
                )
            else:
                plan = client.plans.create(
                    company_id=company_id,
                    product_id=product.id,
                    plan_type="renewal",
                    initial_price=tier["price"],
                    renewal_price=tier["price"],
                    billing_period=30,
                    currency="usd",
                    unlimited_stock=True,
                )

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
            url=webhook_url,
            resource_id=company_id,
            events=[
                "membership_went_valid",
                "membership_went_invalid",
                "membership_cancel_at_period_end_changed",
                "payment_succeeded",
                "payment_failed",
                "payment_created",
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
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            (f"whop_{tier_key}_product_id", product_id),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
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

    product_info = WHOP_PRODUCTS[tier]
    try:
        checkout = client.checkout_configurations.create(
            plan_id=plan_id,
            metadata={
                "user_id": str(current_user.id),
                "tier": tier,
                "source": "social_optimize",
            },
            redirect_url=f"{config.APP_BASE_URL}/whop/success?tier={tier}",
        )
        checkout_url = getattr(checkout, "purchase_url", None) or f"https://whop.com/checkout/{plan_id}"
        return jsonify({"checkout_url": checkout_url})
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

    if not _verify_webhook(payload, signature):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return jsonify({"error": "Invalid JSON"}), 400

    event_type = event.get("event") or event.get("action", "")
    data = event.get("data", {})

    logger.info("Whop webhook: %s", event_type)

    if event_type == "membership_went_valid":
        _handle_membership_activated(data)
    elif event_type in ("membership_went_invalid", "membership_cancel_at_period_end_changed"):
        _handle_membership_deactivated(data)
    elif event_type in ("payment_succeeded", "payment_created"):
        _handle_payment_succeeded(data)
    elif event_type == "payment_failed":
        _handle_payment_failed(data)

    return jsonify({"ok": True})


def _verify_webhook(payload: bytes, signature: str) -> bool:
    """Verify Whop webhook signature."""
    if not WHOP_WEBHOOK_SECRET:
        logger.error("WHOP_WEBHOOK_SECRET is not configured — rejecting webhook (fail closed).")
        return False
    expected = hmac.HMAC(
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

    videos_per_month = WHOP_PRODUCTS.get(tier, {}).get("videos_per_month", 3)

    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO whop_subscriptions
            (user_id, membership_id, tier, status, videos_remaining, activated_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT (membership_id) DO UPDATE SET
                user_id=EXCLUDED.user_id,
                tier=EXCLUDED.tier,
                status='active',
                videos_remaining=EXCLUDED.videos_remaining,
                updated_at=EXCLUDED.updated_at
        """, (uid, membership_id, tier, videos_per_month,
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
        return {"has_access": False, "tier": None, "videos_remaining": 0}

    return {
        "has_access": True,
        "tier": row["tier"],
        "videos_remaining": row["videos_remaining"],
        "membership_id": row["membership_id"],
        "unlimited": row["videos_remaining"] == -1,
    }


def use_whop_video(user_id: int) -> bool:
    """Decrement clip count for a Whop user. Returns False if no clips left."""
    access = check_whop_access(user_id)
    if not access["has_access"]:
        return False
    if access["unlimited"]:
        return True

    with db.get_conn() as conn:
        result = conn.execute(
            "UPDATE whop_subscriptions SET videos_remaining = videos_remaining - 1, updated_at=? WHERE user_id=? AND status='active' AND videos_remaining > 0",
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
    experience_id = request.args.get("experienceId", "")
    membership_id = request.args.get("membership_id", "")
    user_id = request.args.get("user_id", "")

    return render_template("whop_app.html",
                           experience_id=experience_id,
                           membership_id=membership_id,
                           whop_user_id=user_id)


@whop_bp.route("/experiences/<experience_id>")
def whop_experience(experience_id):
    """Experience path — Whop loads this for each member's experience."""
    membership_id = request.args.get("membership_id", "")
    user_id = request.args.get("user_id", "")
    return render_template("whop_app.html",
                           experience_id=experience_id,
                           membership_id=membership_id,
                           whop_user_id=user_id)


@whop_bp.route("/dashboard/<company_id>")
def whop_dashboard(company_id):
    """Dashboard path — Whop loads this for creators managing the app."""
    client = _get_whop_client(use_app_key=True)
    stats = {}
    if client:
        try:
            memberships = client.memberships.list(
                company_id=company_id, per=100, status="active",
            )
            member_list = memberships.data if hasattr(memberships, "data") else list(memberships)
            stats["active_members"] = len(member_list)
            stats["members"] = [
                {"id": getattr(m, "id", ""), "email": getattr(m, "email", ""),
                 "status": getattr(m, "status", "")}
                for m in member_list
            ]
        except Exception as e:
            stats["error"] = str(e)
    return render_template("whop_dashboard.html",
                           company_id=company_id, stats=stats,
                           products=WHOP_PRODUCTS)


@whop_bp.route("/discover")
def whop_discover():
    """Discover path — public-facing app listing inside Whop."""
    return render_template("whop_discover.html", products=WHOP_PRODUCTS)


@whop_bp.route("/app/validate", methods=["POST"])
def whop_app_validate():
    """Validate that a Whop user has access (called from iframe)."""
    data = request.json or {}
    membership_id = data.get("membership_id", "")

    if not membership_id:
        return jsonify({"valid": False, "error": "No membership ID"}), 400

    client = _get_whop_client(use_app_key=True)
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
            "price": tier["price"],
            "billing_period": tier["billing_period"],
            "features": tier["features"],
            "videos_per_month": tier["videos_per_month"],
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

    result = {
        "active_subscribers": active,
        "total_revenue_cents": total_revenue,
        "total_revenue_usd": f"${total_revenue / 100:.2f}",
        "by_tier": {row["tier"]: row["c"] for row in by_tier},
    }

    # Pull live data from Whop API if available
    client = _get_whop_client()
    if client and WHOP_COMPANY_ID:
        try:
            memberships = client.memberships.list(
                company_id=WHOP_COMPANY_ID,
                per=100,
                status="active",
            )
            live_members = []
            for m in memberships.data if hasattr(memberships, "data") else memberships:
                live_members.append({
                    "id": getattr(m, "id", ""),
                    "email": getattr(m, "email", ""),
                    "status": getattr(m, "status", ""),
                    "product_id": getattr(m, "product_id", ""),
                    "created_at": str(getattr(m, "created_at", "")),
                })
            result["live_memberships"] = live_members
            result["live_active_count"] = len(live_members)
        except Exception as e:
            result["live_error"] = str(e)

    return jsonify(result)


@whop_bp.route("/api/memberships")
@login_required
def whop_api_memberships():
    """Admin endpoint: pull all paying memberships from Whop API."""
    user = db.get_user(current_user.id)
    if not user or not user.get("is_admin"):
        return jsonify({"error": "Admin only"}), 403

    client = _get_whop_client()
    if not client:
        return jsonify({"error": "Whop API key not configured"}), 400

    company_id = WHOP_COMPANY_ID
    if not company_id:
        return jsonify({"error": "WHOP_COMPANY_ID not set"}), 400

    status_filter = request.args.get("status", "active")
    per_page = min(int(request.args.get("per", 100)), 100)

    try:
        memberships = client.memberships.list(
            company_id=company_id,
            per=per_page,
            status=status_filter,
        )
        members = []
        for m in memberships.data if hasattr(memberships, "data") else memberships:
            tier = _membership_to_tier(m) if hasattr(m, "product_id") else "unknown"
            members.append({
                "id": getattr(m, "id", ""),
                "email": getattr(m, "email", ""),
                "user_id": getattr(m, "user_id", ""),
                "status": getattr(m, "status", ""),
                "product_id": getattr(m, "product_id", ""),
                "plan_id": getattr(m, "plan_id", ""),
                "tier": tier,
                "created_at": str(getattr(m, "created_at", "")),
                "valid": getattr(m, "valid", False),
                "metadata": getattr(m, "metadata", {}),
            })
        return jsonify({
            "memberships": members,
            "count": len(members),
            "status_filter": status_filter,
        })
    except Exception as e:
        logger.error("Failed to pull Whop memberships: %s", e)
        return jsonify({"error": str(e)}), 500


@whop_bp.route("/api/payments")
@login_required
def whop_api_payments():
    """Admin endpoint: pull payment history from Whop API."""
    user = db.get_user(current_user.id)
    if not user or not user.get("is_admin"):
        return jsonify({"error": "Admin only"}), 403

    client = _get_whop_client()
    if not client:
        return jsonify({"error": "Whop API key not configured"}), 400

    company_id = WHOP_COMPANY_ID
    if not company_id:
        return jsonify({"error": "WHOP_COMPANY_ID not set"}), 400

    try:
        payments = client.payments.list(
            company_id=company_id,
            per=min(int(request.args.get("per", 50)), 100),
        )
        items = []
        for p in payments.data if hasattr(payments, "data") else payments:
            items.append({
                "id": getattr(p, "id", ""),
                "amount": getattr(p, "amount", 0),
                "currency": getattr(p, "currency", "usd"),
                "status": getattr(p, "status", ""),
                "membership_id": getattr(p, "membership_id", ""),
                "created_at": str(getattr(p, "created_at", "")),
            })
        return jsonify({"payments": items, "count": len(items)})
    except Exception as e:
        logger.error("Failed to pull Whop payments: %s", e)
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# 7. DATABASE TABLES
# ═════════════════════════════════════════════════════════════════════════════

def init_whop_tables():
    """Create Whop-related tables if they don't exist."""
    with db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whop_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                membership_id TEXT UNIQUE,
                tier TEXT DEFAULT 'clipper_basic',
                status TEXT DEFAULT 'active',
                videos_remaining INTEGER DEFAULT 3,
                activated_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whop_payments (
                id SERIAL PRIMARY KEY,
                membership_id TEXT,
                amount_cents INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'usd',
                status TEXT DEFAULT 'pending',
                whop_payment_id TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
