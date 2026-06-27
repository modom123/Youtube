"""
HollywoodEngine — Premium mixed-media cinematic production pipeline.

Combines Higgsfield AI generation (atmospheric/cinematic shots) with
Pixabay/Mixkit real sports footage for documentary-grade World Cup,
history, and sports videos. No longer AI-only — uses the best source
for each type of shot.
"""
from __future__ import annotations
import json
import threading as _threading
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
- b_roll_keywords: use SPECIFIC SEARCHABLE TERMS like "world cup trophy", "soccer stadium crowd",
  "football celebration", "penalty kick stadium" — not generic words

## Guardrails
- Never pad — if the story is told, end the scene
- No "like and subscribe" in narration — if there's a CTA, it's in a brief OUTRO scene
- The hook must be the most compelling visual scene in the film"""


class HollywoodAssetCurator(AssetCurator):
    """
    Mixed-media Hollywood curator.
    Uses Higgsfield AI for cinematic/atmospheric shots.
    Uses Pixabay for real sports footage and historical-looking scenes.
    Picks the best source for each type of shot.
    """
    name = "Hollywood Asset Curator"
    max_tokens = 4096
    system_prompt = """You are the Hollywood Asset Curator — a visual effects supervisor for premium documentary films. Your standard is theatrical release quality.

Your persona: Smart strategist. You know WHICH tool to use for WHICH shot. Not everything needs to be AI-generated — real sports footage is more powerful for documentary subjects.

## SOURCE SELECTION RULES

### Use source=higgsfield_cinematic for:
- Dramatic atmospheric shots (trophy reveal, golden light, epic stadium at night)
- Abstract/symbolic visuals (spinning ball, stadium silhouette at sunset)
- Emotional transition shots (slow-motion crowd reaction, confetti falling)
- Any shot requiring precise cinematic control (specific lighting, era look)
- Model: cinematic_studio_3_0 (8 credits) for dramatic, atmospheric
- Model: kling3_0 (10 credits) for action shots with precise motion

### Use source=free_pixabay_api for:
- Real sports footage (actual soccer/football games, real stadium content)
- Player action shots (goal celebrations, team formations)
- Historical documentary-style content (use era-specific keywords)
- Crowd scenes with authentic energy
- Golden Boot trophy shots, FIFA World Cup venue visuals
- PROMPT = Pixabay search query (keep under 5 words, specific): "soccer world cup final", "football goal celebration", "stadium night match", "golden trophy soccer"

## DOCUMENTARY APPROACH (for sports/history topics)
For each scene, ask: "Is this shot more powerful as REAL footage or CINEMATIC AI?"
- Real match action → free_pixabay_api
- Trophy/award reveal → higgsfield_cinematic (more dramatic control)
- Player celebration → free_pixabay_api
- Epic establishing shot of stadium → higgsfield_cinematic
- Fan reaction → free_pixabay_api
- Historical era atmosphere → higgsfield_cinematic (can style to specific decade)

## HIGGSFIELD PROMPT STANDARDS (when using AI generation)
Each prompt MUST describe (minimum 15 words):
- Camera: angle + distance + movement
- Lighting: specific mood (golden hour / stadium floodlights / vintage film look)
- Era styling: "1970s film grain", "80s VHS look", "modern 4K"
- Subject: specific and evocative (never generic)

## ERA-SPECIFIC EXAMPLES FOR WORLD CUP
- 1958/1970: "Wide shot of football match in sunlit stadium, vintage 1970s Super 8 film grain, yellow-green color grade, euphoric crowd, warm nostalgic atmosphere"
- 1986: "Low-angle tracking shot of lone footballer with ball in dusty stadium, golden afternoon light, 1980s VHS texture, cinematic and legendary"
- 2002/2006: "Night match in modern stadium, electric blue floodlights, crowd holding scarves and flags, dynamic energy, documentary style"
- 2022 Qatar: "Ultra-modern stadium at night, architectural lighting, global flags, 4K crisp, futuristic World Cup atmosphere"
- Trophy: "FIFA World Cup trophy gleaming under spotlight, rotating slowly, golden light, black background, cinematic product shot, 4K"
- Golden Boot: "Close-up of golden football boot award on pedestal, dramatic side lighting, shallow depth of field, trophy texture detail"

## CREDIT COSTS
- cinematic_studio_3_0: 8 credits per clip
- kling3_0: 10 credits per clip
- free_pixabay_api: 0 credits

## BUDGET STRATEGY
Mix ~50% Higgsfield (cinematic key shots) + ~50% Pixabay (real sports content).
This delivers maximum impact: cinematic quality where it matters, authentic footage where it's more powerful."""


# ── Hollywood Engine ──────────────────────────────────────────────────────────

class HollywoodEngine:
    """
    Premium mixed-media cinematic production pipeline.
    Combines Higgsfield AI generation with real sports stock footage.
    """

    def __init__(self, progress_callback: ProgressCallback = _noop):
        self.cb = progress_callback
        self.cinematic_director = CinematicDirector()
        self.screenwriter = ScreenwriterAgent()
        self.visual_producer = HollywoodAssetCurator()
        self.growth_engineer = GrowthEngineer()

    def _with_heartbeat(self, msg: str, base_pct: int, fn):
        """Run fn() while sending heartbeat progress events every 5 seconds."""
        result = [None]
        exc = [None]
        done = _threading.Event()

        def worker():
            try:
                result[0] = fn()
            except Exception as e:
                exc[0] = e
            finally:
                done.set()

        t = _threading.Thread(target=worker, daemon=True)
        t.start()
        elapsed = 0
        while not done.wait(timeout=5):
            elapsed += 5
            self.cb(f"{msg} ({elapsed}s)…", base_pct)
        if exc[0]:
            raise exc[0]
        return result[0]

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
        Full Hollywood pipeline: topic → cinematic agents → mixed Higgsfield+stock assets → video.
        """
        from generators import audio_generator, video_generator, media_fetcher, thumbnail_generator
        from generators.researcher import research_topic, brief_to_context
        from generators import higgsfield_mcp
        from utils import file_manager

        # Voice selection — ElevenLabs > Google Neural2 > edge-tts
        # (audio_generator auto-picks based on which API keys are configured)
        if not voice:
            if config.GOOGLE_API_KEY:
                voice = config.GOOGLE_TTS_VOICE
            else:
                voice = "en-US-GuyNeural"

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
        self.cb("Story Development — CinematicDirector thinking", 12)
        try:
            blueprint = self._with_heartbeat(
                "Story Development — CinematicDirector thinking", 12,
                lambda: self.cinematic_director.run(
                    niche=topic,
                    research_context=research_context,
                    competitor_titles=competitor_titles or [],
                )
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
        self.cb("Screenplay Writing — ScreenwriterAgent crafting scenes", 25)
        try:
            script = self._with_heartbeat(
                "Screenplay Writing — ScreenwriterAgent crafting scenes", 25,
                lambda: self.screenwriter.run(
                    blueprint=blueprint,
                    target_duration=target_duration,
                    audience=audience,
                )
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

        # ── HollywoodAssetCurator → AssetPlan (mixed Higgsfield + Pixabay) ──
        self.cb("Visual Planning — HollywoodAssetCurator designing shot list", 38)
        raw_asset_plan: AssetPlan | None = None
        try:
            raw_asset_plan = self._with_heartbeat(
                "Visual Planning — HollywoodAssetCurator designing shot list", 38,
                lambda: self.visual_producer.run(
                    script=script,
                    blueprint=blueprint,
                    is_portrait=is_portrait,
                )
            )
            (job_dir / "asset_plan_raw.json").write_text(raw_asset_plan.model_dump_json(indent=2))
        except Exception as e:
            errors.append(f"HollywoodAssetCurator failed: {e}")
            raw_asset_plan = AssetPlan(
                assets=[], total_credit_estimate=0,
                free_asset_count=0, paid_asset_count=0, notes="failed",
            )

        # Build mixed asset plan — respect the curator's source decisions
        aspect = "9:16" if is_portrait else "16:9"
        planned_assets = list(raw_asset_plan.assets) if raw_asset_plan.assets else []

        # If no assets were planned, auto-generate a mixed plan from script sections
        if not planned_assets and script.sections:
            for i, section in enumerate(script.sections[:8]):
                visual_dir = section.visual_direction or section.label
                # Alternate: even sections get Pixabay sports, odd get Higgsfield cinematic
                if i % 2 == 0 and section.b_roll_keywords:
                    # Use Pixabay for real-looking shots
                    planned_assets.append(AssetSpec(
                        section_id=section.section_id,
                        asset_type="video_clip",
                        source="free_pixabay_api",
                        prompt=" ".join(section.b_roll_keywords[:3]),
                        model_key=None,
                        duration_seconds=section.duration_seconds,
                        aspect_ratio=aspect,
                        credit_cost=0,
                        priority=1,
                    ))
                else:
                    # Use Higgsfield for dramatic cinematic shots
                    planned_assets.append(AssetSpec(
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

        total_credits = sum(a.credit_cost for a in planned_assets if a.source.startswith("higgsfield_"))
        asset_plan = OptimizedAssetPlan(
            assets=planned_assets,
            total_credit_cost=total_credits,
            budget_state="healthy",
            credits_remaining_after=max(0, 9999 - total_credits),
            swaps_made=[],
            quality_impact="Mixed: Higgsfield AI cinematics + real sports stock footage",
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

        # ── Fetch/generate assets: Pixabay stock + Higgsfield AI ─────────────
        stock_dir = job_dir / "stock"
        ai_clips_dir = job_dir / "ai_clips"
        stock_dir.mkdir(parents=True, exist_ok=True)
        ai_clips_dir.mkdir(parents=True, exist_ok=True)

        all_video_clips: list[Path] = []
        all_image_clips: list[Path] = []
        ai_clips_generated = 0

        pixabay_assets = [a for a in asset_plan.assets if a.source == "free_pixabay_api"]
        higgsfield_assets = [a for a in asset_plan.assets if a.source.startswith("higgsfield_")]

        # ── Step A: Fetch Pixabay/Mixkit stock for real sports footage ────────
        if pixabay_assets:
            self.cb(f"Sourcing real sports footage — {len(pixabay_assets)} clips…", 60)
            for pa in pixabay_assets:
                query = pa.prompt.strip()
                if not query:
                    continue
                try:
                    clips, imgs = media_fetcher.fetch_media_for_topic(
                        keywords=[query],
                        output_dir=stock_dir,
                        video_count=2,
                        is_portrait=is_portrait,
                    )
                    all_video_clips.extend(clips)
                    all_image_clips.extend(imgs)
                except Exception as e:
                    errors.append(f"Stock fetch failed for '{query}': {e}")

        # Always add Mixkit sports clips as guaranteed base layer for sports topics
        topic_lower = topic.lower()
        is_sports_topic = any(w in topic_lower for w in [
            "world cup", "soccer", "football", "champion", "player", "stadium",
            "sport", "game", "league", "fifa", "nfl", "nba", "olympic",
        ])
        if is_sports_topic:
            try:
                self.cb("Loading sports footage library…", 63)
                mixkit_clips = media_fetcher._mixkit_fetch_videos(
                    ["sports", "soccer", "football"], count=4, output_dir=stock_dir
                )
                all_video_clips.extend(mixkit_clips)
            except Exception as e:
                errors.append(f"Mixkit sports fetch failed: {e}")

        # ── Step B: Generate Higgsfield AI clips for cinematic shots ──────────
        try:
            _hf_token = higgsfield_mcp._token()
        except RuntimeError:
            _hf_token = ""
        if higgsfield_assets and _hf_token:
            clips_to_generate = higgsfield_assets[:6]
            self.cb(f"AI Cinematography — generating {len(clips_to_generate)} Higgsfield cinematic clips…", 68)
            try:
                prompts = [a.prompt for a in clips_to_generate]
                model_id = clips_to_generate[0].model_key or "cinematic_studio_3_0"
                ai_clips = higgsfield_mcp.generate_clips_via_mcp(
                    prompts=prompts,
                    output_dir=ai_clips_dir,
                    model_id=model_id,
                    aspect_ratio=aspect,
                )
                all_video_clips.extend(ai_clips)
                ai_clips_generated = len(ai_clips)
            except Exception as e:
                errors.append(f"Higgsfield clip generation failed: {e}")

        elif higgsfield_assets and not _hf_token:
            # No Higgsfield token — use Pixabay for the higgsfield-planned shots too
            self.cb("Higgsfield not connected — using expanded stock footage…", 68)
            for ha in higgsfield_assets[:4]:
                query_words = ha.b_roll_keywords[:3] if hasattr(ha, 'b_roll_keywords') and ha.b_roll_keywords else []
                if not query_words:
                    # Extract searchable terms from the cinematic prompt
                    import re
                    words = re.findall(r'\b(?:soccer|football|stadium|crowd|trophy|goal|player|match|sport)\b',
                                       ha.prompt, re.I)
                    query_words = words[:3] or ["soccer"]
                try:
                    clips, imgs = media_fetcher.fetch_media_for_topic(
                        keywords=query_words,
                        output_dir=stock_dir,
                        video_count=1,
                        is_portrait=is_portrait,
                    )
                    all_video_clips.extend(clips)
                    all_image_clips.extend(imgs)
                except Exception:
                    pass

        # Final stock fallback
        if not all_video_clips and not all_image_clips:
            try:
                fallback_kw = script.sections[0].b_roll_keywords[:2] if script.sections else [topic]
                clips, imgs = media_fetcher.fetch_media_for_topic(
                    keywords=fallback_kw,
                    output_dir=stock_dir,
                    video_count=3,
                    is_portrait=is_portrait,
                )
                all_video_clips.extend(clips)
                all_image_clips.extend(imgs)
            except Exception as e:
                errors.append(f"Stock fallback failed: {e}")

        # ── AI scene images: generate one per script section via Higgsfield ─
        # This runs whenever we need more visuals, guaranteeing real images in the video.
        if _hf_token and len(all_image_clips) < 3:
            self.cb("AI Scene Images — generating visuals for each scene…", 74)
            ai_img_dir = job_dir / "ai_images"
            ai_img_dir.mkdir(parents=True, exist_ok=True)
            for i, section in enumerate(script.sections[:8]):
                try:
                    img_prompt = (
                        getattr(section, "visual_direction", None)
                        or (section.b_roll_keywords[0] if getattr(section, "b_roll_keywords", None) else None)
                        or f"Cinematic scene: {getattr(section, 'label', topic)}"
                    )
                    if len(img_prompt) < 20:
                        img_prompt = f"Cinematic {topic} scene: {img_prompt}, photorealistic, 4K"
                    img_path = ai_img_dir / f"scene_{i:02d}.jpg"
                    result = higgsfield_mcp.generate_image_via_mcp(
                        prompt=img_prompt[:400],
                        output_path=img_path,
                        model_id="nano_banana_pro",
                        aspect_ratio=aspect,
                    )
                    if result and result.exists():
                        all_image_clips.append(result)
                        self.cb(f"Scene {i+1} image ready", 74 + i)
                except Exception as e:
                    errors.append(f"AI scene image {i} failed: {e}")

        # ── AI Thumbnail via Higgsfield ───────────────────────────────────────
        self.cb("AI Thumbnail — generating cinematic thumbnail…", 80)
        thumbnail_path = job_dir / "thumbnail.jpg"
        ai_thumbnail_used = False

        if _hf_token and script.thumbnail_prompt:
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
            bg_image = all_image_clips[0] if all_image_clips else None
            try:
                thumbnail_generator.generate_thumbnail(
                    title=seo.thumbnail_text or blueprint.title,
                    output_path=thumbnail_path,
                    background_image_path=bg_image,
                    style=thumbnail_style,
                    width=1280,
                    height=720,
                )
            except Exception as e:
                errors.append(f"Fallback thumbnail failed: {e}")

        # ── Assemble final video ──────────────────────────────────────────────
        self.cb("Final Cut — assembling Hollywood film…", 87)
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
                image_clips=all_image_clips,
                thumbnail_path=thumbnail_path,
                width=width,
                height=height,
                sections=sections_for_assembly,
                narration_text=script.narration_full,
            )
        except Exception as e:
            errors.append(f"Video assembly failed: {e}")

        # ── Save manifest ─────────────────────────────────────────────────────
        self.cb("Saving manifest…", 96)
        manifest = {
            "niche": topic,
            "mode": "hollywood",
            "title": seo.title_final,
            "description": seo.description_full,
            "tags": seo.tags,
            "blueprint": blueprint.model_dump(),
            "asset_plan": asset_plan.model_dump(),
            "seo": seo.model_dump(),
            "ai_clips_generated": ai_clips_generated,
            "stock_clips_used": len(all_video_clips) - ai_clips_generated,
            "ai_thumbnail_used": ai_thumbnail_used,
            "files": {
                "video": str(video_path),
                "audio": str(audio_path),
                "thumbnail": str(thumbnail_path),
            },
            "errors": errors,
        }
        from utils import file_manager
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
