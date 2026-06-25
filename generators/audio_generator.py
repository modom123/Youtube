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

# Map edge-tts voice names to best Google TTS equivalents (Studio > Journey > Neural2)
_EDGE_TO_GOOGLE = {
    "en-US-AriaNeural":    "en-US-Studio-O",
    "en-US-JennyNeural":   "en-US-Journey-F",
    "en-US-GuyNeural":     "en-US-Studio-Q",
    "en-US-DavisNeural":   "en-US-Journey-D",
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
    """Resolve an edge-tts voice name to the best Google TTS voice (Studio/Journey/Neural2)."""
    if "Studio" in voice or "Journey" in voice or "Neural2" in voice:
        return voice
    if voice in _EDGE_TO_GOOGLE:
        return _EDGE_TO_GOOGLE[voice]
    return getattr(config, "GOOGLE_TTS_VOICE", "en-US-Studio-O")


def _google_tts_chunk(text: str, voice: str, api_key: str) -> bytes:
    """Call Google Cloud TTS REST API for a single chunk, return high-quality MP3 bytes."""
    import requests as req
    language_code = "-".join(voice.split("-")[:2])

    ssml = f'<speak><prosody rate="medium" pitch="+0st">{text}</prosody></speak>'

    payload = {
        "input": {"ssml": ssml},
        "voice": {"languageCode": language_code, "name": voice},
        "audioConfig": {
            "audioEncoding": "MP3",
            "sampleRateHertz": 24000,
            "speakingRate": 1.0,
            "pitch": 0.0,
            "effectsProfileId": ["headphone-class-device"],
        },
    }

    # Studio/Journey voices use v1beta1 endpoint
    api_version = "v1beta1" if ("Studio" in voice or "Journey" in voice) else "v1"
    url = f"https://texttospeech.googleapis.com/{api_version}/text:synthesize?key={api_key}"
    resp = req.post(url, json=payload, timeout=30)

    if resp.status_code != 200 and api_version == "v1beta1":
        # Fallback to Neural2 if Studio/Journey voice not available
        fallback_voice = language_code + "-Neural2-D"
        print(f"[audio] {voice} unavailable, falling back to {fallback_voice}")
        payload["voice"]["name"] = fallback_voice
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


def _elevenlabs_tts_chunk(text: str, voice_id: str, api_key: str) -> bytes:
    """Call ElevenLabs TTS API for a single chunk, return MP3 bytes."""
    import requests as req
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        },
    }
    resp = req.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content


def _generate_elevenlabs_tts(text: str, output_path: Path) -> bool:
    """Generate TTS using ElevenLabs API. Returns True on success."""
    api_key = getattr(config, "ELEVENLABS_API_KEY", "")
    if not api_key:
        return False

    voice_id = getattr(config, "ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
    try:
        chunks = _split_into_chunks(text, max_bytes=4000)
        mp3_chunks = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            mp3_data = _elevenlabs_tts_chunk(chunk, voice_id, api_key)
            mp3_chunks.append(mp3_data)

        if not mp3_chunks:
            return False

        _stitch_mp3_chunks(mp3_chunks, output_path)
        print(f"[audio] ElevenLabs TTS ({voice_id}) — {len(chunks)} chunk(s)")
        return True
    except Exception as e:
        print(f"[audio] ElevenLabs TTS failed ({e}) — falling back")
        return False


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
    if not Path(output_path).exists() or Path(output_path).stat().st_size < 1000:
        raise RuntimeError("edge-tts produced empty or invalid output")


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
    """Linux TTS fallback using espeak-ng with enhanced audio quality."""
    import shutil
    import imageio_ffmpeg

    wav_path = output_path.with_suffix(".wav")
    espeak = shutil.which("espeak-ng") or "espeak-ng"
    result = subprocess.run(
        [espeak, "-v", "en-us", "-s", "160", "-p", "50", "-a", "180", "--stdin", "-w", str(wav_path)],
        input=text, text=True, capture_output=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"[audio] espeak-ng stderr: {result.stderr[:200]}")
    if not wav_path.exists():
        raise RuntimeError(f"espeak-ng produced no output: {result.stderr[:200]}")
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg_bin, "-y", "-i", str(wav_path),
         "-ar", "44100", "-ac", "2",
         "-b:a", "192k",
         str(output_path)],
        capture_output=True, timeout=60,
    )
    wav_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output_path.exists():
        if wav_path.exists():
            shutil.copy(str(wav_path), str(output_path))


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
    1. ElevenLabs (if ELEVENLABS_API_KEY set — highest quality)
    2. Google Cloud TTS Studio/Journey (if GOOGLE_API_KEY set)
    3. edge-tts (Microsoft neural voices — free, good quality)
    4. espeak-ng / pyttsx3 fallback
    """
    voice = voice or config.DEFAULT_VOICE
    clean_text = clean_narration(text)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try ElevenLabs (highest quality voices)
    if getattr(config, "ELEVENLABS_API_KEY", ""):
        if _generate_elevenlabs_tts(clean_text, output_path):
            if output_path.exists() and output_path.stat().st_size > 1000:
                return output_path

    # 2. Try Google Cloud TTS Studio/Journey
    if getattr(config, "GOOGLE_API_KEY", ""):
        if _generate_google_tts(clean_text, output_path, voice):
            if output_path.exists() and output_path.stat().st_size > 1000:
                return output_path

    # 3. Try edge-tts (run in a fresh thread with its own event loop to avoid conflicts)
    edge_voices = [voice, "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural"]
    seen = set()
    edge_voices = [v for v in edge_voices if not (v in seen or seen.add(v))]
    edge_ok = False

    for ev in edge_voices:
        try:
            import concurrent.futures
            def _edge_tts_in_thread():
                asyncio.run(_generate_speech(clean_text, output_path, ev, rate, pitch))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_edge_tts_in_thread).result(timeout=90)
            if output_path.exists() and output_path.stat().st_size > 1000:
                print(f"[audio] edge-tts generated audio ({ev})")
                edge_ok = True
                break
        except Exception as e:
            print(f"[audio] edge-tts failed with voice {ev}: {e}")

    if not edge_ok:
        print("[audio] All edge-tts voices failed — using fallback TTS")
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


async def list_voices() -> list:
    """List all available edge-tts voices."""
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith("en-")]


def list_voices_sync() -> list:
    return asyncio.run(list_voices())
