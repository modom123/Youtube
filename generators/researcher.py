"""
Auto-research any topic before script generation.
Uses Wikipedia, DuckDuckGo Instant Answer, and web scraping — all free, no API keys.
"""
import re
import time
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


def _safe_get(url: str, params: dict, timeout: int = 10) -> dict | None:
    """GET with retry on 429 and silent failure on any error."""
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"[research] 429 rate-limit — retrying in {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[research] request failed ({e}) — skipping")
            return None
    return None


# ── Wikipedia ────────────────────────────────────────────────────────────────

def _search_wikipedia(query: str) -> list[dict]:
    data = _safe_get(
        "https://en.wikipedia.org/w/api.php",
        {"action": "query", "list": "search", "srsearch": query,
         "srlimit": 5, "format": "json"},
    )
    return (data or {}).get("query", {}).get("search", [])


def _get_wikipedia_extract(title: str, sentences: int = 20) -> str:
    data = _safe_get(
        "https://en.wikipedia.org/w/api.php",
        {"action": "query", "prop": "extracts", "exsentences": sentences,
         "exintro": True, "explaintext": True, "titles": title, "format": "json"},
    )
    if not data:
        return ""
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        return page.get("extract", "")
    return ""


def _get_wikipedia_sections(title: str) -> str:
    data = _safe_get(
        "https://en.wikipedia.org/w/api.php",
        {"action": "query", "prop": "extracts", "explaintext": True,
         "titles": title, "format": "json"},
        timeout=15,
    )
    if not data:
        return ""
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        return page.get("extract", "")[:5000]
    return ""


# ── DuckDuckGo Instant Answer ────────────────────────────────────────────────

def _duckduckgo_instant(query: str) -> dict:
    return _safe_get(
        "https://api.duckduckgo.com/",
        {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        timeout=8,
    ) or {}


# ── Fact Extraction ──────────────────────────────────────────────────────────

def _extract_numbered_facts(text: str) -> list[str]:
    facts = []
    numbered = re.findall(r'(?:^|\n)\s*\d+[.)]\s+(.+)', text)
    facts.extend(f.strip() for f in numbered if len(f.strip()) > 15)
    bulleted = re.findall(r'(?:^|\n)\s*[-•*]\s+(.+)', text)
    facts.extend(b.strip() for b in bulleted if len(b.strip()) > 15)
    return facts[:30]


def _extract_key_sentences(text: str, topic: str, max_sentences: int = 15) -> list[str]:
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
    """Research a topic — always returns a brief, never raises."""
    brief = ResearchBrief(topic=topic, summary="", key_facts=[], data_points=[])

    try:
        results = _search_wikipedia(topic)
        articles_text = []

        for result in results[:3]:
            title = result.get("title", "")
            text = _get_wikipedia_sections(title)
            if text and len(text) > 200:
                articles_text.append((title, text))
                brief.sources.append(f"Wikipedia: {title}")

        if articles_text:
            best_title, best_text = articles_text[0]
            intro = _get_wikipedia_extract(best_title, sentences=10)
            brief.summary = intro if intro else best_text[:800]
            brief.raw_text = "\n\n".join(t for _, t in articles_text)
    except Exception as e:
        print(f"[research] Wikipedia failed ({e})")

    try:
        ddg = _duckduckgo_instant(topic)
        if ddg.get("AbstractText"):
            if not brief.summary:
                brief.summary = ddg["AbstractText"]
            if ddg.get("AbstractSource"):
                brief.sources.append(ddg["AbstractSource"])
        for rt in ddg.get("RelatedTopics", [])[:5]:
            if isinstance(rt, dict) and rt.get("Text"):
                brief.related_topics.append(rt["Text"][:100])
    except Exception as e:
        print(f"[research] DuckDuckGo failed ({e})")

    full_corpus = brief.raw_text or brief.summary
    brief.key_facts = _extract_key_sentences(full_corpus, topic, max_sentences=20)
    brief.data_points = _extract_numbered_facts(full_corpus)

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
