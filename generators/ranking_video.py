"""
RankingVideoEngine — generates "Top N" / ranking / listicle-style videos.

Pipeline: Claude writes the ranked list (title + blurb per item) if not
supplied -> Gamma turns that outline into a real slide deck, exported as one
PNG per card -> per-item TTS narration -> ffmpeg assembles the ordered
slides, each shown for exactly its own narration's duration, into the final
video.

Deliberately does NOT reuse video_generator.create_video()'s image handling:
that function shuffles visuals and assigns each a random 4-8s duration,
which is correct for B-roll filler but wrong here — a ranked list must show
slide #10 while narrating item #10, then #9, etc., in order, each synced to
its own audio.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

import config
from generators import gamma_client
from generators.audio_generator import generate_audio, get_audio_duration
from generators.video_generator import _prepare_clip_segment, _get_ffmpeg

ProgressCallback = Optional[Callable[[str, int, str], None]]

RATIO_SIZES = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
    "4:5": (1080, 1350),
}


def _progress(cb: ProgressCallback, status: str, pct: int, step: str):
    if cb:
        try:
            cb(status, pct, step)
        except Exception:
            pass


def _generate_ranked_items(topic: str, count: int) -> list[dict]:
    """Use Claude to write `count` ranked items (title + narration blurb)
    for the given topic. Falls back to a minimal placeholder list if
    ANTHROPIC_API_KEY isn't configured (caller should treat that as
    degraded, not silently 'working')."""
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured — cannot auto-generate ranked items. "
            "Pass explicit items instead."
        )

    prompt = f"""Write a "Top {count}" ranking video script about: {topic}

Return exactly {count} items, ranked from #{count} (least notable) down to #1 (most notable) —
classic countdown order, since that's how ranking videos are narrated.

For each item provide:
- rank: the number (from {count} down to 1)
- title: a short punchy name for this item (a few words)
- blurb: 2-3 sentences of narration text explaining why it's ranked here — written
  to be read aloud, conversational, engaging, with a hook

Response format (JSON only, no markdown fence):
{{
  "items": [
    {{"rank": {count}, "title": "...", "blurb": "..."}},
    ...
    {{"rank": 1, "title": "...", "blurb": "..."}}
  ]
}}
"""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    data = json.loads(text)
    items = data.get("items", [])
    if len(items) != count:
        raise RuntimeError(f"Expected {count} ranked items from Claude, got {len(items)}")
    return items


def _build_gamma_input_text(topic: str, items: list[dict]) -> str:
    """Build a structured outline for Gamma to turn into a slide deck."""
    lines = [f"# Top {len(items)}: {topic}", ""]
    for item in items:
        lines.append(f"## #{item['rank']}: {item['title']}")
        lines.append(item.get("blurb", ""))
        lines.append("")
    return "\n".join(lines)


def _assemble_video(
    slide_images: list[Path],
    narration_texts: list[str],
    voice: Optional[str],
    output_path: Path,
    ratio: str,
    work_dir: Path,
    cb: ProgressCallback,
) -> Path:
    """Generate per-slide TTS, then assemble ordered slides (each held for
    its own narration's duration) into the final video with ffmpeg."""
    if len(slide_images) != len(narration_texts):
        raise ValueError(
            f"Slide count ({len(slide_images)}) doesn't match narration count "
            f"({len(narration_texts)}) — Gamma may have split cards differently "
            f"than the ranked item list."
        )

    width, height = RATIO_SIZES.get(ratio, RATIO_SIZES["9:16"])
    ffmpeg = _get_ffmpeg()

    audio_paths = []
    for i, text in enumerate(narration_texts):
        _progress(cb, "narrating", 50 + int(15 * i / len(narration_texts)),
                   f"Recording narration {i+1}/{len(narration_texts)}...")
        audio_path = work_dir / f"narration_{i:03d}.mp3"
        generate_audio(text, audio_path, voice=voice)
        audio_paths.append(audio_path)

    durations = [get_audio_duration(p) for p in audio_paths]

    video_segments = []
    for i, (img, dur) in enumerate(zip(slide_images, durations)):
        _progress(cb, "assembling", 65 + int(20 * i / len(slide_images)),
                   f"Rendering slide {i+1}/{len(slide_images)}...")
        seg = _prepare_clip_segment(img, max(dur, 1.0), width, height, work_dir, i)
        if not seg:
            raise RuntimeError(f"Failed to render slide {i+1} ({img.name})")
        video_segments.append(seg)

    concat_video = work_dir / "concat_video.txt"
    concat_video.write_text("\n".join(f"file '{seg}'" for seg in video_segments))

    concat_audio = work_dir / "concat_audio.txt"
    concat_audio.write_text("\n".join(f"file '{p}'" for p in audio_paths))

    silent_video = work_dir / "silent.mp4"
    combined_audio = work_dir / "combined_audio.mp3"

    _progress(cb, "assembling", 87, "Concatenating slides...")
    r = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_video),
         "-c", "copy", str(silent_video)],
        capture_output=True, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Slide concat failed: {r.stderr.decode('utf-8', errors='replace')[-400:]}")

    _progress(cb, "assembling", 92, "Concatenating narration...")
    r = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_audio),
         "-c", "copy", str(combined_audio)],
        capture_output=True, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Audio concat failed: {r.stderr.decode('utf-8', errors='replace')[-400:]}")

    _progress(cb, "finalizing", 96, "Muxing final video...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [ffmpeg, "-y", "-i", str(silent_video), "-i", str(combined_audio),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", "-shortest",
         str(output_path)],
        capture_output=True, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Final mux failed: {r.stderr.decode('utf-8', errors='replace')[-400:]}")

    return output_path


def generate_ranking_video(job_id: str, job_config: dict, progress_callback: ProgressCallback = None) -> dict:
    """
    Main entry point.

    job_config keys:
        topic: str — required if items not supplied
        count: int — number of ranked items (default 10)
        items: list[dict] — optional pre-written [{rank, title, blurb}, ...],
                             skips the Claude auto-write step
        voice: str — TTS voice (optional)
        ratio: "9:16" | "1:1" | "16:9" | "4:5" (default "9:16")
        theme: str — optional Gamma theme name
        user_id: int

    Returns dict: {status, video_path, thumbnail_path, items, error}
    """
    cb = progress_callback
    topic = job_config.get("topic", "")
    count = int(job_config.get("count", 10))
    voice = job_config.get("voice")
    ratio = job_config.get("ratio", "9:16")
    theme = job_config.get("theme")

    out_dir = Path(config.OUTPUT_DIR) / "rankings" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        items = job_config.get("items")
        if not items:
            _progress(cb, "writing", 5, "Writing ranked list...")
            items = _generate_ranked_items(topic, count)

        _progress(cb, "designing", 20, "Designing slide deck with Gamma...")
        input_text = _build_gamma_input_text(topic, items)
        slides_dir = out_dir / "slides"
        slide_images = gamma_client.generate_slide_deck(
            input_text, slides_dir, num_cards=len(items) + 1, theme=theme,
        )
        # Gamma may add a title card — if so, drop it and keep exactly one
        # slide per ranked item, in order.
        if len(slide_images) == len(items) + 1:
            slide_images = slide_images[1:]

        narration_texts = [f"Number {item['rank']}: {item['title']}. {item.get('blurb', '')}" for item in items]

        video_path = out_dir / "ranking_video.mp4"
        _assemble_video(slide_images, narration_texts, voice, video_path, ratio, work_dir, cb)

        for f in work_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
        try:
            work_dir.rmdir()
        except Exception:
            pass

        _progress(cb, "done", 100, "Ranking video complete!")
        return {
            "status": "done",
            "video_path": str(video_path),
            "thumbnail_path": str(slide_images[0]) if slide_images else "",
            "items": items,
            "topic": topic,
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "items": job_config.get("items", [])}
