#!/usr/bin/env python3
"""
UGC Video Producer — generates real MP4 videos without external API keys.
Uses edge-tts (free) for voiceover, Pillow for visuals, MoviePy for assembly.

Studios:
  hollywood   — cinematic long-form (60s)
  studio56    — short-form viral (30s)
  commercials — 15s product ad

Usage:
  python produce_ugc.py                    # all three studios
  python produce_ugc.py --studio hollywood # single studio
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
)
from moviepy.video.fx import FadeIn, FadeOut

OUTPUT_ROOT = Path(__file__).parent / "output" / "ugc_productions"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ── Studio definitions ─────────────────────────────────────────────────────

STUDIOS = {
    "hollywood": {
        "label": "Hollywood Studio",
        "voice": "en-US-GuyNeural",
        "width": 1920,
        "height": 1080,
        "style": "cinematic",
        "script": {
            "title": "The Silent Revolution: How AI Changed Everything",
            "sections": [
                {
                    "heading": "Hook",
                    "narration": "In 2025, something changed. Not with a bang, but with a whisper. Artificial intelligence didn't just arrive. It rewired the world.",
                    "visual": "Dark gradient, bold white text",
                    "colors": [(10, 10, 30), (30, 20, 60)],
                    "text_color": (255, 255, 255),
                },
                {
                    "heading": "The Problem",
                    "narration": "For decades, creators spent 80 percent of their time on repetitive tasks. Editing, formatting, scheduling. The creative spark? Buried under busywork.",
                    "visual": "Red-tinted urgency",
                    "colors": [(60, 10, 10), (30, 5, 5)],
                    "text_color": (255, 200, 200),
                },
                {
                    "heading": "The Transformation",
                    "narration": "Then AI tools emerged that could handle the grind. Script generation in seconds. Voiceovers that sound human. Video assembly on autopilot. Creators got their time back.",
                    "visual": "Blue transformation",
                    "colors": [(5, 20, 60), (10, 40, 80)],
                    "text_color": (200, 220, 255),
                },
                {
                    "heading": "The Future",
                    "narration": "Today, a single creator can produce what once required a full studio team. The playing field isn't just level. It's wide open. The question isn't whether AI will change content creation. It already has. The question is: what will you create?",
                    "visual": "Gold inspiration",
                    "colors": [(40, 30, 5), (60, 45, 10)],
                    "text_color": (255, 230, 150),
                },
            ],
        },
    },
    "studio56": {
        "label": "Studio 56",
        "voice": "en-US-AriaNeural",
        "width": 1080,
        "height": 1920,
        "style": "viral_short",
        "script": {
            "title": "5 Things Nobody Tells You About Going Viral",
            "sections": [
                {
                    "heading": "Hook",
                    "narration": "Stop scrolling. Here are five things nobody tells you about going viral.",
                    "visual": "Neon gradient hook",
                    "colors": [(120, 0, 200), (200, 0, 100)],
                    "text_color": (255, 255, 255),
                },
                {
                    "heading": "Tip 1",
                    "narration": "Number one. Your first three seconds decide everything. If you don't hook them instantly, they're gone.",
                    "visual": "Electric blue",
                    "colors": [(0, 50, 150), (0, 100, 200)],
                    "text_color": (255, 255, 100),
                },
                {
                    "heading": "Tip 2",
                    "narration": "Number two. Trending audio is a cheat code. Use it before everyone else catches on.",
                    "visual": "Green energy",
                    "colors": [(0, 80, 40), (0, 150, 60)],
                    "text_color": (255, 255, 255),
                },
                {
                    "heading": "Tip 3",
                    "narration": "Number three. Post when your audience is awake, not when you are. Check your analytics.",
                    "visual": "Orange fire",
                    "colors": [(150, 50, 0), (200, 80, 0)],
                    "text_color": (255, 255, 255),
                },
                {
                    "heading": "CTA",
                    "narration": "Follow for more tips that actually work. Save this for later.",
                    "visual": "Purple CTA",
                    "colors": [(80, 0, 120), (150, 0, 200)],
                    "text_color": (255, 220, 100),
                },
            ],
        },
    },
    "commercials": {
        "label": "Commercial Studio",
        "voice": "en-US-DavisNeural",
        "width": 1920,
        "height": 1080,
        "style": "commercial",
        "script": {
            "title": "Social Optimize — Your Content Engine",
            "sections": [
                {
                    "heading": "Problem",
                    "narration": "Tired of spending hours creating content that nobody sees?",
                    "visual": "Dark dramatic",
                    "colors": [(20, 20, 20), (40, 40, 40)],
                    "text_color": (255, 100, 100),
                },
                {
                    "heading": "Solution",
                    "narration": "Social Optimize turns one idea into videos for every platform. Scripts, voiceovers, thumbnails. All generated in minutes.",
                    "visual": "Brand blue",
                    "colors": [(0, 40, 100), (0, 80, 180)],
                    "text_color": (255, 255, 255),
                },
                {
                    "heading": "CTA",
                    "narration": "Start creating smarter. Try Social Optimize free today.",
                    "visual": "Bold CTA",
                    "colors": [(0, 100, 50), (0, 180, 80)],
                    "text_color": (255, 255, 255),
                },
            ],
        },
    },
}


def make_gradient(width, height, color1, color2):
    """Create a vertical gradient numpy array."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        arr[y, :] = [r, g, b]
    return arr


def make_section_frame(section, width, height):
    """Create a single section's visual frame as a PIL Image."""
    gradient = make_gradient(width, height, section["colors"][0], section["colors"][1])
    img = Image.fromarray(gradient)
    draw = ImageDraw.Draw(img)

    # Heading
    head_size = max(28, min(width // 16, 72))
    body_size = max(20, min(width // 24, 48))

    try:
        head_font = ImageFont.truetype(FONT_PATH, head_size)
        body_font = ImageFont.truetype(FONT_PATH, body_size)
    except Exception:
        head_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    tc = section["text_color"]

    # Draw heading centered
    heading = section["heading"].upper()
    hbox = draw.textbbox((0, 0), heading, font=head_font)
    hx = (width - (hbox[2] - hbox[0])) // 2
    hy = height // 4
    draw.text((hx, hy), heading, fill=tc, font=head_font)

    # Draw narration text wrapped
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

    y_start = height // 2 - (len(lines) * (body_size + 8)) // 2
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=body_font)
        lx = (width - (bbox[2] - bbox[0])) // 2
        ly = y_start + i * (body_size + 12)
        draw.text((lx, ly), line, fill=tc, font=body_font)

    return np.array(img)


def generate_voiceover_espeak(text, output_path, voice="en-us"):
    """Generate voiceover using espeak-ng (offline, no API key needed)."""
    import subprocess
    import tempfile

    wav_path = str(output_path).replace(".mp3", ".wav")
    subprocess.run(
        ["espeak-ng", "-w", wav_path, "-v", voice, "-s", "160", "-p", "50", text],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "128k", str(output_path)],
        check=True,
        capture_output=True,
    )
    Path(wav_path).unlink(missing_ok=True)


def produce_studio(studio_key):
    """Produce a complete video for one studio."""
    studio = STUDIOS[studio_key]
    script = studio["script"]
    w, h = studio["width"], studio["height"]

    job_dir = OUTPUT_ROOT / studio_key / datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  {studio['label']} — Producing: {script['title']}")
    print(f"{'='*60}")

    # 1. Generate voiceover for full narration
    full_narration = " ".join(s["narration"] for s in script["sections"])
    audio_path = job_dir / "voiceover.mp3"
    print(f"  [1/4] Generating voiceover ({studio['voice']})...")
    generate_voiceover_espeak(full_narration, audio_path)

    audio_clip = AudioFileClip(str(audio_path))
    total_duration = audio_clip.duration
    print(f"         Audio: {total_duration:.1f}s")

    # 2. Generate section voiceovers to get per-section timing
    section_durations = []
    section_audios = []
    print(f"  [2/4] Generating section audio for timing...")
    for i, sec in enumerate(script["sections"]):
        sec_audio_path = job_dir / f"section_{i}.mp3"
        generate_voiceover_espeak(sec["narration"], sec_audio_path)
        sec_clip = AudioFileClip(str(sec_audio_path))
        section_durations.append(sec_clip.duration + 0.5)  # small padding
        section_audios.append(sec_audio_path)
        sec_clip.close()

    # Normalize durations to match total
    total_raw = sum(section_durations)
    scale = total_duration / total_raw if total_raw > 0 else 1
    section_durations = [d * scale for d in section_durations]

    # 3. Build visual clips
    print(f"  [3/4] Building {len(script['sections'])} visual sections...")
    clips = []
    for i, sec in enumerate(script["sections"]):
        frame = make_section_frame(sec, w, h)
        dur = max(section_durations[i], 1.0)
        clip = ImageClip(frame).with_duration(dur)
        clip = clip.with_effects([FadeIn(0.4), FadeOut(0.4)])
        clips.append(clip)

    video = concatenate_videoclips(clips, method="compose")
    video = video.with_audio(audio_clip)

    # 4. Export
    output_path = job_dir / f"{studio_key}_ugc.mp4"
    print(f"  [4/4] Rendering video to {output_path.name}...")
    video.write_videofile(
        str(output_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )

    # Save manifest
    manifest = {
        "studio": studio_key,
        "label": studio["label"],
        "title": script["title"],
        "duration": total_duration,
        "resolution": f"{w}x{h}",
        "output": str(output_path),
        "created_at": datetime.now().isoformat(),
        "sections": len(script["sections"]),
    }
    manifest_path = job_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Cleanup section audio files
    for p in section_audios:
        p.unlink(missing_ok=True)

    file_size = output_path.stat().st_size / (1024 * 1024)
    print(f"\n  ✓ DONE: {output_path}")
    print(f"    Duration: {total_duration:.1f}s | Size: {file_size:.1f} MB | Resolution: {w}x{h}")

    video.close()
    audio_clip.close()
    return manifest


def main():
    parser = argparse.ArgumentParser(description="UGC Video Producer")
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
    print()

    return results


if __name__ == "__main__":
    main()
