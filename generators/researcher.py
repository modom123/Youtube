"""
Auto-research any topic before script generation.
Uses Wikipedia, DuckDuckGo Instant Answer, and web scraping — all free, no API keys.
"""
import re
import json
import urllib.parse
import requests
from dataclasses import dataclass, field


HEADERS = {
    "User-Agent": "SocialOptimizeMachine/1.0 (content research bot; educational use)"
}


@dataclass
class ResearchBrief:
    topic: str
    summary: str
    key_facts: list[str] = field(default_factory=list)
    data_points: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)
    raw_text: str = ""


# ── Wikipedia ────────────────────────────────────────────────────────────────

def _search_wikipedia(query: str) -> list[dict]:
    """Search Wikipedia and return top article titles."""
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
            "format": "json",
        },
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("query", {}).get("search", [])


def _get_wikipedia_extract(title: str, sentences: int = 20) -> str:
    """Fetch the intro extract of a Wikipedia article."""
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "prop": "extracts",
            "exsentences": sentences,
            "exintro": True,
            "explaintext": True,
            "titles": title,
            "format": "json",
        },
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""


def _get_wikipedia_sections(title: str) -> str:
    """Fetch full article text (first 4000 chars)."""
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": True,
            "titles": title,
            "format": "json",
        },
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")[:5000]
    return ""


# ── DuckDuckGo Instant Answer ────────────────────────────────────────────────

def _duckduckgo_instant(query: str) -> dict:
    """Use DuckDuckGo's Instant Answer API for quick facts."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers=HEADERS,
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


# ── Fact Extraction ──────────────────────────────────────────────────────────

def _extract_numbered_facts(text: str) -> list[str]:
    """Extract list items, numbered facts, and bullet-style sentences."""
    facts = []

    # Numbered items: "1. Mount Everest ..." or "1) ..."
    numbered = re.findall(r'(?:^|\n)\s*\d+[.)]\s+(.+)', text)
    facts.extend(f.strip() for f in numbered if len(f.strip()) > 15)

    # Lines starting with dash or bullet
    bulleted = re.findall(r'(?:^|\n)\s*[-•*]\s+(.+)', text)
    facts.extend(b.strip() for b in bulleted if len(b.strip()) > 15)

    return facts[:30]


def _extract_key_sentences(text: str, topic: str, max_sentences: int = 15) -> list[str]:
    """Pick the most informative sentences from a block of text."""
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text)
    keywords = set(re.findall(r'\b\w{4,}\b', topic.lower()))
    keywords.update(["first", "highest", "largest", "most", "record", "known",
                     "million", "billion", "thousand", "year", "world", "located"])

    scored = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30 or len(s) > 400:
            continue
        words = set(re.findall(r'\b\w{4,}\b', s.lower()))
        score = len(words & keywords)
        # Bonus for sentences with numbers (data-rich)
        if re.search(r'\d', s):
            score += 3
        scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    seen = set()
    results = []
    for _, s in scored:
        norm = s[:60].lower()
        if norm not in seen:
            seen.add(norm)
            results.append(s)
        if len(results) >= max_sentences:
            break
    return results


# ── Main Research Function ────────────────────────────────────────────────────

def research_topic(topic: str) -> ResearchBrief:
    """
    Research a topic and return a structured ResearchBrief.

    Strategy:
    1. Search Wikipedia for best matching article(s)
    2. Pull full extract text
    3. Try DuckDuckGo Instant Answer for supplementary data
    4. Extract key facts and data points
    """
    brief = ResearchBrief(topic=topic, summary="", key_facts=[], data_points=[])

    # ── Step 1: Wikipedia search ──────────────────────────────────────────────
    results = _search_wikipedia(topic)
    articles_text = []

    for result in results[:3]:
        title = result.get("title", "")
        text = _get_wikipedia_sections(title)
        if text and len(text) > 200:
            articles_text.append((title, text))
            brief.sources.append(f"Wikipedia: {title}")

    # Best single article for summary
    if articles_text:
        best_title, best_text = articles_text[0]
        intro = _get_wikipedia_extract(best_title, sentences=10)
        brief.summary = intro if intro else best_text[:800]
        brief.raw_text = "\n\n".join(t for _, t in articles_text)

    # ── Step 2: DuckDuckGo ───────────────────────────────────────────────────
    ddg = _duckduckgo_instant(topic)
    if ddg.get("AbstractText"):
        if not brief.summary:
            brief.summary = ddg["AbstractText"]
        if ddg.get("AbstractSource"):
            brief.sources.append(ddg["AbstractSource"])

    # Related topics from DDG
    for rt in ddg.get("RelatedTopics", [])[:5]:
        if isinstance(rt, dict) and rt.get("Text"):
            brief.related_topics.append(rt["Text"][:100])

    # ── Step 3: Extract facts ─────────────────────────────────────────────────
    full_corpus = brief.raw_text or brief.summary
    brief.key_facts = _extract_key_sentences(full_corpus, topic, max_sentences=20)
    brief.data_points = _extract_numbered_facts(full_corpus)

    # ── Step 4: Fallback if nothing found ────────────────────────────────────
    if not brief.summary and not brief.key_facts:
        brief.summary = f"Research on: {topic}"

    return brief


def brief_to_context(brief: ResearchBrief) -> str:
    """Format a ResearchBrief into a readable context block for Claude."""
    lines = [f"RESEARCH CONTEXT — Topic: {brief.topic}\n"]

    if brief.summary:
        lines.append(f"OVERVIEW:\n{brief.summary[:1500]}\n")

    if brief.data_points:
        lines.append("SPECIFIC DATA POINTS & LISTS:")
        for dp in brief.data_points[:20]:
            lines.append(f"  • {dp}")
        lines.append("")

    if brief.key_facts:
        lines.append("KEY FACTS:")
        for f in brief.key_facts[:15]:
            lines.append(f"  • {f}")
        lines.append("")

    if brief.related_topics:
        lines.append("RELATED CONTEXT:")
        for rt in brief.related_topics[:5]:
            lines.append(f"  • {rt}")
        lines.append("")

    if brief.sources:
        lines.append(f"SOURCES: {', '.join(brief.sources[:5])}")

    return "\n".join(lines)
