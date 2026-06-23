"""
ProductionStudioEngine — orchestrates the 5-agent pipeline and drives
actual asset generation (audio + video assembly).
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Callable, Optional

import config
from generators.agents import (
    TrendArchitect,
    NarrativeDesigner,
    AssetCurator,
    CostEngineer,
    GrowthEngineer,
)
from generators.agents.schemas import (
    VideoBlueprint,
    FullScript,
    AssetPlan,
    OptimizedAssetPlan,
    SEOPackage,
    ProductionResult,
    AssetSpec,
)


ProgressCallback = Callable[[str, int], None]  # (message, percent)


def _noop(msg: str, pct: int) -> None:
    pass


class ProductionStudioEngine:
    """
    Runs the full 5-agent → asset generation → video assembly pipeline.
    """

    def __init__(
        self,
        monthly_budget: int = 500,
        progress_callback: ProgressCallback = _noop,
        subscription_tier: str = "free",
    ):
        self.monthly_budget = monthly_budget
        self.cb = progress_callback

        # Instantiate agents and apply tier-based model routing
        self.trend_architect = TrendArchitect()
        self.narrative_designer = NarrativeDesigner()
        self.asset_curator = AssetCurator()
        self.cost_engineer = CostEngineer()
        self.growth_engineer = GrowthEngineer()

        for agent in (
            self.trend_architect, self.narrative_designer,
            self.asset_curator, self.cost_engineer, self.growth_engineer,
        ):
            agent.set_tier(subscription_tier)

    # ── Public entry point ───────────────────────────────────────────────────

    def run_daily_pipeline(
        self,
        niche: str,
        remaining_credits: int = 500,
        target_duration: int = 480,
        audience: str = "",
        is_portrait: bool = False,
        voice: str = None,
        thumbnail_style: str = "fire",
        privacy: str = "private",
        dry_run: bool = False,
        research_enabled: bool = True,
        competitor_titles: list[str] = None,
        job_dir: Optional[Path] = None,
        platforms: list[str] = None,
    ) -> ProductionResult:
        """
        Full pipeline: niche → 5 agents → assets → video → manifest.
        Returns a ProductionResult with all outputs.
        """
        from generators import audio_generator, video_generator, media_fetcher, thumbnail_generator
        from generators.researcher import research_topic, brief_to_context
        from generators import higgsfield_mcp
        from utils import file_manager, logger

        voice = voice or config.DEFAULT_VOICE
        errors: list[str] = []
        blueprint: VideoBlueprint | None = None
        script: FullScript | None = None
        asset_plan: OptimizedAssetPlan | None = None
        seo: SEOPackage | None = None

        # Create job dir
        if job_dir is None:
            job_dir = file_manager.job_dir(niche, "studio")

        self.cb("Setting up job directory…", 2)

        # ── Research ─────────────────────────────────────────────────────────
        research_context = ""
        if research_enabled:
            self.cb("Researching topic…", 5)
            try:
                brief = research_topic(niche)
                research_context = brief_to_context(brief)
                rp = job_dir / "research.json"
                rp.write_text(json.dumps({
                    "topic": brief.topic,
                    "summary": brief.summary,
                    "key_facts": brief.key_facts,
                    "data_points": brief.data_points,
                    "sources": brief.sources,
                }, indent=2))
            except Exception as e:
                errors.append(f"Research failed: {e}")

        # ── Agent 1: Trend Architect ──────────────────────────────────────────
        self.cb("Agent 1/5 — Trend Architect analysing niche…", 12)
        try:
            blueprint = self.trend_architect.run(
                niche=niche,
                research_context=research_context,
                competitor_titles=competitor_titles or [],
            )
            (job_dir / "blueprint.json").write_text(blueprint.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"Trend Architect failed: {e}")
            return ProductionResult(
                niche=niche, blueprint=VideoBlueprint(**_blank_blueprint(niche)),
                script=FullScript(**_blank_script(niche)), asset_plan=_blank_asset_plan(),
                seo=SEOPackage(**_blank_seo(niche)), pipeline_cost_credits=0,
                status="failed", errors=errors,
            )

        # ── Agent 2: Narrative Designer ───────────────────────────────────────
        self.cb("Agent 2/5 — Narrative Designer writing script…", 25)
        try:
            script = self.narrative_designer.run(
                blueprint=blueprint,
                target_duration=target_duration,
                audience=audience,
            )
            (job_dir / "script.json").write_text(script.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"Narrative Designer failed: {e}")
            return ProductionResult(
                niche=niche, blueprint=blueprint,
                script=FullScript(**_blank_script(blueprint.title)),
                asset_plan=_blank_asset_plan(), seo=SEOPackage(**_blank_seo(blueprint.title)),
                pipeline_cost_credits=0, status="failed", errors=errors,
            )

        # ── Agent 3: Asset Curator ────────────────────────────────────────────
        self.cb("Agent 3/5 — Asset Curator planning visuals…", 38)
        try:
            raw_asset_plan = self.asset_curator.run(
                script=script,
                blueprint=blueprint,
                is_portrait=is_portrait,
            )
            (job_dir / "asset_plan_raw.json").write_text(raw_asset_plan.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"Asset Curator failed: {e}")
            raw_asset_plan = AssetPlan(assets=[], total_credit_estimate=0, free_asset_count=0, paid_asset_count=0, notes="failed")

        # ── Agent 3.5: Cost Engineer ──────────────────────────────────────────
        self.cb("Agent 3.5/5 — Cost Engineer optimising budget…", 45)
        try:
            asset_plan = self.cost_engineer.run(
                asset_plan=raw_asset_plan,
                remaining_credits=remaining_credits,
                monthly_budget=self.monthly_budget,
            )
            (job_dir / "asset_plan_optimised.json").write_text(asset_plan.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"Cost Engineer failed: {e}")
            asset_plan = OptimizedAssetPlan(
                assets=raw_asset_plan.assets,
                total_credit_cost=raw_asset_plan.total_credit_estimate,
                budget_state="healthy",
                credits_remaining_after=remaining_credits,
                swaps_made=[],
                quality_impact="Optimisation skipped due to error",
            )

        # ── Agent 4: Growth Engineer ──────────────────────────────────────────
        self.cb("Agent 4/5 — Growth Engineer crafting SEO package…", 52)
        try:
            seo = self.growth_engineer.run(blueprint=blueprint, script=script)
            (job_dir / "seo.json").write_text(seo.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"Growth Engineer failed: {e}")
            seo = SEOPackage(**_blank_seo(blueprint.title))

        # ── Generate audio ────────────────────────────────────────────────────
        self.cb("Generating voiceover…", 58)
        audio_path = job_dir / "voiceover.mp3"
        try:
            audio_generator.generate_audio(
                text=script.narration_full,
                output_path=audio_path,
                voice=voice,
            )
            duration = audio_generator.get_audio_duration(audio_path)
        except Exception as e:
            errors.append(f"Audio generation failed: {e}")
            duration = target_duration

        # ── Fetch / generate assets ───────────────────────────────────────────
        self.cb("Fetching and generating visual assets…", 65)
        stock_dir = job_dir / "stock"
        ai_clips_dir = job_dir / "ai_clips"
        ai_clips_dir.mkdir(parents=True, exist_ok=True)

        # Group assets by source
        higgsfield_assets = [a for a in asset_plan.assets if a.source.startswith("higgsfield_")]
        pexels_assets = [a for a in asset_plan.assets if a.source == "free_pexels_api"]

        # Stock media from Pexels
        pexels_keywords = list({kw for a in pexels_assets for kw in a.prompt.split()[:3]})
        pexels_keywords = pexels_keywords or script.sections[0].b_roll_keywords[:3] if script.sections else ["abstract background"]

        video_clips: list[Path] = []
        image_clips: list[Path] = []
        try:
            video_clips, image_clips = media_fetcher.fetch_media_for_topic(
                keywords=pexels_keywords[:5],
                output_dir=stock_dir,
                video_count=max(4, len(pexels_assets)),
                is_portrait=is_portrait,
            )
        except Exception as e:
            errors.append(f"Pexels fetch failed: {e}")

        # Higgsfield AI clips via MCP
        ai_clips: list[Path] = []
        if higgsfield_assets and not dry_run:
            self.cb("Generating AI video clips via Higgsfield…", 72)
            try:
                prompts = [a.prompt for a in higgsfield_assets[:6]]
                model_key = higgsfield_assets[0].model_key or "cinematic_studio_3_0"
                aspect = higgsfield_assets[0].aspect_ratio
                ai_clips = higgsfield_mcp.generate_clips_via_mcp(
                    prompts=prompts,
                    output_dir=ai_clips_dir,
                    model_id=model_key,
                    aspect_ratio=aspect,
                )
            except Exception as e:
                errors.append(f"Higgsfield generation failed: {e}")

        all_video_clips = ai_clips + list(video_clips)

        # ── Thumbnail ─────────────────────────────────────────────────────────
        self.cb("Generating thumbnail…", 78)
        thumbnail_path = job_dir / "thumbnail.jpg"
        try:
            thumbnail_generator.generate_thumbnail(
                title=seo.thumbnail_text or blueprint.title,
                output_path=thumbnail_path,
                background_image_path=image_clips[0] if image_clips else None,
                style=thumbnail_style,
                width=1280,
                height=720,
            )
        except Exception as e:
            errors.append(f"Thumbnail failed: {e}")

        # ── Assemble video ────────────────────────────────────────────────────
        self.cb("Assembling final video…", 84)
        video_path = job_dir / "video.mp4"
        width = config.SHORT_WIDTH if is_portrait else config.VIDEO_WIDTH
        height = config.SHORT_HEIGHT if is_portrait else config.VIDEO_HEIGHT

        try:
            sections_for_assembly = [
                {
                    "title": s.label,
                    "duration": s.duration_seconds,
                    "narration": s.narration,
                }
                for s in script.sections
            ]
            video_generator.create_video(
                audio_path=audio_path,
                output_path=video_path,
                video_clips=all_video_clips,
                image_clips=list(image_clips),
                thumbnail_path=thumbnail_path,
                width=width,
                height=height,
                sections=sections_for_assembly,
                narration_text=script.narration_full,
            )
        except Exception as e:
            errors.append(f"Video assembly failed: {e}")

        # ── Save manifest ─────────────────────────────────────────────────────
        self.cb("Saving manifest…", 94)
        manifest = {
            "niche": niche,
            "title": seo.title_final,
            "description": seo.description_full,
            "tags": seo.tags,
            "blueprint": blueprint.model_dump(),
            "asset_plan": asset_plan.model_dump(),
            "seo": seo.model_dump(),
            "files": {
                "video": str(video_path),
                "audio": str(audio_path),
                "thumbnail": str(thumbnail_path),
            },
            "errors": errors,
        }
        file_manager.save_manifest(job_dir, manifest)

        result = ProductionResult(
            niche=niche,
            blueprint=blueprint,
            script=script,
            asset_plan=asset_plan,
            seo=seo,
            pipeline_cost_credits=asset_plan.total_credit_cost,
            status="success" if not errors else "partial",
            errors=errors,
        )

        self.cb("Production complete!", 100)
        return result


# ── Blank fallback constructors ──────────────────────────────────────────────

def _blank_blueprint(niche: str) -> dict:
    return {
        "title": niche, "hook": "", "core_angle": "", "target_audience": "general",
        "content_type": "educational", "tone": "conversational",
        "estimated_ctr": 0.04, "trend_score": 5.0, "keywords": [niche],
        "thumbnail_concept": "", "rationale": "",
    }


def _blank_script(title: str) -> dict:
    return {
        "title": title, "description": "", "hashtags": [], "sections": [],
        "total_duration_seconds": 0, "narration_full": "",
        "thumbnail_prompt": "", "chapter_timestamps": [],
    }


def _blank_asset_plan() -> OptimizedAssetPlan:
    return OptimizedAssetPlan(
        assets=[], total_credit_cost=0, budget_state="healthy",
        credits_remaining_after=0, swaps_made=[], quality_impact="N/A",
    )


def _blank_seo(title: str) -> dict:
    return {
        "title_final": title, "description_full": "", "tags": [],
        "thumbnail_text": "", "end_screen_cta": "Subscribe for more!",
        "pinned_comment": "", "upload_timing": "Tuesday 14:00 UTC",
        "predicted_views_30d": 0, "ab_title_variants": [title],
    }
