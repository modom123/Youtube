"""Tests for JarveePro-matching features: spintax, proxy, fingerprint,
RSS monitor, user scraper, account warmup, hashtag research, growth analytics,
follow tracking, DM templates, auto-reply rules, and API endpoints."""
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest


# ── Spintax Engine ───────────────────────────────────────────────────────────

class TestSpintax:
    def test_spin_basic(self):
        from utils.spintax import spin
        result = spin("{Hello|Hi} world")
        assert result in ["Hello world", "Hi world"]

    def test_spin_no_spintax(self):
        from utils.spintax import spin
        assert spin("plain text") == "plain text"

    def test_spin_multiple(self):
        from utils.spintax import spin
        result = spin("{A|B} {C|D}")
        assert result in ["A C", "A D", "B C", "B D"]

    def test_spin_nested(self):
        from utils.spintax import spin
        result = spin("{Hi|{Hey|Yo}}")
        assert result in ["Hi", "Hey", "Yo"]

    def test_spin_batch(self):
        from utils.spintax import spin_batch
        results = spin_batch("{A|B|C|D} {1|2|3|4}", 5)
        assert len(results) <= 5
        assert len(set(results)) == len(results)

    def test_estimate_variations(self):
        from utils.spintax import estimate_variations
        count = estimate_variations("{A|B} {C|D|E}")
        assert count == 6

    def test_validate_valid(self):
        from utils.spintax import validate
        ok, msg = validate("{Hello|Hi} {world|earth}")
        assert ok is True
        assert msg == ""

    def test_validate_unclosed(self):
        from utils.spintax import validate
        ok, msg = validate("{Hello|Hi")
        assert ok is False
        assert "Unclosed" in msg

    def test_validate_unmatched(self):
        from utils.spintax import validate
        ok, msg = validate("Hello}")
        assert ok is False


# ── Proxy Manager ────────────────────────────────────────────────────────────

class TestProxyManager:
    def test_add_proxy(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool()
        pool.add_proxy({"url": "http://proxy1:8080"})
        assert pool.size == 1

    def test_get_proxy(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://proxy1:8080"}])
        proxy = pool.get_proxy()
        assert proxy is not None
        assert proxy.url == "http://proxy1:8080"

    def test_get_proxy_empty(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool()
        assert pool.get_proxy() is None

    def test_account_assignment(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://proxy1:8080"}, {"url": "http://proxy2:8080"}])
        p1 = pool.get_proxy("acc_1")
        p2 = pool.get_proxy("acc_1")
        assert p1.url == p2.url

    def test_rotate_proxy(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://p1:8080"}, {"url": "http://p2:8080"}])
        p1 = pool.get_proxy("acc_1")
        p2 = pool.rotate_proxy("acc_1")
        assert p2 is not None

    def test_mark_failed(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://proxy1:8080"}])
        proxy = pool.get_proxy()
        pool.mark_failed(proxy, max_fails=2)
        assert proxy.is_healthy is True
        pool.mark_failed(proxy, max_fails=2)
        assert proxy.is_healthy is False

    def test_mark_success(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://proxy1:8080"}])
        proxy = pool.get_proxy()
        proxy.fail_count = 5
        proxy.is_healthy = False
        pool.mark_success(proxy)
        assert proxy.is_healthy is True
        assert proxy.fail_count == 0

    def test_proxy_auth_url(self):
        from utils.proxy_manager import ProxyEntry
        entry = ProxyEntry(url="http://host:8080", username="user", password="pass")
        assert "user:pass@" in entry.full_url

    def test_get_stats(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://p1:8080"}, {"url": "http://p2:8080"}])
        stats = pool.get_stats()
        assert stats["total"] == 2
        assert stats["healthy"] == 2

    def test_remove_proxy(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://p1:8080"}, {"url": "http://p2:8080"}])
        pool.remove_proxy("http://p1:8080")
        assert pool.size == 1

    def test_global_pool(self):
        from utils.proxy_manager import init_pool, get_pool
        pool = init_pool([{"url": "http://global:8080"}])
        assert get_pool().size == 1

    def test_playwright_proxy(self):
        from utils.proxy_manager import ProxyPool
        pool = ProxyPool([{"url": "http://p1:8080", "username": "u", "password": "p"}])
        pw = pool.get_playwright_proxy("acc")
        assert pw["server"] == "http://p1:8080"
        assert pw["username"] == "u"


# ── Browser Fingerprint ──────────────────────────────────────────────────────

class TestBrowserFingerprint:
    def test_generate_fingerprint(self):
        from utils.browser_fingerprint import generate_fingerprint
        fp = generate_fingerprint("account_123")
        assert "user_agent" in fp
        assert "Chrome" in fp["user_agent"]
        assert fp["screen_width"] > 0
        assert fp["canvas_hash"]

    def test_deterministic(self):
        from utils.browser_fingerprint import generate_fingerprint
        fp1 = generate_fingerprint("same_account")
        fp2 = generate_fingerprint("same_account")
        assert fp1["user_agent"] == fp2["user_agent"]
        assert fp1["timezone"] == fp2["timezone"]

    def test_different_accounts(self):
        from utils.browser_fingerprint import generate_fingerprint
        fp1 = generate_fingerprint("account_a")
        fp2 = generate_fingerprint("account_b")
        assert fp1["canvas_hash"] != fp2["canvas_hash"]

    def test_anti_detect_script(self):
        from utils.browser_fingerprint import generate_fingerprint, get_anti_detect_script
        fp = generate_fingerprint("test")
        script = get_anti_detect_script(fp)
        assert "navigator" in script
        assert fp["platform"] in script

    def test_playwright_context_options(self):
        from utils.browser_fingerprint import generate_fingerprint, get_playwright_context_options
        fp = generate_fingerprint("test")
        opts = get_playwright_context_options(fp)
        assert opts["user_agent"] == fp["user_agent"]
        assert opts["viewport"]["width"] == fp["screen_width"]

    def test_playwright_context_with_proxy(self):
        from utils.browser_fingerprint import generate_fingerprint, get_playwright_context_options
        fp = generate_fingerprint("test")
        proxy = {"server": "http://proxy:8080"}
        opts = get_playwright_context_options(fp, proxy)
        assert opts["proxy"] == proxy


# ── RSS Monitor ──────────────────────────────────────────────────────────────

class TestRSSMonitor:
    def test_add_feed(self):
        from generators.rss_monitor import RSSMonitor
        monitor = RSSMonitor()
        feed = monitor.add_feed("http://example.com/rss", "Test Feed", "tech")
        assert feed.name == "Test Feed"
        assert len(monitor.list_feeds()) == 1

    def test_remove_feed(self):
        from generators.rss_monitor import RSSMonitor
        monitor = RSSMonitor()
        monitor.add_feed("http://example.com/rss", "Test")
        monitor.remove_feed("http://example.com/rss")
        assert len(monitor.list_feeds()) == 0

    def test_parse_rss(self):
        from generators.rss_monitor import RSSMonitor, Feed
        monitor = RSSMonitor()
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item><title>Test Article</title><link>http://example.com/1</link>
        <pubDate>Mon, 01 Jan 2024</pubDate></item>
        </channel></rss>"""
        feed = Feed(url="test", name="test")
        items = monitor._parse_feed(xml, feed)
        assert len(items) == 1
        assert items[0].title == "Test Article"

    def test_search_items(self):
        from generators.rss_monitor import RSSMonitor, FeedItem
        monitor = RSSMonitor()
        monitor._items_cache["test"] = [
            FeedItem(title="Python Tips", url="http://a.com", published="2024"),
            FeedItem(title="Go Tutorial", url="http://b.com", published="2024"),
        ]
        results = monitor.search_items("python")
        assert len(results) == 1

    def test_create_niche_monitor(self):
        from generators.rss_monitor import create_niche_monitor
        monitor = create_niche_monitor("tech")
        assert len(monitor.list_feeds()) > 0

    def test_get_trending_empty(self):
        from generators.rss_monitor import RSSMonitor
        monitor = RSSMonitor()
        assert monitor.get_trending() == []


# ── Account Warmup ───────────────────────────────────────────────────────────

class TestAccountWarmup:
    def test_fully_warmed(self):
        from generators.account_warmup import get_warmup_multiplier
        old_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
        assert get_warmup_multiplier(old_date) == 1.0

    def test_new_account(self):
        from generators.account_warmup import get_warmup_multiplier
        now = datetime.utcnow().isoformat()
        mult = get_warmup_multiplier(now)
        assert mult < 0.3

    def test_invalid_date(self):
        from generators.account_warmup import get_warmup_multiplier
        assert get_warmup_multiplier("not-a-date") == 1.0

    def test_warmed_limits(self):
        from generators.account_warmup import get_warmed_limits
        now = datetime.utcnow().isoformat()
        limits = get_warmed_limits("youtube", now)
        assert "like" in limits
        assert limits["like"] >= 1
        assert limits["like"] < 50

    def test_warmup_status(self):
        from generators.account_warmup import get_warmup_status
        now = datetime.utcnow().isoformat()
        status = get_warmup_status(now)
        assert status["phase"] in ["initial", "early", "mid", "late", "fully_warmed"]
        assert 0 <= status["multiplier"] <= 1.0

    def test_should_rest_new(self):
        from generators.account_warmup import should_rest
        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
        result = should_rest(yesterday)
        assert isinstance(result, bool)

    def test_profiles(self):
        from generators.account_warmup import get_warmup_multiplier
        date = (datetime.utcnow() - timedelta(days=5)).isoformat()
        conservative = get_warmup_multiplier(date, "conservative")
        aggressive = get_warmup_multiplier(date, "aggressive")
        assert aggressive >= conservative


# ── Hashtag Research ─────────────────────────────────────────────────────────

class TestHashtagResearch:
    def test_fallback_hashtags(self):
        from generators.hashtag_research import _fallback_hashtags
        results = _fallback_hashtags("python programming", "youtube", 10)
        assert len(results) > 0
        assert results[0].platform == "youtube"

    def test_fallback_scores(self):
        from generators.hashtag_research import _fallback_hashtags
        results = _fallback_hashtags("tech", "twitter", 5)
        for r in results:
            assert r.score > 0

    def test_get_best_hashtags_fallback(self):
        with patch("generators.hashtag_research.config") as mock_cfg:
            mock_cfg.YOUTUBE_CLIENT_ID = ""
            mock_cfg.TWITTER_API_KEY = ""
            mock_cfg.INSTAGRAM_ACCESS_TOKEN = ""
            from generators.hashtag_research import get_best_hashtags
            tags = get_best_hashtags("python", count=5)
            assert len(tags) > 0
            assert all(t.startswith("#") for t in tags)

    def test_hashtag_result_score(self):
        from generators.hashtag_research import HashtagResult
        hr = HashtagResult(tag="test", platform="youtube", volume=500000, difficulty=0.3, trending=True)
        score = hr.compute_score()
        assert score > 0


# ── User Scraper ─────────────────────────────────────────────────────────────

class TestUserScraper:
    def test_scraped_user_to_dict(self):
        from generators.user_scraper import ScrapedUser
        user = ScrapedUser(username="test_user", platform="twitter", followers=1000)
        d = user.to_dict()
        assert d["username"] == "test_user"
        assert d["platform"] == "twitter"
        assert d["followers"] == 1000

    def test_scrape_by_platform_unsupported(self):
        from generators.user_scraper import scrape_by_platform
        result = scrape_by_platform("fakebook", "target", method="commenters")
        assert result == []

    def test_scrape_youtube_no_config(self):
        with patch("generators.user_scraper.config") as mock_cfg:
            mock_cfg.YOUTUBE_CLIENT_ID = ""
            from generators.user_scraper import scrape_youtube_commenters
            assert scrape_youtube_commenters("video123") == []

    def test_scrape_twitter_no_config(self):
        with patch("generators.user_scraper.config") as mock_cfg:
            mock_cfg.TWITTER_API_KEY = ""
            from generators.user_scraper import scrape_twitter_followers
            assert scrape_twitter_followers("user123") == []


# ── Database: Growth Snapshots ───────────────────────────────────────────────

class TestGrowthDB:
    def test_add_and_get_snapshot(self, db_conn, test_user):
        acc_id = db_conn.upsert_account(
            "youtube", "testchannel", user_id=test_user["id"],
        )
        snap_id = db_conn.add_growth_snapshot(
            test_user["id"], acc_id, "youtube",
            followers=100, following=50, posts=10,
            engagement_rate=3.5, views_total=5000, likes_total=200,
        )
        assert snap_id > 0
        history = db_conn.get_growth_history(test_user["id"], account_id=acc_id)
        assert len(history) == 1
        assert history[0]["followers"] == 100

    def test_growth_summary(self, db_conn, test_user):
        acc_id = db_conn.upsert_account(
            "youtube", "testchannel", user_id=test_user["id"],
        )
        db_conn.add_growth_snapshot(test_user["id"], acc_id, "youtube", followers=100)
        db_conn.add_growth_snapshot(test_user["id"], acc_id, "youtube", followers=200)
        summary = db_conn.get_growth_summary(test_user["id"])
        assert "youtube" in summary
        assert summary["youtube"]["growth"] == 100


# ── Database: RSS Feeds ──────────────────────────────────────────────────────

class TestRSSFeedDB:
    def test_add_and_get_feeds(self, db_conn, test_user):
        feed_id = db_conn.add_rss_feed(
            test_user["id"], "http://example.com/rss", "Test", "tech"
        )
        assert feed_id > 0
        feeds = db_conn.get_rss_feeds(test_user["id"])
        assert len(feeds) == 1
        assert feeds[0]["url"] == "http://example.com/rss"

    def test_delete_feed(self, db_conn, test_user):
        feed_id = db_conn.add_rss_feed(test_user["id"], "http://del.com/rss")
        db_conn.delete_rss_feed(feed_id, test_user["id"])
        assert len(db_conn.get_rss_feeds(test_user["id"])) == 0


# ── Database: Auto-Reply Rules ───────────────────────────────────────────────

class TestAutoReplyDB:
    def test_create_and_get_rules(self, db_conn, test_user):
        rule_id = db_conn.create_auto_reply_rule(
            test_user["id"], "twitter", "keyword", "hello",
            "Thanks for reaching out!", uses_spintax=False,
        )
        assert rule_id > 0
        rules = db_conn.get_auto_reply_rules(test_user["id"])
        assert len(rules) == 1
        assert rules[0]["trigger_value"] == "hello"

    def test_filter_by_platform(self, db_conn, test_user):
        db_conn.create_auto_reply_rule(
            test_user["id"], "twitter", "keyword", "hi", "Hey!"
        )
        db_conn.create_auto_reply_rule(
            test_user["id"], "instagram", "keyword", "hi", "Hello!"
        )
        twitter_rules = db_conn.get_auto_reply_rules(test_user["id"], "twitter")
        assert len(twitter_rules) == 1

    def test_delete_rule(self, db_conn, test_user):
        rule_id = db_conn.create_auto_reply_rule(
            test_user["id"], "twitter", "keyword", "bye", "Goodbye!"
        )
        db_conn.delete_auto_reply_rule(rule_id, test_user["id"])
        assert len(db_conn.get_auto_reply_rules(test_user["id"])) == 0


# ── Database: DM Templates ──────────────────────────────────────────────────

class TestDMTemplateDB:
    def test_create_and_get_templates(self, db_conn, test_user):
        tmpl_id = db_conn.create_dm_template(
            test_user["id"], "Welcome", "{Hi|Hey} there!",
            platform="twitter", trigger_on="new_follower",
        )
        assert tmpl_id > 0
        templates = db_conn.get_dm_templates(test_user["id"])
        assert len(templates) == 1
        assert templates[0]["name"] == "Welcome"

    def test_delete_template(self, db_conn, test_user):
        tmpl_id = db_conn.create_dm_template(
            test_user["id"], "Test", "Hello"
        )
        db_conn.delete_dm_template(tmpl_id, test_user["id"])
        assert len(db_conn.get_dm_templates(test_user["id"])) == 0


# ── Database: Follow Tracking ───────────────────────────────────────────────

class TestFollowTrackingDB:
    def test_track_follow(self, db_conn, test_user):
        fid = db_conn.track_follow(test_user["id"], "twitter", "target_user")
        assert fid > 0
        follows = db_conn.get_follows(test_user["id"])
        assert len(follows) == 1
        assert follows[0]["target_username"] == "target_user"

    def test_mark_follow_back(self, db_conn, test_user):
        db_conn.track_follow(test_user["id"], "twitter", "friend")
        db_conn.mark_follow_back(test_user["id"], "twitter", "friend")
        follows = db_conn.get_follows(test_user["id"])
        assert follows[0]["followed_back"] == 1

    def test_mark_unfollowed(self, db_conn, test_user):
        fid = db_conn.track_follow(test_user["id"], "twitter", "unfriend")
        db_conn.mark_unfollowed(fid)
        following = db_conn.get_follows(test_user["id"], status="following")
        unfollowed = db_conn.get_follows(test_user["id"], status="unfollowed")
        assert len(following) == 0
        assert len(unfollowed) == 1


# ── Engagement Engine: New Features ──────────────────────────────────────────

class TestEngagementEngineFeatures:
    def test_auto_unfollow(self, db_conn, test_user):
        db_conn.track_follow(test_user["id"], "twitter", "stale_user")
        conn = db_conn.get_conn()
        conn.execute(
            "UPDATE follow_tracking SET followed_at=datetime('now', '-10 days') WHERE target_username='stale_user'"
        )
        conn.commit()
        conn.close()
        from generators.engagement_engine import auto_unfollow_stale
        results = auto_unfollow_stale(test_user["id"], days_threshold=3)
        assert len(results) >= 1
        assert results[0]["username"] == "stale_user"

    def test_send_dm_direct(self):
        from generators.engagement_engine import send_dm
        result = send_dm(1, "twitter", "someone", message="Hello!")
        assert result["status"] == "queued"

    def test_send_dm_no_message(self):
        from generators.engagement_engine import send_dm
        result = send_dm(1, "twitter", "someone")
        assert result["status"] == "error"

    def test_check_auto_replies_match(self, db_conn, test_user):
        db_conn.create_auto_reply_rule(
            test_user["id"], "twitter", "keyword", "pricing",
            "Check out our plans at example.com/pricing!"
        )
        from generators.engagement_engine import check_auto_replies
        reply = check_auto_replies(test_user["id"], "twitter", "What is your pricing?", "user1")
        assert reply is not None
        assert "pricing" in reply.lower() or "plans" in reply.lower()

    def test_check_auto_replies_no_match(self, db_conn, test_user):
        db_conn.create_auto_reply_rule(
            test_user["id"], "twitter", "keyword", "pricing",
            "Check pricing!"
        )
        from generators.engagement_engine import check_auto_replies
        reply = check_auto_replies(test_user["id"], "twitter", "Hello there!", "user1")
        assert reply is None

    def test_check_auto_replies_spintax(self, db_conn, test_user):
        db_conn.create_auto_reply_rule(
            test_user["id"], "twitter", "keyword", "help",
            "{Sure|Of course}, I can help!",
            uses_spintax=True,
        )
        from generators.engagement_engine import check_auto_replies
        reply = check_auto_replies(test_user["id"], "twitter", "I need help", "user1")
        assert reply in ["Sure, I can help!", "Of course, I can help!"]


# ── API Endpoints ────────────────────────────────────────────────────────────

class TestAPIEndpoints:
    def test_rss_feeds_crud(self, auth_client):
        resp = auth_client.post("/api/rss/feeds", json={
            "url": "http://example.com/rss", "name": "Test Feed"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "added"
        feed_id = data["id"]

        resp = auth_client.get("/api/rss/feeds")
        assert resp.status_code == 200
        feeds = resp.get_json()
        assert len(feeds) == 1

        resp = auth_client.delete(f"/api/rss/feeds/{feed_id}")
        assert resp.status_code == 200

    def test_rss_feeds_validation(self, auth_client):
        resp = auth_client.post("/api/rss/feeds", json={})
        assert resp.status_code == 400

    def test_dm_templates_crud(self, auth_client):
        resp = auth_client.post("/api/dm/templates", json={
            "name": "Welcome", "message_template": "{Hi|Hey}!"
        })
        assert resp.status_code == 200
        tmpl_id = resp.get_json()["id"]

        resp = auth_client.get("/api/dm/templates")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1

        resp = auth_client.delete(f"/api/dm/templates/{tmpl_id}")
        assert resp.status_code == 200

    def test_dm_templates_validation(self, auth_client):
        resp = auth_client.post("/api/dm/templates", json={"name": ""})
        assert resp.status_code == 400

    def test_auto_reply_rules_crud(self, auth_client):
        resp = auth_client.post("/api/auto-reply/rules", json={
            "platform": "twitter",
            "trigger_type": "keyword",
            "trigger_value": "pricing",
            "reply_template": "Check our website!",
        })
        assert resp.status_code == 200
        rule_id = resp.get_json()["id"]

        resp = auth_client.get("/api/auto-reply/rules")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1

        resp = auth_client.delete(f"/api/auto-reply/rules/{rule_id}")
        assert resp.status_code == 200

    def test_auto_reply_validation(self, auth_client):
        resp = auth_client.post("/api/auto-reply/rules", json={"platform": "twitter"})
        assert resp.status_code == 400

    def test_hashtag_research(self, auth_client):
        resp = auth_client.get("/api/hashtags/research?topic=python")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "hashtags" in data
        assert len(data["hashtags"]) > 0

    def test_hashtag_research_no_topic(self, auth_client):
        resp = auth_client.get("/api/hashtags/research")
        assert resp.status_code == 400

    def test_growth_snapshot(self, auth_client, db_conn, test_user):
        acc_id = db_conn.upsert_account("youtube", "ch", user_id=test_user["id"])
        resp = auth_client.post("/api/growth/snapshot", json={
            "account_id": acc_id, "platform": "youtube", "followers": 500
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "recorded"

    def test_growth_history(self, auth_client):
        resp = auth_client.get("/api/growth/history")
        assert resp.status_code == 200

    def test_growth_summary(self, auth_client):
        resp = auth_client.get("/api/growth/summary")
        assert resp.status_code == 200

    def test_follow_tracking(self, auth_client):
        resp = auth_client.post("/api/follows", json={
            "platform": "twitter", "target_username": "testuser"
        })
        assert resp.status_code == 200

        resp = auth_client.get("/api/follows")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1

    def test_follow_validation(self, auth_client):
        resp = auth_client.post("/api/follows", json={"platform": "twitter"})
        assert resp.status_code == 400

    def test_stale_follows(self, auth_client):
        resp = auth_client.get("/api/follows/stale")
        assert resp.status_code == 200

    def test_auto_unfollow(self, auth_client):
        resp = auth_client.post("/api/follows/auto-unfollow", json={})
        assert resp.status_code == 200
        assert "unfollowed" in resp.get_json()

    def test_warmup_status(self, auth_client):
        resp = auth_client.get("/api/warmup/status?account_created=2024-01-01T00:00:00")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "phase" in data

    def test_warmup_status_no_date(self, auth_client):
        resp = auth_client.get("/api/warmup/status")
        assert resp.status_code == 400

    def test_warmup_limits(self, auth_client):
        resp = auth_client.get(
            "/api/warmup/limits?platform=youtube&account_created=2024-01-01T00:00:00"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "limits" in data

    def test_spintax_preview(self, auth_client):
        resp = auth_client.post("/api/spintax/preview", json={
            "text": "{Hello|Hi} {world|earth}", "count": 3
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["variations"]) <= 3
        assert data["total_possible"] == 4

    def test_spintax_preview_invalid(self, auth_client):
        resp = auth_client.post("/api/spintax/preview", json={
            "text": "{Hello|Hi"
        })
        assert resp.status_code == 400

    def test_spintax_preview_empty(self, auth_client):
        resp = auth_client.post("/api/spintax/preview", json={"text": ""})
        assert resp.status_code == 400

    def test_dm_send(self, auth_client):
        resp = auth_client.post("/api/dm/send", json={
            "platform": "twitter", "target_username": "someone", "message": "Hi!"
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "queued"

    def test_growth_snapshot_validation(self, auth_client):
        resp = auth_client.post("/api/growth/snapshot", json={"platform": "youtube"})
        assert resp.status_code == 400

    def test_scraper_run(self, auth_client):
        resp = auth_client.post("/api/scraper/run", json={
            "platform": "fakebook", "target": "user123"
        })
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 0

    def test_scraper_validation(self, auth_client):
        resp = auth_client.post("/api/scraper/run", json={"platform": "twitter"})
        assert resp.status_code == 400
