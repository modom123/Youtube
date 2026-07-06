"""Assemble final videos from audio, stock clips, and graphics — uses ffmpeg directly for speed."""
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config


def _get_ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _get_ffprobe() -> Optional[str]:
    """Find a real ffprobe binary. imageio_ffmpeg only bundles ffmpeg, never
    ffprobe -- deriving a path by string-replacing "ffmpeg" with "ffprobe" in
    its bundled binary's path never resolves to a real file, so that never
    actually works even where a system ffprobe is installed alongside
    ffmpeg (e.g. via apt). Look on PATH instead, where the real one lives."""
    import shutil
    return shutil.which("ffprobe")


def _get_duration(path: Path) -> float:
    """Get media duration using ffprobe, with MoviePy fallback."""
    ffprobe = _get_ffprobe()
    duration = 0.0
    if ffprobe:
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            val = r.stdout.strip()
            if val:
                duration = float(val)
        except Exception:
            pass
    if duration > 0:
        return duration
    # ffprobe unavailable/failed or returned 0 — try MoviePy
    try:
        from moviepy import AudioFileClip
        clip = AudioFileClip(str(path))
        duration = float(clip.duration)
        clip.close()
    except Exception:
        pass
    if duration <= 0:
        raise RuntimeError(f"Could not determine duration of {path} (got {duration}s). File may be corrupt.")
    return duration


def _get_video_duration(path: Path) -> float:
    """Get video file duration, with a MoviePy fallback when ffprobe isn't
    on PATH -- without this fallback every video clip silently reads as
    duration 0 and gets discarded, forcing the no-visuals text-card path
    even when real stock/AI video clips were successfully fetched."""
    ffprobe = _get_ffprobe()
    if ffprobe:
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            val = r.stdout.strip()
            if val:
                return float(val)
        except Exception:
            pass
    try:
        from moviepy import VideoFileClip
        clip = VideoFileClip(str(path))
        duration = float(clip.duration)
        clip.close()
        return duration
    except Exception:
        return 0


_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
_FONT_PATHS_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]

_GRADIENT_PALETTES = [
    ((10, 15, 60), (30, 60, 120)),     # deep blue
    ((15, 50, 80), (10, 100, 130)),    # ocean teal
    ((60, 10, 60), (120, 30, 100)),    # purple
    ((20, 60, 40), (10, 110, 70)),     # forest green
    ((80, 30, 10), (140, 60, 20)),     # warm amber
    ((10, 30, 70), (50, 20, 90)),      # indigo
]


def _load_font(size: int, bold: bool = True):
    paths = _FONT_PATHS if bold else _FONT_PATHS_REGULAR
    for fp in paths:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _make_gradient_image(width: int, height: int, c1: tuple, c2: tuple) -> Path:
    """Create a gradient image and save to temp file."""
    grad = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / max(height - 1, 1)
        grad[y, :] = [
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
        ]
    img = Image.fromarray(grad)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return Path(tmp.name)


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    for word in words:
        test = f"{current} {word}".strip() if current else word
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _make_text_card(
    text: str,
    width: int,
    height: int,
    palette_idx: int = 0,
    subtitle: str = "",
    number: str = "",
) -> Path:
    """Create a professional text card image with gradient background."""
    c1, c2 = _GRADIENT_PALETTES[palette_idx % len(_GRADIENT_PALETTES)]
    grad = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / max(height - 1, 1)
        grad[y, :] = [
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
        ]
    img = Image.fromarray(grad)
    draw = ImageDraw.Draw(img)

    # Decorative accent line at top
    accent_color = (255, 200, 50)
    draw.rectangle([(0, 0), (width, 4)], fill=accent_color)

    text_area_w = int(width * 0.8)
    center_x = width // 2

    y_cursor = height // 2

    if number:
        num_font = _load_font(min(120, height // 4))
        bbox = draw.textbbox((0, 0), number, font=num_font)
        nw = bbox[2] - bbox[0]
        nh = bbox[3] - bbox[1]
        y_cursor = int(height * 0.25)
        draw.text((center_x - nw // 2, y_cursor - nh // 2), number, font=num_font, fill=accent_color)
        y_cursor += nh // 2 + 30

    main_font_size = min(48, height // 12)
    main_font = _load_font(main_font_size)
    lines = _wrap_text(text, main_font, text_area_w)
    line_h = main_font_size + 8

    if not number:
        total_text_h = len(lines) * line_h
        y_cursor = (height - total_text_h) // 2

    for line in lines[:8]:
        bbox = draw.textbbox((0, 0), line, font=main_font)
        lw = bbox[2] - bbox[0]
        draw.text((center_x - lw // 2, y_cursor), line, font=main_font, fill=(255, 255, 255))
        y_cursor += line_h

    if subtitle:
        y_cursor += 20
        sub_font = _load_font(min(28, height // 20), bold=False)
        sub_lines = _wrap_text(subtitle, sub_font, text_area_w)
        for sl in sub_lines[:4]:
            bbox = draw.textbbox((0, 0), sl, font=sub_font)
            sw = bbox[2] - bbox[0]
            draw.text((center_x - sw // 2, y_cursor), sl, font=sub_font, fill=(200, 200, 220))
            y_cursor += min(32, height // 18)

    # Bottom accent bar
    draw.rectangle([(0, height - 4), (width, height)], fill=accent_color)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return Path(tmp.name)


def _generate_section_cards(
    sections: list[dict],
    narration_text: str,
    width: int,
    height: int,
    total_duration: float,
) -> list[tuple]:
    """Generate text card images for each section. Returns list of (path, duration)."""
    if not sections:
        card = _make_text_card(narration_text[:120] or "Content", width, height)
        return [(card, total_duration)]

    cards = []
    total_section_dur = sum(s.get("duration", 10) for s in sections) or 1
    scale = total_duration / total_section_dur

    for i, section in enumerate(sections):
        name = section.get("name", f"Section {i + 1}")
        visual_cue = section.get("visual_cue", "")
        raw_dur = section.get("duration", 10)
        dur = max(2.0, raw_dur * scale)

        # Detect countdown numbers in section name
        import re
        num_match = re.search(r'#(\d+)|(?:number|no\.?)\s*(\d+)', name, re.IGNORECASE)
        number_str = ""
        if num_match:
            number_str = f"#{num_match.group(1) or num_match.group(2)}"

        card = _make_text_card(
            text=name,
            width=width,
            height=height,
            palette_idx=i,
            subtitle=visual_cue[:150] if visual_cue else "",
            number=number_str,
        )
        cards.append((card, dur))

    return cards


def _prepare_clip_segment(source: Path, duration: float, width: int, height: int, tmpdir: Path, idx: int,
                           punchy: bool = False) -> Optional[Path]:
    """Use ffmpeg to create a scaled/cropped segment from a source file.

    punchy=True swaps the uniform soft fade-in/out every clip gets (which,
    at commercial pacing, reads as a slow, cinematic edit) for mostly hard
    cuts with an occasional quick dip -- closer to how real ads are cut."""
    ffmpeg = _get_ffmpeg()
    out = tmpdir / f"seg_{idx:04d}.mp4"

    is_video = source.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv")
    is_image = source.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp")

    if is_video:
        src_dur = _get_video_duration(source)
        if src_dur <= 0:
            return None
        start = random.uniform(0, max(0, src_dur - duration - 0.5))
        actual_dur = min(duration, src_dur - start)
        if actual_dur < 0.5:
            start = 0
            actual_dur = min(duration, src_dur)

        if punchy:
            fade_vf = (f"fade=in:0:4,fade=out:st={max(0, actual_dur-0.2):.2f}:d=0.2"
                       if idx % 3 == 0 else "")
        else:
            fade_vf = f"fade=in:0:6,fade=out:st={max(0, actual_dur-0.3):.2f}:d=0.3"
        base_vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        vf = f"{base_vf},{fade_vf}" if fade_vf else base_vf

        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start:.2f}",
            "-i", str(source),
            "-t", f"{actual_dur:.2f}",
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", "24",
            str(out),
        ]
    elif is_image:
        # Slow Ken Burns zoom instead of a flat static frame -- a plain still
        # held for 4-8s with zero motion reads as the video "stopping" next to
        # real video-clip segments. zoompan needs a heavily upscaled source
        # (the 8000px scale is the standard workaround for its low-res jitter)
        # and a real frame rate to look smooth, unlike the old 8fps-static path.
        fps = 25
        frames = max(1, int(duration * fps))
        zoom_in = idx % 2 == 0
        zoom_expr = "min(zoom+0.0015,1.3)" if zoom_in else "if(eq(on,0),1.3,max(zoom-0.0015,1.0))"
        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-i", str(source),
            "-t", f"{duration:.2f}",
            "-vf", (f"scale=8000:-1,"
                    f"zoompan=z='{zoom_expr}':d={frames}:s={width}x{height}:fps={fps}"),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(out),
        ]
    else:
        return None

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
        print(f"[video] ffmpeg segment failed for {source.name}: {r.stderr.decode('utf-8', errors='replace')[-200:]}")
    except Exception as e:
        print(f"[video] Segment creation failed for {source.name}: {e}")
    return None


def create_video(
    audio_path: Path,
    output_path: Path,
    video_clips: list[Path] = None,
    image_clips: list[Path] = None,
    thumbnail_path: Optional[Path] = None,
    width: int = config.VIDEO_WIDTH,
    height: int = config.VIDEO_HEIGHT,
    sections: list[dict] = None,
    add_subtitles: bool = False,
    narration_text: str = "",
    punchy_cuts: bool = False,
) -> Path:
    """Assemble the final video from audio and visual assets using ffmpeg directly."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    total_duration = _get_duration(audio_path)
    ffmpeg = _get_ffmpeg()

    video_clips = [Path(p) for p in (video_clips or []) if p and Path(p).exists()]
    image_clips = [Path(p) for p in (image_clips or []) if p and Path(p).exists()]
    all_visuals = list(video_clips) + list(image_clips)

    print(f"[video] Visuals available: {len(video_clips)} videos, {len(image_clips)} images, total_duration={total_duration:.1f}s")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        segments = []

        if all_visuals:
            random.shuffle(all_visuals)
            elapsed = 0.0
            idx = 0
            while elapsed < total_duration:
                remaining = total_duration - elapsed
                clip_duration = min(random.uniform(4, 8), remaining)
                if clip_duration < 0.5:
                    break
                source = all_visuals[idx % len(all_visuals)]
                seg = _prepare_clip_segment(source, clip_duration, width, height, tmpdir, idx, punchy=punchy_cuts)
                if seg:
                    segments.append(seg)
                    elapsed += clip_duration
                idx += 1
                if idx > len(all_visuals) * 3 and not segments:
                    break

        if not segments:
            print("[video] No stock visuals — generating text card slides from sections")
            section_cards = _generate_section_cards(
                sections or [], narration_text, width, height, total_duration,
            )
            for i, (card_path, card_dur) in enumerate(section_cards):
                seg = _prepare_clip_segment(card_path, card_dur, width, height, tmpdir, i + 1000)
                if seg:
                    segments.append(seg)
                card_path.unlink(missing_ok=True)

        if not segments:
            card = _make_text_card("Content", width, height)
            seg = _prepare_clip_segment(card, total_duration, width, height, tmpdir, 9999)
            if seg:
                segments.append(seg)
            card.unlink(missing_ok=True)

        if not segments:
            raise RuntimeError("No video segments could be created — all visual sources failed to encode")

        # Write concat list
        concat_file = tmpdir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{seg}'" for seg in segments))

        # Concatenate all segments and add audio in one ffmpeg pass.
        # Use -map to explicitly choose streams (avoids -shortest truncating to audio=0 when
        # audio metadata is missing) and pad audio to match video length instead.
        print(f"[video] Concatenating {len(segments)} segments ({total_duration:.1f}s audio) with audio...")
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        encode_timeout = max(600, int(total_duration * 4))  # scale with video length
        r = subprocess.run(cmd, capture_output=True, timeout=encode_timeout)
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace")[-500:]
            print(f"[video] Concat failed, trying full re-encode: {stderr}")
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-i", str(audio_path),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                "-r", "24",
                "-movflags", "+faststart",
                str(output_path),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=encode_timeout * 2)
            if r.returncode != 0:
                raise RuntimeError(f"Video assembly failed: {r.stderr.decode('utf-8', errors='replace')[-300:]}")

    if not output_path.exists():
        raise RuntimeError(f"Video output not found at {output_path}")

    final_size = output_path.stat().st_size
    if final_size < 50_000:  # less than 50 KB means something went wrong
        raise RuntimeError(
            f"Video assembly produced suspiciously small file ({final_size} bytes). "
            "Likely the visual segments failed to encode. Check ffmpeg logs."
        )

    print(f"[video] Video assembled: {final_size / 1024 / 1024:.1f} MB")
    return output_path


def _text_overlay_png(text: str, width: int, height: int, fontsize: int, position: str) -> Path:
    """Render a full-canvas transparent PNG with just the given text (+ a
    semi-transparent backing box) at the given position, for compositing via
    ffmpeg's overlay filter.

    Not drawtext: this build's static ffmpeg binary doesn't include the
    drawtext filter (confirmed directly -- "Unknown filter 'drawtext'" even
    though libfreetype/fontconfig are otherwise linked in), so text has to be
    rendered with PIL and composited as an image instead, same as every other
    text card in this codebase.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(fontsize)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 14
    if position == "bottom_right":
        x, y = width - tw - 24, height - th - 24
    else:  # "lower_third", centered
        x, y = (width - tw) // 2, int(height * 0.74)
    draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(0, 0, 0, 140))
    draw.text((x, y - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return Path(tmp.name)


def add_commercial_polish(
    video_path: Path,
    output_path: Path,
    width: int,
    height: int,
    brand: str = "",
    hero_text: str = "",
    cta_text: str = "",
    color_grade: bool = True,
) -> Path:
    """Bake in a persistent corner watermark, one or two timed on-screen text
    call-outs, and a subtle unified color grade -- the things that make
    assembled stock footage read as a produced commercial instead of a
    slideshow. One re-encode pass over the assembled body video; call this
    BEFORE add_outro_splash() so the splash's frozen last frame inherits the
    same graded/watermarked look."""
    ffmpeg = _get_ffmpeg()
    video_path, output_path = Path(video_path), Path(output_path)
    dur = _get_video_duration(video_path) or 15.0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        overlays = []  # list of (png_path, enable_expr_or_None)

        if brand:
            overlays.append((_text_overlay_png(brand, width, height, 26, "bottom_right"), None))
        if hero_text:
            hs = max(1.0, dur * 0.15)
            he = min(dur - 1.0, hs + 3.5)
            if he > hs:
                overlays.append((_text_overlay_png(hero_text, width, height, 46, "lower_third"),
                                  f"between(t,{hs:.2f},{he:.2f})"))
        if cta_text:
            ce, cs = dur, max(1.0, dur - 4.0)
            if ce > cs:
                overlays.append((_text_overlay_png(cta_text, width, height, 46, "lower_third"),
                                  f"between(t,{cs:.2f},{ce:.2f})"))

        if not overlays and not color_grade:
            import shutil
            shutil.copy(str(video_path), str(output_path))
            return output_path

        cmd = [ffmpeg, "-y", "-i", str(video_path)]
        for png, _ in overlays:
            cmd += ["-i", str(png)]

        base = "[0:v]eq=contrast=1.08:saturation=1.15:brightness=0.02,curves=preset=medium_contrast[v0]" \
            if color_grade else "[0:v]null[v0]"
        chain = [base]
        for i, (_, enable) in enumerate(overlays):
            src, dst = f"v{i}", f"v{i+1}"
            ov = f"overlay=0:0" + (f":enable='{enable}'" if enable else "")
            chain.append(f"[{src}][{i+1}:v]{ov}[{dst}]")
        filter_complex = ";".join(chain)
        final_label = f"v{len(overlays)}"

        cmd += ["-filter_complex", filter_complex, "-map", f"[{final_label}]", "-map", "0:a",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", "24",
                "-c:a", "copy",
                str(output_path)]

        result = subprocess.run(cmd, capture_output=True, timeout=max(120, int(dur * 6)))
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Could not apply commercial polish: {result.stderr.decode('utf-8', errors='replace')[-300:]}")
    return output_path


def add_outro_splash(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    brand: str,
    tagline: str,
    splash_duration: float,
    width: int,
    height: int,
) -> Path:
    """Freeze the last frame of video_path, overlay the brand name (+ tagline)
    over a darkened scrim, and append it as a splash-duration outro card with
    audio_path as its soundtrack (already full-volume, no voice — the voice
    track has ended by this point). Returns output_path: video_path with the
    outro appended."""
    ffmpeg = _get_ffmpeg()
    video_path, audio_path, output_path = Path(video_path), Path(audio_path), Path(output_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 1. Grab the last frame.
        last_frame = tmpdir / "last_frame.png"
        r = subprocess.run(
            [ffmpeg, "-y", "-sseof", "-1", "-i", str(video_path),
             "-update", "1", "-q:v", "2", str(last_frame)],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0 or not last_frame.exists():
            raise RuntimeError(f"Could not extract last frame: {r.stderr.decode('utf-8', errors='replace')[-200:]}")

        # 2. Overlay brand + tagline on a darkened copy of that frame so text stays legible.
        img = Image.open(last_frame).convert("RGB").resize((width, height))
        scrim = Image.new("RGB", img.size, (0, 0, 0))
        img = Image.blend(img, scrim, 0.45)
        draw = ImageDraw.Draw(img)
        center_x = width // 2

        brand_font = _load_font(min(64, height // 12))
        bbox = draw.textbbox((0, 0), brand, font=brand_font)
        by = int(height * 0.42)
        draw.text((center_x - (bbox[2] - bbox[0]) // 2, by), brand, font=brand_font, fill=(255, 255, 255))

        if tagline:
            tagline_font = _load_font(min(28, height // 26), bold=False)
            ty = by + (bbox[3] - bbox[1]) + 20
            tbbox = draw.textbbox((0, 0), tagline, font=tagline_font)
            draw.text((center_x - (tbbox[2] - tbbox[0]) // 2, ty), tagline, font=tagline_font, fill=(230, 230, 230))

        card_path = tmpdir / "splash_card.png"
        img.save(card_path)

        # 3. Turn the card into a splash_duration clip with the given (music-only) audio.
        splash_clip = tmpdir / "splash.mp4"
        r = subprocess.run(
            [ffmpeg, "-y", "-loop", "1", "-i", str(card_path), "-i", str(audio_path),
             "-t", f"{splash_duration:.2f}",
             "-vf", "fade=in:0:8",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", "24",
             "-c:a", "aac", "-b:a", "192k",
             "-shortest",
             str(splash_clip)],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0 or not splash_clip.exists():
            raise RuntimeError(f"Could not build outro splash clip: {r.stderr.decode('utf-8', errors='replace')[-200:]}")

        # 4. Append to the main video. Re-encode rather than stream-copy so this
        # is robust to whichever of create_video()'s two internal encode paths
        # (primary vs. its own fallback) produced video_path.
        concat_list = tmpdir / "concat.txt"
        concat_list.write_text(f"file '{video_path}'\nfile '{splash_clip}'\n")
        r = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", "24",
             "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart",
             str(output_path)],
            capture_output=True, timeout=60,
        )
        if r.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Could not append outro splash: {r.stderr.decode('utf-8', errors='replace')[-200:]}")

    return output_path


def create_podcast_video(
    audio_path: Path,
    output_path: Path,
    thumbnail_path: Optional[Path] = None,
    width: int = config.VIDEO_WIDTH,
    height: int = config.VIDEO_HEIGHT,
    channel_name: str = "My Podcast",
    episode_number: int = 1,
    title: str = "",
    sections: list[dict] = None,
) -> Path:
    """Create a podcast video with a static visual overlay and audio."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_duration = _get_duration(audio_path)
    ffmpeg = _get_ffmpeg()

    # Build the podcast frame as a single image
    frame = _build_podcast_frame(
        width, height, thumbnail_path, channel_name,
        episode_number, title, sections,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        frame_path = Path(tmpdir) / "podcast_frame.png"
        Image.fromarray(frame).save(str(frame_path))

        # Use ffmpeg to loop the image + overlay audio — extremely fast
        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-i", str(frame_path),
            "-i", str(audio_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-r", "1",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
        print(f"[video] Creating podcast video ({total_duration:.0f}s) with ffmpeg...")
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(
                f"Podcast video assembly failed: {r.stderr.decode('utf-8', errors='replace')[-300:]}"
            )

    print(f"[video] Podcast video: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    return output_path


def _build_podcast_frame(
    width: int, height: int,
    thumbnail_path: Optional[Path],
    channel_name: str,
    episode_number: int,
    title: str,
    sections: list[dict] = None,
) -> np.ndarray:
    """Build a single podcast frame image with all visual elements."""
    import math

    _FONTS = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]

    def _font(size: int):
        for fp in _FONTS:
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # Background
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            bg_img = Image.open(thumbnail_path).convert("RGB").resize((width, height), Image.LANCZOS)
            overlay_img = Image.new("RGB", (width, height), (0, 0, 0))
            bg_img = Image.blend(bg_img, overlay_img, 0.65)
            frame = np.array(bg_img)
        except Exception:
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            for y in range(height):
                v = int(10 + 20 * (1 - y / height))
                frame[y, :] = [v, v, v + 18]
    else:
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        for y in range(height):
            v = int(10 + 20 * (1 - y / height))
            frame[y, :] = [v, v, v + 18]

    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)

    # Header bar
    header_h = max(70, height // 11)
    draw.rectangle([(0, 0), (width, header_h)], fill=(20, 20, 40))
    fn_l = _font(max(28, header_h // 2 - 4))
    draw.text((36, header_h // 2 - 16), channel_name[:50], font=fn_l, fill=(240, 180, 60))
    ep_label = f"EP. {episode_number:02d}"
    fn_r = _font(max(22, header_h // 2 - 8))
    bb = draw.textbbox((0, 0), ep_label, font=fn_r)
    draw.text((width - (bb[2] - bb[0]) - 36, header_h // 2 - 14), ep_label, font=fn_r, fill=(160, 160, 180))
    draw.line([(0, header_h), (width, header_h)], fill=(60, 60, 100), width=2)

    # Title
    if title:
        fn_t = _font(max(30, height // 22))
        title_y = header_h + max(20, height // 16)
        draw.text((40, title_y), title[:80], font=fn_t, fill=(240, 240, 240))

    # Equalizer bars
    BARS = 48
    WV_H = height // 5
    WV_Y = height // 2 - WV_H // 2
    WV_W = width - 80
    bar_w = max(3, WV_W // (BARS * 2))
    spacing = WV_W // BARS
    max_h = int(WV_H * 0.88)
    cy = WV_Y + WV_H // 2

    for i in range(BARS):
        wave = 0.3 + 0.5 * abs(math.sin(i * 0.55))
        bh = max(6, int(max_h * wave))
        x0 = 40 + i * spacing + (spacing - bar_w) // 2
        x1 = x0 + bar_w
        y0 = max(0, cy - bh // 2)
        y1 = min(height - 1, cy + bh // 2)
        r = int(20 + 40 * wave)
        g = int(120 + 100 * wave)
        b = int(210 + 45 * wave)
        draw.rectangle([(x0, y0), (x1, y1)], fill=(r, g, b))

    # Chapter list
    ch_y = WV_Y + WV_H + max(18, height // 28)
    fn_ch = _font(max(22, height // 30))
    sections = sections or []
    if sections:
        for i, sec in enumerate(sections[:5]):
            name = sec.get("name", "")
            if name:
                draw.text((40, ch_y + i * 30), f"▶  {name[:60]}", font=fn_ch, fill=(180, 220, 255))
    else:
        draw.text((40, ch_y), "Now Playing", font=fn_ch, fill=(180, 220, 255))

    # Progress track
    BAR_H = max(6, height // 90)
    BAR_Y = height - max(50, height // 14)
    draw.rectangle([(40, BAR_Y), (width - 40, BAR_Y + BAR_H)], fill=(40, 40, 70))

    return np.array(img)


def get_audio_duration(audio_path: Path) -> float:
    """Get duration of audio file in seconds."""
    return _get_duration(audio_path)
