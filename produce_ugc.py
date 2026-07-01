#!/usr/bin/env python3
"""
UGC Video Producer (Enhanced) — cinematic MP4 videos with no external API keys.

Features:
  - Radial gradient backgrounds with vignette
  - Animated particle/bokeh overlays
  - Lower-third title bars with brand styling
  - Synthesized ambient background music
  - Ken Burns zoom animation
  - Subtitle-style word-by-word text reveal
  - Smooth crossfade transitions between sections
  - Section number badges

Studios:
  hollywood   — cinematic long-form (~50s, 16:9)
  studio56    — short-form viral (~30s, 9:16)
  commercials — product ad (~17s, 16:9)

Usage:
  python produce_ugc.py                    # all three studios
  python produce_ugc.py --studio hollywood # single studio
"""
import argparse
import json
import math
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import (
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
)
from moviepy.video.fx import FadeIn, FadeOut, CrossFadeIn, CrossFadeOut

OUTPUT_ROOT = Path(__file__).parent / "output" / "ugc_productions"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ── Studio definitions ─────────────────────────────────────────────────────

STUDIOS = {
    "hollywood": {
        "label": "Cinema House",
        "voice": "en-us",
        "width": 1920,
        "height": 1080,
        "style": "cinematic",
        "fps": 30,
        "music_key": "ambient_dark",
        "script": {
            "title": "The Silent Revolution: How AI Changed Everything",
            "subtitle": "A Social Optimize Production",
            "sections": [
                {
                    "heading": "THE HOOK",
                    "narration": "In 2025, something changed. Not with a bang, but with a whisper. Artificial intelligence didn't just arrive. It rewired the world.",
                    "visual": "Dark gradient, bold white text",
                    "bg_colors": [(8, 8, 25), (25, 15, 50)],
                    "accent": (100, 80, 255),
                    "text_color": (255, 255, 255),
                    "particles": "bokeh_blue",
                },
                {
                    "heading": "THE PROBLEM",
                    "narration": "For decades, creators spent 80 percent of their time on repetitive tasks. Editing, formatting, scheduling. The creative spark? Buried under busywork.",
                    "visual": "Red-tinted urgency",
                    "bg_colors": [(50, 8, 8), (25, 4, 4)],
                    "accent": (255, 80, 80),
                    "text_color": (255, 220, 220),
                    "particles": "embers",
                },
                {
                    "heading": "THE SHIFT",
                    "narration": "Then AI tools emerged that could handle the grind. Script generation in seconds. Voiceovers that sound human. Video assembly on autopilot. Creators got their time back.",
                    "visual": "Blue transformation",
                    "bg_colors": [(4, 15, 50), (8, 30, 70)],
                    "accent": (60, 160, 255),
                    "text_color": (200, 225, 255),
                    "particles": "bokeh_blue",
                },
                {
                    "heading": "THE FUTURE",
                    "narration": "Today, a single creator can produce what once required a full studio team. The playing field isn't just level. It's wide open. The question isn't whether AI will change content creation. It already has. The question is: what will you create?",
                    "visual": "Gold inspiration",
                    "bg_colors": [(35, 25, 4), (50, 40, 8)],
                    "accent": (255, 200, 60),
                    "text_color": (255, 235, 170),
                    "particles": "sparkle",
                },
            ],
        },
    },
    "studio56": {
        "label": "The Forge",
        "voice": "en-us",
        "width": 1080,
        "height": 1920,
        "style": "viral_short",
        "fps": 30,
        "music_key": "upbeat",
        "script": {
            "title": "5 Things Nobody Tells You About Going Viral",
            "subtitle": "The Forge — Viral Shorts",
            "sections": [
                {
                    "heading": "STOP SCROLLING",
                    "narration": "Stop scrolling. Here are five things nobody tells you about going viral.",
                    "visual": "Neon gradient hook",
                    "bg_colors": [(100, 0, 180), (180, 0, 90)],
                    "accent": (255, 100, 255),
                    "text_color": (255, 255, 255),
                    "particles": "neon",
                },
                {
                    "heading": "#1 — FIRST 3 SECONDS",
                    "narration": "Number one. Your first three seconds decide everything. If you don't hook them instantly, they're gone.",
                    "visual": "Electric blue",
                    "bg_colors": [(0, 40, 130), (0, 80, 180)],
                    "accent": (0, 200, 255),
                    "text_color": (255, 255, 100),
                    "particles": "bokeh_blue",
                },
                {
                    "heading": "#2 — TRENDING AUDIO",
                    "narration": "Number two. Trending audio is a cheat code. Use it before everyone else catches on.",
                    "visual": "Green energy",
                    "bg_colors": [(0, 60, 30), (0, 120, 50)],
                    "accent": (0, 255, 130),
                    "text_color": (255, 255, 255),
                    "particles": "sparkle",
                },
                {
                    "heading": "#3 — TIMING IS KEY",
                    "narration": "Number three. Post when your audience is awake, not when you are. Check your analytics.",
                    "visual": "Orange fire",
                    "bg_colors": [(130, 40, 0), (180, 70, 0)],
                    "accent": (255, 160, 0),
                    "text_color": (255, 255, 255),
                    "particles": "embers",
                },
                {
                    "heading": "FOLLOW FOR MORE",
                    "narration": "Follow for more tips that actually work. Save this for later.",
                    "visual": "Purple CTA",
                    "bg_colors": [(70, 0, 110), (130, 0, 180)],
                    "accent": (255, 200, 60),
                    "text_color": (255, 220, 100),
                    "particles": "neon",
                },
            ],
        },
    },
    "commercials": {
        "label": "Ad Lab",
        "voice": "en-us",
        "width": 1920,
        "height": 1080,
        "style": "commercial",
        "fps": 30,
        "music_key": "corporate",
        "script": {
            "title": "Social Optimize — Your Content Engine",
            "subtitle": "Create Smarter. Publish Faster.",
            "sections": [
                {
                    "heading": "THE PROBLEM",
                    "narration": "Tired of spending hours creating content that nobody sees?",
                    "visual": "Dark dramatic",
                    "bg_colors": [(15, 15, 15), (30, 30, 30)],
                    "accent": (255, 70, 70),
                    "text_color": (255, 100, 100),
                    "particles": "embers",
                },
                {
                    "heading": "THE SOLUTION",
                    "narration": "Social Optimize turns one idea into videos for every platform. Scripts, voiceovers, thumbnails. All generated in minutes.",
                    "visual": "Brand blue",
                    "bg_colors": [(0, 30, 90), (0, 60, 150)],
                    "accent": (0, 180, 255),
                    "text_color": (255, 255, 255),
                    "particles": "bokeh_blue",
                },
                {
                    "heading": "START FREE",
                    "narration": "Start creating smarter. Try Social Optimize free today.",
                    "visual": "Bold CTA",
                    "bg_colors": [(0, 80, 40), (0, 150, 70)],
                    "accent": (255, 255, 100),
                    "text_color": (255, 255, 255),
                    "particles": "sparkle",
                },
            ],
        },
    },
}


# ── Visual generators ──────────────────────────────────────────────────────

def make_radial_gradient(width, height, color1, color2, center_bias=0.6):
    """Radial gradient with vignette effect."""
    arr = np.zeros((height, width, 3), dtype=np.float32)
    cx, cy = width / 2, height / 2
    max_r = math.sqrt(cx ** 2 + cy ** 2)
    y_coords, x_coords = np.mgrid[0:height, 0:width]
    dist = np.sqrt((x_coords - cx) ** 2 + (y_coords - cy) ** 2)
    ratio = np.clip(dist / (max_r * center_bias), 0, 1)
    for c in range(3):
        arr[:, :, c] = color1[c] * (1 - ratio) + color2[c] * ratio
    return np.clip(arr, 0, 255).astype(np.uint8)


def add_particles(img, style, count=40, seed=42):
    """Add bokeh/particle overlay to a PIL Image."""
    rng = random.Random(seed)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size

    for _ in range(count):
        x = rng.randint(0, w)
        y = rng.randint(0, h)

        if style == "bokeh_blue":
            r = rng.randint(8, 40)
            alpha = rng.randint(15, 50)
            color = (100, 160, 255, alpha)
        elif style == "embers":
            r = rng.randint(2, 8)
            alpha = rng.randint(40, 120)
            color = (255, rng.randint(80, 180), 0, alpha)
        elif style == "sparkle":
            r = rng.randint(1, 5)
            alpha = rng.randint(60, 200)
            color = (255, 255, rng.randint(150, 255), alpha)
        elif style == "neon":
            r = rng.randint(5, 25)
            alpha = rng.randint(20, 70)
            color = (rng.randint(150, 255), 0, rng.randint(150, 255), alpha)
        else:
            r = rng.randint(3, 15)
            alpha = rng.randint(20, 60)
            color = (255, 255, 255, alpha)

        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def draw_lower_third(draw, width, height, heading, accent_color, is_portrait=False):
    """Draw a professional lower-third title bar."""
    bar_h = int(height * (0.08 if not is_portrait else 0.05))
    bar_y = int(height * (0.72 if not is_portrait else 0.78))

    # Semi-transparent dark bar
    draw.rectangle(
        [0, bar_y, width, bar_y + bar_h],
        fill=(0, 0, 0, 160),
    )
    # Accent stripe
    stripe_h = max(4, bar_h // 12)
    draw.rectangle(
        [0, bar_y, width, bar_y + stripe_h],
        fill=accent_color + (220,),
    )

    # Heading text on the bar
    font_size = max(18, min(bar_h - 16, 42))
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception:
        font = ImageFont.load_default()

    text_y = bar_y + (bar_h - font_size) // 2
    padding = int(width * 0.04)
    draw.text((padding, text_y), heading, fill=(255, 255, 255, 240), font=font)


def draw_watermark(draw, width, height, text="SOCIAL OPTIMIZE", is_portrait=False):
    """Subtle top-right watermark."""
    font_size = max(12, min(width // 50, 22))
    try:
        font = ImageFont.truetype(FONT_PATH_REGULAR, font_size)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = width - tw - int(width * 0.03)
    y = int(height * 0.03)
    draw.text((x, y), text, fill=(255, 255, 255, 60), font=font)


def make_section_frame_enhanced(section, width, height, section_idx, total_sections, studio_style):
    """Create an enhanced visual frame for a section."""
    is_portrait = height > width

    # Radial gradient background
    gradient = make_radial_gradient(width, height, section["bg_colors"][0], section["bg_colors"][1])
    img = Image.fromarray(gradient).convert("RGBA")

    # Particle overlay
    add_particles(img, section.get("particles", "bokeh_blue"), count=50, seed=section_idx * 17 + 7)

    draw = ImageDraw.Draw(img, "RGBA")
    accent = section["accent"]
    tc = section["text_color"]

    # Lower-third title bar
    draw_lower_third(draw, width, height, section["heading"], accent, is_portrait)

    # Watermark
    draw_watermark(draw, width, height, is_portrait=is_portrait)

    # Main narration text — centered, larger
    body_size = max(22, min(width // 20, 52)) if not is_portrait else max(22, min(width // 16, 44))
    try:
        body_font = ImageFont.truetype(FONT_PATH, body_size)
    except Exception:
        body_font = ImageFont.load_default()

    narration = section["narration"]
    max_chars = max(20, width // (body_size // 2 + 2))
    words = narration.split()
    lines = []
    current = ""
    for w in words:
        test = f"{current} {w}".strip()
        if len(test) <= max_chars:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)

    line_height = body_size + 14
    block_height = len(lines) * line_height
    y_start = int(height * 0.35) - block_height // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=body_font)
        lw = bbox[2] - bbox[0]
        lx = (width - lw) // 2
        ly = y_start + i * line_height

        # Text shadow
        draw.text((lx + 2, ly + 2), line, fill=(0, 0, 0, 120), font=body_font)
        # Main text
        draw.text((lx, ly), line, fill=tc + (255,), font=body_font)

    # Section indicator dots at bottom
    dot_y = int(height * 0.92)
    dot_spacing = 24
    total_w = (total_sections - 1) * dot_spacing
    dot_x_start = (width - total_w) // 2
    for i in range(total_sections):
        dx = dot_x_start + i * dot_spacing
        r = 5 if i == section_idx else 3
        color = accent + (220,) if i == section_idx else (255, 255, 255, 60)
        draw.ellipse([dx - r, dot_y - r, dx + r, dot_y + r], fill=color)

    return np.array(img.convert("RGB"))


def make_title_card(width, height, title, subtitle, accent_color, bg_colors):
    """Create a title card for the beginning of the video."""
    gradient = make_radial_gradient(width, height, bg_colors[0], bg_colors[1], center_bias=0.5)
    img = Image.fromarray(gradient).convert("RGBA")
    add_particles(img, "sparkle", count=60, seed=99)
    draw = ImageDraw.Draw(img, "RGBA")

    # Title
    title_size = max(30, min(width // 12, 80))
    try:
        title_font = ImageFont.truetype(FONT_PATH, title_size)
    except Exception:
        title_font = ImageFont.load_default()

    # Word-wrap title
    max_chars = max(15, width // (title_size // 2 + 2))
    words = title.split()
    lines = []
    current = ""
    for w in words:
        test = f"{current} {w}".strip()
        if len(test) <= max_chars:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)

    line_h = title_size + 12
    block_h = len(lines) * line_h
    y_start = height // 2 - block_h // 2 - 30

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        lw = bbox[2] - bbox[0]
        lx = (width - lw) // 2
        ly = y_start + i * line_h
        draw.text((lx + 3, ly + 3), line, fill=(0, 0, 0, 140), font=title_font)
        draw.text((lx, ly), line, fill=(255, 255, 255, 245), font=title_font)

    # Accent line
    line_y = y_start + block_h + 15
    line_w = min(width // 3, 300)
    draw.rectangle(
        [(width - line_w) // 2, line_y, (width + line_w) // 2, line_y + 4],
        fill=accent_color + (200,),
    )

    # Subtitle
    sub_size = max(16, min(width // 30, 32))
    try:
        sub_font = ImageFont.truetype(FONT_PATH_REGULAR, sub_size)
    except Exception:
        sub_font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
    sw = bbox[2] - bbox[0]
    draw.text(
        ((width - sw) // 2, line_y + 24),
        subtitle,
        fill=accent_color + (180,),
        font=sub_font,
    )

    draw_watermark(draw, width, height)
    return np.array(img.convert("RGB"))


def make_outro_card(width, height, accent_color, bg_colors):
    """Create an outro/end card."""
    gradient = make_radial_gradient(width, height, bg_colors[0], bg_colors[1], center_bias=0.5)
    img = Image.fromarray(gradient).convert("RGBA")
    add_particles(img, "sparkle", count=80, seed=123)
    draw = ImageDraw.Draw(img, "RGBA")

    size = max(28, min(width // 14, 64))
    try:
        font = ImageFont.truetype(FONT_PATH, size)
    except Exception:
        font = ImageFont.load_default()

    text = "SOCIAL OPTIMIZE"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, height // 2 - size), text, fill=accent_color + (240,), font=font)

    sub_size = max(14, size // 2)
    try:
        sub_font = ImageFont.truetype(FONT_PATH_REGULAR, sub_size)
    except Exception:
        sub_font = ImageFont.load_default()
    sub = "socialoptimize.online"
    bbox = draw.textbbox((0, 0), sub, font=sub_font)
    sw = bbox[2] - bbox[0]
    draw.text(((width - sw) // 2, height // 2 + 20), sub, fill=(255, 255, 255, 120), font=sub_font)

    return np.array(img.convert("RGB"))


# ── Audio generators ───────────────────────────────────────────────────────

def generate_voiceover_espeak(text, output_path, voice="en-us"):
    """Generate voiceover using espeak-ng (offline)."""
    wav_path = str(output_path).replace(".mp3", ".wav")
    subprocess.run(
        ["espeak-ng", "-w", wav_path, "-v", voice, "-s", "150", "-p", "45", "-a", "180", text],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", str(output_path)],
        check=True,
        capture_output=True,
    )
    Path(wav_path).unlink(missing_ok=True)


def generate_background_music(output_path, duration, style="ambient_dark"):
    """Synthesize simple ambient background music using ffmpeg filters."""
    if style == "ambient_dark":
        # Low drone with subtle modulation
        af = (
            f"sine=f=80:d={duration}[s1];"
            f"sine=f=120:d={duration}[s2];"
            f"sine=f=160:d={duration}[s3];"
            f"[s1][s2]amix=inputs=2[m1];"
            f"[m1][s3]amix=inputs=2,"
            f"tremolo=f=0.3:d=0.4,"
            f"volume=0.08,"
            f"afade=t=in:d=2,afade=t=out:st={max(0, duration-3)}:d=3"
        )
    elif style == "upbeat":
        af = (
            f"sine=f=220:d={duration}[s1];"
            f"sine=f=330:d={duration}[s2];"
            f"sine=f=440:d={duration}[s3];"
            f"[s1][s2]amix=inputs=2[m1];"
            f"[m1][s3]amix=inputs=2,"
            f"tremolo=f=4:d=0.5,"
            f"volume=0.06,"
            f"afade=t=in:d=1,afade=t=out:st={max(0, duration-2)}:d=2"
        )
    else:  # corporate
        af = (
            f"sine=f=130:d={duration}[s1];"
            f"sine=f=196:d={duration}[s2];"
            f"sine=f=262:d={duration}[s3];"
            f"[s1][s2]amix=inputs=2[m1];"
            f"[m1][s3]amix=inputs=2,"
            f"tremolo=f=1:d=0.3,"
            f"volume=0.07,"
            f"afade=t=in:d=1.5,afade=t=out:st={max(0, duration-2.5)}:d=2.5"
        )

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"[0:a]{af}" if ";" not in af else af.split(",")[0],
            "-filter_complex", af,
            "-t", str(duration),
            "-codec:a", "libmp3lame", "-b:a", "128k",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


def mix_audio(voice_path, music_path, output_path, music_vol=0.15):
    """Mix voiceover with background music."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(voice_path),
            "-i", str(music_path),
            "-filter_complex",
            f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2",
            "-codec:a", "libmp3lame", "-b:a", "192k",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


# ── Ken Burns effect ───────────────────────────────────────────────────────

def apply_ken_burns(clip, target_w, target_h, zoom_start=1.0, zoom_end=1.08):
    """Apply slow zoom (Ken Burns) to an ImageClip."""
    duration = clip.duration

    def make_frame(t):
        progress = t / max(duration, 0.01)
        zoom = zoom_start + (zoom_end - zoom_start) * progress
        frame = clip.get_frame(t)
        h, w = frame.shape[:2]
        new_w = int(w / zoom)
        new_h = int(h / zoom)
        x1 = (w - new_w) // 2
        y1 = (h - new_h) // 2
        cropped = frame[y1:y1 + new_h, x1:x1 + new_w]
        # Resize back using PIL for quality
        img = Image.fromarray(cropped)
        img = img.resize((target_w, target_h), Image.LANCZOS)
        return np.array(img)

    from moviepy import VideoClip
    return VideoClip(make_frame, duration=duration).with_fps(clip.fps or 30)


# ── Main producer ──────────────────────────────────────────────────────────

def produce_studio(studio_key):
    """Produce an enhanced video for one studio."""
    studio = STUDIOS[studio_key]
    script = studio["script"]
    w, h = studio["width"], studio["height"]
    fps = studio.get("fps", 30)

    job_dir = OUTPUT_ROOT / studio_key / datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  {studio['label']} — Producing: {script['title']}")
    print(f"{'='*60}")

    # 1. Generate voiceover
    full_narration = " ".join(s["narration"] for s in script["sections"])
    voice_path = job_dir / "voiceover.mp3"
    print(f"  [1/6] Generating voiceover...")
    generate_voiceover_espeak(full_narration, voice_path, studio["voice"])

    voice_clip = AudioFileClip(str(voice_path))
    total_duration = voice_clip.duration
    print(f"         Voiceover: {total_duration:.1f}s")

    # 2. Per-section timing
    section_durations = []
    section_audios = []
    print(f"  [2/6] Calculating section timing...")
    for i, sec in enumerate(script["sections"]):
        sec_path = job_dir / f"section_{i}.mp3"
        generate_voiceover_espeak(sec["narration"], sec_path, studio["voice"])
        sc = AudioFileClip(str(sec_path))
        section_durations.append(sc.duration + 0.8)
        section_audios.append(sec_path)
        sc.close()

    # Add time for title + outro cards
    title_dur = 3.0
    outro_dur = 2.5
    content_dur = total_duration
    total_raw = sum(section_durations)
    scale = content_dur / total_raw if total_raw > 0 else 1
    section_durations = [d * scale for d in section_durations]

    # 3. Background music
    print(f"  [3/6] Synthesizing background music...")
    music_path = job_dir / "bgm.mp3"
    full_dur = title_dur + content_dur + outro_dur
    try:
        generate_background_music(music_path, full_dur, studio.get("music_key", "ambient_dark"))
        mixed_path = job_dir / "mixed_audio.mp3"
        # Create silent padding for title card, then voice, then silence for outro
        padded_voice = job_dir / "padded_voice.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                "-i", str(voice_path),
                "-filter_complex",
                f"[0:a]atrim=0:{title_dur}[pad];[pad][1:a]concat=n=2:v=0:a=1,"
                f"apad=pad_dur={outro_dur}",
                "-t", str(full_dur),
                "-codec:a", "libmp3lame", "-b:a", "192k",
                str(padded_voice),
            ],
            check=True, capture_output=True,
        )
        mix_audio(padded_voice, music_path, mixed_path, music_vol=0.2)
        final_audio = AudioFileClip(str(mixed_path))
        padded_voice.unlink(missing_ok=True)
        has_music = True
        print(f"         Background music mixed successfully")
    except Exception as e:
        print(f"         Music generation failed ({e}), using voice only")
        # Pad voice with silence for title card
        padded_voice = job_dir / "padded_voice.mp3"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                    "-i", str(voice_path),
                    "-filter_complex",
                    f"[0:a]atrim=0:{title_dur}[pad];[pad][1:a]concat=n=2:v=0:a=1,"
                    f"apad=pad_dur={outro_dur}",
                    "-t", str(full_dur),
                    "-codec:a", "libmp3lame", "-b:a", "192k",
                    str(padded_voice),
                ],
                check=True, capture_output=True,
            )
            final_audio = AudioFileClip(str(padded_voice))
        except Exception:
            final_audio = voice_clip
            title_dur = 0
            outro_dur = 0
            full_dur = content_dur
        has_music = False

    # 4. Build visual clips
    total_sections = len(script["sections"])
    first_section = script["sections"][0]
    accent = first_section["accent"]

    print(f"  [4/6] Building title card + {total_sections} sections + outro...")

    clips = []

    # Title card
    title_frame = make_title_card(
        w, h, script["title"], script.get("subtitle", ""),
        accent, first_section["bg_colors"],
    )
    # Render title at slightly larger size for Ken Burns
    overscan = int(w * 0.1)
    title_frame_big = make_title_card(
        w + overscan, h + int(overscan * h / w),
        script["title"], script.get("subtitle", ""),
        accent, first_section["bg_colors"],
    )
    title_clip = ImageClip(title_frame_big).with_duration(title_dur).with_fps(fps)
    title_clip = apply_ken_burns(title_clip, w, h, zoom_start=1.0, zoom_end=1.06)
    title_clip = title_clip.with_effects([FadeIn(0.6), FadeOut(0.4)])
    clips.append(title_clip)

    # Section clips with Ken Burns
    for i, sec in enumerate(script["sections"]):
        overscan_sec = int(w * 0.12)
        frame = make_section_frame_enhanced(
            sec, w + overscan_sec, h + int(overscan_sec * h / w),
            i, total_sections, studio["style"],
        )
        dur = max(section_durations[i], 1.0)
        clip = ImageClip(frame).with_duration(dur).with_fps(fps)
        # Alternate zoom direction
        if i % 2 == 0:
            clip = apply_ken_burns(clip, w, h, zoom_start=1.0, zoom_end=1.08)
        else:
            clip = apply_ken_burns(clip, w, h, zoom_start=1.06, zoom_end=1.0)
        clip = clip.with_effects([FadeIn(0.5), FadeOut(0.5)])
        clips.append(clip)

    # Outro card
    last_section = script["sections"][-1]
    outro_frame_big = make_outro_card(
        w + overscan, h + int(overscan * h / w),
        accent, last_section["bg_colors"],
    )
    outro_clip = ImageClip(outro_frame_big).with_duration(outro_dur).with_fps(fps)
    outro_clip = apply_ken_burns(outro_clip, w, h, zoom_start=1.0, zoom_end=1.04)
    outro_clip = outro_clip.with_effects([FadeIn(0.4), FadeOut(0.8)])
    clips.append(outro_clip)

    # 5. Assemble
    print(f"  [5/6] Compositing {len(clips)} clips...")
    video = concatenate_videoclips(clips, method="compose")
    video = video.with_duration(min(video.duration, full_dur))
    video = video.with_audio(final_audio.subclipped(0, min(final_audio.duration, video.duration)))

    # 6. Export
    output_path = job_dir / f"{studio_key}_ugc.mp4"
    print(f"  [6/6] Rendering {output_path.name} at {fps}fps...")
    video.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="4000k",
        logger=None,
    )

    # Save manifest
    manifest = {
        "studio": studio_key,
        "label": studio["label"],
        "title": script["title"],
        "duration": float(video.duration),
        "resolution": f"{w}x{h}",
        "fps": fps,
        "has_music": has_music,
        "output": str(output_path),
        "created_at": datetime.now().isoformat(),
        "sections": total_sections,
        "features": [
            "radial_gradient", "particle_overlay", "lower_third",
            "ken_burns_zoom", "title_card", "outro_card",
            "section_indicators", "text_shadows", "watermark",
        ],
    }
    manifest_path = job_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Cleanup temp files
    for p in section_audios:
        p.unlink(missing_ok=True)

    file_size = output_path.stat().st_size / (1024 * 1024)
    print(f"\n  ✓ DONE: {output_path}")
    print(f"    Duration: {video.duration:.1f}s | Size: {file_size:.1f} MB | {w}x{h}@{fps}fps")
    if has_music:
        print(f"    Features: radial gradients, particles, Ken Burns zoom, BGM, lower-thirds")

    video.close()
    voice_clip.close()
    final_audio.close()
    return manifest


def main():
    parser = argparse.ArgumentParser(description="UGC Video Producer (Enhanced)")
    parser.add_argument(
        "--studio", "-s",
        choices=list(STUDIOS.keys()) + ["all"],
        default="all",
        help="Which studio to run",
    )
    args = parser.parse_args()

    studios = list(STUDIOS.keys()) if args.studio == "all" else [args.studio]
    results = {}

    for key in studios:
        try:
            manifest = produce_studio(key)
            results[key] = manifest
        except Exception as e:
            print(f"\n  ✗ {key} FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[key] = {"error": str(e)}

    print(f"\n{'='*60}")
    print("  PRODUCTION SUMMARY")
    print(f"{'='*60}")
    for key, res in results.items():
        if "error" in res:
            print(f"  ✗ {STUDIOS[key]['label']}: FAILED — {res['error']}")
        else:
            print(f"  ✓ {res['label']}: {res['title']}")
            print(f"    → {res['output']}")
            print(f"    → {res['duration']:.1f}s | {res['resolution']} | Music: {res.get('has_music', False)}")
    print()

    return results


if __name__ == "__main__":
    main()
