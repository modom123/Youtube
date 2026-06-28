"""
Editing Room — Enhanced video assembly engine connected to the jobs system.

Three production studios:
  hollywood   — cinematic long-form (16:9, ~50-60s)
  studio56    — vertical viral shorts (9:16, ~30s)
  commercials — product ads (16:9, ~15-20s)

Each studio produces a complete MP4 with:
  - AI-generated video clip backgrounds (via Higgsfield) OR gradient fallback
  - Lower-third title bars and text overlays
  - Ken Burns zoom animation
  - Synthesized ambient background music
  - Title card + section cards + outro
  - Text shadows and watermarks
"""
import math
import random
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip,
    ImageClip,
    VideoFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from moviepy.video.fx import FadeIn, FadeOut

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

STUDIO_PRESETS = {
    "hollywood": {
        "label": "Hollywood Studio",
        "width": 1920, "height": 1080, "fps": 30,
        "music_key": "ambient_dark",
        "default_topic": "The Silent Revolution: How AI Changed Everything",
    },
    "studio56": {
        "label": "Studio 56",
        "width": 1080, "height": 1920, "fps": 30,
        "music_key": "upbeat",
        "default_topic": "5 Things Nobody Tells You About Going Viral",
    },
    "commercials": {
        "label": "Commercial Studio",
        "width": 1920, "height": 1080, "fps": 30,
        "music_key": "corporate",
        "default_topic": "Social Optimize — Your Content Engine",
    },
}

# Color palettes per studio
PALETTES = {
    "hollywood": [
        {"bg": [(8, 8, 25), (25, 15, 50)], "accent": (100, 80, 255), "tc": (255, 255, 255), "particles": "bokeh_blue"},
        {"bg": [(50, 8, 8), (25, 4, 4)], "accent": (255, 80, 80), "tc": (255, 220, 220), "particles": "embers"},
        {"bg": [(4, 15, 50), (8, 30, 70)], "accent": (60, 160, 255), "tc": (200, 225, 255), "particles": "bokeh_blue"},
        {"bg": [(35, 25, 4), (50, 40, 8)], "accent": (255, 200, 60), "tc": (255, 235, 170), "particles": "sparkle"},
    ],
    "studio56": [
        {"bg": [(100, 0, 180), (180, 0, 90)], "accent": (255, 100, 255), "tc": (255, 255, 255), "particles": "neon"},
        {"bg": [(0, 40, 130), (0, 80, 180)], "accent": (0, 200, 255), "tc": (255, 255, 100), "particles": "bokeh_blue"},
        {"bg": [(0, 60, 30), (0, 120, 50)], "accent": (0, 255, 130), "tc": (255, 255, 255), "particles": "sparkle"},
        {"bg": [(130, 40, 0), (180, 70, 0)], "accent": (255, 160, 0), "tc": (255, 255, 255), "particles": "embers"},
        {"bg": [(70, 0, 110), (130, 0, 180)], "accent": (255, 200, 60), "tc": (255, 220, 100), "particles": "neon"},
    ],
    "commercials": [
        {"bg": [(15, 15, 15), (30, 30, 30)], "accent": (255, 70, 70), "tc": (255, 100, 100), "particles": "embers"},
        {"bg": [(0, 30, 90), (0, 60, 150)], "accent": (0, 180, 255), "tc": (255, 255, 255), "particles": "bokeh_blue"},
        {"bg": [(0, 80, 40), (0, 150, 70)], "accent": (255, 255, 100), "tc": (255, 255, 255), "particles": "sparkle"},
    ],
}


# ── Visual helpers ─────────────────────────────────────────────────────────

def _radial_gradient(w, h, c1, c2, bias=0.6):
    arr = np.zeros((h, w, 3), dtype=np.float32)
    cx, cy = w / 2, h / 2
    max_r = math.sqrt(cx ** 2 + cy ** 2)
    yc, xc = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xc - cx) ** 2 + (yc - cy) ** 2)
    ratio = np.clip(dist / (max_r * bias), 0, 1)
    for c in range(3):
        arr[:, :, c] = c1[c] * (1 - ratio) + c2[c] * ratio
    return np.clip(arr, 0, 255).astype(np.uint8)


def _add_particles(img, style, count=50, seed=42):
    rng = random.Random(seed)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    for _ in range(count):
        x, y = rng.randint(0, w), rng.randint(0, h)
        if style == "bokeh_blue":
            r, alpha = rng.randint(8, 40), rng.randint(15, 50)
            color = (100, 160, 255, alpha)
        elif style == "embers":
            r, alpha = rng.randint(2, 8), rng.randint(40, 120)
            color = (255, rng.randint(80, 180), 0, alpha)
        elif style == "sparkle":
            r, alpha = rng.randint(1, 5), rng.randint(60, 200)
            color = (255, 255, rng.randint(150, 255), alpha)
        elif style == "neon":
            r, alpha = rng.randint(5, 25), rng.randint(20, 70)
            color = (rng.randint(150, 255), 0, rng.randint(150, 255), alpha)
        else:
            r, alpha = rng.randint(3, 15), rng.randint(20, 60)
            color = (255, 255, 255, alpha)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _lower_third(draw, w, h, heading, accent, is_portrait=False):
    bar_h = int(h * (0.08 if not is_portrait else 0.05))
    bar_y = int(h * (0.72 if not is_portrait else 0.78))
    draw.rectangle([0, bar_y, w, bar_y + bar_h], fill=(0, 0, 0, 160))
    stripe_h = max(4, bar_h // 12)
    draw.rectangle([0, bar_y, w, bar_y + stripe_h], fill=accent + (220,))
    fs = max(18, min(bar_h - 16, 42))
    try:
        font = ImageFont.truetype(FONT_PATH, fs)
    except Exception:
        font = ImageFont.load_default()
    draw.text((int(w * 0.04), bar_y + (bar_h - fs) // 2), heading, fill=(255, 255, 255, 240), font=font)


def _watermark(draw, w, h, text="SOCIAL OPTIMIZE"):
    fs = max(12, min(w // 50, 22))
    try:
        font = ImageFont.truetype(FONT_PATH_REGULAR, fs)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((w - (bbox[2] - bbox[0]) - int(w * 0.03), int(h * 0.03)), text, fill=(255, 255, 255, 60), font=font)


def _wrap_text(text, max_chars):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if len(test) <= max_chars:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _section_frame(heading, narration, palette, w, h, idx, total, is_portrait=False):
    bg = _radial_gradient(w, h, palette["bg"][0], palette["bg"][1])
    img = Image.fromarray(bg).convert("RGBA")
    _add_particles(img, palette.get("particles", "bokeh_blue"), count=50, seed=idx * 17 + 7)
    draw = ImageDraw.Draw(img, "RGBA")
    _lower_third(draw, w, h, heading, palette["accent"], is_portrait)
    _watermark(draw, w, h)

    body_sz = max(22, min(w // 20, 52)) if not is_portrait else max(22, min(w // 16, 44))
    try:
        font = ImageFont.truetype(FONT_PATH, body_sz)
    except Exception:
        font = ImageFont.load_default()

    lines = _wrap_text(narration, max(20, w // (body_sz // 2 + 2)))
    lh = body_sz + 14
    y0 = int(h * 0.35) - (len(lines) * lh) // 2
    tc = palette["tc"]
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lx = (w - (bbox[2] - bbox[0])) // 2
        ly = y0 + i * lh
        draw.text((lx + 2, ly + 2), line, fill=(0, 0, 0, 120), font=font)
        draw.text((lx, ly), line, fill=tc + (255,), font=font)

    # Section dots
    dot_y = int(h * 0.92)
    dot_sp = 24
    dx_start = (w - (total - 1) * dot_sp) // 2
    for i in range(total):
        dx = dx_start + i * dot_sp
        r = 5 if i == idx else 3
        c = palette["accent"] + (220,) if i == idx else (255, 255, 255, 60)
        draw.ellipse([dx - r, dot_y - r, dx + r, dot_y + r], fill=c)

    return np.array(img.convert("RGB"))


def _title_card(w, h, title, subtitle, accent, bg_colors):
    bg = _radial_gradient(w, h, bg_colors[0], bg_colors[1], bias=0.5)
    img = Image.fromarray(bg).convert("RGBA")
    _add_particles(img, "sparkle", count=60, seed=99)
    draw = ImageDraw.Draw(img, "RGBA")

    tsz = max(30, min(w // 12, 80))
    try:
        tfont = ImageFont.truetype(FONT_PATH, tsz)
    except Exception:
        tfont = ImageFont.load_default()
    lines = _wrap_text(title, max(15, w // (tsz // 2 + 2)))
    lh = tsz + 12
    y0 = h // 2 - (len(lines) * lh) // 2 - 30
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=tfont)
        lx = (w - (bbox[2] - bbox[0])) // 2
        ly = y0 + i * lh
        draw.text((lx + 3, ly + 3), line, fill=(0, 0, 0, 140), font=tfont)
        draw.text((lx, ly), line, fill=(255, 255, 255, 245), font=tfont)

    # Accent line
    ly = y0 + len(lines) * lh + 15
    lw = min(w // 3, 300)
    draw.rectangle([(w - lw) // 2, ly, (w + lw) // 2, ly + 4], fill=accent + (200,))

    ssz = max(16, min(w // 30, 32))
    try:
        sfont = ImageFont.truetype(FONT_PATH_REGULAR, ssz)
    except Exception:
        sfont = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), subtitle, font=sfont)
    draw.text(((w - (bbox[2] - bbox[0])) // 2, ly + 24), subtitle, fill=accent + (180,), font=sfont)
    _watermark(draw, w, h)
    return np.array(img.convert("RGB"))


def _outro_card(w, h, accent, bg_colors):
    bg = _radial_gradient(w, h, bg_colors[0], bg_colors[1], bias=0.5)
    img = Image.fromarray(bg).convert("RGBA")
    _add_particles(img, "sparkle", count=80, seed=123)
    draw = ImageDraw.Draw(img, "RGBA")
    sz = max(28, min(w // 14, 64))
    try:
        font = ImageFont.truetype(FONT_PATH, sz)
    except Exception:
        font = ImageFont.load_default()
    text = "SOCIAL OPTIMIZE"
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((w - (bbox[2] - bbox[0])) // 2, h // 2 - sz), text, fill=accent + (240,), font=font)
    ssz = max(14, sz // 2)
    try:
        sfont = ImageFont.truetype(FONT_PATH_REGULAR, ssz)
    except Exception:
        sfont = ImageFont.load_default()
    sub = "socialoptimize.online"
    bbox = draw.textbbox((0, 0), sub, font=sfont)
    draw.text(((w - (bbox[2] - bbox[0])) // 2, h // 2 + 20), sub, fill=(255, 255, 255, 120), font=sfont)
    return np.array(img.convert("RGB"))


# ── Audio helpers ──────────────────────────────────────────────────────────

def _tts_espeak(text, output_path):
    wav = str(output_path).replace(".mp3", ".wav")
    subprocess.run(
        ["espeak-ng", "-w", wav, "-v", "en-us", "-s", "150", "-p", "45", "-a", "180", text],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav, "-codec:a", "libmp3lame", "-b:a", "192k", str(output_path)],
        check=True, capture_output=True,
    )
    Path(wav).unlink(missing_ok=True)


def _synth_bgm(output_path, duration, style="ambient_dark"):
    freq_map = {
        "ambient_dark": ([80, 120, 160], 0.3, 0.4, 0.08),
        "upbeat": ([220, 330, 440], 4, 0.5, 0.06),
        "corporate": ([130, 196, 262], 1, 0.3, 0.07),
    }
    freqs, trem_f, trem_d, vol = freq_map.get(style, freq_map["ambient_dark"])
    af = (
        f"sine=f={freqs[0]}:d={duration}[s1];"
        f"sine=f={freqs[1]}:d={duration}[s2];"
        f"sine=f={freqs[2]}:d={duration}[s3];"
        f"[s1][s2]amix=inputs=2[m1];[m1][s3]amix=inputs=2,"
        f"tremolo=f={trem_f}:d={trem_d},volume={vol},"
        f"afade=t=in:d=2,afade=t=out:st={max(0, duration - 3)}:d=3"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", af.split(",")[0],
         "-filter_complex", af, "-t", str(duration),
         "-codec:a", "libmp3lame", "-b:a", "128k", str(output_path)],
        check=True, capture_output=True,
    )


def _mix_audio(voice_path, music_path, output_path, pad_before=3.0, pad_after=2.5, music_vol=0.2):
    """Mix voiceover (padded with silence for title/outro) with background music."""
    dur_cmd = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(voice_path)],
        capture_output=True, text=True,
    )
    voice_dur = float(dur_cmd.stdout.strip())
    full_dur = pad_before + voice_dur + pad_after

    padded = str(output_path).replace(".mp3", "_padded.mp3")
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-i", str(voice_path),
         "-filter_complex",
         f"[0:a]atrim=0:{pad_before}[pad];[pad][1:a]concat=n=2:v=0:a=1,apad=pad_dur={pad_after}",
         "-t", str(full_dur), "-codec:a", "libmp3lame", "-b:a", "192k", padded],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", padded, "-i", str(music_path),
         "-filter_complex",
         f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2",
         "-codec:a", "libmp3lame", "-b:a", "192k", str(output_path)],
        check=True, capture_output=True,
    )
    Path(padded).unlink(missing_ok=True)
    return full_dur


# ── Video clip helpers ─────────────────────────────────────────────────────

def _clip_with_overlay(clip_path, heading, palette, w, h, duration, idx, total, is_portrait=False):
    """Use an AI-generated video clip as background with text overlay."""
    try:
        vclip = VideoFileClip(str(clip_path))
        # Resize to fill target dimensions
        vw, vh = vclip.size
        scale = max(w / vw, h / vh)
        nw, nh = int(vw * scale), int(vh * scale)
        vclip = vclip.resized((nw, nh))
        # Center crop
        x_off = (nw - w) // 2
        y_off = (nh - h) // 2
        vclip = vclip.cropped(x1=x_off, y1=y_off, x2=x_off + w, y2=y_off + h)
        # Loop or trim to match duration
        if vclip.duration < duration:
            loops = int(duration / vclip.duration) + 1
            from moviepy import concatenate_videoclips as _cat
            vclip = _cat([vclip] * loops).subclipped(0, duration)
        else:
            vclip = vclip.subclipped(0, duration)

        # Create text overlay frame
        overlay_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay_img, "RGBA")
        # Semi-transparent bottom gradient for readability
        for y in range(h // 2, h):
            alpha = int(140 * (y - h // 2) / (h // 2))
            draw.rectangle([0, y, w, y + 1], fill=(0, 0, 0, alpha))
        _lower_third(draw, w, h, heading, palette["accent"], is_portrait)
        _watermark(draw, w, h)
        # Section dots
        dot_y = int(h * 0.92)
        dot_sp = 24
        dx_start = (w - (total - 1) * dot_sp) // 2
        for i in range(total):
            dx = dx_start + i * dot_sp
            r = 5 if i == idx else 3
            c = palette["accent"] + (220,) if i == idx else (255, 255, 255, 60)
            draw.ellipse([dx - r, dot_y - r, dx + r, dot_y + r], fill=c)

        overlay_arr = np.array(overlay_img)
        overlay_clip = ImageClip(overlay_arr).with_duration(duration).with_fps(30)

        composite = CompositeVideoClip([vclip, overlay_clip], size=(w, h))
        return composite
    except Exception as e:
        print(f"[editing_room] Clip overlay failed for {clip_path}: {e}, falling back to gradient")
        return None


def generate_section_clips(sections, studio, output_dir, progress_cb=None):
    """Generate Higgsfield AI clips for each section. Returns dict of {index: clip_path}."""
    from generators.higgsfield_mcp import generate_clips_via_mcp
    preset = STUDIO_PRESETS[studio]
    w, h = preset["width"], preset["height"]
    ar = "9:16" if h > w else "16:9"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompts = []
    for sec in sections:
        visual_prompt = sec.get("visual_prompt", "")
        if not visual_prompt:
            visual_prompt = f"Cinematic video: {sec['narration'][:120]}. Professional quality, smooth motion."
        prompts.append(visual_prompt)

    if progress_cb:
        progress_cb(f"Generating {len(prompts)} AI clips via Higgsfield...", 5)

    model = "kling3_0_turbo"
    clips = generate_clips_via_mcp(
        prompts=prompts,
        output_dir=output_dir / "clips",
        model_id=model,
        aspect_ratio=ar,
        duration=5,
    )

    clip_map = {}
    for i, path in enumerate(clips):
        if path and path.exists() and path.stat().st_size > 10_000:
            clip_map[i] = path

    if progress_cb:
        progress_cb(f"Generated {len(clip_map)}/{len(prompts)} clips", 15)

    return clip_map


# ── Ken Burns ──────────────────────────────────────────────────────────────

def _ken_burns(clip, tw, th, z_start=1.0, z_end=1.08):
    from moviepy import VideoClip
    dur = clip.duration

    def make_frame(t):
        progress = t / max(dur, 0.01)
        z = z_start + (z_end - z_start) * progress
        frame = clip.get_frame(t)
        h, w = frame.shape[:2]
        nw, nh = int(w / z), int(h / z)
        x1, y1 = (w - nw) // 2, (h - nh) // 2
        cropped = frame[y1:y1 + nh, x1:x1 + nw]
        return np.array(Image.fromarray(cropped).resize((tw, th), Image.LANCZOS))

    return VideoClip(make_frame, duration=dur).with_fps(clip.fps or 30)


# ── Main production function ──────────────────────────────────────────────

def _image_background(image_path, heading, palette, w, h, duration, idx, total, is_portrait=False):
    """Use an uploaded image as background with text overlay."""
    try:
        img = Image.open(image_path).convert("RGBA")
        iw, ih = img.size
        scale = max(w / iw, h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = img.resize((nw, nh), Image.LANCZOS)
        x_off = (nw - w) // 2
        y_off = (nh - h) // 2
        img = img.crop((x_off, y_off, x_off + w, y_off + h))
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        for y in range(h // 2, h):
            alpha = int(140 * (y - h // 2) / (h // 2))
            draw.rectangle([0, y, w, y + 1], fill=(0, 0, 0, alpha))
        _lower_third(draw, w, h, heading, palette["accent"], is_portrait)
        _watermark(draw, w, h)
        dot_y = int(h * 0.92)
        dot_sp = 24
        dx_start = (w - (total - 1) * dot_sp) // 2
        for i in range(total):
            dx = dx_start + i * dot_sp
            r = 5 if i == idx else 3
            c = palette["accent"] + (220,) if i == idx else (255, 255, 255, 60)
            draw.ellipse([dx - r, dot_y - r, dx + r, dot_y + r], fill=c)
        composite = Image.alpha_composite(img, overlay)
        frame = np.array(composite.convert("RGB"))
        clip = ImageClip(frame).with_duration(duration).with_fps(30)
        return clip
    except Exception as e:
        print(f"[editing_room] Image background failed for {image_path}: {e}")
        return None


def produce(
    studio: str,
    topic: str,
    sections: list[dict],
    output_dir: Path,
    subtitle: str = "",
    progress_cb: Optional[Callable] = None,
    clip_paths: Optional[dict] = None,
    use_ai_clips: bool = False,
    custom_bgm_path: Optional[str] = None,
    section_media: Optional[dict] = None,
) -> dict:
    """
    Produce a complete enhanced video.

    Args:
        studio: "hollywood", "studio56", or "commercials"
        topic: Video title
        sections: List of {"heading": str, "narration": str, "visual_prompt": str (optional)}
        output_dir: Where to write output files
        subtitle: Optional subtitle for title card
        progress_cb: Optional callback(message, percent)
        clip_paths: Optional dict {section_index: Path} of pre-generated video clips
        use_ai_clips: If True, generate AI clips via Higgsfield before assembly

    Returns:
        dict with output path, duration, resolution, etc.
    """
    preset = STUDIO_PRESETS[studio]
    w, h, fps = preset["width"], preset["height"], preset["fps"]
    is_portrait = h > w
    palette_list = PALETTES.get(studio, PALETTES["hollywood"])
    output_dir.mkdir(parents=True, exist_ok=True)

    def _progress(msg, pct):
        if progress_cb:
            progress_cb(msg, pct)

    # Generate AI clips if requested
    if clip_paths is None:
        clip_paths = {}
    if use_ai_clips and not clip_paths:
        try:
            _progress("Generating AI video clips...", 5)
            clip_paths = generate_section_clips(sections, studio, output_dir, progress_cb)
        except Exception as e:
            _progress(f"AI clip generation failed ({e}), using gradient visuals", 8)
            clip_paths = {}

    _progress("Generating voiceover...", 10)
    full_narration = " ".join(s["narration"] for s in sections)
    voice_path = output_dir / "voiceover.mp3"
    _tts_espeak(full_narration, voice_path)
    voice_clip = AudioFileClip(str(voice_path))
    voice_dur = voice_clip.duration

    # Per-section timing
    _progress("Calculating section timing...", 20)
    sec_durs = []
    sec_tmps = []
    for i, sec in enumerate(sections):
        sp = output_dir / f"_sec_{i}.mp3"
        _tts_espeak(sec["narration"], sp)
        sc = AudioFileClip(str(sp))
        sec_durs.append(sc.duration + 0.8)
        sec_tmps.append(sp)
        sc.close()
    total_raw = sum(sec_durs)
    scale = voice_dur / total_raw if total_raw > 0 else 1
    sec_durs = [d * scale for d in sec_durs]

    # Background music
    title_dur, outro_dur = 3.0, 2.5
    full_dur = title_dur + voice_dur + outro_dur

    _progress("Mixing background music...", 35)
    music_path = output_dir / "bgm.mp3"
    mixed_path = output_dir / "mixed.mp3"
    has_music = False
    try:
        if custom_bgm_path and Path(custom_bgm_path).exists():
            # Use custom track from Music Studio — loop/trim to fit duration
            subprocess.run(
                ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(custom_bgm_path),
                 "-t", str(full_dur), "-codec:a", "libmp3lame", "-b:a", "192k", str(music_path)],
                check=True, capture_output=True,
            )
        else:
            _synth_bgm(music_path, full_dur, preset.get("music_key", "ambient_dark"))
        _mix_audio(voice_path, music_path, mixed_path, pad_before=title_dur, pad_after=outro_dur)
        final_audio = AudioFileClip(str(mixed_path))
        has_music = True
    except Exception:
        # Fallback: pad voice with silence
        padded = output_dir / "_padded.mp3"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                 "-i", str(voice_path), "-filter_complex",
                 f"[0:a]atrim=0:{title_dur}[pad];[pad][1:a]concat=n=2:v=0:a=1,apad=pad_dur={outro_dur}",
                 "-t", str(full_dur), "-codec:a", "libmp3lame", "-b:a", "192k", str(padded)],
                check=True, capture_output=True,
            )
            final_audio = AudioFileClip(str(padded))
        except Exception:
            final_audio = voice_clip
            title_dur, outro_dur = 0, 0
            full_dur = voice_dur

    # Build visual clips
    total_secs = len(sections)
    first_pal = palette_list[0 % len(palette_list)]
    overscan = int(w * 0.1)
    ow = w + overscan
    oh = h + int(overscan * h / w)

    _progress(f"Building title card + {total_secs} sections...", 45)
    clips = []

    # Title card
    tc_frame = _title_card(ow, oh, topic, subtitle or preset["label"], first_pal["accent"], first_pal["bg"])
    tc_clip = ImageClip(tc_frame).with_duration(title_dur).with_fps(fps)
    tc_clip = _ken_burns(tc_clip, w, h, 1.0, 1.06)
    tc_clip = tc_clip.with_effects([FadeIn(0.6), FadeOut(0.4)])
    clips.append(tc_clip)

    # Section clips
    has_ai_clips = False
    if section_media is None:
        section_media = {}
    for i, sec in enumerate(sections):
        pal = palette_list[i % len(palette_list)]
        dur = max(sec_durs[i], 1.0)

        clip = None
        # Try user-uploaded media first
        si = str(i)
        media_list = section_media.get(si, [])
        valid_media = [m for m in media_list if Path(m.get("path", "")).exists()]
        if valid_media:
            if len(valid_media) == 1:
                m = valid_media[0]
                mp = Path(m["path"])
                if m.get("type") == "video":
                    clip = _clip_with_overlay(str(mp), sec["heading"], pal, w, h, dur, i, total_secs, is_portrait)
                else:
                    clip = _image_background(str(mp), sec["heading"], pal, w, h, dur, i, total_secs, is_portrait)
            else:
                sub_dur = dur / len(valid_media)
                sub_clips = []
                for m in valid_media:
                    mp = Path(m["path"])
                    if m.get("type") == "video":
                        sc = _clip_with_overlay(str(mp), sec["heading"], pal, w, h, sub_dur, i, total_secs, is_portrait)
                    else:
                        sc = _image_background(str(mp), sec["heading"], pal, w, h, sub_dur, i, total_secs, is_portrait)
                    if sc:
                        sc = sc.with_effects([FadeIn(0.3), FadeOut(0.3)])
                        sub_clips.append(sc)
                if sub_clips:
                    clip = concatenate_videoclips(sub_clips, method="compose")
            if clip:
                has_ai_clips = True

        # Try AI video clip background
        if clip is None and i in clip_paths and clip_paths[i] and Path(clip_paths[i]).exists():
            clip = _clip_with_overlay(
                clip_paths[i], sec["heading"], pal, w, h, dur, i, total_secs, is_portrait,
            )
            if clip:
                has_ai_clips = True

        # Fallback to gradient card
        if clip is None:
            frame = _section_frame(
                sec["heading"], sec["narration"], pal, ow, oh, i, total_secs, is_portrait,
            )
            clip = ImageClip(frame).with_duration(dur).with_fps(fps)
            if i % 2 == 0:
                clip = _ken_burns(clip, w, h, 1.0, 1.08)
            else:
                clip = _ken_burns(clip, w, h, 1.06, 1.0)

        clip = clip.with_effects([FadeIn(0.5), FadeOut(0.5)])
        clips.append(clip)
        _progress(f"Section {i + 1}/{total_secs} built", 45 + int(35 * (i + 1) / total_secs))

    # Outro
    last_pal = palette_list[(total_secs - 1) % len(palette_list)]
    outro_frame = _outro_card(ow, oh, first_pal["accent"], last_pal["bg"])
    outro_clip = ImageClip(outro_frame).with_duration(outro_dur).with_fps(fps)
    outro_clip = _ken_burns(outro_clip, w, h, 1.0, 1.04)
    outro_clip = outro_clip.with_effects([FadeIn(0.4), FadeOut(0.8)])
    clips.append(outro_clip)

    # Assemble
    _progress("Compositing video...", 82)
    video = concatenate_videoclips(clips, method="compose")
    video = video.with_duration(min(video.duration, full_dur))
    video = video.with_audio(final_audio.subclipped(0, min(final_audio.duration, video.duration)))

    # Export
    output_path = output_dir / f"{studio}_ugc.mp4"
    _progress(f"Rendering {output_path.name}...", 88)
    video.write_videofile(
        str(output_path), fps=fps, codec="libx264", audio_codec="aac",
        preset="medium", bitrate="4000k", logger=None,
    )

    # Cleanup temp files
    for p in sec_tmps:
        p.unlink(missing_ok=True)
    for p in [output_dir / "bgm.mp3", output_dir / "mixed.mp3", output_dir / "_padded.mp3"]:
        p.unlink(missing_ok=True)

    duration = video.duration
    file_size = output_path.stat().st_size / (1024 * 1024)
    video.close()
    voice_clip.close()
    final_audio.close()

    _progress("Complete!", 100)

    return {
        "studio": studio,
        "label": preset["label"],
        "title": topic,
        "duration": duration,
        "resolution": f"{w}x{h}",
        "fps": fps,
        "has_music": has_music,
        "has_ai_clips": has_ai_clips,
        "file_size_mb": round(file_size, 1),
        "output_path": str(output_path),
        "sections": total_secs,
    }
