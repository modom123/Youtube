"""
ClipperEngine — AI-powered video clipper for viral short-form content.

Downloads or ingests a long-form video, uses ffmpeg scene/silence detection
and Claude AI analysis to identify the most engaging moments, then extracts,
reframes, captions, and exports ready-to-post clips.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import textwrap
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_CLIP_COUNT = 5
DEFAULT_CLIP_LENGTH = 60  # seconds
DEFAULT_RATIO = "9:16"
SCENE_THRESHOLD = 0.3
SILENCE_NOISE_DB = -30
SILENCE_DURATION = 0.5
HOOK_DURATION = 3.0
FADE_DURATION = 0.5
CAPTION_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CAPTION_FONTSIZE = 48
CAPTION_COLOR = "white"
CAPTION_OUTLINE = "black"
CAPTION_OUTLINE_WIDTH = 3

ProgressCallback = Optional[Callable[[str, int, str], None]]


def _progress(cb: ProgressCallback, status: str, progress: int, step: str):
    if cb:
        try:
            cb(status, progress, step)
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# 1. VIDEO ACQUISITION
# ═════════════════════════════════════════════════════════════════════════════

def _acquire_video(clip_config: dict, work_dir: Path, cb: ProgressCallback) -> Path:
    """Return path to the source video file, downloading if necessary."""
    source = clip_config.get("source", "url")
    video_path = clip_config.get("video_path")
    url = clip_config.get("url")

    if source == "file" and video_path:
        p = Path(video_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if source == "upload" and video_path:
        p = Path(video_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Uploaded file not found: {video_path}")

    if source == "job" and clip_config.get("job_id"):
        # Look in the standard output location for a completed job
        job_dir = config.OUTPUT_DIR / "videos" / clip_config["job_id"]
        if job_dir.is_dir():
            for ext in ("*.mp4", "*.webm", "*.mkv"):
                matches = sorted(job_dir.glob(ext))
                if matches:
                    return matches[0]
        if video_path and Path(video_path).is_file():
            return Path(video_path)
        raise FileNotFoundError(f"No video found for job {clip_config['job_id']}")

    if url:
        _progress(cb, "downloading", 5, "Downloading video...")
        out_path = work_dir / "source.%(ext)s"
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", str(out_path),
            "--no-overwrites",
            "--socket-timeout", "30",
            "--retries", "3",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("yt-dlp failed: %s", result.stderr)
            raise RuntimeError(f"yt-dlp download failed: {result.stderr[:500]}")

        # Find the downloaded file
        for f in sorted(work_dir.glob("source.*")):
            if f.suffix in (".mp4", ".webm", ".mkv", ".mov"):
                return f
        raise RuntimeError("Download completed but no video file found")

    raise ValueError("No video source provided in clip_config")


# ═════════════════════════════════════════════════════════════════════════════
# 2. VIDEO METADATA & ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def _get_video_metadata(video_path: Path) -> dict:
    """Extract duration, resolution, fps, codec via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:300]}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0))

    width = height = fps = 0
    codec = ""
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            codec = s.get("codec_name", "")
            r = s.get("r_frame_rate", "30/1")
            parts = r.split("/")
            fps = round(int(parts[0]) / max(int(parts[1]), 1), 2) if len(parts) == 2 else 30
            break

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "codec": codec,
        "format": fmt.get("format_name", ""),
    }


def _detect_scenes(video_path: Path, threshold: float = SCENE_THRESHOLD) -> List[float]:
    """Detect scene change timestamps using ffmpeg."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    stderr = result.stderr

    timestamps = []
    for match in re.finditer(r"pts_time:(\d+\.?\d*)", stderr):
        timestamps.append(float(match.group(1)))
    return sorted(set(timestamps))


def _detect_silence(video_path: Path) -> List[dict]:
    """Detect silence boundaries → infer speech segments."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", f"silencedetect=n={SILENCE_NOISE_DB}dB:d={SILENCE_DURATION}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    stderr = result.stderr

    silences = []
    starts = re.findall(r"silence_start: (\d+\.?\d*)", stderr)
    ends = re.findall(r"silence_end: (\d+\.?\d*)", stderr)

    for s, e in zip(starts, ends):
        silences.append({"start": float(s), "end": float(e)})

    return silences


def _extract_audio(video_path: Path, work_dir: Path) -> Path:
    """Extract audio track to WAV."""
    audio_path = work_dir / "audio.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[:300]}")
    return audio_path


def _extract_subtitles(video_path: Path, work_dir: Path) -> Optional[str]:
    """Try to extract embedded subtitles from the video."""
    srt_path = work_dir / "subs.srt"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-map", "0:s:0", str(srt_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0 and srt_path.is_file() and srt_path.stat().st_size > 10:
        return srt_path.read_text(errors="replace")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# 3. AI-POWERED MOMENT DETECTION
# ═════════════════════════════════════════════════════════════════════════════

def _build_analysis_prompt(
    metadata: dict,
    scenes: List[float],
    silences: List[dict],
    subtitle_text: Optional[str],
    clip_count: int,
    clip_length: int,
) -> str:
    """Build the Claude prompt for viral moment identification."""
    duration = metadata["duration"]

    # Build speech segments from silence gaps
    speech_segments = []
    if silences:
        # Speech is between silences
        prev_end = 0.0
        for s in silences:
            if s["start"] - prev_end > 1.0:
                speech_segments.append({"start": round(prev_end, 1), "end": round(s["start"], 1)})
            prev_end = s["end"]
        if duration - prev_end > 1.0:
            speech_segments.append({"start": round(prev_end, 1), "end": round(duration, 1)})

    prompt = f"""Analyze this video and identify the {clip_count} most viral/engaging moments for short-form clips.

## Video Metadata
- Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)
- Resolution: {metadata['width']}x{metadata['height']}
- FPS: {metadata['fps']}

## Scene Changes (visual transitions at these timestamps):
{json.dumps(scenes[:100], indent=2) if scenes else "No significant scene changes detected."}

## Speech Segments (periods with active speech):
{json.dumps(speech_segments[:50], indent=2) if speech_segments else "No clear speech segments detected."}
"""

    if subtitle_text:
        # Truncate to avoid token limits
        sub_preview = subtitle_text[:8000]
        prompt += f"""
## Transcript/Subtitles:
{sub_preview}
"""

    prompt += f"""
## Task
Identify exactly {clip_count} clip candidates, each approximately {clip_length} seconds long.

For each clip, consider:
1. **Hook strength**: Does it open with something attention-grabbing?
2. **Emotional arc**: Does the segment have a beginning, middle, payoff?
3. **Speech density**: Segments with continuous speech tend to perform better.
4. **Visual dynamism**: More scene changes = more visually engaging.
5. **Standalone value**: Can someone understand it without watching the full video?

## Response Format (JSON only, no markdown fence)
{{
  "clips": [
    {{
      "title": "Short catchy title for this clip",
      "start_sec": 0.0,
      "end_sec": 60.0,
      "virality_score": 85,
      "hook": "Opening hook text to overlay on the clip",
      "reasoning": "Why this moment is engaging",
      "transcript_snippet": "Key quote from this segment if available"
    }}
  ]
}}

Rules:
- virality_score: 1-100
- Clips must not overlap
- start_sec and end_sec must be within 0 and {duration:.1f}
- Each clip should be between {max(15, clip_length - 15)} and {clip_length + 15} seconds
- Sort by virality_score descending
- Return valid JSON only
"""
    return prompt


def _analyze_with_claude(prompt: str) -> Optional[List[dict]]:
    """Send analysis prompt to Claude and parse response."""
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY configured, falling back to scene-based detection")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        data = json.loads(text)
        return data.get("clips", [])
    except Exception as e:
        logger.error("Claude analysis failed: %s", e)
        return None


def _fallback_moment_detection(
    metadata: dict,
    scenes: List[float],
    silences: List[dict],
    clip_count: int,
    clip_length: int,
) -> List[dict]:
    """Heuristic-based moment detection when Claude is unavailable."""
    duration = metadata["duration"]
    clips = []

    # Build speech density map
    speech_segments = []
    if silences:
        prev_end = 0.0
        for s in silences:
            if s["start"] - prev_end > 1.0:
                speech_segments.append((prev_end, s["start"]))
            prev_end = s["end"]
        if duration - prev_end > 1.0:
            speech_segments.append((prev_end, duration))

    # Score windows of clip_length seconds
    step = max(5, clip_length // 4)
    candidates = []
    for start in range(0, max(1, int(duration - clip_length)), step):
        end = min(start + clip_length, duration)
        # Scene density score
        scene_count = sum(1 for s in scenes if start <= s <= end)
        # Speech coverage score
        speech_secs = sum(
            min(seg_e, end) - max(seg_s, start)
            for seg_s, seg_e in speech_segments
            if seg_s < end and seg_e > start
        )
        speech_ratio = speech_secs / max(end - start, 1)
        # Combined score
        score = int((scene_count * 10 + speech_ratio * 70 + (10 if start < 30 else 0)))
        score = min(score, 100)
        candidates.append({
            "title": f"Clip at {_fmt_time(start)}",
            "start_sec": float(start),
            "end_sec": float(end),
            "virality_score": score,
            "hook": "",
            "reasoning": "Auto-detected based on scene changes and speech density",
            "transcript_snippet": "",
        })

    # Sort by score, pick non-overlapping
    candidates.sort(key=lambda c: c["virality_score"], reverse=True)
    for c in candidates:
        if len(clips) >= clip_count:
            break
        overlaps = any(
            not (c["end_sec"] <= ex["start_sec"] or c["start_sec"] >= ex["end_sec"])
            for ex in clips
        )
        if not overlaps:
            clips.append(c)

    # Sort by time
    clips.sort(key=lambda c: c["start_sec"])
    return clips


def _identify_moments(
    video_path: Path,
    metadata: dict,
    work_dir: Path,
    clip_config: dict,
    cb: ProgressCallback,
) -> List[dict]:
    """Orchestrate scene/silence detection + AI analysis."""
    clip_count = clip_config.get("clip_count", DEFAULT_CLIP_COUNT)
    clip_length = clip_config.get("clip_length", DEFAULT_CLIP_LENGTH)

    _progress(cb, "analyzing", 15, "Detecting scene changes...")
    scenes = _detect_scenes(video_path)

    _progress(cb, "analyzing", 25, "Detecting speech segments...")
    silences = _detect_silence(video_path)

    _progress(cb, "analyzing", 30, "Extracting subtitles...")
    subtitle_text = _extract_subtitles(video_path, work_dir)

    _progress(cb, "analyzing", 35, "AI analysis of viral moments...")
    prompt = _build_analysis_prompt(metadata, scenes, silences, subtitle_text, clip_count, clip_length)
    clips = _analyze_with_claude(prompt)

    if clips is None:
        _progress(cb, "analyzing", 40, "Using scene-based detection (AI unavailable)...")
        clips = _fallback_moment_detection(metadata, scenes, silences, clip_count, clip_length)

    # Validate and clamp timestamps
    duration = metadata["duration"]
    validated = []
    for c in clips:
        c["start_sec"] = max(0, float(c.get("start_sec", 0)))
        c["end_sec"] = min(duration, float(c.get("end_sec", c["start_sec"] + clip_length)))
        if c["end_sec"] - c["start_sec"] < 5:
            continue
        c["virality_score"] = max(1, min(100, int(c.get("virality_score", 50))))
        c.setdefault("title", f"Clip at {_fmt_time(c['start_sec'])}")
        c.setdefault("hook", "")
        c.setdefault("transcript_snippet", "")
        validated.append(c)

    validated.sort(key=lambda c: c["virality_score"], reverse=True)
    return validated[:clip_count]


# ═════════════════════════════════════════════════════════════════════════════
# 4. CLIP EXTRACTION & REFRAMING
# ═════════════════════════════════════════════════════════════════════════════

def _get_crop_filter(src_w: int, src_h: int, target_ratio: str) -> Optional[str]:
    """Return ffmpeg crop filter for aspect ratio conversion."""
    ratios = {
        "9:16": (9, 16),
        "1:1": (1, 1),
        "16:9": (16, 9),
        "4:5": (4, 5),
    }
    if target_ratio not in ratios:
        return None

    tw, th = ratios[target_ratio]
    target_ar = tw / th
    src_ar = src_w / max(src_h, 1)

    if abs(src_ar - target_ar) < 0.05:
        return None  # Already correct ratio

    if target_ar < src_ar:
        # Crop width (e.g., 16:9 → 9:16)
        new_w = int(src_h * target_ar)
        new_w = new_w - (new_w % 2)  # Ensure even
        x_offset = (src_w - new_w) // 2
        return f"crop={new_w}:{src_h}:{x_offset}:0"
    else:
        # Crop height
        new_h = int(src_w / target_ar)
        new_h = new_h - (new_h % 2)
        y_offset = (src_h - new_h) // 2
        return f"crop={src_w}:{new_h}:0:{y_offset}"


def _extract_clip(
    video_path: Path,
    clip_data: dict,
    output_path: Path,
    metadata: dict,
    clip_config: dict,
) -> Path:
    """Extract a single clip from the source video."""
    start = clip_data["start_sec"]
    duration = clip_data["end_sec"] - start
    ratio = clip_config.get("ratio", DEFAULT_RATIO)
    style = clip_config.get("style", "default")

    filters = []

    # Aspect ratio crop
    crop = _get_crop_filter(metadata["width"], metadata["height"], ratio)
    if crop:
        filters.append(crop)

    # Scale to standard dimensions
    scale_map = {
        "9:16": "1080:1920",
        "1:1": "1080:1080",
        "16:9": "1920:1080",
        "4:5": "1080:1350",
    }
    target_size = scale_map.get(ratio)
    if target_size:
        filters.append(f"scale={target_size}:force_original_aspect_ratio=decrease")
        w, h = target_size.split(":")
        filters.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")

    # Fade transitions
    filters.append(f"fade=t=in:st=0:d={FADE_DURATION}")
    filters.append(f"fade=t=out:st={duration - FADE_DURATION}:d={FADE_DURATION}")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
    ]

    if filters:
        cmd += ["-vf", ",".join(filters)]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        # Stream copy when no filters needed
        cmd += [
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Clip extraction failed: {result.stderr[:400]}")
    return output_path


# ═════════════════════════════════════════════════════════════════════════════
# 5. CAPTION BURNING
# ═════════════════════════════════════════════════════════════════════════════

def _generate_srt(transcript: str, start_sec: float, end_sec: float, output_path: Path) -> Path:
    """Generate a simple SRT file from transcript text."""
    duration = end_sec - start_sec
    words = transcript.split()
    if not words:
        output_path.write_text("")
        return output_path

    # Distribute words across the duration
    words_per_group = 4
    groups = [words[i:i + words_per_group] for i in range(0, len(words), words_per_group)]
    time_per_group = duration / max(len(groups), 1)

    lines = []
    for idx, group in enumerate(groups):
        s = idx * time_per_group
        e = min(s + time_per_group, duration)
        lines.append(str(idx + 1))
        lines.append(f"{_srt_time(s)} --> {_srt_time(e)}")
        lines.append(" ".join(group))
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _burn_captions(
    clip_path: Path,
    transcript: str,
    start_sec: float,
    end_sec: float,
    work_dir: Path,
) -> Path:
    """Burn word-by-word animated captions onto the clip."""
    if not transcript.strip():
        return clip_path

    srt_path = work_dir / f"caption_{clip_path.stem}.srt"
    _generate_srt(transcript, start_sec, end_sec, srt_path)

    if srt_path.stat().st_size < 5:
        return clip_path

    output_path = clip_path.with_name(clip_path.stem + "_captioned.mp4")

    # Use ASS-style subtitles for better appearance
    font_arg = CAPTION_FONT if Path(CAPTION_FONT).is_file() else "Sans"
    style = (
        f"FontName={Path(font_arg).stem},"
        f"FontSize={CAPTION_FONTSIZE},"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"Outline={CAPTION_OUTLINE_WIDTH},"
        f"Shadow=1,"
        f"Alignment=2,"
        f"MarginV=60"
    )
    sub_filter = f"subtitles='{srt_path}':force_style='{style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-vf", sub_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning("Caption burn failed, returning uncaptioned clip: %s", result.stderr[:200])
        return clip_path

    # Replace original with captioned version
    clip_path.unlink(missing_ok=True)
    output_path.rename(clip_path)
    return clip_path


# ═════════════════════════════════════════════════════════════════════════════
# 6. HOOK OVERLAY
# ═════════════════════════════════════════════════════════════════════════════

def _burn_hook(clip_path: Path, hook_text: str) -> Path:
    """Burn hook text overlay on the first few seconds of the clip."""
    if not hook_text.strip():
        return clip_path

    output_path = clip_path.with_name(clip_path.stem + "_hooked.mp4")

    # Escape special characters for drawtext
    escaped = hook_text.replace("'", "'\\''").replace(":", "\\:")
    # Wrap long text
    if len(escaped) > 40:
        mid = len(escaped) // 2
        sp = escaped.rfind(" ", 0, mid + 10)
        if sp > 0:
            escaped = escaped[:sp] + "\n" + escaped[sp + 1:]

    font_arg = CAPTION_FONT if Path(CAPTION_FONT).is_file() else "Sans"

    drawtext = (
        f"drawtext=text='{escaped}'"
        f":fontfile='{font_arg}'"
        f":fontsize=42"
        f":fontcolor=white"
        f":borderw=3"
        f":bordercolor=black"
        f":x=(w-text_w)/2"
        f":y=h*0.08"
        f":enable='between(t,0,{HOOK_DURATION})'"
        f":alpha='if(lt(t,0.3),t/0.3,if(gt(t,{HOOK_DURATION - 0.3}),({HOOK_DURATION}-t)/0.3,1))'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning("Hook overlay failed: %s", result.stderr[:200])
        return clip_path

    clip_path.unlink(missing_ok=True)
    output_path.rename(clip_path)
    return clip_path


# ═════════════════════════════════════════════════════════════════════════════
# 7. THUMBNAIL GENERATION
# ═════════════════════════════════════════════════════════════════════════════

def _generate_thumbnail(video_path: Path, timestamp: float, output_path: Path) -> Path:
    """Extract a single frame as a thumbnail."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.warning("Thumbnail generation failed: %s", result.stderr[:200])
    return output_path


# ═════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def _fmt_time(seconds: float) -> str:
    """Format seconds as M:SS."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


# ═════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def run_clipper(clip_job_id: str, clip_config: dict, progress_callback: ProgressCallback = None) -> dict:
    """
    Main clipper engine entry point.

    Args:
        clip_job_id: Unique identifier for this clipping job.
        clip_config: Configuration dict with keys:
            - source: "url" | "file" | "upload" | "job"
            - url: Video URL (for source="url")
            - job_id: Existing job ID (for source="job")
            - video_path: Local file path (for source="file"/"upload")
            - clip_count: Number of clips to generate (default 5)
            - clip_length: Target clip length in seconds (default 60)
            - ratio: "9:16" | "1:1" | "16:9" | "4:5" (default "9:16")
            - style: Style preset (default "default")
            - captions: bool — burn captions (default True)
            - hook_overlay: bool — burn hook text (default True)
            - user_id: User identifier for output path namespacing.
        progress_callback: Optional function(status, progress, step).

    Returns:
        dict with status, clips list, source_duration, transcript_preview.
    """
    cb = progress_callback
    clip_count = clip_config.get("clip_count", DEFAULT_CLIP_COUNT)
    clip_length = clip_config.get("clip_length", DEFAULT_CLIP_LENGTH)
    do_captions = clip_config.get("captions", True)
    do_hook = clip_config.get("hook_overlay", True)

    # Set up output directories
    clips_dir = Path(config.OUTPUT_DIR) / "clips" / clip_job_id
    clips_dir.mkdir(parents=True, exist_ok=True)
    work_dir = clips_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── Step 1: Acquire video ───────────────────────────────────────────
        _progress(cb, "downloading", 2, "Acquiring source video...")
        video_path = _acquire_video(clip_config, work_dir, cb)
        _progress(cb, "downloading", 10, "Video acquired")

        # ── Step 2: Get metadata ────────────────────────────────────────────
        _progress(cb, "analyzing", 12, "Reading video metadata...")
        metadata = _get_video_metadata(video_path)
        logger.info(
            "Source video: %.1fs, %dx%d, %s",
            metadata["duration"], metadata["width"], metadata["height"], metadata["codec"],
        )

        if metadata["duration"] < 10:
            return {
                "status": "error",
                "error": "Video is too short (under 10 seconds)",
                "clips": [],
                "source_duration": metadata["duration"],
                "transcript_preview": "",
            }

        # ── Step 3: AI moment detection ─────────────────────────────────────
        moments = _identify_moments(video_path, metadata, work_dir, clip_config, cb)

        if not moments:
            return {
                "status": "error",
                "error": "Could not identify any clip-worthy moments",
                "clips": [],
                "source_duration": metadata["duration"],
                "transcript_preview": "",
            }

        # ── Step 4: Extract & process clips ─────────────────────────────────
        output_clips = []
        total = len(moments)

        for i, moment in enumerate(moments):
            clip_num = i + 1
            pct = 45 + int(50 * clip_num / total)
            _progress(cb, "clipping", pct, f"Extracting clip {clip_num}/{total}...")

            clip_filename = f"clip_{clip_num}.mp4"
            clip_path = clips_dir / clip_filename
            thumb_filename = f"clip_{clip_num}_thumb.jpg"
            thumb_path = clips_dir / thumb_filename

            try:
                # Extract clip
                _extract_clip(video_path, moment, clip_path, metadata, clip_config)

                # Burn captions
                if do_captions:
                    transcript = moment.get("transcript_snippet", "")
                    if transcript:
                        _progress(cb, "captioning", pct, f"Adding captions to clip {clip_num}...")
                        _burn_captions(
                            clip_path, transcript,
                            moment["start_sec"], moment["end_sec"],
                            work_dir,
                        )

                # Burn hook overlay
                if do_hook and moment.get("hook"):
                    _progress(cb, "hook", pct, f"Adding hook to clip {clip_num}...")
                    _burn_hook(clip_path, moment["hook"])

                # Generate thumbnail at the midpoint of the clip
                thumb_time = (moment["end_sec"] - moment["start_sec"]) / 3  # 1/3 in for interesting frame
                _generate_thumbnail(clip_path, thumb_time, thumb_path)

                # Build download URL
                relative_path = f"clips/{clip_job_id}/{clip_filename}"
                download_url = f"/output/{relative_path}"

                output_clips.append({
                    "title": moment.get("title", f"Clip {clip_num}"),
                    "start_time": _fmt_time(moment["start_sec"]),
                    "end_time": _fmt_time(moment["end_sec"]),
                    "start_sec": moment["start_sec"],
                    "end_sec": moment["end_sec"],
                    "virality_score": moment["virality_score"],
                    "hook": moment.get("hook", ""),
                    "file_path": str(clip_path),
                    "thumbnail_path": str(thumb_path) if thumb_path.is_file() else "",
                    "download_url": download_url,
                    "transcript": moment.get("transcript_snippet", ""),
                })

            except Exception as e:
                logger.error("Failed to process clip %d: %s", clip_num, e)
                continue

        # ── Step 5: Clean up work directory ─────────────────────────────────
        _progress(cb, "finalizing", 97, "Cleaning up...")
        for f in work_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
        try:
            work_dir.rmdir()
        except Exception:
            pass

        # ── Build transcript preview ────────────────────────────────────────
        transcript_preview = " | ".join(
            c.get("transcript", "")[:100] for c in output_clips if c.get("transcript")
        )[:500]

        _progress(cb, "done", 100, "Clipping complete!")

        return {
            "status": "done",
            "clips": output_clips,
            "source_duration": metadata["duration"],
            "transcript_preview": transcript_preview,
        }

    except Exception as e:
        logger.exception("Clipper engine failed for job %s", clip_job_id)
        return {
            "status": "error",
            "error": str(e),
            "clips": [],
            "source_duration": 0,
            "transcript_preview": "",
        }
