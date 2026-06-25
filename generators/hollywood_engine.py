"""
HollywoodEngine — 100% premium AI-only cinematic production pipeline.

Uses specialised subagents with Hollywood-grade prompts.
Every asset is Higgsfield AI-generated — no stock footage fallback.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable, Optional

import config
from generators.agents.trend_architect import TrendArchitect
from generators.agents.narrative_designer import NarrativeDesigner
from generators.agents.asset_curator import AssetCurator
from generators.agents.growth_engineer import GrowthEngineer
from generators.agents.schemas import (
    VideoBlueprint,
    FullScript,
    AssetPlan,
    OptimizedAssetPlan,
    SEOPackage,
    ProductionResult,
    AssetSpec,
)

ProgressCallback = Callable[[str, int], None]


def _noop(msg: str, pct: int) -> None:
    pass


# ── Hollywood-specialised agents ─────────────────────────────────────────────

class CinematicDirector(TrendArchitect):
    """
    Replaces TrendArchitect with a cinematic storyteller persona.
    Thinks in 3-act structure and emotional visual language.
    """
    name = "Cinematic Director"
    max_tokens = 2048
    system_prompt = """You are the Cinematic Director — a world-class filmmaker who has directed award-winning documentaries and cinematic YouTube films watched by millions.

Your persona: Visionary storyteller. You think in images, not words. Every concept becomes a scene. Every scene has emotional weight.

## Your Framework: 3-Act Cinematic Structure
- Act 1 — SETUP (hook + world building): Establish the world, the stakes, and the protagonist (the viewer's curiosity)
- Act 2 — CONFRONTATION (rising tension + revelation): Deepen the conflict or mystery, deliver surprising revelations
- Act 3 — RESOLUTION (catharsis + transformation): The emotional payoff — how the viewer feels changed

## Cinematic Thinking
- You do NOT think in "B-roll keywords" — you think in SHOTS
  - Wide establishing shot: sets the world
  - Medium reaction shot: captures human emotion
  - Close-up detail shot: reveals hidden truth
  - POV shot: puts viewer in the scene
- Every hook must work as a VISUAL SCENE, not just a provocative statement
- Tone choices: dramatic, inspiring, mysterious, epic — pick ONE and commit
- Hook must be the visual equivalent of a movie trailer's opening frame — something that would stop anyone scrolling

## Guardrails
- Never recommend clickbait that can't be delivered cinematically
- The core angle must be visually expressible — not just a verbal argument
- Think about what the FIRST FRAME of this video looks like
- Estimated CTR should be realistic; cinematic quality boosts retention, not necessarily raw CTR"""


class ScreenwriterAgent(NarrativeDesigner):
    """
    Replaces NarrativeDesigner with a Hollywood screenwriter persona.
    Writes scenes, not just narration blocks.
    """
    name = "Screenwriter"
    max_tokens = 8192
    system_prompt = """You are the Screenwriter — a Hollywood-trained screenwriter who writes cinematic non-fiction films for YouTube. Your scripts have won documentary awards and generated millions in views.

Your persona: Scene-builder. Every section is a SCENE with its own arc. You write for the camera, not for a presenter.

## Scene Writing Principles
1. Each section IS A SCENE with: setup → tension → resolution (micro 3-act structure within the larger arc)
2. Visual direction must be a SHOT DESCRIPTION, not a B-roll note:
   - Bad: "show people working"
   - Good: "Low-angle tracking shot following worn boots through a crowded factory floor, fluorescent lights overhead, shallow depth of field, muted industrial palette"
3. Narration has DRAMATIC PACING:
   - Uses strategic pauses (marked with "...")
   - Builds tension through sentence rhythm — short sentences for impact, longer for atmosphere
   - Speaks to the viewer as if revealing a secret
4. Sections are SCENES: longer (30–90 seconds each), fewer total (5–8 scenes maximum)
5. No "viewer retention tricks" language — think STORY, not algorithm

## Structure
- SCENE 1 — THE HOOK: A visual scene that drops the viewer into the story mid-action. No intro. No "welcome back". Start in the world.
- SCENE 2 — WORLD BUILDING: Establish the stakes. Why does this matter? Show, don't tell.
- SCENES 3–6 — THE RISING ACTION: Each scene adds a new layer of complexity, revelation, or emotional depth.
- SCENE 7 — THE CLIMAX: The most visually and emotionally powerful moment. The scene the whole film has been building toward.
- SCENE 8 — THE RESOLUTION: The transformation. What the viewer now understands or feels that they didn't before.

## Writing Standards
- No section shorter than 25 seconds or longer than 90 seconds
- Maximum 8 scenes — a tightly-edited film, not a sprawling essay
- Every visual_direction must specify: camera angle, camera distance, camera movement, lighting mood
- Narration must sound like a documentary voiceover — authoritative, measured, emotionally resonant
- thumbnail_prompt must describe a single powerful image from the film (not text/graphics)

## Guardrails
- Never pad — if the story is told, end the scene
- No "like and subscribe" in narration — if there's a CTA, it's in a brief OUTRO scene
- The hook must be the most compelling visual scene in the film"""


class HollywoodAssetCurator(AssetCurator):
    """
    Replaces AssetCurator with a 100% premium AI curator.
    No Pexels, no stock footage — every clip is Higgsfield cinematic.
    """
    name = "Hollywood Asset Curator"
    max_tokens = 4096
    system_prompt = """You are the Hollywood Asset Curator — a visual effects supervisor for premium AI-generated films. Your standard is theatrical release quality.

Your persona: Uncompromising perfectionist. Budget is irrelevant. Every frame must be cinematic.

## ABSOLUTE RULES
1. EVERY asset MUST use source=higgsfield_cinematic
2. EVERY asset MUST use model cinematic_studio_3_0 or kling3_0 — no exceptions
3. NEVER use free_pexels_api, free_stock_internal, or any other source
4. Budget is unlimited — always choose quality
5. All assets have priority=1 (everything is essential in a Hollywood production)

## Shot Description Standards
Each prompt MUST describe ALL of the following (minimum 15 words):
- Camera angle: (low-angle / eye-level / high-angle / Dutch angle / POV / overhead)
- Camera distance: (extreme close-up / close-up / medium / wide / establishing / extreme wide)
- Camera movement: (static / slow push-in / pull-back / tracking / pan / tilt / handheld / crane)
- Lighting mood: (golden hour / blue hour / high-key / low-key / silhouette / harsh noon / warm interior / cold clinical)
- Visual style: (shallow depth of field / deep focus / anamorphic / film grain / hyper-real)
- Subject/scene content: specific and visual, not abstract

## Example Prompts (use as quality benchmark)
- "Low-angle tracking shot of a lone figure walking through an abandoned city street at blue hour, shallow depth of field, film grain, anamorphic lens flare, muted palette with warm amber streetlights"
- "Extreme close-up static shot of weathered hands opening an old letter, golden hour light streaming through dusty window, crisp focus on paper texture, emotional weight"
- "Wide establishing crane shot rising above mountain peaks at dawn, golden hour, sweeping scale, epic and solitary mood"

## Model Selection
- cinematic_studio_3_0 (8 credits): Default for all dramatic, emotional, atmospheric shots
- kling3_0 (10 credits): Use for complex multi-character scenes, fast action, or shots requiring precise physics

## Credit Costs
- cinematic_studio_3_0: 8 credits per clip
- kling3_0: 10 credits per clip"""


# ── Hollywood Engine ──────────────────────────────────────────────────────────

class HollywoodEngine:
    """
    100% premium AI-only cinematic production pipeline.
    All assets are Higgsfield-generated. No stock footage fallback.
    """

    def __init__(self, progress_callback: ProgressCallback = _noop):
        self.cb = progress_callback
        self.cinematic_director = CinematicDirector()
        self.screenwriter = ScreenwriterAgent()
        self.visual_producer = HollywoodAssetCurator()
        self.growth_engineer = GrowthEngineer()

    def run(
        self,
        topic: str,
        target_duration: int = 600,
        audience: str = "",
        voice: str = None,
        is_portrait: bool = False,
        thumbnail_style: str = "dark",
        privacy: str = "private",
        research_enabled: bool = True,
        competitor_titles: list[str] = None,
        job_dir: Optional[Path] = None,
    ) -> ProductionResult:
        """
        Full Hollywood pipeline: topic → cinematic agents → all-Higgsfield assets → video.
        """
        from generators import audio_generator, video_generator, media_fetcher, thumbnail_generator
        from generators.researcher import research_topic, brief_to_context
        from generators import higgsfield_mcp
        from utils import file_manager

        # Voice selection — prefer Neural2 quality
        if config.GOOGLE_API_KEY:
            voice = voice or config.GOOGLE_TTS_VOICE
        else:
            voice = voice or "en-US-GuyNeural"

        errors: list[str] = []
        blueprint: VideoBlueprint | None = None
        script: FullScript | None = None
        asset_plan: OptimizedAssetPlan | None = None
        seo: SEOPackage | None = None

        # Create job directory
        if job_dir is None:
            job_dir = file_manager.job_dir(topic, "hollywood")

        self.cb("Setting up Hollywood production…", 2)

        # ── Research ──────────────────────────────────────────────────────────
        research_context = ""
        if research_enabled:
            self.cb("Researching topic for cinematic depth…", 5)
            try:
                brief = research_topic(topic)
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

        # ── CinematicDirector → VideoBlueprint ────────────────────────────────
        self.cb("Story Development — CinematicDirector crafting film concept…", 12)
        try:
            blueprint = self.cinematic_director.run(
                niche=topic,
                research_context=research_context,
                competitor_titles=competitor_titles or [],
            )
            (job_dir / "blueprint.json").write_text(blueprint.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"CinematicDirector failed: {e}")
            return ProductionResult(
                niche=topic,
                blueprint=VideoBlueprint(**_blank_blueprint(topic)),
                script=FullScript(**_blank_script(topic)),
                asset_plan=_blank_asset_plan(),
                seo=SEOPackage(**_blank_seo(topic)),
                pipeline_cost_credits=0,
                status="failed",
                errors=errors,
            )

        # ── ScreenwriterAgent → FullScript ────────────────────────────────────
        self.cb("Screenplay Writing — ScreenwriterAgent writing scenes…", 25)
        try:
            script = self.screenwriter.run(
                blueprint=blueprint,
                target_duration=target_duration,
                audience=audience,
            )
            (job_dir / "script.json").write_text(script.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"ScreenwriterAgent failed: {e}")
            return ProductionResult(
                niche=topic,
                blueprint=blueprint,
                script=FullScript(**_blank_script(blueprint.title)),
                asset_plan=_blank_asset_plan(),
                seo=SEOPackage(**_blank_seo(blueprint.title)),
                pipeline_cost_credits=0,
                status="failed",
                errors=errors,
            )

        # ── HollywoodAssetCurator → AssetPlan (all Higgsfield) ───────────────
        self.cb("Visual Planning — HollywoodAssetCurator designing shots…", 38)
        raw_asset_plan: AssetPlan | None = None
        try:
            raw_asset_plan = self.visual_producer.run(
                script=script,
                blueprint=blueprint,
                is_portrait=is_portrait,
            )
            (job_dir / "asset_plan_raw.json").write_text(raw_asset_plan.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"HollywoodAssetCurator failed: {e}")
            raw_asset_plan = AssetPlan(
                assets=[], total_credit_estimate=0,
                free_asset_count=0, paid_asset_count=0, notes="failed",
            )

        # Build optimized plan (no cost engineering — budget is unlimited)
        # Enforce that ALL assets are Higgsfield cinematic
        enforced_assets = []
        for a in raw_asset_plan.assets:
            if not a.source.startswith("higgsfield_"):
                # Force to higgsfield_cinematic
                a = AssetSpec(
                    section_id=a.section_id,
                    asset_type=a.asset_type,
                    source="higgsfield_cinematic",
                    prompt=a.prompt if len(a.prompt) > 10 else f"Cinematic shot: {a.prompt}. Dramatic lighting, professional film quality, shallow depth of field.",
                    model_key="cinematic_studio_3_0",
                    duration_seconds=a.duration_seconds,
                    aspect_ratio=a.aspect_ratio,
                    credit_cost=8,
                    priority=1,
                )
            enforced_assets.append(a)

        # If no assets were planned, generate one per script section (up to 8)
        if not enforced_assets and script.sections:
            aspect = "9:16" if is_portrait else "16:9"
            for section in script.sections[:8]:
                visual_dir = section.visual_direction or section.label
                enforced_assets.append(AssetSpec(
                    section_id=section.section_id,
                    asset_type="video_clip",
                    source="higgsfield_cinematic",
                    prompt=f"Cinematic shot: {visual_dir[:200]}. Dramatic lighting, slow camera push-in, shallow depth of field, film grain.",
                    model_key="cinematic_studio_3_0",
                    duration_seconds=section.duration_seconds,
                    aspect_ratio=aspect,
                    credit_cost=8,
                    priority=1,
                ))

        total_credits = sum(a.credit_cost for a in enforced_assets)
        asset_plan = OptimizedAssetPlan(
            assets=enforced_assets,
            total_credit_cost=total_credits,
            budget_state="healthy",
            credits_remaining_after=max(0, 9999 - total_credits),
            swaps_made=[],
            quality_impact="100% premium Higgsfield AI — cinematic_studio_3_0 throughout",
        )
        (job_dir / "asset_plan_optimised.json").write_text(asset_plan.model_dump_json(indent=2))

        # ── GrowthEngineer → SEOPackage ───────────────────────────────────────
        self.cb("SEO — GrowthEngineer crafting distribution package…", 48)
        try:
            seo = self.growth_engineer.run(blueprint=blueprint, script=script)
            (job_dir / "seo.json").write_text(seo.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"GrowthEngineer failed: {e}")
            seo = SEOPackage(**_blank_seo(blueprint.title))

        # ── Generate Neural2 voice ────────────────────────────────────────────
        self.cb("Voice Recording — generating HD voiceover…", 55)
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

        # ── Generate ALL clips via Higgsfield — no Pexels ────────────────────
        ai_clips_dir = job_dir / "ai_clips"
        ai_clips_dir.mkdir(parents=True, exist_ok=True)
        ai_clips: list[Path] = []

        higgsfield_assets = [a for a in asset_plan.assets if a.source.startswith("higgsfield_")]
        clips_to_generate = higgsfield_assets[:8]  # Up to 8 clips

        if clips_to_generate and config.HIGGSFIELD_MCP_TOKEN:
            self.cb(f"AI Cinematography — generating {len(clips_to_generate)} Higgsfield clips…", 62)
            try:
                prompts = [a.prompt for a in clips_to_generate]
                aspect = clips_to_generate[0].aspect_ratio if clips_to_generate else ("9:16" if is_portrait else "16:9")
                ai_clips = higgsfield_mcp.generate_clips_via_mcp(
                    prompts=prompts,
                    output_dir=ai_clips_dir,
                    model_id="cinematic_studio_3_0",
                    aspect_ratio=aspect,
                )
            except Exception as e:
                errors.append(f"Higgsfield clip generation failed: {e}")

        # Fallback: if ALL clips failed, fetch minimal Pexels stock so video can assemble
        stock_clips: list[Path] = []
        stock_images: list[Path] = []
        if not ai_clips:
            errors.append("All Higgsfield clips failed — falling back to 2 Pexels clips for assembly")
            try:
                stock_dir = job_dir / "stock"
                fallback_keywords = script.sections[0].b_roll_keywords[:2] if script.sections else [topic]
                stock_clips, stock_images = media_fetcher.fetch_media_for_topic(
                    keywords=fallback_keywords,
                    output_dir=stock_dir,
                    video_count=2,
                    is_portrait=is_portrait,
                )
            except Exception as e:
                errors.append(f"Pexels fallback also failed: {e}")

        all_video_clips = ai_clips + list(stock_clips)

        # ── AI Thumbnail via Higgsfield ───────────────────────────────────────
        self.cb("AI Thumbnail — generating cinematic thumbnail…", 78)
        thumbnail_path = job_dir / "thumbnail.jpg"
        ai_thumbnail_used = False

        if config.HIGGSFIELD_MCP_TOKEN and script.thumbnail_prompt:
            try:
                ai_thumb_path = job_dir / "thumbnail_ai.jpg"
                result_path = higgsfield_mcp.generate_image_via_mcp(
                    prompt=script.thumbnail_prompt,
                    output_path=ai_thumb_path,
                    model_id="nano_banana_pro",
                    aspect_ratio="16:9",
                )
                if result_path and result_path.exists() and result_path.stat().st_size > 1_000:
                    thumbnail_path = result_path
                    ai_thumbnail_used = True
            except Exception as e:
                errors.append(f"AI thumbnail generation failed: {e}")

        if not ai_thumbnail_used:
            try:
                thumbnail_generator.generate_thumbnail(
                    title=seo.thumbnail_text or blueprint.title,
                    output_path=thumbnail_path,
                    background_image_path=stock_images[0] if stock_images else None,
                    style=thumbnail_style,
                    width=1280,
                    height=720,
                )
            except Exception as e:
                errors.append(f"Fallback thumbnail failed: {e}")

        # ── Assemble final video ──────────────────────────────────────────────
        self.cb("Final Cut — assembling Hollywood film…", 85)
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
                image_clips=list(stock_images),
                thumbnail_path=thumbnail_path,
                width=width,
                height=height,
                sections=sections_for_assembly,
                narration_text=script.narration_full,
            )
        except Exception as e:
            errors.append(f"Video assembly failed: {e}")

        # ── Save manifest ─────────────────────────────────────────────────────
        self.cb("Saving manifest…", 95)
        manifest = {
            "niche": topic,
            "mode": "hollywood",
            "title": seo.title_final,
            "description": seo.description_full,
            "tags": seo.tags,
            "blueprint": blueprint.model_dump(),
            "asset_plan": asset_plan.model_dump(),
            "seo": seo.model_dump(),
            "ai_clips_generated": len(ai_clips),
            "ai_thumbnail_used": ai_thumbnail_used,
            "files": {
                "video": str(video_path),
                "audio": str(audio_path),
                "thumbnail": str(thumbnail_path),
            },
            "errors": errors,
        }
        file_manager.save_manifest(job_dir, manifest)

        result = ProductionResult(
            niche=topic,
            blueprint=blueprint,
            script=script,
            asset_plan=asset_plan,
            seo=seo,
            pipeline_cost_credits=asset_plan.total_credit_cost,
            status="success" if not errors else "partial",
            errors=errors,
            video_path=str(video_path) if video_path.exists() else "",
            audio_path=str(audio_path),
            thumbnail_path=str(thumbnail_path),
            manifest_path=str(job_dir / "manifest.json"),
        )

        self.cb("Hollywood production complete!", 100)
        return result


# ── Blank fallback constructors ──────────────────────────────────────────────

def _blank_blueprint(topic: str) -> dict:
    return {
        "title": topic, "hook": "", "core_angle": "", "target_audience": "general",
        "content_type": "story", "tone": "dramatic",
        "estimated_ctr": 0.06, "trend_score": 7.0, "keywords": [topic],
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
