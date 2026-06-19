"""
Social Optimize Machine - Core Orchestrator
Turns any topic into a complete multi-platform content package.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import config
from generators import script_generator, audio_generator, video_generator, media_fetcher, thumbnail_generator
from publishers import youtube_publisher, tiktok_publisher, instagram_publisher
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
) -> dict:
    """
    Full pipeline: topic → script → audio → video → publish.

    Args:
        topic:               What the content is about
        format:              Content format: short | long | podcast | reel
        platforms:           List of platforms: youtube, tiktok, instagram
        audience:            Target audience description
        voice:               edge-tts voice name
        thumbnail_style:     Thumbnail color style: fire | ocean | purple | dark | green | sunset
        privacy:             Upload privacy: private | unlisted | public
        custom_instructions: Extra instructions for the AI
        dry_run:             Generate content but skip uploading
        cleanup:             Remove stock media files after completion

    Returns:
        Manifest dict with all outputs and publish results
    """
    platforms = platforms or []
    profile = CONTENT_PROFILES.get(format, CONTENT_PROFILES["short"])
    voice = voice or config.DEFAULT_VOICE

    logger.header(f"Social Optimize Machine")
    logger.info(f"Topic: [bold]{topic}[/bold]")
    logger.info(f"Format: {profile['label']}")
    logger.info(f"Platforms: {', '.join(platforms) if platforms else 'generate only'}")

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
    }

    # ── 2. Generate script ───────────────────────────────────────────────────
    with logger.spinner("Generating script with Claude AI..."):
        script = script_generator.generate_script(
            topic=topic,
            content_type=profile["content_type"],
            target_duration=profile["duration"],
            audience=audience,
            custom_instructions=custom_instructions,
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
        }, f, indent=2)

    manifest["title"] = script.title
    manifest["description"] = script.description
    manifest["hashtags"] = script.hashtags
    manifest["keywords"] = script.keywords
    manifest["files"]["script"] = str(script_path)

    logger.success(f"Script: {script.title[:60]}")

    # ── 3. Generate audio voiceover ──────────────────────────────────────────
    audio_path = job / "voiceover.mp3"
    with logger.spinner(f"Generating voiceover ({voice})..."):
        audio_generator.generate_audio(
            text=script.narration,
            output_path=audio_path,
            voice=voice,
        )
        duration = audio_generator.get_audio_duration(audio_path)

    manifest["duration"] = duration
    manifest["files"]["audio"] = str(audio_path)
    logger.success(f"Voiceover: {duration:.1f}s ({file_manager.get_file_size_mb(audio_path):.1f} MB)")

    # ── 4. Fetch stock media ─────────────────────────────────────────────────
    with logger.spinner("Fetching stock media from Pexels..."):
        stock_dir = job / "stock"
        video_clips, image_clips = media_fetcher.fetch_media_for_topic(
            keywords=script.keywords[:5],
            output_dir=stock_dir,
            video_count=6 if not profile["is_portrait"] else 4,
            is_portrait=profile["is_portrait"],
        )

    if video_clips or image_clips:
        logger.success(f"Media: {len(video_clips)} videos, {len(image_clips)} images")
    else:
        logger.warn("No stock media fetched (check PEXELS_API_KEY). Using color background.")

    # ── 5. Generate thumbnail ────────────────────────────────────────────────
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

    # ── 6. Assemble video ────────────────────────────────────────────────────
    video_path = job / "video.mp4"
    with logger.spinner("Assembling video..."):
        if format == "podcast":
            video_generator.create_podcast_video(
                audio_path=audio_path,
                output_path=video_path,
                thumbnail_path=thumbnail_path,
                width=profile["width"],
                height=profile["height"],
            )
        else:
            video_generator.create_video(
                audio_path=audio_path,
                output_path=video_path,
                video_clips=video_clips,
                image_clips=image_clips,
                thumbnail_path=thumbnail_path,
                width=profile["width"],
                height=profile["height"],
                sections=script.sections,
                narration_text=script.narration,
            )

    manifest["files"]["video"] = str(video_path)
    video_mb = file_manager.get_file_size_mb(video_path)
    logger.success(f"Video assembled: {video_mb:.1f} MB")

    # ── 7. Publish ───────────────────────────────────────────────────────────
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
                    logger.warn("Instagram requires a publicly hosted video URL. Set video_url manually or use a CDN.")
                    manifest["publish_results"]["instagram"] = {
                        "status": "skipped",
                        "reason": "Instagram requires public video URL (CDN). Upload manually or host the video first.",
                        "video_path": str(video_path),
                    }

            except Exception as e:
                logger.error(f"{platform} upload failed: {e}")
                manifest["publish_results"][platform] = {"error": str(e)}

    # ── 8. Save manifest ─────────────────────────────────────────────────────
    manifest_path = file_manager.save_manifest(job, manifest)
    manifest["files"]["manifest"] = str(manifest_path)

    if cleanup:
        removed = file_manager.cleanup_temp_files(job)
        logger.info(f"Cleaned up {removed} temporary stock files")

    logger.header("Done!")
    logger.print_job_summary(manifest)

    return manifest
