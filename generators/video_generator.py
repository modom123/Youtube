"""Assemble final videos from audio, stock clips, and graphics using MoviePy 2.x."""
import random
from pathlib import Path
from typing import Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy import (
    AudioFileClip,
    VideoFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
)
from moviepy.video.fx import FadeIn, FadeOut, CrossFadeIn, CrossFadeOut

import config


def _fit_clip(clip, target_w: int, target_h: int):
    """Scale and crop a clip to fill target dimensions."""
    iw, ih = clip.size
    scale = max(target_w / iw, target_h / ih)
    clip = clip.resized(scale)
    clip = clip.cropped(
        x_center=clip.size[0] // 2,
        y_center=clip.size[1] // 2,
        width=target_w,
        height=target_h,
    )
    return clip


def _load_image_clip(
    image_path: Path,
    duration: float,
    target_w: int,
    target_h: int,
) -> ImageClip:
    """Load image as a video clip."""
    clip = ImageClip(str(image_path)).with_duration(duration)
    clip = _fit_clip(clip, target_w, target_h)
    clip = clip.with_effects([FadeIn(0.4), FadeOut(0.4)])
    return clip


def _load_video_clip(
    video_path: Path,
    duration: float,
    target_w: int,
    target_h: int,
    start_at: float = 0,
) -> VideoFileClip:
    """Load and trim a stock video clip."""
    clip = VideoFileClip(str(video_path), audio=False)
    available = clip.duration - start_at
    actual_duration = min(duration, max(available, 0.5))
    if actual_duration < 0.5:
        start_at = 0
        actual_duration = min(duration, clip.duration)
    clip = clip.subclipped(start_at, start_at + actual_duration)
    clip = _fit_clip(clip, target_w, target_h)
    clip = clip.with_effects([FadeIn(0.3), FadeOut(0.3)])
    return clip


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

    # Measure text
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
    """Assemble the final video from audio and visual assets."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio = AudioFileClip(str(audio_path))
    total_duration = audio.duration

    video_clips = video_clips or []
    image_clips = image_clips or []
    all_visuals = list(video_clips) + list(image_clips)

    if not all_visuals:
        bg = ColorClip(size=(width, height), color=(20, 20, 40)).with_duration(total_duration)
        visual_clips = [bg]
    else:
        random.shuffle(all_visuals)
        visual_clips = []
        elapsed = 0.0
        i = 0
        while elapsed < total_duration:
            remaining = total_duration - elapsed
            clip_duration = min(random.uniform(4, 8), remaining)
            if clip_duration < 0.5:
                break
            source = all_visuals[i % len(all_visuals)]
            i += 1
            try:
                if source.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv"):
                    start = random.uniform(0, 3)
                    clip = _load_video_clip(source, clip_duration, width, height, start_at=start)
                else:
                    clip = _load_image_clip(source, clip_duration, width, height)
                clip = clip.with_start(elapsed)
                visual_clips.append(clip)
                elapsed += clip_duration
            except Exception as e:
                print(f"[video] Skipping {source.name}: {e}")

    if not visual_clips:
        visual_clips = [ColorClip(size=(width, height), color=(20, 20, 40)).with_duration(total_duration)]

    composite_layers = list(visual_clips)

    # Branding bar
    try:
        brand_arr = _make_text_image("Social Optimize", width, font_size=22,
                                     color=(200, 200, 200), bg=(0, 0, 0, 120))
        brand_clip = (
            ImageClip(brand_arr)
            .with_duration(total_duration)
            .with_position(("left", height - 50))
        )
        composite_layers.append(brand_clip)
    except Exception:
        pass

    final = CompositeVideoClip(composite_layers, size=(width, height))
    final = final.with_audio(audio).with_duration(total_duration)

    final.write_videofile(
        str(output_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=4,
        logger=None,
    )
    audio.close()
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
    """
    Create a dynamic podcast video with animated equalizer waveform,
    chapter markers, episode info, and animated progress bar.
    """
    from moviepy import VideoClip
    import math

    audio = AudioFileClip(str(audio_path))
    total_duration = audio.duration
    sections = sections or []

    # ── font helpers ──────────────────────────────────────────────────────────
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

    def _text_img(text: str, size: int, color, max_w: int, bg=(0, 0, 0, 0)) -> np.ndarray:
        font = _font(size)
        dummy = Image.new("RGBA", (1, 1))
        bbox = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=font)
        tw = min(bbox[2] - bbox[0], max_w)
        th = bbox[3] - bbox[1]
        pad = 12
        img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), bg)
        ImageDraw.Draw(img).text((pad, pad), text[:80], font=font, fill=color)
        return np.array(img.convert("RGB"))

    # ── background layer ──────────────────────────────────────────────────────
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            bg_img = Image.open(thumbnail_path).convert("RGB").resize((width, height), Image.LANCZOS)
            # Dark overlay so text and waveform stand out
            overlay = Image.new("RGB", (width, height), (0, 0, 0))
            bg_img = Image.blend(bg_img, overlay, 0.65)
            bg = ImageClip(np.array(bg_img)).with_duration(total_duration)
        except Exception:
            bg = ColorClip(size=(width, height), color=(12, 12, 25)).with_duration(total_duration)
    else:
        # Gradient dark background
        grad = np.zeros((height, width, 3), dtype=np.uint8)
        for y in range(height):
            v = int(10 + 20 * (1 - y / height))
            grad[y, :] = [v, v, v + 18]
        bg = ImageClip(grad).with_duration(total_duration)

    layers = [bg]

    # ── header: podcast name + episode number ─────────────────────────────────
    ep_label = f"EP. {episode_number:02d}"
    header_h = max(70, height // 11)
    header = Image.new("RGB", (width, header_h), (20, 20, 40))
    draw = ImageDraw.Draw(header)
    # Left: podcast name
    fn_l = _font(max(28, header_h // 2 - 4))
    draw.text((36, header_h // 2 - 16), channel_name[:50], font=fn_l, fill=(240, 180, 60))
    # Right: episode number
    fn_r = _font(max(22, header_h // 2 - 8))
    bb = draw.textbbox((0, 0), ep_label, font=fn_r)
    draw.text((width - (bb[2] - bb[0]) - 36, header_h // 2 - 14), ep_label, font=fn_r, fill=(160, 160, 180))
    layers.append(ImageClip(np.array(header)).with_duration(total_duration).with_position((0, 0)))

    # Divider line under header
    div = np.zeros((2, width, 3), dtype=np.uint8)
    div[:] = [60, 60, 100]
    layers.append(ImageClip(div).with_duration(total_duration).with_position((0, header_h)))

    # ── episode title ─────────────────────────────────────────────────────────
    if title:
        title_arr = _text_img(title[:80], max(30, height // 22), (240, 240, 240), width - 80)
        title_y = header_h + max(20, height // 16)
        layers.append(
            ImageClip(title_arr).with_duration(total_duration).with_position((40, title_y))
        )

    # ── animated equalizer waveform ───────────────────────────────────────────
    BARS = 48
    WV_H = height // 5
    WV_Y = height // 2 - WV_H // 2
    WV_W = width - 80

    def _waveform_frame(t: float) -> np.ndarray:
        frame = np.zeros((WV_H, WV_W, 3), dtype=np.uint8)
        bar_w = max(3, WV_W // (BARS * 2))
        spacing = WV_W // BARS
        max_h = int(WV_H * 0.88)
        cy = WV_H // 2

        for i in range(BARS):
            wave = (
                0.35 * abs(math.sin(t * 2.1 + i * 0.55)) +
                0.28 * abs(math.sin(t * 3.7 + i * 0.85)) +
                0.22 * abs(math.sin(t * 1.3 + i * 1.25)) +
                0.15 * abs(math.sin(t * 5.2 + i * 0.35))
            )
            bh = max(6, int(max_h * wave))
            x0 = i * spacing + (spacing - bar_w) // 2
            x1 = x0 + bar_w
            y0 = max(0, cy - bh // 2)
            y1 = min(WV_H - 1, cy + bh // 2)

            # Teal-to-blue gradient colour based on amplitude
            r = int(20 + 40 * wave)
            g = int(120 + 100 * wave)
            b = int(210 + 45 * wave)
            frame[y0:y1 + 1, x0:x1 + 1] = [r, g, b]

            # Subtle glow: lighter wider bar behind
            if x0 > 1 and x1 < WV_W - 1:
                frame[y0:y1 + 1, max(0, x0 - 1):min(WV_W, x1 + 2)] = [
                    min(255, r + 30),
                    min(255, g + 20),
                    min(255, b + 10),
                ]
                frame[y0:y1 + 1, x0:x1 + 1] = [r, g, b]  # restore main bar on top

        return frame

    wv_clip = (
        VideoClip(lambda t: _waveform_frame(t), duration=total_duration)
        .with_position((40, WV_Y))
    )
    layers.append(wv_clip)

    # ── chapter title cards ───────────────────────────────────────────────────
    ch_y = WV_Y + WV_H + max(18, height // 28)
    if sections:
        elapsed = 0.0
        for sec in sections:
            dur = float(sec.get("duration", 60))
            name = sec.get("name", "")
            if name and dur > 0:
                ch_arr = _text_img(
                    f"▶  {name}",
                    max(22, height // 30),
                    (180, 220, 255),
                    width - 80,
                    bg=(0, 0, 0, 0),
                )
                layers.append(
                    ImageClip(ch_arr)
                    .with_start(elapsed)
                    .with_duration(dur)
                    .with_position((40, ch_y))
                )
            elapsed += dur
    else:
        # Static fallback label
        pod_arr = _text_img("🎙  Now Playing", max(22, height // 30), (180, 220, 255), width - 80)
        layers.append(ImageClip(pod_arr).with_duration(total_duration).with_position((40, ch_y)))

    # ── animated progress bar ─────────────────────────────────────────────────
    BAR_H = max(6, height // 90)
    BAR_Y = height - max(50, height // 14)
    BAR_W = width - 80

    def _prog_frame(t: float) -> np.ndarray:
        frame = np.zeros((BAR_H + 40, BAR_W, 3), dtype=np.uint8)
        # Track (dim)
        frame[:BAR_H, :] = [40, 40, 70]
        # Filled portion
        filled = max(0, min(BAR_W, int(BAR_W * t / total_duration)))
        frame[:BAR_H, :filled] = [80, 160, 255]
        # Playhead dot
        dot_x = max(0, min(BAR_W - 1, filled))
        dot_r = BAR_H + 4
        for dy in range(-dot_r, dot_r + 1):
            for dx in range(-dot_r, dot_r + 1):
                if dx * dx + dy * dy <= dot_r * dot_r:
                    py = dy
                    px = dot_x + dx
                    if 0 <= py < BAR_H + 8 and 0 <= px < BAR_W:
                        frame[max(0, py):min(BAR_H + 40, py + 1), px] = [120, 200, 255]

        # Time label (static image per-second; we rebuild each frame)
        elapsed_s = int(t)
        total_s = int(total_duration)
        ts = f"{elapsed_s//60}:{elapsed_s%60:02d} / {total_s//60}:{total_s%60:02d}"
        try:
            lbl_img = Image.new("RGB", (BAR_W, 26), (0, 0, 0))
            lbl_draw = ImageDraw.Draw(lbl_img)
            lbl_font = _font(18)
            lbl_draw.text((0, 4), ts, font=lbl_font, fill=(140, 140, 180))
            frame[BAR_H + 8: BAR_H + 34, :] = np.array(lbl_img)
        except Exception:
            pass
        return frame

    prog_clip = (
        VideoClip(lambda t: _prog_frame(t), duration=total_duration)
        .with_position((40, BAR_Y))
    )
    layers.append(prog_clip)

    # ── compose & render ──────────────────────────────────────────────────────
    final = CompositeVideoClip(layers, size=(width, height))
    final = final.with_audio(audio).with_duration(total_duration)
    final.write_videofile(
        str(output_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=4,
        logger=None,
    )
    audio.close()
    return output_path
