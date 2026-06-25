"""Shared pytest fixtures for the Social Optimize test suite."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure the project root is importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Patch config BEFORE importing any application code so that directory-creation
# side effects in config.py target a temp directory rather than the repo root.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _patch_config_dirs():
    """Redirect all output directories to a temp folder for the test session."""
    tmpdir = tempfile.mkdtemp(prefix="som_test_")
    tmp_path = Path(tmpdir)
    with patch.dict(os.environ, {
        "DATA_DIR": tmpdir,
        "SECRET_KEY": "test-secret-key-fixed",
        "STRIPE_SECRET_KEY": "",
        "STRIPE_PUBLISHABLE_KEY": "",
        "STRIPE_WEBHOOK_SECRET": "whsec_test_secret",
        "STRIPE_PRICE_STARTER": "price_starter_test",
        "STRIPE_PRICE_CREATOR": "price_creator_test",
        "STRIPE_PRICE_AGENCY": "price_agency_test",
        "ANTHROPIC_API_KEY": "",
        "PIXABAY_API_KEY": "",
        "GOOGLE_API_KEY": "",
    }):
        # Force re-evaluation of config paths
        import config as cfg
        orig_data = cfg.DATA_DIR
        orig_output = cfg.OUTPUT_DIR
        orig_videos = cfg.VIDEOS_DIR
        orig_audio = cfg.AUDIO_DIR
        orig_thumbs = cfg.THUMBNAILS_DIR
        orig_scripts = cfg.SCRIPTS_DIR
        orig_secret = cfg.SECRET_KEY

        cfg.DATA_DIR = tmp_path
        cfg.OUTPUT_DIR = tmp_path / "output"
        cfg.VIDEOS_DIR = tmp_path / "output" / "videos"
        cfg.AUDIO_DIR = tmp_path / "output" / "audio"
        cfg.THUMBNAILS_DIR = tmp_path / "output" / "thumbnails"
        cfg.SCRIPTS_DIR = tmp_path / "output" / "scripts"
        cfg.SECRET_KEY = "test-secret-key-fixed"

        for d in [cfg.VIDEOS_DIR, cfg.AUDIO_DIR, cfg.THUMBNAILS_DIR, cfg.SCRIPTS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        yield

        cfg.DATA_DIR = orig_data
        cfg.OUTPUT_DIR = orig_output
        cfg.VIDEOS_DIR = orig_videos
        cfg.AUDIO_DIR = orig_audio
        cfg.THUMBNAILS_DIR = orig_thumbs
        cfg.SCRIPTS_DIR = orig_scripts
        cfg.SECRET_KEY = orig_secret


@pytest.fixture(scope="session")
def _init_test_db(_patch_config_dirs):
    """Initialise a fresh SQLite DB in the temp DATA_DIR."""
    import config as cfg
    import database as db

    # Point database module at the temp directory
    db.DB_PATH = cfg.DATA_DIR / "som_test.db"
    db.init_db()
    yield db


@pytest.fixture()
def db_conn(_init_test_db):
    """Per-test: clean all rows so tests are isolated, return the db module."""
    db = _init_test_db
    # Wipe data but keep schema
    conn = db.get_conn()
    for table in [
        "follow_tracking", "dm_templates", "auto_reply_rules",
        "rss_feeds", "growth_snapshots",
        "engagement_targets", "engagement_actions", "engagement_campaigns",
        "team_members", "teams", "competitor_videos", "competitor_channels",
        "in_app_notifications", "notification_log", "dub_jobs",
        "content_templates", "batch_jobs", "scheduled_posts",
        "published_videos", "analytics_cache", "contacts",
        "social_accounts", "jobs", "settings", "users",
    ]:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def app(db_conn):
    """Create a Flask test application."""
    import config as cfg
    cfg.SECRET_KEY = "test-secret-key-fixed"

    from app import app as flask_app
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key-fixed",
        "WTF_CSRF_ENABLED": False,
        "SERVER_NAME": None,
        "RATELIMIT_ENABLED": False,
    })
    # Disable rate limiter for tests
    from extensions import limiter
    limiter.enabled = False
    yield flask_app
    limiter.enabled = True


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture()
def test_user(db_conn):
    """Create a test user in the database and return the user dict."""
    from werkzeug.security import generate_password_hash
    pw_hash = generate_password_hash("Str0ngP@ss!")
    user_id = db_conn.create_user(
        email="test@example.com", password_hash=pw_hash, name="Test User"
    )
    return db_conn.get_user_by_id(user_id)


@pytest.fixture()
def auth_client(client, test_user):
    """A test client that is already logged in as test_user."""
    client.post("/auth/login", data={
        "email": "test@example.com",
        "password": "Str0ngP@ss!",
    }, follow_redirects=False)
    return client


@pytest.fixture()
def agency_user(db_conn):
    """Create a user on the agency (unlimited) tier."""
    from werkzeug.security import generate_password_hash
    pw_hash = generate_password_hash("Agency1234!")
    user_id = db_conn.create_user(
        email="agency@example.com", password_hash=pw_hash, name="Agency User"
    )
    db_conn.update_user(user_id, subscription_tier="agency")
    return db_conn.get_user_by_id(user_id)


@pytest.fixture()
def mock_stripe():
    """Mock the stripe module to prevent real API calls."""
    with patch("stripe.Customer.create") as mock_cust, \
         patch("stripe.checkout.Session.create") as mock_sess, \
         patch("stripe.billing_portal.Session.create") as mock_portal, \
         patch("stripe.Webhook.construct_event") as mock_webhook:
        mock_cust.return_value = MagicMock(id="cus_test_123")
        mock_sess.return_value = MagicMock(url="https://checkout.stripe.com/test", id="cs_test_123")
        mock_portal.return_value = MagicMock(url="https://billing.stripe.com/test")
        yield {
            "customer": mock_cust,
            "session": mock_sess,
            "portal": mock_portal,
            "webhook": mock_webhook,
        }
