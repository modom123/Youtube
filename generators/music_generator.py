"""
MusicEngine — AI song production via Mureka → ElevenLabs Music → Suno →
Replicate MusicGen → HuggingFace MusicGen → ElevenLabs Sound Generation cascade.
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


def _try_mureka(
    prompt: str,
    lyrics: str,
    vocal_style: str,
    job_dir: Path,
) -> Optional[str]:
    """Generate via Mureka's official key-based API (real singing). Returns local file path or None."""
    key = getattr(config, "MUREKA_API_KEY", "") or ""
    if not key:
        log.info("Mureka: MUREKA_API_KEY not set, skipping")
        return None

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": "auto", "prompt": prompt[:500]}
    if vocal_style == "instrumental":
        body["lyrics"] = "[Instrumental]"
    elif lyrics:
        body["lyrics"] = lyrics[:3000]

    try:
        r = requests.post("https://api.mureka.ai/v1/song/generate", json=body, headers=headers, timeout=30)
        r.raise_for_status()
        task_id = r.json().get("id")
        if not task_id:
            log.warning("Mureka: no task id returned")
            return None

        log.info("Mureka: polling task %s", task_id)
        for _ in range(90):  # up to ~7.5 minutes
            time.sleep(5)
            pr = requests.get(f"https://api.mureka.ai/v1/song/query/{task_id}", headers=headers, timeout=30)
            pr.raise_for_status()
            data = pr.json()
            status = data.get("status")
            if status in ("succeeded", "completed", "finished"):
                choices = data.get("choices") or []
                audio_url = (
                    data.get("audio_url") or data.get("url")
                    or (choices[0].get("url") if choices else None)
                )
                if audio_url:
                    log.info("Mureka: downloading from %s", audio_url)
                    dest = job_dir / "song_mureka.mp3"
                    _download(audio_url, dest)
                    return str(dest)
                log.warning("Mureka: succeeded but no audio url in response")
                return None
            elif status in ("failed", "error", "cancelled"):
                log.warning("Mureka: task %s", status)
                return None

        log.warning("Mureka: timed out waiting for song")
        return None

    except Exception as exc:
        log.warning("Mureka failed: %s", exc)
        return None


def _try_elevenlabs_music(
    prompt: str,
    lyrics: str,
    vocal_style: str,
    duration_seconds: int,
    job_dir: Path,
) -> Optional[str]:
    """Generate via ElevenLabs Music API (real singing). Returns local file path or None."""
    key = getattr(config, "ELEVENLABS_API_KEY", "") or ""
    if not key:
        log.info("ElevenLabs Music: ELEVENLABS_API_KEY not set, skipping")
        return None

    music_prompt = prompt[:1900]
    if lyrics and vocal_style != "instrumental":
        music_prompt += f"\nLyrics:\n{lyrics[:1500]}"

    try:
        r = requests.post(
            "https://api.elevenlabs.io/v1/music",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "prompt": music_prompt,
                "music_length_ms": max(3000, min(duration_seconds * 1000, 600_000)),
                "model_id": "music_v2",
                "instrumental": vocal_style == "instrumental",
            },
            timeout=180,
        )
        r.raise_for_status()
        dest = job_dir / "song_elevenlabs_music.mp3"
        dest.write_bytes(r.content)
        if dest.stat().st_size > 10_000:
            log.info("ElevenLabs Music: saved %d bytes → %s", dest.stat().st_size, dest)
            return str(dest)
        log.warning("ElevenLabs Music: response too small, likely an error body")
        return None
    except Exception as exc:
        log.warning("ElevenLabs Music failed: %s", exc)
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
            # Normalize both inputs to the same sample rate/channel layout before mixing —
            # providers return different formats (e.g. 32kHz mono vs 44.1kHz stereo), and
            # amix-ing mismatched streams without resampling first can produce sped-up/
            # doubled-sounding audio.
            "[0:a]aresample=44100,aformat=channel_layouts=stereo,volume=0.70[inst];"
            "[1:a]aresample=44100,aformat=channel_layouts=stereo,volume=0.95[vox];"
            "[inst][vox]amix=inputs=2:duration=longest:dropout_transition=3",
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


# ── Main Engine ────────────────────────────────────────────────────────────────

class MusicEngine:
    """Cascade of AI music providers: Mureka → ElevenLabs Music → Suno → Replicate.
    No low-quality free fallback (HuggingFace MusicGen, ElevenLabs Sound Generation)
    is used — those produced unusable output, so if none of the real providers
    are configured the job fails with a clear error instead of garbage audio."""

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

        cb("Trying Mureka...", 33)
        audio_path = _try_mureka(prompt, lyrics, vocal_style, job_dir)
        provider = "Mureka"

        if not audio_path:
            cb("Trying ElevenLabs Music...", 34)
            audio_path = _try_elevenlabs_music(prompt, lyrics, vocal_style, duration_seconds, job_dir)
            provider = "ElevenLabs Music"

        if not audio_path:
            cb("Trying Suno AI...", 35)
            audio_path = _try_suno(prompt, title, genre, duration_seconds, vocal_style, job_dir)
            provider = "Suno AI"

        if not audio_path:
            cb("Trying Replicate MusicGen...", 50)
            audio_path = _try_replicate(prompt, duration_seconds, job_dir)
            provider = "Replicate MusicGen"

        no_audio_warning = None
        if not audio_path:
            provider = "none"
            log.warning("All music providers failed — no audio generated")
            no_audio_warning = (
                "No music could be generated. None of Mureka (MUREKA_API_KEY), "
                "ElevenLabs Music (ELEVENLABS_API_KEY), Suno (SUNO_COOKIE), or "
                "Replicate (REPLICATE_API_TOKEN) are configured. Connect one in "
                "Settings to generate real songs — low-quality free fallbacks have "
                "been removed rather than producing unusable audio."
            )

        # Mureka, ElevenLabs Music, and Suno actually sing the lyrics to a melody.
        sung_by_singing_provider = provider in ("Mureka", "ElevenLabs Music", "Suno AI") and vocal_style != "instrumental"
        warning = no_audio_warning

        # Add ElevenLabs TTS vocal layer and mix with instrumental.
        # Note: this is spoken text-to-speech laid over the instrumental, not real
        # singing — it's a fallback approximation when no singing-capable provider
        # (Mureka, ElevenLabs Music, Suno) was available, not a substitute for one.
        if lyrics and vocal_style != "instrumental" and not sung_by_singing_provider:
            cb("Generating vocal layer...", 70)
            vocal_path = _try_elevenlabs_tts(lyrics, job_dir)
            if vocal_path:
                if audio_path:
                    cb("Mixing vocals with instrumental...", 80)
                    audio_path = _mix_vocal_instrumental(audio_path, vocal_path, job_dir)
                    provider = provider + " + ElevenLabs Vocals (spoken, not sung)"
                else:
                    audio_path = vocal_path
                    provider = "ElevenLabs Vocals (spoken, not sung)"

        has_vocals = sung_by_singing_provider or (lyrics and vocal_style != "instrumental" and "ElevenLabs Vocals" in provider)
        if no_audio_warning:
            pass
        elif vocal_style != "instrumental" and not has_vocals:
            warning = (
                "No vocals were added to this track. Real singing requires Mureka "
                "(MUREKA_API_KEY), ElevenLabs Music (ELEVENLABS_API_KEY), or Suno "
                "(SUNO_COOKIE), none of which are configured, so this fell back to "
                "an instrumental-only track."
            )
        elif vocal_style != "instrumental" and not sung_by_singing_provider:
            warning = (
                "Vocals on this track are spoken text-to-speech laid over the instrumental, "
                "not real singing — none of Mureka (MUREKA_API_KEY), ElevenLabs Music "
                "(ELEVENLABS_API_KEY), or Suno (SUNO_COOKIE) are configured, and those are "
                "the only providers here that actually sing lyrics to a melody."
            )

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
            "has_vocals": bool(has_vocals),
            "warning": warning,
        }
