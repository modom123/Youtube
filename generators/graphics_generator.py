"""
Graphics Generator — creates ranked cards, bar charts, info graphics, and data visuals
for list-style content like "Top 10 teams with most World Cup victories".
"""
import re
import textwrap
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


def _safe_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return default


# ── Font helpers ─────────────────────────────────────────────────────────────

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]

FONT_PATHS_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    paths = FONT_PATHS if bold else FONT_PATHS_REGULAR
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _shadow_text(draw, text, pos, font, color=(255, 255, 255), shadow=(0, 0, 0), offset=3):
    x, y = pos
    for dx, dy in [(-offset, -offset), (offset, -offset), (-offset, offset), (offset, offset)]:
        draw.text((x + dx, y + dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=color)


def _text_w(draw, text, font):
    try:
        return draw.textbbox((0, 0), text, font=font)[2]
    except Exception:
        return len(text) * (font.size // 2 if hasattr(font, "size") else 10)


# ── Color palette ─────────────────────────────────────────────────────────────

RANK_COLORS = [
    (230, 32,  32),   # #1 — Red
    (250, 204, 21),   # #2 — Yellow/Gold
    (34,  197, 94),   # #3 — Green
    (59,  130, 246),  # #4 — Blue
    (168, 85,  247),  # #5 — Purple
    (249, 115, 22),   # #6 — Orange
    (20,  184, 166),  # #7 — Teal
    (236, 72,  153),  # #8 — Pink
    (139, 92,  246),  # #9 — Violet
    (100, 116, 139),  # #10 — Slate
]


def _rank_color(rank: int) -> tuple:
    return RANK_COLORS[(rank - 1) % len(RANK_COLORS)]


# ── Ranked Item Card ──────────────────────────────────────────────────────────

def create_rank_card(
    rank: int,
    name: str,
    value: str,
    sub_info: str = "",
    output_path: Optional[Path] = None,
    width: int = 1080,
    height: int = 400,
    bg_image_path: Optional[Path] = None,
    is_portrait: bool = False,
) -> Image.Image:
    """
    Create a visually striking ranked item card.
    e.g. rank=1, name="Brazil", value="5 World Cup titles", sub_info="1958, 1962, 1970, 1994, 2002"
    """
    if is_portrait:
        width, height = 1080, 500

    img = Image.new("RGB", (width, height), (10, 10, 15))
    draw = ImageDraw.Draw(img)

    # Background: dark gradient
    for y in range(height):
        ratio = y / height
        r = int(10 + 20 * ratio)
        g = int(10 + 20 * ratio)
        b = int(15 + 30 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Optional background image (blurred, dark overlay)
    if bg_image_path and Path(bg_image_path).exists():
        try:
            bg = Image.open(bg_image_path).convert("RGB").resize((width, height), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=8))
            bg = ImageEnhance.Brightness(bg).enhance(0.3)
            img.paste(bg)
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    color = _rank_color(rank)

    # Left accent bar
    bar_w = 10
    draw.rectangle([0, 0, bar_w, height], fill=color)

    # Rank badge (large number)
    rank_font_size = min(160, height - 40)
    rank_font = _font(rank_font_size)
    rank_str = f"#{rank}"
    rw = _text_w(draw, rank_str, rank_font)
    rank_x = bar_w + 30
    rank_y = (height - rank_font_size) // 2 - 10

    # Rank number glow
    for offset in range(8, 0, -2):
        draw.text((rank_x - offset, rank_y - offset), rank_str, font=rank_font,
                  fill=(*color, max(0, 255 - offset * 30)))

    draw.text((rank_x, rank_y), rank_str, font=rank_font, fill=color)

    # Content area
    content_x = rank_x + rw + 40
    available_w = width - content_x - 30

    # Name
    name_font_size = min(80, max(40, available_w // max(len(name), 1) * 2))
    name_font = _font(min(name_font_size, 72))
    name_lines = textwrap.wrap(name, width=max(10, available_w // (name_font_size // 2)))

    name_y = 40
    for line in name_lines[:2]:
        _shadow_text(draw, line, (content_x, name_y), name_font, color=(255, 255, 255))
        name_y += name_font_size + 6

    # Value (e.g. "5 World Cup titles")
    val_font = _font(44)
    _shadow_text(draw, value, (content_x, name_y + 10), val_font, color=color)

    # Sub-info (smaller detail)
    if sub_info:
        sub_font = _font(30, bold=False)
        sub_lines = textwrap.wrap(sub_info, width=max(20, available_w // 18))
        sub_y = name_y + 70
        for line in sub_lines[:2]:
            draw.text((content_x, sub_y), line, font=sub_font, fill=(180, 180, 180))
            sub_y += 36

    # Bottom accent line
    draw.rectangle([0, height - 4, width, height], fill=color)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "JPEG", quality=92)

    return img


# ── Bar Chart ─────────────────────────────────────────────────────────────────

def create_bar_chart(
    items: list[dict],   # [{"name": "Brazil", "value": 5, "label": "5 titles"}, ...]
    title: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    x_label: str = "",
) -> Path:
    """Create a styled bar chart image."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not items:
        img = Image.new("RGB", (width, height), (10, 10, 15))
        img.save(str(output_path), "JPEG")
        return output_path

    # Sort descending
    items = sorted(items, key=lambda x: x.get("value", 0), reverse=True)[:15]
    max_val = max(x.get("value", 1) for x in items) or 1

    img = Image.new("RGB", (width, height), (10, 10, 15))
    draw = ImageDraw.Draw(img)

    # Background gradient
    for y in range(height):
        ratio = y / height
        r = int(10 + 15 * ratio)
        g = int(10 + 15 * ratio)
        b = int(15 + 25 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Margins
    margin_left = 220
    margin_right = 60
    margin_top = 100
    margin_bottom = 80
    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom

    # Title
    title_font = _font(42)
    _shadow_text(draw, title, (margin_left, 25), title_font, color=(255, 255, 255))

    # Grid lines
    for i in range(5):
        grid_y = margin_top + chart_h - (i / 4) * chart_h
        draw.line([(margin_left, grid_y), (margin_left + chart_w, grid_y)],
                  fill=(60, 60, 60), width=1)
        val_label = f"{int((i / 4) * max_val)}"
        grid_font = _font(22, bold=False)
        draw.text((margin_left - 45, grid_y - 12), val_label, font=grid_font, fill=(130, 130, 130))

    # Bars
    n = len(items)
    bar_spacing = 8
    bar_w = (chart_w - bar_spacing * (n + 1)) // n

    for i, item in enumerate(items):
        x = margin_left + bar_spacing * (i + 1) + bar_w * i
        val = item.get("value", 0)
        bar_h = int((val / max_val) * chart_h)
        y_top = margin_top + chart_h - bar_h
        y_bot = margin_top + chart_h

        color = _rank_color(i + 1)

        # Bar shadow
        shadow_offset = 4
        draw.rectangle([x + shadow_offset, y_top + shadow_offset,
                        x + bar_w + shadow_offset, y_bot + shadow_offset],
                       fill=(5, 5, 10))

        # Bar gradient
        for y in range(y_top, y_bot):
            ratio = (y - y_top) / max(bar_h, 1)
            r = int(color[0] * (1 - ratio * 0.4))
            g = int(color[1] * (1 - ratio * 0.4))
            b = int(color[2] * (1 - ratio * 0.4))
            draw.line([(x, y), (x + bar_w, y)], fill=(r, g, b))

        # Bright top edge
        draw.rectangle([x, y_top, x + bar_w, y_top + 3], fill=color)

        # Value label on top of bar
        val_text = item.get("label", str(val))
        val_font = _font(24)
        vw = _text_w(draw, val_text, val_font)
        draw.text((x + (bar_w - vw) // 2, y_top - 32), val_text, font=val_font, fill=color)

        # Name label below bar
        name = item.get("name", "")[:12]
        name_font = _font(22, bold=False)
        nw = _text_w(draw, name, name_font)
        draw.text((x + (bar_w - nw) // 2, y_bot + 8), name, font=name_font, fill=(200, 200, 200))

    # X axis line
    draw.line([margin_left, margin_top + chart_h, margin_left + chart_w, margin_top + chart_h],
              fill=(80, 80, 80), width=2)

    if x_label:
        xl_font = _font(28, bold=False)
        xlw = _text_w(draw, x_label, xl_font)
        draw.text(((width - xlw) // 2, height - 36), x_label, font=xl_font, fill=(150, 150, 150))

    img.save(str(output_path), "JPEG", quality=92)
    return output_path


# ── Intro Title Card ──────────────────────────────────────────────────────────

def create_title_card(
    title: str,
    subtitle: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    bg_image_path: Optional[Path] = None,
    accent_color: tuple = (230, 32, 32),
) -> Path:
    """Full-screen intro title card."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), (8, 8, 12))
    draw = ImageDraw.Draw(img)

    # Background
    if bg_image_path and Path(bg_image_path).exists():
        try:
            bg = Image.open(bg_image_path).convert("RGB").resize((width, height), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=6))
            bg = ImageEnhance.Brightness(bg).enhance(0.25)
            img.paste(bg)
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    # Red bottom bar
    bar_h = height // 6
    for y in range(height - bar_h, height):
        ratio = (y - (height - bar_h)) / bar_h
        r = int(accent_color[0] * (0.6 + 0.4 * ratio))
        g = int(accent_color[1] * (0.6 + 0.4 * ratio))
        b = int(accent_color[2] * (0.6 + 0.4 * ratio))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Title
    title_lines = textwrap.wrap(title.upper(), width=24)
    font_size = 100 if len(title_lines) == 1 else 80 if len(title_lines) == 2 else 66
    title_font = _font(font_size)
    total_h = len(title_lines) * (font_size + 12)
    y = (height - total_h) // 2 - 40

    for line in title_lines:
        lw = _text_w(draw, line, title_font)
        _shadow_text(draw, line, ((width - lw) // 2, y), title_font,
                     color=(255, 255, 255), shadow=(0, 0, 0), offset=4)
        y += font_size + 12

    # Subtitle
    if subtitle:
        sub_font = _font(36, bold=False)
        sub_lines = textwrap.wrap(subtitle, width=50)
        sub_y = y + 20
        for line in sub_lines[:2]:
            sw = _text_w(draw, line, sub_font)
            draw.text(((width - sw) // 2, sub_y), line, font=sub_font, fill=(210, 210, 210))
            sub_y += 44

    # Accent line
    draw.rectangle([width // 2 - 80, height - bar_h - 6, width // 2 + 80, height - bar_h - 2],
                   fill=(255, 255, 255))

    img.save(str(output_path), "JPEG", quality=93)
    return output_path


# ── Parse ranked list from research ──────────────────────────────────────────

def extract_ranked_items(topic: str, research_brief) -> list[dict]:
    """
    Parse a ranked list of items from research data.
    Works for topics like "top 10 teams with most World Cup victories",
    "15 highest mountains", "most popular programming languages", etc.
    """
    items = []
    all_text = "\n".join([
        research_brief.summary or "",
        "\n".join(research_brief.data_points),
        "\n".join(research_brief.key_facts),
        research_brief.raw_text or "",
    ])

    # Pattern 1: Numbered list "1. Brazil (5 titles)" or "1. Mount Everest – 8,849 m"
    pattern1 = re.findall(
        r'(?:^|\n)\s*(\d+)[.)]\s+'
        r'([A-Z][^(\n\d]{2,40})'
        r'(?:[(\-–—:]?\s*([^)\n]{2,50}))?',
        all_text, re.MULTILINE
    )

    for rank, name, detail in pattern1:
        rank = int(rank)
        name = name.strip().rstrip(',:;-–—').strip()
        detail = detail.strip() if detail else ""
        if name and 3 <= len(name) <= 60 and rank <= 30:
            # Extract numeric value from detail if present (must start with digit)
            nums = re.findall(r'\d[\d,.]*', detail)
            val = _safe_float(nums[0]) if nums else rank
            items.append({
                "rank": rank,
                "name": name,
                "value": val,
                "detail": detail,
                "label": detail[:30] if detail else str(int(val)),
            })

    # Pattern 2: Lines like "Brazil – 5 titles" or "Everest: 8849m"
    if not items:
        pattern2 = re.findall(
            r'([A-Z][a-zA-Z\s]{2,30})\s*[–\-:]\s*([^\n]{2,60})',
            all_text
        )
        for i, (name, detail) in enumerate(pattern2[:15], 1):
            name = name.strip()
            detail = detail.strip()
            nums = re.findall(r'\d[\d,.]*', detail)
            val = _safe_float(nums[0]) if nums else (15 - i + 1)
            items.append({
                "rank": i,
                "name": name,
                "value": val,
                "detail": detail,
                "label": detail[:30] if detail else str(int(val)),
            })

    # Deduplicate by name (keep highest-ranked)
    seen = {}
    for it in sorted(items, key=lambda x: x["rank"]):
        key = it["name"].lower()[:20]
        if key not in seen:
            seen[key] = it

    result = list(seen.values())
    result.sort(key=lambda x: x["rank"])
    return result


# ── Master: Generate All Graphics for a Job ───────────────────────────────────

def generate_content_graphics(
    topic: str,
    research_brief,
    output_dir: Path,
    width: int = 1280,
    height: int = 720,
    bg_images: list[Path] = None,
) -> dict:
    """
    Generate the full set of graphics for a topic:
    - Intro title card
    - One ranked card per item
    - A bar chart
    Returns dict of {"title_card": path, "rank_cards": [...], "bar_chart": path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bg_images = bg_images or []
    is_portrait = (height > width)

    results = {"title_card": None, "rank_cards": [], "bar_chart": None}

    # ── Title card ───────────────────────────────────────────────────────────
    title_bg = bg_images[0] if bg_images else None
    title_path = output_dir / "title_card.jpg"
    create_title_card(
        title=topic,
        subtitle=research_brief.summary[:120] if research_brief.summary else "",
        output_path=title_path,
        width=width,
        height=height,
        bg_image_path=title_bg,
    )
    results["title_card"] = title_path

    # ── Extract ranked items ─────────────────────────────────────────────────
    ranked = extract_ranked_items(topic, research_brief)

    # ── Ranked cards ─────────────────────────────────────────────────────────
    for i, item in enumerate(ranked):
        bg = bg_images[(i + 1) % len(bg_images)] if bg_images else None
        card_path = output_dir / f"rank_{item['rank']:02d}_{_safe(item['name'])}.jpg"
        create_rank_card(
            rank=item["rank"],
            name=item["name"],
            value=item["label"] or str(item["value"]),
            sub_info=item.get("detail", ""),
            output_path=card_path,
            width=width if not is_portrait else 1080,
            height=height if not is_portrait else 500,
            bg_image_path=bg,
            is_portrait=is_portrait,
        )
        results["rank_cards"].append(card_path)

    # ── Bar chart (only if we have numeric data and it's landscape) ──────────
    if ranked and not is_portrait:
        chart_items = [
            {"name": it["name"][:12], "value": it["value"], "label": it.get("label", str(it["value"]))}
            for it in ranked
        ]
        chart_path = output_dir / "bar_chart.jpg"
        create_bar_chart(
            items=chart_items,
            title=f"Rankings: {topic[:50]}",
            output_path=chart_path,
            width=width,
            height=height,
        )
        results["bar_chart"] = chart_path

    return results


def _safe(name: str) -> str:
    return re.sub(r'[^\w]', '_', name.lower())[:20]
