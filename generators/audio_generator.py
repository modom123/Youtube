"""Text-to-speech audio generation — ElevenLabs primary, Google Cloud TTS
Neural2 secondary, edge-tts tertiary, pyttsx3/espeak-ng last-resort fallback.

ElevenLabs goes first because it's the highest quality of the four AND the
most reliable to actually reach from a cloud server: edge-tts calls
Microsoft's consumer endpoint, which frequently blocks datacenter/cloud IP
ranges (Render, AWS, GCP, ...) with 403s — so on a server, edge-tts can fail
silently far more often than it does on a home connection, and Google Cloud
TTS requires the API key to have the Cloud Text-to-Speech API specifically
enabled (a separate scope from Vision/Translate/NLP, easy to miss). When
both of those fail, this used to fall all the way to espeak-ng/pyttsx3 —
robotic, 1990s-sounding synthesis — for real customer-facing videos.

Voice selection is centralized in config.resolve_voice(), which maps any
identifier (a curated ElevenLabs catalog id, a friendly name, or a legacy
Google/edge id) to a {elevenlabs, google, edge} triple so every fallback
layer stays the SAME gender the user picked.
"""
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


# Max characters per ElevenLabs request. The API accepts more, but keeping
# chunks modest keeps latency down and lets us stitch on sentence boundaries.
_ELEVENLABS_CHUNK_SIZE = 2500


def _elevenlabs_tts_chunk(text: str, voice_id: str, api_key: str, model_id: str) -> bytes:
    """Call the ElevenLabs text-to-speech API for a single chunk, return MP3 bytes."""
    import requests as req
    resp = req.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": model_id,
            # Tuned for clear, consistent narration.
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.content


_EL_ACCOUNT_VOICES_CACHE: Optional[list] = None


def _elevenlabs_account_voices(api_key: str) -> list:
    """Fetch (and cache) the voices actually available on THIS ElevenLabs account."""
    global _EL_ACCOUNT_VOICES_CACHE
    if _EL_ACCOUNT_VOICES_CACHE is not None:
        return _EL_ACCOUNT_VOICES_CACHE
    import requests as req
    try:
        r = req.get("https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": api_key}, timeout=15)
        r.raise_for_status()
        _EL_ACCOUNT_VOICES_CACHE = r.json().get("voices", [])
    except Exception as e:
        print(f"[audio] ElevenLabs: could not list account voices ({e})")
        _EL_ACCOUNT_VOICES_CACHE = []
    return _EL_ACCOUNT_VOICES_CACHE


def _elevenlabs_fallback_voice(api_key: str, voice_id: str) -> Optional[str]:
    """If a catalog voice_id isn't on this account (older/free plans differ),
    pick a REAL account voice matched to the catalog voice's gender so we still
    get an ElevenLabs voice of the right gender instead of dropping to espeak."""
    entry = next((v for v in config.VOICE_CATALOG if v["id"] == voice_id), None)
    gender = (entry or {}).get("gender", "").lower()
    voices = _elevenlabs_account_voices(api_key)
    if not voices:
        return None
    same = [v for v in voices if (v.get("labels") or {}).get("gender", "").lower() == gender]
    pool = same or voices
    return pool[0].get("voice_id")


def _generate_elevenlabs(text: str, output_path: Path, voice_id: str) -> bool:
    """
    Generate TTS using the ElevenLabs API — the primary, highest-quality source.
    Returns True on success, False if ELEVENLABS_API_KEY is not set or on error.

    Fails LOUDLY (logs the HTTP status) so a silent drop to the robotic espeak
    voice is diagnosable, and self-heals a bad/unavailable voice id by retrying
    with a real gender-matched voice from the account.
    """
    api_key = (getattr(config, "ELEVENLABS_API_KEY", "") or "").strip()
    if not api_key:
        print("[audio] ElevenLabs SKIPPED — ELEVENLABS_API_KEY is not set. "
              "Set it in Settings → ElevenLabs (or the env var) or you'll get the "
              "robotic fallback voice.")
        return False
    if not voice_id:
        return False

    model_id = getattr(config, "ELEVENLABS_MODEL", "eleven_multilingual_v2")
    chunks = _split_into_chunks(text, _ELEVENLABS_CHUNK_SIZE)

    # Try the requested catalog voice first; if it 404/422s (not on this plan),
    # retry once with a real account voice of the same gender.
    tried = []
    attempt = voice_id
    for _ in range(2):
        tried.append(attempt)
        try:
            mp3_chunks = [
                _elevenlabs_tts_chunk(chunk, attempt, api_key, model_id)
                for chunk in chunks if chunk.strip()
            ]
            if not mp3_chunks:
                return False
            _stitch_mp3_chunks(mp3_chunks, output_path)
            print(f"[audio] ElevenLabs OK ({model_id}, voice={attempt}) — {len(mp3_chunks)} chunk(s)")
            return output_path.exists()
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            body = ""
            try:
                body = e.response.text[:200]
            except Exception:
                pass
            print(f"[audio] ElevenLabs FAILED voice={attempt} status={status} err={e} {body}")
            if status in (401, 403):
                print("[audio] ElevenLabs: API key rejected — check ELEVENLABS_API_KEY is valid.")
                return False
            if status == 429:
                print("[audio] ElevenLabs: quota/credits exhausted (429).")
                return False
            # 404/422/etc: voice may not exist on this account — self-heal once.
            fb = _elevenlabs_fallback_voice(api_key, voice_id)
            if fb and fb not in tried:
                print(f"[audio] ElevenLabs: retrying with account voice {fb}")
                attempt = fb
                continue
            return False
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


def _resolve_edge_voice(voice: str) -> str:
    """Resolve a Social Optimize voice-catalog id (e.g. 'en-US-Studio-O') or a
    Google Neural2 name to a real edge-tts voice name (e.g. 'en-US-AriaNeural').

    edge-tts has its own naming scheme, distinct from both the app's catalog
    ids and Google Cloud TTS's Neural2/Studio names — passing either of those
    straight through fails with "Invalid voice" every time. Every catalog
    entry already carries the correct edge-tts name in its 'edge' field."""
    if voice.endswith("Neural") or voice.endswith("Neural2"):
        return voice
    catalog_entry = next((v for v in config.VOICE_CATALOG if v["id"] == voice), None)
    if catalog_entry and catalog_entry.get("edge"):
        return catalog_entry["edge"]
    return "en-US-AriaNeural"


async def _generate_speech(text: str, output_path: Path, voice: str, rate: str, pitch: str) -> None:
    edge_voice = _resolve_edge_voice(voice)
    communicate = edge_tts.Communicate(text, edge_voice, rate=rate, pitch=pitch)
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

    Priority (each fallback stays the SAME gender the user selected):
    1. ElevenLabs (if ELEVENLABS_API_KEY set) — highest quality, most
       reliable to reach from a cloud server
    2. Google Cloud TTS Neural2 (if GOOGLE_API_KEY set)
    3. edge-tts
    4. espeak-ng / pyttsx3 fallback
    """
    voice = voice or config.DEFAULT_VOICE
    resolved = config.resolve_voice(voice)
    clean_text = clean_narration(text)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _has_real_audio() -> bool:
        # edge-tts (and some failure paths) can leave a 0-byte file behind
        # when the connection drops mid-write — exists() alone would treat
        # that empty stub as a successful result.
        return output_path.exists() and output_path.stat().st_size > 0

    # 1. Try ElevenLabs — the primary, highest-quality source
    if _generate_elevenlabs(clean_text, output_path, resolved["elevenlabs"]):
        if _has_real_audio():
            return output_path

    # 2. Try Google Cloud TTS Neural2 (gender-matched fallback voice)
    if getattr(config, "GOOGLE_API_KEY", ""):
        if _generate_google_tts(clean_text, output_path, resolved["google"]):
            if _has_real_audio():
                return output_path

    # 3. Try edge-tts (gender-matched fallback voice — never a raw Google id,
    #    which edge-tts would reject and drop us to the robotic espeak voice)
    try:
        asyncio.run(_generate_speech(clean_text, output_path, resolved["edge"], rate, pitch))
        if not _has_real_audio():
            raise RuntimeError("edge-tts produced no audio content")
    except Exception as e:
        print(f"[audio] edge-tts failed ({e}) — using fallback TTS")
        _tts_fallback(clean_text, output_path)

    if not _has_real_audio():
        raise RuntimeError(f"Audio generation failed — no output at {output_path}")

    return output_path


def get_audio_duration(audio_path: Path) -> float:
    """Get duration of audio file in seconds using moviepy."""
    from moviepy import AudioFileClip
    clip = AudioFileClip(str(audio_path))
    duration = float(clip.duration)  # cast numpy.float64 → plain float so DB drivers don't choke
    clip.close()
    return duration


_gcs_credentials = None


def _get_gcs_token() -> str:
    """Return a fresh OAuth2 access token for the configured service account.
    GCS bucket writes need real IAM authorization, not the plain API key
    used everywhere else in this file — a service account is the only
    practical way to get that from a headless server."""
    global _gcs_credentials
    import json as _json
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as _AuthRequest

    if _gcs_credentials is None:
        info = _json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        _gcs_credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
        )
    if not _gcs_credentials.valid:
        _gcs_credentials.refresh(_AuthRequest())
    return _gcs_credentials.token


def _gcs_upload(bucket: str, object_name: str, data: bytes) -> None:
    import requests

    token = _get_gcs_token()
    resp = requests.post(
        f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o",
        params={"uploadType": "media", "name": object_name},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "audio/wav"},
        data=data,
        timeout=60,
    )
    resp.raise_for_status()
    print(f"[audio] Uploaded {len(data)} bytes to gs://{bucket}/{object_name}")


def _gcs_delete(bucket: str, object_name: str) -> None:
    if not bucket:
        return
    import requests
    from urllib.parse import quote
    try:
        token = _get_gcs_token()
        requests.delete(
            f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(object_name, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except Exception as e:
        # Not fatal to transcription itself, but don't pretend it succeeded.
        print(f"[audio] Failed to clean up gs://{bucket}/{object_name}: {e}")


def transcribe_audio(audio_path, language_code: str = "en-US") -> str:
    """Real speech-to-text transcription via Google Cloud Speech-to-Text v1,
    using the same GOOGLE_API_KEY already configured for TTS.

    Converts to 16kHz mono LINEAR16 WAV first — the most reliably-supported
    STT input — rather than sending the source MP3 directly, since exact
    MP3 sample-rate/encoding handling varies by API version.

    Uses the asynchronous longrunningrecognize endpoint since podcast
    episodes routinely exceed the synchronous recognize endpoint's ~1-minute
    cap. Inline (non-GCS) audio content has a real ~10MB request-size
    ceiling on Google's side, which at 16kHz mono is only ~5 minutes of
    audio — well under a typical podcast episode. If GCS_BUCKET_NAME and
    GOOGLE_SERVICE_ACCOUNT_JSON are configured, audio over that threshold is
    uploaded to GCS first and referenced by gs:// URI instead (then deleted
    once transcription completes); otherwise this raises a clear error
    rather than silently truncating, which callers already treat as
    non-fatal.
    """
    import base64
    import subprocess
    import time
    import uuid as _uuid
    import imageio_ffmpeg
    import requests

    api_key = getattr(config, "GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not configured — cannot transcribe audio")

    audio_path = Path(audio_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "for_stt.wav"
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_bin, "-y", "-i", str(audio_path), "-ac", "1", "-ar", "16000",
             "-sample_fmt", "s16", str(wav_path)],
            capture_output=True,
        )
        if result.returncode != 0 or not wav_path.exists():
            raise RuntimeError(
                f"Failed to convert audio for transcription: "
                f"{result.stderr.decode('utf-8', errors='replace')[-300:]}"
            )
        audio_bytes = wav_path.read_bytes()

    gcs_object_name = None
    audio_field: dict

    if len(audio_bytes) > 9_500_000:
        bucket = getattr(config, "GCS_BUCKET_NAME", "")
        if not bucket or not getattr(config, "GOOGLE_SERVICE_ACCOUNT_JSON", ""):
            raise RuntimeError(
                f"Audio too large for inline transcription ({len(audio_bytes) / 1e6:.1f}MB, "
                "~10MB limit) and GCS_BUCKET_NAME / GOOGLE_SERVICE_ACCOUNT_JSON aren't both "
                "configured — transcription skipped."
            )
        gcs_object_name = f"stt-scratch/{_uuid.uuid4()}.wav"
        _gcs_upload(bucket, gcs_object_name, audio_bytes)
        audio_field = {"uri": f"gs://{bucket}/{gcs_object_name}"}
    else:
        audio_field = {"content": base64.b64encode(audio_bytes).decode()}

    try:
        start_resp = requests.post(
            f"https://speech.googleapis.com/v1/speech:longrunningrecognize?key={api_key}",
            json={
                "config": {
                    "encoding": "LINEAR16",
                    "sampleRateHertz": 16000,
                    "languageCode": language_code,
                    "enableAutomaticPunctuation": True,
                },
                "audio": audio_field,
            },
            timeout=30,
        )
        start_resp.raise_for_status()
        operation_name = start_resp.json().get("name")
        if not operation_name:
            raise RuntimeError(f"Google Speech-to-Text did not return an operation name: {start_resp.json()}")
    except Exception:
        if gcs_object_name:
            _gcs_delete(getattr(config, "GCS_BUCKET_NAME", ""), gcs_object_name)
        raise

    try:
        # Poll until done — long episodes can take a few minutes to transcribe.
        for _ in range(60):  # up to ~5 minutes
            time.sleep(5)
            poll_resp = requests.get(
                f"https://speech.googleapis.com/v1/operations/{operation_name}",
                params={"key": api_key},
                timeout=30,
            )
            poll_resp.raise_for_status()
            data = poll_resp.json()
            if data.get("done"):
                if "error" in data:
                    raise RuntimeError(f"Google Speech-to-Text failed: {data['error']}")
                results = data.get("response", {}).get("results", [])
                transcript = " ".join(
                    r["alternatives"][0]["transcript"]
                    for r in results
                    if r.get("alternatives")
                )
                print(f"[audio] Transcribed {len(transcript)} chars via Google Speech-to-Text")
                return transcript.strip()

        raise TimeoutError("Google Speech-to-Text did not complete within 5 minutes")
    finally:
        # Scratch object served its purpose the moment the request was
        # accepted — never leave it in the bucket accumulating storage cost.
        if gcs_object_name:
            _gcs_delete(getattr(config, "GCS_BUCKET_NAME", ""), gcs_object_name)


async def list_voices() -> list:
    """List all available edge-tts voices."""
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith("en-")]


def list_voices_sync() -> list:
    return asyncio.run(list_voices())
