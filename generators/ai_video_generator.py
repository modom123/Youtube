"""
AI Video Generator — Google Flow (Veo 2) + Higgsfield AI
Generates cinematic AI video clips from text prompts.
Used as a premium alternative / supplement to stock footage.
"""
import os
import time
import tempfile
import requests
from pathlib import Path
from typing import Optional
import config


# ── Google Flow / Veo 2 ──────────────────────────────────────────────────────

def generate_veo_clips(
    prompts: list[str],
    output_dir: Path,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 8,
    model: str = "veo-002",
) -> list[Path]:
    """
    Generate video clips using Google Veo 2 (Google Flow).
    Returns list of downloaded .mp4 paths.

    Requires: GOOGLE_API_KEY in .env
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai not installed. Run: pip install google-genai")

    api_key = config.GOOGLE_API_KEY
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for i, prompt in enumerate(prompts):
        print(f"[veo2] Generating clip {i+1}/{len(prompts)}: {prompt[:60]}...")
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

            # Poll until done (Veo is async)
            max_wait = 300  # 5 minutes max
            elapsed = 0
            while not operation.done and elapsed < max_wait:
                time.sleep(10)
                elapsed += 10
                operation = client.operations.get(operation)

            if not operation.done:
                print(f"[veo2] Clip {i+1} timed out — skipping")
                continue

            # Download generated video
            for j, generated in enumerate(operation.response.generated_videos):
                video = generated.video
                out_path = output_dir / f"veo2_clip_{i:02d}_{j}.mp4"

                if hasattr(video, "uri") and video.uri:
                    # Download from URI
                    _download_video_uri(video.uri, out_path, api_key)
                elif hasattr(video, "video_bytes") and video.video_bytes:
                    out_path.write_bytes(video.video_bytes)
                else:
                    print(f"[veo2] No video data in response for clip {i+1}")
                    continue

                if out_path.exists() and out_path.stat().st_size > 10000:
                    results.append(out_path)
                    print(f"[veo2] ✓ Clip {i+1} saved: {out_path.name}")

        except Exception as e:
            print(f"[veo2] Clip {i+1} failed: {e}")
            continue

    return results


def _download_video_uri(uri: str, out_path: Path, api_key: str) -> None:
    """Download a video from a Google-hosted URI."""
    headers = {}
    if "googleapis.com" in uri:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.get(uri, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


# ── Higgsfield AI ─────────────────────────────────────────────────────────────

HIGGSFIELD_VIDEO_MODELS = {
    "kling-v2":        "kling/v2/video/text-to-video",
    "kling-v1.6":      "kling/v1.6/video/text-to-video",
    "wan-t2v":         "wan/v1/video/text-to-video",
    "wan-i2v":         "wan/v1/video/image-to-video",
    "hunyuan-t2v":     "tencent/hunyuan/v1/text-to-video",
    "mochi":           "genmo/mochi/v1/text-to-video",
    "luma-dream":      "luma/dream-machine/v1/text-to-video",
    "seedream-image":  "bytedance/seedream/v4/text-to-image",
}

DEFAULT_HIGGSFIELD_MODEL = "kling-v2"


def generate_higgsfield_clips(
    prompts: list[str],
    output_dir: Path,
    model_key: str = DEFAULT_HIGGSFIELD_MODEL,
    aspect_ratio: str = "16:9",
    duration: int = 5,
    quality: str = "standard",
) -> list[Path]:
    """
    Generate video clips using Higgsfield AI (supports Kling, Wan, HunyuanVideo, etc.)
    Returns list of downloaded .mp4 paths.

    Requires: HF_KEY in .env (or HF_API_KEY + HF_API_SECRET)
    """
    try:
        import higgsfield_client as hf
    except ImportError:
        raise RuntimeError("higgsfield-client not installed. Run: pip install higgsfield-client")

    hf_key = config.HIGGSFIELD_API_KEY
    if not hf_key:
        raise RuntimeError("HIGGSFIELD_API_KEY not set in .env")

    # Set credentials
    os.environ["HF_KEY"] = hf_key

    model_path = HIGGSFIELD_VIDEO_MODELS.get(model_key, model_key)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for i, prompt in enumerate(prompts):
        print(f"[higgsfield] Generating clip {i+1}/{len(prompts)} ({model_key}): {prompt[:60]}...")
        try:
            controller = hf.subscribe(
                model_path,
                {
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "duration": duration,
                    "quality": quality,
                },
                on_queue_update=lambda s: print(f"[higgsfield]   Status: {s}"),
            )

            result = controller.result()

            if result and hasattr(result, "url") and result.url:
                out_path = output_dir / f"hf_clip_{i:02d}_{model_key}.mp4"
                _download_file(result.url, out_path)
                if out_path.exists() and out_path.stat().st_size > 10000:
                    results.append(out_path)
                    print(f"[higgsfield] ✓ Clip {i+1} saved: {out_path.name}")
            elif result and isinstance(result, (bytes, bytearray)):
                out_path = output_dir / f"hf_clip_{i:02d}_{model_key}.mp4"
                out_path.write_bytes(result)
                results.append(out_path)
            else:
                print(f"[higgsfield] No video data for clip {i+1}: {result}")

        except Exception as e:
            print(f"[higgsfield] Clip {i+1} failed: {e}")
            continue

    return results


def generate_higgsfield_image(
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "16:9",
    resolution: str = "2K",
) -> Optional[Path]:
    """Generate a single AI image using Higgsfield (SeedDream)."""
    try:
        import higgsfield_client as hf
        os.environ["HF_KEY"] = config.HIGGSFIELD_API_KEY

        controller = hf.subscribe(
            HIGGSFIELD_VIDEO_MODELS["seedream-image"],
            {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "camera_fixed": True,
            },
        )

        result = controller.result()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if result and hasattr(result, "url") and result.url:
            _download_file(result.url, output_path)
            return output_path if output_path.exists() else None
        elif result and isinstance(result, (bytes, bytearray)):
            output_path.write_bytes(result)
            return output_path
        return None

    except Exception as e:
        print(f"[higgsfield] Image generation failed: {e}")
        return None


def _download_file(url: str, out_path: Path) -> None:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


# ── Prompt Builder (shared) ───────────────────────────────────────────────────

def build_video_prompts(
    topic: str,
    keywords: list[str],
    sections: list[dict],
    style: str = "cinematic",
    is_portrait: bool = False,
) -> list[str]:
    """
    Build AI video generation prompts from topic keywords and script sections.
    """
    orientation = "vertical 9:16 portrait" if is_portrait else "horizontal 16:9 landscape"
    style_descriptors = {
        "cinematic": "cinematic film quality, shallow depth of field, professional lighting, dramatic",
        "documentary": "documentary style, natural lighting, authentic, realistic",
        "viral": "dynamic, fast-paced, vibrant colors, social media optimized",
        "nature": "nature documentary, stunning landscape, golden hour lighting",
        "tech": "futuristic, sleek, neon lighting, high-tech aesthetic",
    }
    style_desc = style_descriptors.get(style, style_descriptors["cinematic"])

    prompts = []

    # Intro clip from topic
    prompts.append(
        f"{style_desc}, {orientation}, establishing shot related to '{topic}', "
        f"no text, no subtitles, 4K quality, smooth camera movement"
    )

    # One clip per script section
    for section in sections[:6]:
        cue = section.get("visual_cue", "")
        if cue:
            prompts.append(
                f"{style_desc}, {orientation}, {cue}, "
                f"no text overlays, high quality, smooth motion"
            )

    # Keyword-driven clips if we still need more
    for kw in keywords[:4]:
        if len(prompts) >= 8:
            break
        prompts.append(
            f"{style_desc}, {orientation}, visually representing '{kw}', "
            f"no text, no subtitles, 4K quality"
        )

    return prompts[:8]  # Max 8 AI clips per video


# ── Unified interface ─────────────────────────────────────────────────────────

def generate_ai_clips(
    topic: str,
    keywords: list[str],
    sections: list[dict],
    output_dir: Path,
    provider: str = "higgsfield",
    model_key: str = DEFAULT_HIGGSFIELD_MODEL,
    is_portrait: bool = False,
    max_clips: int = 5,
) -> list[Path]:
    """
    Generate AI video clips using the specified provider.

    provider: "higgsfield" | "google_flow" | "both"
    Returns list of video clip paths.
    """
    output_dir = Path(output_dir)

    prompts = build_video_prompts(
        topic=topic,
        keywords=keywords,
        sections=sections,
        is_portrait=is_portrait,
    )[:max_clips]

    aspect = "9:16" if is_portrait else "16:9"
    clips = []

    if provider in ("higgsfield", "both"):
        if config.HIGGSFIELD_API_KEY:
            hf_clips = generate_higgsfield_clips(
                prompts=prompts,
                output_dir=output_dir / "higgsfield",
                model_key=model_key,
                aspect_ratio=aspect,
            )
            clips.extend(hf_clips)
        else:
            print("[ai_video] HIGGSFIELD_API_KEY not set — skipping Higgsfield")

    if provider in ("google_flow", "both"):
        if config.GOOGLE_API_KEY:
            veo_clips = generate_veo_clips(
                prompts=prompts,
                output_dir=output_dir / "veo2",
                aspect_ratio=aspect,
            )
            clips.extend(veo_clips)
        else:
            print("[ai_video] GOOGLE_API_KEY not set — skipping Google Flow/Veo 2")

    return clips
