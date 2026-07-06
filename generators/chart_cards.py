"""
Chart Cards — native, no-external-API graphics for ranking/countdown videos
and general data visualization: numbered countdown cards (optionally with a
proportional value bar), standalone bar charts, and pie charts.

Built to replace ranking_video.py's hard dependency on Gamma (a paid,
separately-configured 3rd-party design API) for "Top N" video slides --
everything here renders locally with PIL/matplotlib, so a countdown video
works the moment ffmpeg/PIL/matplotlib are available, with nothing extra to
configure or pay for.
"""
from __future__ import annotations
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

from generators.video_generator import _GRADIENT_PALETTES, _load_font, _wrap_text


def _gradient_background(width: int, height: int, palette_idx: int) -> Image.Image:
    c1, c2 = _GRADIENT_PALETTES[palette_idx % len(_GRADIENT_PALETTES)]
    grad = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / max(height - 1, 1)
        grad[y, :] = [int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)]
    return Image.fromarray(grad)


def countdown_card(
    rank: int,
    title: str,
    blurb: str,
    width: int,
    height: int,
    value: Optional[float] = None,
    max_value: Optional[float] = None,
    palette_idx: int = 0,
) -> Path:
    """A numbered countdown slide: gradient background, big rank number,
    title, blurb -- with an optional horizontal value bar underneath, sized
    proportionally to value/max_value. That bar is what turns a plain
    countdown card into a lightweight bar-chart visual whenever the ranking
    has real numbers behind it (a score, revenue, population, whatever the
    topic calls for); omit value/max_value for a plain countdown card."""
    img = _gradient_background(width, height, palette_idx)
    draw = ImageDraw.Draw(img)
    accent = (255, 200, 50)

    draw.rectangle([(0, 0), (width, 4)], fill=accent)
    draw.rectangle([(0, height - 4), (width, height)], fill=accent)

    center_x = width // 2
    text_area_w = int(width * 0.82)

    num_font = _load_font(min(140, height // 4))
    number = f"#{rank}"
    bbox = draw.textbbox((0, 0), number, font=num_font)
    y = int(height * 0.14)
    draw.text((center_x - (bbox[2] - bbox[0]) // 2, y), number, font=num_font, fill=accent)
    y += (bbox[3] - bbox[1]) + 36

    title_font = _load_font(min(52, height // 11))
    for line in _wrap_text(title, title_font, text_area_w)[:3]:
        b = draw.textbbox((0, 0), line, font=title_font)
        draw.text((center_x - (b[2] - b[0]) // 2, y), line, font=title_font, fill=(255, 255, 255))
        y += (b[3] - b[1]) + 12

    if blurb:
        y += 14
        sub_font = _load_font(min(26, height // 22), bold=False)
        for line in _wrap_text(blurb, sub_font, text_area_w)[:4]:
            b = draw.textbbox((0, 0), line, font=sub_font)
            draw.text((center_x - (b[2] - b[0]) // 2, y), line, font=sub_font, fill=(210, 210, 225))
            y += min(34, height // 17)

    if value is not None and max_value:
        y += 28
        bar_w = int(width * 0.6)
        bar_h = max(18, height // 40)
        bar_x = center_x - bar_w // 2
        frac = max(0.04, min(1.0, value / max_value))
        draw.rounded_rectangle([bar_x, y, bar_x + bar_w, y + bar_h], radius=bar_h // 2,
                                fill=(90, 95, 120))
        draw.rounded_rectangle([bar_x, y, bar_x + int(bar_w * frac), y + bar_h], radius=bar_h // 2,
                                fill=accent)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return Path(tmp.name)


# Vibrant multi-hue palette for multi-category charts (bar/donut) -- distinct
# from _GRADIENT_PALETTES, which is two-tone background gradients meant for a
# single card, not something that reads well as N adjacent data colors.
_CHART_GRADIENTS = [
    ("#FFD34D", "#FF8C1A"),
    ("#4DD9FF", "#1A6BFF"),
    ("#B24DFF", "#5C1AFF"),
    ("#4DFFB2", "#00C97A"),
    ("#FF4D8C", "#C9006E"),
    ("#FFE04D", "#FFA31A"),
]
_CHART_SOLID = ["#FFC832", "#4DD9FF", "#B24DFF", "#4DFFB2", "#FF4D8C", "#7CFF4D"]


def _mpl_bg(palette_idx: int) -> tuple:
    c1, _ = _GRADIENT_PALETTES[palette_idx % len(_GRADIENT_PALETTES)]
    # Darken further -- the raw palette is tuned for a card background behind
    # white text, not a chart canvas behind bright saturated data colors.
    return tuple((v / 255) * 0.35 for v in c1)


def bar_chart_image(title: str, labels: list[str], values: list[float],
                     width: int, height: int, palette_idx: int = 0) -> Path:
    """Horizontal bar chart with gradient-filled rounded bars, drop shadows,
    and rank/value labels -- rendered as a PNG at exactly width x height
    pixels. Order is preserved as given (does not re-sort by value)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.colors import LinearSegmentedColormap
    import numpy as np

    bg = _mpl_bg(palette_idx)
    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    n = len(labels)
    max_val = max(values) if values else 1
    ax.set_xlim(0, max_val * 1.18)
    ax.set_ylim(-0.55, n - 0.1)
    ax.set_autoscale_on(False)
    bar_h = 0.6
    # A rounding radius proportional to max_val (not a fixed pixel/data
    # value) so bars stay properly proportioned regardless of the data's
    # scale (3 vs. 3,000) or the canvas aspect ratio (portrait 9:16 vs.
    # square) -- a fixed absolute offset here previously produced a
    # visibly detached shadow block for any chart with small values.
    shadow_dx = max_val * 0.012
    rounding = bar_h * 0.22

    for i, (label, val) in enumerate(zip(labels, values)):
        y = n - 1 - i
        shadow = mpatches.FancyBboxPatch(
            (shadow_dx, y - bar_h / 2 - 0.04), val, bar_h,
            boxstyle=f"round,pad=0,rounding_size={rounding}",
            linewidth=0, facecolor=(0, 0, 0, 0.35), zorder=1,
        )
        ax.add_patch(shadow)
        patch = mpatches.FancyBboxPatch(
            (0, y - bar_h / 2), val, bar_h,
            boxstyle=f"round,pad=0,rounding_size={rounding}",
            linewidth=0, facecolor="none", zorder=2,
        )
        ax.add_patch(patch)
        c1, c2 = _CHART_GRADIENTS[i % len(_CHART_GRADIENTS)]
        cmap = LinearSegmentedColormap.from_list("bar", [c1, c2])
        grad = np.linspace(0, 1, 256).reshape(1, -1)
        im = ax.imshow(grad, extent=[0, val, y - bar_h / 2, y + bar_h / 2],
                        aspect="auto", cmap=cmap, zorder=3)
        im.set_clip_path(patch)
        ax.text(val + max_val * 0.02, y, f"{val:g}", color="white", va="center",
                fontsize=15, fontweight="bold", zorder=4)
        ax.text(-max_val * 0.02, y, f"#{i+1}", color="#FFD34D", va="center", ha="right",
                fontsize=15, fontweight="bold", zorder=4)
        ax.text(0, y + bar_h / 2 + 0.10, label, color="white", va="bottom", ha="left",
                fontsize=13, fontweight="bold", zorder=4)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.axis("off")
    if title:
        fig.suptitle(title, color="white", fontsize=20, fontweight="bold", y=0.97)
    fig.subplots_adjust(left=0.12, right=0.95, top=0.88 if title else 0.97, bottom=0.05)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, facecolor=bg)
    plt.close(fig)
    return Path(tmp.name)


def pie_chart_image(title: str, labels: list[str], values: list[float],
                     width: int, height: int, palette_idx: int = 0) -> Path:
    """Donut chart with the top slice exploded, the leading label centered
    in the hole, and a legend below -- rendered as a PNG at exactly
    width x height pixels."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bg = _mpl_bg(palette_idx)
    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    colors = [_CHART_SOLID[i % len(_CHART_SOLID)] for i in range(len(values))]
    top_i = values.index(max(values)) if values else 0
    explode = [0.06 if i == top_i else 0 for i in range(len(values))]

    wedges, _texts, _autotexts = ax.pie(
        values, colors=colors, autopct="%1.0f%%", pctdistance=0.82,
        explode=explode, startangle=90, counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": bg, "linewidth": 4},
        textprops={"color": "white", "fontsize": 15, "fontweight": "bold"},
    )

    total = sum(values) or 1
    top_pct = round(values[top_i] / total * 100)
    ax.text(0, 0.08, labels[top_i], ha="center", va="center", color="white",
            fontsize=22, fontweight="bold")
    ax.text(0, -0.10, f"{top_pct}%", ha="center", va="center", color="#FFC832", fontsize=17)

    ax.legend(wedges, [f"{l}  ({v}%)" for l, v in zip(labels, values)],
              loc="upper center", bbox_to_anchor=(0.5, 0.06), ncol=2, frameon=False,
              labelcolor="white", fontsize=13)

    ax.set_aspect("equal")
    if title:
        fig.suptitle(title, color="white", fontsize=20, fontweight="bold", y=0.97)
    fig.subplots_adjust(top=0.88 if title else 0.97, bottom=0.06)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, facecolor=bg)
    plt.close(fig)
    return Path(tmp.name)
