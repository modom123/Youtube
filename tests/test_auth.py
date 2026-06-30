"""Tests for the auth blueprint — registration, login, logout."""
import pytest


class TestRegistration:
    """POST /auth/register"""

    def test_register_success(self, client, db_conn):
        resp = client.post("/auth/register", data={
            "name": "New User",
            "email": "newuser@example.com",
            "password": "SecureP@ss1",
            "password2": "SecureP@ss1",
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)
        # User should exist in DB
        user = db_conn.get_user_by_email("newuser@example.com")
        assert user is not None
        assert user["name"] == "New User"

    def test_register_duplicate_email(self, client, test_user):
        resp = client.post("/auth/register", data={
            "name": "Another",
            "email": "test@example.com",  # already exists via test_user
            "password": "SecureP@ss1",
            "password2": "SecureP@ss1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"already exists" in resp.data

    def test_register_weak_password(self, client, db_conn):
        resp = client.post("/auth/register", data={
            "name": "Weak",
            "email": "weak@example.com",
            "password": "short",
            "password2": "short",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"at least 8 characters" in resp.data

    def test_register_mismatched_passwords(self, client, db_conn):
        resp = client.post("/auth/register", data={
            "name": "Mismatch",
            "email": "mismatch@example.com",
            "password": "SecureP@ss1",
            "password2": "DifferentPass!",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"do not match" in resp.data

    def test_register_missing_fields(self, client, db_conn):
        resp = client.post("/auth/register", data={
            "email": "",
            "password": "",
            "password2": "",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"required" in resp.data

    def test_register_get_shows_form(self, client):
        resp = client.get("/auth/register")
        assert resp.status_code == 200


class TestLogin:
    """POST /auth/login"""

    def test_login_success(self, client, test_user):
        resp = client.post("/auth/login", data={
            "email": "test@example.com",
            "password": "Str0ngP@ss!",
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert "/dashboard" in resp.headers.get("Location", "")

    def test_login_wrong_password(self, client, test_user):
        resp = client.post("/auth/login", data={
            "email": "test@example.com",
            "password": "WrongPassword!",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid email or password" in resp.data

    def test_login_wrong_email(self, client, db_conn):
        resp = client.post("/auth/login", data={
            "email": "nobody@example.com",
            "password": "AnyPassword1!",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid email or password" in resp.data

    def test_login_get_shows_form(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200


class TestLogout:
    """GET /auth/logout"""

    def test_logout_redirects(self, auth_client):
        resp = auth_client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_after_logout_protected_route_redirects(self, auth_client):
        auth_client.get("/auth/logout")
        resp = auth_client.get("/dashboard", follow_redirects=False)
        assert resp.status_code in (302, 303)
        location = resp.headers.get("Location", "")
        assert "/auth/login" in location or "/login" in location


class TestProtectedRoutes:
    """Unauthenticated access to protected routes should redirect to login."""

    @pytest.mark.parametrize("path", [
        "/dashboard",
        "/create",
        "/jobs",
        "/accounts",
        "/contacts",
        "/settings",
        "/billing/",
    ])
    def test_protected_routes_redirect(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (302, 303)
        location = resp.headers.get("Location", "")
        assert "login" in location.lower()
