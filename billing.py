"""Billing Blueprint — Stripe checkout, portal, webhook."""
import logging
import stripe
from flask import Blueprint, request, redirect, render_template, url_for, jsonify
from flask_login import login_required, current_user
import config
import database as db

log = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

stripe.api_key = config.STRIPE_SECRET_KEY

TIER_ORDER = ["free", "starter", "creator", "pro", "agency"]


@billing_bp.route("/")
@login_required
def billing_page():
    current_user._d = db.get_user_by_id(current_user.id)  # refresh
    db.reset_usage_if_new_period(current_user.id)
    tier = config.TIERS.get(current_user.subscription_tier, config.TIERS["free"])
    videos_limit = tier["videos_per_month"]
    videos_used = current_user.videos_used_this_month or 0
    credits_used = current_user.credits_used or 0
    pct = 0
    if videos_limit > 0:
        pct = min(100, round(videos_used / videos_limit * 100))
    elif videos_limit == -1:
        pct = 0  # unlimited
    credits_pct = 0
    credits_limit = tier["higgsfield_credits"]
    if credits_limit > 0:
        credits_pct = min(100, round(credits_used / credits_limit * 100))
    return render_template(
        "billing.html",
        tiers=config.TIERS,
        current_tier=current_user.subscription_tier,
        tier_data=tier,
        videos_used=videos_used,
        videos_limit=videos_limit,
        usage_pct=pct,
        credits_used=credits_used,
        credits_limit=credits_limit,
        credits_pct=credits_pct,
        stripe_pub=config.STRIPE_PUBLISHABLE_KEY,
    )


@billing_bp.route("/checkout/<tier_name>")
@login_required
def checkout(tier_name):
    if tier_name not in config.TIERS or tier_name == "free":
        return redirect(url_for("billing.billing_page"))

    tier = config.TIERS[tier_name]
    price_id = tier.get("stripe_price_id")
    if not price_id:
        return render_template("billing.html",
                               error="Stripe is not configured. Add STRIPE_PRICE_* keys to your .env.",
                               tiers=config.TIERS, current_tier=current_user.subscription_tier,
                               tier_data=config.TIERS.get(current_user.subscription_tier, config.TIERS["free"]),
                               videos_used=0, videos_limit=0, usage_pct=0,
                               credits_used=0, credits_limit=0,
                               stripe_pub=config.STRIPE_PUBLISHABLE_KEY), 400

    # Create or retrieve Stripe customer
    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(email=current_user.email, name=current_user.name)
        customer_id = customer.id
        db.update_user(current_user.id, stripe_customer_id=customer_id)

    trial_days = tier.get("trial_days", 0)
    subscription_data = {"metadata": {"user_id": str(current_user.id), "tier": tier_name}}
    if trial_days:
        subscription_data["trial_period_days"] = trial_days
        subscription_data["trial_settings"] = {
            "end_behavior": {"missing_payment_method": "cancel"}
        }

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        payment_method_collection="always",
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=config.APP_BASE_URL + url_for("billing.checkout_success") + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=config.APP_BASE_URL + url_for("billing.billing_page"),
        client_reference_id=str(current_user.id),
        metadata={"user_id": str(current_user.id), "tier": tier_name},
        subscription_data=subscription_data,
        allow_promotion_codes=True,
    )
    return redirect(session.url, code=303)


@billing_bp.route("/checkout/credits/<int:package_id>")
@login_required
def checkout_credits(package_id):
    packages = {int(p["id"]): p for p in db.get_credit_packages()}
    pkg = packages.get(package_id)
    if not pkg:
        return redirect(url_for("credits_page"))

    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(email=current_user.email, name=current_user.name)
        customer_id = customer.id
        db.update_user(current_user.id, stripe_customer_id=customer_id)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"{pkg['name']} — Credit Pack"},
                "unit_amount": int(round(float(pkg["price_usd"]) * 100)),
            },
            "quantity": 1,
        }],
        success_url=config.APP_BASE_URL + url_for("credits_page") + "?purchase=success",
        cancel_url=config.APP_BASE_URL + url_for("credits_page"),
        client_reference_id=str(current_user.id),
        metadata={"user_id": str(current_user.id), "credit_package_id": str(package_id)},
    )
    return redirect(session.url, code=303)


@billing_bp.route("/success")
@login_required
def checkout_success():
    session_id = request.args.get("session_id")
    if session_id and config.STRIPE_SECRET_KEY:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            tier_name = session.metadata.get("tier")
            sub_id = session.subscription
            if tier_name and sub_id:
                db.update_user(
                    current_user.id,
                    subscription_tier=tier_name,
                    subscription_status="active",
                    stripe_subscription_id=sub_id,
                    videos_used=0,
                    credits_used=0,
                )
        except Exception:
            pass
    return redirect(url_for("billing.billing_page"))


@billing_bp.route("/portal")
@login_required
def portal():
    customer_id = current_user.stripe_customer_id
    if not customer_id or not config.STRIPE_SECRET_KEY:
        return redirect(url_for("billing.billing_page"))
    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=config.APP_BASE_URL + url_for("billing.billing_page"),
    )
    return redirect(portal_session.url, code=303)


@billing_bp.route("/portal-api", methods=["POST"])
@login_required
def portal_api():
    """JSON endpoint for Stripe Customer Portal — returns {url: ...}."""
    customer_id = current_user.stripe_customer_id
    if not customer_id or not config.STRIPE_SECRET_KEY:
        return jsonify({"error": "No billing account found"}), 400
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=config.APP_BASE_URL + url_for("billing.billing_page"),
        )
        return jsonify({"url": portal_session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@billing_bp.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    if not config.STRIPE_WEBHOOK_SECRET:
        log.error("STRIPE_WEBHOOK_SECRET is not set — rejecting webhook (fail closed). "
                  "Set STRIPE_WEBHOOK_SECRET to accept real Stripe events.")
        return jsonify({"error": "Webhook not configured"}), 503

    try:
        event = stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({"error": "Invalid signature"}), 400

    etype = event["type"]
    data  = event["data"]["object"]

    if etype in ("customer.subscription.updated", "customer.subscription.created"):
        _handle_subscription(data)
    elif etype == "customer.subscription.deleted":
        _handle_subscription_deleted(data)
    elif etype == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif etype == "invoice.payment_succeeded":
        _handle_payment_succeeded(data)
    elif etype == "invoice.payment_failed":
        _handle_payment_failed(data)

    return jsonify({"received": True})


def _handle_subscription(sub):
    user = db.get_user_by_stripe_subscription(sub["id"])
    if not user:
        cid = sub.get("customer")
        user = db.get_user_by_stripe_customer(cid) if cid else None
    if not user:
        return

    tier_name = sub.get("metadata", {}).get("tier")
    if not tier_name:
        # Infer from price ID
        price_id = sub["items"]["data"][0]["price"]["id"] if sub.get("items") else None
        tier_name = _price_to_tier(price_id)

    status = sub.get("status", "active")
    sub_status = "active" if status in ("active", "trialing") else "inactive"

    db.update_user(
        user["id"],
        subscription_tier=tier_name or user["subscription_tier"],
        subscription_status=sub_status,
        stripe_subscription_id=sub["id"],
    )


def _handle_subscription_deleted(sub):
    user = db.get_user_by_stripe_subscription(sub["id"])
    if user:
        db.update_user(user["id"], subscription_tier="free", subscription_status="inactive",
                       stripe_subscription_id=None)


def _handle_checkout_completed(session):
    metadata = session.get("metadata", {}) or {}
    uid = metadata.get("user_id")
    if not uid:
        return

    credit_package_id = metadata.get("credit_package_id")
    if credit_package_id:
        if session.get("payment_status") != "paid":
            return
        packages = {int(p["id"]): p for p in db.get_credit_packages()}
        pkg = packages.get(int(credit_package_id))
        if not pkg:
            return
        credits = float(pkg["credits"])
        bonus = credits * float(pkg.get("bonus_pct", 0)) / 100
        total = credits + bonus
        db.add_credits(int(uid), total, "purchase",
                       f"Purchased {pkg['name']} ({total:.0f} credits)")
        return

    tier_name = metadata.get("tier")
    sub_id = session.get("subscription")
    if tier_name:
        db.update_user(
            int(uid),
            subscription_tier=tier_name,
            subscription_status="active",
            stripe_subscription_id=sub_id,
        )


def _handle_payment_succeeded(invoice):
    """Reset monthly usage on a successful subscription payment (new billing period)."""
    cid = invoice.get("customer")
    if not cid:
        return
    user = db.get_user_by_stripe_customer(cid)
    if not user:
        return
    # Only reset for subscription invoices
    if invoice.get("subscription"):
        db.reset_monthly_usage(user["id"])
    db.update_user(user["id"], subscription_status="active")


def _handle_payment_failed(invoice):
    """Mark user as past_due on a failed invoice payment."""
    cid = invoice.get("customer")
    if not cid:
        return
    user = db.get_user_by_stripe_customer(cid)
    if not user:
        return
    db.update_user(user["id"], subscription_status="past_due")
    try:
        from notifications import send_notification
        send_notification(user["id"], "payment_failed", {"invoice_id": invoice.get("id")})
    except Exception:
        pass


def _price_to_tier(price_id: str) -> str:
    mapping = {
        config.STRIPE_PRICE_STARTER: "starter",
        config.STRIPE_PRICE_CREATOR: "creator",
        config.STRIPE_PRICE_AGENCY:  "agency",
    }
    return mapping.get(price_id, "free")


# ── Usage gate helper ─────────────────────────────────────────────────────────

def check_usage_gate(user_id: int) -> tuple[bool, str]:
    """Returns (allowed, error_message). Enforces per-tier video limits."""
    import database, config
    user = database.get_user_by_id(user_id)
    if not user:
        return False, "User not found"
    if user.get("is_admin"):
        return True, ""
    tier = user.get("subscription_tier", "free")
    tier_cfg = config.TIERS.get(tier, config.TIERS.get("free", {}))
    limit = tier_cfg.get("videos_per_month", 3)
    if limit == -1:
        return True, ""
    used = user.get("videos_used", 0)
    if used >= limit:
        return False, f"You've reached your {tier} plan limit of {limit} videos. Upgrade for more."
    return True, ""
