"""
Higgsfield CLI wrapper — generates video clips via the `higgsfield` CLI binary.
Seeds credentials from HIGGSFIELD_MCP_TOKEN into ~/.config/higgsfield/credentials.json
so the CLI can run non-interactively on servers.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests
import config

_CRED_FILE = Path.home() / ".config" / "higgsfield" / "credentials.json"
_SEEDED = False  # seed once per process


def _seed_credentials() -> bool:
    """Write bearer token to CLI credential file. Returns True if token available."""
    global _SEEDED
    if _SEEDED:
        return _CRED_FILE.exists()

    token = config.HIGGSFIELD_MCP_TOKEN
    if not token:
        return False

    _CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CRED_FILE.write_text(
        json.dumps({"access_token": token, "token_type": "Bearer"})
    )
    _SEEDED = True
    return True


def _run_cli(*args: str, timeout: int = 30) -> Optional[dict]:
    """Run `higgsfield <args> --json` and return parsed JSON output, or None on error."""
    if not _seed_credentials():
        return None
    try:
        result = subprocess.run(
            ["higgsfield", *args, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"[hf-cli] Error: {result.stderr.strip()}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"[hf-cli] CLI call failed: {e}")
        return None


def generate_clips_via_cli(
    prompts: list[str],
    output_dir: Path,
    model_id: str = "kling3_0",
    aspect_ratio: str = "16:9",
    duration: int = 5,
    wait_timeout: str = "15m",
) -> list[Path]:
    """
    Generate video clips using the Higgsfield CLI.
    Uses --wait so each call blocks until the job completes and returns the URL.
    Returns list of downloaded .mp4 paths.
    """
    if not _seed_credentials():
        print("[hf-cli] No Higgsfield token — skipping CLI generation")
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, prompt in enumerate(prompts):
        print(f"[hf-cli:{model_id}] Clip {i+1}/{len(prompts)}: {prompt[:60]}...")
        try:
            result = subprocess.run(
                [
                    "higgsfield", "generate", "create", model_id,
                    "--prompt", prompt,
                    "--aspect-ratio", aspect_ratio,
                    "--duration", str(duration),
                    "--wait",
                    "--wait-timeout", wait_timeout,
                    "--wait-interval", "10s",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=int(wait_timeout.rstrip("m")) * 60 + 30,
            )

            if result.returncode != 0:
                print(f"[hf-cli] Clip {i+1} failed: {result.stderr.strip()[:200]}")
                continue

            data = json.loads(result.stdout)
            url = _extract_url(data)
            if not url:
                print(f"[hf-cli] Clip {i+1}: no URL in response: {str(data)[:200]}")
                continue

            out_path = output_dir / f"hfcli_{model_id}_{i:02d}.mp4"
            _download(url, out_path)
            if out_path.exists() and out_path.stat().st_size > 10_000:
                results.append(out_path)
                print(f"[hf-cli] ✓ Clip {i+1} saved: {out_path.name}")

        except subprocess.TimeoutExpired:
            print(f"[hf-cli] Clip {i+1} timed out after {wait_timeout}")
        except (json.JSONDecodeError, Exception) as e:
            print(f"[hf-cli] Clip {i+1} error: {e}")

    return results


def submit_clip_async(
    prompt: str,
    model_id: str = "kling3_0",
    aspect_ratio: str = "16:9",
    duration: int = 5,
) -> Optional[str]:
    """Submit a generation job without waiting. Returns job_id or None."""
    if not _seed_credentials():
        return None
    try:
        result = subprocess.run(
            [
                "higgsfield", "generate", "create", model_id,
                "--prompt", prompt,
                "--aspect-ratio", aspect_ratio,
                "--duration", str(duration),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[hf-cli] Submit failed: {result.stderr.strip()[:200]}")
            return None
        data = json.loads(result.stdout)
        return data.get("id") or data.get("job_id")
    except Exception as e:
        print(f"[hf-cli] Submit error: {e}")
        return None


def poll_job(job_id: str, timeout_seconds: int = 900) -> Optional[str]:
    """Poll a submitted job until done. Returns video URL or None."""
    if not _seed_credentials():
        return None

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["higgsfield", "generate", "get", job_id, "--json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                time.sleep(15)
                continue
            data = json.loads(result.stdout)
            status = (data.get("status") or "").lower()
            if status in ("completed", "done", "succeeded"):
                return _extract_url(data)
            elif status in ("failed", "error", "cancelled"):
                print(f"[hf-cli] Job {job_id} ended with status: {status}")
                return None
            time.sleep(15)
        except Exception as e:
            print(f"[hf-cli] Poll error: {e}")
            time.sleep(15)

    print(f"[hf-cli] Job {job_id} timed out after {timeout_seconds}s")
    return None


def list_models(model_type: str = "video") -> Optional[list]:
    """List available models. Returns list or None if unauthenticated."""
    data = _run_cli("model", "list", f"--{model_type}")
    if data is None:
        return None
    if isinstance(data, list):
        return data
    return data.get("models") or data.get("items") or []


def is_authenticated() -> bool:
    """Check if CLI credentials are seeded and valid (fast check)."""
    return _seed_credentials() and _CRED_FILE.exists()


def _extract_url(data: dict) -> Optional[str]:
    """Extract video URL from various CLI response shapes."""
    if not isinstance(data, dict):
        return None
    for key in ("url", "output_url", "video_url", "download_url"):
        if val := data.get(key):
            return val
    result = data.get("result") or data.get("output") or {}
    if isinstance(result, dict):
        for key in ("url", "video_url", "output_url"):
            if val := result.get(key):
                return val
    items = data.get("items") or data.get("outputs") or []
    if isinstance(items, list) and items:
        item = items[0]
        if isinstance(item, dict):
            return item.get("url") or item.get("video_url")
    return None


def _download(url: str, out_path: Path) -> None:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
