"""Text-to-speech audio generation — edge-tts primary, espeak-ng fallback."""
import asyncio
import subprocess
import re
from pathlib import Path
from typing import Optional
import edge_tts
import config


def clean_narration(text: str) -> str:
    """Strip any stage directions or markdown from narration."""
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"#{1,6}\s", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def _generate_speech(text: str, output_path: Path, voice: str, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(output_path))


def _espeak_fallback(text: str, output_path: Path) -> None:
    """Generate speech using local espeak-ng — saves as WAV then converts to MP3."""
    import shutil
    import imageio_ffmpeg

    wav_path = output_path.with_suffix(".wav")
    espeak = shutil.which("espeak-ng") or "espeak-ng"

    subprocess.run(
        [espeak, "-v", "en-us+m3", "-s", "150", "-p", "45", text, "-w", str(wav_path)],
        check=True, capture_output=True,
    )

    # Use imageio-ffmpeg's bundled binary (avoids broken system ffmpeg)
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg_bin, "-y", "-i", str(wav_path), "-q:a", "3", str(output_path)],
        capture_output=True,
    )
    wav_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output_path.exists():
        # Last resort: just rename WAV to MP3 (moviepy can handle it)
        import shutil as sh
        sh.copy(wav_path if wav_path.exists() else str(wav_path), str(output_path))


def generate_audio(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> Path:
    """Convert text to speech and save as MP3."""
    voice = voice or config.DEFAULT_VOICE
    clean_text = clean_narration(text)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(_generate_speech(clean_text, output_path, voice, rate, pitch))
    except Exception as e:
        print(f"[audio] edge-tts failed ({e}) — using espeak-ng fallback")
        _espeak_fallback(clean_text, output_path)
    return output_path


def get_audio_duration(audio_path: Path) -> float:
    """Get duration of audio file in seconds using moviepy."""
    from moviepy import AudioFileClip
    clip = AudioFileClip(str(audio_path))
    duration = clip.duration
    clip.close()
    return duration


async def list_voices() -> list[dict]:
    """List all available edge-tts voices."""
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith("en-")]


def list_voices_sync() -> list[dict]:
    return asyncio.run(list_voices())
