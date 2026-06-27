"""
Chinese Open-Source AI Video Client
Interfaces with Alibaba Wan 2.7, Tencent HunyuanVideo, and ByteDance Seedance 2.0
via serverless GPU endpoints (RunPod / MassedCompute).

Tier 2 (ULTRA-CHEAP) in the 3-tier cost routing system:
  Tier 1: FREE — Pexels stock footage
  Tier 2: ULTRA-CHEAP — Chinese open-source models (~$0.02/clip)
  Tier 3: PREMIUM — Higgsfield subscription (complex agentic shots)
"""
from __future__ import annotations
import time
import requests
from pathlib import Path
from typing import Optional
import config


CHINESE_MODELS = {
    "wan2_7_opensource": {
        "name": "Wan 2.7 (Open-Source)",
        "provider": "Alibaba",
        "license": "Apache 2.0",
        "strengths": ["b-roll", "text-to-video", "image-to-video", "stylized"],
        "cost_per_clip_usd": 0.02,
        "default_duration": 5,
        "supports_i2v": True,
    },
    "hunyuan_video": {
        "name": "HunyuanVideo",
        "provider": "Tencent",
        "license": "Tencent Hunyuan",
        "strengths": ["cinematic", "13B-param", "high-fidelity", "long-form"],
        "cost_per_clip_usd": 0.05,
        "default_duration": 5,
        "supports_i2v": False,
    },
    "seedance2_opensource": {
        "name": "Seedance 2.0 (Open-Source)",
        "provider": "ByteDance",
        "license": "Research",
        "strengths": ["character-consistency", "identity-preserving", "reference-driven"],
        "cost_per_clip_usd": 0.04,
        "default_duration": 5,
        "supports_i2v": True,
    },
}

DEFAULT_CHINESE_MODEL = "wan2_7_opensource"


def _get_endpoint_url(model_id: str) -> str:
    endpoints = {
        "wan2_7_opensource": config.RUNPOD_WAN_ENDPOINT,
        "hunyuan_video": config.RUNPOD_HUNYUAN_ENDPOINT,
        "seedance2_opensource": config.RUNPOD_SEEDANCE_ENDPOINT,
    }
    url = endpoints.get(model_id, "")
    if not url:
        raise RuntimeError(f"No serverless endpoint configured for {model_id}. "
                           f"Set the appropriate RUNPOD_*_ENDPOINT env var.")
    return url


def _serverless_headers() -> dict:
    key = config.RUNPOD_API_KEY
    if not key:
        raise RuntimeError("RUNPOD_API_KEY not set in .env")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _submit_job(model_id: str, prompt: str, params: dict) -> Optional[str]:
    endpoint = _get_endpoint_url(model_id)
    payload = {
        "input": {
            "prompt": prompt,
            "model": model_id,
            **params,
        }
    }
    try:
        resp = requests.post(
            f"{endpoint}/run",
            headers=_serverless_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("id")
    except Exception as e:
        print(f"[chinese_video:{model_id}] Submit failed: {e}")
        return None


def _poll_job(model_id: str, job_id: str, timeout: int = 600) -> Optional[str]:
    endpoint = _get_endpoint_url(model_id)
    elapsed = 0
    wait = 10
    while elapsed < timeout:
        try:
            resp = requests.get(
                f"{endpoint}/status/{job_id}",
                headers=_serverless_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "").upper()

            if status == "COMPLETED":
                output = data.get("output", {})
                return (
                    output.get("video_url")
                    or output.get("url")
                    or output.get("result", {}).get("url")
                )
            elif status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                print(f"[chinese_video:{model_id}] Job {job_id} {status}: "
                      f"{data.get('error', 'unknown')}")
                return None

            time.sleep(wait)
            elapsed += wait
        except Exception as e:
            print(f"[chinese_video:{model_id}] Poll error: {e}")
            time.sleep(wait)
            elapsed += wait

    print(f"[chinese_video:{model_id}] Job {job_id} timed out after {timeout}s")
    return None


def _download_file(url: str, out_path: Path) -> None:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def generate_chinese_clips(
    prompts: list[str],
    output_dir: Path,
    model_id: str = DEFAULT_CHINESE_MODEL,
    aspect_ratio: str = "16:9",
    duration: int = 5,
    reference_image: Optional[str] = None,
) -> list[Path]:
    """
    Generate video clips via Chinese open-source models on serverless GPU.
    Returns list of downloaded .mp4 paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    model_info = CHINESE_MODELS.get(model_id, {})
    model_name = model_info.get("name", model_id)

    params = {
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "num_inference_steps": 30,
    }

    if model_id == "wan2_7_opensource":
        params["resolution"] = "720p"
        params["guidance_scale"] = 7.5
        if reference_image and model_info.get("supports_i2v"):
            params["image_url"] = reference_image
            params["mode"] = "image-to-video"
        else:
            params["mode"] = "text-to-video"

    elif model_id == "hunyuan_video":
        params["resolution"] = "720p"
        params["guidance_scale"] = 6.0
        params["num_inference_steps"] = 50

    elif model_id == "seedance2_opensource":
        params["resolution"] = "720p"
        params["guidance_scale"] = 7.0
        if reference_image and model_info.get("supports_i2v"):
            params["reference_image"] = reference_image
            params["mode"] = "reference-driven"
        else:
            params["mode"] = "text-to-video"

    for i, prompt in enumerate(prompts):
        print(f"[chinese_video:{model_name}] Clip {i+1}/{len(prompts)}: {prompt[:60]}...")
        try:
            job_id = _submit_job(model_id, prompt, params)
            if not job_id:
                continue

            print(f"[chinese_video] Job submitted: {job_id}")
            url = _poll_job(model_id, job_id)
            if not url:
                continue

            clip_path = output_dir / f"cn_{model_id}_{i:02d}.mp4"
            _download_file(url, clip_path)

            if clip_path.exists() and clip_path.stat().st_size > 10000:
                results.append(clip_path)
                print(f"[chinese_video] Clip {i+1} saved: {clip_path.name}")
        except Exception as e:
            print(f"[chinese_video] Clip {i+1} error: {e}")
            continue

    return results


def estimate_cost(model_id: str, num_clips: int) -> float:
    model_info = CHINESE_MODELS.get(model_id, {})
    return model_info.get("cost_per_clip_usd", 0.02) * num_clips


def select_cheapest_model(
    visual_complexity: str,
    needs_character_consistency: bool = False,
    needs_cinematic: bool = False,
) -> str:
    if needs_character_consistency:
        return "seedance2_opensource"
    if needs_cinematic:
        return "hunyuan_video"
    return "wan2_7_opensource"
