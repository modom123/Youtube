"""
Studio Blueprints — The production DNA for each studio.
========================================================
6 named studios, zero overlap. Each is great at ONE thing.

  The Forge      — Premium long-form YouTube videos (5-agent pipeline)
  Cinema House   — Cinematic documentaries & epic narratives
  Hit Factory    — Professional beats, tracks & AI songs
  The Scalpel    — Viral clip extraction from long content
  Ad Lab         — Scroll-stopping product ads that convert
  The Cut        — Post-production polish & remix

The /create page acts as a smart router into the right studio.
Batch mode is a feature toggle on The Forge, not a separate studio.
"""

STUDIO_NAMES = {
    "the_forge":     {"display": "The Forge",     "route": "/studio",       "emoji": "🔥", "tagline": "Where YouTube hits are made"},
    "cinema_house":  {"display": "Cinema House",  "route": "/hollywood",    "emoji": "🎬", "tagline": "Documentary-grade storytelling"},
    "hit_factory":   {"display": "Hit Factory",   "route": "/music-studio", "emoji": "🎵", "tagline": "Beats that sound radio-ready"},
    "the_scalpel":   {"display": "The Scalpel",   "route": "/clipper",      "emoji": "✂️", "tagline": "Extract the viral moment"},
    "ad_lab":        {"display": "Ad Lab",        "route": "/commercial",   "emoji": "📢", "tagline": "Ads that stop the scroll"},
    "the_cut":       {"display": "The Cut",       "route": "/editing-room", "emoji": "🎛️", "tagline": "Polish until it shines"},
}

FORMAT_ROUTER = {
    "short": "the_forge",
    "long": "the_forge",
    "podcast": "the_forge",
    "commercial": "ad_lab",
    "documentary": "cinema_house",
    "cinematic": "cinema_house",
    "music": "hit_factory",
    "clip": "the_scalpel",
    "remix": "the_cut",
    "ad": "ad_lab",
}

BLUEPRINTS = {

    # ─────────────────────────────────────────────────────────────────────────
    # THE FORGE — Premium long-form YouTube content factory
    # Absorbs: Production Studio + Create(long/short/podcast) + Batch
    # ─────────────────────────────────────────────────────────────────────────
    "the_forge": {
        "identity": "The Forge",
        "great_at": "Producing algorithm-optimized YouTube videos that rank, retain, and convert",
        "formats": ["long", "short", "podcast"],
        "batch_capable": True,
        "final_product": {
            "format": "mp4",
            "resolution_by_format": {
                "long": "1920x1080",
                "short": "1080x1920",
                "podcast": "1920x1080",
            },
            "fps": 30,
            "duration_by_format": {
                "long": [480, 900],
                "short": [15, 60],
                "podcast": [300, 3600],
            },
            "audio_codec": "aac",
            "video_codec": "h264",
            "includes": ["narration", "b-roll", "graphics", "background_music", "thumbnail", "seo_package"],
        },
        "asset_recipe": {
            "narration": {
                "source_priority": ["elevenlabs", "google_tts_studio", "edge_tts"],
                "style_by_format": {
                    "long": "conversational authority — 120-150 wpm, 1.5s section pauses",
                    "short": "punchy, fast, hook-first — 160+ wpm, no dead air",
                    "podcast": "natural warmth, interview-paced — 130-140 wpm",
                },
                "chunks": "one per section, stitched with crossfade",
            },
            "video_clips": {
                "count_by_format": {
                    "long": {"per_minute": 4, "min": 30, "max": 60},
                    "short": {"total": [3, 8]},
                    "podcast": {"total": [1, 5]},
                },
                "duration_each": [3, 8],
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
                "source_priority": ["hit_factory_generated", "loop_library"],
                "volume_by_format": {"long": 0.08, "short": 0.15, "podcast": 0.04},
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
            "transitions_by_format": {
                "long": "cut (YouTube algorithm prefers hard cuts)",
                "short": "hard cuts, 0.3s max gap",
                "podcast": "static frame with audio waveform overlay",
            },
            "audio_mix": "narration at 0dB, music at -18dB, sfx at -12dB",
            "intro_by_format": {
                "long": "0.5s brand sting + title card (3s)",
                "short": "immediate hook — no intro",
                "podcast": "5s intro jingle + title card",
            },
            "outro_by_format": {
                "long": "subscribe CTA (5s) + end screen (20s)",
                "short": "follow CTA overlay (2s)",
                "podcast": "next episode teaser (10s)",
            },
            "captions": "burned-in subtitles, white with black outline, bottom-third",
        },
        "batch_config": {
            "max_batch_size": 50,
            "optimization": {
                "shared_music": True,
                "parallel_research": True,
                "asset_dedup": True,
                "voice_consistency": True,
            },
            "concurrency": 1,
            "failure_handling": "skip failed, continue, report at end",
        },
        "quality_gates": {
            "long": {
                "min_duration_seconds": 420,
                "min_unique_clips": 20,
                "thumbnail_has_text": True,
                "seo_title_length": [40, 70],
                "seo_description_min_words": 100,
            },
            "short": {
                "min_clips": 3,
                "max_duration": 60,
                "has_hook_first_3s": True,
            },
            "podcast": {
                "min_duration": 300,
                "audio_quality": "high",
            },
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CINEMA HOUSE — Emotional, documentary-grade narratives
    # ─────────────────────────────────────────────────────────────────────────
    "cinema_house": {
        "identity": "Cinema House",
        "great_at": "Producing cinema-quality documentaries with emotional depth that make people feel",
        "formats": ["documentary", "cinematic"],
        "final_product": {
            "format": "mp4",
            "resolution": "1920x1080",
            "fps": 24,
            "duration_range": [480, 1200],
            "audio_codec": "aac",
            "video_codec": "h264",
            "includes": ["narration", "cinematic_footage", "scene_cards", "original_score", "thumbnail"],
        },
        "asset_recipe": {
            "narration": {
                "source_priority": ["elevenlabs", "google_tts_studio"],
                "style": "dramatic narrator — measured pace, emotional weight, deliberate pauses",
                "pacing": "100-120 wpm with 2-3s dramatic pauses between scenes",
                "chunks": "one per scene, 2s silence between scenes",
            },
            "video_clips": {
                "count_per_minute": 3,
                "min_clips": 20,
                "max_clips": 45,
                "duration_each": [4, 12],
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
                "source_priority": ["hit_factory_generated"],
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
            "scene_count": [5, 10],
            "thumbnail_has_text": True,
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # HIT FACTORY — Professional beats, tracks & AI songs
    # ─────────────────────────────────────────────────────────────────────────
    "hit_factory": {
        "identity": "Hit Factory",
        "great_at": "Producing professional beats and tracks that sound radio-ready across every genre",
        "formats": ["beat", "full_track", "instrumental"],
        "final_product": {
            "format": "mp3",
            "bitrate": "320k",
            "sample_rate": 44100,
            "channels": "stereo",
            "duration_range": [30, 240],
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
    # THE SCALPEL — Viral clip extraction from long-form content
    # ─────────────────────────────────────────────────────────────────────────
    "the_scalpel": {
        "identity": "The Scalpel",
        "great_at": "Finding and extracting the viral moment from long-form content",
        "formats": ["clip"],
        "final_product": {
            "format": "mp4",
            "resolution": "1080x1920",
            "fps": 30,
            "duration_range": [15, 90],
            "includes": ["clip", "hook_overlay", "captions", "music_bed"],
        },
        "asset_recipe": {
            "source_video": {
                "sources": ["youtube_url", "uploaded_file", "completed_job"],
                "download_tool": "yt-dlp",
                "max_source_duration": 7200,
            },
            "clip_detection": {
                "method_priority": [
                    "claude_analysis",
                    "silence_detection",
                    "scene_detection",
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
                    "style": "match energy — trending sounds preferred",
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
    # AD LAB — Scroll-stopping product ads that convert
    # Absorbs: Commercial Studio + Create(commercial)
    # ─────────────────────────────────────────────────────────────────────────
    "ad_lab": {
        "identity": "Ad Lab",
        "great_at": "Creating scroll-stopping product ads that convert browsers into buyers",
        "formats": ["commercial", "ad"],
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
    # THE CUT — Post-production polish & remix
    # ─────────────────────────────────────────────────────────────────────────
    "the_cut": {
        "identity": "The Cut",
        "great_at": "Refining rough videos into polished, broadcast-ready final cuts",
        "formats": ["remix", "re-edit"],
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
                "source_priority": ["user_upload", "hit_factory_catalog", "loop_library"],
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
            "output_duration_delta": 0.15,
            "audio_sync": True,
            "no_black_frames": True,
        },
    },
}

# Legacy aliases for backward compatibility
BLUEPRINTS["production"] = BLUEPRINTS["the_forge"]
BLUEPRINTS["hollywood"] = BLUEPRINTS["cinema_house"]
BLUEPRINTS["music"] = BLUEPRINTS["hit_factory"]
BLUEPRINTS["clipper"] = BLUEPRINTS["the_scalpel"]
BLUEPRINTS["commercial"] = BLUEPRINTS["ad_lab"]
BLUEPRINTS["editing_room"] = BLUEPRINTS["the_cut"]
BLUEPRINTS["create"] = BLUEPRINTS["the_forge"]
BLUEPRINTS["batch"] = BLUEPRINTS["the_forge"]


def get_blueprint(studio_name: str) -> dict:
    """Get the production blueprint for a studio."""
    bp = BLUEPRINTS.get(studio_name)
    if not bp:
        raise ValueError(f"Unknown studio: {studio_name}. Available: {list(STUDIO_NAMES.keys())}")
    return bp


def get_studio_info(studio_name: str) -> dict:
    """Get display info for a studio (name, route, emoji, tagline)."""
    return STUDIO_NAMES.get(studio_name, {})


def route_format(format_name: str) -> str:
    """Given a content format, return which studio handles it."""
    return FORMAT_ROUTER.get(format_name, "the_forge")


def get_all_studios() -> list:
    """Return all studio names with display info and blueprint identity."""
    result = []
    for key, info in STUDIO_NAMES.items():
        bp = BLUEPRINTS.get(key, {})
        result.append({
            "id": key,
            "display": info["display"],
            "route": info["route"],
            "emoji": info["emoji"],
            "tagline": info["tagline"],
            "great_at": bp.get("great_at", ""),
            "formats": bp.get("formats", []),
        })
    return result


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
        if isinstance(requirement, dict) and not any(k in requirement for k in ("passed", "expected")):
            continue
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
