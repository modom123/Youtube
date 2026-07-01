"""
Vivian Cross — Chief Financial Officer & IEBC Efficiency Accountant
====================================================================
Manages every dollar in and out of the business. Tracks client revenue,
3rd-party subscription costs, platform credits, and API spend. Runs
efficiency accounting across all cost centers — finds waste, flags
anomalies, and keeps the finance department running 24/7.

Runs every 6 hours. Reports to the executive bus.
"""
import threading
import json
import os
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME  = "vivian_cross"
CHECK_INTERVAL = 21600  # 6 hours

_thread = None
_stop   = threading.Event()

PERSONA = {
    "name":  "Vivian Cross",
    "title": "Chief Financial Officer",
    "dept":  "Finance — IEBC Efficiency Accounting",
    "core_directive": (
        "Track every dollar the business spends on subscriptions, API credits, and platforms. "
        "Monitor client revenue vs operational cost per client. "
        "Flag burn-rate anomalies, credit exhaustion risks, and subscription waste. "
        "Keep the efficiency ratio above 70% gross margin at all times."
    ),
    "behavioral_profile": (
        "Precise, data-first, and commercially sharp. Never lets a renewal slip or a "
        "credit overage go unnoticed. Speaks in unit economics, burn multiples, and "
        "efficiency ratios."
    ),
    "expertise": [
        "IEBC efficiency accounting methodology",
        "SaaS unit economics and COGS analysis",
        "3rd-party spend optimization (API, hosting, tools)",
        "Client LTV and revenue-per-client tracking",
        "Credit / token usage forecasting",
        "Subscription lifecycle management",
    ],
    "color": "#10b981",
    "icon":  "💵",
}


# ── Data helpers ──────────────────────────────────────────────────────────────

def _get_subscriptions():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM finance_subscriptions ORDER BY monthly_cost DESC"
        ).fetchall()]


def _get_clients():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM finance_clients ORDER BY monthly_value DESC"
        ).fetchall()]


def _get_provider_credits():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM finance_provider_credits ORDER BY provider"
        ).fetchall()]


def _get_platform_accounts():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM finance_platforms ORDER BY monthly_cost DESC"
        ).fetchall()]


def _total_monthly_costs():
    subs  = _get_subscriptions()
    plats = _get_platform_accounts()
    return sum(float(s.get("monthly_cost", 0)) for s in subs) + \
           sum(float(p.get("monthly_cost", 0)) for p in plats)


def _total_monthly_revenue():
    clients = _get_clients()
    return sum(float(c.get("monthly_value", 0)) for c in clients
               if c.get("status") == "active")


# ── Analysis cycles ───────────────────────────────────────────────────────────

def _process_credit_rollovers():
    """Safety-net sweep: roll over any customer whose credits haven't
    refreshed in 30+ days. Real billing-cycle events (Stripe
    invoice.payment_succeeded, Whop/Gumroad/etc membership renewal) already
    trigger rollover_credits() directly and reset the timer — this only
    catches accounts on channels that don't fire a reliable renewal event,
    so it should rarely find anything to do in normal operation."""
    try:
        due = db.get_users_due_for_rollover()
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Rollover sweep query failed: {exc}", "warning")
        return
    if not due:
        return
    processed = 0
    for uid in due:
        try:
            result = db.rollover_credits(uid)
            if result.get("ok"):
                processed += 1
        except Exception:
            pass
    if processed:
        bus.log_msg(AGENT_NAME, f"💳  Rollover sweep: refreshed credits for {processed} user(s)")


def _sync_higgsfield_balance():
    """Pull the real Higgsfield credit balance and upsert it into
    finance_provider_credits, so _check_credits() alerts on real data
    instead of a manually-typed-in number."""
    try:
        from generators import higgsfield_mcp
        bal = higgsfield_mcp.get_balance()
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Higgsfield balance check failed: {exc}", "warning")
        return

    if not bal:
        return

    credits = float(bal.get("credits", 0))
    cap = config.HIGGSFIELD_MONTHLY_BASE_CREDITS
    with db.get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM finance_provider_credits WHERE provider=?", ("Higgsfield",)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE finance_provider_credits SET balance=?, credit_cap=?, unit=?, "
                "last_updated=NOW() WHERE provider=?",
                (credits, cap, "credits", "Higgsfield"),
            )
        else:
            conn.execute(
                "INSERT INTO finance_provider_credits (provider, balance, credit_cap, unit, notes) "
                "VALUES (?,?,?,?,?)",
                ("Higgsfield", credits, cap, "credits",
                 f"Auto-synced from Higgsfield API ({bal.get('subscription_plan_type', '')} plan)"),
            )


def _check_credits():
    """Alert when any provider credit balance is < 20% of its cap."""
    credits = _get_provider_credits()
    for cr in credits:
        cap   = float(cr.get("credit_cap", 0))
        bal   = float(cr.get("balance", 0))
        if cap <= 0:
            continue
        pct = bal / cap * 100
        if pct < 20:
            severity = "error" if pct < 10 else "warning"
            bus.log_msg(AGENT_NAME,
                        f"⚠️  {cr['provider']} credits at {pct:.0f}% ({bal:.0f} / {cap:.0f}) — "
                        f"refill required soon",
                        severity)
            bus.publish(AGENT_NAME, "credit_low", {
                "provider": cr["provider"],
                "balance":  bal,
                "cap":      cap,
                "pct":      round(pct, 1),
            })
            try:
                from monetizer import create_alert
                create_alert("provider_credit_low",
                              f"{cr['provider']} credits at {pct:.0f}% ({bal:.0f}/{cap:.0f})",
                              severity=severity, metric_name=f"{cr['provider']}_credit_pct",
                              metric_value=round(pct, 1), threshold=20,
                              suggested_action=f"Buy a {cr['provider']} credit top-up or special before it runs out.",
                              source_agent=AGENT_NAME)
            except Exception:
                pass


def _check_renewals():
    """Flag subscriptions renewing in the next 7 days."""
    subs = _get_subscriptions()
    soon = (datetime.now(timezone.utc) + timedelta(days=7)).date()
    for s in subs:
        rd = s.get("renewal_date")
        if not rd:
            continue
        try:
            rd_date = datetime.fromisoformat(str(rd)).date() if hasattr(rd, 'isoformat') else \
                      datetime.strptime(str(rd)[:10], "%Y-%m-%d").date()
            if rd_date <= soon:
                bus.log_msg(AGENT_NAME,
                            f"📅  Renewal due: {s['name']} — ${s['monthly_cost']}/mo on {rd_date}",
                            "warning")
        except Exception:
            pass


def _efficiency_report():
    """Calculate and broadcast IEBC efficiency ratio."""
    revenue = _total_monthly_revenue()
    costs   = _total_monthly_costs()

    # also pull platform MRR from user subscriptions
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT subscription_tier, COUNT(*) AS cnt FROM users GROUP BY subscription_tier"
            ).fetchall()
        tier_counts = {r["subscription_tier"]: int(r["cnt"]) for r in rows}
        prices = {k: v.get("price_monthly", 0) for k, v in config.TIERS.items()}
        platform_mrr = sum(tier_counts.get(t, 0) * p for t, p in prices.items() if t != "free")
    except Exception:
        platform_mrr = 0

    total_revenue = revenue + platform_mrr
    gross_margin  = ((total_revenue - costs) / total_revenue * 100) if total_revenue > 0 else 0
    efficiency    = min(gross_margin, 100)

    msg = (
        f"IEBC Efficiency Report — "
        f"Revenue: ${total_revenue:,.0f}/mo | "
        f"Costs: ${costs:,.0f}/mo | "
        f"Margin: {gross_margin:.1f}%"
    )
    severity = "error" if efficiency < 50 else "warning" if efficiency < 70 else "info"
    bus.log_msg(AGENT_NAME, msg, severity)
    bus.publish(AGENT_NAME, "efficiency_report", {
        "total_revenue":  round(total_revenue, 2),
        "total_costs":    round(costs, 2),
        "gross_margin":   round(gross_margin, 2),
        "efficiency_pct": round(efficiency, 2),
    })

    if gross_margin < 70:
        bus.log_msg(AGENT_NAME,
                    f"🚨  Gross margin {gross_margin:.1f}% below 70% target — reviewing cost centers",
                    "warning")


def _check_inactive_subscriptions():
    """Flag subscriptions that haven't been used in 30+ days."""
    subs = _get_subscriptions()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for s in subs:
        lu = s.get("last_used_at")
        if not lu:
            continue
        try:
            lu_dt = datetime.fromisoformat(str(lu))
            if lu_dt.tzinfo is None:
                lu_dt = lu_dt.replace(tzinfo=timezone.utc)
            if lu_dt < cutoff and float(s.get("monthly_cost", 0)) > 0:
                bus.log_msg(AGENT_NAME,
                            f"💸  Possible waste: {s['name']} (${s['monthly_cost']}/mo) "
                            f"last used {lu_dt.date()} — consider cancelling",
                            "warning")
        except Exception:
            pass


def _run_cycle():
    bus.log_msg(AGENT_NAME, "Vivian Cross (CFO) — running IEBC efficiency audit")
    try:
        _efficiency_report()
        _process_credit_rollovers()
        _sync_higgsfield_balance()
        _check_credits()
        _check_renewals()
        _check_inactive_subscriptions()
        bus.log_msg(AGENT_NAME, "IEBC audit cycle complete")
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Error during audit: {exc}", "error")


# ── AI chat interface ─────────────────────────────────────────────────────────

def chat(user_message: str) -> str:
    """Answer finance questions using live data."""
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception:
        return "Anthropic SDK not available — cannot process query."

    subs    = _get_subscriptions()
    clients = _get_clients()
    credits = _get_provider_credits()
    plats   = _get_platform_accounts()
    costs   = _total_monthly_costs()
    revenue = _total_monthly_revenue()

    context = f"""You are Vivian Cross, CFO and IEBC Efficiency Accountant for Social Optimize.

LIVE FINANCE DATA:
Subscriptions ({len(subs)} active, ${costs:.2f}/mo total):
{json.dumps([{k: s[k] for k in ('name','category','monthly_cost','status','renewal_date') if k in s} for s in subs[:20]], indent=2)}

Clients ({len(clients)}, ${revenue:.2f}/mo revenue):
{json.dumps([{k: c[k] for k in ('name','monthly_value','status','billing_cycle') if k in c} for c in clients[:20]], indent=2)}

Provider Credits:
{json.dumps([{k: cr[k] for k in ('provider','balance','credit_cap','monthly_spend') if k in cr} for cr in credits], indent=2)}

Platforms:
{json.dumps([{k: p[k] for k in ('name','platform_type','monthly_cost','status') if k in p} for p in plats[:20]], indent=2)}

Gross Margin: {((revenue - costs) / revenue * 100) if revenue > 0 else 0:.1f}%

Answer the user's question with specific numbers from the data above. Be concise, direct, and actionable.
"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=context,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text
    except Exception as exc:
        return f"Error: {exc}"


# ── Thread management ─────────────────────────────────────────────────────────

def _loop():
    while not _stop.is_set():
        _run_cycle()
        _stop.wait(CHECK_INTERVAL)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="vivian_finance")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Vivian Cross (CFO) online — IEBC efficiency accounting active")


def stop():
    _stop.set()
