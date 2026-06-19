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
) -> Path:
    """Create a static podcast video."""
    audio = AudioFileClip(str(audio_path))
    total_duration = audio.duration

    if thumbnail_path and Path(thumbnail_path).exists():
        bg = ImageClip(str(thumbnail_path)).resized((width, height)).with_duration(total_duration)
    else:
        bg = ColorClip(size=(width, height), color=(15, 15, 30)).with_duration(total_duration)

    card_w, card_h = width - 200, height - 300
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 180))
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            thumb = Image.open(thumbnail_path).resize((card_w, card_h), Image.LANCZOS)
            card.paste(thumb, (0, 0))
            overlay = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 120))
            card = Image.alpha_composite(card.convert("RGBA"), overlay)
        except Exception:
            pass

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 60)
            break
        except Exception:
            pass
    if not font:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(card)
    draw.text((50, 50), "PODCAST", font=font, fill=(255, 165, 0))
    draw.text((50, 140), channel_name[:40], font=font, fill=(255, 255, 255))

    card_clip = (
        ImageClip(np.array(card.convert("RGB")))
        .with_duration(total_duration)
        .with_position(("center", "center"))
    )

    final = CompositeVideoClip([bg, card_clip], size=(width, height))
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
