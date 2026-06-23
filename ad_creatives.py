"""
Ad Creative Generator — produces static ad images for Meta/social campaigns.
Generates multiple formats (feed 1200x628, story 1080x1920, square 1080x1080)
from video thumbnails and AI-generated copy.
"""
import os
import uuid
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

import config

log = logging.getLogger("ad_creatives")

AD_CREATIVES_DIR = config.DATA_DIR / "ad_creatives"
AD_CREATIVES_DIR.mkdir(parents=True, exist_ok=True)

# Standard Meta ad sizes
FORMATS = {
    "feed":   (1200, 628),
    "square": (1080, 1080),
    "story":  (1080, 1920),
}

# Brand colors
COLORS = {
    "dark":     {"bg": (10, 10, 10), "text": (255, 255, 255), "accent": (255, 59, 48), "muted": (160, 160, 160)},
    "light":    {"bg": (255, 255, 255), "text": (26, 26, 26), "accent": (37, 99, 235), "muted": (107, 114, 128)},
    "gradient": {"bg": (15, 7, 32), "text": (255, 255, 255), "accent": (139, 92, 246), "muted": (176, 160, 208)},
    "bold_red": {"bg": (180, 20, 20), "text": (255, 255, 255), "accent": (255, 220, 50), "muted": (255, 200, 200)},
}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try to load a system font, fall back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines or [text]


def _draw_rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.pieslice([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=fill)
    draw.pieslice([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=fill)
    draw.pieslice([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=fill)
    draw.pieslice([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=fill)


def generate_ad_creative(
    headline: str,
    body_text: str,
    cta_text: str = "Learn More",
    thumbnail_path: str = None,
    formats: list[str] = None,
    color_scheme: str = "dark",
    logo_path: str = None,
) -> dict:
    """
    Generate static ad creatives in multiple formats.

    Returns: {
        "creative_id": str,
        "files": {"feed": path, "square": path, "story": path},
        "formats_generated": list[str]
    }
    """
    creative_id = str(uuid.uuid4())[:8]
    formats = formats or list(FORMATS.keys())
    colors = COLORS.get(color_scheme, COLORS["dark"])

    # Load thumbnail if provided
    thumb = None
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb = Image.open(thumbnail_path).convert("RGBA")
        except Exception as e:
            log.warning("Could not load thumbnail: %s", e)

    files = {}
    for fmt in formats:
        if fmt not in FORMATS:
            continue
        w, h = FORMATS[fmt]
        img = _render_ad(w, h, headline, body_text, cta_text, thumb, colors, fmt)

        out_path = AD_CREATIVES_DIR / f"{creative_id}_{fmt}.png"
        img.save(str(out_path), "PNG", quality=95)
        files[fmt] = str(out_path)
        log.info("Generated %s ad: %s", fmt, out_path)

    return {
        "creative_id": creative_id,
        "files": files,
        "formats_generated": list(files.keys()),
    }


def _render_ad(w: int, h: int, headline: str, body_text: str, cta_text: str,
               thumb: Optional[Image.Image], colors: dict, fmt: str) -> Image.Image:
    """Render a single ad creative."""
    img = Image.new("RGB", (w, h), colors["bg"])
    draw = ImageDraw.Draw(img)

    pad = int(w * 0.06)

    if fmt == "story":
        # Vertical layout: thumbnail top half, text bottom half
        text_area_top = h // 2
        if thumb:
            t = thumb.copy()
            t = t.resize((w, h // 2), Image.LANCZOS)
            img.paste(t, (0, 0))
            # Gradient overlay at bottom of image
            for y in range(h // 2 - 80, h // 2):
                alpha = int(255 * (y - (h // 2 - 80)) / 80)
                draw.line([(0, y), (w, y)], fill=(*colors["bg"], alpha))

        # Headline
        head_font = _get_font(int(w * 0.07), bold=True)
        lines = _wrap_text(headline, head_font, w - pad * 2)
        y = text_area_top + pad
        for line in lines[:3]:
            draw.text((pad, y), line, font=head_font, fill=colors["text"])
            y += int(head_font.size * 1.3)

        # Body
        body_font = _get_font(int(w * 0.04))
        body_lines = _wrap_text(body_text, body_font, w - pad * 2)
        y += 20
        for line in body_lines[:3]:
            draw.text((pad, y), line, font=body_font, fill=colors["muted"])
            y += int(body_font.size * 1.4)

        # CTA button
        cta_font = _get_font(int(w * 0.045), bold=True)
        cta_bbox = cta_font.getbbox(cta_text)
        cta_w = cta_bbox[2] + 60
        cta_h = cta_bbox[3] + 30
        cta_x = (w - cta_w) // 2
        cta_y = h - pad - cta_h - 40
        _draw_rounded_rect(draw, (cta_x, cta_y, cta_x + cta_w, cta_y + cta_h), 12, colors["accent"])
        draw.text((cta_x + 30, cta_y + 12), cta_text, font=cta_font, fill=(255, 255, 255))

    elif fmt == "square":
        # Square: thumbnail top 60%, text bottom 40%
        text_area_top = int(h * 0.55)
        if thumb:
            t = thumb.copy()
            t = t.resize((w, int(h * 0.55)), Image.LANCZOS)
            img.paste(t, (0, 0))

        head_font = _get_font(int(w * 0.055), bold=True)
        lines = _wrap_text(headline, head_font, w - pad * 2)
        y = text_area_top + pad
        for line in lines[:2]:
            draw.text((pad, y), line, font=head_font, fill=colors["text"])
            y += int(head_font.size * 1.3)

        body_font = _get_font(int(w * 0.035))
        body_lines = _wrap_text(body_text, body_font, w - pad * 2)
        y += 10
        for line in body_lines[:2]:
            draw.text((pad, y), line, font=body_font, fill=colors["muted"])
            y += int(body_font.size * 1.4)

        # CTA button at bottom
        cta_font = _get_font(int(w * 0.04), bold=True)
        cta_bbox = cta_font.getbbox(cta_text)
        cta_w = cta_bbox[2] + 50
        cta_h = cta_bbox[3] + 24
        cta_x = pad
        cta_y = h - pad - cta_h
        _draw_rounded_rect(draw, (cta_x, cta_y, cta_x + cta_w, cta_y + cta_h), 10, colors["accent"])
        draw.text((cta_x + 25, cta_y + 10), cta_text, font=cta_font, fill=(255, 255, 255))

    else:  # feed (landscape)
        # Side-by-side: thumbnail left 50%, text right 50%
        text_x = w // 2 + pad
        if thumb:
            t = thumb.copy()
            t = t.resize((w // 2, h), Image.LANCZOS)
            img.paste(t, (0, 0))

        head_font = _get_font(int(h * 0.09), bold=True)
        text_max_w = w // 2 - pad * 2
        lines = _wrap_text(headline, head_font, text_max_w)
        y = pad + 10
        for line in lines[:3]:
            draw.text((text_x, y), line, font=head_font, fill=colors["text"])
            y += int(head_font.size * 1.2)

        body_font = _get_font(int(h * 0.055))
        body_lines = _wrap_text(body_text, body_font, text_max_w)
        y += 12
        for line in body_lines[:3]:
            draw.text((text_x, y), line, font=body_font, fill=colors["muted"])
            y += int(body_font.size * 1.4)

        # CTA button
        cta_font = _get_font(int(h * 0.06), bold=True)
        cta_bbox = cta_font.getbbox(cta_text)
        cta_w = cta_bbox[2] + 40
        cta_h = cta_bbox[3] + 20
        cta_x = text_x
        cta_y = h - pad - cta_h - 10
        _draw_rounded_rect(draw, (cta_x, cta_y, cta_x + cta_w, cta_y + cta_h), 8, colors["accent"])
        draw.text((cta_x + 20, cta_y + 8), cta_text, font=cta_font, fill=(255, 255, 255))

    return img


def generate_bulk_creatives(
    variants: list[dict],
    thumbnail_path: str = None,
    formats: list[str] = None,
    color_scheme: str = "dark",
) -> list[dict]:
    """
    Generate ad creatives for multiple copy variants at once.
    Each variant: {"headline": str, "body": str, "cta": str}
    Returns list of creative results.
    """
    results = []
    for v in variants:
        result = generate_ad_creative(
            headline=v.get("headline", ""),
            body_text=v.get("body", ""),
            cta_text=v.get("cta", "Learn More"),
            thumbnail_path=thumbnail_path,
            formats=formats,
            color_scheme=color_scheme,
        )
        results.append(result)
    return results


def list_creatives() -> list:
    """List all generated ad creatives."""
    creatives = {}
    for f in AD_CREATIVES_DIR.glob("*.png"):
        parts = f.stem.rsplit("_", 1)
        if len(parts) == 2:
            cid, fmt = parts
            if cid not in creatives:
                creatives[cid] = {"creative_id": cid, "files": {}, "formats_generated": []}
            creatives[cid]["files"][fmt] = str(f)
            creatives[cid]["formats_generated"].append(fmt)
    return list(creatives.values())
