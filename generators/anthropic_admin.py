"""
Anthropic Admin API client — real organization spend tracking.

Uses ANTHROPIC_ADMIN_KEY, which is a SEPARATE key from ANTHROPIC_API_KEY
(the one every Claude call in this app actually uses). The regular API key
has no endpoint to check its own spend or remaining budget — only an Admin
API key (Anthropic Console > Settings > Admin API Keys, requires an org
admin role) can query the cost report.

The exact response shape below is best-effort — it hasn't been verified
against a live call in this environment (no network access to Anthropic's
docs or API from here), so get_month_to_date_cost_usd() parses defensively
across a few plausible field layouts rather than assuming one, and raises
rather than silently returning a wrong number if nothing parses.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

import config

_API_BASE = "https://api.anthropic.com/v1/organizations"


def _headers() -> dict:
    if not config.ANTHROPIC_ADMIN_KEY:
        raise RuntimeError("ANTHROPIC_ADMIN_KEY is not configured")
    return {
        "x-api-key": config.ANTHROPIC_ADMIN_KEY,
        "anthropic-version": "2023-06-01",
    }


def get_month_to_date_cost_usd() -> float:
    """Real dollar spend on the Anthropic API so far this calendar month."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    resp = requests.get(
        f"{_API_BASE}/cost_report",
        headers=_headers(),
        params={
            "starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ending_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    total = 0.0
    found_any = False
    for bucket in data.get("data", []):
        for result in bucket.get("results", []):
            amount = result.get("amount")
            if isinstance(amount, dict) and "amount" in amount:
                total += float(amount.get("amount") or 0)
                found_any = True
            elif isinstance(amount, (int, float, str)):
                try:
                    total += float(amount)
                    found_any = True
                except (TypeError, ValueError):
                    pass
            elif "cost" in result:
                try:
                    total += float(result["cost"])
                    found_any = True
                except (TypeError, ValueError):
                    pass

    if not found_any and data.get("data"):
        raise RuntimeError(
            f"Cost report returned data but no recognizable cost field — response shape may "
            f"have changed. Raw sample: {str(data)[:300]}"
        )
    return total
