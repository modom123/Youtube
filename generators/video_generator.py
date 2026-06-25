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


def _get_duration(path: Path) -> float:
    """Get media duration using ffprobe."""
    ffmpeg = _get_ffmpeg()
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        from moviepy import AudioFileClip
        clip = AudioFileClip(str(path))
        d = clip.duration
        clip.close()
        return d


def _get_video_duration(path: Path) -> float:
    """Get video file duration."""
    ffmpeg = _get_ffmpeg()
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0


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


def _make_text_image(
    text: str,
    width: int,
    font_size: int = 36,
    color: tuple = (255, 255, 255),
    bg: tuple = (0, 0, 0, 140),
) -> Optional[np.ndarray]:
    """Render text to a numpy image array using Pillow."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            pass
    if not font:
        font = ImageFont.load_default()

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = 20
    img = Image.new("RGBA", (min(tw + pad * 2, width), th + pad * 2), (0, 0, 0, 0))
    overlay = Image.new("RGBA", img.size, bg)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    draw.text((pad, pad), text, font=font, fill=color + (255,) if len(color) == 3 else color)
    return np.array(img.convert("RGB"))


def _prepare_clip_segment(source: Path, duration: float, width: int, height: int, tmpdir: Path, idx: int) -> Optional[Path]:
    """Use ffmpeg to create a scaled/cropped segment from a source file."""
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
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start:.2f}",
            "-i", str(source),
            "-t", f"{actual_dur:.2f}",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fade=in:0:6,fade=out:st={max(0, actual_dur-0.3):.2f}:d=0.3",
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", "24",
            str(out),
        ]
    elif is_image:
        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-i", str(source),
            "-t", f"{duration:.2f}",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", "24",
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
                seg = _prepare_clip_segment(source, clip_duration, width, height, tmpdir, idx)
                if seg:
                    segments.append(seg)
                    elapsed += clip_duration
                idx += 1
                if idx > len(all_visuals) * 3 and not segments:
                    break

        if not segments:
            print("[video] No visual segments — creating gradient backgrounds")
            gradients = [
                ((15, 15, 40), (40, 20, 60)),
                ((10, 25, 45), (20, 50, 70)),
                ((30, 15, 35), (50, 25, 55)),
                ((5, 20, 35), (15, 45, 60)),
            ]
            elapsed = 0.0
            idx = 0
            while elapsed < total_duration:
                seg_dur = min(random.uniform(5, 10), total_duration - elapsed)
                if seg_dur < 0.5:
                    break
                c1, c2 = gradients[idx % len(gradients)]
                grad_img = _make_gradient_image(width, height, c1, c2)
                seg = _prepare_clip_segment(grad_img, seg_dur, width, height, tmpdir, idx + 1000)
                if seg:
                    segments.append(seg)
                    elapsed += seg_dur
                grad_img.unlink(missing_ok=True)
                idx += 1

        if not segments:
            # Last resort: single color frame
            color_img = _make_gradient_image(width, height, (15, 15, 40), (15, 15, 40))
            seg = _prepare_clip_segment(color_img, total_duration, width, height, tmpdir, 9999)
            if seg:
                segments.append(seg)
            color_img.unlink(missing_ok=True)

        # Write concat list
        concat_file = tmpdir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{seg}'" for seg in segments))

        # Concatenate all segments and add audio in one ffmpeg pass
        print(f"[video] Concatenating {len(segments)} segments with audio...")
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace")[-500:]
            print(f"[video] Concat failed, trying re-encode: {stderr}")
            # Fallback: re-encode during concat
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-i", str(audio_path),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-r", "24",
                "-shortest",
                "-movflags", "+faststart",
                str(output_path),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError(f"Video assembly failed: {r.stderr.decode('utf-8', errors='replace')[-300:]}")

    if not output_path.exists():
        raise RuntimeError(f"Video output not found at {output_path}")

    print(f"[video] Video assembled: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
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
