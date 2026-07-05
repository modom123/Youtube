"""
Higgsfield MCP HTTP client for the Social Optimize pipeline.

Connects to https://mcp.higgsfield.ai/mcp using the MCP Streamable HTTP
transport to generate AI video and image clips without leaving the pipeline.
Authentication uses HIGGSFIELD_MCP_TOKEN.
"""
import json
import re
import time
import threading
import requests
from pathlib import Path
from typing import Callable, Optional
import config

# Per-thread Higgsfield token override (set by app.py thread functions)
_session_token: threading.local = threading.local()

MCP_URL = config.HIGGSFIELD_MCP_URL
_PROTO_VERSION = "2024-11-05"


def resolve_token() -> str:
    """Effective Higgsfield MCP token for the current request/thread.

    Higgsfield has no REST API key — access is the OAuth/MCP bearer token, set
    per-user into ``_session_token`` (from the Accounts-page OAuth connection)
    with the ``HIGGSFIELD_MCP_TOKEN`` env var as a global fallback. Returns ""
    when nothing is connected. Accidental URL pastes are ignored.
    """
    tok = getattr(_session_token, "value", None) or config.HIGGSFIELD_MCP_TOKEN or ""
    if tok.startswith("http://") or tok.startswith("https://"):
        tok = ""
    return tok


def has_platform_credentials() -> bool:
    """True when Higgsfield Platform API key+secret are set (used by the SDK)."""
    return bool(getattr(config, "HIGGSFIELD_API_CREDENTIAL", ""))


def is_connected() -> bool:
    """True when Higgsfield is reachable — MCP token (OAuth session or env) OR
    Platform API key+secret."""
    return bool(resolve_token()) or has_platform_credentials()


def _token() -> str:
    tok = resolve_token()
    if not tok:
        raise RuntimeError(
            "Higgsfield not connected. Go to Accounts page and click 'Connect Higgsfield' "
            "to authenticate via OAuth — no API key needed."
        )
    return tok


def has_key() -> bool:
    """True if this thread has a connected user's token OR the global system
    token is configured OR Platform API key+secret are set. Callers must check
    this instead of config.HIGGSFIELD_MCP_TOKEN directly -- otherwise a customer
    who connected their own Higgsfield account still gets skipped whenever the
    system-wide token isn't set."""
    tok = getattr(_session_token, "value", None) or config.HIGGSFIELD_MCP_TOKEN or ""
    return (bool(tok) and not tok.startswith(("http://", "https://"))) or has_platform_credentials()


# ── Platform API (key+secret) image generation via the higgsfield-client SDK ──

_SDK_IMAGE_PATHS = {
    "seedream_4":      "bytedance/seedream/v4/text-to-image",
    "seedream":        "bytedance/seedream/v4/text-to-image",
    "flux_2":          "flux-pro/kontext/max/text-to-image",
    "flux":            "flux-pro/kontext/max/text-to-image",
    "nano_banana_pro": "google/nano-banana/text-to-image",
    "nano_banana":     "google/nano-banana/text-to-image",
}
# Documented, broadly-available default — used when the requested model has no
# known SDK path or its path fails.
_SDK_DEFAULT_IMAGE_PATH = "bytedance/seedream/v4/text-to-image"


def _extract_image_url(result) -> Optional[str]:
    """Pull an image URL out of the higgsfield-client SDK result (dict or obj)."""
    try:
        if isinstance(result, dict):
            imgs = result.get("images") or result.get("output") or []
            if imgs and isinstance(imgs[0], dict):
                return imgs[0].get("url")
            return result.get("url") or result.get("image_url")
        url = getattr(result, "url", None)
        if url:
            return url
        imgs = getattr(result, "images", None)
        if imgs and hasattr(imgs[0], "url"):
            return imgs[0].url
    except Exception:
        pass
    return None


def generate_image_via_sdk(
    prompt: str,
    output_path: Path,
    model_id: str = "seedream_4",
    aspect_ratio: str = "1:1",
    resolution: str = "2K",
) -> Optional[Path]:
    """Generate an image via the higgsfield-client SDK using Platform API
    key+secret (HF_API_KEY/HF_API_SECRET). Returns the path or None.

    Tries the requested model's SDK path, then falls back to the documented
    default so a wrong/unavailable model id still produces an image.
    """
    if not has_platform_credentials():
        return None
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import higgsfield_client as hf
    except Exception as e:
        print(f"[higgsfield_sdk] higgsfield-client not installed: {e}")
        return None

    paths = []
    mapped = _SDK_IMAGE_PATHS.get(model_id)
    if mapped:
        paths.append(mapped)
    if _SDK_DEFAULT_IMAGE_PATH not in paths:
        paths.append(_SDK_DEFAULT_IMAGE_PATH)

    for path in paths:
        try:
            result = hf.subscribe(path, arguments={
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "camera_fixed": False,
            })
            url = _extract_image_url(result)
            if url:
                _download(url, output_path)
                if output_path.exists() and output_path.stat().st_size > 1_000:
                    print(f"[higgsfield_sdk] image via {path}")
                    return output_path
            print(f"[higgsfield_sdk] {path} returned no image url")
        except Exception as e:
            print(f"[higgsfield_sdk] {path} failed: {e}")
    return None


_SDK_VIDEO_PATHS = {
    "kling3_0":                  "kling/v3/video/text-to-video",
    "kling3_0_turbo":            "kling/v3/video/text-to-video-turbo",
    "kling2_6":                  "kling/v2.6/video/text-to-video",
    "wan2_7":                    "wan/v2.7/video/text-to-video",
    "wan2_6":                    "wan/v2.6/video/text-to-video",
    "seedance_2_0":              "bytedance/seedance/v2/text-to-video",
    "seedance_1_5":              "bytedance/seedance/v1.5/text-to-video",
    "cinematic_studio_3_0":      "higgsfield/cinematic-studio/v3/text-to-video",
    "cinematic_studio_video_v2": "higgsfield/cinematic-studio/v2/text-to-video",
    "minimax_hailuo":            "minimax/hailuo/v2.3/text-to-video",
}
_SDK_DEFAULT_VIDEO_PATH = "bytedance/seedance/v2/text-to-video"


def _extract_video_url(result) -> Optional[str]:
    """Pull a video URL out of the higgsfield-client SDK result (dict or obj)."""
    try:
        if isinstance(result, dict):
            for key in ("videos", "clips", "output"):
                v = result.get(key)
                if v and isinstance(v[0], dict):
                    return v[0].get("url")
            return result.get("url") or result.get("video_url") or result.get("download_url")
        url = getattr(result, "url", None)
        if url:
            return url
        vids = getattr(result, "videos", None)
        if vids and hasattr(vids[0], "url"):
            return vids[0].url
    except Exception:
        pass
    return None


def generate_clips_via_sdk(
    prompts: list,
    output_dir: Path,
    model_id: str = "kling3_0",
    aspect_ratio: str = "16:9",
    duration: int = 5,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list:
    """Generate video clips via the higgsfield-client SDK (Platform API
    key+secret). Returns downloaded .mp4 paths. Errors per clip, never raises."""
    if not has_platform_credentials():
        return []
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import higgsfield_client as hf
    except Exception as e:
        print(f"[higgsfield_sdk] higgsfield-client not installed: {e}")
        return []

    mapped = _SDK_VIDEO_PATHS.get(model_id, _SDK_DEFAULT_VIDEO_PATH)
    paths = [mapped] + ([_SDK_DEFAULT_VIDEO_PATH] if mapped != _SDK_DEFAULT_VIDEO_PATH else [])
    results = []
    for i, prompt in enumerate(prompts):
        if cancel_check and cancel_check():
            print(f"[higgsfield_sdk] Cancelled before clip {i+1}/{len(prompts)}")
            break
        for path in paths:
            try:
                result = hf.subscribe(path, arguments={
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "duration": duration,
                })
                url = _extract_video_url(result)
                if url:
                    out = output_dir / f"sdk_{model_id}_{i:02d}.mp4"
                    _download(url, out)
                    if out.exists() and out.stat().st_size > 10_000:
                        results.append(out)
                        print(f"[higgsfield_sdk] clip {i+1} via {path}")
                        break
            except Exception as e:
                print(f"[higgsfield_sdk] video {path} failed: {e}")
    return results


# ── Unified entry points: Platform SDK (key+secret) first, MCP fallback ────────

def generate_image(prompt, output_path, model_id="flux_2", aspect_ratio="1:1", **kw) -> Optional[Path]:
    """Generate one image — Higgsfield Platform SDK (key+secret) first, then the
    MCP/OAuth endpoint. Every studio should call this."""
    if has_platform_credentials():
        r = generate_image_via_sdk(prompt, output_path, model_id=model_id, aspect_ratio=aspect_ratio)
        if r:
            return r
        print("[higgsfield] Platform SDK image failed — falling back to MCP")
    return generate_image_via_mcp(prompt, output_path, model_id=model_id, aspect_ratio=aspect_ratio)


def generate_clips(prompts, output_dir, model_id="kling3_0", aspect_ratio="16:9",
                   duration=5, max_poll=600, cancel_check: Optional[Callable[[], bool]] = None, **kw) -> list:
    """Generate video clips — Higgsfield Platform SDK (key+secret) first, then the
    MCP/OAuth endpoint. Every studio should call this."""
    if cancel_check and cancel_check():
        return []
    if has_platform_credentials():
        clips = generate_clips_via_sdk(prompts, output_dir, model_id=model_id,
                                       aspect_ratio=aspect_ratio, duration=duration,
                                       cancel_check=cancel_check)
        if clips:
            return clips
        if cancel_check and cancel_check():
            return []
        print("[higgsfield] Platform SDK video failed — falling back to MCP")
    return generate_clips_via_mcp(prompts, output_dir, model_id=model_id,
                                  aspect_ratio=aspect_ratio, duration=duration, max_poll=max_poll,
                                  cancel_check=cancel_check)


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


def _find_upload_url(text: str) -> Optional[str]:
    for pat in [
        r'"upload_url"\s*:\s*"(https?://[^"]+)"',
        r'"url"\s*:\s*"(https?://[^"]+)"',
        r'"presigned_url"\s*:\s*"(https?://[^"]+)"',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _find_media_id(text: str) -> Optional[str]:
    for pat in [
        r'"media_id"\s*:\s*"([^"]+)"',
        r'"id"\s*:\s*"([a-f0-9]{8}-[a-f0-9-]{27,})"',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def upload_media_via_mcp(session: "_MCPSession", file_path: Path, media_type: str) -> Optional[str]:
    """Upload a local file (image/video/audio) to Higgsfield storage and
    return a confirmed media_id, or None on failure. media_type is one of
    'image' | 'video' | 'audio'."""
    file_path = Path(file_path)
    content_types = {
        "video": "video/mp4", "image": "image/jpeg", "audio": "audio/mpeg",
    }
    try:
        up = session.call("media_upload", {
            "filename": file_path.name,
            "content_type": content_types.get(media_type, "application/octet-stream"),
        })
        up_text = _text(up)
        upload_url = _find_upload_url(up_text)
        media_id = _find_media_id(up_text)
        if not upload_url or not media_id:
            print(f"[higgsfield_mcp] media_upload response missing upload_url/media_id: {up_text[:300]}")
            return None

        put_resp = requests.put(upload_url, data=file_path.read_bytes(), timeout=300)
        put_resp.raise_for_status()

        confirm = session.call("media_confirm", {"media_id": media_id, "type": media_type})
        confirm_text = _text(confirm)
        if any(s in confirm_text.lower() for s in ("error", "failed")):
            print(f"[higgsfield_mcp] media_confirm failed: {confirm_text[:300]}")
            return None
        return media_id
    except Exception as e:
        print(f"[higgsfield_mcp] Media upload failed: {e}")
        return None


def generate_dubbing_via_mcp(
    video_path: Path,
    target_language: str,
    output_path: Path,
    max_poll: int = 600,
) -> Optional[Path]:
    """Dub a local video into another language via the Higgsfield MCP
    'dubbing' tool. Uploads the video, submits the dubbing job, polls until
    done, and downloads the result. target_language must be one of the MCP
    dubbing tool's 3-letter codes (eng, cmn, fra, hin, ita, jpn, kor, por,
    rus, tur, spa, deu, ara, pol, ind, fil, swe, fin). Returns the downloaded
    path, or None on failure -- never raises."""
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    session = _MCPSession()
    try:
        session.initialize()
    except Exception as e:
        print(f"[higgsfield_mcp] Session init failed: {e}")
        return None

    media_id = upload_media_via_mcp(session, video_path, "video")
    if not media_id:
        return None

    try:
        gen = session.call("dubbing", {
            "params": {"video_id": media_id, "target_language": target_language}
        })
        text = _text(gen)

        video_url = _find_video_url(text)
        if not video_url:
            job_id = _find_job_id(text)
            if not job_id:
                print(f"[higgsfield_mcp] Dubbing: no job_id in response: {text[:300]}")
                return None
            elapsed, wait = 0, 15
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
                        print(f"[higgsfield_mcp] Dubbing job {job_id} failed")
                        return None
                except Exception as pe:
                    print(f"[higgsfield_mcp] Dubbing poll error: {pe}")

        if not video_url:
            print(f"[higgsfield_mcp] Dubbing timed out after {max_poll}s")
            return None

        _download(video_url, output_path)
        if output_path.exists() and output_path.stat().st_size > 10_000:
            return output_path
        return None
    except Exception as e:
        print(f"[higgsfield_mcp] Dubbing error: {e}")
        return None


# ── public API ────────────────────────────────────────────────────────────────

def generate_clips_via_mcp(
    prompts: list[str],
    output_dir: Path,
    model_id: str = "kling3_0",
    aspect_ratio: str = "16:9",
    duration: int = 5,
    max_poll: int = 600,
    cancel_check: Optional[Callable[[], bool]] = None,
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
        if cancel_check and cancel_check():
            print(f"[higgsfield_mcp] Cancelled before clip {i+1}/{len(prompts)}")
            break
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
                if cancel_check and cancel_check():
                    print(f"[higgsfield_mcp] Cancelled while polling job {job_id}")
                    break
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


def _find_image_url(text: str) -> Optional[str]:
    for pat in [
        r'"url"\s*:\s*"(https://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"(?:image_url|download_url|output_url)"\s*:\s*"(https://[^"]+)"',
        r'(https://\S+\.(?:jpg|jpeg|png|webp)(?:\?\S*)?)',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def generate_image_via_mcp(
    prompt: str,
    output_path: Path,
    model_id: str = "flux_2",
    aspect_ratio: str = "16:9",
    max_poll: int = 240,
) -> Optional[Path]:
    """Generate a single image via Higgsfield MCP. Returns path or None.

    Handles both inline results (URL returned immediately) and async jobs
    (a job id that must be polled via job_display) — the latter is what FLUX.2
    and other higher-quality models return, and not polling for it was making
    the Image Studio report 'returned nothing / not connected'.
    """
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

        # 1. Inline URL → done immediately.
        url = _find_image_url(text)
        if url:
            _download(url, output_path)
            if output_path.exists() and output_path.stat().st_size > 1_000:
                return output_path

        # 2. Otherwise poll the job until the image is ready.
        job_id = _find_job_id(text)
        if not job_id:
            print(f"[higgsfield_mcp] Image gen: no URL or job id in response — {text[:200]}")
            return None

        elapsed, wait = 0, 8
        while elapsed < max_poll:
            time.sleep(wait)
            elapsed += wait
            try:
                poll = session.call("job_display", {"id": job_id})
                pt = _text(poll)
                url = _find_image_url(pt)
                if url:
                    _download(url, output_path)
                    if output_path.exists() and output_path.stat().st_size > 1_000:
                        return output_path
                if any(s in pt for s in ('"failed"', '"error"', '"cancelled"')):
                    print(f"[higgsfield_mcp] Image job {job_id} failed — {pt[:200]}")
                    return None
            except Exception as pe:
                print(f"[higgsfield_mcp] Image poll error: {pe}")
        print(f"[higgsfield_mcp] Image job {job_id} timed out after {max_poll}s")
    except Exception as e:
        print(f"[higgsfield_mcp] Image gen error: {e}")
    return None


# ── Billing / balance ──────────────────────────────────────────────────────────

def get_balance() -> Optional[dict]:
    """Return {'credits': float, 'subscription_plan_type': str} or None on failure."""
    session = _MCPSession()
    try:
        session.initialize()
        result = session.call("balance", {})
        text = _text(result)
        return json.loads(text)
    except Exception as e:
        print(f"[higgsfield_mcp] Balance check failed: {e}")
        return None


def get_transactions(size: int = 50) -> Optional[list]:
    """Return recent Higgsfield credit transactions (newest first), or None on failure."""
    session = _MCPSession()
    try:
        session.initialize()
        result = session.call("transactions", {"size": size})
        text = _text(result)
        data = json.loads(text)
        return data.get("items", [])
    except Exception as e:
        print(f"[higgsfield_mcp] Transactions fetch failed: {e}")
        return None


# ── Text-to-speech (Higgsfield Audio) — fallback voice when ElevenLabs is down ──
# MCP schema: generate_audio(params={model:"seed_audio", prompt, voice_type:"preset",
# voice_id}) with voice ids from list_voices. Never a computer voice.

def _find_audio_url(text: str) -> Optional[str]:
    for pat in [
        r'"url"\s*:\s*"(https://[^"]+\.(?:mp3|wav|m4a|ogg|aac)[^"]*)"',
        r'"(?:audio_url|download_url|output_url)"\s*:\s*"(https://[^"]+)"',
        r'(https://\S+\.(?:mp3|wav|m4a|ogg)(?:\?\S*)?)',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _find_voice_pair(text: str, gender: str = "") -> tuple:
    """Pick a (voice_id, voice_type) from a list_voices result, gender-matched if
    the gender appears near the id."""
    pairs = re.findall(
        r'"voice_id"\s*:\s*"([^"]+)"[^}]*?"voice_type"\s*:\s*"(preset|element)"', text)
    if not pairs:
        vid = re.search(r'"voice_id"\s*:\s*"([^"]+)"', text)
        if vid:
            return vid.group(1), "preset"
        return None, None
    g = (gender or "").lower()
    if g:
        for vid, vtype in pairs:
            window = text[max(0, text.find(vid) - 200): text.find(vid) + 200].lower()
            if g in window:
                return vid, vtype
    return pairs[0][0], pairs[0][1]


def _concat_audio(parts: list, out: Path) -> None:
    import imageio_ffmpeg, tempfile, shutil
    if len(parts) == 1:
        shutil.copy(parts[0], out)
        return
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "c.txt"
        lst.write_text("\n".join(f"file '{p}'" for p in parts))
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        try:
            subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", str(out)], capture_output=True, timeout=180)
        except Exception:
            out.write_bytes(b"".join(Path(p).read_bytes() for p in parts))


def generate_speech_via_mcp(text: str, output_path: Path, gender: str = "",
                            max_poll: int = 180) -> Optional[Path]:
    """Higgsfield TTS via the MCP endpoint (needs an MCP/OAuth token)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    session = _MCPSession()
    try:
        session.initialize()
    except Exception as e:
        print(f"[higgsfield_audio] MCP session failed: {e}")
        return None
    try:
        vres = session.call("list_voices", {"size": 100})
        vid, vtype = _find_voice_pair(_text(vres), gender)
    except Exception as e:
        print(f"[higgsfield_audio] list_voices failed: {e}")
        return None
    if not vid:
        print("[higgsfield_audio] no preset voice available")
        return None

    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)] or [text]
    parts = []
    for i, ch in enumerate(chunks):
        if not ch.strip():
            continue
        try:
            gen = session.call("generate_audio", {"params": {
                "model": "seed_audio", "prompt": ch,
                "voice_type": vtype, "voice_id": vid}})
            gt = _text(gen)
            url = _find_audio_url(gt)
            if not url:
                jid = _find_job_id(gt)
                elapsed, wait = 0, 6
                while jid and not url and elapsed < max_poll:
                    time.sleep(wait); elapsed += wait
                    pt = _text(session.call("job_display", {"id": jid}))
                    url = _find_audio_url(pt)
                    if any(s in pt for s in ('"failed"', '"error"', '"cancelled"')):
                        break
            if url:
                p = output_path.parent / f"_hfspeech_{i:03d}.mp3"
                _download(url, p)
                if p.exists() and p.stat().st_size > 500:
                    parts.append(str(p))
        except Exception as e:
            print(f"[higgsfield_audio] chunk {i} failed: {e}")
    if not parts:
        return None
    _concat_audio(parts, output_path)
    for p in parts:
        try:
            Path(p).unlink()
        except Exception:
            pass
    ok = output_path.exists() and output_path.stat().st_size > 500
    if ok:
        print(f"[higgsfield_audio] speech via MCP seed_audio ({len(parts)} chunk(s))")
    return output_path if ok else None


def generate_speech_via_sdk(text: str, output_path: Path, gender: str = "") -> Optional[Path]:
    """Higgsfield TTS via the Platform SDK (key+secret). Best-effort — tries the
    text2speech model paths; returns None if the SDK can't do it."""
    if not has_platform_credentials():
        return None
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import higgsfield_client as hf
    except Exception as e:
        print(f"[higgsfield_audio] SDK not installed: {e}")
        return None
    for model in ("text2speech_v2", "seed_audio"):
        try:
            args = {"prompt": text}
            if model == "text2speech_v2":
                args["variant"] = "elevenlabs"
            result = hf.subscribe(model, arguments=args)
            url = _find_audio_url(str(result))
            if not url and isinstance(result, dict):
                for k in ("audio", "output", "result"):
                    v = result.get(k)
                    if isinstance(v, dict) and v.get("url"):
                        url = v["url"]; break
                url = url or result.get("url")
            if url:
                _download(url, output_path)
                if output_path.exists() and output_path.stat().st_size > 500:
                    print(f"[higgsfield_audio] speech via SDK {model}")
                    return output_path
        except Exception as e:
            print(f"[higgsfield_audio] SDK {model} failed: {e}")
    return None


def generate_speech(text: str, output_path: Path, gender: str = "", **kw) -> Optional[Path]:
    """Higgsfield TTS fallback (real voice, not a computer voice):
    Platform SDK (key+secret) first, then the MCP endpoint. Returns None if
    Higgsfield can't produce speech (caller then errors rather than going robotic)."""
    if has_platform_credentials():
        r = generate_speech_via_sdk(text, output_path, gender=gender)
        if r:
            return r
    if resolve_token():
        return generate_speech_via_mcp(text, output_path, gender=gender)
    return None
