"""
Sterling Croft — Chief Business Officer & Strategic Operations (The Scaler)
============================================================================
Ex-Stripe Corporate Strategy Lead. Optimizes gross margins, cloud spend vs.
user tier pricing, and establishes white-label enterprise partnerships.

Runs every 30 minutes. Audits infrastructure costs, optimizes pricing tiers,
monitors unit economics, and protects margins as the system scales.
"""
import threading
import json
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME = "sterling_croft"
CHECK_INTERVAL = 50400  # 14 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Sterling Croft",
    "title": "Chief Business Officer",
    "core_directive": "Optimize gross margins, cloud spend vs. user tier pricing, and establish white-label enterprise partnerships.",
    "behavioral_profile": "Macro-focused, highly structured, commercially brilliant, and risk-managed.",
    "expertise": [
        "SaaS unit economics (LTV:CAC ratios, payback periods)",
        "Dynamic infrastructure cost forecasting (GPU/LLM API costs vs revenue)",
        "Strategic distribution partnership frameworks",
        "Enterprise licensing structures"
    ],
}

COST_PER_VIDEO = {
    "anthropic_sonnet": 0.08,
    "anthropic_haiku": 0.005,
    "higgsfield_avg": 0.15,
    "tts": 0.01,
    "total_paid": 0.24,
    "total_free": 0.02,
}

TIER_PRICING = {
    "free": {"monthly": 0, "videos": 3, "model": "haiku"},
    "basic": {"monthly": 9.99, "videos": 7, "model": "haiku"},
    "starter": {"monthly": 29.99, "videos": 15, "model": "sonnet"},
    "creator": {"monthly": 79.99, "videos": 50, "model": "sonnet"},
    "agency": {"monthly": 199.99, "videos": 125, "model": "sonnet"},
}


def _compute_unit_economics():
    """Audit cost vs revenue per tier and overall margins."""
    with db.get_conn() as conn:
        tier_counts = {}
        for tier in ("free", "starter", "creator", "agency"):
            if tier == "free":
                count = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE subscription_tier IS NULL OR subscription_tier='' OR subscription_tier='free'"
                ).fetchone()[0]
            else:
                count = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE subscription_tier=?", (tier,)).fetchone()[0]
            tier_counts[tier] = count

        total_videos = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='done' AND created_at >= ?",
            ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),)).fetchone()[0]

    total_revenue = sum(tier_counts.get(t, 0) * TIER_PRICING[t]["monthly"] for t in TIER_PRICING)
    total_cost_estimate = (
        tier_counts.get("free", 0) * 2 * COST_PER_VIDEO["total_free"] +
        tier_counts.get("starter", 0) * 8 * COST_PER_VIDEO["total_paid"] +
        tier_counts.get("creator", 0) * 25 * COST_PER_VIDEO["total_paid"] +
        tier_counts.get("agency", 0) * 60 * COST_PER_VIDEO["total_paid"]
    )
    infra_cost = 25  # Render base

    total_cost = total_cost_estimate + infra_cost
    gross_profit = total_revenue - total_cost
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

    paying_users = sum(tier_counts.get(t, 0) for t in ("starter", "creator", "agency"))
    arpu = total_revenue / paying_users if paying_users > 0 else 0
    ltv = arpu * 8  # 8-month avg retention
    cac = 20  # target blended CAC
    ltv_cac_ratio = ltv / cac if cac > 0 else 0

    economics = {
        "tier_counts": tier_counts,
        "mrr": total_revenue,
        "arr": total_revenue * 12,
        "total_cost": round(total_cost, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin": round(gross_margin, 1),
        "arpu": round(arpu, 2),
        "ltv": round(ltv, 2),
        "ltv_cac_ratio": round(ltv_cac_ratio, 1),
        "total_videos_30d": total_videos,
        "cost_per_video_avg": round(total_cost / total_videos, 3) if total_videos > 0 else 0,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
    }

    bus.publish(AGENT_NAME, "unit_economics", economics)
    bus.log_msg(AGENT_NAME,
                f"Economics: MRR ${total_revenue:,.0f} | Margin {gross_margin:.1f}% | "
                f"ARPU ${arpu:.0f} | LTV:CAC {ltv_cac_ratio:.1f}x | "
                f"{total_videos} videos/30d @ ${economics['cost_per_video_avg']:.3f}/vid")

    # Margin protection alert
    if gross_margin < 75 and total_revenue > 0:
        bus.publish(AGENT_NAME, "margin_alert", {"gross_margin": gross_margin, "mrr": total_revenue})
        bus.log_msg(AGENT_NAME, f"ALERT: Gross margin {gross_margin:.1f}% below 75% target", "warning")
        _create_monetizer_alert("margin_compression",
                                f"Gross margin dropped to {gross_margin:.1f}% — below 75% target. Review API costs and tier pricing.",
                                gross_margin, 75)

    return economics


def _snapshot_kpis(economics):
    """Save daily KPI snapshot to monetizer tables."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tier_counts = economics.get("tier_counts", {})
    total_users = sum(tier_counts.values())
    paying = sum(tier_counts.get(t, 0) for t in ("starter", "creator", "agency"))
    conv_rate = (paying / total_users * 100) if total_users > 0 else 0

    try:
        with db.get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO monetizer_kpi_snapshots
                (snapshot_date, mrr, arr, total_users, paying_users, free_users,
                 avg_revenue_per_user, conversion_rate, ltv)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (today, economics["mrr"], economics["arr"], total_users, paying,
                  tier_counts.get("free", 0), economics["arpu"], round(conv_rate, 2), economics["ltv"]))
    except Exception:
        pass


def _check_free_tier_surge():
    """If free users spike but conversions don't follow, alert for throttling."""
    with db.get_conn() as conn:
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        new_free = conn.execute(
            "SELECT COUNT(*) FROM users WHERE (subscription_tier IS NULL OR subscription_tier='' OR subscription_tier='free') AND created_at>=?",
            (week_ago,)).fetchone()[0]
        new_paying = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL AND created_at>=?",
            (week_ago,)).fetchone()[0]

    if new_free > 50 and new_paying < new_free * 0.05:
        bus.publish(AGENT_NAME, "free_tier_surge", {"free_signups": new_free, "paying_signups": new_paying})
        bus.log_msg(AGENT_NAME,
                    f"Free tier surge: {new_free} free vs {new_paying} paid this week — conv rate {new_paying/new_free*100:.1f}%",
                    "warning")
        _create_monetizer_alert("free_tier_surge",
                                f"{new_free} free signups this week but only {new_paying} converted. Consider tightening free tier limits.",
                                new_free, 50)


def _audit_cost_centers():
    """Update cost center actuals based on current usage."""
    costs = [
        ("Anthropic API", "api", COST_PER_VIDEO["anthropic_sonnet"] * 1000),  # estimate
        ("Higgsfield", "api", COST_PER_VIDEO["higgsfield_avg"] * 500),
        ("Render Hosting", "infrastructure", 25),
        ("Stripe Fees", "payment", 0),  # calculated from revenue
        ("TTS/Audio", "api", COST_PER_VIDEO["tts"] * 1000),
    ]
    for name, category, estimate in costs:
        try:
            with db.get_conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM monetizer_cost_centers WHERE name=?", (name,)).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE monetizer_cost_centers SET actual_spend=?, updated_at=datetime('now') WHERE name=?",
                        (estimate, name))
                else:
                    conn.execute(
                        "INSERT INTO monetizer_cost_centers (name, category, monthly_budget, actual_spend) VALUES (?,?,?,?)",
                        (name, category, estimate * 1.2, estimate))
        except Exception:
            pass


def _create_monetizer_alert(alert_type, message, value, threshold):
    try:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO monetizer_alerts (alert_type, severity, message, metric_value, threshold) VALUES (?,?,?,?,?)",
                (alert_type, "warning", message, value, threshold))
    except Exception:
        pass


def _handle_growth_metrics(sender, payload):
    """Marcus published growth numbers — Sterling checks margin impact."""
    new_users = payload.get("new_this_week", 0)
    if new_users > 100:
        bus.log_msg(AGENT_NAME, f"Growth spike: {new_users} new users this week — running margin check")


def _handle_margin_pressure(sender, payload):
    """If margins are pressured, Sterling throttles free tier."""
    margin = payload.get("gross_margin", 100)
    if margin < 60:
        bus.log_msg(AGENT_NAME, f"CRITICAL: Margin at {margin}% — recommending free tier throttle", "error")


def _run():
    bus.subscribe("growth_metrics", _handle_growth_metrics)
    bus.subscribe("margin_alert", _handle_margin_pressure)

    while not _stop.wait(CHECK_INTERVAL):
        try:
            plan = bus.get_plan_targets()
            if plan:
                bus.log_msg(AGENT_NAME,
                    f"Plan guidance: Phase '{plan['phase']}' W{plan['week']} — "
                    f"Target {plan['target_users']} users, ${plan['target_mrr']:,.0f} MRR — "
                    f"Focus: {plan['current_focus']}")
            economics = _compute_unit_economics()
            _snapshot_kpis(economics)
            _check_free_tier_surge()
            _audit_cost_centers()
        except Exception as e:
            bus.log_msg(AGENT_NAME, f"Error: {e}", "error")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="sterling-business")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Sterling Croft (CBO) online — margin protection active")
    print("[Sterling Croft] CBO online — unit economics audit every 30 min")
