"""
Studio Blueprints — The production DNA for each studio.
========================================================
Every studio has ONE thing it's great at. This module codifies exactly:
  - What the final product looks like
  - How many assets, from where, in what order
  - How to compile them
  - Quality gates before delivery

Blueprints are deterministic recipes. The intelligence layer (studio_intelligence.py)
adapts parameters within the blueprint's constraints based on past job performance.
"""

BLUEPRINTS = {

    # ─────────────────────────────────────────────────────────────────────────
    # PRODUCTION STUDIO — "The YouTube Machine"
    # Great at: Consistent, algorithm-friendly YouTube videos that get views
    # ─────────────────────────────────────────────────────────────────────────
    "production": {
        "identity": "The YouTube Machine",
        "great_at": "Producing algorithm-optimized YouTube videos that rank and retain",
        "final_product": {
            "format": "mp4",
            "resolution": "1920x1080",
            "fps": 30,
            "duration_range": [480, 900],  # 8-15 minutes sweet spot
            "audio_codec": "aac",
            "video_codec": "h264",
            "includes": ["narration", "b-roll", "graphics", "background_music", "thumbnail", "seo_package"],
        },
        "asset_recipe": {
            "narration": {
                "source_priority": ["google_tts_studio", "elevenlabs", "edge_tts"],
                "style": "conversational-authority",
                "pacing": "120-150 wpm, 1.5s pause between sections",
                "chunks": "one per section, stitched with crossfade",
            },
            "video_clips": {
                "count_per_minute": 4,  # 4 clips per minute of final video
                "min_clips": 30,
                "max_clips": 60,
                "duration_each": [3, 8],  # seconds
                "source_priority": [
                    {"source": "ai_video", "provider": "higgsfield", "share": 0.3,
                     "prompt_style": "cinematic b-roll matching narration context"},
                    {"source": "stock", "provider": "pixabay", "share": 0.5,
                     "query_strategy": "section keywords + topic synonyms"},
                    {"source": "stock", "provider": "mixkit", "share": 0.2,
                     "query_strategy": "broad category fallback"},
                ],
                "fallback": "graphics_cards",
            },
            "graphics": {
                "per_video": ["title_card", "section_headers", "key_stats", "final_leaderboard"],
                "style": "dark gradient with accent bars",
                "resolution": "1280x720",
            },
            "background_music": {
                "source_priority": ["music_studio_generated", "loop_library"],
                "volume": 0.08,  # relative to narration
                "style": "match video mood — lo-fi for educational, trap for lists, cinematic for stories",
            },
            "thumbnail": {
                "resolution": "1280x720",
                "style": "high-contrast, large text, face if available, 3 colors max",
                "elements": ["hook_text", "key_image", "brand_accent"],
            },
        },
        "compilation": {
            "method": "ffmpeg_concat",
            "transitions": "cut (no dissolves — YouTube algorithm prefers hard cuts)",
            "audio_mix": "narration at 0dB, music at -18dB, sfx at -12dB",
            "intro": "0.5s brand sting + title card (3s)",
            "outro": "subscribe CTA card (5s) + end screen (20s)",
            "captions": "burned-in subtitles, white with black outline, bottom-third",
        },
        "quality_gates": {
            "min_duration_seconds": 420,
            "min_unique_clips": 20,
            "audio_levels": {"narration_db": [-3, 0], "music_db": [-20, -14]},
            "thumbnail_has_text": True,
            "seo_title_length": [40, 70],
            "seo_description_min_words": 100,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # HOLLYWOOD STUDIO — "The Cinematic Storyteller"
    # Great at: Emotional, documentary-grade narratives that make people FEEL
    # ─────────────────────────────────────────────────────────────────────────
    "hollywood": {
        "identity": "The Cinematic Storyteller",
        "great_at": "Producing cinema-quality documentaries with emotional depth",
        "final_product": {
            "format": "mp4",
            "resolution": "1920x1080",
            "fps": 24,  # cinematic framerate
            "duration_range": [480, 1200],  # 8-20 minutes
            "audio_codec": "aac",
            "video_codec": "h264",
            "includes": ["narration", "cinematic_footage", "scene_cards", "original_score", "thumbnail"],
        },
        "asset_recipe": {
            "narration": {
                "source_priority": ["elevenlabs", "google_tts_studio"],
                "style": "dramatic-narrator — measured pace, emotional weight, deliberate pauses",
                "pacing": "100-120 wpm with 2-3s dramatic pauses between scenes",
                "chunks": "one per scene, 2s silence between scenes",
            },
            "video_clips": {
                "count_per_minute": 3,  # slower pacing than production
                "min_clips": 20,
                "max_clips": 45,
                "duration_each": [4, 12],  # longer holds for drama
                "source_priority": [
                    {"source": "ai_video", "provider": "higgsfield", "share": 0.5,
                     "prompt_style": "cinematic establishing shots, slow motion, dramatic lighting",
                     "models": ["kling3.0", "seedance", "wan"]},
                    {"source": "stock", "provider": "pixabay", "share": 0.35,
                     "query_strategy": "emotional context — faces, landscapes, action moments"},
                    {"source": "stock", "provider": "mixkit", "share": 0.15,
                     "query_strategy": "atmospheric wide shots"},
                ],
                "fallback": "slow_ken_burns_on_images",
            },
            "scene_cards": {
                "per_video": ["cold_open_title", "act_breaks", "epilogue_card"],
                "style": "minimal white on black, serif font, fade in/out",
                "duration": 3,
            },
            "background_music": {
                "source_priority": ["music_studio_generated"],
                "volume": 0.12,
                "style": "orchestral/cinematic — builds with narrative, swells at climax, quiet at emotional beats",
            },
            "thumbnail": {
                "resolution": "1280x720",
                "style": "movie-poster aesthetic — dramatic lighting, single subject, minimal text",
                "elements": ["hero_image", "title_overlay", "cinematic_grade"],
            },
        },
        "compilation": {
            "method": "ffmpeg_concat",
            "transitions": "1s crossfade between scenes, cut within scenes",
            "audio_mix": "narration at 0dB, score at -14dB, ambient at -20dB",
            "intro": "cold open hook (15-30s of most dramatic moment) → title card (4s)",
            "outro": "epilogue narration → credits card (8s)",
            "color_grade": "cinematic LUT — slight teal/orange, crushed blacks",
        },
        "quality_gates": {
            "min_duration_seconds": 420,
            "min_unique_clips": 15,
            "min_ai_clips": 5,
            "audio_levels": {"narration_db": [-3, 0], "score_db": [-18, -10]},
            "scene_count": [5, 10],
            "thumbnail_has_text": True,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CREATE — "The All-Format Factory"
    # Great at: Producing any format fast — shorts, long, podcast, docs
    # ─────────────────────────────────────────────────────────────────────────
    "create": {
        "identity": "The All-Format Factory",
        "great_at": "Fast, flexible content in any format — shorts to podcasts",
        "final_product": {
            "format": "mp4",
            "resolution_by_format": {
                "short": "1080x1920",
                "long": "1920x1080",
                "podcast": "1920x1080",
                "commercial": "1080x1920",
            },
            "fps": 30,
            "duration_by_format": {
                "short": [15, 60],
                "long": [300, 900],
                "podcast": [300, 3600],
                "commercial": [15, 30],
            },
            "includes": ["narration", "visuals", "music", "thumbnail"],
        },
        "asset_recipe": {
            "narration": {
                "source_priority": ["google_tts_studio", "elevenlabs", "edge_tts", "espeak"],
                "style_by_format": {
                    "short": "punchy, fast, hook-first — 160+ wpm",
                    "long": "conversational authority — 130 wpm",
                    "podcast": "natural, warm, interview-paced — 140 wpm",
                    "commercial": "energetic, clear CTA — 150 wpm",
                },
            },
            "video_clips": {
                "count_by_format": {
                    "short": [3, 8],
                    "long": [25, 50],
                    "podcast": [1, 5],  # mostly static with waveform
                    "commercial": [4, 10],
                },
                "source_priority": [
                    {"source": "ai_video", "provider": "higgsfield", "share": 0.25},
                    {"source": "stock", "provider": "pixabay", "share": 0.55},
                    {"source": "stock", "provider": "mixkit", "share": 0.20},
                ],
                "fallback": "graphics_cards",
            },
            "background_music": {
                "source_priority": ["loop_library", "music_studio_generated"],
                "volume_by_format": {
                    "short": 0.15,
                    "long": 0.08,
                    "podcast": 0.04,
                    "commercial": 0.12,
                },
            },
        },
        "compilation": {
            "method": "ffmpeg_concat",
            "transitions_by_format": {
                "short": "hard cuts, 0.3s max between clips",
                "long": "cuts with occasional 0.5s crossfade",
                "podcast": "static frame with audio waveform overlay",
                "commercial": "dynamic cuts, zoom transitions",
            },
        },
        "quality_gates": {
            "short": {"min_clips": 3, "max_duration": 60, "has_hook_first_3s": True},
            "long": {"min_clips": 20, "min_duration": 300},
            "podcast": {"min_duration": 300, "audio_quality": "high"},
            "commercial": {"min_clips": 3, "has_cta": True, "max_duration": 30},
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # MUSIC STUDIO — "The Hit Factory"
    # Great at: Producing radio-ready beats and tracks across every genre
    # ─────────────────────────────────────────────────────────────────────────
    "music": {
        "identity": "The Hit Factory",
        "great_at": "Producing professional beats and tracks that sound radio-ready",
        "final_product": {
            "format": "mp3",
            "bitrate": "320k",
            "sample_rate": 44100,
            "channels": "stereo",
            "duration_range": [30, 240],  # 30s to 4 minutes
            "includes": ["instrumental", "optional_vocals", "master_mix"],
        },
        "asset_recipe": {
            "beat_layers": {
                "kick": {"source": "ffmpeg_synth", "frequency_range": [40, 100]},
                "snare": {"source": "ffmpeg_synth", "frequency_range": [150, 300]},
                "hi_hat": {"source": "ffmpeg_synth", "frequency_range": [5000, 10000]},
                "bass": {"source": "ffmpeg_synth", "frequency_range": [30, 150]},
                "pads": {"source": "ffmpeg_synth", "count": [2, 5]},
            },
            "production_chain": [
                "generate individual layers via ffmpeg synthesis",
                "apply style-specific EQ and effects",
                "mix layers with proper gain staging",
                "add style flavor (vinyl crackle for lofi, distortion for drill)",
                "master with compression and limiting",
            ],
            "vocals": {
                "source_priority": ["elevenlabs", "espeak"],
                "lyrics_source": "claude_lyrics_agent",
                "mix": "vocals at 0dB, beat at -6dB",
            },
            "ai_music": {
                "source_priority": ["suno", "replicate_musicgen", "huggingface_musicgen"],
                "use_when": "user requests full AI song or high-quality instrumental",
            },
        },
        "compilation": {
            "method": "ffmpeg_amix",
            "mastering": "compand + loudnorm to -14 LUFS (streaming standard)",
            "fade_in": 0.5,
            "fade_out": 2.0,
        },
        "quality_gates": {
            "min_duration_seconds": 15,
            "min_file_size_bytes": 50000,
            "peak_db_max": -1.0,
            "has_kick_and_snare": True,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CLIPPER — "The Viral Surgeon"
    # Great at: Extracting the ONE moment from long content that goes viral
    # ─────────────────────────────────────────────────────────────────────────
    "clipper": {
        "identity": "The Viral Surgeon",
        "great_at": "Finding and extracting viral-worthy moments from long-form content",
        "final_product": {
            "format": "mp4",
            "resolution": "1080x1920",  # always vertical
            "fps": 30,
            "duration_range": [15, 90],
            "includes": ["clip", "hook_overlay", "captions", "music_bed"],
        },
        "asset_recipe": {
            "source_video": {
                "sources": ["youtube_url", "uploaded_file", "completed_job"],
                "download_tool": "yt-dlp",
                "max_source_duration": 7200,  # 2 hours max
            },
            "clip_detection": {
                "method_priority": [
                    "claude_analysis",  # AI identifies high-energy/emotional moments
                    "silence_detection",  # ffmpeg silence detect for natural breaks
                    "scene_detection",  # ffmpeg scene change detection
                ],
                "clips_to_extract": [5, 15],
                "ranking": "claude virality scoring — hook strength, emotional peak, shareability",
            },
            "enhancements": {
                "reframe": "auto-crop to 9:16 focusing on faces/action",
                "hook_overlay": {
                    "position": "top-center",
                    "duration": 3,
                    "style": "bold sans-serif, white with shadow",
                    "examples": ["Wait for it...", "Nobody talks about this", "This changes everything"],
                },
                "captions": {
                    "style": "word-by-word highlight, bottom-third",
                    "font": "bold sans-serif",
                    "colors": "white text, yellow highlight on current word",
                },
                "music_bed": {
                    "source": "loop_library",
                    "volume": 0.06,
                    "style": "match energy of clip — trending sounds preferred",
                },
            },
        },
        "compilation": {
            "method": "ffmpeg_filter_complex",
            "reframe_filter": "crop=ih*9/16:ih, scale=1080:1920",
            "caption_filter": "drawtext with per-word timing from whisper",
            "output": "one file per clip, ranked by virality score",
        },
        "quality_gates": {
            "min_clips_extracted": 3,
            "min_virality_score": 0.6,
            "has_captions": True,
            "aspect_ratio": "9:16",
            "max_duration": 90,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # EDITING ROOM — "The Polish Machine"
    # Great at: Taking rough cuts and making them broadcast-ready
    # ─────────────────────────────────────────────────────────────────────────
    "editing_room": {
        "identity": "The Polish Machine",
        "great_at": "Refining rough videos into polished, professional final cuts",
        "final_product": {
            "format": "mp4",
            "resolution": "match_source",
            "fps": "match_source",
            "includes": ["re-edited_video", "new_narration", "music_bed", "color_correction"],
        },
        "asset_recipe": {
            "source": {
                "type": "completed_job",
                "decompose": "split into sections by silence/scene detection",
            },
            "re_narration": {
                "source_priority": ["elevenlabs", "google_tts_studio", "edge_tts"],
                "mode": "per-section override — keep original or replace",
            },
            "replacement_clips": {
                "source_priority": [
                    {"source": "user_upload", "share": 0.5},
                    {"source": "ai_video", "provider": "higgsfield", "share": 0.3},
                    {"source": "stock", "provider": "pixabay", "share": 0.2},
                ],
            },
            "music": {
                "source_priority": ["user_upload", "music_studio_catalog", "loop_library"],
                "volume": 0.08,
            },
            "color_correction": {
                "presets": ["warm", "cool", "cinematic", "vibrant", "muted"],
                "method": "ffmpeg eq/colorbalance filters",
            },
        },
        "compilation": {
            "method": "ffmpeg_filter_complex",
            "preserve_timing": True,
            "crossfade_at_edits": 0.5,
        },
        "quality_gates": {
            "output_duration_delta": 0.15,  # within 15% of original
            "audio_sync": True,
            "no_black_frames": True,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # COMMERCIAL — "The Ad Machine"
    # Great at: 15-30s product spots that convert
    # ─────────────────────────────────────────────────────────────────────────
    "commercial": {
        "identity": "The Ad Machine",
        "great_at": "Creating scroll-stopping product ads that convert",
        "final_product": {
            "format": "mp4",
            "resolution_options": ["1080x1920", "1920x1080", "1080x1080"],
            "fps": 30,
            "duration_range": [15, 30],
            "includes": ["product_shots", "voiceover", "music", "cta_card", "logo"],
        },
        "asset_recipe": {
            "product_shots": {
                "source_priority": [
                    {"source": "user_upload", "share": 0.6, "note": "real product photos/video"},
                    {"source": "ai_video", "provider": "higgsfield", "share": 0.3,
                     "prompt_style": "product showcase, studio lighting, slow rotation"},
                    {"source": "stock", "provider": "pixabay", "share": 0.1,
                     "query_strategy": "lifestyle context matching product category"},
                ],
                "count": [4, 8],
                "duration_each": [2, 5],
            },
            "voiceover": {
                "source_priority": ["elevenlabs", "google_tts_studio"],
                "style": "confident, clear, benefit-focused — 150wpm",
                "structure": "hook(3s) → problem(5s) → solution(10s) → CTA(5s)",
            },
            "music": {
                "source": "loop_library",
                "style": "energetic, upbeat, builds to CTA",
                "volume": 0.10,
            },
            "cta_card": {
                "duration": 4,
                "elements": ["brand_logo", "tagline", "url_or_qr", "action_button"],
                "style": "brand colors, clean, large text",
            },
        },
        "compilation": {
            "method": "ffmpeg_filter_complex",
            "transitions": "dynamic — zoom, slide, quick cuts",
            "structure": [
                {"name": "hook", "duration": 3, "purpose": "stop the scroll"},
                {"name": "problem", "duration": 5, "purpose": "agitate the pain point"},
                {"name": "solution", "duration": 10, "purpose": "showcase product benefits"},
                {"name": "social_proof", "duration": 4, "purpose": "testimonial or stats"},
                {"name": "cta", "duration": 4, "purpose": "clear call to action"},
            ],
            "audio_mix": "voiceover at 0dB, music at -16dB, sfx at -10dB",
        },
        "quality_gates": {
            "max_duration": 31,
            "has_cta": True,
            "has_product_shot": True,
            "hook_in_first_3s": True,
            "brand_mentioned": True,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # BATCH — "The Content Army"
    # Great at: Producing many videos at once with consistent quality
    # ─────────────────────────────────────────────────────────────────────────
    "batch": {
        "identity": "The Content Army",
        "great_at": "Mass-producing consistent content across topics efficiently",
        "final_product": {
            "format": "mp4",
            "inherits": "create",  # uses create blueprint per item
            "batch_sizes": [3, 50],
            "includes": ["multiple_videos", "batch_report", "publishing_queue"],
        },
        "asset_recipe": {
            "per_item": "inherits from create blueprint based on selected format",
            "optimization": {
                "shared_music": "reuse same background track across batch if same mood",
                "parallel_research": "research all topics simultaneously",
                "asset_dedup": "avoid using same stock clip in multiple videos",
                "voice_consistency": "same voice/settings across all items",
            },
        },
        "compilation": {
            "method": "sequential_pipeline",
            "concurrency": 1,  # one at a time to avoid resource contention
            "failure_handling": "skip failed, continue batch, report at end",
        },
        "quality_gates": {
            "min_success_rate": 0.8,  # 80% of batch must succeed
            "no_duplicate_clips_across_batch": True,
            "consistent_branding": True,
        },
    },
}


def get_blueprint(studio_name: str) -> dict:
    """Get the production blueprint for a studio."""
    bp = BLUEPRINTS.get(studio_name)
    if not bp:
        raise ValueError(f"Unknown studio: {studio_name}. Available: {list(BLUEPRINTS.keys())}")
    return bp


def get_asset_sources(studio_name: str) -> list:
    """Get prioritized asset source list for a studio."""
    bp = get_blueprint(studio_name)
    recipe = bp.get("asset_recipe", {})
    sources = set()
    for asset_type, cfg in recipe.items():
        if isinstance(cfg, dict):
            for src in cfg.get("source_priority", []):
                if isinstance(src, dict):
                    sources.add(f"{src['source']}:{src.get('provider', 'default')}")
                elif isinstance(src, str):
                    sources.add(src)
    return sorted(sources)


def get_quality_gates(studio_name: str) -> dict:
    """Get quality gate requirements for a studio."""
    bp = get_blueprint(studio_name)
    return bp.get("quality_gates", {})


def validate_output(studio_name: str, output_metadata: dict) -> dict:
    """Validate a studio output against its quality gates. Returns pass/fail per gate."""
    gates = get_quality_gates(studio_name)
    results = {}
    for gate, requirement in gates.items():
        actual = output_metadata.get(gate)
        if actual is None:
            results[gate] = {"passed": False, "reason": "metric not reported"}
            continue
        if isinstance(requirement, bool):
            results[gate] = {"passed": actual == requirement, "expected": requirement, "actual": actual}
        elif isinstance(requirement, (int, float)):
            results[gate] = {"passed": actual >= requirement, "expected": f">= {requirement}", "actual": actual}
        elif isinstance(requirement, list) and len(requirement) == 2:
            results[gate] = {"passed": requirement[0] <= actual <= requirement[1],
                             "expected": f"[{requirement[0]}, {requirement[1]}]", "actual": actual}
        else:
            results[gate] = {"passed": True, "reason": "non-numeric gate, skipped"}
    return results
