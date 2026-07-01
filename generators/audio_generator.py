"""Text-to-speech audio generation — Google Cloud TTS Neural2 primary, edge-tts secondary, pyttsx3/espeak-ng fallback."""
import asyncio
import base64
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
import edge_tts
import config

# Fix Windows asyncio event loop policy (required for edge-tts on Python 3.10+)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Map edge-tts voice names to Google Neural2 equivalents
_EDGE_TO_NEURAL2 = {
    "en-US-AriaNeural":    "en-US-Neural2-C",
    "en-US-JennyNeural":   "en-US-Neural2-F",
    "en-US-GuyNeural":     "en-US-Neural2-D",
    "en-US-DavisNeural":   "en-US-Neural2-A",
    "en-GB-SoniaNeural":   "en-GB-Neural2-A",
    "en-AU-NatashaNeural": "en-AU-Neural2-A",
}

# Max bytes per Google TTS request (API limit is 5000, use 4800 for safety)
_GOOGLE_TTS_CHUNK_SIZE = 4800


def clean_narration(text: str) -> str:
    """Strip any stage directions or markdown from narration."""
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"#{1,6}\s", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_into_chunks(text: str, max_bytes: int = _GOOGLE_TTS_CHUNK_SIZE) -> list:
    """Split text into chunks <= max_bytes, splitting on sentence boundaries."""
    chunks = []
    current = ""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for sentence in sentences:
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If single sentence exceeds limit, split by word
            if len(sentence.encode("utf-8")) > max_bytes:
                words = sentence.split()
                word_chunk = ""
                for word in words:
                    candidate_word = (word_chunk + " " + word).strip() if word_chunk else word
                    if len(candidate_word.encode("utf-8")) <= max_bytes:
                        word_chunk = candidate_word
                    else:
                        if word_chunk:
                            chunks.append(word_chunk)
                        word_chunk = word
                current = word_chunk
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks


def _resolve_google_voice(voice: str) -> str:
    """Resolve an edge-tts voice name or Google Neural2 voice name to a Neural2 voice id."""
    if "Neural2" in voice:
        return voice
    if voice in _EDGE_TO_NEURAL2:
        return _EDGE_TO_NEURAL2[voice]
    return getattr(config, "GOOGLE_TTS_VOICE", "en-US-Neural2-C")


def _google_tts_chunk(text: str, voice: str, api_key: str) -> bytes:
    """Call Google Cloud TTS REST API for a single chunk, return MP3 bytes."""
    import requests as req
    language_code = "-".join(voice.split("-")[:2])
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": language_code, "name": voice},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    resp = req.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    audio_content = resp.json().get("audioContent", "")
    return base64.b64decode(audio_content)


def _stitch_mp3_chunks(mp3_chunks: list, output_path: Path) -> None:
    """Concatenate MP3 chunks using ffmpeg concat."""
    import imageio_ffmpeg

    if len(mp3_chunks) == 1:
        output_path.write_bytes(mp3_chunks[0])
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        chunk_files = []
        for i, chunk_bytes in enumerate(mp3_chunks):
            chunk_path = Path(tmpdir) / f"chunk_{i:04d}.mp3"
            chunk_path.write_bytes(chunk_bytes)
            chunk_files.append(str(chunk_path))

        list_path = Path(tmpdir) / "concat.txt"
        list_path.write_text("\n".join(f"file '{f}'" for f in chunk_files))

        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c", "copy", str(output_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            # Fallback: raw byte concatenation
            output_path.write_bytes(b"".join(mp3_chunks))


def _generate_google_tts(text: str, output_path: Path, voice: str) -> bool:
    """
    Generate TTS using Google Cloud TTS Neural2 REST API.
    Returns True on success, False if GOOGLE_API_KEY not set or on error.
    Handles long texts by chunking into <=4800 byte pieces.
    """
    api_key = getattr(config, "GOOGLE_API_KEY", "")
    if not api_key:
        return False

    try:
        neural_voice = _resolve_google_voice(voice)
        chunks = _split_into_chunks(text)
        mp3_chunks = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            mp3_data = _google_tts_chunk(chunk, neural_voice, api_key)
            mp3_chunks.append(mp3_data)

        if not mp3_chunks:
            return False

        _stitch_mp3_chunks(mp3_chunks, output_path)
        print(f"[audio] Google Cloud TTS Neural2 ({neural_voice}) — {len(chunks)} chunk(s)")
        return True
    except Exception as e:
        print(f"[audio] Google TTS failed ({e}) — falling back to edge-tts")
        return False


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
    """Convert text to speech and save as MP3.

    Priority:
    1. Google Cloud TTS Neural2 (if GOOGLE_API_KEY set)
    2. edge-tts
    3. espeak-ng / pyttsx3 fallback
    """
    voice = voice or config.DEFAULT_VOICE
    clean_text = clean_narration(text)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try Google Cloud TTS Neural2
    if getattr(config, "GOOGLE_API_KEY", ""):
        if _generate_google_tts(clean_text, output_path, voice):
            if output_path.exists():
                return output_path

    # 2. Try edge-tts
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
    duration = float(clip.duration)  # cast numpy.float64 → plain float so DB drivers don't choke
    clip.close()
    return duration


async def list_voices() -> list:
    """List all available edge-tts voices."""
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith("en-")]


def list_voices_sync() -> list:
    return asyncio.run(list_voices())
