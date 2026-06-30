"""
Hit Factory — Beat maker + vocal generator + mixer.

Vocal sources (priority order):
  1. ElevenLabs API — professional AI voices (requires ELEVENLABS_API_KEY)
  2. espeak-ng — offline fallback

Sound sources:
  1. Freesound API — real instrument samples & loops (requires FREESOUND_API_KEY)
  2. ffmpeg synth — generated beats fallback
"""
import json
import subprocess
from pathlib import Path
from typing import Optional

import config

def _build_loop_library():
    """Generate a 1003-entry loop library with varied musical characteristics."""
    _GENRES = [
        {"style":"trap","genre":"trap","adjectives":["Dark","Hard","Bouncy","Heavy","Murky","Gritty","Sinister","Menacing","Aggressive","Hypnotic"],
         "nouns":["808 Bass","Hi-Hats","Percussion","Kick Pattern","Snare Roll","Beat","Drums","Rhythm","Groove","Loop"],
         "tags_pool":["trap","hip-hop","808","bass","dark","hard","bounce","modern","urban","street","ATL","drill","phonk","mumble","SoundCloud"],
         "bpm_range":(130,160),"keys":["C","Cm","Dm","Em","Fm","Gm","Am","—"]},
        {"style":"lofi","genre":"lo-fi","adjectives":["Chill","Mellow","Dreamy","Nostalgic","Hazy","Warm","Dusty","Soft","Peaceful","Sleepy"],
         "nouns":["Piano","Guitar","Chords","Vinyl Loop","Rhodes","Keys","Melody","Pads","Atmosphere","Beat"],
         "tags_pool":["lo-fi","chill","study","relax","jazz","vinyl","tape","warm","ambient","bedroom","cafe","rain","night","dreamy","nostalgic"],
         "bpm_range":(60,90),"keys":["C","Dm","Em","F","G","Am","Bb","Eb"]},
        {"style":"pop","genre":"pop","adjectives":["Uplifting","Bright","Catchy","Groovy","Punchy","Energetic","Shimmering","Happy","Driving","Anthemic"],
         "nouns":["Synth","Beat","Drums","Hook","Rhythm","Clap Pattern","Bass","Chord Stab","Arp","Melody"],
         "tags_pool":["pop","synth","dance","radio","commercial","upbeat","chart","EDM","house","future-bass","tropical","electro","club","anthem","festival"],
         "bpm_range":(110,135),"keys":["C","D","Em","F","G","Am","Bb","A"]},
        {"style":"drill","genre":"drill","adjectives":["Dark","Sinister","Cold","Sliding","Menacing","Icy","Eerie","Haunting","Ruthless","Grimy"],
         "nouns":["Bass","Pattern","Melody","Percussion","Hi-Hats","Beat","Rhythm","Loop","Lead","Stab"],
         "tags_pool":["drill","uk-drill","dark","bass","sliding","chicago","NY","trap","minor","grime","road","cold","sinister","aggressive","hard"],
         "bpm_range":(138,148),"keys":["Cm","Dm","Em","Fm","Gm","Am","Bbm","—"]},
        {"style":"rnb","genre":"r&b","adjectives":["Smooth","Silky","Lush","Warm","Sensual","Groovy","Mellow","Soulful","Dreamy","Intimate"],
         "nouns":["Keys","Guitar","Chords","Pads","Bass","Beat","Groove","Melody","Rhythm","Vibe"],
         "tags_pool":["r&b","soul","neo-soul","smooth","groove","funk","jazz","slow-jam","moody","soulful","velvet","late-night","romantic","sensual","mellow"],
         "bpm_range":(75,100),"keys":["Dm","Em","F","Gm","Am","Bb","C","Eb"]},
        {"style":"trap","genre":"afrobeats","adjectives":["Tribal","Tropical","Vibrant","Sunny","Rhythmic","Pulsing","Festive","Bouncy","Warm","Groovy"],
         "nouns":["Drums","Percussion","Shaker","Log Drum","Guitar","Rhythm","Pattern","Beat","Loop","Groove"],
         "tags_pool":["afrobeats","afro","african","dancehall","amapiano","tropical","caribbean","reggae","riddim","island","summer","vibrant","highlife","azonto","afropop"],
         "bpm_range":(100,118),"keys":["C","Dm","Em","F","G","Am","Gm","—"]},
        {"style":"pop","genre":"edm","adjectives":["Epic","Massive","Soaring","Pulsing","Euphoric","Driving","Glitchy","Rolling","Thumping","Rising"],
         "nouns":["Synth","Drop","Build-Up","Lead","Arp","Kick","Bass","Pad","Chord","Riser"],
         "tags_pool":["edm","electronic","house","techno","trance","dubstep","bass-music","rave","club","festival","synth","dance","future","progressive","tech-house"],
         "bpm_range":(120,140),"keys":["Am","Cm","Dm","Em","Fm","C","F","G"]},
        {"style":"lofi","genre":"jazz","adjectives":["Smooth","Swinging","Cool","Moody","Classic","Laid-Back","Improvisational","Breezy","Rich","Bluesy"],
         "nouns":["Piano","Bass Walk","Brush Drums","Chords","Sax Line","Melody","Comping","Groove","Vamp","Riff"],
         "tags_pool":["jazz","blues","swing","classic","live","sax","piano","upright-bass","brush","modal","bebop","cool","fusion","smooth-jazz","bossa"],
         "bpm_range":(80,130),"keys":["Bb","Eb","F","Dm","Gm","Am","C","G"]},
        {"style":"pop","genre":"rock","adjectives":["Heavy","Crunchy","Driving","Raw","Punchy","Distorted","Power","Thundering","Gritty","Raging"],
         "nouns":["Guitar Riff","Drums","Power Chords","Bass","Beat","Groove","Break","Fill","Rhythm","Loop"],
         "tags_pool":["rock","metal","punk","grunge","indie","guitar","distortion","power","live","garage","alternative","hard-rock","heavy","riff","shred"],
         "bpm_range":(110,160),"keys":["E","Em","A","Am","D","Dm","G","C"]},
        {"style":"rnb","genre":"gospel","adjectives":["Uplifting","Soulful","Majestic","Warm","Heavenly","Powerful","Glorious","Inspiring","Joyful","Triumphant"],
         "nouns":["Choir","Piano","Organ","Chords","Pads","Clap","Beat","Groove","Keys","Swell"],
         "tags_pool":["gospel","church","worship","praise","choir","organ","piano","soulful","spiritual","uplift","hymn","faith","inspirational","sacred","hallelujah"],
         "bpm_range":(70,95),"keys":["Bb","C","Eb","F","G","Ab","Db","D"]},
        {"style":"trap","genre":"latin","adjectives":["Fiery","Rhythmic","Tropical","Passionate","Groovy","Sultry","Festive","Spicy","Smooth","Lively"],
         "nouns":["Dembow","Guitar","Percussion","Congas","Timbales","Beat","Rhythm","Bass","Claves","Bongos"],
         "tags_pool":["reggaeton","latin","salsa","bachata","merengue","tropical","urban","dembow","cumbia","bossa-nova","tango","flamenco","rumba","son","guaguanco"],
         "bpm_range":(90,130),"keys":["Am","Dm","Em","C","F","G","Gm","Cm"]},
        {"style":"lofi","genre":"cinematic","adjectives":["Epic","Sweeping","Dramatic","Haunting","Ethereal","Vast","Brooding","Majestic","Tense","Atmospheric"],
         "nouns":["Strings","Orchestra Hit","Pad","Texture","Drone","Melody","Theme","Motif","Ambience","Score"],
         "tags_pool":["cinematic","film","trailer","epic","dramatic","orchestral","ambient","score","soundtrack","tension","suspense","emotional","dark","atmospheric","ethereal"],
         "bpm_range":(55,80),"keys":["Dm","Cm","Em","Fm","Am","Gm","Bbm","C"]},
        {"style":"pop","genre":"funk","adjectives":["Funky","Groovy","Slapping","Tight","Bouncy","Syncopated","Crisp","Dirty","Swinging","Snappy"],
         "nouns":["Bass Line","Drums","Wah Guitar","Clav","Rhythm","Break","Groove","Loop","Pattern","Lick"],
         "tags_pool":["funk","groove","slap","bass","disco","soul","rhythm","breakbeat","syncopation","wah","clavinet","motown","stax","p-funk","boogie"],
         "bpm_range":(95,115),"keys":["E","Em","Am","Dm","G","C","F","A"]},
    ]
    library = []
    idx = 0
    while idx < 1003:
        for genre_def in _GENRES:
            if idx >= 1003:
                break
            slot = idx % len(genre_def["adjectives"])
            noun_slot = idx % len(genre_def["nouns"])
            adj = genre_def["adjectives"][slot]
            noun = genre_def["nouns"][noun_slot]
            bpm_lo, bpm_hi = genre_def["bpm_range"]
            bpm = bpm_lo + (idx * 7) % (bpm_hi - bpm_lo + 1)
            key = genre_def["keys"][idx % len(genre_def["keys"])]
            tag_start = idx % max(1, len(genre_def["tags_pool"]) - 4)
            raw_tags = [genre_def["genre"]] + genre_def["tags_pool"][tag_start:tag_start+4]
            tags = list(dict.fromkeys(raw_tags))
            dur = 8 + (idx % 3) * 2
            library.append({
                "id": f"c{idx+1:04d}",
                "name": f"{adj} {genre_def['genre'].title()} {noun}",
                "bpm": bpm,
                "key": key,
                "tags": tags,
                "duration": dur,
                "style": genre_def["style"],
            })
            idx += 1
    return library


LOOP_LIBRARY = _build_loop_library()


def generate_loop(loop_id, output_path):
    """Generate an audio loop from the LOOP_LIBRARY by ID."""
    entry = next((e for e in LOOP_LIBRARY if e["id"] == loop_id), None)
    if not entry:
        return False
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_beat(str(output_path), duration=entry["duration"],
                  style=entry.get("style", "trap"), bpm=entry["bpm"])
    return output_path.exists() and output_path.stat().st_size > 1000


BEAT_STYLES = {
    "trap": {
        "label": "Trap",
        "emoji": "🔥",
        "description": "808 bass + hi-hats",
        "freesound_query": "trap beat loop 808",
        "config": {
            "bass_freq": 55, "bass_mod": 0.5, "hi_hat_freq": 8000, "hi_hat_rate": 4,
            "kick_freq": 60, "snare_freq": 200, "pad_freqs": [220, 277, 330],
            "pad_vol": 0.04, "bass_vol": 0.25,
        },
    },
    "lofi": {
        "label": "Lo-Fi",
        "emoji": "🌧",
        "description": "Mellow chords + vinyl crackle",
        "freesound_query": "lofi chill beat loop",
        "config": {
            "bass_freq": 110, "bass_mod": 0.2, "hi_hat_freq": 6000, "hi_hat_rate": 2,
            "kick_freq": 80, "snare_freq": 150, "pad_freqs": [262, 330, 392, 494],
            "pad_vol": 0.08, "bass_vol": 0.12,
        },
    },
    "pop": {
        "label": "Pop",
        "emoji": "✨",
        "description": "Upbeat synth",
        "freesound_query": "pop upbeat synth loop",
        "config": {
            "bass_freq": 130, "bass_mod": 1.0, "hi_hat_freq": 9000, "hi_hat_rate": 4,
            "kick_freq": 100, "snare_freq": 250, "pad_freqs": [523, 659, 784],
            "pad_vol": 0.06, "bass_vol": 0.15,
        },
    },
    "drill": {
        "label": "Drill",
        "emoji": "🥶",
        "description": "Dark sliding bass",
        "freesound_query": "drill dark bass loop",
        "config": {
            "bass_freq": 45, "bass_mod": 3.0, "hi_hat_freq": 7500, "hi_hat_rate": 6,
            "kick_freq": 50, "snare_freq": 180, "pad_freqs": [185, 220, 277],
            "pad_vol": 0.05, "bass_vol": 0.30,
        },
    },
    "rnb": {
        "label": "R&B",
        "emoji": "💜",
        "description": "Smooth pads",
        "freesound_query": "rnb smooth pad loop",
        "config": {
            "bass_freq": 98, "bass_mod": 0.3, "hi_hat_freq": 5000, "hi_hat_rate": 2,
            "kick_freq": 70, "snare_freq": 160, "pad_freqs": [294, 370, 440, 554],
            "pad_vol": 0.10, "bass_vol": 0.10,
        },
    },
}


def list_beat_styles():
    return [
        {"id": k, "label": v["label"], "emoji": v["emoji"], "description": v["description"]}
        for k, v in BEAT_STYLES.items()
    ]


# ── ElevenLabs ────────────────────────────────────────────────────────────

def _elevenlabs_available():
    return bool(config.ELEVENLABS_API_KEY)


def elevenlabs_list_voices():
    """Fetch available ElevenLabs voices."""
    if not _elevenlabs_available():
        return []
    import requests
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        voices = r.json().get("voices", [])
        return [
            {
                "voice_id": v["voice_id"],
                "name": v["name"],
                "category": v.get("category", ""),
                "preview_url": v.get("preview_url", ""),
                "labels": v.get("labels", {}),
            }
            for v in voices
        ]
    except Exception as e:
        print(f"[music_studio] ElevenLabs voices error: {e}")
        return []


def elevenlabs_tts(text, output_path, voice_id="21m00Tcm4TlvDq8ikWAM", model_id="eleven_monolingual_v1"):
    """Generate speech/vocals via ElevenLabs API."""
    import requests
    output_path = Path(output_path)
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
        stream=True,
    )
    r.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path


# ── Freesound ─────────────────────────────────────────────────────────────

def _freesound_available():
    return bool(config.FREESOUND_API_KEY)


def freesound_search(query, duration_min=5, duration_max=60, page_size=10):
    """Search Freesound for sounds/loops."""
    if not _freesound_available():
        return []
    import requests
    try:
        r = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": query,
                "filter": f"duration:[{duration_min} TO {duration_max}]",
                "fields": "id,name,duration,previews,tags,username,license",
                "page_size": page_size,
                "token": config.FREESOUND_API_KEY,
            },
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        return [
            {
                "id": s["id"],
                "name": s["name"],
                "duration": round(s["duration"], 1),
                "preview_url": s.get("previews", {}).get("preview-hq-mp3", ""),
                "tags": s.get("tags", [])[:5],
                "username": s.get("username", ""),
                "license": s.get("license", ""),
            }
            for s in results
        ]
    except Exception as e:
        print(f"[music_studio] Freesound search error: {e}")
        return []


def freesound_download(sound_id, output_path):
    """Download a Freesound sound by ID (requires OAuth or API key with download scope)."""
    import requests
    output_path = Path(output_path)
    try:
        # Get sound info to find download URL
        r = requests.get(
            f"https://freesound.org/apiv2/sounds/{sound_id}/",
            params={
                "token": config.FREESOUND_API_KEY,
                "fields": "id,name,previews,download",
            },
            timeout=15,
        )
        r.raise_for_status()
        info = r.json()
        # Use preview (always available without OAuth) as fallback
        url = info.get("previews", {}).get("preview-hq-mp3", "")
        if not url:
            return None
        dr = requests.get(url, timeout=30)
        dr.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(dr.content)
        return output_path if output_path.stat().st_size > 1000 else None
    except Exception as e:
        print(f"[music_studio] Freesound download error: {e}")
        return None


# ── Beat Generation ───────────────────────────────────────────────────────

def generate_beat(output_path, duration=30, style="trap", bpm=120):
    """Generate an instrumental beat using ffmpeg audio filters."""
    output_path = str(output_path)
    cfg = BEAT_STYLES.get(style, BEAT_STYLES["trap"])["config"]

    beat_interval = 60.0 / bpm
    bass_freq = cfg["bass_freq"]
    bass_mod = cfg["bass_mod"]
    pad_freqs = cfg["pad_freqs"]
    pad_vol = cfg["pad_vol"]
    bass_vol = cfg["bass_vol"]
    hi_hat_freq = cfg["hi_hat_freq"]
    hi_hat_rate = cfg["hi_hat_rate"]
    kick_freq = cfg["kick_freq"]
    snare_freq = cfg["snare_freq"]

    inputs = []
    filters = []
    idx = 0

    # Sub bass
    inputs.append(f"sine=f={bass_freq}:d={duration}")
    filters.append(
        f"[{idx}:a]vibrato=f={bass_mod}:d=0.5,volume={bass_vol},"
        f"lowpass=f=150,afade=t=in:d=1,afade=t=out:st={max(0,duration-2)}:d=2[bass]"
    )
    idx += 1

    # Kick
    inputs.append(f"sine=f={kick_freq}:d={duration}")
    kick_trem = bpm / 60.0
    filters.append(
        f"[{idx}:a]tremolo=f={kick_trem}:d=0.9,volume=0.20,lowpass=f=200[kick]"
    )
    idx += 1

    # Hi-hat
    inputs.append(f"anoisesrc=d={duration}:c=white:a=0.03")
    filters.append(
        f"[{idx}:a]highpass=f={hi_hat_freq},tremolo=f={hi_hat_rate}:d=0.8,volume=0.15[hihat]"
    )
    idx += 1

    # Snare
    inputs.append(f"anoisesrc=d={duration}:c=pink:a=0.05")
    snare_rate = bpm / 120.0
    filters.append(
        f"[{idx}:a]bandpass=f={snare_freq}:w=100,tremolo=f={snare_rate}:d=0.7,volume=0.12[snare]"
    )
    idx += 1

    # Pad tones
    pad_labels = []
    for i, freq in enumerate(pad_freqs):
        inputs.append(f"sine=f={freq}:d={duration}")
        label = f"pad{i}"
        pad_labels.append(f"[{label}]")
        filters.append(
            f"[{idx}:a]volume={pad_vol},tremolo=f=0.5:d=0.3,lowpass=f={freq*2}[{label}]"
        )
        idx += 1

    if len(pad_labels) > 1:
        filters.append(f"{''.join(pad_labels)}amix=inputs={len(pad_labels)}[pads]")
    else:
        filters.append(f"[pad0]anull[pads]")

    # Style-specific mixing
    mix_map = {
        "lofi": (True, f"lowpass=f=12000,equalizer=f=800:t=q:w=1:g=3"),
        "drill": (False, f"equalizer=f=60:t=q:w=0.5:g=6,equalizer=f=3000:t=q:w=1:g=-3"),
        "rnb": (False, f"equalizer=f=400:t=q:w=1:g=2,equalizer=f=5000:t=q:w=1:g=2,aecho=0.8:0.88:60:0.3"),
        "pop": (False, f"equalizer=f=5000:t=q:w=1:g=4,equalizer=f=200:t=q:w=1:g=2,compand=attacks=0.01:decays=0.1:points=-80/-80|-30/-15|0/-3:soft-knee=6"),
    }
    has_crackle, extra_fx = mix_map.get(style, (False, f"equalizer=f=80:t=q:w=0.5:g=5,equalizer=f=8000:t=q:w=1:g=2"))

    if has_crackle:
        inputs.append(f"anoisesrc=d={duration}:c=brown:a=0.008")
        filters.append(f"[{idx}:a]highpass=f=3000,lowpass=f=8000,volume=0.3[crackle]")
        idx += 1
        filters.append(
            f"[bass][kick][hihat][snare][pads][crackle]amix=inputs=6:duration=first:dropout_transition=3,"
            f"{extra_fx},afade=t=in:d=2,afade=t=out:st={max(0,duration-3)}:d=3[out]"
        )
    else:
        filters.append(
            f"[bass][kick][hihat][snare][pads]amix=inputs=5:duration=first:dropout_transition=3,"
            f"{extra_fx},afade=t=in:d=1,afade=t=out:st={max(0,duration-2)}:d=2[out]"
        )

    cmd = ["ffmpeg", "-y"]
    for inp in inputs:
        cmd.extend(["-f", "lavfi", "-i", inp])
    cmd.extend(["-filter_complex", ";".join(filters)])
    cmd.extend(["-map", "[out]", "-t", str(duration),
                "-codec:a", "libmp3lame", "-b:a", "192k", output_path])
    subprocess.run(cmd, check=True, capture_output=True)


def generate_beat_from_freesound(output_path, duration=30, style="trap"):
    """Try to get a real beat loop from Freesound, fall back to synth."""
    if not _freesound_available():
        return False
    query = BEAT_STYLES.get(style, BEAT_STYLES["trap"]).get("freesound_query", "beat loop")
    sounds = freesound_search(query, duration_min=5, duration_max=120, page_size=5)
    for sound in sounds:
        if sound.get("preview_url"):
            result = freesound_download(sound["id"], output_path)
            if result:
                # Loop/trim to requested duration
                temp = str(output_path) + ".tmp.mp3"
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(output_path),
                         "-t", str(duration), "-codec:a", "libmp3lame", "-b:a", "192k", temp],
                        check=True, capture_output=True,
                    )
                    Path(temp).rename(output_path)
                except Exception:
                    Path(temp).unlink(missing_ok=True)
                return True
    return False


# ── Vocals ────────────────────────────────────────────────────────────────

def generate_vocals(lyrics, output_path, voice="en-us", speed=140,
                    elevenlabs_voice_id=None):
    """Generate vocals — ElevenLabs if available, espeak-ng fallback."""
    output_path = Path(output_path)

    # Try ElevenLabs first
    if _elevenlabs_available() and elevenlabs_voice_id:
        try:
            elevenlabs_tts(lyrics, output_path, voice_id=elevenlabs_voice_id)
            if output_path.exists() and output_path.stat().st_size > 1000:
                return str(output_path)
        except Exception as e:
            print(f"[music_studio] ElevenLabs failed, falling back to espeak: {e}")

    # Fallback: espeak-ng
    wav_path = str(output_path).replace(".mp3", ".wav")
    subprocess.run(
        ["espeak-ng", "-v", voice, "-s", str(speed), "-w", wav_path, lyrics],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", str(output_path)],
        check=True, capture_output=True,
    )
    Path(wav_path).unlink(missing_ok=True)
    return str(output_path)


def mix_track(vocal_path, beat_path, output_path, vocal_volume=1.0, beat_volume=0.7):
    """Mix vocals over beat using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(vocal_path), "-i", str(beat_path),
         "-filter_complex",
         f"[0:a]volume={vocal_volume}[v];"
         f"[1:a]volume={beat_volume}[b];"
         f"[v][b]amix=inputs=2:duration=longest:dropout_transition=3",
         "-codec:a", "libmp3lame", "-b:a", "192k", str(output_path)],
        check=True, capture_output=True,
    )
