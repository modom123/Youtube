"""
Agent 3.5 — Cost Engineer
Deterministic 3-tier cost routing: Free (Pixabay) → Cheap (Chinese OSS) → Premium (Higgsfield).
"""
from __future__ import annotations
import re
from .base import BaseAgent
from .schemas import AssetSpec, AssetPlan, OptimizedAssetPlan


CHINESE_COST_PER_CLIP = {
    "wan2_7_opensource": 0.02,
    "hunyuan_video": 0.05,
    "seedance2_opensource": 0.04,
}

_PHYSICS_RE = re.compile(r"(physics|simulation|particles|explosion|collision|fluid|destruction)", re.I)
_CHARACTER_RE = re.compile(r"(person|character|people|walking|running|identity|face|human|man|woman)", re.I)
_CINEMATIC_RE = re.compile(r"(cinematic|film|dramatic|establishing shot|epic|sweeping)", re.I)


class CostEngineer(BaseAgent):
    name = "Cost Engineer"
    model = "claude-haiku-4-5-20251001"
    max_tokens = 3000
    system_prompt = ""

    def _classify_complexity(self, asset: AssetSpec) -> str:
        if asset.visual_complexity and asset.visual_complexity != "low":
            return asset.visual_complexity
        prompt = asset.prompt.lower()
        if _PHYSICS_RE.search(prompt):
            return "high_agentic_physics"
        if _CHARACTER_RE.search(prompt):
            return "medium_custom"
        return "low"

    def _pick_chinese_model(self, asset: AssetSpec) -> str:
        prompt = asset.prompt.lower()
        if _CHARACTER_RE.search(prompt):
            return "seedance2_opensource"
        if _CINEMATIC_RE.search(prompt):
            return "hunyuan_video"
        return "wan2_7_opensource"

    def run(self, asset_plan: AssetPlan, remaining_credits: int,
            monthly_budget: int = 500, dollar_budget: float = 0.0) -> OptimizedAssetPlan:
        budget_pct = remaining_credits / max(monthly_budget, 1)
        if budget_pct > 0.5:
            budget_state = "healthy"
        elif budget_pct > 0.25:
            budget_state = "warning"
        else:
            budget_state = "critical_save"

        swaps = []
        optimized = []
        total_credits = 0
        total_dollars = 0.0
        dollar_remaining = dollar_budget

        for asset in asset_plan.assets:
            a = asset.model_copy()
            complexity = self._classify_complexity(a)
            a.visual_complexity = complexity

            if a.source == "free_pixabay_api" or a.source == "free_stock_internal":
                a.credit_cost = 0
                a.dollar_cost = 0.0
                optimized.append(a)
                continue

            if a.priority == 3:
                old_source = a.source
                a.source = "free_pixabay_api"
                a.credit_cost = 0
                a.dollar_cost = 0.0
                a.model_key = None
                swaps.append(f"Section {a.section_id}: {old_source} → free_pixabay_api (priority 3 downgrade)")
                optimized.append(a)
                continue

            if a.priority == 1 and complexity == "high_agentic_physics":
                total_credits += a.credit_cost
                optimized.append(a)
                continue

            if complexity in ("medium_custom", "high_agentic_physics") and a.priority <= 2:
                if budget_state == "critical_save" and a.priority == 2:
                    model_key = self._pick_chinese_model(a)
                    clip_cost = CHINESE_COST_PER_CLIP.get(model_key, 0.02)
                    if dollar_remaining >= clip_cost:
                        old_source = a.source
                        a.source = "chinese_open_source_api"
                        a.model_key = model_key
                        a.credit_cost = 0
                        a.dollar_cost = clip_cost
                        dollar_remaining -= clip_cost
                        total_dollars += clip_cost
                        swaps.append(f"Section {a.section_id}: {old_source} → chinese_open_source_api/{model_key} (critical save)")
                        optimized.append(a)
                        continue

                if dollar_budget > 0 and dollar_remaining > 0:
                    model_key = self._pick_chinese_model(a)
                    clip_cost = CHINESE_COST_PER_CLIP.get(model_key, 0.02)
                    if dollar_remaining >= clip_cost:
                        old_source = a.source
                        a.source = "chinese_open_source_api"
                        a.model_key = model_key
                        a.credit_cost = 0
                        a.dollar_cost = clip_cost
                        dollar_remaining -= clip_cost
                        total_dollars += clip_cost
                        swaps.append(f"Section {a.section_id}: {old_source} → chinese_open_source_api/{model_key}")
                        optimized.append(a)
                        continue
                    else:
                        old_source = a.source
                        a.source = "free_pixabay_api"
                        a.credit_cost = 0
                        a.dollar_cost = 0.0
                        a.model_key = None
                        swaps.append(f"Section {a.section_id}: {old_source} → free_pixabay_api (dollar budget exhausted)")
                        optimized.append(a)
                        continue

            total_credits += a.credit_cost
            optimized.append(a)

        quality_parts = []
        if any("free_pixabay_api" in s for s in swaps):
            quality_parts.append("Some clips downgraded to stock footage")
        if any("chinese_open_source_api" in s for s in swaps):
            quality_parts.append("Some clips routed to Chinese open-source models")
        quality_impact = ". ".join(quality_parts) if quality_parts else "No quality impact"

        return OptimizedAssetPlan(
            assets=optimized,
            total_credit_cost=total_credits,
            total_dollar_cost=total_dollars,
            budget_state=budget_state,
            credits_remaining_after=remaining_credits - total_credits,
            dollars_remaining_after=dollar_remaining,
            swaps_made=swaps,
            quality_impact=quality_impact,
        )
