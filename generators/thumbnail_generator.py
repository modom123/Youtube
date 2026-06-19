"""Generate eye-catching thumbnails using Pillow."""
import textwrap
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests
from io import BytesIO
import config


GRADIENT_PRESETS = {
    "fire": [(255, 69, 0), (255, 165, 0)],
    "ocean": [(0, 119, 190), (0, 212, 255)],
    "purple": [(75, 0, 130), (238, 130, 238)],
    "dark": [(20, 20, 20), (60, 60, 60)],
    "green": [(0, 128, 0), (0, 255, 127)],
    "sunset": [(255, 94, 77), (255, 175, 66)],
}


def _draw_gradient(img: Image.Image, color1: tuple, color2: tuple) -> Image.Image:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        ratio = y / h
        r = int(color1[0] + (color2[0] - color1[0]) * ratio)
        g = int(color1[1] + (color2[1] - color1[1]) * ratio)
        b = int(color1[2] + (color2[2] - color1[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def _get_font(size: int) -> ImageFont.ImageFont:
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _add_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    text: str,
    position: tuple,
    font: ImageFont.ImageFont,
    text_color: tuple = (255, 255, 255),
    shadow_color: tuple = (0, 0, 0),
    shadow_offset: int = 3,
) -> None:
    x, y = position
    # Shadow
    for ox, oy in [(shadow_offset, shadow_offset), (-shadow_offset, shadow_offset),
                   (shadow_offset, -shadow_offset), (-shadow_offset, -shadow_offset)]:
        draw.text((x + ox, y + oy), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=text_color)


def generate_thumbnail(
    title: str,
    output_path: Path,
    background_image_path: Optional[Path] = None,
    background_url: Optional[str] = None,
    style: str = "fire",
    width: int = 1280,
    height: int = 720,
    subtitle: Optional[str] = None,
    emoji: str = "",
) -> Path:
    """Generate a YouTube/social media thumbnail."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Base image
    img = Image.new("RGB", (width, height))

    # Background
    bg_loaded = False
    if background_image_path and Path(background_image_path).exists():
        try:
            bg = Image.open(background_image_path).convert("RGB")
            bg = bg.resize((width, height), Image.LANCZOS)
            bg = ImageEnhance.Brightness(bg).enhance(0.5)
            img.paste(bg)
            bg_loaded = True
        except Exception:
            pass

    if not bg_loaded and background_url:
        try:
            resp = requests.get(background_url, timeout=10)
            bg = Image.open(BytesIO(resp.content)).convert("RGB")
            bg = bg.resize((width, height), Image.LANCZOS)
            bg = ImageEnhance.Brightness(bg).enhance(0.5)
            img.paste(bg)
            bg_loaded = True
        except Exception:
            pass

    if not bg_loaded:
        colors = GRADIENT_PRESETS.get(style, GRADIENT_PRESETS["fire"])
        img = _draw_gradient(img, colors[0], colors[1])

    # Overlay for readability
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    # Accent bar
    bar_h = height // 8
    for y in range(height - bar_h, height):
        ratio = (y - (height - bar_h)) / bar_h
        colors = GRADIENT_PRESETS.get(style, GRADIENT_PRESETS["fire"])
        r = int(colors[0][0] * (1 - ratio) + colors[1][0] * ratio)
        g = int(colors[0][1] * (1 - ratio) + colors[1][1] * ratio)
        b = int(colors[0][2] * (1 - ratio) + colors[1][2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 200))

    # Title text
    max_chars = 22 if len(title) > 30 else 28
    lines = textwrap.wrap(title.upper(), width=max_chars)

    font_size = 100 if len(lines) == 1 else 80 if len(lines) == 2 else 65
    font = _get_font(font_size)

    total_text_h = len(lines) * (font_size + 10)
    y_start = (height - total_text_h) // 2 - 30

    for i, line in enumerate(lines):
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(line) * font_size // 2

        x = (width - text_w) // 2
        y = y_start + i * (font_size + 10)
        _add_text_with_shadow(draw, line, (x, y), font, shadow_offset=4)

    # Subtitle
    if subtitle:
        sub_font = _get_font(36)
        sub_lines = textwrap.wrap(subtitle, width=50)
        sub_y = y_start + total_text_h + 20
        for line in sub_lines[:2]:
            try:
                bbox = draw.textbbox((0, 0), line, font=sub_font)
                sub_w = bbox[2] - bbox[0]
            except Exception:
                sub_w = len(line) * 20
            draw.text(((width - sub_w) // 2, sub_y), line, font=sub_font, fill=(220, 220, 220))
            sub_y += 44

    img.save(str(output_path), "JPEG", quality=95)
    return output_path
