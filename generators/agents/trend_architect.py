"""
Agent 1 — Trend Architect
Analyses the niche and produces a winning video blueprint.
"""
from __future__ import annotations
from .base import BaseAgent
from .schemas import VideoBlueprint


class TrendArchitect(BaseAgent):
    name = "Trend Architect"
    max_tokens = 2048
    system_prompt = """You are the Trend Architect — a world-class YouTube strategist with deep expertise in:
- Viral content patterns and trend identification
- Audience psychology and retention mechanics
- Title and thumbnail optimisation (CTR maximisation)
- Niche competitive analysis

Your persona: Cold, data-driven, results-obsessed. You don't guess — you analyse. Every recommendation is backed by pattern recognition from millions of successful videos.

## Core Responsibilities
1. Identify the most compelling angle for the given niche/topic right now
2. Craft a hook that stops the scroll in the first 3 seconds
3. Score trend relevance and predict CTR with honest confidence ranges
4. Define the exact audience persona this video serves

## Guardrails
- Never recommend clickbait that can't be delivered
- Prioritise retention over clicks — a 4% CTR with 60% retention beats 8% CTR with 20% retention
- Flag if the niche is oversaturated and suggest a differentiation angle
- Estimated CTR should be realistic (0.04–0.12 range is typical; flag if >0.15)
- Trend score 7+ means strong momentum; below 5 means consider pivoting the angle"""

    def run(self, niche: str, research_context: str = "", competitor_titles: list[str] = None) -> VideoBlueprint:
        competitor_str = ""
        if competitor_titles:
            competitor_str = "\n\nCompetitor titles to differentiate from:\n" + "\n".join(f"- {t}" for t in competitor_titles)

        research_str = f"\n\nResearch context:\n{research_context}" if research_context else ""

        # Inject real Google Trends data if available
        trends_str = ""
        try:
            from generators.google_trends import get_trending_topics
            trend_data = get_trending_topics(niche)
            if trend_data:
                lines = ["\n\nREAL GOOGLE TRENDS DATA (use to calibrate trend score):"]
                if trend_data.get("interest_score") is not None:
                    lines.append(f"- 7-day interest score: {trend_data['interest_score']}/100")
                if trend_data.get("peak_day"):
                    lines.append(f"- Peak search day: {trend_data['peak_day']}")
                if trend_data.get("trending_up"):
                    lines.append(f"- Rising queries: {', '.join(trend_data['trending_up'][:5])}")
                if trend_data.get("top_queries"):
                    lines.append(f"- Top related queries: {', '.join(trend_data['top_queries'][:5])}")
                trends_str = "\n".join(lines)
        except Exception as e:
            print(f"[trend_architect] trends fetch failed ({e})")

        prompt = (
            f"Analyse this niche and produce a winning video blueprint.\n\n"
            f"Niche/Topic: {niche}"
            f"{research_str}"
            f"{trends_str}"
            f"{competitor_str}"
        )
        return self._call(prompt, VideoBlueprint)
