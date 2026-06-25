"""
Auto-research any topic before script generation.
Uses Wikipedia, DuckDuckGo Instant Answer, and web scraping — all free, no API keys.
"""
import re
import time
import json
import requests
from dataclasses import dataclass, field


HEADERS = {
    "User-Agent": "SocialOptimizeMachine/1.0 (content research bot; educational use)"
}

# Keywords that indicate a ranked-list / countdown topic
_RANKED_LIST_SIGNALS = {
    "top", "best", "greatest", "ranked", "ranking", "countdown", "all time",
    "alltime", "all-time", "worst", "most", "least", "highest", "lowest",
    "richest", "famous", "popular", "powerful", "strongest", "fastest",
}


def _is_ranked_list_topic(topic: str) -> bool:
    t = topic.lower()
    return any(sig in t for sig in _RANKED_LIST_SIGNALS)


def _extract_count_from_topic(topic: str) -> int | None:
    """Return the N in 'top N' / 'top-N' if present, else None."""
    m = re.search(r'\btop[\s-]?(\d+)\b', topic, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _ranked_list_wikipedia_queries(topic: str) -> list[str]:
    """
    Generate targeted Wikipedia search queries for a ranked-list topic.
    E.g. "top 25 soccer players goals" → searches for 'List of top scorers' etc.
    """
    t = topic.lower()
    queries = [topic]

    if any(w in t for w in ("soccer", "football", "futbol")):
        if any(w in t for w in ("goal", "scorer", "score")):
            queries += [
                "List of top UEFA Champions League scorers",
                "FIFA World Cup top scorers",
                "International football goals records",
                "List of association football records",
            ]
        else:
            queries += [
                "List of best association football players",
                "Ballon d'Or winners all time",
            ]
    elif any(w in t for w in ("basketball", "nba")):
        if any(w in t for w in ("point", "score")):
            queries.append("List of NBA all-time scoring leaders")
    elif any(w in t for w in ("tennis")):
        queries.append("List of tennis records")
    elif any(w in t for w in ("boxing")):
        queries.append("List of boxing records and statistics")

    # Generic "List of top X" search
    subject_words = re.sub(r'\btop\s*\d+\b|\bbed\b|\ball.time\b|\bcountdown\b|\branked?\b|\bbest\b|\bgreatest\b', '', t).strip()
    if subject_words:
        queries.append(f"List of {subject_words}")

    return queries


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


# ── Gemini Flash Research ────────────────────────────────────────────────────

def _research_with_gemini(topic: str) -> dict:
    """
    Use Gemini Flash to gather enhanced research data alongside Wikipedia.
    Returns dict with facts/trends/statistics/sources, or empty dict if unavailable.
    """
    try:
        import config as _config
        if not getattr(_config, "GOOGLE_API_KEY", ""):
            return {}
        from google import genai
        client = genai.Client(api_key=_config.GOOGLE_API_KEY)
        prompt = (
            f"Research the topic: {topic}. "
            "Provide 10 key facts, current trends, and notable statistics. "
            "Format as JSON with keys: facts (list of strings), trends (list of strings), "
            "statistics (list of strings), sources (list of strings). "
            "Return ONLY valid JSON, no markdown or code fences."
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[research] Gemini research failed ({e})")
        return {}


def _merge_gemini_into_brief(brief: "ResearchBrief", gemini_data: dict) -> None:
    """Merge Gemini research results into brief, deduplicating by 60-char prefix."""
    if not gemini_data:
        return
    existing_lower = {f.lower()[:60] for f in brief.key_facts + brief.data_points}
    for fact in gemini_data.get("facts", []):
        if fact and fact.lower()[:60] not in existing_lower:
            brief.key_facts.append(fact)
            existing_lower.add(fact.lower()[:60])
    for stat in gemini_data.get("statistics", []):
        if stat and stat.lower()[:60] not in existing_lower:
            brief.data_points.append(stat)
            existing_lower.add(stat.lower()[:60])
    for trend in gemini_data.get("trends", []):
        if trend:
            brief.related_topics.append(trend)
    for src in gemini_data.get("sources", []):
        if src and f"Gemini: {src}" not in brief.sources:
            brief.sources.append(f"Gemini: {src}")


# ── Main Research Function ────────────────────────────────────────────────────

def research_topic(topic: str) -> ResearchBrief:
    """Research a topic — always returns a brief, never raises."""
    brief = ResearchBrief(topic=topic, summary="", key_facts=[], data_points=[])

    # For ranked-list topics, search multiple targeted articles in parallel
    wikipedia_queries = (
        _ranked_list_wikipedia_queries(topic)
        if _is_ranked_list_topic(topic)
        else [topic]
    )

    try:
        articles_text = []
        seen_titles: set[str] = set()

        for query in wikipedia_queries[:4]:
            results = _search_wikipedia(query)
            for result in results[:2]:
                title = result.get("title", "")
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                text = _get_wikipedia_sections(title)
                if text and len(text) > 200:
                    articles_text.append((title, text))
                    brief.sources.append(f"Wikipedia: {title}")
                if len(articles_text) >= 5:
                    break
            if len(articles_text) >= 5:
                break

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

    # Gemini Flash enhancement — runs alongside Wikipedia/DDG, merges results
    try:
        gemini_data = _research_with_gemini(topic)
        _merge_gemini_into_brief(brief, gemini_data)
    except Exception as e:
        print(f"[research] Gemini merge failed ({e})")

    # For ranked-list topics with sparse data: use Claude to generate the ranked list directly
    if _is_ranked_list_topic(topic) and len(brief.key_facts) + len(brief.data_points) < 8:
        try:
            _claude_ranked_list_research(brief, topic)
        except Exception as e:
            print(f"[research] Claude ranked-list research failed ({e})")

    if not brief.summary and not brief.key_facts:
        brief.summary = f"Research on: {topic}"

    return brief


def _claude_ranked_list_research(brief: "ResearchBrief", topic: str) -> None:
    """
    Use Claude to populate a ranked-list brief when Wikipedia/DDG data is sparse.
    Asks Claude to produce the actual ranked entries with stats.
    """
    try:
        import config as _config
        import anthropic as _anthropic
        if not getattr(_config, "ANTHROPIC_API_KEY", ""):
            return
        n = _extract_count_from_topic(topic) or 10
        client = _anthropic.Anthropic(api_key=_config.ANTHROPIC_API_KEY)
        prompt = (
            f"I need accurate research data for this video topic: {topic}\n\n"
            f"Generate the top {n} ranked entries with real, accurate statistics. "
            "For each entry include: rank number, name, and the key statistic/reason for the ranking. "
            "Format as a numbered list, e.g.:\n"
            "1. Cristiano Ronaldo — 919 career goals (club + international)\n"
            "2. ...\n\n"
            "Use only real, verifiable facts from your training data. "
            f"Return ONLY the numbered list of {n} entries, nothing else."
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        entries = re.findall(r'\d+\.\s+(.+)', raw)
        existing = {e.lower()[:60] for e in brief.data_points}
        for entry in entries:
            entry = entry.strip()
            if entry and entry.lower()[:60] not in existing:
                brief.data_points.append(entry)
                existing.add(entry.lower()[:60])
        if not brief.summary and raw:
            brief.summary = f"Ranked list research for: {topic}"
        brief.sources.append("Claude AI knowledge base")
        print(f"[research] Claude ranked-list: {len(entries)} entries found")
    except Exception as e:
        print(f"[research] Claude ranked-list failed: {e}")


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
