"""Tests for the Engagement Center — campaigns, actions, targets, and API endpoints."""
import json



class TestEngagementCampaigns:
    """Campaign CRUD via API."""

    def test_list_campaigns_empty(self, auth_client):
        resp = auth_client.get("/api/engagement/campaigns")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_create_campaign(self, auth_client):
        resp = auth_client.post("/api/engagement/campaigns",
                                data=json.dumps({
                                    "name": "AI Growth Q1",
                                    "platforms": ["youtube", "tiktok"],
                                    "target_niche": "AI tutorials",
                                    "strategy": "growth",
                                    "daily_limit": 50,
                                }),
                                content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "created"
        assert "campaign_id" in data

    def test_create_campaign_missing_name(self, auth_client):
        resp = auth_client.post("/api/engagement/campaigns",
                                data=json.dumps({"platforms": ["youtube"]}),
                                content_type="application/json")
        assert resp.status_code == 400

    def test_create_campaign_missing_platforms(self, auth_client):
        resp = auth_client.post("/api/engagement/campaigns",
                                data=json.dumps({"name": "Test", "platforms": []}),
                                content_type="application/json")
        assert resp.status_code == 400

    def test_get_campaign(self, auth_client, db_conn, test_user):
        camp_id = db_conn.create_engagement_campaign(
            user_id=test_user["id"], name="Test Camp", platforms=["youtube"],
        )
        resp = auth_client.get(f"/api/engagement/campaigns/{camp_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["campaign"]["name"] == "Test Camp"
        assert "stats" in data
        assert "recent_actions" in data
        assert "targets" in data

    def test_get_campaign_not_found(self, auth_client):
        resp = auth_client.get("/api/engagement/campaigns/nonexistent")
        assert resp.status_code == 404

    def test_update_campaign(self, auth_client, db_conn, test_user):
        camp_id = db_conn.create_engagement_campaign(
            user_id=test_user["id"], name="Old Name", platforms=["youtube"],
        )
        resp = auth_client.put(f"/api/engagement/campaigns/{camp_id}",
                               data=json.dumps({"name": "New Name", "is_active": False}),
                               content_type="application/json")
        assert resp.status_code == 200

    def test_delete_campaign(self, auth_client, db_conn, test_user):
        camp_id = db_conn.create_engagement_campaign(
            user_id=test_user["id"], name="Delete Me", platforms=["youtube"],
        )
        resp = auth_client.delete(f"/api/engagement/campaigns/{camp_id}")
        assert resp.status_code == 200
        resp2 = auth_client.get(f"/api/engagement/campaigns/{camp_id}")
        assert resp2.status_code == 404


class TestEngagementTargets:
    """Target management."""

    def test_add_targets(self, auth_client, db_conn, test_user):
        camp_id = db_conn.create_engagement_campaign(
            user_id=test_user["id"], name="Target Camp", platforms=["youtube"],
        )
        resp = auth_client.post(f"/api/engagement/campaigns/{camp_id}/targets",
                                data=json.dumps({
                                    "targets": [
                                        {"platform": "youtube", "username": "creator1"},
                                        {"platform": "youtube", "username": "creator2", "followers": 50000},
                                    ]
                                }),
                                content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["added"] == 2

    def test_add_targets_no_data(self, auth_client, db_conn, test_user):
        camp_id = db_conn.create_engagement_campaign(
            user_id=test_user["id"], name="Empty", platforms=["youtube"],
        )
        resp = auth_client.post(f"/api/engagement/campaigns/{camp_id}/targets",
                                data=json.dumps({"targets": []}),
                                content_type="application/json")
        assert resp.status_code == 400

    def test_add_targets_campaign_not_found(self, auth_client):
        resp = auth_client.post("/api/engagement/campaigns/fake/targets",
                                data=json.dumps({"targets": [{"platform": "youtube", "username": "x"}]}),
                                content_type="application/json")
        assert resp.status_code == 404


class TestEngagementActions:
    """Quick action creation and stats."""

    def test_create_action(self, auth_client):
        resp = auth_client.post("/api/engagement/actions",
                                data=json.dumps({
                                    "platform": "youtube",
                                    "action_type": "like",
                                    "target_url": "https://youtube.com/watch?v=test123",
                                }),
                                content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "queued"
        assert "action_id" in data

    def test_create_action_missing_fields(self, auth_client):
        resp = auth_client.post("/api/engagement/actions",
                                data=json.dumps({"platform": "youtube"}),
                                content_type="application/json")
        assert resp.status_code == 400

    def test_engagement_stats(self, auth_client):
        resp = auth_client.get("/api/engagement/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data
        assert "daily_count" in data


class TestEngagementPage:
    """UI page tests."""

    def test_engagement_page_requires_auth(self, client):
        resp = client.get("/engagement", follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_engagement_page_renders(self, auth_client):
        resp = auth_client.get("/engagement")
        assert resp.status_code == 200
        assert b"Engagement Center" in resp.data


class TestEngagementEngine:
    """Unit tests for the engagement engine module."""

    def test_check_rate_limit_allows(self, db_conn):
        from generators.engagement_engine import check_rate_limit
        uid = db_conn.create_user(email="rate1@test.com", password_hash="h")
        allowed, err = check_rate_limit(uid, "youtube", "like")
        assert allowed is True

    def test_queue_engagement_actions(self, db_conn):
        from generators.engagement_engine import queue_engagement_actions
        uid = db_conn.create_user(email="queue1@test.com", password_hash="h")
        camp_id = db_conn.create_engagement_campaign(uid, "Test", platforms=["youtube"])
        actions = [
            {"platform": "youtube", "action_type": "like", "target_url": "https://yt.com/1"},
            {"platform": "youtube", "action_type": "comment", "comment_text": "Great insight!"},
        ]
        ids = queue_engagement_actions(uid, camp_id, actions)
        assert len(ids) == 2

    def test_platform_rate_limits_structure(self):
        from generators.engagement_engine import PLATFORM_RATE_LIMITS
        assert "youtube" in PLATFORM_RATE_LIMITS
        assert "tiktok" in PLATFORM_RATE_LIMITS
        assert "instagram" in PLATFORM_RATE_LIMITS
        assert "twitter" in PLATFORM_RATE_LIMITS
        assert "linkedin" in PLATFORM_RATE_LIMITS


class TestCommunityEngineerAgent:
    """Test the Community Engineer agent schema."""

    def test_engagement_plan_schema(self):
        from generators.agents.schemas import EngagementPlan, EngagementAction
        action = EngagementAction(
            platform="youtube",
            action_type="comment",
            target_description="Top AI tutorial creator with 50K subs",
            target_username="@aicreator",
            comment_text="Great breakdown of transformers!",
            timing="09:00-10:00 UTC",
            priority=1,
            strategy_tier="reciprocity",
            rationale="High-value reciprocity target in our niche",
        )
        plan = EngagementPlan(
            daily_actions=[action],
            total_actions=1,
            platform_breakdown={"youtube": 1},
            estimated_reach=500,
            key_focus="Reciprocity with mid-tier AI creators",
            notes="Focus on genuine engagement",
        )
        assert plan.total_actions == 1
        assert plan.daily_actions[0].platform == "youtube"

    def test_agent_instantiation(self):
        from generators.agents import CommunityEngineer
        agent = CommunityEngineer()
        assert agent.name == "Community Engineer"


class TestDatabaseEngagement:
    """Database layer engagement methods."""

    def test_campaign_crud(self, db_conn):
        uid = db_conn.create_user(email="dbeng@test.com", password_hash="h")
        camp_id = db_conn.create_engagement_campaign(uid, "DB Test", platforms=["youtube", "tiktok"])
        camps = db_conn.get_engagement_campaigns(uid)
        assert len(camps) >= 1

        camp = db_conn.get_engagement_campaign(camp_id, uid)
        assert camp["name"] == "DB Test"

        db_conn.update_engagement_campaign(camp_id, name="Updated")
        camp2 = db_conn.get_engagement_campaign(camp_id, uid)
        assert camp2["name"] == "Updated"

        db_conn.delete_engagement_campaign(camp_id, uid)
        assert db_conn.get_engagement_campaign(camp_id, uid) is None

    def test_action_crud(self, db_conn):
        uid = db_conn.create_user(email="dbact@test.com", password_hash="h")
        action_id = db_conn.create_engagement_action(
            uid, "youtube", "like", target_url="https://yt.com/test",
        )
        assert action_id > 0

        actions = db_conn.get_engagement_actions(uid)
        assert len(actions) >= 1

        db_conn.update_engagement_action(action_id, status="completed")
        actions2 = db_conn.get_engagement_actions(uid, status="completed")
        assert any(a["id"] == action_id for a in actions2)

    def test_target_crud(self, db_conn):
        uid = db_conn.create_user(email="dbtgt@test.com", password_hash="h")
        camp_id = db_conn.create_engagement_campaign(uid, "Tgt Test", platforms=["youtube"])
        tgt_id = db_conn.add_engagement_target(uid, camp_id, "youtube", "creator1")
        assert tgt_id > 0

        targets = db_conn.get_engagement_targets(uid, camp_id)
        assert len(targets) >= 1

        db_conn.mark_target_engaged(tgt_id)
        engaged = db_conn.get_engagement_targets(uid, camp_id, engaged=True)
        assert len(engaged) >= 1

    def test_engagement_stats(self, db_conn):
        uid = db_conn.create_user(email="dbstats@test.com", password_hash="h")
        db_conn.create_engagement_action(uid, "youtube", "like")
        db_conn.create_engagement_action(uid, "youtube", "comment")
        stats = db_conn.get_engagement_stats(uid)
        assert stats["total"] >= 2
        assert "like" in stats["by_action"]

    def test_daily_action_count(self, db_conn):
        uid = db_conn.create_user(email="dbdaily@test.com", password_hash="h")
        db_conn.create_engagement_action(uid, "youtube", "like")
        db_conn.create_engagement_action(uid, "youtube", "like")
        count = db_conn.get_daily_action_count(uid)
        assert count >= 2
