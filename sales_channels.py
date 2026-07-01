"""Sales Channels Blueprint — Whop, Gumroad, LemonSqueezy, AppSumo, PayPal, Affiliates."""
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, redirect, url_for, render_template, make_response
from flask_login import login_required, current_user

import config
import database as db

log = logging.getLogger(__name__)
sales_bp = Blueprint("sales", __name__)

TIER_ORDER = ["free", "starter", "creator", "pro", "agency"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _product_to_tier(channel: str, product_id: str) -> str | None:
    mapping = {
        "whop": {
            config.WHOP_PLAN_STARTER: "starter",
            config.WHOP_PLAN_CREATOR: "creator",
            config.WHOP_PLAN_PRO: "pro",
            config.WHOP_PLAN_AGENCY: "agency",
        },
        "gumroad": {
            config.GUMROAD_PRODUCT_STARTER: "starter",
            config.GUMROAD_PRODUCT_CREATOR: "creator",
            config.GUMROAD_PRODUCT_PRO: "pro",
            config.GUMROAD_PRODUCT_AGENCY: "agency",
        },
        "lemonsqueezy": {
            config.LEMONSQUEEZY_VARIANT_STARTER: "starter",
            config.LEMONSQUEEZY_VARIANT_CREATOR: "creator",
            config.LEMONSQUEEZY_VARIANT_PRO: "pro",
            config.LEMONSQUEEZY_VARIANT_AGENCY: "agency",
        },
        "paypal": {
            config.PAYPAL_PLAN_STARTER: "starter",
            config.PAYPAL_PLAN_CREATOR: "creator",
            config.PAYPAL_PLAN_PRO: "pro",
            config.PAYPAL_PLAN_AGENCY: "agency",
        },
    }
    channel_map = mapping.get(channel, {})
    return channel_map.get(product_id) if product_id else None


def _activate_subscription(email: str, tier: str, channel: str, external_id: str = ""):
    user = db.get_user_by_email(email)
    if not user:
        log.warning(f"[{channel}] No user found for {email} — creating account")
        password_hash = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()
        user_id = db.create_user(email=email, password_hash=password_hash, name=email.split("@")[0])
        user = db.get_user_by_id(user_id)
    db.update_user(user["id"],
                   subscription_tier=tier,
                   subscription_status="active",
                   subscription_channel=channel,
                   subscription_external_id=external_id)
    log.info(f"[{channel}] Activated {tier} for {email} (ext: {external_id})")
    return user


def _cancel_subscription(email: str = None, external_id: str = "", channel: str = ""):
    user = None
    if email:
        user = db.get_user_by_email(email)
    if not user and external_id:
        user = _find_user_by_external_id(external_id, channel)
    if user:
        db.update_user(user["id"],
                       subscription_tier="free",
                       subscription_status="cancelled")
        log.info(f"[{channel}] Cancelled subscription for {user['email']}")
    else:
        log.warning(f"[{channel}] Cancel: no user found (email={email}, ext={external_id})")


def _find_user_by_external_id(external_id: str, channel: str):
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE subscription_external_id=? AND subscription_channel=?",
            (external_id, channel)).fetchone()
        return dict(row) if row else None


def _verify_hmac(payload: bytes, signature: str, secret: str, algo="sha256") -> bool:
    if not secret:
        log.error("Webhook secret not configured — rejecting webhook (fail closed).")
        return False
    if not signature:
        return False
    expected = hmac.new(secret.encode(), payload, getattr(hashlib, algo)).hexdigest()
    return hmac.compare_digest(expected, signature)


# ═════════════════════════════════════════════════════════════════════════════
# WHOP
# ═════════════════════════════════════════════════════════════════════════════

@sales_bp.route("/whop/webhook", methods=["POST"])
def whop_webhook():
    payload = request.get_data()
    sig = request.headers.get("Whop-Signature", "")
    if not _verify_hmac(payload, sig, config.WHOP_WEBHOOK_SECRET):
        return jsonify({"error": "invalid signature"}), 401

    data = request.get_json(silent=True) or {}
    event = data.get("event", "")
    membership = data.get("data", {})
    email = membership.get("email", "") or membership.get("user", {}).get("email", "")
    plan_id = membership.get("plan_id", "") or membership.get("product_id", "")
    membership_id = membership.get("id", "")

    if event in ("membership.went_valid", "membership.created"):
        tier = _product_to_tier("whop", plan_id) or "starter"
        _activate_subscription(email, tier, "whop", membership_id)
    elif event in ("membership.went_invalid", "membership.cancelled"):
        _cancel_subscription(email=email, external_id=membership_id, channel="whop")
    else:
        log.info(f"[whop] Unhandled event: {event}")

    return jsonify({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# GUMROAD
# ═════════════════════════════════════════════════════════════════════════════

@sales_bp.route("/gumroad/webhook", methods=["POST"])
def gumroad_webhook():
    data = request.form.to_dict() if request.content_type and "form" in request.content_type else (request.get_json(silent=True) or {})

    email = data.get("email", "") or data.get("purchaser_id", "")
    product_id = data.get("product_id", "") or data.get("product_permalink", "")
    sale_id = data.get("sale_id", "")
    resource_name = data.get("resource_name", "")

    if resource_name in ("sale", ""):
        tier = _product_to_tier("gumroad", product_id) or "starter"
        if email:
            _activate_subscription(email, tier, "gumroad", sale_id)
    elif resource_name in ("refund", "cancellation", "subscription_ended"):
        _cancel_subscription(email=email, external_id=sale_id, channel="gumroad")

    return jsonify({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# LEMONSQUEEZY
# ═════════════════════════════════════════════════════════════════════════════

@sales_bp.route("/lemonsqueezy/webhook", methods=["POST"])
def lemonsqueezy_webhook():
    payload = request.get_data()
    sig = request.headers.get("X-Signature", "")
    if not _verify_hmac(payload, sig, config.LEMONSQUEEZY_WEBHOOK_SECRET):
        return jsonify({"error": "invalid signature"}), 401

    data = request.get_json(silent=True) or {}
    event = data.get("meta", {}).get("event_name", "")
    attrs = data.get("data", {}).get("attributes", {})
    email = attrs.get("user_email", "")
    variant_id = str(attrs.get("variant_id", "") or attrs.get("first_order_item", {}).get("variant_id", ""))
    sub_id = str(data.get("data", {}).get("id", ""))

    if event in ("subscription_created", "subscription_updated", "subscription_resumed",
                 "order_created", "subscription_payment_success"):
        status = attrs.get("status", "active")
        if status in ("active", "on_trial", "paid"):
            tier = _product_to_tier("lemonsqueezy", variant_id) or "starter"
            _activate_subscription(email, tier, "lemonsqueezy", sub_id)
        elif status in ("cancelled", "expired", "unpaid"):
            _cancel_subscription(email=email, external_id=sub_id, channel="lemonsqueezy")
    elif event in ("subscription_cancelled", "subscription_expired"):
        _cancel_subscription(email=email, external_id=sub_id, channel="lemonsqueezy")

    return jsonify({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# APPSUMO
# ═════════════════════════════════════════════════════════════════════════════

APPSUMO_TIER_MAP = {1: "starter", 2: "creator", 3: "pro", 4: "agency", 5: "agency"}

@sales_bp.route("/appsumo/webhook", methods=["POST"])
def appsumo_webhook():
    payload = request.get_data()
    sig = request.headers.get("X-AppSumo-Signature", "")
    if not _verify_hmac(payload, sig, config.APPSUMO_WEBHOOK_SECRET):
        return jsonify({"error": "invalid signature"}), 401

    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    email = data.get("activation_email", "") or data.get("email", "")
    plan_id = data.get("plan_id", "")
    uuid_code = data.get("uuid", "")
    tier_num = data.get("tier", 1)

    if action == "activate":
        tier = APPSUMO_TIER_MAP.get(tier_num, "starter")
        _activate_subscription(email, tier, "appsumo", uuid_code)
    elif action == "enhance":
        tier = APPSUMO_TIER_MAP.get(tier_num, "creator")
        _activate_subscription(email, tier, "appsumo", uuid_code)
    elif action in ("reduce", "deactivate"):
        if action == "deactivate":
            _cancel_subscription(email=email, external_id=uuid_code, channel="appsumo")
        else:
            tier = APPSUMO_TIER_MAP.get(tier_num, "starter")
            _activate_subscription(email, tier, "appsumo", uuid_code)
    elif action == "refund":
        _cancel_subscription(email=email, external_id=uuid_code, channel="appsumo")

    return jsonify({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# PAYPAL
# ═════════════════════════════════════════════════════════════════════════════

def _paypal_base_url():
    return "https://api-m.paypal.com" if config.PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"


def _paypal_verify_webhook(headers: dict, body: bytes) -> bool:
    if not config.PAYPAL_WEBHOOK_ID:
        log.error("PAYPAL_WEBHOOK_ID is not configured — rejecting webhook (fail closed).")
        return False
    import requests as _req
    try:
        token_resp = _req.post(f"{_paypal_base_url()}/v1/oauth2/token",
                               auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET),
                               data={"grant_type": "client_credentials"}, timeout=10)
        token = token_resp.json().get("access_token", "")
        verify_resp = _req.post(f"{_paypal_base_url()}/v1/notifications/verify-webhook-signature",
                                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                json={
                                    "auth_algo": headers.get("PAYPAL-AUTH-ALGO", ""),
                                    "cert_url": headers.get("PAYPAL-CERT-URL", ""),
                                    "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID", ""),
                                    "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG", ""),
                                    "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME", ""),
                                    "webhook_id": config.PAYPAL_WEBHOOK_ID,
                                    "webhook_event": json.loads(body),
                                }, timeout=10)
        return verify_resp.json().get("verification_status") == "SUCCESS"
    except Exception as e:
        log.error(f"[paypal] Webhook verification failed: {e}")
        return False


@sales_bp.route("/paypal/webhook", methods=["POST"])
def paypal_webhook():
    body = request.get_data()
    if not _paypal_verify_webhook(dict(request.headers), body):
        return jsonify({"error": "invalid signature"}), 401

    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type", "")
    resource = data.get("resource", {})

    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
        email = resource.get("subscriber", {}).get("email_address", "")
        plan_id = resource.get("plan_id", "")
        sub_id = resource.get("id", "")
        tier = _product_to_tier("paypal", plan_id) or "starter"
        if email:
            _activate_subscription(email, tier, "paypal", sub_id)

    elif event_type in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.SUSPENDED",
                        "BILLING.SUBSCRIPTION.EXPIRED"):
        sub_id = resource.get("id", "")
        email = resource.get("subscriber", {}).get("email_address", "")
        _cancel_subscription(email=email, external_id=sub_id, channel="paypal")

    elif event_type == "CHECKOUT.ORDER.APPROVED":
        payer = resource.get("payer", {})
        email = payer.get("email_address", "")
        order_id = resource.get("id", "")
        items = resource.get("purchase_units", [{}])[0].get("items", [])
        if items and email:
            sku = items[0].get("sku", "")
            tier_map = {"starter": "starter", "creator": "creator", "pro": "pro", "agency": "agency"}
            tier = tier_map.get(sku, "starter")
            _activate_subscription(email, tier, "paypal", order_id)

    return jsonify({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# STRIPE PAYMENT LINKS
# ═════════════════════════════════════════════════════════════════════════════

@sales_bp.route("/stripe/payment-link/webhook", methods=["POST"])
def stripe_payment_link_webhook():
    import stripe as _stripe
    _stripe.api_key = config.STRIPE_SECRET_KEY
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = _stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "invalid signature"}), 401

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email", "") or session.get("customer_details", {}).get("email", "")
        metadata = session.get("metadata", {})
        tier = metadata.get("tier", "starter")
        sub_id = session.get("subscription", "") or session.get("id", "")
        if email and tier in TIER_ORDER:
            _activate_subscription(email, tier, "stripe_link", sub_id)

    return jsonify({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# AFFILIATE PROGRAM
# ═════════════════════════════════════════════════════════════════════════════

@sales_bp.route("/ref/<code>")
def affiliate_link(code):
    with db._get_conn() as conn:
        aff = conn.execute("SELECT * FROM affiliates WHERE code=? AND active=1", (code,)).fetchone()
    if not aff:
        return redirect(url_for("pricing"))
    resp = make_response(redirect(url_for("pricing")))
    resp.set_cookie("ref", code, max_age=config.AFFILIATE_COOKIE_DAYS * 86400,
                    httponly=True, samesite="Lax", secure=True)
    return resp


@sales_bp.route("/api/affiliates/dashboard")
@login_required
def affiliate_dashboard_api():
    with db._get_conn() as conn:
        aff = conn.execute("SELECT * FROM affiliates WHERE user_id=?", (current_user.id,)).fetchone()
        if not aff:
            return jsonify({"error": "Not an affiliate"}), 404
        aff = dict(aff)
        referrals = conn.execute(
            "SELECT id, email, subscription_tier, created_at FROM users WHERE referred_by=? ORDER BY created_at DESC LIMIT 50",
            (aff["code"],)).fetchall()
        earnings = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total, COALESCE(SUM(CASE WHEN paid=0 THEN amount ELSE 0 END), 0) as pending "
            "FROM affiliate_earnings WHERE affiliate_id=?", (aff["id"],)).fetchone()
    return jsonify({
        "code": aff["code"],
        "link": f"{config.APP_BASE_URL}/ref/{aff['code']}",
        "commission_pct": config.AFFILIATE_COMMISSION_PCT,
        "total_earnings": earnings["total"] if earnings else 0,
        "pending_earnings": earnings["pending"] if earnings else 0,
        "referrals": [dict(r) for r in referrals],
        "referral_count": len(referrals),
    })


@sales_bp.route("/api/affiliates/join", methods=["POST"])
@login_required
def affiliate_join():
    with db._get_conn() as conn:
        existing = conn.execute("SELECT id FROM affiliates WHERE user_id=?", (current_user.id,)).fetchone()
        if existing:
            aff = conn.execute("SELECT * FROM affiliates WHERE id=?", (existing["id"],)).fetchone()
            return jsonify({"code": aff["code"], "link": f"{config.APP_BASE_URL}/ref/{aff['code']}"})
        code = current_user.email.split("@")[0].lower().replace(".", "").replace("+", "")[:12]
        code = code + str(current_user.id)
        conn.execute(
            "INSERT INTO affiliates (user_id, code, commission_pct, active) VALUES (?, ?, ?, 1)",
            (current_user.id, code, config.AFFILIATE_COMMISSION_PCT))
        conn.commit()
    return jsonify({"code": code, "link": f"{config.APP_BASE_URL}/ref/{code}"})


def track_affiliate_conversion(user_id: int, tier: str, amount: float):
    with db._get_conn() as conn:
        user = conn.execute("SELECT referred_by FROM users WHERE id=?", (user_id,)).fetchone()
        if not user or not user["referred_by"]:
            return
        aff = conn.execute("SELECT * FROM affiliates WHERE code=? AND active=1",
                           (user["referred_by"],)).fetchone()
        if not aff:
            return
        commission = round(amount * (aff["commission_pct"] / 100), 2)
        conn.execute(
            "INSERT INTO affiliate_earnings (affiliate_id, user_id, tier, amount, paid) VALUES (?, ?, ?, ?, 0)",
            (aff["id"], user_id, tier, commission))
        conn.commit()
        log.info(f"[affiliate] ${commission} commission for {aff['code']} from user {user_id} ({tier})")


# ═════════════════════════════════════════════════════════════════════════════
# SALES CHANNEL STATUS API (admin)
# ═════════════════════════════════════════════════════════════════════════════

@sales_bp.route("/api/admin/sales-channels")
@login_required
def sales_channels_status():
    if not current_user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    channels = {
        "whop": {
            "configured": bool(config.WHOP_WEBHOOK_SECRET),
            "webhook_url": f"{config.APP_BASE_URL}/whop/webhook",
            "plans": {"starter": config.WHOP_PLAN_STARTER, "creator": config.WHOP_PLAN_CREATOR,
                      "pro": config.WHOP_PLAN_PRO, "agency": config.WHOP_PLAN_AGENCY},
        },
        "stripe": {
            "configured": bool(config.STRIPE_SECRET_KEY),
            "webhook_url": f"{config.APP_BASE_URL}/stripe/payment-link/webhook",
            "plans": {"starter": config.STRIPE_PRICE_STARTER, "creator": config.STRIPE_PRICE_CREATOR,
                      "pro": config.STRIPE_PRICE_PRO, "agency": config.STRIPE_PRICE_AGENCY},
        },
        "gumroad": {
            "configured": bool(config.GUMROAD_ACCESS_TOKEN),
            "webhook_url": f"{config.APP_BASE_URL}/gumroad/webhook",
            "products": {"starter": config.GUMROAD_PRODUCT_STARTER, "creator": config.GUMROAD_PRODUCT_CREATOR,
                         "pro": config.GUMROAD_PRODUCT_PRO, "agency": config.GUMROAD_PRODUCT_AGENCY},
        },
        "lemonsqueezy": {
            "configured": bool(config.LEMONSQUEEZY_API_KEY),
            "webhook_url": f"{config.APP_BASE_URL}/lemonsqueezy/webhook",
            "variants": {"starter": config.LEMONSQUEEZY_VARIANT_STARTER, "creator": config.LEMONSQUEEZY_VARIANT_CREATOR,
                         "pro": config.LEMONSQUEEZY_VARIANT_PRO, "agency": config.LEMONSQUEEZY_VARIANT_AGENCY},
        },
        "appsumo": {
            "configured": bool(config.APPSUMO_API_KEY),
            "webhook_url": f"{config.APP_BASE_URL}/appsumo/webhook",
            "product_id": config.APPSUMO_PRODUCT_ID,
        },
        "paypal": {
            "configured": bool(config.PAYPAL_CLIENT_ID),
            "webhook_url": f"{config.APP_BASE_URL}/paypal/webhook",
            "mode": config.PAYPAL_MODE,
            "plans": {"starter": config.PAYPAL_PLAN_STARTER, "creator": config.PAYPAL_PLAN_CREATOR,
                      "pro": config.PAYPAL_PLAN_PRO, "agency": config.PAYPAL_PLAN_AGENCY},
        },
        "affiliates": {
            "configured": True,
            "commission_pct": config.AFFILIATE_COMMISSION_PCT,
            "cookie_days": config.AFFILIATE_COOKIE_DAYS,
            "link_format": f"{config.APP_BASE_URL}/ref/{{code}}",
        },
    }
    with db._get_conn() as conn:
        for ch in ["whop", "gumroad", "lemonsqueezy", "appsumo", "paypal", "stripe_link"]:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM users WHERE subscription_channel=?", (ch,)).fetchone()
            if ch in channels:
                channels[ch]["active_subscribers"] = count["c"] if count else 0
        aff_count = conn.execute("SELECT COUNT(*) as c FROM affiliates WHERE active=1").fetchone()
        channels["affiliates"]["active_affiliates"] = aff_count["c"] if aff_count else 0
    return jsonify(channels)
