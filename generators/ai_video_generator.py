"""
AI Video Generator — Higgsville + Google Flow (Veo 3)
Generates cinematic AI video clips from text prompts.
Supports: Kling 3.0, Veo 3/3.1, Seedance 2.0, Cinema Studio 3.0,
          Minimax Hailuo, Wan 2.7, Grok Imagine, and more.
"""
import os
import time
import threading
import requests
from pathlib import Path
from typing import Optional
import config

# Per-thread Higgsfield token override (set by app.py thread functions)
_session_token: threading.local = threading.local()


# ── Higgsville model catalog ───────────────────────────────────────────────────────────────────────────────
# Keys match the Higgsville API model IDs
HIGGSVILLE_MODELS = {
    # Kling
    "kling3_0":          {"name": "Kling 3.0",           "provider": "Kling",       "tag": "Multi-shot, 4K, audio"},
    "kling3_0_turbo":    {"name": "Kling 3.0 Turbo",     "provider": "Kling",       "tag": "Fast text-to-video"},
    "kling2_6":          {"name": "Kling 2.6",            "provider": "Kling",       "tag": "Cinematic + physics"},
    # Google Veo
    "veo3_1":            {"name": "Google Veo 3.1",       "provider": "Google",      "tag": "Ultra-realistic, top-tier"},
    "veo3":              {"name": "Google Veo 3",         "provider": "Google",      "tag": "Cinematic, broad creative"},
    "veo3_1_lite":       {"name": "Veo 3.1 Lite",         "provider": "Google",      "tag": "Fast, budget batch"},
    # Higgsfield Cinema
    "cinematic_studio_3_0":      {"name": "Cinema Studio 3.0",   "provider": "Higgsfield", "tag": "Best quality, cinema-grade"},
    "cinematic_studio_video_v2": {"name": "Cinema Studio 2",     "provider": "Higgsfield", "tag": "Genre control, cinematic"},
    "cinematic_studio_video":    {"name": "Cinema Studio",       "provider": "Higgsfield", "tag": "Dramatic compositions"},
    # ByteDance Seedance
    "seedance_2_0":      {"name": "Seedance 2.0",         "provider": "ByteDance",   "tag": "Identity-consistent, reference"},
    "seedance_1_5":      {"name": "Seedance 1.5 Pro",     "provider": "ByteDance",   "tag": "Reliable motion + quality"},
    # Others
    "minimax_hailuo":    {"name": "Minimax Hailuo",       "provider": "Hailuo",      "tag": "Natural physics + emotion"},
    "wan2_7":            {"name": "Wan 2.7",              "provider": "Wan",         "tag": "Audio-synced, character"},
    "wan2_6":            {"name": "Wan 2.6",              "provider": "Wan",         "tag": "Stylized, experimental"},
    "grok_video_v15":    {"name": "Grok Imagine 1.5",     "provider": "xAI",         "tag": "Cinematic image-to-video"},
    "grok_video":        {"name": "Grok Imagine",         "provider": "xAI",         "tag": "Versatile text-to-video"},
    # Marketing
    "marketing_studio_video": {"name": "Marketing Studio", "provider": "Higgsfield", "tag": "TikTok/Reels product ads"},
}

DEFAULT_HIGGSVILLE_MODEL = "kling3_0"
HIGGSVILLE_API_BASE = "https://api.higgsfield.ai/v1"


# ── Higgsville REST API client ────────────────────────────────────────────────────────────────────────────

def _higgsville_headers() -> dict:
    key = getattr(_session_token, "value", None) or config.HIGGSFIELD_MCP_TOKEN
    if not key:
        raise RuntimeError("Higgsfield not connected — authenticate via Accounts page")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def has_higgsfield_key() -> bool:
    """True if this thread has a connected user's token OR the global system
    token is configured. Gates that only check config.HIGGSFIELD_MCP_TOKEN
    silently skip AI visual generation for every customer who connected
    their own Higgsfield account but relies on no system-wide token being
    set -- always check this instead."""
    return bool(getattr(_session_token, "value", None) or config.HIGGSFIELD_MCP_TOKEN)


def _higgsville_generate(model_id: str, prompt: str, params: dict) -> Optional[str]:
    """Submit a generation job. Returns job_id or None on failure."""
    try:
        payload = {"model": model_id, "prompt": prompt, **params}
        resp = requests.post(
            f"{HIGGSVILLE_API_BASE}/generate",
            headers=_higgsville_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("job_id") or data.get("id")
    except Exception as e:
        print(f"[higgsville] Submit failed: {e}")
        return None


def _higgsville_poll(job_id: str, timeout: int = 600) -> Optional[str]:
    """Poll until done. Returns download URL or None."""
    elapsed = 0
    wait = 10
    while elapsed < timeout:
        try:
            resp = requests.get(
                f"{HIGGSVILLE_API_BASE}/jobs/{job_id}",
                headers=_higgsville_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "").lower()

            if status in ("completed", "done", "succeeded"):
                return (
                    data.get("output_url")
                    or data.get("url")
                    or data.get("result", {}).get("url")
                )
            elif status in ("failed", "error", "cancelled"):
                print(f"[higgsville] Job {job_id} failed: {data.get('error')}")
                return None

            poll_after = data.get("poll_after_seconds", wait)
            time.sleep(poll_after)
            elapsed += poll_after
        except Exception as e:
            print(f"[higgsville] Poll error: {e}")
            time.sleep(wait)
            elapsed += wait

    print(f"[higgsville] Job {job_id} timed out after {timeout}s")
    return None


def generate_higgsville_clips(
    prompts: list[str],
    output_dir: Path,
    model_id: str = DEFAULT_HIGGSVILLE_MODEL,
    aspect_ratio: str = "16:9",
    duration: int = 5,
) -> list[Path]:
    """
    Generate video clips via Higgsville API.
    Supports all models in HIGGSVILLE_MODELS catalog.
    Returns list of downloaded .mp4 paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    model_info = HIGGSVILLE_MODELS.get(model_id, {})
    model_name = model_info.get("name", model_id)

    params = {"aspect_ratio": aspect_ratio, "duration": duration}

    # Model-specific param adjustments
    if model_id in ("kling3_0",):
        params["mode"] = "std"
        params["sound"] = "on"
    elif model_id == "kling3_0_turbo":
        params["resolution"] = "720p"
    elif model_id in ("veo3_1",):
        params["quality"] = "basic"
        params["model"] = "veo-3-1-fast"
    elif model_id == "veo3":
        params["model"] = "veo-3-fast"
    elif model_id == "veo3_1_lite":
        params["resolution"] = "720p"
        params["generate_audio"] = False
    elif model_id == "cinematic_studio_video_v2":
        params["genre"] = "auto"
        params["mode"] = "std"
    elif model_id == "seedance_2_0":
        params["mode"] = "std"
        params["genre"] = "cinematic"
    elif model_id == "minimax_hailuo":
        params["model"] = "minimax-2.3"
        params["resolution"] = "768"

    for i, prompt in enumerate(prompts):
        print(f"[higgsville:{model_name}] Clip {i+1}/{len(prompts)}: {prompt[:60]}...")
        try:
            # Try SDK first, fall back to REST API
            clip_path = _try_sdk_clip(prompt, output_dir, model_id, i, aspect_ratio, duration)
            if clip_path is None:
                job_id = _higgsville_generate(model_id, prompt, params)
                if not job_id:
                    continue
                print(f"[higgsville] Job submitted: {job_id}")
                url = _higgsville_poll(job_id)
                if not url:
                    continue
                clip_path = output_dir / f"hv_{model_id}_{i:02d}.mp4"
                try:
                    _download_file(url, clip_path)
                except Exception as e:
                    print(f"[higgsville] Download failed, retrying once: {e}")
                    _download_file(url, clip_path)

            if clip_path and _is_valid_mp4(clip_path):
                results.append(clip_path)
                print(f"[higgsville] ✓ Clip {i+1} saved: {clip_path.name}")
            elif clip_path and clip_path.exists():
                print(f"[higgsville] ✗ Clip {i+1} downloaded but failed validation (corrupt/incomplete): {clip_path}")
                clip_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"[higgsville] Clip {i+1} error: {e}")
            continue

    return results


def _try_sdk_clip(
    prompt: str, output_dir: Path, model_id: str, idx: int,
    aspect_ratio: str, duration: int
) -> Optional[Path]:
    """Attempt generation via higgsfield-client SDK. Returns path or None."""
    try:
        import higgsfield_client as hf
        os.environ["HF_KEY"] = getattr(_session_token, "value", None) or config.HIGGSFIELD_MCP_TOKEN

        # Map new model IDs to SDK paths where known
        sdk_paths = {
            "kling3_0":          "kling/v3/video/text-to-video",
            "kling3_0_turbo":    "kling/v3/video/text-to-video-turbo",
            "kling2_6":          "kling/v2.6/video/text-to-video",
            "wan2_7":            "wan/v2.7/video/text-to-video",
            "wan2_6":            "wan/v2.6/video/text-to-video",
            "seedance_2_0":      "bytedance/seedance/v2/text-to-video",
            "seedance_1_5":      "bytedance/seedance/v1.5/text-to-video",
            "cinematic_studio_3_0": "higgsfield/cinematic-studio/v3/text-to-video",
            "cinematic_studio_video_v2": "higgsfield/cinematic-studio/v2/text-to-video",
            "minimax_hailuo":    "minimax/hailuo/v2.3/text-to-video",
        }

        path = sdk_paths.get(model_id)
        if not path:
            return None

        controller = hf.subscribe(
            path,
            {"prompt": prompt, "aspect_ratio": aspect_ratio, "duration": duration},
            on_queue_update=lambda s: print(f"[higgsville]   {s}"),
        )
        result = controller.result()
        out = output_dir / f"hv_{model_id}_{idx:02d}.mp4"

        if result and hasattr(result, "url") and result.url:
            _download_file(result.url, out)
            return out if out.exists() else None
        elif result and isinstance(result, (bytes, bytearray)):
            out.write_bytes(result)
            return out
        return None
    except Exception:
        return None


# ── Google Flow / Veo ────────────────────────────────────────────────────────────────────────────────

def generate_veo_clips(
    prompts: list[str],
    output_dir: Path,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 8,
    model: str = "veo-002",
) -> list[Path]:
    """Generate video clips using Google Veo (via google-genai SDK)."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai not installed. Run: pip install google-genai")

    if not config.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY not set in .env")

    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, prompt in enumerate(prompts):
        print(f"[veo] Generating clip {i+1}/{len(prompts)}: {prompt[:60]}...")
        try:
            operation = client.models.generate_video(
                model=model,
                prompt=prompt,
                config=types.GenerateVideoConfig(
                    aspect_ratio=aspect_ratio,
                    duration_seconds=min(duration_seconds, 8),
                    number_of_videos=1,
                    enhance_prompt=True,
                ),
            )
            max_wait, elapsed = 300, 0
            while not operation.done and elapsed < max_wait:
                time.sleep(10)
                elapsed += 10
                operation = client.operations.get(operation)

            if not operation.done:
                print(f"[veo] Clip {i+1} timed out")
                continue

            for j, generated in enumerate(operation.response.generated_videos):
                video = generated.video
                out_path = output_dir / f"veo_clip_{i:02d}_{j}.mp4"
                if hasattr(video, "uri") and video.uri:
                    _download_veo_uri(video.uri, out_path, config.GOOGLE_API_KEY)
                elif hasattr(video, "video_bytes") and video.video_bytes:
                    out_path.write_bytes(video.video_bytes)
                else:
                    continue
                if out_path.exists() and out_path.stat().st_size > 10000:
                    results.append(out_path)
                    print(f"[veo] ✓ Clip {i+1} saved: {out_path.name}")
        except Exception as e:
            print(f"[veo] Clip {i+1} failed: {e}")
            continue

    return results


def _download_veo_uri(uri: str, out_path: Path, api_key: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if "googleapis.com" in uri else {}
    resp = requests.get(uri, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def _download_file(url: str, out_path: Path) -> None:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    expected_len = resp.headers.get("Content-Length")
    written = 0
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            written += len(chunk)
    if expected_len is not None and written != int(expected_len):
        out_path.unlink(missing_ok=True)
        raise IOError(
            f"Incomplete download: got {written} bytes, expected {expected_len} ({url})"
        )


def _is_valid_mp4(path: Path) -> bool:
    """Cheap structural check: a finished mp4 must contain a moov atom
    (Higgsfield/CDN downloads can get cut off mid-stream and pass a naive
    size check while still being unplayable)."""
    try:
        if not path.exists() or path.stat().st_size < 10000:
            return False
        with open(path, "rb") as f:
            data = f.read()
        return b"moov" in data and b"ftyp" in data[:64]
    except Exception:
        return False


# ── Prompt Builder ──────────────────────────────────────────────────────────────────────────────────

def build_video_prompts(
    topic: str,
    keywords: list[str],
    sections: list[dict],
    style: str = "cinematic",
    is_portrait: bool = False,
) -> list[str]:
    orientation = "vertical 9:16 portrait" if is_portrait else "horizontal 16:9 landscape"
    styles = {
        "cinematic":   "cinematic film quality, shallow depth of field, professional lighting, dramatic",
        "documentary": "documentary style, natural lighting, authentic, realistic",
        "viral":       "dynamic, fast-paced, vibrant colors, social media optimized",
        "nature":      "nature documentary, stunning landscape, golden hour lighting",
        "tech":        "futuristic, sleek, neon lighting, high-tech aesthetic",
    }
    style_desc = styles.get(style, styles["cinematic"])
    prompts = [
        f"{style_desc}, {orientation}, establishing shot related to '{topic}', "
        f"no text, no subtitles, 4K quality, smooth camera movement"
    ]
    for section in sections[:6]:
        cue = section.get("visual_cue", "")
        if cue:
            prompts.append(
                f"{style_desc}, {orientation}, {cue}, no text overlays, high quality, smooth motion"
            )
    for kw in keywords[:4]:
        if len(prompts) >= 8:
            break
        prompts.append(
            f"{style_desc}, {orientation}, visually representing '{kw}', no text, no subtitles, 4K quality"
        )
    return prompts[:8]


# ── Unified interface ─────────────────────────────────────────────────────────────────────────────────

def generate_ai_clips(
    topic: str,
    keywords: list[str],
    sections: list[dict],
    output_dir: Path,
    provider: str = "higgsville",
    model_key: str = DEFAULT_HIGGSVILLE_MODEL,
    is_portrait: bool = False,
    max_clips: int = 5,
) -> list[Path]:
    """
    Generate AI video clips using the specified provider.
    provider: "higgsville" | "google_flow" | "both" | "none"

    Higgsfield path tries the MCP endpoint first (https://mcp.higgsfield.ai/mcp),
    then falls back to the higgsfield-client SDK, then the REST API.
    """
    output_dir = Path(output_dir)
    prompts = build_video_prompts(
        topic=topic, keywords=keywords, sections=sections, is_portrait=is_portrait,
    )[:max_clips]
    aspect = "9:16" if is_portrait else "16:9"
    clips = []

    if provider in ("higgsville", "both"):
        if has_higgsfield_key():
            hv_clips = _generate_higgsville_with_mcp_fallback(
                prompts=prompts,
                output_dir=output_dir / "higgsville",
                model_id=model_key,
                aspect_ratio=aspect,
            )
            clips.extend(hv_clips)
        else:
            print("[ai_video] No Higgsfield token (user or system) — skipping Higgsville")

    if provider in ("google_flow", "both"):
        if config.GOOGLE_API_KEY:
            veo_clips = generate_veo_clips(
                prompts=prompts,
                output_dir=output_dir / "veo",
                aspect_ratio=aspect,
            )
            clips.extend(veo_clips)
        else:
            print("[ai_video] GOOGLE_API_KEY not set — skipping Google Flow/Veo")

    return clips


def _generate_higgsville_with_mcp_fallback(
    prompts: list[str],
    output_dir: Path,
    model_id: str,
    aspect_ratio: str,
    duration: int = 5,
) -> list[Path]:
    """
    Try Higgsfield CLI first (non-interactive, seeds token from env).
    Fall back to MCP endpoint → SDK → REST API.
    """
    # 1. CLI path (preferred — single binary, no SDK dependency)
    try:
        from generators.higgsfield_cli import generate_clips_via_cli, is_authenticated
        if is_authenticated():
            cli_clips = generate_clips_via_cli(
                prompts=prompts,
                output_dir=output_dir / "cli",
                model_id=model_id,
                aspect_ratio=aspect_ratio,
                duration=duration,
            )
            if cli_clips:
                print(f"[ai_video] ✓ {len(cli_clips)} clips via Higgsfield CLI")
                return cli_clips
            print("[ai_video] CLI returned 0 clips — falling back to MCP")
    except Exception as e:
        print(f"[ai_video] CLI path error ({e}) — falling back to MCP")

    # 2. MCP path
    try:
        from generators.higgsfield_mcp import generate_clips_via_mcp
        mcp_clips = generate_clips_via_mcp(
            prompts=prompts,
            output_dir=output_dir / "mcp",
            model_id=model_id,
            aspect_ratio=aspect_ratio,
            duration=duration,
        )
        if mcp_clips:
            print(f"[ai_video] ✓ {len(mcp_clips)} clips via Higgsfield MCP")
            return mcp_clips
        print("[ai_video] MCP returned 0 clips — falling back to SDK/REST")
    except Exception as e:
        print(f"[ai_video] MCP path error ({e}) — falling back to SDK/REST")

    # 3. SDK / REST fallback
    return generate_higgsville_clips(
        prompts=prompts,
        output_dir=output_dir,
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        duration=duration,
    )
