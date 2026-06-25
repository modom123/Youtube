"""
Pydantic v2 schemas for the 5-Agent Faceless YouTube Production Engine.
Each schema is the output contract of its corresponding agent.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Agent 1: Trend Architect output ─────────────────────────────────────────

class VideoBlueprint(BaseModel):
    title: str = Field(description="Optimised video title (max 60 chars)")
    hook: str = Field(description="Opening hook sentence for first 3 seconds")
    core_angle: str = Field(description="Unique angle that differentiates this video")
    target_audience: str = Field(description="Primary audience persona")
    content_type: Literal["educational", "listicle", "story", "tutorial", "opinion"]
    tone: Literal["authoritative", "conversational", "dramatic", "inspiring", "urgent"]
    estimated_ctr: float = Field(ge=0.0, le=1.0, description="Predicted CTR 0-1")
    trend_score: float = Field(ge=0.0, le=10.0, description="Trend relevance score 0-10")
    keywords: list[str] = Field(min_length=3, max_length=10)
    thumbnail_concept: str = Field(description="Visual concept for thumbnail")
    rationale: str = Field(description="Why this angle wins right now")


# ── Agent 2: Narrative Designer output ──────────────────────────────────────

class ScriptSection(BaseModel):
    section_id: int
    label: str
    narration: str
    visual_direction: str = Field(description="What should appear on screen")
    b_roll_keywords: list[str] = Field(min_length=1, max_length=5)
    duration_seconds: int = Field(ge=3, le=120)
    emotional_beat: Literal["curiosity", "tension", "relief", "excitement", "reflection"]


class FullScript(BaseModel):
    title: str
    description: str = Field(description="YouTube description (first 125 chars are above fold)")
    hashtags: list[str] = Field(min_length=3, max_length=15)
    sections: list[ScriptSection] = Field(min_length=3)
    total_duration_seconds: int
    narration_full: str = Field(description="Complete narration joined for TTS")
    thumbnail_prompt: str = Field(description="Detailed image-gen prompt for thumbnail")
    chapter_timestamps: list[str] = Field(description="Formatted as '00:00 - Title'")


# ── Agent 3: Asset Curator output ───────────────────────────────────────────

AssetSource = Literal["higgsfield_cinematic", "higgsfield_ugc", "free_pexels_api", "free_stock_internal"]

class AssetSpec(BaseModel):
    section_id: int
    asset_type: Literal["video_clip", "image", "animation"]
    source: AssetSource
    prompt: str = Field(description="Generation prompt or Pexels search query")
    model_key: Optional[str] = Field(None, description="Higgsfield model key if source=higgsfield_*")
    duration_seconds: Optional[int] = None
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    credit_cost: int = Field(ge=0, description="Estimated Higgsfield credits (0 for free sources)")
    priority: int = Field(ge=1, le=3, description="1=must-have, 2=nice-to-have, 3=optional")


class AssetPlan(BaseModel):
    assets: list[AssetSpec]
    total_credit_estimate: int
    free_asset_count: int
    paid_asset_count: int
    notes: str


# ── Agent 3.5: Cost Engineer output ─────────────────────────────────────────

BudgetState = Literal["healthy", "warning", "critical_save"]

class OptimizedAssetPlan(BaseModel):
    assets: list[AssetSpec]
    total_credit_cost: int
    budget_state: BudgetState
    credits_remaining_after: int
    swaps_made: list[str] = Field(description="Human-readable list of cost substitutions")
    quality_impact: str = Field(description="Assessment of quality after optimisations")


# ── Agent 4: Growth Engineer output ─────────────────────────────────────────

class SEOPackage(BaseModel):
    title_final: str = Field(description="SEO-optimised title (max 60 chars)")
    description_full: str = Field(description="Full YouTube description with timestamps")
    tags: list[str] = Field(min_length=10, max_length=30)
    thumbnail_text: str = Field(description="Max 5 words for thumbnail overlay")
    end_screen_cta: str = Field(description="Call-to-action for end screen")
    pinned_comment: str = Field(description="First comment to pin for engagement")
    upload_timing: str = Field(description="Recommended day and hour in UTC")
    predicted_views_30d: int = Field(ge=0)
    ab_title_variants: list[str] = Field(min_length=2, max_length=3)


# ── Pipeline result ──────────────────────────────────────────────────────────

class ProductionResult(BaseModel):
    niche: str
    blueprint: VideoBlueprint
    script: FullScript
    asset_plan: OptimizedAssetPlan
    seo: SEOPackage
    pipeline_cost_credits: int
    status: Literal["success", "partial", "failed"]
    errors: list[str] = Field(default_factory=list)
    video_path: str = ""
    audio_path: str = ""
    thumbnail_path: str = ""
    manifest_path: str = ""
