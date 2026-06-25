"""
Higgsfield MCP HTTP client for the Social Optimize pipeline.

Connects to https://mcp.higgsfield.ai/mcp using the MCP Streamable HTTP
transport to generate AI video and image clips without leaving the pipeline.
Authentication uses HIGGSFIELD_MCP_TOKEN.
"""
import json
import re
import time
import requests
from pathlib import Path
from typing import Optional
import config


MCP_URL = config.HIGGSFIELD_MCP_URL
_PROTO_VERSION = "2024-11-05"


def _token() -> str:
    tok = config.HIGGSFIELD_MCP_TOKEN
    if not tok:
        raise RuntimeError("Set HIGGSFIELD_MCP_TOKEN in .env")
    return tok


class _MCPSession:
    """Minimal MCP over Streamable HTTP session."""

    def __init__(self):
        self._sid: Optional[str] = None
        self._rid = 0

    # ── transport ──────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._sid:
            h["Mcp-Session-Id"] = self._sid
        return h

    def _post(self, payload: dict, *, notification: bool = False) -> Optional[dict]:
        if not notification:
            self._rid += 1
            payload["id"] = self._rid
        resp = requests.post(
            MCP_URL,
            headers=self._headers(),
            json=payload,
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._sid = sid
        if notification:
            return None
        ct = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ct:
            for raw in resp.iter_lines():
                if raw and raw.startswith(b"data: "):
                    return json.loads(raw[6:])
            return {}
        return resp.json()

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def initialize(self):
        self._post({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTO_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "social-optimize", "version": "1.0"},
            },
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notification=True)

    # ── tool call ──────────────────────────────────────────────────────────────

    def call(self, name: str, arguments: dict) -> dict:
        resp = self._post({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if not resp:
            return {}
        if "error" in resp:
            raise RuntimeError(f"MCP {name} error: {resp['error']}")
        return resp.get("result", {})


# ── helpers ───────────────────────────────────────────────────────────────────

def _text(result: dict) -> str:
    return "\n".join(
        item.get("text", "")
        for item in result.get("content", [])
        if item.get("type") == "text"
    )


def _find_job_id(text: str) -> Optional[str]:
    for pat in [
        r'"id"\s*:\s*"([a-f0-9]{8}-[a-f0-9-]{27,})"',  # UUID
        r'"id"\s*:\s*"([A-Za-z0-9_-]{12,})"',
        r'"job_id"\s*:\s*"([^"]+)"',
        r'[Jj]ob[\s_-]?[Ii][Dd][\s:=]+([A-Za-z0-9_-]{8,})',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _find_video_url(text: str) -> Optional[str]:
    for pat in [
        r'"url"\s*:\s*"(https://[^"]+\.mp4[^"]*)"',
        r'(https://\S+\.mp4(?:\?\S*)?)',
        r'"download_url"\s*:\s*"(https://[^"]+)"',
        r'"video_url"\s*:\s*"(https://[^"]+)"',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _download(url: str, path: Path) -> None:
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)


# ── public API ────────────────────────────────────────────────────────────────

def generate_clips_via_mcp(
    prompts: list[str],
    output_dir: Path,
    model_id: str = "kling3_0",
    aspect_ratio: str = "16:9",
    duration: int = 5,
    max_poll: int = 600,
) -> list[Path]:
    """
    Generate video clips via the Higgsfield MCP endpoint.
    Returns list of downloaded .mp4 paths on success.
    Falls back gracefully — errors per clip, never raises.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = _MCPSession()
    try:
        session.initialize()
    except Exception as e:
        print(f"[higgsfield_mcp] Session init failed: {e}")
        return []

    results: list[Path] = []

    for i, prompt in enumerate(prompts):
        print(f"[higgsfield_mcp:{model_id}] Clip {i+1}/{len(prompts)}: {prompt[:60]}...")
        try:
            gen = session.call("generate_video", {
                "params": {
                    "model": model_id,
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "duration": duration,
                }
            })
            text = _text(gen)

            # Immediate URL → generation completed inline
            url = _find_video_url(text)
            if url:
                out = output_dir / f"mcp_{model_id}_{i:02d}.mp4"
                _download(url, out)
                if out.stat().st_size > 10_000:
                    results.append(out)
                    print(f"[higgsfield_mcp] ✓ Clip {i+1} instant")
                continue

            # Otherwise poll via job_display
            job_id = _find_job_id(text)
            if not job_id:
                print(f"[higgsfield_mcp] No job_id for clip {i+1}, skipping")
                continue

            print(f"[higgsfield_mcp] Polling job {job_id} …")
            elapsed, wait = 0, 15
            video_url: Optional[str] = None
            while elapsed < max_poll:
                time.sleep(wait)
                elapsed += wait
                try:
                    poll = session.call("job_display", {"id": job_id})
                    pt = _text(poll)
                    video_url = _find_video_url(pt)
                    if video_url:
                        break
                    if any(s in pt for s in ('"failed"', '"error"', '"cancelled"')):
                        print(f"[higgsfield_mcp] Job {job_id} failed")
                        break
                except Exception as pe:
                    print(f"[higgsfield_mcp] Poll error: {pe}")

            if video_url:
                out = output_dir / f"mcp_{model_id}_{i:02d}.mp4"
                _download(video_url, out)
                if out.exists() and out.stat().st_size > 10_000:
                    results.append(out)
                    print(f"[higgsfield_mcp] ✓ Clip {i+1}: {out.name}")
            else:
                print(f"[higgsfield_mcp] Clip {i+1} timed out")

        except Exception as e:
            print(f"[higgsfield_mcp] Clip {i+1} error: {e}")

    return results


def generate_image_via_mcp(
    prompt: str,
    output_path: Path,
    model_id: str = "nano_banana_pro",
    aspect_ratio: str = "16:9",
) -> Optional[Path]:
    """Generate a single image via Higgsfield MCP. Returns path or None."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    session = _MCPSession()
    try:
        session.initialize()
        result = session.call("generate_image", {
            "params": {
                "model": model_id,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
            }
        })
        text = _text(result)
        # Look for image URL
        for pat in [
            r'"url"\s*:\s*"(https://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
            r'(https://\S+\.(?:jpg|jpeg|png|webp)(?:\?\S*)?)',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                _download(m.group(1), output_path)
                if output_path.exists() and output_path.stat().st_size > 1_000:
                    return output_path
    except Exception as e:
        print(f"[higgsfield_mcp] Image gen error: {e}")
    return None
