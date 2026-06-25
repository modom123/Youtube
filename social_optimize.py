"""
Social Optimize - Core Orchestrator
Turns any topic into a complete multi-platform content package.
"""
import json
import concurrent.futures
from datetime import datetime
import config
from generators import script_generator, audio_generator, video_generator, media_fetcher, thumbnail_generator
from generators.researcher import research_topic, brief_to_context
from generators import graphics_generator
from generators import ai_video_generator
from publishers import (
    youtube_publisher, tiktok_publisher, facebook_publisher, twitter_publisher, linkedin_publisher,
    pinterest_publisher, threads_publisher,
)
from utils import file_manager, logger


CONTENT_PROFILES = {
    "short": {
        "label": "Short / Reel / TikTok",
        "duration": 55,
        "width": config.SHORT_WIDTH,
        "height": config.SHORT_HEIGHT,
        "is_portrait": True,
        "is_short": True,
        "content_type": "short",
    },
    "long": {
        "label": "Long-form YouTube Video",
        "duration": 480,
        "width": config.VIDEO_WIDTH,
        "height": config.VIDEO_HEIGHT,
        "is_portrait": False,
        "is_short": False,
        "content_type": "long",
    },
    "podcast": {
        "label": "Podcast Episode",
        "duration": 600,
        "width": config.VIDEO_WIDTH,
        "height": config.VIDEO_HEIGHT,
        "is_portrait": False,
        "is_short": False,
        "content_type": "podcast",
    },
    "reel": {
        "label": "Instagram Reel",
        "duration": 30,
        "width": config.SHORT_WIDTH,
        "height": config.SHORT_HEIGHT,
        "is_portrait": True,
        "is_short": True,
        "content_type": "reel",
    },
    # Commercials — content_type is set dynamically based on ad_format
    "commercial": {
        "label": "Commercial / Ad",
        "duration": 30,
        "width": config.VIDEO_WIDTH,
        "height": config.VIDEO_HEIGHT,
        "is_portrait": False,
        "is_short": False,
        "content_type": "commercial_30",  # overridden at runtime
    },
    "countdown": {
        "label": "Countdown / Top N Ranked List",
        "duration": 720,  # 12 minutes default — enough for top 25
        "width": config.VIDEO_WIDTH,
        "height": config.VIDEO_HEIGHT,
        "is_portrait": False,
        "is_short": False,
        "content_type": "countdown",
    },
}


def run(
    topic: str,
    format: str = "short",
    platforms: list[str] = None,
    audience: str = "general public",
    voice: str = None,
    thumbnail_style: str = "fire",
    privacy: str = "private",
    custom_instructions: str = None,
    dry_run: bool = False,
    cleanup: bool = False,
    skip_research: bool = False,
    ai_video_provider: str = "none",
    higgsfield_model: str = "kling-v2",
    podcast_name: str = "",
    episode_number: int = 1,
    guest_name: str = "",
    # Commercial-specific params
    ad_format: str = "",
    ad_brand: str = "",
    ad_product: str = "",
    ad_benefit: str = "",
    ad_cta: str = "",
    ad_style: str = "cinematic",
    ad_platforms: list = None,
    target_duration: int = None,
    ai_model: str = "claude",
    subscription_tier: str = "starter",
    progress_cb=None,
) -> dict:
    """
    Full pipeline: topic → research → script → audio → video → publish.

    Args:
        topic:               What the content is about (can be anything — it will be researched)
        format:              Content format: short | long | podcast | reel
        platforms:           List of platforms: youtube, tiktok, instagram
        audience:            Target audience description
        voice:               edge-tts voice name
        thumbnail_style:     Thumbnail color style
        privacy:             Upload privacy: private | unlisted | public
        custom_instructions: Extra instructions for the AI
        dry_run:             Generate content but skip uploading
        cleanup:             Remove stock media files after completion
        skip_research:       Skip the research phase (faster, but less factually grounded)

    Returns:
        Manifest dict with all outputs and publish results
    """
    platforms = platforms or []
    ad_platforms = ad_platforms or []
    profile = CONTENT_PROFILES.get(format, CONTENT_PROFILES["short"]).copy()
    voice = voice or config.DEFAULT_VOICE

    def _push_progress(pct: int, msg: str):
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass

    # Commercial: set content_type and duration from ad_format
    if format == "commercial":
        profile["content_type"] = ad_format or "commercial_30"
        dur_map = {"commercial_6": 6, "commercial_15": 15, "commercial_30": 30, "commercial_60": 60}
        profile["duration"] = dur_map.get(ad_format, 30)
        # Inject brand context into topic for script generation
        if ad_brand:
            brand_ctx = f"{ad_brand}"
            if ad_product:
                brand_ctx += f" — {ad_product}"
            if ad_benefit:
                brand_ctx += f". Key benefit: {ad_benefit}"
            if ad_cta:
                brand_ctx += f". CTA: {ad_cta}"
            topic = f"{topic} | {brand_ctx}"
        # Use marketing_studio model for Higgsfield
        if ai_video_provider != "none":
            higgsfield_model = "marketing_studio_video"
    elif target_duration and format == "podcast":
        profile["duration"] = target_duration

    logger.header("Social Optimize")
    logger.info(f"Topic: [bold]{topic}[/bold]")
    logger.info(f"Format: {profile['label']}")
    logger.info(f"Platforms: {', '.join(platforms) if platforms else 'generate only (dry run)'}")

    # ── 1. Create job directory ──────────────────────────────────────────────
    job = file_manager.job_dir(topic, format)
    logger.step("📁", f"Job directory: {job.name}")

    manifest = {
        "topic": topic,
        "format": format,
        "content_type": profile["content_type"],
        "audience": audience,
        "platforms": platforms,
        "created_at": datetime.now().isoformat(),
        "job_dir": str(job),
        "files": {},
        "publish_results": {},
        "research": {},
        "podcast_name": podcast_name or topic,
        "episode_number": episode_number,
        "guest_name": guest_name,
    }

    # ── 2. Research the topic ────────────────────────────────────────────────
    research_context = ""
    brief = None
    _push_progress(8, "Researching topic from Wikipedia & web...")
    if not skip_research:
        with logger.spinner(f"Researching '{topic}' from Wikipedia & web..."):
            try:
                brief = research_topic(topic)
                research_context = brief_to_context(brief)

                # Save research to disk
                research_path = job / "research.json"
                with open(research_path, "w") as f:
                    json.dump({
                        "topic": brief.topic,
                        "summary": brief.summary,
                        "key_facts": brief.key_facts,
                        "data_points": brief.data_points,
                        "sources": brief.sources,
                        "related_topics": brief.related_topics,
                    }, f, indent=2)

                manifest["files"]["research"] = str(research_path)
                manifest["research"] = {
                    "sources": brief.sources,
                    "facts_found": len(brief.key_facts),
                    "data_points_found": len(brief.data_points),
                }
                logger.success(
                    f"Research complete — {len(brief.key_facts)} facts, "
                    f"{len(brief.data_points)} data points from {len(brief.sources)} sources"
                )
            except Exception as e:
                logger.warn(f"Research failed ({e}) — continuing without it")

    # ── 3. Generate script ───────────────────────────────────────────────────
    _MODEL_LABELS = {
        "claude": "Claude AI", "deepseek": "DeepSeek-V3",
        "qwen": "Qwen (Alibaba)", "groq": "Groq/Llama",
        "gemini": "Gemini Flash", "parallel": "Parallel Race", "auto": "AI",
    }
    model_label = _MODEL_LABELS.get(ai_model, "AI")
    _push_progress(18, f"Generating script with {model_label}...")
    SCRIPT_TIMEOUT = 90  # seconds — generous for long countdown scripts
    _script_kwargs = dict(
        topic=topic,
        content_type=profile["content_type"],
        target_duration=profile["duration"],
        audience=audience,
        custom_instructions=custom_instructions,
        research_context=research_context,
        subscription_tier=subscription_tier,
    )

    def _run_script_with_timeout(model: str):
        # NOTE: Do NOT use ThreadPoolExecutor as a context manager here —
        # its __exit__ calls shutdown(wait=True) which blocks even after TimeoutError.
        # Instead: submit, get with timeout, then shutdown(wait=False) to release.
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        _fut = _executor.submit(script_generator.generate_script, ai_model=model, **_script_kwargs)
        try:
            return _fut.result(timeout=SCRIPT_TIMEOUT)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(
                f"Script engine '{model}' did not respond in {SCRIPT_TIMEOUT}s"
            )
        finally:
            # shutdown(wait=False) lets the orphaned thread die on its own;
            # the main thread moves on immediately.
            _executor.shutdown(wait=False)

    print(f"[pipeline] Starting script generation stage with {model_label}...")
    with logger.spinner(f"Generating script with {model_label}..."):
        script = None
        last_err = None
        try:
            script = _run_script_with_timeout(ai_model)
            logger.success(f"Script generated via {model_label}")
        except Exception as e:
            last_err = e
            logger.warn(f"Script engine '{ai_model}' failed: {e}")

        # Fallback chain: try every other available model
        if script is None:
            from generators.ai_router import _available_models
            _fallback_order = ["claude", "gemini", "deepseek", "groq", "qwen"]
            available = _available_models()
            for fb_model in _fallback_order:
                if fb_model == ai_model or fb_model not in available:
                    continue
                fb_label = _MODEL_LABELS.get(fb_model, fb_model)
                print(f"[pipeline] Trying fallback script engine: {fb_label}")
                _push_progress(18, f"Retrying script with {fb_label}...")
                try:
                    script = _run_script_with_timeout(fb_model)
                    logger.success(f"Script generated via {fb_label} (fallback)")
                    break
                except Exception as e:
                    last_err = e
                    logger.warn(f"{fb_label} fallback also failed: {e}")

        if script is None:
            raise RuntimeError(
                f"All script engines failed ({last_err}). "
                "Check API keys (ANTHROPIC_API_KEY, GOOGLE_API_KEY, etc.) on Render."
            )

    script_path = job / "script.json"
    with open(script_path, "w") as f:
        json.dump({
            "title": script.title,
            "description": script.description,
            "hashtags": script.hashtags,
            "narration": script.narration,
            "sections": script.sections,
            "keywords": script.keywords,
            "thumbnail_prompt": script.thumbnail_prompt,
            "estimated_duration": script.estimated_duration,
            "seo_data": script.seo_data,
        }, f, indent=2)

    manifest["title"] = script.title
    manifest["description"] = script.description
    manifest["hashtags"] = script.hashtags
    manifest["keywords"] = script.keywords
    manifest["seo_data"] = script.seo_data
    manifest["files"]["script"] = str(script_path)

    logger.success(f"Script: {script.title[:60]}")

    # ── 4. Generate audio voiceover ──────────────────────────────────────────
    _push_progress(35, f"Creating voiceover audio ({voice})...")
    audio_path = job / "voiceover.mp3"
    print(f"[pipeline] Starting audio generation stage...")
    with logger.spinner(f"Generating voiceover ({voice})..."):
        audio_generator.generate_audio(
            text=script.narration,
            output_path=audio_path,
            voice=voice,
        )
        duration = audio_generator.get_audio_duration(audio_path)
    print(f"[pipeline] Audio stage complete: {duration:.1f}s")

    manifest["duration"] = duration
    manifest["files"]["audio"] = str(audio_path)
    logger.success(f"Voiceover: {duration:.1f}s ({file_manager.get_file_size_mb(audio_path):.1f} MB)")

    # ── 5. Fetch stock media ─────────────────────────────────────────────────
    _push_progress(50, "Fetching stock media...")
    print(f"[pipeline] Starting media fetch stage...")
    with logger.spinner("Fetching stock media..."):
        stock_dir = job / "stock"
        video_clips, image_clips = media_fetcher.fetch_media_for_topic(
            keywords=script.keywords[:5],
            output_dir=stock_dir,
            video_count=6 if not profile["is_portrait"] else 4,
            is_portrait=profile["is_portrait"],
        )

    if video_clips or image_clips:
        logger.success(f"Stock media: {len(video_clips)} videos, {len(image_clips)} images")
    else:
        logger.warn("No stock media fetched (check PEXELS_API_KEY). Using gradient background.")

    # ── 5b. Generate AI video clips (Google Flow / Higgsfield) ───────────────
    ai_clips = []
    if ai_video_provider and ai_video_provider != "none":
        with logger.spinner(f"Generating AI video clips via {ai_video_provider}..."):
            try:
                ai_clips = ai_video_generator.generate_ai_clips(
                    topic=topic,
                    keywords=script.keywords[:6],
                    sections=script.sections,
                    output_dir=job / "ai_clips",
                    provider=ai_video_provider,
                    model_key=higgsfield_model,
                    is_portrait=profile["is_portrait"],
                    max_clips=6,
                )
                manifest["ai_clips"] = {
                    "provider": ai_video_provider,
                    "count": len(ai_clips),
                    "model": higgsfield_model if ai_video_provider in ("higgsville", "both") else "veo3",
                }
                logger.success(f"AI video: {len(ai_clips)} clips generated via {ai_video_provider}")
            except Exception as e:
                logger.warn(f"AI video generation failed ({e}) — using stock media only")

    # AI clips go first for maximum visual impact, then stock videos
    all_video_clips = ai_clips + list(video_clips)

    # ── 6. Generate thumbnail ────────────────────────────────────────────────
    _push_progress(62, "Generating thumbnail...")
    thumbnail_path = job / "thumbnail.jpg"
    bg_image = image_clips[0] if image_clips else None
    with logger.spinner("Generating thumbnail..."):
        thumbnail_generator.generate_thumbnail(
            title=script.title,
            output_path=thumbnail_path,
            background_image_path=bg_image,
            style=thumbnail_style,
            width=1280,
            height=720,
        )

    manifest["files"]["thumbnail"] = str(thumbnail_path)
    logger.success("Thumbnail generated")

    # ── 6b. Generate content graphics (ranked cards, charts, title card) ────
    content_graphics = []
    content_images_dir = job / "graphics"
    if not skip_research and brief:
        _push_progress(68, "Creating ranked cards and infographics...")
        with logger.spinner("Generating ranked cards, charts, and infographics..."):
            try:
                gfx = graphics_generator.generate_content_graphics(
                    topic=topic,
                    research_brief=brief,
                    output_dir=content_images_dir,
                    width=profile["width"],
                    height=profile["height"],
                    bg_images=image_clips[:8],
                )
                # Collect all graphic paths: title card first, then rank cards, then chart
                if gfx.get("title_card"):
                    content_graphics.append(gfx["title_card"])
                content_graphics.extend(gfx.get("rank_cards", []))
                if gfx.get("bar_chart"):
                    content_graphics.append(gfx["bar_chart"])

                manifest["files"]["graphics_dir"] = str(content_images_dir)
                manifest["graphics"] = {
                    "rank_cards": len(gfx.get("rank_cards", [])),
                    "has_chart": gfx.get("bar_chart") is not None,
                    "has_title_card": gfx.get("title_card") is not None,
                }
                logger.success(
                    f"Graphics: {len(gfx.get('rank_cards',[]))} rank cards"
                    + (", bar chart" if gfx.get("bar_chart") else "")
                )
            except Exception as e:
                logger.warn(f"Graphics generation failed ({e}) — using stock media only")

    # Merge custom graphics with stock media (graphics first for impact)
    all_image_sources = content_graphics + list(image_clips)

    # ── 7. Assemble video ────────────────────────────────────────────────────
    _push_progress(78, "Assembling final video...")
    print(f"[pipeline] Starting video assembly stage...")
    video_path = job / "video.mp4"
    with logger.spinner("Assembling video..."):
        if format == "podcast":
            video_generator.create_podcast_video(
                audio_path=audio_path,
                output_path=video_path,
                thumbnail_path=thumbnail_path,
                width=profile["width"],
                height=profile["height"],
                channel_name=podcast_name or topic,
                episode_number=episode_number,
                title=script.title,
                sections=script.sections,
            )
        else:
            video_generator.create_video(
                audio_path=audio_path,
                output_path=video_path,
                video_clips=all_video_clips,
                image_clips=all_image_sources,
                thumbnail_path=thumbnail_path,
                width=profile["width"],
                height=profile["height"],
                sections=script.sections,
                narration_text=script.narration,
            )

    manifest["files"]["video"] = str(video_path)
    video_mb = file_manager.get_file_size_mb(video_path)
    logger.success(f"Video assembled: {video_mb:.1f} MB")

    # ── 8. Publish ───────────────────────────────────────────────────────────
    _push_progress(93, "Publishing to platforms...")
    if dry_run:
        logger.warn("Dry run — skipping upload to platforms")
    else:
        for platform in platforms:
            try:
                if platform == "youtube":
                    with logger.spinner("Uploading to YouTube..."):
                        result = youtube_publisher.upload_video(
                            video_path=video_path,
                            title=script.title,
                            description=script.description,
                            tags=script.hashtags + script.keywords,
                            thumbnail_path=thumbnail_path,
                            privacy=privacy,
                            is_short=profile["is_short"],
                        )
                    manifest["publish_results"]["youtube"] = result
                    logger.success(f"YouTube: {result.get('url')}")

                elif platform == "tiktok":
                    with logger.spinner("Uploading to TikTok..."):
                        result = tiktok_publisher.upload_video(
                            video_path=video_path,
                            title=script.title,
                            description=script.description,
                            tags=script.hashtags,
                            privacy="SELF_ONLY" if privacy == "private" else "PUBLIC_TO_EVERYONE",
                        )
                    manifest["publish_results"]["tiktok"] = result
                    logger.success(f"TikTok: {result.get('publish_id')}")

                elif platform == "instagram":
                    logger.warn("Instagram requires a publicly hosted video URL.")
                    manifest["publish_results"]["instagram"] = {
                        "status": "skipped",
                        "reason": "Instagram requires a public CDN URL. Upload the video manually or host it first.",
                        "video_path": str(video_path),
                    }

                elif platform == "facebook":
                    with logger.spinner("Uploading to Facebook..."):
                        result = facebook_publisher.upload_video(
                            video_path=video_path,
                            title=script.title,
                            description=script.description,
                            tags=script.hashtags + script.keywords,
                        )
                    manifest["publish_results"]["facebook"] = result
                    if result.get("video_id"):
                        logger.success(f"Facebook: {result.get('url')}")
                    else:
                        logger.warn(f"Facebook: {result.get('reason') or result.get('error')}")

                elif platform == "twitter":
                    with logger.spinner("Uploading to Twitter/X..."):
                        result = twitter_publisher.upload_video(
                            video_path=video_path,
                            title=script.title,
                            description=script.description,
                            tags=script.hashtags,
                        )
                    manifest["publish_results"]["twitter"] = result
                    if result.get("tweet_id"):
                        logger.success(f"Twitter/X: {result.get('url')}")
                    else:
                        logger.warn(f"Twitter/X: {result.get('reason') or result.get('error')}")

                elif platform == "linkedin":
                    with logger.spinner("Uploading to LinkedIn..."):
                        result = linkedin_publisher.upload_video(
                            video_path=video_path,
                            title=script.title,
                            description=script.description,
                            tags=script.hashtags + script.keywords,
                        )
                    manifest["publish_results"]["linkedin"] = result
                    if result.get("post_id"):
                        logger.success(f"LinkedIn: {result.get('url')}")
                    else:
                        logger.warn(f"LinkedIn: {result.get('reason') or result.get('error')}")

                elif platform == "pinterest":
                    with logger.spinner("Uploading to Pinterest..."):
                        result = pinterest_publisher.upload_video(
                            video_path=video_path,
                            title=script.title,
                            description=script.description,
                            tags=script.hashtags + script.keywords,
                        )
                    manifest["publish_results"]["pinterest"] = result
                    if result.get("pin_id"):
                        logger.success(f"Pinterest: {result.get('url')}")
                    else:
                        logger.warn(f"Pinterest: {result.get('reason') or result.get('error')}")

                elif platform == "threads":
                    # Threads requires a CDN URL — check manifest for a cdn_url or skip
                    cdn_url = manifest.get("files", {}).get("cdn_url", "")
                    if not cdn_url:
                        logger.warn("Threads requires a public CDN URL — skipping (no cdn_url in manifest).")
                        manifest["publish_results"]["threads"] = {
                            "status": "skipped",
                            "reason": "Threads requires a public CDN URL. No cdn_url found in manifest.",
                            "video_path": str(video_path),
                        }
                    else:
                        with logger.spinner("Uploading to Threads..."):
                            result = threads_publisher.upload_video(
                                video_url=cdn_url,
                                title=script.title,
                                description=script.description,
                                tags=script.hashtags,
                            )
                        manifest["publish_results"]["threads"] = result
                        if result.get("thread_id"):
                            logger.success(f"Threads: {result.get('url')}")
                        else:
                            logger.warn(f"Threads: {result.get('reason') or result.get('error')}")

            except Exception as e:
                logger.error(f"{platform} upload failed: {e}")
                manifest["publish_results"][platform] = {"error": str(e)}

    # ── 9. Save manifest ─────────────────────────────────────────────────────
    manifest_path = file_manager.save_manifest(job, manifest)
    manifest["files"]["manifest"] = str(manifest_path)

    if cleanup:
        removed = file_manager.cleanup_temp_files(job)
        logger.info(f"Cleaned up {removed} temporary stock files")

    logger.header("Done!")
    logger.print_job_summary(manifest)

    return manifest
