"""Tests for Hollywood agent blueprint tools."""
import json

import pytest


@pytest.fixture
def blueprint_dir(tmp_path):
    """Create a temp directory with a blueprint.json."""
    bp_data = {
        "title": "AI Trends 2025",
        "hook": "These 5 AI tools will change everything in 2025",
        "core_angle": "Practical AI tools for everyday productivity",
        "target_audience": "tech-savvy professionals 25-45",
        "content_type": "listicle",
        "tone": "conversational",
        "estimated_ctr": 0.08,
        "trend_score": 7.5,
        "keywords": ["ai tools", "ai trends", "productivity", "automation", "2025"],
        "thumbnail_concept": "Split screen: human vs AI working side by side",
        "rationale": "AI fatigue hasn't set in yet; practical angle differentiates from hype",
    }
    bp_path = tmp_path / "blueprint.json"
    bp_path.write_text(json.dumps(bp_data, indent=2))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"niche": "AI Trends"}))
    return tmp_path, bp_data


class TestBlueprintTools:
    def test_get_blueprint(self, blueprint_dir, db_conn):
        bp_dir, bp_data = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI Trends", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_get_blueprint
        result = _tool_get_blueprint(job_id)
        assert "error" not in result
        assert result["blueprint"]["title"] == "AI Trends 2025"
        assert result["blueprint"]["tone"] == "conversational"

    def test_get_blueprint_not_found(self, db_conn):
        from generators.hollywood_agent import _tool_get_blueprint
        result = _tool_get_blueprint(99999)
        assert "error" in result

    def test_update_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI Trends", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_update_blueprint
        result = _tool_update_blueprint(job_id, {
            "title": "Top 10 AI Tools for 2025",
            "tone": "dramatic",
            "trend_score": 9.0,
        })
        assert "error" not in result
        assert "title" in result["updated_fields"]
        assert result["new_values"]["title"] == "Top 10 AI Tools for 2025"

        with open(bp_dir / "blueprint.json") as f:
            saved = json.load(f)
        assert saved["title"] == "Top 10 AI Tools for 2025"
        assert saved["tone"] == "dramatic"

    def test_update_blueprint_invalid_field(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_update_blueprint
        result = _tool_update_blueprint(job_id, {"fake_field": "value"})
        assert "error" in result

    def test_update_blueprint_invalid_content_type(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_update_blueprint
        result = _tool_update_blueprint(job_id, {"content_type": "invalid_type"})
        assert "error" in result

    def test_update_blueprint_ctr_range(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_update_blueprint
        result = _tool_update_blueprint(job_id, {"estimated_ctr": 1.5})
        assert "error" in result

    def test_create_blueprint(self, db_conn):
        from generators.hollywood_agent import _tool_create_blueprint
        result = _tool_create_blueprint(
            title="Crypto for Beginners",
            hook="You're losing money every day you don't understand this",
            core_angle="Simple explanations for complex crypto concepts",
            target_audience="18-30 curious about investing",
            content_type="educational",
            tone="conversational",
            keywords=["crypto", "bitcoin", "investing", "beginners"],
            estimated_ctr=0.07,
            trend_score=8.0,
            thumbnail_concept="Confused person next to Bitcoin logo",
            rationale="Crypto market uptick creates renewed interest",
        )
        assert "error" not in result
        assert result["status"] == "created"
        assert result["blueprint"]["title"] == "Crypto for Beginners"
        assert result["job_id"] > 0

    def test_create_blueprint_invalid_tone(self, db_conn):
        from generators.hollywood_agent import _tool_create_blueprint
        result = _tool_create_blueprint(
            title="Test", hook="test", core_angle="test",
            target_audience="test", content_type="educational",
            tone="boring",
            keywords=["test"],
        )
        assert "error" in result

    def test_clone_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        source_id = db_conn.create_job(
            topic="AI Trends", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(source_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_clone_blueprint
        result = _tool_clone_blueprint(source_id, overrides={
            "title": "AI Trends Remix",
            "tone": "urgent",
        })
        assert "error" not in result
        assert result["new_job_id"] > 0
        assert result["new_job_id"] != source_id
        assert result["blueprint"]["title"] == "AI Trends Remix"
        assert result["blueprint"]["tone"] == "urgent"
        assert result["blueprint"]["core_angle"] == "Practical AI tools for everyday productivity"

    def test_clone_blueprint_no_overrides(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        source_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(source_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_clone_blueprint
        result = _tool_clone_blueprint(source_id)
        assert "error" not in result
        assert result["blueprint"]["title"] == "AI Trends 2025"

    def test_analyze_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _tool_analyze_blueprint
        result = _tool_analyze_blueprint(job_id)
        assert "error" not in result
        assert "strengths" in result
        assert "weaknesses" in result
        assert "suggestions" in result
        assert "overall_score" in result
        assert result["overall_score"] > 0

    def test_analyze_blueprint_weak(self, db_conn, tmp_path):
        bp_data = {
            "title": "Hi",
            "hook": "",
            "core_angle": "",
            "target_audience": "everyone",
            "content_type": "educational",
            "tone": "conversational",
            "estimated_ctr": 0.25,
            "trend_score": 2.0,
            "keywords": ["test"],
            "thumbnail_concept": "",
            "rationale": "",
        }
        (tmp_path / "blueprint.json").write_text(json.dumps(bp_data))
        (tmp_path / "manifest.json").write_text("{}")
        job_id = db_conn.create_job(
            topic="Weak", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(tmp_path / "manifest.json"))
        from generators.hollywood_agent import _tool_analyze_blueprint
        result = _tool_analyze_blueprint(job_id)
        assert len(result["weaknesses"]) > len(result["strengths"])

    def test_compare_blueprints(self, db_conn, tmp_path):
        bp_a = {
            "title": "AI Tools", "hook": "Amazing", "core_angle": "practical",
            "target_audience": "pros", "content_type": "listicle",
            "tone": "conversational", "estimated_ctr": 0.08,
            "trend_score": 7.0, "keywords": ["ai"],
            "thumbnail_concept": "split screen", "rationale": "trending",
        }
        bp_b = dict(bp_a)
        bp_b["title"] = "Crypto Tools"
        bp_b["tone"] = "dramatic"
        bp_b["trend_score"] = 9.0

        dir_a = tmp_path / "job_a"
        dir_a.mkdir()
        (dir_a / "blueprint.json").write_text(json.dumps(bp_a))
        (dir_a / "manifest.json").write_text("{}")

        dir_b = tmp_path / "job_b"
        dir_b.mkdir()
        (dir_b / "blueprint.json").write_text(json.dumps(bp_b))
        (dir_b / "manifest.json").write_text("{}")

        id_a = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(id_a, status="done", manifest_path=str(dir_a / "manifest.json"))
        id_b = db_conn.create_job(
            topic="Crypto", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(id_b, status="done", manifest_path=str(dir_b / "manifest.json"))

        from generators.hollywood_agent import _tool_compare_blueprints
        result = _tool_compare_blueprints(id_a, id_b)
        assert "error" not in result
        assert result["fields"]["title"]["match"] is False
        assert result["fields"]["tone"]["match"] is False
        assert result["fields"]["core_angle"]["match"] is True
        assert result["different_fields"] >= 3
        assert 0 <= result["similarity_pct"] <= 100


class TestBlueprintDispatch:
    def test_dispatch_get_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("get_blueprint", {"job_id": job_id}))
        assert "blueprint" in result

    def test_dispatch_update_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("update_blueprint", {
            "job_id": job_id,
            "updates": {"title": "Updated Title"}
        }))
        assert result["updated_fields"] == ["title"]

    def test_dispatch_create_blueprint(self, db_conn):
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("create_blueprint", {
            "title": "Test Video",
            "hook": "You won't believe this",
            "core_angle": "Unique angle",
            "target_audience": "everyone",
            "content_type": "tutorial",
            "tone": "inspiring",
            "keywords": ["test", "video", "tutorial"],
        }))
        assert result["status"] == "created"

    def test_dispatch_analyze_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("analyze_blueprint", {"job_id": job_id}))
        assert "overall_score" in result

    def test_dispatch_list_blueprints(self, db_conn):
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("list_blueprints", {}))
        assert "blueprints" in result

    def test_dispatch_clone_blueprint(self, blueprint_dir, db_conn):
        bp_dir, _ = blueprint_dir
        job_id = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(job_id, status="done", manifest_path=str(bp_dir / "manifest.json"))
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("clone_blueprint", {
            "source_job_id": job_id,
            "overrides": {"title": "Cloned!"}
        }))
        assert result["blueprint"]["title"] == "Cloned!"

    def test_dispatch_compare_blueprints(self, blueprint_dir, db_conn, tmp_path):
        bp_dir, bp_data = blueprint_dir
        id_a = db_conn.create_job(
            topic="AI", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(id_a, status="done", manifest_path=str(bp_dir / "manifest.json"))
        dir_b = tmp_path / "job_b"
        dir_b.mkdir()
        bp_b = dict(bp_data)
        bp_b["title"] = "Different"
        (dir_b / "blueprint.json").write_text(json.dumps(bp_b))
        (dir_b / "manifest.json").write_text("{}")
        id_b = db_conn.create_job(
            topic="B", format="short", platforms=[],
            audience="general", voice="alloy", style="fire", privacy="private",
        )
        db_conn.update_job(id_b, status="done", manifest_path=str(dir_b / "manifest.json"))
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("compare_blueprints", {
            "job_id_a": id_a, "job_id_b": id_b,
        }))
        assert "similarity_pct" in result
