"""Text-to-speech audio generation — edge-tts primary, pyttsx3/espeak-ng fallback."""
import asyncio
import subprocess
import sys
import re
from pathlib import Path
from typing import Optional
import edge_tts
import config

# Fix Windows asyncio event loop policy (required for edge-tts on Python 3.10+)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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


def _pyttsx3_fallback(text: str, output_path: Path) -> None:
    """Windows TTS fallback using pyttsx3 (saves to WAV, converts to MP3)."""
    import pyttsx3
    import imageio_ffmpeg

    wav_path = output_path.with_suffix(".wav")
    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    engine.save_to_file(text, str(wav_path))
    engine.runAndWait()
    engine.stop()

    if wav_path.exists():
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg_bin, "-y", "-i", str(wav_path), "-q:a", "3", str(output_path)],
            capture_output=True,
        )
        wav_path.unlink(missing_ok=True)

    if not output_path.exists() and wav_path.exists():
        import shutil
        shutil.copy(str(wav_path), str(output_path))


def _espeak_fallback(text: str, output_path: Path) -> None:
    """Linux TTS fallback using espeak-ng."""
    import shutil
    import imageio_ffmpeg

    wav_path = output_path.with_suffix(".wav")
    espeak = shutil.which("espeak-ng") or "espeak-ng"
    subprocess.run(
        [espeak, "-v", "en-us+m3", "-s", "150", "-p", "45", text, "-w", str(wav_path)],
        check=True, capture_output=True,
    )
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg_bin, "-y", "-i", str(wav_path), "-q:a", "3", str(output_path)],
        capture_output=True,
    )
    wav_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output_path.exists():
        import shutil as sh
        if wav_path.exists():
            sh.copy(str(wav_path), str(output_path))


def _tts_fallback(text: str, output_path: Path) -> None:
    """Platform-aware TTS fallback."""
    if sys.platform == "win32":
        try:
            _pyttsx3_fallback(text, output_path)
            return
        except Exception as e:
            print(f"[audio] pyttsx3 failed ({e})")
    # Linux/Mac — try espeak-ng
    try:
        _espeak_fallback(text, output_path)
    except Exception as e:
        print(f"[audio] espeak-ng failed ({e})")


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
        print(f"[audio] edge-tts failed ({e}) — using fallback TTS")
        _tts_fallback(clean_text, output_path)

    if not output_path.exists():
        raise RuntimeError(f"Audio generation failed — no output at {output_path}")

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
