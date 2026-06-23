"""Tests for the 3-tier cost routing system and Chinese video client."""
import pytest
from generators.agents.schemas import AssetSpec, AssetPlan, OptimizedAssetPlan
from generators.agents.cost_engineer import CostEngineer


def _make_asset(
    section_id=1, source="higgsfield_cinematic", model_key="cinematic_studio_3_0",
    prompt="cinematic shot of mountains", credit_cost=8, priority=2,
    visual_complexity="low", dollar_cost=0.0,
):
    return AssetSpec(
        section_id=section_id,
        asset_type="video_clip",
        source=source,
        prompt=prompt,
        model_key=model_key,
        duration_seconds=5,
        aspect_ratio="16:9",
        credit_cost=credit_cost,
        dollar_cost=dollar_cost,
        priority=priority,
        visual_complexity=visual_complexity,
    )


def _make_plan(assets):
    total_credits = sum(a.credit_cost for a in assets)
    paid = sum(1 for a in assets if a.source.startswith("higgsfield_"))
    free = len(assets) - paid
    return AssetPlan(
        assets=assets,
        total_credit_estimate=total_credits,
        free_asset_count=free,
        paid_asset_count=paid,
        notes="test plan",
    )


class TestCostEngineerRouting:
    """3-tier cost routing logic."""

    def test_priority3_always_downgraded_to_pexels(self):
        engineer = CostEngineer()
        assets = [_make_asset(priority=3, credit_cost=10, model_key="kling3_0")]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500)
        assert result.assets[0].source == "free_pexels_api"
        assert result.assets[0].credit_cost == 0
        assert len(result.swaps_made) == 1

    def test_medium_custom_routes_to_chinese(self):
        engineer = CostEngineer()
        assets = [_make_asset(
            priority=2,
            prompt="custom character walking through city",
            visual_complexity="medium_custom",
        )]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500, dollar_budget=20.0)
        assert result.assets[0].source == "chinese_open_source_api"
        assert result.assets[0].credit_cost == 0
        assert result.assets[0].dollar_cost > 0
        assert result.total_dollar_cost > 0

    def test_high_complexity_priority1_stays_premium(self):
        engineer = CostEngineer()
        assets = [_make_asset(
            priority=1,
            prompt="multi-character physics simulation explosion",
            visual_complexity="high_agentic_physics",
            credit_cost=10,
        )]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500)
        assert result.assets[0].source == "higgsfield_cinematic"
        assert result.total_credit_cost == 10

    def test_critical_save_downgrades_non_priority1(self):
        engineer = CostEngineer()
        assets = [
            _make_asset(priority=1, prompt="multi-character physics scene", visual_complexity="high_agentic_physics", credit_cost=10),
            _make_asset(section_id=2, priority=2, prompt="custom character shot", visual_complexity="high_agentic_physics", credit_cost=8),
        ]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=50, monthly_budget=500, dollar_budget=20.0)
        assert result.budget_state == "critical_save"
        assert result.assets[0].source == "higgsfield_cinematic"
        assert result.assets[1].source == "chinese_open_source_api"

    def test_low_complexity_goes_to_pexels(self):
        engineer = CostEngineer()
        assets = [_make_asset(
            source="free_pexels_api",
            model_key=None,
            prompt="abstract background loop",
            credit_cost=0,
            visual_complexity="low",
        )]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500)
        assert result.assets[0].source == "free_pexels_api"
        assert result.total_credit_cost == 0

    def test_dollar_budget_exhaustion_falls_to_pexels(self):
        engineer = CostEngineer()
        assets = [
            _make_asset(section_id=i, priority=2, prompt="custom character scene",
                        visual_complexity="medium_custom")
            for i in range(5)
        ]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500, dollar_budget=0.05)
        chinese_count = sum(1 for a in result.assets if a.source == "chinese_open_source_api")
        pexels_count = sum(1 for a in result.assets if a.source == "free_pexels_api")
        assert chinese_count >= 1
        assert pexels_count >= 1

    def test_character_prompt_picks_seedance(self):
        engineer = CostEngineer()
        assets = [_make_asset(
            priority=2,
            prompt="consistent character identity walking through park",
            visual_complexity="medium_custom",
        )]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500, dollar_budget=20.0)
        assert result.assets[0].source == "chinese_open_source_api"
        assert result.assets[0].model_key == "seedance2_opensource"

    def test_cinematic_prompt_picks_hunyuan(self):
        engineer = CostEngineer()
        assets = [_make_asset(
            priority=2,
            prompt="dramatic cinematic film establishing shot",
            visual_complexity="medium_custom",
        )]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500, dollar_budget=20.0)
        assert result.assets[0].source == "chinese_open_source_api"
        assert result.assets[0].model_key == "hunyuan_video"

    def test_generic_prompt_picks_wan(self):
        engineer = CostEngineer()
        assets = [_make_asset(
            priority=2,
            prompt="custom stylized abstract motion graphics",
            visual_complexity="medium_custom",
        )]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500, dollar_budget=20.0)
        assert result.assets[0].source == "chinese_open_source_api"
        assert result.assets[0].model_key == "wan2_7_opensource"

    def test_budget_state_healthy(self):
        engineer = CostEngineer()
        plan = _make_plan([_make_asset(source="free_pexels_api", model_key=None, credit_cost=0)])
        result = engineer.run(plan, remaining_credits=400, monthly_budget=500)
        assert result.budget_state == "healthy"

    def test_budget_state_warning(self):
        engineer = CostEngineer()
        plan = _make_plan([_make_asset(source="free_pexels_api", model_key=None, credit_cost=0)])
        result = engineer.run(plan, remaining_credits=200, monthly_budget=500)
        assert result.budget_state == "warning"

    def test_budget_state_critical(self):
        engineer = CostEngineer()
        plan = _make_plan([_make_asset(source="free_pexels_api", model_key=None, credit_cost=0)])
        result = engineer.run(plan, remaining_credits=50, monthly_budget=500)
        assert result.budget_state == "critical_save"

    def test_mixed_tier_plan(self):
        engineer = CostEngineer()
        assets = [
            _make_asset(section_id=1, priority=1, prompt="multi-character physics explosion",
                        visual_complexity="high_agentic_physics", credit_cost=10),
            _make_asset(section_id=2, priority=2, prompt="custom person walking in city",
                        visual_complexity="medium_custom", credit_cost=8),
            _make_asset(section_id=3, priority=3, prompt="generic landscape",
                        visual_complexity="low", credit_cost=5),
            _make_asset(section_id=4, priority=2, source="free_pexels_api",
                        model_key=None, prompt="abstract background",
                        visual_complexity="low", credit_cost=0),
        ]
        plan = _make_plan(assets)
        result = engineer.run(plan, remaining_credits=500, monthly_budget=500, dollar_budget=20.0)

        assert result.assets[0].source == "higgsfield_cinematic"
        assert result.assets[1].source == "chinese_open_source_api"
        assert result.assets[2].source == "free_pexels_api"
        assert result.assets[3].source == "free_pexels_api"

        assert result.total_credit_cost == 10
        assert result.total_dollar_cost > 0
        assert len(result.swaps_made) >= 2


class TestComplexityClassification:
    """Visual complexity auto-detection from prompts."""

    def test_physics_detected_as_high(self):
        engineer = CostEngineer()
        asset = _make_asset(prompt="multi-character physics simulation with particles")
        complexity = engineer._classify_complexity(asset)
        assert complexity == "high_agentic_physics"

    def test_character_detected_as_medium(self):
        engineer = CostEngineer()
        asset = _make_asset(prompt="a person walking through a forest", source="free_pexels_api",
                            model_key=None, credit_cost=0)
        complexity = engineer._classify_complexity(asset)
        assert complexity == "medium_custom"

    def test_generic_broll_detected_as_low(self):
        engineer = CostEngineer()
        asset = _make_asset(prompt="abstract gradient loop", source="free_pexels_api",
                            model_key=None, credit_cost=0)
        complexity = engineer._classify_complexity(asset)
        assert complexity == "low"

    def test_explicit_complexity_preserved(self):
        engineer = CostEngineer()
        asset = _make_asset(prompt="simple shot", visual_complexity="high_agentic_physics")
        complexity = engineer._classify_complexity(asset)
        assert complexity == "high_agentic_physics"


class TestChineseVideoClient:
    """Unit tests for the chinese_video_client module."""

    def test_model_catalog(self):
        from generators.chinese_video_client import CHINESE_MODELS
        assert "wan2_7_opensource" in CHINESE_MODELS
        assert "hunyuan_video" in CHINESE_MODELS
        assert "seedance2_opensource" in CHINESE_MODELS

    def test_estimate_cost(self):
        from generators.chinese_video_client import estimate_cost
        assert estimate_cost("wan2_7_opensource", 10) == pytest.approx(0.20)
        assert estimate_cost("hunyuan_video", 10) == pytest.approx(0.50)
        assert estimate_cost("seedance2_opensource", 10) == pytest.approx(0.40)

    def test_select_cheapest_default(self):
        from generators.chinese_video_client import select_cheapest_model
        assert select_cheapest_model("low") == "wan2_7_opensource"

    def test_select_character_consistency(self):
        from generators.chinese_video_client import select_cheapest_model
        assert select_cheapest_model("medium_custom", needs_character_consistency=True) == "seedance2_opensource"

    def test_select_cinematic(self):
        from generators.chinese_video_client import select_cheapest_model
        assert select_cheapest_model("medium_custom", needs_cinematic=True) == "hunyuan_video"


class TestSchemaUpdates:
    """Verify schema changes for 3-tier routing."""

    def test_asset_spec_has_dollar_cost(self):
        asset = _make_asset(dollar_cost=0.02)
        assert asset.dollar_cost == 0.02

    def test_asset_spec_has_visual_complexity(self):
        asset = _make_asset(visual_complexity="medium_custom")
        assert asset.visual_complexity == "medium_custom"

    def test_chinese_source_literal(self):
        asset = _make_asset(source="chinese_open_source_api", model_key="wan2_7_opensource")
        assert asset.source == "chinese_open_source_api"

    def test_optimized_plan_has_dollar_fields(self):
        plan = OptimizedAssetPlan(
            assets=[],
            total_credit_cost=0,
            total_dollar_cost=0.10,
            budget_state="healthy",
            credits_remaining_after=500,
            dollars_remaining_after=19.90,
            swaps_made=[],
            quality_impact="test",
        )
        assert plan.total_dollar_cost == 0.10
        assert plan.dollars_remaining_after == 19.90
