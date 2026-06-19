"""Assemble final videos from audio, stock clips, and graphics using MoviePy."""
import random
from pathlib import Path
from typing import Optional
import numpy as np
from moviepy.editor import (
    AudioFileClip,
    VideoFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    TextClip,
    ColorClip,
)
from moviepy.video.fx.all import resize, crop, fadein, fadeout
from PIL import Image, ImageDraw, ImageFont
import config


def _load_image_clip(
    image_path: Path,
    duration: float,
    target_w: int,
    target_h: int,
    zoom: bool = True,
) -> ImageClip:
    """Load image as video clip with optional Ken Burns zoom effect."""
    clip = ImageClip(str(image_path)).set_duration(duration)
    iw, ih = clip.size

    scale = max(target_w / iw, target_h / ih) * 1.1
    clip = clip.resize(scale)

    if zoom:
        def zoom_effect(t):
            progress = t / duration
            zoom_factor = 1.0 + 0.05 * progress
            new_w = int(clip.size[0] * zoom_factor)
            new_h = int(clip.size[1] * zoom_factor)
            return clip.resize((new_w, new_h)).crop(
                x_center=new_w // 2, y_center=new_h // 2,
                width=target_w, height=target_h,
            ).get_frame(t)
        clip = clip.fl(lambda gf, t: zoom_effect(t))

    clip = clip.crop(
        x_center=clip.size[0] // 2,
        y_center=clip.size[1] // 2,
        width=target_w,
        height=target_h,
    )
    clip = fadein(clip, 0.5).fx(fadeout, 0.5)
    return clip


def _load_video_clip(
    video_path: Path,
    duration: float,
    target_w: int,
    target_h: int,
    start_at: float = 0,
) -> VideoFileClip:
    """Load and trim a stock video clip to fit target duration."""
    clip = VideoFileClip(str(video_path), audio=False)
    available = clip.duration - start_at
    actual_duration = min(duration, available)

    if actual_duration < 1:
        start_at = 0
        actual_duration = min(duration, clip.duration)

    clip = clip.subclip(start_at, start_at + actual_duration)

    iw, ih = clip.size
    scale = max(target_w / iw, target_h / ih)
    clip = clip.resize(scale)
    clip = clip.crop(
        x_center=clip.size[0] // 2,
        y_center=clip.size[1] // 2,
        width=target_w,
        height=target_h,
    )
    clip = fadein(clip, 0.3).fx(fadeout, 0.3)
    return clip


def _create_text_overlay(
    text: str,
    width: int,
    height: int,
    duration: float,
    font_size: int = 40,
    y_position: str = "bottom",
) -> Optional[ImageClip]:
    """Create a subtitle/text overlay clip."""
    try:
        clip = TextClip(
            text,
            fontsize=font_size,
            color="white",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(width - 100, None),
            align="center",
        )
        y_pos = height - clip.h - 60 if y_position == "bottom" else 40
        clip = clip.set_position(("center", y_pos)).set_duration(duration)
        clip = fadein(clip, 0.2).fx(fadeout, 0.2)
        return clip
    except Exception:
        return None


def _create_color_clip(
    color: tuple,
    width: int,
    height: int,
    duration: float,
) -> ColorClip:
    return ColorClip(size=(width, height), color=color, duration=duration)


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
        # Fallback: solid color background
        bg = _create_color_clip((20, 20, 40), width, height, total_duration)
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

                clip = clip.set_start(elapsed)
                visual_clips.append(clip)
                elapsed += clip_duration
            except Exception as e:
                print(f"[video] Skipping {source.name}: {e}")

    if not visual_clips:
        visual_clips = [_create_color_clip((20, 20, 40), width, height, total_duration)]

    composite_layers = visual_clips.copy()

    # Watermark / branding bar at bottom
    try:
        brand_img = Image.new("RGBA", (width, 50), (0, 0, 0, 120))
        draw = ImageDraw.Draw(brand_img)
        draw.text((20, 10), "Social Optimize Machine", fill=(200, 200, 200, 200))
        brand_clip = ImageClip(np.array(brand_img)).set_duration(total_duration).set_position(("left", height - 50))
        composite_layers.append(brand_clip)
    except Exception:
        pass

    # Add sections as title cards
    if sections:
        for section in sections:
            if section.get("name") and section.get("duration"):
                try:
                    tc = TextClip(
                        section["name"].upper(),
                        fontsize=28,
                        color="white",
                        stroke_color="black",
                        stroke_width=1,
                    )
                    # Position section titles in top-left
                    tc = tc.set_duration(min(2.0, section["duration"])).set_position((30, 30))
                    tc = fadein(tc, 0.3).fx(fadeout, 0.3)
                    composite_layers.append(tc)
                except Exception:
                    pass

    final = CompositeVideoClip(composite_layers, size=(width, height))
    final = final.set_audio(audio).set_duration(total_duration)

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
    """Create a static/animated podcast video (waveform style)."""
    audio = AudioFileClip(str(audio_path))
    total_duration = audio.duration

    # Background
    if thumbnail_path and Path(thumbnail_path).exists():
        bg = ImageClip(str(thumbnail_path)).resize((width, height)).set_duration(total_duration)
        # Blur background
        def blur_frame(gf, t):
            frame = gf(t)
            img = Image.fromarray(frame).filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(radius=15))
            return np.array(img)
        bg = bg.fl(blur_frame)
    else:
        bg = _create_color_clip((15, 15, 30), width, height, total_duration)

    # Podcast overlay card
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

    draw = ImageDraw.Draw(card)
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

    draw.text((50, 50), "🎙 PODCAST", font=font, fill=(255, 165, 0))
    draw.text((50, 140), channel_name[:40], font=font, fill=(255, 255, 255))

    card_clip = (
        ImageClip(np.array(card.convert("RGB")))
        .set_duration(total_duration)
        .set_position(("center", "center"))
    )

    final = CompositeVideoClip([bg, card_clip], size=(width, height))
    final = final.set_audio(audio).set_duration(total_duration)

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
