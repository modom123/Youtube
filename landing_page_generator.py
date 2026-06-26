"""
Landing Page Generator -- creates high-converting HTML landing pages.
Uses Claude AI to generate copy, then renders into responsive HTML templates.
"""
import json
import os
import re
import uuid
import logging
from pathlib import Path
from datetime import datetime

import anthropic
import config

log = logging.getLogger("landing_pages")

LANDING_PAGES_DIR = config.DATA_DIR / "landing_pages"
LANDING_PAGES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_landing_page(
    title: str,
    description: str,
    target_audience: str = "general",
    video_url: str = "",
    thumbnail_url: str = "",
    cta_text: str = "Get Started",
    cta_url: str = "",
    style: str = "modern_dark",
    features: list | None = None,
    testimonials: list | None = None,
    pricing: dict | None = None,
) -> dict:
    """
    Generate a complete landing page.

    Returns::

        {
            "page_id": str,
            "file_path": str,
            "public_url": str,
            "title": str,
            "generated_at": str,
        }
    """
    page_id = str(uuid.uuid4())[:8]

    # Generate copy with Claude (falls back to raw inputs on failure)
    copy = _generate_copy(title, description, target_audience, cta_text, features)

    # Render into HTML
    html = _render_html(
        copy=copy,
        title=title,
        video_url=video_url,
        thumbnail_url=thumbnail_url,
        cta_text=cta_text,
        cta_url=cta_url or config.APP_BASE_URL,
        style=style,
        features=features,
        testimonials=testimonials,
        pricing=pricing,
    )

    # Save
    file_path = LANDING_PAGES_DIR / f"{page_id}.html"
    file_path.write_text(html, encoding="utf-8")

    return {
        "page_id": page_id,
        "file_path": str(file_path),
        "public_url": f"{config.APP_BASE_URL}/lp/{page_id}",
        "title": title,
        "generated_at": datetime.now().isoformat(),
    }


def list_landing_pages() -> list:
    """List all generated landing pages, newest first."""
    pages = []
    for f in LANDING_PAGES_DIR.glob("*.html"):
        pages.append({
            "page_id": f.stem,
            "file_path": str(f),
            "public_url": f"{config.APP_BASE_URL}/lp/{f.stem}",
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    pages.sort(key=lambda x: x["created_at"], reverse=True)
    return pages


def get_landing_page_path(page_id: str) -> str | None:
    """Get file path for a landing page by ID."""
    path = LANDING_PAGES_DIR / f"{page_id}.html"
    return str(path) if path.exists() else None


def delete_landing_page(page_id: str) -> bool:
    """Delete a landing page. Returns True if the page existed."""
    path = LANDING_PAGES_DIR / f"{page_id}.html"
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Copy generation
# ---------------------------------------------------------------------------

def _fallback_copy(title: str, description: str, cta_text: str,
                   features: list | None = None) -> dict:
    """Return plain copy derived from the raw inputs (no AI)."""
    cards = []
    for feat in (features or [])[:3]:
        cards.append({"icon": "->", "title": feat, "description": ""})
    # Pad to 3 cards if fewer were provided
    while len(cards) < 3:
        cards.append({"icon": "->", "title": title, "description": description[:60]})

    return {
        "hero_headline": title,
        "hero_subheadline": description[:120],
        "problem_headline": "",
        "problem_description": "",
        "solution_headline": title,
        "solution_description": description,
        "feature_cards": cards,
        "social_proof_text": "",
        "final_cta_headline": cta_text,
        "final_cta_description": description[:100],
    }


def _generate_copy(title: str, description: str, target_audience: str,
                   cta_text: str, features: list | None = None) -> dict:
    """Use Claude to generate landing page copy.

    Falls back to ``_fallback_copy`` when the API key is missing or the
    request fails for any reason.
    """
    if not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY is not set -- using fallback copy for "
                     "landing page '%s'", title)
        return _fallback_copy(title, description, cta_text, features)

    features_text = ""
    if features:
        features_text = f"\nKey features to highlight: {', '.join(features)}"

    prompt = (
        "Generate landing page copy for the following:\n\n"
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Target audience: {target_audience}\n"
        f"CTA: {cta_text}{features_text}\n\n"
        "Return a JSON object with these fields:\n"
        '- "hero_headline": punchy headline (max 10 words)\n'
        '- "hero_subheadline": supporting text (max 25 words)\n'
        '- "problem_headline": what problem does this solve (max 8 words)\n'
        '- "problem_description": describe the pain point (2-3 sentences)\n'
        '- "solution_headline": how this solves it (max 8 words)\n'
        '- "solution_description": describe the solution (2-3 sentences)\n'
        '- "feature_cards": list of 3 objects with "icon" (emoji), '
        '"title" (max 5 words), "description" (max 15 words)\n'
        '- "social_proof_text": a credibility statement (max 15 words)\n'
        '- "final_cta_headline": closing headline (max 8 words)\n'
        '- "final_cta_description": closing copy (max 20 words)\n\n'
        "Return ONLY valid JSON, no markdown fences."
    )

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if match:
            raw = match.group(1).strip()

        return json.loads(raw)
    except (anthropic.APIError, anthropic.AuthenticationError) as exc:
        log.warning("Claude API error while generating copy for '%s': %s",
                     title, exc)
    except json.JSONDecodeError as exc:
        log.warning("Failed to parse Claude response as JSON for '%s': %s",
                     title, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("Unexpected error generating copy for '%s': %s",
                     title, exc)

    return _fallback_copy(title, description, cta_text, features)


# ---------------------------------------------------------------------------
# Style definitions
# ---------------------------------------------------------------------------

STYLES: dict[str, dict[str, str]] = {
    "modern_dark": {
        "bg": "#0a0a0a", "card_bg": "#161616", "text": "#f0f0f0",
        "muted": "#a0a0a0", "accent": "#ff3b30", "accent_hover": "#ff5545",
        "border": "#2a2a2a",
    },
    "clean_light": {
        "bg": "#ffffff", "card_bg": "#f8f9fa", "text": "#1a1a1a",
        "muted": "#6b7280", "accent": "#2563eb", "accent_hover": "#3b82f6",
        "border": "#e5e7eb",
    },
    "gradient_purple": {
        "bg": "#0f0720", "card_bg": "#1a1040", "text": "#f0f0f0",
        "muted": "#b0a0d0", "accent": "#8b5cf6", "accent_hover": "#a78bfa",
        "border": "#2d1f5e",
    },
}


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Minimal HTML-escape for user-supplied strings."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def _render_html(
    copy: dict,
    title: str,
    video_url: str,
    thumbnail_url: str,
    cta_text: str,
    cta_url: str,
    style: str,
    features: list | None,
    testimonials: list | None,
    pricing: dict | None,
) -> str:
    """Render the landing page as a self-contained HTML document."""
    s = STYLES.get(style, STYLES["modern_dark"])

    # -- Feature cards -------------------------------------------------------
    feature_cards = copy.get("feature_cards", [])
    features_html = ""
    for card in feature_cards:
        features_html += (
            f'<div style="flex:1;min-width:250px;background:{s["card_bg"]};'
            f'border:1px solid {s["border"]};border-radius:12px;padding:32px;'
            f'text-align:center;">'
            f'<div style="font-size:40px;margin-bottom:16px;">'
            f'{_esc(card.get("icon", "->"))}</div>'
            f'<h3 style="color:{s["text"]};margin:0 0 8px;font-size:20px;">'
            f'{_esc(card.get("title", ""))}</h3>'
            f'<p style="color:{s["muted"]};margin:0;font-size:15px;'
            f'line-height:1.5;">{_esc(card.get("description", ""))}</p>'
            f'</div>'
        )

    # -- Video / thumbnail ---------------------------------------------------
    video_section = ""
    if video_url:
        video_section = (
            f'<div style="max-width:720px;margin:40px auto;border-radius:12px;'
            f'overflow:hidden;border:1px solid {s["border"]};">'
            f'<video controls style="width:100%;display:block;" '
            f'poster="{_esc(thumbnail_url)}">'
            f'<source src="{_esc(video_url)}" type="video/mp4">'
            f'</video></div>'
        )
    elif thumbnail_url:
        video_section = (
            f'<div style="max-width:720px;margin:40px auto;border-radius:12px;'
            f'overflow:hidden;border:1px solid {s["border"]};">'
            f'<img src="{_esc(thumbnail_url)}" alt="{_esc(title)}" '
            f'style="width:100%;display:block;"></div>'
        )

    # -- Testimonials --------------------------------------------------------
    testimonials_html = ""
    if testimonials:
        cards = ""
        for t in testimonials[:3]:
            cards += (
                f'<div style="flex:1;min-width:250px;background:{s["card_bg"]};'
                f'border:1px solid {s["border"]};border-radius:12px;padding:24px;">'
                f'<p style="color:{s["text"]};font-style:italic;margin:0 0 12px;">'
                f'&ldquo;{_esc(t.get("quote", ""))}&rdquo;</p>'
                f'<p style="color:{s["muted"]};margin:0;font-size:14px;">'
                f'-- {_esc(t.get("name", "Customer"))}</p></div>'
            )
        testimonials_html = (
            f'<section style="padding:60px 20px;">'
            f'<div style="max-width:960px;margin:0 auto;display:flex;'
            f'gap:24px;flex-wrap:wrap;">{cards}</div></section>'
        )

    # -- Pricing -------------------------------------------------------------
    pricing_html = ""
    if pricing:
        pricing_html = (
            f'<section style="padding:60px 20px;text-align:center;">'
            f'<h2 style="color:{s["text"]};font-size:32px;margin:0 0 8px;">'
            f'{_esc(pricing.get("headline", "Simple Pricing"))}</h2>'
            f'<p style="color:{s["accent"]};font-size:48px;font-weight:800;'
            f'margin:16px 0;">{_esc(pricing.get("price", ""))}</p>'
            f'<p style="color:{s["muted"]};font-size:16px;margin:0 0 32px;">'
            f'{_esc(pricing.get("description", ""))}</p>'
            f'<a href="{_esc(cta_url)}" style="display:inline-block;'
            f'padding:16px 48px;background:{s["accent"]};color:#fff;'
            f'text-decoration:none;border-radius:8px;font-size:18px;'
            f'font-weight:600;">{_esc(cta_text)}</a></section>'
        )

    # -- OG image tag --------------------------------------------------------
    og_image = ""
    if thumbnail_url:
        og_image = f'<meta property="og:image" content="{_esc(thumbnail_url)}">'

    # -- Assemble full page --------------------------------------------------
    hero_headline = _esc(copy.get("hero_headline", title))
    hero_sub = _esc(copy.get("hero_subheadline", ""))
    problem_h = _esc(copy.get("problem_headline", ""))
    problem_d = _esc(copy.get("problem_description", ""))
    solution_h = _esc(copy.get("solution_headline", ""))
    solution_d = _esc(copy.get("solution_description", ""))
    social_proof = _esc(copy.get("social_proof_text", ""))
    final_h = _esc(copy.get("final_cta_headline", ""))
    final_d = _esc(copy.get("final_cta_description", ""))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(title)}</title>
    <meta name="description" content="{hero_sub}">
    <meta property="og:title" content="{_esc(title)}">
    <meta property="og:description" content="{hero_sub}">
    {og_image}
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                background:{s['bg']}; color:{s['text']}; }}
        a:hover {{ opacity:0.9; }}
        @media(max-width:768px) {{
            .features-grid {{ flex-direction:column !important; }}
        }}
    </style>
</head>
<body>
    <!-- Hero -->
    <section style="padding:80px 20px 60px;text-align:center;">
        <div style="max-width:720px;margin:0 auto;">
            <h1 style="font-size:clamp(32px,5vw,56px);font-weight:800;line-height:1.1;margin:0 0 16px;">
                {hero_headline}
            </h1>
            <p style="font-size:20px;color:{s['muted']};margin:0 0 32px;line-height:1.5;">
                {hero_sub}
            </p>
            <a href="{_esc(cta_url)}" style="display:inline-block;padding:16px 48px;background:{s['accent']};
               color:#fff;text-decoration:none;border-radius:8px;font-size:18px;font-weight:600;
               transition:background 0.2s;">
                {_esc(cta_text)}
            </a>
        </div>
    </section>

    {video_section}

    <!-- Problem -->
    <section style="padding:60px 20px;text-align:center;">
        <div style="max-width:640px;margin:0 auto;">
            <h2 style="font-size:28px;margin:0 0 16px;">{problem_h}</h2>
            <p style="color:{s['muted']};font-size:17px;line-height:1.6;">{problem_d}</p>
        </div>
    </section>

    <!-- Solution -->
    <section style="padding:60px 20px;text-align:center;">
        <div style="max-width:640px;margin:0 auto;">
            <h2 style="font-size:28px;margin:0 0 16px;">{solution_h}</h2>
            <p style="color:{s['muted']};font-size:17px;line-height:1.6;">{solution_d}</p>
        </div>
    </section>

    <!-- Features -->
    <section style="padding:60px 20px;">
        <div class="features-grid" style="max-width:960px;margin:0 auto;display:flex;gap:24px;flex-wrap:wrap;">
            {features_html}
        </div>
    </section>

    <!-- Social Proof -->
    <section style="padding:40px 20px;text-align:center;">
        <p style="color:{s['muted']};font-size:16px;font-style:italic;">
            {social_proof}
        </p>
    </section>

    {testimonials_html}
    {pricing_html}

    <!-- Final CTA -->
    <section style="padding:80px 20px;text-align:center;">
        <div style="max-width:640px;margin:0 auto;">
            <h2 style="font-size:32px;margin:0 0 12px;">{final_h}</h2>
            <p style="color:{s['muted']};font-size:17px;margin:0 0 32px;">{final_d}</p>
            <a href="{_esc(cta_url)}" style="display:inline-block;padding:16px 48px;background:{s['accent']};
               color:#fff;text-decoration:none;border-radius:8px;font-size:18px;font-weight:600;">
                {_esc(cta_text)}
            </a>
        </div>
    </section>

    <!-- Footer -->
    <footer style="padding:24px 20px;text-align:center;border-top:1px solid {s['border']};">
        <p style="color:{s['muted']};font-size:13px;">
            Powered by <a href="{_esc(config.APP_BASE_URL)}" style="color:{s['accent']};text-decoration:none;">
            Social Optimize Machine</a>
        </p>
    </footer>
</body>
</html>"""

    return html
