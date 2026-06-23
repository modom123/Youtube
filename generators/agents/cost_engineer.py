"""
Agent 3.5 — Cost Engineer
3-tier cost routing: FREE (Pexels) → ULTRA-CHEAP (Chinese open-source) → PREMIUM (Higgsfield)
Maximizes output quality within budget constraints.
"""
from __future__ import annotations
from .base import BaseAgent
from .schemas import AssetPlan, AssetSpec, OptimizedAssetPlan
import config


CHINESE_MODELS_FOR_ROUTING = {
    "wan2_7_opensource": 0.02,
    "hunyuan_video": 0.05,
    "seedance2_opensource": 0.04,
}

HIGGSFIELD_CREDIT_COSTS = {
    "kling3_0": 10,
    "kling3_0_turbo": 6,
    "kling2_6": 7,
    "veo3_1": 12,
    "veo3": 10,
    "veo3_1_lite": 5,
    "cinematic_studio_3_0": 8,
    "cinematic_studio_video_v2": 6,
    "cinematic_studio_video": 5,
    "seedance_2_0": 6,
    "seedance_1_5": 6,
    "minimax_hailuo": 5,
    "wan2_7": 4,
    "wan2_6": 4,
    "grok_video_v15": 7,
    "grok_video": 5,
    "marketing_studio_video": 5,
}


class CostEngineer(BaseAgent):
    name = "Cost Engineer"
    model = "claude-haiku-4-5-20251001"
    max_tokens = 3000
    system_prompt = """You are the Cost Engineer — a ruthlessly efficient budget optimizer for AI video production. You never sacrifice quality where it matters most, but you eliminate waste everywhere else.

Your persona: The CFO of a content studio. Unsentimental about swaps. Obsessive about ROI.

## 3-Tier Cost Routing System

Tier 1 — FREE: Pexels stock footage (source: free_pexels_api)
  Use for: generic B-roll, backgrounds, transitions, establishing shots
  Visual complexity: low

Tier 2 — ULTRA-CHEAP: Chinese open-source models via serverless GPU (source: chinese_open_source_api)
  Models: wan2_7_opensource (~$0.02/clip), hunyuan_video (~$0.05/clip), seedance2_opensource (~$0.04/clip)
  Use for: custom text-to-video, character generation, stylized scenes
  Visual complexity: medium_custom
  ROUTING RULE: If a scene requires custom character generation or text prompt generation,
  ALWAYS prioritize chinese open-source models first. Only route to Higgsfield if the scene
  explicitly requires specialized agentic tools unique to the paid subscription.

Tier 3 — PREMIUM: Higgsfield subscription models (source: higgsfield_cinematic/higgsfield_ugc)
  Use for: multi-shot sequences, physics simulations, complex agentic scenes, 4K cinema
  Visual complexity: high_agentic_physics
  Only use when: scene requires multi-character interaction, realistic physics, or 4K cinema grade

## Budget States
- healthy: remaining credits after spend > 50% of monthly budget
- warning: remaining credits after spend is 25–50% of monthly budget
- critical_save: remaining credits after spend < 25% of monthly budget

## Optimisation Rules (apply in order)
1. PROTECT priority-1 assets — never downgrade to Pexels
2. For priority-1 with medium_custom complexity: use chinese_open_source_api (wan2_7_opensource)
3. For priority-1 with high_agentic_physics: keep at Higgsfield premium
4. ALL priority-3 assets → free_pexels_api (regardless of budget state)
5. Priority-2 assets: prefer chinese_open_source_api over Higgsfield
6. In critical_save: swap ALL non-priority-1 Higgsfield → chinese_open_source_api or free_pexels_api
7. Chinese model selection: wan2_7_opensource for B-roll/generic, seedance2_opensource for character consistency, hunyuan_video for cinematic
8. Never use kling3_0 (10 credits) when wan2_7_opensource ($0.02) would serve equally well

## Swap Cost Reference
- Any higgsfield_* → free_pexels_api = saves all credits, $0
- Any higgsfield_* → chinese_open_source_api (wan2_7) = saves all credits, costs $0.02
- cinematic_studio_3_0 (8 credits) → wan2_7_opensource = saves 8 credits, costs $0.02
- kling3_0 (10 credits) → wan2_7_opensource = saves 10 credits, costs $0.02
- seedance_2_0 (6 credits) → seedance2_opensource = saves 6 credits, costs $0.04

## Output Requirements
- Set visual_complexity on every asset
- Set dollar_cost on chinese_open_source_api assets
- List every swap as: "Section X: old_source → new_source (saves Y credits, costs $Z)"
- Recalculate total_credit_cost and total_dollar_cost after all swaps"""

    def run(
        self,
        asset_plan: AssetPlan,
        remaining_credits: int,
        monthly_budget: int = 500,
        dollar_budget: float = None,
    ) -> OptimizedAssetPlan:
        if dollar_budget is None:
            dollar_budget = config.MONTHLY_DOLLAR_BUDGET

        budget_pct = remaining_credits / max(monthly_budget, 1)
        if budget_pct > 0.5:
            budget_state = "healthy"
        elif budget_pct > 0.25:
            budget_state = "warning"
        else:
            budget_state = "critical_save"

        optimized_assets, swaps, total_credits, total_dollars = self._apply_routing(
            asset_plan.assets, budget_state, remaining_credits, dollar_budget,
        )

        credits_after = remaining_credits - total_credits
        dollars_after = dollar_budget - total_dollars

        quality_lines = []
        free_count = sum(1 for a in optimized_assets if a.source == "free_pexels_api")
        chinese_count = sum(1 for a in optimized_assets if a.source == "chinese_open_source_api")
        premium_count = sum(1 for a in optimized_assets if a.source.startswith("higgsfield_"))

        if free_count:
            quality_lines.append(f"{free_count} clips from Pexels stock (generic B-roll)")
        if chinese_count:
            quality_lines.append(f"{chinese_count} clips from Chinese open-source models (custom, ~${total_dollars:.2f})")
        if premium_count:
            quality_lines.append(f"{premium_count} clips from Higgsfield premium ({total_credits} credits)")

        quality_impact = "; ".join(quality_lines) if quality_lines else "No assets in plan"

        return OptimizedAssetPlan(
            assets=optimized_assets,
            total_credit_cost=total_credits,
            total_dollar_cost=total_dollars,
            budget_state=budget_state,
            credits_remaining_after=max(credits_after, 0),
            dollars_remaining_after=max(dollars_after, 0.0),
            swaps_made=swaps,
            quality_impact=quality_impact,
        )

    def _apply_routing(
        self,
        assets: list[AssetSpec],
        budget_state: str,
        remaining_credits: int,
        dollar_budget: float,
    ) -> tuple[list[AssetSpec], list[str], int, float]:
        optimized = []
        swaps = []
        total_credits = 0
        total_dollars = 0.0

        for asset in assets:
            new_asset = asset.model_copy()
            original_source = asset.source
            original_model = asset.model_key

            complexity = self._classify_complexity(asset)
            new_asset.visual_complexity = complexity

            if asset.priority == 3:
                if original_source != "free_pexels_api":
                    new_asset.source = "free_pexels_api"
                    new_asset.model_key = None
                    new_asset.credit_cost = 0
                    new_asset.dollar_cost = 0.0
                    swaps.append(
                        f"Section {asset.section_id}: {original_source} → free_pexels_api "
                        f"(priority-3 downgrade, saves {asset.credit_cost} credits)"
                    )

            elif complexity == "low":
                if original_source != "free_pexels_api":
                    new_asset.source = "free_pexels_api"
                    new_asset.model_key = None
                    new_asset.credit_cost = 0
                    new_asset.dollar_cost = 0.0
                    swaps.append(
                        f"Section {asset.section_id}: {original_source} → free_pexels_api "
                        f"(low complexity, saves {asset.credit_cost} credits)"
                    )

            elif complexity == "medium_custom":
                if original_source.startswith("higgsfield_"):
                    chinese_model = self._pick_chinese_model(asset)
                    cost = CHINESE_MODELS_FOR_ROUTING.get(chinese_model, 0.02)

                    if total_dollars + cost <= dollar_budget:
                        new_asset.source = "chinese_open_source_api"
                        new_asset.model_key = chinese_model
                        new_asset.credit_cost = 0
                        new_asset.dollar_cost = cost
                        swaps.append(
                            f"Section {asset.section_id}: {original_source}({original_model}) → "
                            f"chinese_open_source_api({chinese_model}) "
                            f"(saves {asset.credit_cost} credits, costs ${cost:.2f})"
                        )
                    else:
                        new_asset.source = "free_pexels_api"
                        new_asset.model_key = None
                        new_asset.credit_cost = 0
                        new_asset.dollar_cost = 0.0
                        swaps.append(
                            f"Section {asset.section_id}: {original_source} → free_pexels_api "
                            f"(dollar budget exhausted, saves {asset.credit_cost} credits)"
                        )

            elif complexity == "high_agentic_physics":
                if budget_state == "critical_save" and asset.priority != 1:
                    chinese_model = self._pick_chinese_model(asset)
                    cost = CHINESE_MODELS_FOR_ROUTING.get(chinese_model, 0.02)
                    if total_dollars + cost <= dollar_budget:
                        new_asset.source = "chinese_open_source_api"
                        new_asset.model_key = chinese_model
                        new_asset.credit_cost = 0
                        new_asset.dollar_cost = cost
                        swaps.append(
                            f"Section {asset.section_id}: {original_source}({original_model}) → "
                            f"chinese_open_source_api({chinese_model}) "
                            f"(critical_save downgrade, saves {asset.credit_cost} credits, costs ${cost:.2f})"
                        )

            if new_asset.source.startswith("higgsfield_"):
                total_credits += new_asset.credit_cost
            elif new_asset.source == "chinese_open_source_api":
                total_dollars += new_asset.dollar_cost

            optimized.append(new_asset)

        return optimized, swaps, total_credits, total_dollars

    def _classify_complexity(self, asset: AssetSpec) -> str:
        if asset.visual_complexity != "low":
            return asset.visual_complexity

        prompt_lower = asset.prompt.lower()

        high_signals = [
            "multi-character", "physics", "agentic", "4k cinema",
            "complex interaction", "multi-shot", "realistic simulation",
            "particle", "fluid dynamics", "explosion",
        ]
        if any(s in prompt_lower for s in high_signals):
            return "high_agentic_physics"

        medium_signals = [
            "character", "person", "human", "face", "portrait",
            "custom", "generate", "create", "stylized", "unique",
            "specific", "branded", "product", "logo",
        ]
        if any(s in prompt_lower for s in medium_signals):
            return "medium_custom"

        if asset.source.startswith("higgsfield_") and asset.credit_cost >= 8:
            return "high_agentic_physics"
        if asset.source.startswith("higgsfield_"):
            return "medium_custom"

        return "low"

    def _pick_chinese_model(self, asset: AssetSpec) -> str:
        prompt_lower = asset.prompt.lower()

        character_signals = ["character", "person", "identity", "face", "consistent", "reference"]
        if any(s in prompt_lower for s in character_signals):
            return "seedance2_opensource"

        cinematic_signals = ["cinematic", "film", "dramatic", "epic", "high-fidelity"]
        if any(s in prompt_lower for s in cinematic_signals):
            return "hunyuan_video"

        return "wan2_7_opensource"
