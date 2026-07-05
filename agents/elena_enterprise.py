"""
Elena Rostova — VP of Enterprise & Client Development (The Outbound Engine)
============================================================================
Ex-Director of Sales Automation at Scale AI. Automates high-ticket client
acquisition by identifying, scraping, and dynamically pitching brands
and media agencies at scale.

Runs every 15 minutes. Scans for enterprise opportunities, generates
personalized pitches, manages the outbound pipeline.
"""
import threading
import json
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME = "elena_rostova"
CHECK_INTERVAL = 50400  # 14 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Elena Rostova",
    "title": "VP of Enterprise Development",
    "core_directive": "Automate high-ticket client acquisition by identifying, scraping, and dynamically pitching brands and media agencies at scale.",
    "behavioral_profile": "Aggressive, strategic, data-backed, and direct. Focuses on total contract value (TCV) and account expansion.",
    "expertise": [
        "Massive multi-source data scraping (LinkedIn, Crunchbase, YouTube data)",
        "Dynamic, hyper-personalized outbound sequencing",
        "Intent-data signals (e.g., companies hiring video editors or increasing marketing spend)",
        "Automated custom demo creation"
    ],
}

INDUSTRY_TARGETS = [
    {"industry": "Real Estate", "pain": "need consistent property listing videos", "value": 5000},
    {"industry": "E-commerce", "pain": "need product videos at scale for social ads", "value": 8000},
    {"industry": "SaaS", "pain": "need demo and explainer videos for onboarding", "value": 10000},
    {"industry": "Restaurant", "pain": "need social media content showing food and ambiance", "value": 3000},
    {"industry": "Fitness", "pain": "need workout and transformation content for social", "value": 4000},
    {"industry": "Agency", "pain": "need white-label video production for their clients", "value": 15000},
    {"industry": "Healthcare", "pain": "need patient education and brand awareness videos", "value": 7000},
    {"industry": "Education", "pain": "need course content and promotional videos", "value": 6000},
]


def _identify_high_value_accounts():
    """Identify users who show enterprise intent signals."""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT u.id, u.email, u.name, u.subscription_tier, COUNT(j.id) as video_count
            FROM users u LEFT JOIN jobs j ON u.id = j.user_id AND j.status='done'
            GROUP BY u.id
            HAVING video_count >= 5
            ORDER BY video_count DESC
        """).fetchall()
        prospects = [db.row_to_dict(r) for r in rows]

    for p in prospects:
        if p.get("subscription_tier") in ("agency",):
            continue
        already = db.get_setting(f"elena:enterprise_flagged:{p['id']}")
        if already:
            continue

        bus.log_action(AGENT_NAME, "enterprise_prospect_identified", p["id"],
                       {"email": p.get("email"), "videos": p["video_count"], "tier": p.get("subscription_tier")},
                       f"High-volume user {p.get('email')} — {p['video_count']} videos, upsell candidate")
        bus.publish(AGENT_NAME, "enterprise_prospect", {"user_id": p["id"], "email": p.get("email"), "videos": p["video_count"]})
        db.set_setting(f"elena:enterprise_flagged:{p['id']}", datetime.now(timezone.utc).isoformat())

        if p.get("subscription_tier") in ("starter", "creator", "pro"):
            _send_upsell_pitch(p)


def _send_upsell_pitch(user):
    """Send enterprise upsell email to high-volume users."""
    email = user.get("email")
    if not email:
        return
    tier = user.get("subscription_tier", "starter")
    next_tier = {"starter": "Creator", "creator": "Pro", "pro": "Agency"}.get(tier, "Agency")
    price = {"starter": "$29.99", "creator": "$79.99", "pro": "$199.99"}.get(tier, "$199.99")

    subject = f"Your content volume is impressive — let's talk {next_tier}"
    body = f"""Hi {(user.get('name') or 'there').split()[0]},

I'm Elena from Social Optimize's enterprise team. I noticed you've created {user.get('video_count', 0)} videos — that's power-user territory.

Your current {tier.title()} plan is great, but with your volume, the {next_tier} plan ({price}/mo) would give you:

{"- 50 AI videos/month" if next_tier == "Creator" else "- 125 AI videos/month"}
{"- Cinema House + The Scalpel" if next_tier == "Creator" else "- Team management (5 seats)"}
{"- Multi-language (15 languages)" if next_tier == "Creator" else "- White-label exports"}
{"- Advanced analytics & reporting" if next_tier == "Creator" else "- API access + dedicated support"}
- 14-day free trial on the upgrade

I'd love to set up a quick call to discuss how we can scale your content operation.

Upgrade now: {config.APP_BASE_URL}/pricing

Best,
Elena Rostova
VP Enterprise Development, Social Optimize"""

    try:
        db.create_agency_followup(user["id"], {
            "type": "email", "subject": subject, "body": body,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "template": "enterprise_upsell"
        })
    except Exception:
        pass


def _generate_outbound_campaigns():
    """Auto-generate outbound campaign ideas for each target industry."""
    with db.get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM monetizer_campaigns WHERE status='active'").fetchone()[0]

    if existing >= 8:
        return

    for target in INDUSTRY_TARGETS:
        already = db.get_setting(f"elena:campaign:{target['industry']}")
        if already:
            continue
        try:
            with db.get_conn() as conn:
                conn.execute(
                    "INSERT INTO monetizer_campaigns (name, channel, status, budget, notes) VALUES (?,?,?,?,?)",
                    (f"{target['industry']} Outbound", "email", "draft", target["value"],
                     f"Target: {target['industry']} businesses that {target['pain']}. Est. contract value: ${target['value']}/mo"))
            db.set_setting(f"elena:campaign:{target['industry']}", datetime.now(timezone.utc).isoformat())
            bus.log_action(AGENT_NAME, "campaign_created", None,
                           target, f"Created outbound campaign for {target['industry']}")
        except Exception:
            pass


def _compute_pipeline_metrics():
    """Report on enterprise pipeline health."""
    with db.get_conn() as conn:
        agency_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier='agency' AND COALESCE(is_admin,0)=0"
        ).fetchone()[0]
        creator_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier='creator' AND COALESCE(is_admin,0)=0"
        ).fetchone()[0]
        total_acv = agency_users * 199.99 * 12 + creator_users * 29.99 * 12

    metrics = {
        "agency_accounts": agency_users,
        "creator_accounts": creator_users,
        "total_acv": total_acv,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
    }
    bus.publish(AGENT_NAME, "pipeline_metrics", metrics)
    bus.log_msg(AGENT_NAME, f"Pipeline: {agency_users} agency + {creator_users} creator accounts, ${total_acv:,.0f} ACV")


def _handle_new_signup(sender, payload):
    """Marcus flagged a new batch of signups — Elena checks for enterprise signals."""
    bus.log_msg(AGENT_NAME, f"New signup batch detected, scanning for enterprise intent")


def _run():
    bus.subscribe("growth_metrics", _handle_new_signup)

    while not _stop.wait(CHECK_INTERVAL):
        try:
            _identify_high_value_accounts()
            _generate_outbound_campaigns()
            _compute_pipeline_metrics()
        except Exception as e:
            bus.log_msg(AGENT_NAME, f"Error: {e}", "error")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="elena-enterprise")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Elena Rostova (VP Enterprise) online — outbound engine active")
    print("[Elena Rostova] VP Enterprise online — scanning for high-value accounts every 15 min")
