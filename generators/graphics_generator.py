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
        return float(str(s).replace(",", ""))
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

RANK_COLORS = [
    (255, 215,   0),  # #1  — Gold
    (192, 192, 192),  # #2  — Silver
    (205, 127,  50),  # #3  — Bronze
    ( 59, 130, 246),  # #4  — Blue
    (168,  85, 247),  # #5  — Purple
    (249, 115,  22),  # #6  — Orange
    ( 20, 184, 166),  # #7  — Teal
    (236,  72, 153),  # #8  — Pink
    ( 34, 197,  94),  # #9  — Green
    (139,  92, 246),  # #10 — Violet
    (100, 116, 139),  # #11 — Slate
    (251, 191,  36),  # #12 — Amber
    ( 52, 211, 153),  # #13 — Emerald
    (248, 113, 113),  # #14 — Rose
    ( 96, 165, 250),  # #15 — Light Blue
    (167, 243, 208),  # #16 — Mint
    (253, 164, 175),  # #17 — Light Rose
    (196, 181, 253),  # #18 — Lavender
    (110, 231, 183),  # #19 — Seafoam
    (253, 230, 138),  # #20 — Light Amber
]


def _rank_color(rank: int) -> tuple:
    return RANK_COLORS[(rank - 1) % len(RANK_COLORS)]


# ── Extract ranked items from script (PRIMARY source) ────────────────────────

def _extract_from_script(
    sections: list,
    narration: str,
    total_expected: int = 20,
) -> list[dict]:
    """
    Parse actual ranked entity names from script sections + narration.

    Script sections for a countdown look like:
      {"name": "#20 - MIT", ...}
      {"name": "Number 20: Harvard", ...}
      {"name": "20. Oxford University", ...}
      {"name": "Rank 20 - Name", ...}

    Narration contains sentences like:
      "Coming in at number 20, we have Harvard University..."
      "At number 19 is Stanford..."
    """
    items: dict[int, dict] = {}

    # ── Phase 1: Section name patterns ───────────────────────────────────────
    section_patterns = [
        # "#20 - Name", "#20: Name", "#20 – Name"
        r'^#(\d+)\s*[\-–—:\.]+\s*(.+)$',
        # "#1 Reveal - MIT", "#1 Big Reveal: Cambridge" (word(s) before separator)
        r'^#(\d+)\s+\w[\w\s]{0,25}[\-–—:]+\s*(.+)$',
        # "20. Name", "20) Name", "20 - Name", "20: Name"
        r'^(\d+)\s*[\.\)\-–—:]+\s*(.+)$',
        # "Number 20: Name", "Number 20 - Name"
        r'^(?:number|num\.?)\s+#?(\d+)\s*[\-–—:\.]*\s*(.+)$',
        # "Rank 20 - Name", "Rank 20: Name"
        r'^(?:rank|position|entry|place|no\.?)\s*#?(\d+)\s*[\-–—:\.]*\s*(.+)$',
    ]

    for sec in (sections or []):
        raw_name = sec.get("name", "").strip()
        if not raw_name:
            continue
        for pat in section_patterns:
            m = re.match(pat, raw_name, re.IGNORECASE)
            if m:
                try:
                    rank = int(m.group(1))
                    name = m.group(2).strip().strip('.,;:-—').strip()
                    # Skip obvious non-names when they stand alone
                    skip_alone = {"hook", "intro", "introduction", "outro", "conclusion",
                                  "recap", "cta", "opening", "ending", "title"}
                    # If name starts with a stage word, try to split to get real entity name
                    # e.g. "#1 Reveal - MIT" → "Reveal - MIT" → split → "MIT"
                    stage_prefixes = ("reveal", "big reveal", "final", "ultimate", "champion",
                                      "winner", "top", "best", "grand", "special", "the reveal",
                                      "and the winner", "#1 reveal", "number one reveal")
                    name_lower = name.lower()
                    for stage in stage_prefixes:
                        if name_lower.startswith(stage):
                            for sep in (" - ", " – ", " — ", ": ", " | "):
                                if sep in name:
                                    name = name.split(sep, 1)[-1].strip()
                                    break
                            break
                    if 1 <= rank <= 50 and len(name) >= 2 and name.lower() not in skip_alone:
                        if rank not in items:
                            items[rank] = {
                                "rank": rank,
                                "name": name,
                                "visual_cue": sec.get("visual_cue", ""),
                            }
                except (ValueError, IndexError):
                    pass
                break

    # ── Phase 2: Narration text patterns ─────────────────────────────────────
    # Only run if we didn't get enough from sections.
    # No re.IGNORECASE — [A-Z] must match uppercase only to capture proper nouns.
    if len(items) < max(3, total_expected // 3) and narration:
        narr_patterns = [
            # "coming in at number 20, we have Harvard University with..."
            # "at number 20 is Stanford..."
            (
                r'(?:coming in at |sitting at |landing at |at )?'
                r'(?:[Nn]umber|#|[Nn]o\.?)\s*(\d+)[,.:!\s]+'
                r'(?:(?:we have |is |are |it\'s |that\'s |stands? |comes? in )?)'
                r'([A-Z][A-Za-z0-9\s\.\'\&\-\(\)]{2,60}?)'
                r'(?=[\.,!?]|\s+(?:with|has|had|is|are|was|took|scored|earned|'
                r'comes?|takes?|ranks?|came|finish|boast|feat|known|based|'
                r'located|which|who|they|the\s+uni|this\s+uni|this\s+school|'
                r'a\s+uni|an\s+uni|one\s+of|record|hold|claim|achiev))'
            ),
            # "Number 1: MIT" / "#1 – Harvard"
            (
                r'(?:[Nn]umber|#)\s*(\d+)\s*[:\-]\s*'
                r'([A-Z][A-Za-z0-9\s\.\'\&\-]{2,50}?)'
                r'(?=[\.,!?]|\s+(?:with|has|is|are|was|which|who|they))'
            ),
        ]
        for pat in narr_patterns:
            for m in re.finditer(pat, narration):
                try:
                    rank = int(m.group(1))
                    name = m.group(2).strip().rstrip('.,;:- ')
                    # Strip leading articles captured by the pattern
                    for prefix in ("The ", "A ", "An "):
                        if name.startswith(prefix):
                            name = name[len(prefix):]
                            break
                    skip_alone = {"pick", "one", "two", "top", "list", "spot", "place",
                                  "winner", "champion", "choice", "entry", "pick"}
                    if (1 <= rank <= 50 and rank not in items
                            and len(name) >= 3 and name.lower() not in skip_alone):
                        items[rank] = {"rank": rank, "name": name, "visual_cue": ""}
                except (ValueError, IndexError):
                    pass

    if not items:
        return []

    total = max(items.keys()) if items else total_expected
    result = []
    for rank, it in sorted(items.items()):
        # Bar value: #1 = 100%, #n ≥ 48% (minimum so bars are wide enough for name)
        bar_val = 48.0 + 52.0 * (total - rank) / max(total - 1, 1)
        result.append({
            "rank": rank,
            "name": it["name"],
            "value": bar_val,
            "label": "",
            "detail": it.get("visual_cue", ""),
        })

    return sorted(result, key=lambda x: x["rank"])


# ── Fallback: parse ranked items from research text ───────────────────────────

def _extract_from_research(topic: str, research_brief) -> list[dict]:
    """
    Fallback extraction from research text.
    Only used when script data is unavailable or has too few entries.
    Significantly more noise-prone than _extract_from_script().
    """
    all_text = "\n".join([
        research_brief.summary or "",
        "\n".join(research_brief.data_points),
        "\n".join(research_brief.key_facts),
        research_brief.raw_text or "",
    ])

    items = []
    # Only match lines that start with a number followed by a dot/paren
    pattern1 = re.findall(
        r'(?:^|\n)\s*(\d+)[.)]\s+'
        r'([A-Z][^(\n\d]{2,50})'
        r'(?:[(\-–—:]?\s*([^)\n]{2,50}))?',
        all_text, re.MULTILINE
    )

    for rank, name, detail in pattern1:
        rank = int(rank)
        name = name.strip().rstrip(',:;-–—').strip()
        detail = (detail or "").strip()
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

    seen: dict[str, dict] = {}
    for it in sorted(items, key=lambda x: x["rank"]):
        key = it["name"].lower()[:20]
        if key not in seen:
            seen[key] = it

    result = list(seen.values())
    result.sort(key=lambda x: x["rank"])
    return result


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

    Names are displayed INSIDE the bars so they are never truncated.
    Rank #1 is at the TOP; newly revealed item has a glow + NEW badge.
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

    # Ensure all bars have a value
    for it in items:
        if not it.get("value") or it["value"] <= 0:
            total = max(x["rank"] for x in items)
            it["value"] = 48.0 + 52.0 * (total - it["rank"]) / max(total - 1, 1)

    max_val = max(x["value"] for x in items) or 1.0

    # ── Canvas ────────────────────────────────────────────────────────────────
    img = Image.new("RGB", (width, height), (6, 6, 12))
    draw = ImageDraw.Draw(img)

    # Dark navy-to-charcoal gradient background
    for y in range(height):
        ratio = y / height
        r = int(6 + 14 * ratio)
        g = int(6 + 10 * ratio)
        b = int(12 + 18 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Subtle horizontal grid lines
    for gx in range(0, width, 80):
        draw.line([(gx, 0), (gx, height)], fill=(255, 255, 255, 8))

    # ── Layout ───────────────────────────────────────────────────────────────
    rank_zone = 68       # left zone: rank badge only
    right_pad = 14       # right edge padding
    header_h = 78        # top header zone
    footer_h = 36        # bottom status zone

    bar_x0 = rank_zone
    bar_x1 = width - right_pad
    bar_area_w = bar_x1 - bar_x0

    chart_top = header_h
    chart_bot = height - footer_h
    chart_h = chart_bot - chart_top

    # Adaptive row height
    row_h = max(24, min(56, chart_h // max(n, 1)))
    bar_h = max(18, int(row_h * 0.76))
    bar_pad = (row_h - bar_h) // 2

    # ── Header ────────────────────────────────────────────────────────────────
    # Title
    title_font = _font(min(40, max(26, 1500 // max(len(title), 1))))
    title_short = title[:70] + ("…" if len(title) > 70 else "")
    _shadow_text(draw, title_short, (rank_zone, 14), title_font,
                 color=(255, 255, 255), shadow=(0, 0, 0), offset=2)

    # Revealed counter (top-right)
    counter_font = _font(22, bold=False)
    counter_text = f"{n} of {total_expected} revealed"
    ctw = _text_w(draw, counter_text, counter_font)
    draw.text((width - ctw - 16, 22), counter_text, font=counter_font, fill=(100, 100, 130))

    # Thin separator line below header
    draw.line([(0, header_h - 4), (width, header_h - 4)], fill=(40, 40, 60), width=1)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    rank_font_size = max(13, min(28, bar_h - 4))
    name_font_size = max(11, min(22, bar_h - 6))
    rank_font = _font(rank_font_size, bold=True)
    name_font = _font(name_font_size, bold=True)
    label_font = _font(max(10, name_font_size - 3), bold=False)

    # ── Bars ──────────────────────────────────────────────────────────────────
    for i, item in enumerate(items):
        rank = item["rank"]
        color = _rank_color(rank)
        is_new = (rank == highlight_rank)

        y_top = chart_top + i * row_h + bar_pad
        y_bot = y_top + bar_h
        y_mid = (y_top + y_bot) // 2

        bar_len = int((item["value"] / max_val) * bar_area_w)
        bar_len = max(bar_len, 60)   # minimum visible bar
        x_bar_end = bar_x0 + bar_len

        # ── Glow for newly revealed ───────────────────────────────────────
        if is_new:
            for glow_r in range(10, 0, -2):
                rc, gc, bc = color
                draw.rectangle(
                    [bar_x0 - glow_r, y_top - glow_r, x_bar_end + glow_r, y_bot + glow_r],
                    fill=(max(0, rc - 40), max(0, gc - 40), max(0, bc - 40)),
                )

        # Bar track (dark background)
        draw.rectangle([bar_x0, y_top, bar_x1, y_bot], fill=(18, 18, 28))

        # Gradient bar fill (bright left → darker right)
        for px in range(bar_len):
            ratio = px / max(bar_len - 1, 1)
            bright = 1.0 - ratio * 0.40
            r2 = int(color[0] * bright)
            g2 = int(color[1] * bright)
            b2 = int(color[2] * bright)
            draw.line([(bar_x0 + px, y_top), (bar_x0 + px, y_bot)], fill=(r2, g2, b2))

        # Bright leading edge cap
        draw.rectangle([x_bar_end - 3, y_top, x_bar_end, y_bot], fill=color)

        # ── Rank badge (left zone) ────────────────────────────────────────
        rank_str = f"#{rank}"
        rstw = _text_w(draw, rank_str, rank_font)
        rsth = _text_h(draw, rank_str, rank_font)
        rx = (rank_zone - rstw) // 2
        ry = y_mid - rsth // 2
        badge_color = color if is_new else tuple(int(c * 0.85) for c in color)
        _shadow_text(draw, rank_str, (rx, ry), rank_font,
                     color=badge_color, shadow=(0, 0, 0), offset=2)

        # ── Name inside bar ───────────────────────────────────────────────
        name = item.get("name", "")
        # Fit as many chars as possible inside the bar
        name_x = bar_x0 + 8
        available_name_w = x_bar_end - name_x - 8
        # Measure and trim if needed (prefer full name, trim only if truly too wide)
        full_w = _text_w(draw, name, name_font)
        if full_w <= available_name_w:
            name_display = name
        else:
            # Trim character by character until it fits
            trimmed = name
            while len(trimmed) > 4 and _text_w(draw, trimmed + "…", name_font) > available_name_w:
                trimmed = trimmed[:-1]
            name_display = trimmed + "…" if trimmed != name else name

        # Shadow for contrast on colored bar
        name_y = y_mid - _text_h(draw, name_display, name_font) // 2
        _shadow_text(draw, name_display, (name_x, name_y), name_font,
                     color=(255, 255, 255), shadow=(0, 0, 0), offset=2)

        # If name was trimmed and there's room to the right of the bar, show rest there
        if name_display.endswith("…") and x_bar_end + 6 < bar_x1 - 20:
            overflow_font = _font(max(10, name_font_size - 4), bold=False)
            draw.text((x_bar_end + 6, y_mid - _text_h(draw, name, overflow_font) // 2),
                      name[len(name_display) - 1:],
                      font=overflow_font, fill=(180, 180, 180))

        # ── NEW badge ─────────────────────────────────────────────────────
        if is_new:
            badge_x = x_bar_end + 8
            badge_w, badge_h2 = 44, bar_h - 4
            badge_y = y_mid - badge_h2 // 2
            # Arrow triangle
            draw.polygon([
                (badge_x, y_mid - 7),
                (badge_x + 10, y_mid),
                (badge_x, y_mid + 7),
            ], fill=color)
            # "NEW" text
            new_font = _font(max(9, bar_h - 10), bold=True)
            draw.text((badge_x + 13, y_mid - _text_h(draw, "NEW", new_font) // 2),
                      "NEW", font=new_font, fill=color)

    # ── Footer status bar ────────────────────────────────────────────────────
    draw.line([(0, chart_bot + 4), (width, chart_bot + 4)], fill=(40, 40, 60), width=1)
    if highlight_rank:
        status_font = _font(18, bold=False)
        status = f"⬆  #{highlight_rank} just revealed!"
        draw.text((rank_zone, chart_bot + 8), status, font=status_font, fill=(160, 160, 180))

    img.save(str(output_path), "JPEG", quality=93)
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
            bg = ImageEnhance.Brightness(bg).enhance(0.22)
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


# ── Public alias (backward compat) ───────────────────────────────────────────

def extract_ranked_items(topic: str, research_brief) -> list[dict]:
    """Kept for backward compat — wraps _extract_from_research."""
    return _extract_from_research(topic, research_brief)


# ── Master: Generate All Graphics for a Job ───────────────────────────────────

def generate_content_graphics(
    topic: str,
    research_brief,
    output_dir: Path,
    width: int = 1280,
    height: int = 720,
    bg_images: list = None,
    format: str = "short",
    script_sections: list = None,
    script_narration: str = "",
) -> dict:
    """
    Generate the full set of graphics for a topic.

    script_sections / script_narration: when provided (countdown mode), these are used
    as the PRIMARY source for ranked item names so the graphics show real names from
    the actual script instead of noise from raw research text.

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
        subtitle=research_brief.summary[:120] if (research_brief and research_brief.summary) else "",
        output_path=title_path,
        width=width,
        height=height,
        bg_image_path=title_bg,
    )
    results["title_card"] = title_path

    # ── Choose ranked item source ─────────────────────────────────────────────
    # Priority: script data (accurate) → research text (noisy fallback)
    ranked = []
    if script_sections or script_narration:
        ranked = _extract_from_script(
            sections=script_sections or [],
            narration=script_narration or "",
            total_expected=20,
        )
        if ranked:
            print(f"[graphics] Extracted {len(ranked)} ranked items from script")
        else:
            print("[graphics] Script extraction found 0 items — falling back to research text")

    if not ranked and research_brief:
        ranked = _extract_from_research(topic, research_brief)
        if ranked:
            print(f"[graphics] Extracted {len(ranked)} ranked items from research text (fallback)")

    if not ranked:
        print("[graphics] No ranked items found — returning title card only")
        return results

    total = len(ranked)

    if is_countdown and not is_portrait:
        # ── Countdown mode: progressive bar chart series ──────────────────────
        # Reveal from highest rank number (e.g. #20) down to #1
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

        # Final full leaderboard
        final_path = output_dir / "final_leaderboard.jpg"
        create_final_leaderboard(
            items=ranked,
            title=f"Final Rankings — {topic}",
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
                value=item.get("label") or item.get("detail", "") or str(int(item["value"])),
                sub_info=item.get("detail", ""),
                output_path=card_path,
                width=width if not is_portrait else 1080,
                height=height if not is_portrait else 500,
                bg_image_path=bg,
                is_portrait=is_portrait,
            )
            results["rank_cards"].append(card_path)

        if ranked and not is_portrait:
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
