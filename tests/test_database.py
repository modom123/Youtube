"""Tests for the database layer."""
from werkzeug.security import generate_password_hash


class TestUserCRUD:

    def test_create_user(self, db_conn):
        uid = db_conn.create_user(
            email="dbtest@example.com",
            password_hash=generate_password_hash("test1234"),
            name="DB Test",
        )
        assert uid > 0
        user = db_conn.get_user_by_id(uid)
        assert user["email"] == "dbtest@example.com"
        assert user["name"] == "DB Test"
        assert user["subscription_tier"] == "free"

    def test_get_user_by_email(self, db_conn):
        db_conn.create_user(
            email="lookup@example.com",
            password_hash=generate_password_hash("pw"),
        )
        user = db_conn.get_user_by_email("lookup@example.com")
        assert user is not None
        assert user["email"] == "lookup@example.com"

    def test_get_user_by_email_case_insensitive(self, db_conn):
        db_conn.create_user(
            email="UPPER@EXAMPLE.COM",
            password_hash=generate_password_hash("pw"),
        )
        user = db_conn.get_user_by_email("upper@example.com")
        assert user is not None

    def test_get_nonexistent_user(self, db_conn):
        assert db_conn.get_user_by_id(99999) is None
        assert db_conn.get_user_by_email("ghost@void.com") is None

    def test_update_user(self, db_conn):
        uid = db_conn.create_user(
            email="update@test.com",
            password_hash=generate_password_hash("pw"),
        )
        db_conn.update_user(uid, name="Updated Name", subscription_tier="creator")
        user = db_conn.get_user_by_id(uid)
        assert user["name"] == "Updated Name"
        assert user["subscription_tier"] == "creator"

    def test_list_users(self, db_conn):
        db_conn.create_user(email="a@test.com", password_hash="h")
        db_conn.create_user(email="b@test.com", password_hash="h")
        users = db_conn.list_users()
        assert len(users) >= 2


class TestUsageTracking:

    def test_increment_user_usage(self, db_conn):
        uid = db_conn.create_user(email="usage@test.com", password_hash="h")
        db_conn.increment_user_usage(uid, videos=3, credits=10)
        user = db_conn.get_user_by_id(uid)
        assert user["videos_used"] == 3
        assert user["credits_used"] == 10

    def test_increment_videos_used(self, db_conn):
        uid = db_conn.create_user(email="vids@test.com", password_hash="h")
        count = db_conn.increment_videos_used(uid)
        assert count == 1
        count = db_conn.increment_videos_used(uid)
        assert count == 2

    def test_reset_monthly_usage(self, db_conn):
        uid = db_conn.create_user(email="reset@test.com", password_hash="h")
        db_conn.increment_videos_used(uid)
        db_conn.increment_videos_used(uid)
        db_conn.reset_monthly_usage(uid)
        user = db_conn.get_user_by_id(uid)
        assert user["videos_used_this_month"] == 0

    def test_check_usage_allowed_free(self, db_conn):
        uid = db_conn.create_user(email="free@test.com", password_hash="h")
        result = db_conn.check_usage_allowed(uid)
        assert result["allowed"] is True

    def test_check_usage_allowed_admin_always(self, db_conn):
        uid = db_conn.create_user(email="admin@test.com", password_hash="h")
        db_conn.update_user(uid, is_admin=1, videos_used_this_month=999)
        result = db_conn.check_usage_allowed(uid)
        assert result["allowed"] is True

    def test_reset_usage_if_new_period(self, db_conn):
        uid = db_conn.create_user(email="period@test.com", password_hash="h")
        # Set period_start to an old date to force reset
        db_conn.update_user(uid, period_start="2020-01-01", videos_used=5, credits_used=10)
        db_conn.reset_usage_if_new_period(uid)
        user = db_conn.get_user_by_id(uid)
        assert user["videos_used"] == 0
        assert user["credits_used"] == 0


class TestJobCRUD:

    def test_create_and_get_job(self, db_conn):
        uid = db_conn.create_user(email="job@test.com", password_hash="h")
        job_id = db_conn.create_job(
            topic="Test Topic", format="short", platforms=["youtube"],
            audience="general", voice="en-US-AriaNeural",
            style="fire", privacy="private", user_id=uid,
        )
        assert job_id > 0
        job = db_conn.get_job(job_id)
        assert job["topic"] == "Test Topic"
        assert job["status"] == "pending"
        assert job["platforms"] == ["youtube"]

    def test_update_job(self, db_conn):
        uid = db_conn.create_user(email="jobup@test.com", password_hash="h")
        job_id = db_conn.create_job(
            topic="Update Me", format="long", platforms=[],
            audience="tech", voice="v", style="s", privacy="public", user_id=uid,
        )
        db_conn.update_job(job_id, status="running", progress=50, current_step="Halfway")
        job = db_conn.get_job(job_id)
        assert job["status"] == "running"
        assert job["progress"] == 50

    def test_get_jobs_for_user(self, db_conn):
        uid1 = db_conn.create_user(email="u1@test.com", password_hash="h")
        uid2 = db_conn.create_user(email="u2@test.com", password_hash="h")
        db_conn.create_job(topic="T1", format="short", platforms=[], audience="a",
                           voice="v", style="s", privacy="p", user_id=uid1)
        db_conn.create_job(topic="T2", format="short", platforms=[], audience="a",
                           voice="v", style="s", privacy="p", user_id=uid2)
        jobs = db_conn.get_jobs(user_id=uid1)
        assert len(jobs) == 1
        assert jobs[0]["topic"] == "T1"

    def test_get_job_user_isolation(self, db_conn):
        uid1 = db_conn.create_user(email="iso1@test.com", password_hash="h")
        uid2 = db_conn.create_user(email="iso2@test.com", password_hash="h")
        job_id = db_conn.create_job(topic="Private", format="short", platforms=[],
                                    audience="a", voice="v", style="s", privacy="p",
                                    user_id=uid1)
        # user2 should not see user1's job
        assert db_conn.get_job(job_id, user_id=uid2) is None


class TestContactsBulkInsert:

    def test_insert_contacts_bulk(self, db_conn):
        uid = db_conn.create_user(email="contacts@test.com", password_hash="h")
        contacts = [
            {"name": "Alice", "handle": "@alice", "email": "a@t.com",
             "phone": "", "platform": "youtube", "avatar_url": "",
             "followers": 100, "tags": "[]"},
            {"name": "Bob", "handle": "@bob", "email": "b@t.com",
             "phone": "555-0100", "platform": "tiktok", "avatar_url": "",
             "followers": 200, "tags": "[]"},
        ]
        count = db_conn.insert_contacts_bulk(contacts, user_id=uid)
        assert count == 2
        result = db_conn.get_contacts(user_id=uid)
        assert len(result) == 2

    def test_count_contacts(self, db_conn):
        uid = db_conn.create_user(email="cnt@test.com", password_hash="h")
        db_conn.insert_contacts_bulk([
            {"name": "C1", "handle": "", "email": "", "phone": "",
             "platform": "youtube", "avatar_url": "", "followers": 0, "tags": "[]"},
        ], user_id=uid)
        assert db_conn.count_contacts(user_id=uid) == 1

    def test_delete_contacts_by_platform(self, db_conn):
        uid = db_conn.create_user(email="delc@test.com", password_hash="h")
        db_conn.insert_contacts_bulk([
            {"name": "YT", "handle": "", "email": "", "phone": "",
             "platform": "youtube", "avatar_url": "", "followers": 0, "tags": "[]"},
            {"name": "TK", "handle": "", "email": "", "phone": "",
             "platform": "tiktok", "avatar_url": "", "followers": 0, "tags": "[]"},
        ], user_id=uid)
        db_conn.delete_contacts(platform="youtube", user_id=uid)
        remaining = db_conn.get_contacts(user_id=uid)
        assert len(remaining) == 1
        assert remaining[0]["platform"] == "tiktok"


class TestTemplatesCRUD:

    def test_create_and_get_template(self, db_conn):
        uid = db_conn.create_user(email="tmpl@test.com", password_hash="h")
        tmpl_id = db_conn.create_template(
            user_id=uid, name="Quick Short",
            description="A quick short video template",
            config_json={"format": "short", "voice": "en-US-AriaNeural"},
        )
        assert tmpl_id
        tmpl = db_conn.get_template(tmpl_id, user_id=uid)
        assert tmpl["name"] == "Quick Short"
        assert tmpl["config_json"]["format"] == "short"

    def test_list_templates(self, db_conn):
        uid = db_conn.create_user(email="tmpl2@test.com", password_hash="h")
        db_conn.create_template(uid, "A", "desc", {})
        db_conn.create_template(uid, "B", "desc", {})
        templates = db_conn.get_templates(uid)
        assert len(templates) == 2

    def test_increment_template_use(self, db_conn):
        uid = db_conn.create_user(email="tmpl3@test.com", password_hash="h")
        tmpl_id = db_conn.create_template(uid, "Popular", "desc", {})
        db_conn.increment_template_use(tmpl_id)
        db_conn.increment_template_use(tmpl_id)
        tmpl = db_conn.get_template(tmpl_id, uid)
        assert tmpl["use_count"] == 2

    def test_delete_template(self, db_conn):
        uid = db_conn.create_user(email="tmpl4@test.com", password_hash="h")
        tmpl_id = db_conn.create_template(uid, "Gone", "desc", {})
        db_conn.delete_template(tmpl_id, uid)
        assert db_conn.get_template(tmpl_id, uid) is None


class TestTeamCRUD:

    def test_create_team_and_owner_membership(self, db_conn):
        uid = db_conn.create_user(email="owner@test.com", password_hash="h")
        team_id = db_conn.create_team(owner_id=uid, name="My Team")
        assert team_id
        team = db_conn.get_team_by_id(team_id)
        assert team["name"] == "My Team"
        assert team["owner_id"] == uid

        members = db_conn.get_team_members(team_id)
        assert len(members) == 1
        assert members[0]["role"] == "owner"
        assert members[0]["user_id"] == uid

    def test_add_team_member(self, db_conn):
        uid = db_conn.create_user(email="owner2@test.com", password_hash="h")
        db_conn.create_user(email="editor@test.com", password_hash="h")
        team_id = db_conn.create_team(owner_id=uid, name="Team 2")
        member_id = db_conn.add_team_member(team_id, "editor@test.com", role="editor")
        assert member_id
        members = db_conn.get_team_members(team_id)
        assert len(members) == 2

    def test_get_team_for_user(self, db_conn):
        uid = db_conn.create_user(email="findteam@test.com", password_hash="h")
        team_id = db_conn.create_team(owner_id=uid, name="Findable")
        team = db_conn.get_team_for_user(uid)
        assert team is not None
        assert team["id"] == team_id

    def test_remove_team_member(self, db_conn):
        uid = db_conn.create_user(email="rmowner@test.com", password_hash="h")
        team_id = db_conn.create_team(owner_id=uid, name="Remove Test")
        member_id = db_conn.add_team_member(team_id, "nobody@test.com", role="viewer")
        db_conn.remove_team_member(member_id, team_id)
        members = db_conn.get_team_members(team_id)
        assert len(members) == 1  # only owner remains


class TestSocialAccounts:

    def test_upsert_and_get_accounts(self, db_conn):
        uid = db_conn.create_user(email="acct@test.com", password_hash="h")
        acc_id = db_conn.upsert_account(
            platform="youtube", username="chan1",
            display_name="Channel One", user_id=uid,
        )
        assert acc_id > 0
        accounts = db_conn.get_accounts(user_id=uid)
        assert len(accounts) == 1
        assert accounts[0]["platform"] == "youtube"

    def test_upsert_updates_existing(self, db_conn):
        uid = db_conn.create_user(email="upsert@test.com", password_hash="h")
        id1 = db_conn.upsert_account(platform="tiktok", username="user1",
                                     display_name="Old", user_id=uid)
        id2 = db_conn.upsert_account(platform="tiktok", username="user1",
                                     display_name="New", user_id=uid)
        assert id1 == id2
        accounts = db_conn.get_accounts(user_id=uid)
        assert len(accounts) == 1
        assert accounts[0]["display_name"] == "New"

    def test_delete_account(self, db_conn):
        uid = db_conn.create_user(email="delacc@test.com", password_hash="h")
        acc_id = db_conn.upsert_account(platform="instagram", username="ig",
                                        user_id=uid)
        db_conn.delete_account(acc_id)
        assert db_conn.get_accounts(user_id=uid) == []


class TestStats:

    def test_get_stats(self, db_conn):
        uid = db_conn.create_user(email="stats@test.com", password_hash="h")
        db_conn.create_job(topic="J1", format="short", platforms=[], audience="a",
                           voice="v", style="s", privacy="p", user_id=uid)
        db_conn.create_job(topic="J2", format="short", platforms=[], audience="a",
                           voice="v", style="s", privacy="p", user_id=uid)
        stats = db_conn.get_stats(user_id=uid)
        assert stats["total_jobs"] == 2
        assert stats["completed_jobs"] == 0


class TestSettings:

    def test_get_set_setting(self, db_conn):
        db_conn.set_setting("test_key", "test_value")
        assert db_conn.get_setting("test_key") == "test_value"

    def test_get_setting_default(self, db_conn):
        assert db_conn.get_setting("nonexistent", default="fallback") == "fallback"
