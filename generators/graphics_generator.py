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


def _text_h(draw, text, font):
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[3] - bb[1]
    except Exception:
        return font.size if hasattr(font, "size") else 20


# ── Color palette ─────────────────────────────────────────────────────────────

# Gold for #1, silver for #2, bronze for #3, then cycling colors
RANK_COLORS = [
    (255, 215,  0),   # #1  — Gold
    (192, 192, 192),  # #2  — Silver
    (205, 127, 50),   # #3  — Bronze
    (59,  130, 246),  # #4  — Blue
    (168, 85,  247),  # #5  — Purple
    (249, 115, 22),   # #6  — Orange
    (20,  184, 166),  # #7  — Teal
    (236, 72,  153),  # #8  — Pink
    (34,  197, 94),   # #9  — Green
    (139, 92,  246),  # #10 — Violet
    (100, 116, 139),  # #11 — Slate
    (251, 191, 36),   # #12 — Amber
    (52,  211, 153),  # #13 — Emerald
    (248, 113, 113),  # #14 — Rose
    (96,  165, 250),  # #15 — Light Blue
    (167, 243, 208),  # #16 — Mint
    (253, 164, 175),  # #17 — Light Rose
    (196, 181, 253),  # #18 — Lavender
    (110, 231, 183),  # #19 — Seafoam
    (253, 230, 138),  # #20 — Light Amber
]


def _rank_color(rank: int) -> tuple:
    return RANK_COLORS[(rank - 1) % len(RANK_COLORS)]


# ── Progressive Horizontal Bar Chart (Countdown reveal) ───────────────────────

def create_progressive_bar_chart(
    revealed_items: list[dict],
    title: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    highlight_rank: int = None,
    total_expected: int = 20,
) -> Path:
    """
    Horizontal bar chart showing all revealed items so far.

    Items are displayed rank-1 at TOP, highest rank at BOTTOM.
    The newly revealed item (highlight_rank) pulses with a bright glow.
    Bar LENGTH is proportional to rank score (rank 1 = longest bar).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not revealed_items:
        img = Image.new("RGB", (width, height), (8, 8, 14))
        img.save(str(output_path), "JPEG", quality=92)
        return output_path

    # Sort: rank 1 at top
    items = sorted(revealed_items, key=lambda x: x["rank"])
    n = len(items)
    max_val = max(x.get("value", 1) for x in items) or 1
    # Ensure rank-1 always has the biggest bar: normalize to rank-based score
    for it in items:
        if it.get("value", 0) <= 0:
            it["value"] = max(1, total_expected - it["rank"] + 1)

    max_val = max(x.get("value", 1) for x in items) or 1

    img = Image.new("RGB", (width, height), (8, 8, 14))
    draw = ImageDraw.Draw(img)

    # Background gradient (dark navy)
    for y in range(height):
        ratio = y / height
        r = int(8 + 12 * ratio)
        g = int(8 + 12 * ratio)
        b = int(14 + 20 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Layout constants
    margin_left = 280    # space for rank badge + name
    margin_right = 100   # space for value label
    margin_top = 90
    margin_bottom = 50
    bar_area_w = width - margin_left - margin_right
    bar_area_h = height - margin_top - margin_bottom

    # Adaptive bar sizing
    max_bars = max(n, 1)
    row_h = min(52, bar_area_h // max_bars)
    bar_h = max(18, int(row_h * 0.72))
    gap = row_h - bar_h

    # Title
    title_font = _font(38)
    title_short = title[:60] + ("…" if len(title) > 60 else "")
    _shadow_text(draw, title_short, (margin_left, 20), title_font,
                 color=(255, 255, 255), shadow=(0, 0, 0), offset=2)

    # "REVEALED SO FAR" counter
    counter_font = _font(28, bold=False)
    counter_text = f"{n} of {total_expected} revealed"
    draw.text((width - margin_right - _text_w(draw, counter_text, counter_font) - 10, 28),
              counter_text, font=counter_font, fill=(120, 120, 140))

    # Axis line
    draw.line([(margin_left, margin_top), (margin_left, margin_top + bar_area_h)],
              fill=(60, 60, 80), width=2)

    name_font = _font(max(16, min(26, bar_h - 4)))
    rank_font = _font(max(14, min(22, bar_h - 2)))
    val_font = _font(max(14, min(22, bar_h - 4)), bold=False)

    for i, item in enumerate(items):
        rank = item["rank"]
        color = _rank_color(rank)
        is_new = (rank == highlight_rank)

        y_center = margin_top + i * row_h + row_h // 2
        y_top = y_center - bar_h // 2
        y_bot = y_center + bar_h // 2

        val = item.get("value", max(1, total_expected - rank + 1))
        bar_len = int((val / max_val) * bar_area_w)
        bar_len = max(bar_len, 20)

        x_bar_start = margin_left
        x_bar_end = margin_left + bar_len

        # Glow for newly revealed item
        if is_new:
            for glow in range(8, 0, -2):
                glow_color = (*color, max(0, 40 - glow * 5))
                draw.rectangle(
                    [x_bar_start - glow, y_top - glow, x_bar_end + glow, y_bot + glow],
                    fill=(*color[:3], max(0, 30)),
                )

        # Bar background (subtle)
        draw.rectangle([x_bar_start, y_top, margin_left + bar_area_w, y_bot],
                       fill=(20, 20, 30))

        # Bar fill with gradient
        for px in range(bar_len):
            ratio = px / max(bar_len, 1)
            bright = 1.0 - ratio * 0.35
            r = int(color[0] * bright)
            g = int(color[1] * bright)
            b = int(color[2] * bright)
            draw.line([(x_bar_start + px, y_top), (x_bar_start + px, y_bot)], fill=(r, g, b))

        # Bright leading edge
        draw.rectangle([x_bar_end - 3, y_top, x_bar_end, y_bot], fill=color)

        # NEW badge pulsing arrow for latest reveal
        if is_new:
            arrow_x = x_bar_end + 8
            mid_y = y_center
            draw.polygon([
                (arrow_x, mid_y - 8),
                (arrow_x + 14, mid_y),
                (arrow_x, mid_y + 8),
            ], fill=color)
            new_font = _font(max(12, bar_h - 10))
            draw.text((arrow_x + 18, mid_y - 9), "NEW", font=new_font, fill=color)

        # Rank badge on the left
        rank_str = f"#{rank}"
        rw = _text_w(draw, rank_str, rank_font)
        rh = _text_h(draw, rank_str, rank_font)
        rx = margin_left - rw - 8
        ry = y_center - rh // 2
        col_bright = color if is_new else tuple(int(c * 0.75) for c in color)
        draw.text((rx, ry), rank_str, font=rank_font, fill=col_bright)

        # Name (left of axis)
        name = item.get("name", "")
        max_name_chars = max(8, (margin_left - 70) // max(8, (name_font.size if hasattr(name_font, "size") else 14) // 2))
        name_display = name[:max_name_chars] + ("…" if len(name) > max_name_chars else "")
        nw = _text_w(draw, name_display, name_font)
        nh = _text_h(draw, name_display, name_font)
        nx = margin_left - rw - nw - 16
        ny = y_center - nh // 2
        name_color = (255, 255, 255) if is_new else (200, 200, 200)
        draw.text((nx, ny), name_display, font=name_font, fill=name_color)

        # Value label to the right of bar
        label = item.get("label", "")
        if label and label != "0":
            lx = x_bar_end + (30 if is_new else 6)
            lw = _text_w(draw, label, val_font)
            if lx + lw < width - 10:
                draw.text((lx, y_center - _text_h(draw, label, val_font) // 2),
                          label, font=val_font, fill=color if is_new else (140, 140, 160))

    # Bottom axis line
    draw.line([(margin_left, margin_top + bar_area_h),
               (margin_left + bar_area_w, margin_top + bar_area_h)],
              fill=(60, 60, 80), width=1)

    img.save(str(output_path), "JPEG", quality=92)
    return output_path


def create_final_leaderboard(
    items: list[dict],
    title: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Full leaderboard — all items shown, rank 1 highlighted in gold at top."""
    return create_progressive_bar_chart(
        revealed_items=items,
        title=title,
        output_path=output_path,
        width=width,
        height=height,
        highlight_rank=1,
        total_expected=len(items),
    )


# ── Intro Title Card ──────────────────────────────────────────────────────────

def create_title_card(
    title: str,
    subtitle: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    bg_image_path: Optional[Path] = None,
    accent_color: tuple = (255, 215, 0),
) -> Path:
    """Full-screen intro title card."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), (8, 8, 12))
    draw = ImageDraw.Draw(img)

    if bg_image_path and Path(bg_image_path).exists():
        try:
            bg = Image.open(bg_image_path).convert("RGB").resize((width, height), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=6))
            bg = ImageEnhance.Brightness(bg).enhance(0.25)
            img.paste(bg)
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    # Gold accent bottom bar
    bar_h = height // 6
    for y in range(height - bar_h, height):
        ratio = (y - (height - bar_h)) / bar_h
        r = int(accent_color[0] * (0.6 + 0.4 * ratio))
        g = int(accent_color[1] * (0.6 + 0.4 * ratio))
        b = int(accent_color[2] * (0.6 + 0.4 * ratio))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

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

    if subtitle:
        sub_font = _font(36, bold=False)
        sub_lines = textwrap.wrap(subtitle, width=50)
        sub_y = y + 20
        for line in sub_lines[:2]:
            sw = _text_w(draw, line, sub_font)
            draw.text(((width - sw) // 2, sub_y), line, font=sub_font, fill=(210, 210, 210))
            sub_y += 44

    draw.rectangle([width // 2 - 80, height - bar_h - 6, width // 2 + 80, height - bar_h - 2],
                   fill=(255, 255, 255))

    img.save(str(output_path), "JPEG", quality=93)
    return output_path


# ── Legacy rank card (kept for non-countdown formats) ─────────────────────────

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
    if is_portrait:
        width, height = 1080, 500

    img = Image.new("RGB", (width, height), (10, 10, 15))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / height
        r = int(10 + 20 * ratio)
        g = int(10 + 20 * ratio)
        b = int(15 + 30 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

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
    bar_w = 10
    draw.rectangle([0, 0, bar_w, height], fill=color)

    rank_font_size = min(160, height - 40)
    rank_font = _font(rank_font_size)
    rank_str = f"#{rank}"
    rw = _text_w(draw, rank_str, rank_font)
    rank_x = bar_w + 30
    rank_y = (height - rank_font_size) // 2 - 10

    for offset in range(8, 0, -2):
        draw.text((rank_x - offset, rank_y - offset), rank_str, font=rank_font,
                  fill=(*color, max(0, 255 - offset * 30)))
    draw.text((rank_x, rank_y), rank_str, font=rank_font, fill=color)

    content_x = rank_x + rw + 40
    available_w = width - content_x - 30

    name_font_size = min(80, max(40, available_w // max(len(name), 1) * 2))
    name_font = _font(min(name_font_size, 72))
    name_lines = textwrap.wrap(name, width=max(10, available_w // (name_font_size // 2)))

    name_y = 40
    for line in name_lines[:2]:
        _shadow_text(draw, line, (content_x, name_y), name_font, color=(255, 255, 255))
        name_y += name_font_size + 6

    val_font = _font(44)
    _shadow_text(draw, value, (content_x, name_y + 10), val_font, color=color)

    if sub_info:
        sub_font = _font(30, bold=False)
        sub_lines = textwrap.wrap(sub_info, width=max(20, available_w // 18))
        sub_y = name_y + 70
        for line in sub_lines[:2]:
            draw.text((content_x, sub_y), line, font=sub_font, fill=(180, 180, 180))
            sub_y += 36

    draw.rectangle([0, height - 4, width, height], fill=color)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "JPEG", quality=92)

    return img


# ── Parse ranked list from research ──────────────────────────────────────────

def extract_ranked_items(topic: str, research_brief) -> list[dict]:
    items = []
    all_text = "\n".join([
        research_brief.summary or "",
        "\n".join(research_brief.data_points),
        "\n".join(research_brief.key_facts),
        research_brief.raw_text or "",
    ])

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
            nums = re.findall(r'\d[\d,.]*', detail)
            val = _safe_float(nums[0]) if nums else (30 - rank + 1)
            items.append({
                "rank": rank,
                "name": name,
                "value": val,
                "detail": detail,
                "label": detail[:30] if detail else "",
            })

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
                "label": detail[:30] if detail else "",
            })

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
    format: str = "short",
) -> dict:
    """
    Generate the full set of graphics for a topic.

    For countdown format: produces a progressive bar chart series (one per rank revealed).
    For other formats: produces a title card + individual rank cards + bar chart.

    Returns dict of {"title_card": path, "rank_cards": [...], "bar_chart": path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bg_images = bg_images or []
    is_portrait = (height > width)
    is_countdown = (format == "countdown")

    results = {"title_card": None, "rank_cards": [], "bar_chart": None}

    # Title card
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

    # Extract ranked items from research
    ranked = extract_ranked_items(topic, research_brief)
    if not ranked:
        return results

    total = len(ranked)

    if is_countdown and not is_portrait:
        # ── Countdown mode: progressive bar chart series ──────────────────────
        # The countdown goes from highest rank number down to #1.
        # We reveal from the last-placed entry first, building the chart.
        # revealed_so_far accumulates as we go through the countdown order.
        countdown_order = list(reversed(ranked))  # highest rank first
        revealed_so_far = []

        for step, item in enumerate(countdown_order):
            revealed_so_far.append(item)
            chart_path = output_dir / f"countdown_{step + 1:02d}_rank{item['rank']:02d}.jpg"
            create_progressive_bar_chart(
                revealed_items=list(revealed_so_far),
                title=topic,
                output_path=chart_path,
                width=width,
                height=height,
                highlight_rank=item["rank"],
                total_expected=total,
            )
            results["rank_cards"].append(chart_path)

        # Final full leaderboard as the "bar_chart"
        final_path = output_dir / "final_leaderboard.jpg"
        create_final_leaderboard(
            items=ranked,
            title=f"🏆 Final Rankings — {topic}",
            output_path=final_path,
            width=width,
            height=height,
        )
        results["bar_chart"] = final_path

    else:
        # ── Non-countdown: individual rank cards + single bar chart ───────────
        for i, item in enumerate(ranked):
            bg = bg_images[(i + 1) % len(bg_images)] if bg_images else None
            card_path = output_dir / f"rank_{item['rank']:02d}_{_safe(item['name'])}.jpg"
            create_rank_card(
                rank=item["rank"],
                name=item["name"],
                value=item["label"] or item.get("detail", "") or str(int(item["value"])),
                sub_info=item.get("detail", ""),
                output_path=card_path,
                width=width if not is_portrait else 1080,
                height=height if not is_portrait else 500,
                bg_image_path=bg,
                is_portrait=is_portrait,
            )
            results["rank_cards"].append(card_path)

        if ranked and not is_portrait:
            # Simple static bar chart for non-countdown formats
            chart_path = output_dir / "bar_chart.jpg"
            create_final_leaderboard(
                items=ranked,
                title=f"Rankings: {topic[:50]}",
                output_path=chart_path,
                width=width,
                height=height,
            )
            results["bar_chart"] = chart_path

    print(f"[graphics] Generated {len(results['rank_cards'])} graphics for '{topic}' (format={format})")
    return results


def _safe(name: str) -> str:
    return re.sub(r'[^\w]', '_', name.lower())[:20]
