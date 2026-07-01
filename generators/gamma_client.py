"""
Gamma API client — real REST API (https://developers.gamma.app), not the
MCP tool (which is only available in interactive chat sessions, not to this
deployed server).

Used to generate slide decks for ranking/listicle-style video content:
generate a deck, export it as one PNG per card, then feed those images into
a video assembly pipeline alongside per-slide narration.
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests

import config

logger_prefix = "[gamma_client]"


def _headers() -> dict:
    if not config.GAMMA_API_KEY:
        raise RuntimeError("GAMMA_API_KEY is not configured")
    return {
        "X-API-KEY": config.GAMMA_API_KEY,
        "Content-Type": "application/json",
    }


def create_generation(
    input_text: str,
    num_cards: int = 10,
    format: str = "presentation",
    text_mode: str = "generate",
    card_split: str = "auto",
    export_as: str = "png",
    theme: Optional[str] = None,
) -> str:
    """Start a Gamma generation. Returns the generationId."""
    payload = {
        "inputText": input_text,
        "numCards": num_cards,
        "format": format,
        "textMode": text_mode,
        "cardSplit": card_split,
        "exportAs": export_as,
    }
    if theme:
        payload["themeName"] = theme

    resp = requests.post(
        f"{config.GAMMA_API_BASE}/generations",
        headers=_headers(),
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    generation_id = data.get("generationId")
    if not generation_id:
        raise RuntimeError(f"Gamma generation did not return a generationId: {data}")
    return generation_id


def poll_generation(generation_id: str, max_wait: int = 300, interval: int = 5) -> dict:
    """Poll until the generation completes or fails. Returns the final response dict."""
    elapsed = 0
    while elapsed < max_wait:
        resp = requests.get(
            f"{config.GAMMA_API_BASE}/generations/{generation_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "completed":
            return data
        if status == "failed":
            raise RuntimeError(f"Gamma generation {generation_id} failed: {data}")
        time.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Gamma generation {generation_id} did not complete within {max_wait}s")


def download_slide_images(result: dict, output_dir: Path) -> list[Path]:
    """Download the exported PNG zip and extract one image per slide,
    in card order. Returns sorted list of image paths."""
    download_url = (
        result.get("exportUrl")
        or result.get("downloadUrl")
        or (result.get("export") or {}).get("url")
    )
    if not download_url:
        raise RuntimeError(f"Gamma generation result has no export download URL: {result}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resp = requests.get(download_url, timeout=120)
    resp.raise_for_status()

    images: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith((".png", ".jpg", ".jpeg")))
        for i, name in enumerate(names):
            out_path = output_dir / f"slide_{i:03d}{Path(name).suffix}"
            with zf.open(name) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
            images.append(out_path)

    if not images:
        raise RuntimeError("Gamma export zip contained no image files")
    return images


def generate_slide_deck(
    input_text: str,
    output_dir: Path,
    num_cards: int = 10,
    theme: Optional[str] = None,
    max_wait: int = 300,
) -> list[Path]:
    """End-to-end: create a Gamma generation, wait for it, download the
    per-slide PNGs. Returns ordered list of image paths."""
    generation_id = create_generation(input_text, num_cards=num_cards, theme=theme)
    result = poll_generation(generation_id, max_wait=max_wait)
    return download_slide_images(result, output_dir)
