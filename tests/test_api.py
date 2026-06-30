"""Tests for API endpoints."""
import json
from unittest.mock import patch



class TestLanding:
    """GET /"""

    def test_landing_page_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_landing_redirects_when_logged_in(self, auth_client):
        resp = auth_client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert "/dashboard" in resp.headers.get("Location", "")


class TestHealthCheck:
    """GET /health"""

    def test_health_returns_200(self, client):
        with patch("generators.higgsfield_cli.is_authenticated", return_value=True):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


class TestSettingsCheck:
    """GET /api/settings/check"""

    def test_settings_check_returns_json(self, client):
        resp = client.get("/api/settings/check")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "anthropic" in data
        assert "pixabay" in data


class TestCreateVideo:
    """POST /api/create"""

    def test_create_requires_auth(self, client):
        resp = client.post("/api/create",
                           data=json.dumps({"topic": "test"}),
                           content_type="application/json")
        assert resp.status_code in (302, 401)

    def test_create_requires_topic(self, auth_client):
        resp = auth_client.post("/api/create",
                                data=json.dumps({"topic": ""}),
                                content_type="application/json")
        assert resp.status_code == 400
        assert "required" in resp.get_json().get("error", "").lower()

    def test_create_success(self, auth_client, db_conn):
        with patch("app._run_job_thread"):
            resp = auth_client.post("/api/create",
                                    data=json.dumps({"topic": "Python Tips"}),
                                    content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "job_id" in data

    def test_create_usage_gate_blocks_over_limit(self, auth_client, db_conn, test_user):
        # Exhaust free tier (2 videos)
        db_conn.update_user(test_user["id"], videos_used=10)
        resp = auth_client.post("/api/create",
                                data=json.dumps({"topic": "Blocked topic"}),
                                content_type="application/json")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data.get("upgrade") is True


class TestJobEndpoints:
    """GET /api/job/<id> and /jobs"""

    def test_get_job_not_found(self, auth_client):
        resp = auth_client.get("/api/job/99999")
        assert resp.status_code == 404

    def test_get_job_success(self, auth_client, db_conn, test_user):
        job_id = db_conn.create_job(
            topic="Test Job", format="short", platforms=["youtube"],
            audience="general", voice="en-US-AriaNeural",
            style="fire", privacy="private", user_id=test_user["id"],
        )
        resp = auth_client.get(f"/api/job/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["topic"] == "Test Job"

    def test_jobs_page(self, auth_client):
        resp = auth_client.get("/jobs")
        assert resp.status_code == 200


class TestAccountEndpoints:
    """Social account CRUD."""

    def test_list_accounts(self, auth_client):
        resp = auth_client.get("/api/accounts")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_connect_account(self, auth_client):
        resp = auth_client.post("/api/accounts/connect",
                                data=json.dumps({
                                    "platform": "youtube",
                                    "username": "testchannel",
                                    "display_name": "Test Channel",
                                }),
                                content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "connected"

    def test_connect_account_missing_fields(self, auth_client):
        resp = auth_client.post("/api/accounts/connect",
                                data=json.dumps({"platform": ""}),
                                content_type="application/json")
        assert resp.status_code == 400

    def test_delete_account(self, auth_client, db_conn, test_user):
        acc_id = db_conn.upsert_account(
            platform="tiktok", username="tiktokuser",
            user_id=test_user["id"],
        )
        resp = auth_client.delete(f"/api/accounts/{acc_id}")
        assert resp.status_code == 200


class TestContactEndpoints:
    """Contact import and listing."""

    def test_list_contacts(self, auth_client):
        resp = auth_client.get("/api/contacts")
        assert resp.status_code == 200

    def test_import_manual_contacts(self, auth_client):
        resp = auth_client.post("/api/contacts/import/manual",
                                data=json.dumps({
                                    "contacts": [
                                        {"name": "Alice", "email": "alice@test.com", "platform": "youtube"},
                                        {"name": "Bob", "handle": "@bob"},
                                    ]
                                }),
                                content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["imported"] == 2

    def test_import_csv_no_file(self, auth_client):
        resp = auth_client.post("/api/contacts/import/csv")
        assert resp.status_code == 400

    def test_clear_contacts(self, auth_client):
        resp = auth_client.post("/api/contacts/clear",
                                data=json.dumps({}),
                                content_type="application/json")
        assert resp.status_code == 200


class TestSettingsEndpoint:
    """POST /api/settings"""

    def test_update_settings(self, auth_client):
        resp = auth_client.post("/api/settings",
                                data=json.dumps({
                                    "name": "Updated Name",
                                    "notify_email": False,
                                    "webhook_url": "https://hook.example.com",
                                }),
                                content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "saved"

    def test_update_settings_requires_auth(self, client):
        resp = client.post("/api/settings",
                           data=json.dumps({"name": "Nope"}),
                           content_type="application/json")
        assert resp.status_code in (302, 401)
