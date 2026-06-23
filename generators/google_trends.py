"""Google Trends integration using pytrends library."""


def get_trending_topics(niche: str, region: str = "US") -> dict:
    """
    Get Google Trends data for a niche/topic.
    Returns dict with interest_score, trending_up, top_queries, peak_day.
    Returns empty dict on any error or if pytrends unavailable.
    """
    try:
        from pytrends.request import TrendReq
        import pandas as pd

        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload([niche], timeframe="now 7-d", geo=region)

        interest = pytrends.interest_over_time()
        interest_score = 0
        peak_day = ""
        if not interest.empty and niche in interest.columns:
            interest_score = int(interest[niche].mean())
            peak_idx = interest[niche].idxmax()
            peak_day = str(peak_idx.date()) if hasattr(peak_idx, "date") else str(peak_idx)

        related_queries = pytrends.related_queries()
        trending_up = []
        top_queries = []

        niche_queries = related_queries.get(niche, {})
        if niche_queries:
            rising = niche_queries.get("rising")
            if rising is not None and not rising.empty and "query" in rising.columns:
                trending_up = rising["query"].head(10).tolist()
            top = niche_queries.get("top")
            if top is not None and not top.empty and "query" in top.columns:
                top_queries = top["query"].head(10).tolist()

        return {
            "interest_score": interest_score,
            "trending_up": trending_up,
            "top_queries": top_queries,
            "peak_day": peak_day,
        }
    except ImportError:
        print("[trends] pytrends not installed — skipping")
        return {}
    except Exception as e:
        print(f"[trends] get_trending_topics failed ({e})")
        return {}


def get_daily_trends(region: str = "US") -> list:
    """
    Get today's top trending searches for a region.
    Returns list of up to 20 trending topic strings.
    Returns empty list on any error or if pytrends unavailable.
    """
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=360)
        country = region.lower()
        trending = pytrends.trending_searches(pn=country)
        return trending[0].tolist()[:20]
    except ImportError:
        print("[trends] pytrends not installed — skipping")
        return []
    except Exception as e:
        print(f"[trends] get_daily_trends failed ({e})")
        return []
