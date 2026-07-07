"""
MusicEngine — AI song production via Suno → Replicate MusicGen → ElevenLabs cascade.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

import requests
from pydantic import BaseModel

import config
from generators.studio_blueprints import get_blueprint
from generators.studio_intelligence import record_job, get_recommendations
from generators.agents.base import BaseAgent

log = logging.getLogger(__name__)


# ── Lyrics schema ─────────────────────────────────────────────────────────────

class SongLyrics(BaseModel):
    title: str
    verse1: str
    chorus: str
    verse2: str
    bridge: str
    outro: str
    full_lyrics: str


# ── Lyrics Agent ──────────────────────────────────────────────────────────────

class LyricsAgent(BaseAgent):
    name = "LyricsAgent"
    model = "claude-sonnet-4-6"
    max_tokens = 2048
    system_prompt = (
        "You are a world-class songwriter and lyricist with decades of experience "
        "writing hits across every genre. You craft emotionally resonant, memorable "
        "lyrics that feel authentic to the requested style. You understand rhyme scheme, "
        "meter, syllable flow, and hook construction. Write lyrics that could actually "
        "become chart-topping songs — vivid imagery, strong metaphors, catchy hooks."
    )

    def run(
        self,
        title: str,
        genre: str,
        mood: str,
        vocal_style: str,
        reference_artist: str = "",
    ) -> SongLyrics:
        ref_note = f" in the style of {reference_artist}" if reference_artist else ""
        prompt = (
            f"Write complete song lyrics for a {genre} track{ref_note}.\n"
            f"Title: {title}\n"
            f"Mood: {mood}\n"
            f"Vocal style: {vocal_style}\n\n"
            "Structure: verse1, chorus, verse2, bridge, outro, and full_lyrics (all parts assembled).\n"
            "Make it feel authentic, emotional, and ready for production."
        )
        return self._call(prompt, SongLyrics)


# ── Provider helpers ───────────────────────────────────────────────────────────

def _download(url: str, dest: Path, timeout: int = 120) -> Path:
    """Download a URL to dest path, return dest."""
    r = requests.get(url, timeout=timeout, stream=True)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def _try_suno(
    prompt: str,
    title: str,
    genre: str,
    duration_seconds: int,
    vocal_style: str,
    job_dir: Path,
) -> Optional[str]:
    """Generate via Suno unofficial API. Returns local file path or None."""
    cookie = getattr(config, "SUNO_COOKIE", "")
    if not cookie:
        log.info("Suno: SUNO_COOKIE not set, skipping")
        return None

    headers = {
        "Authorization": f"Bearer {cookie}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    body = {
        "prompt": prompt,
        "mv": "chirp-v3-5",
        "title": title[:80],
        "tags": genre.lower(),
        "make_instrumental": vocal_style == "instrumental",
        "wait_audio": False,
    }

    try:
        r = requests.post(
            "https://studio-api.suno.ai/api/generate/v2/",
            json=body,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        clips = r.json().get("clips", [])
        if not clips:
            log.warning("Suno: no clips returned")
            return None

        ids = ",".join(c["id"] for c in clips)
        log.info("Suno: polling clips %s", ids)

        # Poll up to 10 minutes
        for _ in range(120):
            time.sleep(5)
            pr = requests.get(
                f"https://studio-api.suno.ai/api/feed/?ids={ids}",
                headers=headers,
                timeout=30,
            )
            pr.raise_for_status()
            feed = pr.json()
            items = feed if isinstance(feed, list) else feed.get("clips", [])
            ready = [x for x in items if x.get("audio_url")]
            if ready:
                audio_url = ready[0]["audio_url"]
                log.info("Suno: downloading from %s", audio_url)
                dest = job_dir / "song_suno.mp3"
                _download(audio_url, dest)
                return str(dest)

        log.warning("Suno: timed out waiting for audio")
        return None

    except Exception as exc:
        log.warning("Suno failed: %s", exc)
        return None


def _try_replicate(
    prompt: str,
    duration_seconds: int,
    job_dir: Path,
) -> Optional[str]:
    """Generate via Replicate MusicGen. Returns local file path or None."""
    token = getattr(config, "REPLICATE_API_TOKEN", "") or ""
    if not token:
        log.info("Replicate: REPLICATE_API_TOKEN not set, skipping")
        return None

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    body = {
        "version": "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
        "input": {
            "prompt": prompt,
            "duration": min(duration_seconds, 30),
            "model_version": "stereo-large",
            "output_format": "mp3",
            "normalization_strategy": "peak",
        },
    }

    try:
        r = requests.post(
            "https://api.replicate.com/v1/predictions",
            json=body,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        prediction = r.json()
        prediction_id = prediction.get("id")
        if not prediction_id:
            log.warning("Replicate: no prediction id returned")
            return None

        log.info("Replicate: polling prediction %s", prediction_id)

        # Poll up to 5 minutes
        for _ in range(60):
            time.sleep(5)
            pr = requests.get(
                f"https://api.replicate.com/v1/predictions/{prediction_id}",
                headers=headers,
                timeout=30,
            )
            pr.raise_for_status()
            data = pr.json()
            status = data.get("status")
            if status == "succeeded":
                output = data.get("output")
                audio_url = output if isinstance(output, str) else (output[0] if output else None)
                if audio_url:
                    log.info("Replicate: downloading from %s", audio_url)
                    dest = job_dir / "song_replicate.mp3"
                    _download(audio_url, dest)
                    return str(dest)
                log.warning("Replicate: succeeded but no output URL")
                return None
            elif status in ("failed", "canceled"):
                log.warning("Replicate: prediction %s", status)
                return None

        log.warning("Replicate: timed out")
        return None

    except Exception as exc:
        log.warning("Replicate failed: %s", exc)
        return None


def _try_huggingface_musicgen(prompt: str, duration_seconds: int, job_dir: Path) -> Optional[str]:
    """Generate instrumental music via HuggingFace free inference (no key required)."""
    # Cap at 30s — musicgen-small max is ~30s of audio
    max_tokens = min(int(duration_seconds * 51.2), 1500)
    try:
        r = requests.post(
            "https://api-inference.huggingface.co/models/facebook/musicgen-small",
            headers={"Content-Type": "application/json"},
            json={
                "inputs": prompt[:500],
                "parameters": {"max_new_tokens": max_tokens},
            },
            timeout=180,
        )
        content_type = r.headers.get("content-type", "")
        if r.status_code == 200 and ("audio" in content_type or len(r.content) > 50_000):
            dest = job_dir / "song_musicgen.mp3"
            dest.write_bytes(r.content)
            if dest.stat().st_size > 10_000:
                log.info("HuggingFace MusicGen: saved %d bytes → %s", dest.stat().st_size, dest)
                return str(dest)
        elif r.status_code == 503:
            log.info("HuggingFace MusicGen: model loading (503) — skipping")
        else:
            log.warning("HuggingFace MusicGen: status %d — %s", r.status_code, r.text[:200])
    except Exception as exc:
        log.warning("HuggingFace MusicGen failed: %s", exc)
    return None


def _try_elevenlabs_tts(lyrics: str, job_dir: Path) -> Optional[str]:
    """Generate a vocal track from lyrics using ElevenLabs TTS."""
    key = getattr(config, "ELEVENLABS_API_KEY", "") or ""
    if not key or not lyrics:
        return None
    # Use Rachel voice (default, no cloning needed)
    voice_id = "21m00Tcm4TlvDq8ikWAM"
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text": lyrics[:2000],
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.35, "similarity_boost": 0.85, "style": 0.30, "use_speaker_boost": True},
            },
            timeout=90,
        )
        r.raise_for_status()
        dest = job_dir / "vocals_tts.mp3"
        dest.write_bytes(r.content)
        log.info("ElevenLabs TTS vocal: %s", dest)
        return str(dest)
    except Exception as exc:
        log.warning("ElevenLabs TTS failed: %s", exc)
        return None


def _mix_vocal_instrumental(instrumental: str, vocal: str, job_dir: Path) -> str:
    """Mix vocal + instrumental with ffmpeg. Returns path to mixed file."""
    import subprocess
    output = job_dir / "song_final.mp3"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", instrumental,
            "-i", vocal,
            "-filter_complex",
            "[0:a]volume=0.70[inst];[1:a]volume=0.95[vox];[inst][vox]amix=inputs=2:duration=longest:dropout_transition=3",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and output.exists():
            log.info("Mixed vocal+instrumental → %s", output)
            return str(output)
        log.warning("ffmpeg mix failed: %s", result.stderr.decode()[:200])
    except Exception as exc:
        log.warning("Audio mixing failed: %s", exc)
    return instrumental  # fall back to instrumental only


def _try_elevenlabs(
    description: str,
    duration_seconds: int,
    job_dir: Path,
) -> Optional[str]:
    """Generate via ElevenLabs Sound Generation. Returns local file path or None.

    This endpoint's real max is 22 seconds (it's an SFX/ambience generator,
    not a song generator) — the previous 30s clamp exceeded that on every
    call above ~22s, so ElevenLabs rejected the request every time and this
    "last resort" fallback silently never worked. Even fixed, this can only
    ever return a short clip, not a full track — it's a bed/texture layer,
    not a substitute for a real music-generation provider (Suno/Replicate).
    """
    key = getattr(config, "ELEVENLABS_API_KEY", "") or ""
    if not key:
        log.info("ElevenLabs: ELEVENLABS_API_KEY not set, skipping")
        return None

    try:
        r = requests.post(
            "https://api.elevenlabs.io/v1/sound-generation",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text": description[:500],
                "duration_seconds": min(max(duration_seconds, 1), 22),
                "prompt_influence": 0.3,
            },
            timeout=60,
        )
        r.raise_for_status()
        dest = job_dir / "song_elevenlabs.mp3"
        dest.write_bytes(r.content)
        log.info("ElevenLabs: saved to %s", dest)
        return str(dest)

    except Exception as exc:
        log.warning("ElevenLabs failed: %s", exc)
        return None


def _elevenlabs_music_compose(prompt: str, length_ms: int, output_path: Path) -> Optional[Path]:
    """Generate real instrumental music via the ElevenLabs Music API
    (POST /v1/music) — the studio music generator, NOT the Sound-Generation
    SFX/ambience endpoint (which returns broadband noise for a "music"
    prompt). Returns output_path (raw MP3 bytes) on success, else None."""
    key = getattr(config, "ELEVENLABS_API_KEY", "") or ""
    if not key:
        log.info("ElevenLabs Music: ELEVENLABS_API_KEY not set, skipping")
        return None

    # The API accepts 3,000–600,000 ms; clamp to stay inside that window.
    length_ms = int(max(3000, min(length_ms, 600000)))
    model_id = getattr(config, "ELEVENLABS_MUSIC_MODEL", "music_v2")
    try:
        r = requests.post(
            "https://api.elevenlabs.io/v1/music",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "prompt": prompt[:2000],
                "music_length_ms": length_ms,
                "model_id": model_id,
                "force_instrumental": True,
            },
            timeout=180,
        )
        r.raise_for_status()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(r.content)
        if output_path.exists() and output_path.stat().st_size > 1000:
            log.info("ElevenLabs Music (%s): %d ms -> %s", model_id, length_ms, output_path)
            return output_path
        log.warning("ElevenLabs Music returned empty/too-small audio")
    except Exception as exc:
        log.warning("ElevenLabs Music failed: %s", exc)
    return None


def generate_background_bed(description: str, duration_seconds: float, output_path: Path) -> Optional[Path]:
    """Full-length instrumental bed sized to duration_seconds via the
    ElevenLabs Music API. Returns output_path on success, None if ElevenLabs
    isn't configured or generation fails.

    Unlike the old approach (a 22s Sound-Generation SFX clip looped to
    length, which produced static, not music), the Music endpoint generates
    a single coherent instrumental of the exact duration — no looping, no
    noise."""
    return _elevenlabs_music_compose(
        description, int(duration_seconds * 1000), Path(output_path)
    )


def mix_voice_and_music(voice_path: Path, music_path: Path, output_path: Path, music_vol: float = 0.15) -> Optional[Path]:
    """Duck background music under a voice track. No padding -- the caller's
    music is already sized to the voice's duration, and duration=first pins
    the result to the voice length regardless of tiny mismatches."""
    import subprocess

    output_path = Path(output_path)
    try:
        # normalize=0 is essential: amix's default normalize=1 divides every
        # input by the input count, silently halving the voice (-6 dB) and
        # leaving it fighting the music. With normalize=0 the voice stays at
        # full level and the music sits under it at exactly music_vol. A
        # sidechain compressor ducks the music down further whenever the
        # voice is actually speaking, so narration always stays on top.
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(voice_path), "-i", str(music_path),
             "-filter_complex",
             f"[0:a]asplit=2[vox][sc];"
             f"[1:a]volume={music_vol}[bglow];"
             f"[bglow][sc]sidechaincompress=threshold=0.02:ratio=8:attack=5:release=300[bg];"
             f"[vox][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0",
             "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)],
            capture_output=True, timeout=60,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
        log.warning("Voice+music mix failed: %s", result.stderr.decode()[:200])
    except Exception as exc:
        log.warning("Voice+music mix failed: %s", exc)
    return None


def trim_audio(input_path: Path, output_path: Path, start: float, duration: float) -> Optional[Path]:
    """Extract a `duration`-second clip starting at `start` seconds."""
    import subprocess

    output_path = Path(output_path)
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path), "-ss", str(start), "-t", str(duration),
             "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
        log.warning("Audio trim failed: %s", result.stderr.decode()[:200])
    except Exception as exc:
        log.warning("Audio trim failed: %s", exc)
    return None


def set_volume(input_path: Path, output_path: Path, volume: float) -> Optional[Path]:
    """Re-encode input_path at a flat volume multiplier."""
    import subprocess

    output_path = Path(output_path)
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path), "-filter:a", f"volume={volume}",
             "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
        log.warning("Volume adjust failed: %s", result.stderr.decode()[:200])
    except Exception as exc:
        log.warning("Volume adjust failed: %s", exc)
    return None


# ── Main Engine ────────────────────────────────────────────────────────────────

class MusicEngine:
    """Cascade of AI music providers: Suno → Replicate → ElevenLabs."""

    def generate(
        self,
        title: str,
        genre: str,
        mood: str,
        bpm: int,
        key: str,
        duration_seconds: int,
        vocal_style: str,
        lyrics: str = "",
        reference_artist: str = "",
        beat_kit: str = "",
        beat_pads: str = "",
        beat_bpm: int = 0,
        job_dir: Path = None,
        progress_cb: Callable = None,
    ) -> dict:
        """
        Generate a song. Returns:
            {
              "audio_path": str | None,
              "lyrics": str,
              "lyrics_structured": dict | None,
              "title": str,
              "provider": str,
            }
        """
        if job_dir is None:
            from utils import file_manager
            job_dir = file_manager.job_dir(title or "song", "music")

        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        def cb(msg: str, pct: int):
            if progress_cb:
                try:
                    progress_cb(msg, pct)
                except Exception:
                    pass
            log.info("[music] %d%% — %s", pct, msg)

        lyrics_structured = None

        # Step 1 — Lyrics
        if not lyrics:
            cb("Generating lyrics...", 10)
            try:
                agent = LyricsAgent()
                result = agent.run(
                    title=title,
                    genre=genre,
                    mood=mood,
                    vocal_style=vocal_style,
                    reference_artist=reference_artist,
                )
                lyrics = result.full_lyrics
                lyrics_structured = result.model_dump()
                # Update title from AI if blank
                if not title or title == "My Song":
                    title = result.title
                log.info("Lyrics generated: %d chars", len(lyrics))
            except Exception as exc:
                log.warning("LyricsAgent failed: %s", exc)
                lyrics = ""

        cb("Composing music...", 30)

        # Build rich prompt for music providers
        ref_note = f" in the style of {reference_artist}" if reference_artist else ""
        prompt = (
            f"{genre} song{ref_note}, {mood} mood, {bpm} BPM, key of {key}. "
            f"{'Instrumental only.' if vocal_style == 'instrumental' else f'{vocal_style.capitalize()} vocals.'} "
            f"Duration ~{duration_seconds} seconds."
        )
        if beat_kit and beat_pads:
            actual_bpm = beat_bpm or bpm
            prompt += (
                f" Built on a {beat_kit} beat at {actual_bpm} BPM featuring: {beat_pads}."
                " The music should feel like it was made to match this drum pattern."
            )
        if lyrics:
            prompt += f" Lyrics:\n{lyrics}"

        cb("Trying Suno AI...", 35)
        audio_path = _try_suno(prompt, title, genre, duration_seconds, vocal_style, job_dir)
        provider = "Suno AI"

        if not audio_path:
            cb("Trying Replicate MusicGen...", 50)
            audio_path = _try_replicate(prompt, duration_seconds, job_dir)
            provider = "Replicate MusicGen"

        if not audio_path:
            cb("Trying HuggingFace MusicGen (free)...", 58)
            audio_path = _try_huggingface_musicgen(prompt, duration_seconds, job_dir)
            provider = "HuggingFace MusicGen"

        if not audio_path:
            cb("Trying ElevenLabs Sound Generation...", 65)
            audio_path = _try_elevenlabs(
                f"{genre} music, {mood}, {bpm} BPM, {vocal_style} vocals",
                duration_seconds,
                job_dir,
            )
            provider = "ElevenLabs"

        if not audio_path:
            provider = "none"
            log.warning("All music providers failed — no audio generated")

        # Add ElevenLabs TTS vocal layer and mix with instrumental
        if lyrics and vocal_style != "instrumental":
            cb("Generating vocal layer...", 70)
            vocal_path = _try_elevenlabs_tts(lyrics, job_dir)
            if vocal_path:
                if audio_path:
                    cb("Mixing vocals with instrumental...", 80)
                    audio_path = _mix_vocal_instrumental(audio_path, vocal_path, job_dir)
                    provider = provider + " + ElevenLabs Vocals"
                else:
                    audio_path = vocal_path
                    provider = "ElevenLabs Vocals"

        cb("Finalizing track...", 85)

        record_job(
            studio="music", job_id=0, user_id=0,
            topic=title, genre=genre, format=vocal_style,
            duration_seconds=duration_seconds,
            music_style=f"{genre}/{mood}",
            ai_provider=provider,
            completed=1 if audio_path else 0,
            error_message="" if audio_path else "All providers failed",
            file_size_bytes=Path(audio_path).stat().st_size if audio_path and Path(audio_path).exists() else 0,
            quality_score=0.8 if audio_path else 0,
        )

        return {
            "audio_path": audio_path,
            "lyrics": lyrics,
            "lyrics_structured": lyrics_structured,
            "title": title,
            "genre": genre,
            "mood": mood,
            "bpm": bpm,
            "key": key,
            "duration_seconds": duration_seconds,
            "vocal_style": vocal_style,
            "provider": provider,
        }
