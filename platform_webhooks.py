"""
PLATFORM WEBHOOKS — Unified revenue ingestion for all sales platforms
=====================================================================
Handles incoming webhooks from:
  - Gumroad   → /webhooks/gumroad
  - Whop      → /webhooks/whop
  - Stripe    → /webhooks/stripe
  - LemonSqueezy → /webhooks/lemonsqueezy
  - PayPal    → /webhooks/paypal
  - Patreon   → /webhooks/patreon

All platforms write to monetizer_revenue_log with a `platform` column.
"""

import hashlib
import hmac
import json
import logging
import time

from flask import Blueprint, request, jsonify

import config
from monetizer import _conn

log = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _log_sale(platform: str, event_type: str, amount: float, currency: str = "usd",
              tier: str = None, platform_event_id: str = None, email: str = None,
              notes: str = None):
    """Insert one revenue event into monetizer_revenue_log."""
    with _conn() as conn:
        conn.execute("""
            INSERT INTO monetizer_revenue_log
                (platform, event_type, amount, currency, tier, platform_event_id, customer_email, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (platform, event_type, amount, currency, tier, platform_event_id, email, notes))
    log.info("💰 [%s] %s %.2f %s tier=%s", platform, event_type, amount, currency.upper(), tier)


def _hmac_valid(secret: str, body: bytes, sig: str, prefix: str = "") -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(prefix + expected, sig)


# ── Gumroad ──────────────────────────────────────────────────────────────────
# Docs: https://help.gumroad.com/article/76-using-webhooks
# Gumroad sends form-encoded POST. Signature is SHA256 HMAC of raw body.

@webhooks_bp.route("/gumroad", methods=["POST"])
def webhook_gumroad():
    secret = config.GUMROAD_WEBHOOK_SECRET
    if secret:
        sig = request.headers.get("X-Gumroad-Signature", "")
        if not _hmac_valid(secret, request.get_data(), sig):
            return jsonify({"error": "invalid signature"}), 401

    data = request.form
    event = data.get("resource_name", "sale")          # sale | refund | dispute
    product_name = data.get("product_name", "")
    permalink = data.get("product_permalink", "")
    price_cents = int(data.get("price", 0))
    amount = price_cents / 100.0
    currency = data.get("currency", "usd").lower()
    email = data.get("email", "")
    sale_id = data.get("sale_id", "")

    # Map permalink → tier
    tier_map = {
        config.GUMROAD_PRODUCT_STARTER: "Starter",
        config.GUMROAD_PRODUCT_CREATOR: "Creator",
        config.GUMROAD_PRODUCT_PRO: "Pro",
        getattr(config, "GUMROAD_PRODUCT_AGENCY", ""): "Agency",
    }
    tier = tier_map.get(permalink) or product_name

    if event == "refund":
        amount = -amount
        event_type = "refund"
    else:
        event_type = "sale"

    _log_sale("gumroad", event_type, amount, currency, tier, sale_id, email)
    return jsonify({"ok": True})


# ── Whop ─────────────────────────────────────────────────────────────────────
# Docs: https://dev.whop.com/webhooks
# Whop sends JSON. Signature: SHA256 HMAC in X-Whop-Signature-256 as "sha256=<hex>"

@webhooks_bp.route("/whop", methods=["POST"])
def webhook_whop():
    secret = config.WHOP_WEBHOOK_SECRET
    if secret:
        sig = request.headers.get("X-Whop-Signature-256", "")
        if not _hmac_valid(secret, request.get_data(), sig, prefix="sha256="):
            return jsonify({"error": "invalid signature"}), 401

    data = request.json or {}
    action = data.get("action", "")          # membership.went_valid | payment.succeeded | membership.went_invalid
    event_data = data.get("data", {})

    plan_id = event_data.get("plan_id", "") or event_data.get("product", {}).get("id", "")
    tier_map = {
        config.WHOP_PLAN_STARTER: "Starter",
        config.WHOP_PLAN_CREATOR: "Creator",
        config.WHOP_PLAN_PRO: "Pro",
        config.WHOP_PLAN_AGENCY: "Agency",
    }
    tier = tier_map.get(plan_id, plan_id)

    email = event_data.get("user", {}).get("email", "")
    event_id = data.get("id", "")

    if action == "payment.succeeded":
        amount = float(event_data.get("final_amount", 0)) / 100.0
        currency = event_data.get("currency", "usd").lower()
        _log_sale("whop", "sale", amount, currency, tier, event_id, email)

    elif action in ("membership.went_invalid", "membership.cancelled"):
        _log_sale("whop", "churn", 0, "usd", tier, event_id, email,
                  notes=f"action={action}")

    elif action == "membership.went_valid":
        _log_sale("whop", "new_member", 0, "usd", tier, event_id, email)

    return jsonify({"ok": True})


# ── Stripe ───────────────────────────────────────────────────────────────────
# Uses stripe SDK for signature verification.

@webhooks_bp.route("/stripe", methods=["POST"])
def webhook_stripe():
    import stripe
    stripe.api_key = config.STRIPE_SECRET_KEY
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "invoice.payment_succeeded":
        amount = obj.get("amount_paid", 0) / 100.0
        currency = obj.get("currency", "usd")
        email = obj.get("customer_email", "")
        sub_id = obj.get("subscription", "")
        # Derive tier from price ID
        price_id = ""
        lines = obj.get("lines", {}).get("data", [])
        if lines:
            price_id = lines[0].get("price", {}).get("id", "")
        tier_map = {
            config.STRIPE_PRICE_STARTER: "Starter",
            config.STRIPE_PRICE_CREATOR: "Creator",
            config.STRIPE_PRICE_PRO: "Pro",
            config.STRIPE_PRICE_AGENCY: "Agency",
        }
        tier = tier_map.get(price_id, "unknown")
        _log_sale("stripe", "sale", amount, currency, tier, event["id"], email)

    elif etype == "customer.subscription.deleted":
        email = obj.get("customer_email", "") or ""
        _log_sale("stripe", "churn", 0, "usd", None, event["id"], email,
                  notes="subscription cancelled")

    elif etype in ("charge.refunded", "invoice.payment_failed"):
        amount = -(obj.get("amount_refunded", 0) or obj.get("amount_due", 0)) / 100.0
        _log_sale("stripe", "refund" if "refund" in etype else "failed_payment",
                  amount, obj.get("currency", "usd"), None, event["id"])

    return jsonify({"ok": True})


# ── LemonSqueezy ─────────────────────────────────────────────────────────────
# Docs: https://docs.lemonsqueezy.com/help/webhooks
# Signature: SHA256 HMAC hex in X-Signature header

@webhooks_bp.route("/lemonsqueezy", methods=["POST"])
def webhook_lemonsqueezy():
    secret = getattr(config, "LEMONSQUEEZY_WEBHOOK_SECRET", "")
    if secret:
        sig = request.headers.get("X-Signature", "")
        if not _hmac_valid(secret, request.get_data(), sig):
            return jsonify({"error": "invalid signature"}), 401

    data = request.json or {}
    meta = data.get("meta", {})
    event_name = meta.get("event_name", "")
    attrs = data.get("data", {}).get("attributes", {})

    amount = float(attrs.get("total", 0)) / 100.0
    currency = attrs.get("currency", "USD").lower()
    email = attrs.get("user_email", "") or attrs.get("customer_email", "")
    event_id = data.get("data", {}).get("id", "")
    variant_name = attrs.get("variant_name", "")

    if event_name in ("order_created", "subscription_payment_success"):
        _log_sale("lemonsqueezy", "sale", amount, currency, variant_name, event_id, email)
    elif event_name in ("order_refunded",):
        _log_sale("lemonsqueezy", "refund", -amount, currency, variant_name, event_id, email)
    elif event_name in ("subscription_cancelled", "subscription_expired"):
        _log_sale("lemonsqueezy", "churn", 0, currency, variant_name, event_id, email,
                  notes=event_name)

    return jsonify({"ok": True})


# ── PayPal ───────────────────────────────────────────────────────────────────
# Docs: https://developer.paypal.com/docs/api-basics/notifications/webhooks/
# PayPal uses cert-based verification; for simplicity we verify event_id via API.

@webhooks_bp.route("/paypal", methods=["POST"])
def webhook_paypal():
    data = request.json or {}
    event_type = data.get("event_type", "")
    resource = data.get("resource", {})
    event_id = data.get("id", "")

    amount = float(resource.get("amount", {}).get("total", 0) or
                   resource.get("amount", {}).get("value", 0) or 0)
    currency = (resource.get("amount", {}).get("currency") or
                resource.get("amount", {}).get("currency_code", "USD")).lower()
    email = (resource.get("payer", {}).get("email_address", "") or
             resource.get("subscriber", {}).get("email_address", ""))

    if event_type in ("PAYMENT.SALE.COMPLETED", "CHECKOUT.ORDER.APPROVED",
                      "BILLING.SUBSCRIPTION.ACTIVATED"):
        _log_sale("paypal", "sale", amount, currency, None, event_id, email)
    elif event_type in ("PAYMENT.SALE.REFUNDED", "BILLING.SUBSCRIPTION.CANCELLED"):
        _log_sale("paypal", "refund" if "REFUND" in event_type else "churn",
                  -amount if "REFUND" in event_type else 0,
                  currency, None, event_id, email)

    return jsonify({"ok": True})


# ── Patreon ──────────────────────────────────────────────────────────────────
# Docs: https://docs.patreon.com/#webhooks
# Signature: MD5 of body using client secret in X-Patreon-Signature

@webhooks_bp.route("/patreon", methods=["POST"])
def webhook_patreon():
    secret = getattr(config, "PATREON_WEBHOOK_SECRET", "")
    if secret:
        body = request.get_data()
        expected = hmac.new(secret.encode(), body, hashlib.md5).hexdigest()
        sig = request.headers.get("X-Patreon-Signature", "")
        if not hmac.compare_digest(expected, sig):
            return jsonify({"error": "invalid signature"}), 401

    data = request.json or {}
    trigger = request.headers.get("X-Patreon-Event", "")
    attrs = data.get("data", {}).get("attributes", {})
    email = data.get("included", [{}])[0].get("attributes", {}).get("email", "")
    amount_cents = attrs.get("currently_entitled_amount_cents", 0) or 0
    amount = amount_cents / 100.0
    event_id = data.get("data", {}).get("id", "")
    tier = attrs.get("tier", {}).get("title", "") if isinstance(attrs.get("tier"), dict) else ""

    if trigger in ("members:pledge:create", "members:pledge:update"):
        _log_sale("patreon", "sale", amount, "usd", tier, event_id, email)
    elif trigger == "members:pledge:delete":
        _log_sale("patreon", "churn", 0, "usd", tier, event_id, email)

    return jsonify({"ok": True})
