"""Tests for the billing blueprint and usage gate."""
import json
from unittest.mock import patch, MagicMock

import pytest


class TestUsageGate:
    """check_usage_gate() enforces per-tier limits."""

    def test_free_tier_allows_under_limit(self, db_conn):
        from billing import check_usage_gate
        uid = db_conn.create_user(email="gate1@test.com", password_hash="h")
        allowed, err = check_usage_gate(uid)
        assert allowed is True
        assert err == ""

    def test_free_tier_blocks_over_limit(self, db_conn):
        from billing import check_usage_gate
        uid = db_conn.create_user(email="gate2@test.com", password_hash="h")
        db_conn.update_user(uid, videos_used=10)  # exceeds free limit of 2
        allowed, err = check_usage_gate(uid)
        assert allowed is False
        assert "Upgrade" in err

    def test_agency_unlimited(self, db_conn):
        from billing import check_usage_gate
        uid = db_conn.create_user(email="gate3@test.com", password_hash="h")
        db_conn.update_user(uid, subscription_tier="agency", videos_used=999)
        allowed, err = check_usage_gate(uid)
        assert allowed is True

    def test_nonexistent_user(self, db_conn):
        from billing import check_usage_gate
        allowed, err = check_usage_gate(99999)
        assert allowed is False
        assert "not found" in err.lower()


class TestCheckoutEndpoint:
    """GET /billing/checkout/<tier>"""

    def test_checkout_free_redirects(self, auth_client):
        resp = auth_client.get("/billing/checkout/free", follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_checkout_invalid_tier_redirects(self, auth_client):
        resp = auth_client.get("/billing/checkout/nonexistent", follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_checkout_without_stripe_keys_returns_400(self, auth_client):
        """When Stripe price IDs are empty strings, checkout should return 400."""
        import config
        orig = config.STRIPE_PRICE_STARTER
        config.STRIPE_PRICE_STARTER = ""
        # Also clear it in TIERS
        orig_tier = config.TIERS["starter"]["stripe_price_id"]
        config.TIERS["starter"]["stripe_price_id"] = ""
        try:
            resp = auth_client.get("/billing/checkout/starter", follow_redirects=False)
            assert resp.status_code == 400
        finally:
            config.STRIPE_PRICE_STARTER = orig
            config.TIERS["starter"]["stripe_price_id"] = orig_tier

    def test_checkout_with_stripe_keys(self, auth_client):
        """When Stripe is configured, checkout should redirect to Stripe."""
        import config
        orig_tier = config.TIERS["starter"]["stripe_price_id"]
        orig_key = config.STRIPE_SECRET_KEY
        config.TIERS["starter"]["stripe_price_id"] = "price_test_123"
        config.STRIPE_SECRET_KEY = "sk_test_xxx"
        try:
            with patch("stripe.Customer.create", return_value=MagicMock(id="cus_123")), \
                 patch("stripe.checkout.Session.create",
                       return_value=MagicMock(url="https://checkout.stripe.com/test")):
                import stripe
                stripe.api_key = "sk_test_xxx"
                resp = auth_client.get("/billing/checkout/starter", follow_redirects=False)
                assert resp.status_code == 303
        finally:
            config.TIERS["starter"]["stripe_price_id"] = orig_tier
            config.STRIPE_SECRET_KEY = orig_key


class TestBillingPage:
    """GET /billing/"""

    def test_billing_page_requires_auth(self, client):
        resp = client.get("/billing/", follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert "login" in resp.headers.get("Location", "").lower()

    def test_billing_page_renders(self, auth_client):
        resp = auth_client.get("/billing/")
        assert resp.status_code == 200


class TestWebhook:
    """POST /billing/webhook"""

    def test_webhook_valid_payload_no_secret(self, client, db_conn):
        """When STRIPE_WEBHOOK_SECRET is empty, accept raw JSON."""
        import config
        orig = config.STRIPE_WEBHOOK_SECRET
        config.STRIPE_WEBHOOK_SECRET = ""
        try:
            uid = db_conn.create_user(email="hook@test.com", password_hash="h")
            db_conn.update_user(uid, stripe_subscription_id="sub_test_123")
            payload = {
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_test_123",
                        "customer": "cus_test",
                        "status": "active",
                        "metadata": {"tier": "creator"},
                        "items": {"data": [{"price": {"id": "price_creator_test"}}]},
                    }
                },
            }
            resp = client.post("/billing/webhook",
                               data=json.dumps(payload),
                               content_type="application/json")
            assert resp.status_code == 200
            assert resp.get_json()["received"] is True
        finally:
            config.STRIPE_WEBHOOK_SECRET = orig

    def test_webhook_invalid_signature(self, client):
        """When webhook secret is set, invalid signature should return 400."""
        import config
        orig = config.STRIPE_WEBHOOK_SECRET
        config.STRIPE_WEBHOOK_SECRET = "whsec_test_secret"
        try:
            with patch("stripe.Webhook.construct_event",
                       side_effect=ValueError("Invalid")):
                resp = client.post("/billing/webhook",
                                   data=b"raw_payload",
                                   content_type="application/json",
                                   headers={"Stripe-Signature": "bad_sig"})
                assert resp.status_code == 400
        finally:
            config.STRIPE_WEBHOOK_SECRET = orig

    def test_webhook_checkout_completed(self, client, db_conn):
        """checkout.session.completed updates user tier."""
        import config
        orig = config.STRIPE_WEBHOOK_SECRET
        config.STRIPE_WEBHOOK_SECRET = ""
        try:
            uid = db_conn.create_user(email="checkout@test.com", password_hash="h")
            payload = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "metadata": {"tier": "starter", "user_id": str(uid)},
                        "subscription": "sub_new_123",
                    }
                },
            }
            resp = client.post("/billing/webhook",
                               data=json.dumps(payload),
                               content_type="application/json")
            assert resp.status_code == 200
            user = db_conn.get_user_by_id(uid)
            assert user["subscription_tier"] == "starter"
        finally:
            config.STRIPE_WEBHOOK_SECRET = orig

    def test_webhook_subscription_deleted(self, client, db_conn):
        """customer.subscription.deleted downgrades to free."""
        import config
        orig = config.STRIPE_WEBHOOK_SECRET
        config.STRIPE_WEBHOOK_SECRET = ""
        try:
            uid = db_conn.create_user(email="delsub@test.com", password_hash="h")
            db_conn.update_user(uid, subscription_tier="creator",
                                stripe_subscription_id="sub_del_123")
            payload = {
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_del_123", "customer": "cus_del"}},
            }
            resp = client.post("/billing/webhook",
                               data=json.dumps(payload),
                               content_type="application/json")
            assert resp.status_code == 200
            user = db_conn.get_user_by_id(uid)
            assert user["subscription_tier"] == "free"
        finally:
            config.STRIPE_WEBHOOK_SECRET = orig

    def test_webhook_bad_payload(self, client):
        """Malformed payload should return 400."""
        import config
        orig = config.STRIPE_WEBHOOK_SECRET
        config.STRIPE_WEBHOOK_SECRET = ""
        try:
            resp = client.post("/billing/webhook",
                               data=b"not json",
                               content_type="application/json")
            assert resp.status_code == 400
        finally:
            config.STRIPE_WEBHOOK_SECRET = orig
