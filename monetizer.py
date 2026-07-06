"""
MONETIZER — Business Operating System for Social Optimize Machine
=================================================================
Central command for revenue, users, costs, growth, content ops,
and platform health.  Runs as a Flask Blueprint mounted at /monetizer.

IEBC Consultant C-Suite:
  - Marcus Vance (CGO) — Growth & PLG
  - Elena Rostova (VP Enterprise) — Outbound & B2B
  - Dr. Julian Vance (Retention) — Churn & LTV
  - Sterling Croft (CBO) — Unit Economics & Margins
"""

from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

import database as db
import config

monetizer_bp = Blueprint("monetizer", __name__, url_prefix="/monetizer")


# ── Access control ───────────────────────────────────────────────────────────

def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Helpers ──────────────────────────────────────────────────────────────────

def _conn():
    return db.get_conn()


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows):
    return [dict(r) for r in rows]


def _today():
    return datetime.utcnow().strftime("%Y-%m-%d")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _month_start(offset_months=0):
    d = datetime.utcnow().replace(day=1)
    for _ in range(abs(offset_months)):
        if offset_months < 0:
            d = (d - timedelta(days=1)).replace(day=1)
        else:
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d.strftime("%Y-%m-%d")


# ── Database bootstrap ───────────────────────────────────────────────────────

def init_monetizer_tables():
    with _conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_revenue_log (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER,
            event_type  TEXT NOT NULL,
            amount      REAL NOT NULL DEFAULT 0,
            currency    TEXT DEFAULT 'usd',
            tier        TEXT,
            stripe_event_id TEXT,
            notes       TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_expenses (
            id          SERIAL PRIMARY KEY,
            category    TEXT NOT NULL,
            vendor      TEXT,
            description TEXT,
            amount      REAL NOT NULL,
            currency    TEXT DEFAULT 'usd',
            recurring   INTEGER DEFAULT 0,
            period      TEXT DEFAULT 'monthly',
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_kpi_snapshots (
            id          SERIAL PRIMARY KEY,
            snapshot_date TEXT NOT NULL,
            mrr         REAL DEFAULT 0,
            arr         REAL DEFAULT 0,
            total_users INTEGER DEFAULT 0,
            paying_users INTEGER DEFAULT 0,
            free_users  INTEGER DEFAULT 0,
            churned_users INTEGER DEFAULT 0,
            new_signups INTEGER DEFAULT 0,
            total_videos INTEGER DEFAULT 0,
            total_credits_used INTEGER DEFAULT 0,
            avg_revenue_per_user REAL DEFAULT 0,
            conversion_rate REAL DEFAULT 0,
            churn_rate  REAL DEFAULT 0,
            ltv         REAL DEFAULT 0,
            cac         REAL DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE(snapshot_date)
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_goals (
            id          SERIAL PRIMARY KEY,
            metric      TEXT NOT NULL,
            target_value REAL NOT NULL,
            current_value REAL DEFAULT 0,
            deadline    TEXT,
            status      TEXT DEFAULT 'active',
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_cost_centers (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            category    TEXT NOT NULL,
            monthly_budget REAL DEFAULT 0,
            actual_spend REAL DEFAULT 0,
            notes       TEXT,
            updated_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_campaigns (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            channel     TEXT NOT NULL,
            status      TEXT DEFAULT 'draft',
            budget      REAL DEFAULT 0,
            spent       REAL DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            clicks      INTEGER DEFAULT 0,
            signups     INTEGER DEFAULT 0,
            conversions INTEGER DEFAULT 0,
            start_date  TEXT,
            end_date    TEXT,
            notes       TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_feature_flags (
            id          SERIAL PRIMARY KEY,
            name        TEXT UNIQUE NOT NULL,
            enabled     INTEGER DEFAULT 0,
            tier_min    TEXT DEFAULT 'free',
            rollout_pct INTEGER DEFAULT 100,
            description TEXT,
            updated_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_support_tickets (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER,
            subject     TEXT NOT NULL,
            body        TEXT,
            priority    TEXT DEFAULT 'normal',
            status      TEXT DEFAULT 'open',
            assigned_to TEXT,
            resolution  TEXT,
            created_at  TIMESTAMP DEFAULT NOW(),
            resolved_at TEXT
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_changelog (
            id          SERIAL PRIMARY KEY,
            version     TEXT,
            title       TEXT NOT NULL,
            body        TEXT,
            category    TEXT DEFAULT 'feature',
            published   INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_alerts (
            id          SERIAL PRIMARY KEY,
            alert_type  TEXT NOT NULL,
            severity    TEXT DEFAULT 'info',
            message     TEXT NOT NULL,
            metric_name TEXT,
            metric_value REAL,
            threshold   REAL,
            acknowledged INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS business_plan_milestones (
            id          SERIAL PRIMARY KEY,
            phase       INTEGER NOT NULL,
            phase_name  TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            week_dates  TEXT,
            focus       TEXT NOT NULL,
            deliverables TEXT,
            target_users INTEGER DEFAULT 0,
            target_mrr  REAL DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            actual_users INTEGER DEFAULT 0,
            actual_mrr  REAL DEFAULT 0,
            notes       TEXT,
            completed_at TEXT,
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE(week_number)
        )""")
    _seed_milestones()


def _seed_milestones():
    """Populate 5-year business plan milestones to $100M ARR."""
    PLAN_VERSION = "v3_100m_5yr"
    with _conn() as conn:
        saved_ver = None
        try:
            row = conn.execute("SELECT value FROM settings WHERE key='plan_version'").fetchone()
            saved_ver = row[0] if row else None
        except Exception:
            pass
        if saved_ver == PLAN_VERSION:
            return
        conn.execute("DELETE FROM business_plan_milestones")
        try:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ('plan_version', PLAN_VERSION))
        except Exception:
            pass

        # (phase, phase_name, week, dates, focus, deliverables, target_users, target_mrr)
        # YEAR 1: $0 → $317K ARR (1,200 paying)
        milestones = [
            # Phase 1: Launch & Validate (Weeks 1-8)
            (1, "Launch & Validate", 1, "Jul 4-10 2026", "LAUNCH", "Public launch, Product Hunt, social blast, Whop listing", 5, 50),
            (1, "Launch & Validate", 2, "Jul 11-17", "Onboarding", "Welcome flow, tutorial video, email drip sequence", 12, 100),
            (1, "Launch & Validate", 3, "Jul 18-24", "Stability", "Error monitoring, Sentry, fix top 5 user complaints", 20, 150),
            (1, "Launch & Validate", 4, "Jul 25-31", "Feedback Loop", "User interviews, NPS survey, prioritize features", 30, 200),
            (1, "Launch & Validate", 5, "Aug 1-7", "Conversion", "Free-to-paid funnel optimization, trial nudges", 40, 300),
            (1, "Launch & Validate", 6, "Aug 8-14", "Dogfooding", "Create 20 demo videos with own tool, post everywhere", 50, 400),
            (1, "Launch & Validate", 7, "Aug 15-21", "SEO", "10 blog posts, landing pages for long-tail keywords", 65, 500),
            (1, "Launch & Validate", 8, "Aug 22-28", "Referral v1", "Invite a friend = 5 free videos, watermark virality", 80, 650),

            # Phase 2: Product-Market Fit (Weeks 9-16) — Target: 100 paying users
            (2, "Product-Market Fit", 9, "Aug 29-Sep 4", "Whop Revenue", "Activate Whop storefront, first Discover sales", 100, 800),
            (2, "Product-Market Fit", 10, "Sep 5-11", "AI Clipper v2", "Speaker detection, auto-thumbnails, B-roll split", 120, 1000),
            (2, "Product-Market Fit", 11, "Sep 12-18", "Mobile Web", "Responsive dashboard, touch-friendly clipper", 150, 1200),
            (2, "Product-Market Fit", 12, "Sep 19-25", "Templates", "20 pre-built templates, template marketplace", 180, 1500),
            (2, "Product-Market Fit", 13, "Sep 26-Oct 2", "Creator Partnerships", "50 micro-influencer affiliate deals (20% recurring)", 220, 2000),
            (2, "Product-Market Fit", 14, "Oct 3-9", "Analytics v1", "Platform analytics, view counts, engagement rates", 280, 2500),
            (2, "Product-Market Fit", 15, "Oct 10-16", "Zapier", "New Video trigger, Create Clip action", 350, 3200),
            (2, "Product-Market Fit", 16, "Oct 17-23", "A/B Pricing", "Test $9.99 vs $12.99 starter, optimize conversion", 400, 4000),

            # Phase 3: Growth Engine (Weeks 17-30) — Scale to 1,200 paying
            (3, "Growth Engine", 17, "Oct 24-30", "Paid Ads v1", "$500 Meta/TikTok ads, test 10 creatives", 500, 5000),
            (3, "Growth Engine", 18, "Oct 31-Nov 6", "Viral Loop", "Free tier watermark, share buttons, embed codes", 600, 6000),
            (3, "Growth Engine", 20, "Nov 14-27", "ScaleOps Phase 1", "PostgreSQL + Redis + S3 migration (100 client trigger)", 800, 8000),
            (3, "Growth Engine", 22, "Nov 28-Dec 11", "Holiday Push", "Black Friday 40% off annual, New Year Content Kit", 1000, 12000),
            (3, "Growth Engine", 24, "Dec 12-25", "API v1 Beta", "Public REST API for Agency tier developers", 1100, 15000),
            (3, "Growth Engine", 26, "Dec 26-Jan 8 2027", "Team Features", "Multi-seat workspaces, shared asset library", 1200, 18000),
            (3, "Growth Engine", 30, "Jan 9-Feb 5", "Collaboration v1", "Team roles, approval workflows, client portals", 1500, 22000),

            # Phase 4: Scale (Weeks 31-52) — End Y1 at $317K ARR
            (4, "Y1 Scale", 34, "Feb 6-Mar 5", "Ad Ramp $2K/mo", "Scale winning ad creatives across 3 platforms", 2000, 28000),
            (4, "Y1 Scale", 38, "Mar 6-Apr 2", "Affiliates", "20% recurring commission, SaaS review sites", 2800, 35000),
            (4, "Y1 Scale", 42, "Apr 3-30", "AI Clipper v3", "Real-time stream clipping, live-to-short pipeline", 3500, 45000),
            (4, "Y1 Scale", 46, "May 1-28", "Enterprise v1", "SSO, custom branding, SLA, dedicated onboarding", 4500, 55000),
            (4, "Y1 Scale", 50, "May 29-Jun 25", "Content Machine", "50 tutorials, weekly blog, creator podcast", 5500, 65000),
            (4, "Y1 Scale", 52, "Jun 26-Jul 2 2027", "Y1 RETRO", "1,200 paying, $317K ARR, plan Year 2", 6000, 70000),

            # YEAR 2: $317K → $2.5M ARR (6,500 paying)
            (5, "Y2 Growth", 56, "Jul-Aug 2027", "ScaleOps Phase 2", "AWS ECS + RDS Multi-AZ + dedicated workers", 8000, 100000),
            (5, "Y2 Growth", 60, "Aug-Sep 2027", "Multi-Language", "Script + voiceover in 15 languages", 10000, 130000),
            (5, "Y2 Growth", 64, "Sep-Oct 2027", "Ad Spend $10K/mo", "Scale paid acquisition, LTV:CAC > 4:1", 13000, 170000),
            (5, "Y2 Growth", 68, "Oct-Nov 2027", "White-Label v2", "Custom domains, branded dashboards, client portals", 16000, 210000),
            (5, "Y2 Growth", 72, "Nov-Dec 2027", "International v1", "Spanish, Portuguese, LATAM partnerships", 20000, 260000),
            (5, "Y2 Growth", 78, "Jan-Feb 2028", "Auto-Scheduling AI", "ML model picks optimal post times per platform", 25000, 330000),
            (5, "Y2 Growth", 84, "Mar-Apr 2028", "Mobile App v1", "React Native, create + publish from phone", 32000, 420000),
            (5, "Y2 Growth", 90, "May-Jun 2028", "Platform Ecosystem", "Third-party plugins, effects marketplace", 40000, 520000),
            (5, "Y2 Growth", 96, "Jun 2028", "Y2 RETRO", "6,500 paying, $2.5M ARR", 50000, 625000),

            # YEAR 3: $2.5M → $10M ARR (20,325 paying)
            (6, "Y3 Dominance", 100, "Jul-Aug 2028", "ScaleOps Phase 3", "Service-oriented arch, FastAPI, React frontend", 60000, 750000),
            (6, "Y3 Dominance", 108, "Sep-Oct 2028", "Enterprise SSO", "SAML, audit logs, SOC 2 compliance", 75000, 950000),
            (6, "Y3 Dominance", 116, "Nov-Dec 2028", "AI Creative Director", "Full content strategy agent, weekly auto-plans", 95000, 1200000),
            (6, "Y3 Dominance", 124, "Jan-Feb 2029", "Ad Spend $50K/mo", "3 SDRs for Pro/Agency outbound", 120000, 1600000),
            (6, "Y3 Dominance", 132, "Mar-Apr 2029", "Series A", "Raise $5-10M at $40-60M valuation", 140000, 2000000),
            (6, "Y3 Dominance", 140, "May-Jun 2029", "International v2", "Japan, Korea, India, MENA launch", 160000, 2500000),
            (6, "Y3 Dominance", 148, "Jun 2029", "Y3 RETRO", "20,325 paying, $10M ARR", 180000, 2800000),

            # YEAR 4: $10M → $40M ARR
            (7, "Y4 Hypergrowth", 156, "Jul-Sep 2029", "ScaleOps Phase 4", "Kubernetes, multi-region US+EU+APAC", 250000, 4500000),
            (7, "Y4 Hypergrowth", 168, "Oct-Dec 2029", "Acquisitions", "Acquire 2 complementary tools, consolidate", 400000, 7000000),
            (7, "Y4 Hypergrowth", 180, "Jan-Mar 2030", "Enterprise Sales Team", "10 SDRs, Fortune 500 pipeline, $50K+ ACVs", 600000, 10000000),
            (7, "Y4 Hypergrowth", 192, "Apr-Jun 2030", "Data Moat", "Content performance ML, predictive virality", 800000, 13500000),
            (7, "Y4 Hypergrowth", 200, "Jun 2030", "Y4 RETRO", "50K+ paying, $40M ARR", 1000000, 16700000),

            # YEAR 5: $40M → $100M ARR
            (8, "Y5 Category King", 208, "Jul-Sep 2030", "ScaleOps Phase 5", "Microservices, data lake, ML infrastructure", 1500000, 22000000),
            (8, "Y5 Category King", 220, "Oct-Dec 2030", "Series B/C", "Raise $30-50M, expand globally, 200+ employees", 2500000, 33000000),
            (8, "Y5 Category King", 232, "Jan-Mar 2031", "Platform Dominance", "Industry standard for AI content, API ecosystem", 4000000, 50000000),
            (8, "Y5 Category King", 244, "Apr-Jun 2031", "IPO Prep", "Board, CFO, SOX compliance, $100M ARR run rate", 6000000, 70000000),
            (8, "Y5 Category King", 252, "Jun 2031", "$100M ARR", "150K paying at $56 ARPU, IPO or strategic exit", 8000000, 100000000),
        ]
        for m in milestones:
            conn.execute("""INSERT INTO business_plan_milestones
                (phase, phase_name, week_number, week_dates, focus, deliverables, target_users, target_mrr)
                VALUES (?,?,?,?,?,?,?,?)""", m)


# ═══════════════════════════════════════════════════════════════════════════════
# SCALE-OPS — Infrastructure upgrade monitoring
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/scale-ops/status")
@login_required
@owner_required
def scale_ops_status():
    """Current infrastructure phase, metrics, and recommendations."""
    from agents.scale_ops import PHASES, _collect_metrics, _determine_phase
    metrics = _collect_metrics()
    phase = _determine_phase(metrics["total_users"])
    phase_info = PHASES[phase]

    with _conn() as conn:
        recs = _rows_to_list(conn.execute("""
            SELECT * FROM scale_ops_recommendations ORDER BY
            CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
            WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC
        """).fetchall())
        pending = [r for r in recs if r["status"] == "pending"]
        completed = [r for r in recs if r["status"] == "completed"]

    next_phase = phase + 1 if phase < 6 else None
    next_info = PHASES.get(next_phase) if next_phase else None
    users_to_next = (next_info["max_users"] if next_info
                     else None)

    return jsonify({
        "current_phase": phase,
        "phase_label": phase_info["label"],
        "phase_stack": phase_info["stack"],
        "next_phase": next_phase,
        "next_phase_label": next_info["label"] if next_info else None,
        "users_until_upgrade": (users_to_next - metrics["total_users"]) if users_to_next else None,
        "metrics": metrics,
        "recommendations": {"pending": pending, "completed": completed},
    })


@monetizer_bp.route("/api/scale-ops/recommendation/<int:rec_id>", methods=["PATCH"])
@login_required
@owner_required
def scale_ops_update_rec(rec_id):
    data = request.json or {}
    status = data.get("status", "pending")
    with _conn() as conn:
        sets = ["status=?"]
        vals = [status]
        if status == "completed":
            sets.append("completed_at=datetime('now')")
        vals.append(rec_id)
        conn.execute(f"UPDATE scale_ops_recommendations SET {','.join(sets)} WHERE id=?", vals)
    return jsonify({"ok": True})


@monetizer_bp.route("/api/scale-ops/trigger", methods=["POST"])
@login_required
@owner_required
def scale_ops_trigger():
    """Manually trigger a scale-ops check."""
    from agents.scale_ops import _run_check
    _run_check()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — Main Monetizer page
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/")
@login_required
@owner_required
def dashboard():
    return render_template("monetizer.html")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REVENUE & MRR
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/revenue/overview")
@login_required
@owner_required
def revenue_overview():
    with _conn() as conn:
        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}

        rows = conn.execute("""
            SELECT subscription_tier, subscription_status, COUNT(*) as cnt
            FROM users WHERE COALESCE(is_admin,0)=0
            GROUP BY subscription_tier, subscription_status
        """).fetchall()

        tier_breakdown = {}
        total_users = 0
        paying_users = 0
        mrr = 0.0

        for r in rows:
            tier = r["subscription_tier"] or "free"
            status = r["subscription_status"] or "active"
            cnt = r["cnt"]
            total_users += cnt

            if tier not in tier_breakdown:
                tier_breakdown[tier] = {"active": 0, "canceled": 0, "past_due": 0, "total": 0, "revenue": 0}
            tier_breakdown[tier][status] = tier_breakdown[tier].get(status, 0) + cnt
            tier_breakdown[tier]["total"] += cnt

            if status == "active" and tier != "free":
                paying_users += cnt
                tier_revenue = cnt * tier_prices.get(tier, 0)
                mrr += tier_revenue
                tier_breakdown[tier]["revenue"] = tier_revenue

        arr = mrr * 12
        arpu = mrr / paying_users if paying_users else 0
        conversion_rate = (paying_users / total_users * 100) if total_users else 0

        # Revenue trend (last 12 months from snapshots)
        trend = _rows_to_list(conn.execute("""
            SELECT snapshot_date, mrr, paying_users, total_users, churn_rate
            FROM monetizer_kpi_snapshots
            ORDER BY snapshot_date DESC LIMIT 12
        """).fetchall())

        # Recent revenue events
        recent_events = _rows_to_list(conn.execute("""
            SELECT r.*, u.email FROM monetizer_revenue_log r
            LEFT JOIN users u ON r.user_id = u.id
            ORDER BY r.created_at DESC LIMIT 25
        """).fetchall())

    return jsonify({
        "mrr": round(mrr, 2),
        "arr": round(arr, 2),
        "arpu": round(arpu, 2),
        "total_users": total_users,
        "paying_users": paying_users,
        "free_users": total_users - paying_users,
        "conversion_rate": round(conversion_rate, 2),
        "tier_breakdown": tier_breakdown,
        "tier_prices": tier_prices,
        "trend": trend,
        "recent_events": recent_events,
    })


@monetizer_bp.route("/api/revenue/log", methods=["POST"])
@login_required
@owner_required
def log_revenue_event():
    data = request.json or {}
    with _conn() as conn:
        conn.execute("""
            INSERT INTO monetizer_revenue_log (user_id, event_type, amount, currency, tier, stripe_event_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data.get("user_id"), data["event_type"], data.get("amount", 0),
              data.get("currency", "usd"), data.get("tier"), data.get("stripe_event_id"), data.get("notes")))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 2. USER INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/users/cohorts")
@login_required
@owner_required
def user_cohorts():
    with _conn() as conn:
        # Signup cohorts by month
        cohorts = _rows_to_list(conn.execute("""
            SELECT to_char(created_at, 'YYYY-MM') as cohort_month,
                   COUNT(*) as signups,
                   SUM(CASE WHEN subscription_tier != 'free' AND subscription_status = 'active' THEN 1 ELSE 0 END) as converted,
                   SUM(CASE WHEN subscription_status = 'canceled' THEN 1 ELSE 0 END) as churned
            FROM users
            GROUP BY cohort_month
            ORDER BY cohort_month DESC
            LIMIT 12
        """).fetchall())

        # Power users (most videos)
        power_users = _rows_to_list(conn.execute("""
            SELECT u.id, u.email, u.name, u.subscription_tier, u.videos_used, u.credits_used,
                   u.created_at, COUNT(j.id) as total_jobs
            FROM users u
            LEFT JOIN jobs j ON j.user_id = u.id
            GROUP BY u.id
            ORDER BY total_jobs DESC
            LIMIT 20
        """).fetchall())

        # At-risk users (paying but no activity in 14 days)
        cutoff = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
        at_risk = _rows_to_list(conn.execute("""
            SELECT u.id, u.email, u.name, u.subscription_tier,
                   MAX(j.created_at) as last_activity
            FROM users u
            LEFT JOIN jobs j ON j.user_id = u.id
            WHERE u.subscription_tier != 'free'
              AND u.subscription_status = 'active'
            GROUP BY u.id
            HAVING last_activity < ? OR last_activity IS NULL
            ORDER BY last_activity ASC
        """, (cutoff,)).fetchall())

        # Tier distribution
        tiers = _rows_to_list(conn.execute("""
            SELECT subscription_tier as tier, COUNT(*) as count
            FROM users GROUP BY subscription_tier
        """).fetchall())

    return jsonify({
        "cohorts": cohorts,
        "power_users": power_users,
        "at_risk_users": at_risk,
        "tier_distribution": tiers,
    })


@monetizer_bp.route("/api/users/<int:user_id>/profile")
@login_required
@owner_required
def user_profile(user_id):
    with _conn() as conn:
        user = _row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Remove sensitive fields
        user.pop("password_hash", None)

        jobs = _rows_to_list(conn.execute("""
            SELECT id, topic, content_type, status, created_at
            FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 50
        """, (user_id,)).fetchall())

        revenue = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_revenue_log WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 20
        """, (user_id,)).fetchall())

        tickets = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_support_tickets WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall())

        # Calculate LTV
        total_revenue = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) as total FROM monetizer_revenue_log
            WHERE user_id = ? AND event_type IN ('subscription', 'payment', 'upgrade')
        """, (user_id,)).fetchone()["total"]

    return jsonify({
        "user": user,
        "jobs": jobs,
        "revenue_events": revenue,
        "tickets": tickets,
        "lifetime_value": round(total_revenue, 2),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 3. COST MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/costs/overview")
@login_required
@owner_required
def costs_overview():
    with _conn() as conn:
        expenses = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_expenses ORDER BY created_at DESC
        """).fetchall())

        cost_centers = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_cost_centers ORDER BY category, name
        """).fetchall())

        # Calculate totals
        monthly_recurring = sum(e["amount"] for e in expenses if e["recurring"])
        total_spend = sum(e["amount"] for e in expenses)
        total_budget = sum(c["monthly_budget"] for c in cost_centers)

        # Per-video cost estimate
        with _conn() as c2:
            total_videos = c2.execute("SELECT COUNT(*) as cnt FROM jobs WHERE status = 'done'").fetchone()["cnt"]
        cost_per_video = monthly_recurring / max(total_videos, 1)

    return jsonify({
        "expenses": expenses,
        "cost_centers": cost_centers,
        "monthly_recurring": round(monthly_recurring, 2),
        "total_spend": round(total_spend, 2),
        "total_budget": round(total_budget, 2),
        "cost_per_video": round(cost_per_video, 4),
        "total_videos_produced": total_videos,
    })


@monetizer_bp.route("/api/costs/expense", methods=["POST"])
@login_required
@owner_required
def add_expense():
    data = request.json or {}
    with _conn() as conn:
        conn.execute("""
            INSERT INTO monetizer_expenses (category, vendor, description, amount, currency, recurring, period)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data["category"], data.get("vendor"), data.get("description"),
              data["amount"], data.get("currency", "usd"),
              1 if data.get("recurring") else 0, data.get("period", "monthly")))
    return jsonify({"ok": True})


@monetizer_bp.route("/api/costs/expense/<int:expense_id>", methods=["DELETE"])
@login_required
@owner_required
def delete_expense(expense_id):
    with _conn() as conn:
        conn.execute("DELETE FROM monetizer_expenses WHERE id = ?", (expense_id,))
    return jsonify({"ok": True})


@monetizer_bp.route("/api/costs/center", methods=["POST"])
@login_required
@owner_required
def upsert_cost_center():
    data = request.json or {}
    with _conn() as conn:
        if data.get("id"):
            conn.execute("""
                UPDATE monetizer_cost_centers
                SET name=?, category=?, monthly_budget=?, actual_spend=?, notes=?, updated_at=?
                WHERE id=?
            """, (data["name"], data["category"], data.get("monthly_budget", 0),
                  data.get("actual_spend", 0), data.get("notes"), _now(), data["id"]))
        else:
            conn.execute("""
                INSERT INTO monetizer_cost_centers (name, category, monthly_budget, actual_spend, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (data["name"], data["category"], data.get("monthly_budget", 0),
                  data.get("actual_spend", 0), data.get("notes")))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GROWTH & CAMPAIGNS
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/growth/overview")
@login_required
@owner_required
def growth_overview():
    with _conn() as conn:
        # New signups per day (last 30 days)
        thirty_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        daily_signups = _rows_to_list(conn.execute("""
            SELECT created_at::date as day, COUNT(*) as signups
            FROM users WHERE created_at >= ?
            GROUP BY created_at::date ORDER BY day
        """, (thirty_ago,)).fetchall())

        # Conversion funnel
        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        starter = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_tier='starter' AND subscription_status='active'").fetchone()["c"]
        creator = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_tier='creator' AND subscription_status='active'").fetchone()["c"]
        pro = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_tier='pro' AND subscription_status='active'").fetchone()["c"]
        agency = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_tier='agency' AND subscription_status='active'").fetchone()["c"]
        churned = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_status='canceled'").fetchone()["c"]

        # Campaigns
        campaigns = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_campaigns ORDER BY created_at DESC
        """).fetchall())

    return jsonify({
        "daily_signups": daily_signups,
        "funnel": {
            "total_users": total,
            "free": total - starter - creator - pro - agency,
            "starter": starter,
            "creator": creator,
            "pro": pro,
            "agency": agency,
            "churned": churned,
        },
        "campaigns": campaigns,
    })


@monetizer_bp.route("/api/growth/campaign", methods=["POST"])
@login_required
@owner_required
def upsert_campaign():
    data = request.json or {}
    with _conn() as conn:
        if data.get("id"):
            conn.execute("""
                UPDATE monetizer_campaigns
                SET name=?, channel=?, status=?, budget=?, spent=?,
                    impressions=?, clicks=?, signups=?, conversions=?,
                    start_date=?, end_date=?, notes=?
                WHERE id=?
            """, (data["name"], data["channel"], data.get("status", "draft"),
                  data.get("budget", 0), data.get("spent", 0),
                  data.get("impressions", 0), data.get("clicks", 0),
                  data.get("signups", 0), data.get("conversions", 0),
                  data.get("start_date"), data.get("end_date"), data.get("notes"),
                  data["id"]))
        else:
            conn.execute("""
                INSERT INTO monetizer_campaigns (name, channel, status, budget, spent, impressions, clicks, signups, conversions, start_date, end_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (data["name"], data["channel"], data.get("status", "draft"),
                  data.get("budget", 0), data.get("spent", 0),
                  data.get("impressions", 0), data.get("clicks", 0),
                  data.get("signups", 0), data.get("conversions", 0),
                  data.get("start_date"), data.get("end_date"), data.get("notes")))
    return jsonify({"ok": True})


@monetizer_bp.route("/api/growth/campaign/<int:campaign_id>", methods=["DELETE"])
@login_required
@owner_required
def delete_campaign(campaign_id):
    with _conn() as conn:
        conn.execute("DELETE FROM monetizer_campaigns WHERE id = ?", (campaign_id,))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CONTENT & PLATFORM HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/content/stats")
@login_required
@owner_required
def content_stats():
    with _conn() as conn:
        # Videos by content type
        by_type = _rows_to_list(conn.execute("""
            SELECT content_type, COUNT(*) as count,
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as completed,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as failed
            FROM jobs GROUP BY content_type ORDER BY count DESC
        """).fetchall())

        # Videos by status
        by_status = _rows_to_list(conn.execute("""
            SELECT status, COUNT(*) as count FROM jobs GROUP BY status
        """).fetchall())

        # Daily production (last 30 days)
        thirty_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        daily_production = _rows_to_list(conn.execute("""
            SELECT created_at::date as day, COUNT(*) as videos,
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as completed
            FROM jobs WHERE created_at >= ?
            GROUP BY created_at::date ORDER BY day
        """, (thirty_ago,)).fetchall())

        # Platform publishing stats
        platform_stats = _rows_to_list(conn.execute("""
            SELECT platform, COUNT(*) as published,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successful
            FROM published_videos GROUP BY platform
        """).fetchall())

        # Top performing content
        top_content = _rows_to_list(conn.execute("""
            SELECT j.id, j.topic, j.content_type,
                   COALESCE(a.views, 0) as views,
                   COALESCE(a.likes, 0) as likes,
                   COALESCE(a.ctr, 0) as ctr
            FROM jobs j
            LEFT JOIN analytics_cache a ON a.job_id = j.id
            WHERE j.status = 'done'
            ORDER BY COALESCE(a.views, 0) DESC
            LIMIT 15
        """).fetchall())

        # Credit usage across all users
        credit_usage = conn.execute("""
            SELECT SUM(credits_used) as total_credits, SUM(videos_used) as total_videos
            FROM users
        """).fetchone()

    return jsonify({
        "by_type": by_type,
        "by_status": by_status,
        "daily_production": daily_production,
        "platform_stats": platform_stats,
        "top_content": top_content,
        "total_credits_used": credit_usage["total_credits"] or 0,
        "total_videos_produced": credit_usage["total_videos"] or 0,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FEATURE FLAGS
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/features")
@login_required
@owner_required
def list_features():
    with _conn() as conn:
        flags = _rows_to_list(conn.execute("SELECT * FROM monetizer_feature_flags ORDER BY name").fetchall())
    return jsonify({"flags": flags})


@monetizer_bp.route("/api/features", methods=["POST"])
@login_required
@owner_required
def upsert_feature():
    data = request.json or {}
    with _conn() as conn:
        existing = conn.execute("SELECT id FROM monetizer_feature_flags WHERE name = ?", (data["name"],)).fetchone()
        if existing:
            conn.execute("""
                UPDATE monetizer_feature_flags
                SET enabled=?, tier_min=?, rollout_pct=?, description=?, updated_at=?
                WHERE name=?
            """, (1 if data.get("enabled") else 0, data.get("tier_min", "free"),
                  data.get("rollout_pct", 100), data.get("description"), _now(), data["name"]))
        else:
            conn.execute("""
                INSERT INTO monetizer_feature_flags (name, enabled, tier_min, rollout_pct, description)
                VALUES (?, ?, ?, ?, ?)
            """, (data["name"], 1 if data.get("enabled") else 0,
                  data.get("tier_min", "free"), data.get("rollout_pct", 100), data.get("description")))
    return jsonify({"ok": True})


@monetizer_bp.route("/api/features/<int:flag_id>/toggle", methods=["POST"])
@login_required
@owner_required
def toggle_feature(flag_id):
    with _conn() as conn:
        conn.execute("""
            UPDATE monetizer_feature_flags SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END, updated_at = ? WHERE id = ?
        """, (_now(), flag_id))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SUPPORT TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/support/tickets")
@login_required
@owner_required
def list_tickets():
    status_filter = request.args.get("status", "")
    with _conn() as conn:
        if status_filter:
            tickets = _rows_to_list(conn.execute("""
                SELECT t.*, u.email FROM monetizer_support_tickets t
                LEFT JOIN users u ON t.user_id = u.id
                WHERE t.status = ?
                ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.created_at DESC
            """, (status_filter,)).fetchall())
        else:
            tickets = _rows_to_list(conn.execute("""
                SELECT t.*, u.email FROM monetizer_support_tickets t
                LEFT JOIN users u ON t.user_id = u.id
                ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.created_at DESC
                LIMIT 100
            """).fetchall())
    return jsonify({"tickets": tickets})


@monetizer_bp.route("/api/support/ticket", methods=["POST"])
@login_required
@owner_required
def upsert_ticket():
    data = request.json or {}
    with _conn() as conn:
        if data.get("id"):
            conn.execute("""
                UPDATE monetizer_support_tickets
                SET subject=?, body=?, priority=?, status=?, assigned_to=?, resolution=?,
                    resolved_at = CASE WHEN ? = 'resolved' THEN datetime('now') ELSE resolved_at END
                WHERE id=?
            """, (data.get("subject"), data.get("body"), data.get("priority", "normal"),
                  data.get("status", "open"), data.get("assigned_to"), data.get("resolution"),
                  data.get("status", "open"), data["id"]))
        else:
            conn.execute("""
                INSERT INTO monetizer_support_tickets (user_id, subject, body, priority, status, assigned_to)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (data.get("user_id"), data["subject"], data.get("body"),
                  data.get("priority", "normal"), "open", data.get("assigned_to")))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 8. KPI SNAPSHOTS
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/kpi/snapshot", methods=["POST"])
@login_required
@owner_required
def take_kpi_snapshot():
    today = _today()
    with _conn() as conn:
        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}

        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        paying = conn.execute("""
            SELECT COUNT(*) as c FROM users
            WHERE subscription_tier != 'free' AND subscription_status = 'active'
        """).fetchone()["c"]
        churned = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_status = 'canceled'").fetchone()["c"]

        # MRR calc
        mrr = 0
        for tier, price in tier_prices.items():
            cnt = conn.execute("""
                SELECT COUNT(*) as c FROM users
                WHERE subscription_tier = ? AND subscription_status = 'active'
            """, (tier,)).fetchone()["c"]
            mrr += cnt * price

        # New signups today
        new_today = conn.execute("""
            SELECT COUNT(*) as c FROM users WHERE created_at::date = ?
        """, (today,)).fetchone()["c"]

        total_videos = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status='done'").fetchone()["c"]
        total_credits = conn.execute("SELECT COALESCE(SUM(credits_used), 0) as c FROM users").fetchone()["c"]

        arpu = mrr / paying if paying else 0
        conversion = (paying / total * 100) if total else 0
        churn_rate = (churned / (churned + paying) * 100) if (churned + paying) else 0
        ltv = arpu / (churn_rate / 100) if churn_rate > 0 else arpu * 24

        conn.execute("""
            INSERT INTO monetizer_kpi_snapshots
            (snapshot_date, mrr, arr, total_users, paying_users, free_users,
             churned_users, new_signups, total_videos, total_credits_used,
             avg_revenue_per_user, conversion_rate, churn_rate, ltv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (snapshot_date) DO UPDATE SET
             mrr = EXCLUDED.mrr, arr = EXCLUDED.arr, total_users = EXCLUDED.total_users,
             paying_users = EXCLUDED.paying_users, free_users = EXCLUDED.free_users,
             churned_users = EXCLUDED.churned_users, new_signups = EXCLUDED.new_signups,
             total_videos = EXCLUDED.total_videos, total_credits_used = EXCLUDED.total_credits_used,
             avg_revenue_per_user = EXCLUDED.avg_revenue_per_user, conversion_rate = EXCLUDED.conversion_rate,
             churn_rate = EXCLUDED.churn_rate, ltv = EXCLUDED.ltv
        """, (today, round(mrr, 2), round(mrr * 12, 2), total, paying,
              total - paying, churned, new_today, total_videos, total_credits,
              round(arpu, 2), round(conversion, 2), round(churn_rate, 2), round(ltv, 2)))

    return jsonify({"ok": True, "snapshot_date": today, "mrr": round(mrr, 2)})


@monetizer_bp.route("/api/kpi/history")
@login_required
@owner_required
def kpi_history():
    with _conn() as conn:
        rows = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_kpi_snapshots ORDER BY snapshot_date DESC LIMIT 90
        """).fetchall())
    return jsonify({"snapshots": rows})


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GOALS
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/goals")
@login_required
@owner_required
def list_goals():
    with _conn() as conn:
        goals = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_goals ORDER BY status, deadline
        """).fetchall())
    return jsonify({"goals": goals})


@monetizer_bp.route("/api/goals", methods=["POST"])
@login_required
@owner_required
def upsert_goal():
    data = request.json or {}
    with _conn() as conn:
        if data.get("id"):
            conn.execute("""
                UPDATE monetizer_goals SET metric=?, target_value=?, current_value=?, deadline=?, status=?
                WHERE id=?
            """, (data["metric"], data["target_value"], data.get("current_value", 0),
                  data.get("deadline"), data.get("status", "active"), data["id"]))
        else:
            conn.execute("""
                INSERT INTO monetizer_goals (metric, target_value, current_value, deadline)
                VALUES (?, ?, ?, ?)
            """, (data["metric"], data["target_value"], data.get("current_value", 0), data.get("deadline")))
    return jsonify({"ok": True})


@monetizer_bp.route("/api/goals/<int:goal_id>", methods=["DELETE"])
@login_required
@owner_required
def delete_goal(goal_id):
    with _conn() as conn:
        conn.execute("DELETE FROM monetizer_goals WHERE id = ?", (goal_id,))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CHANGELOG
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/changelog")
@login_required
@owner_required
def list_changelog():
    with _conn() as conn:
        entries = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_changelog ORDER BY created_at DESC LIMIT 50
        """).fetchall())
    return jsonify({"entries": entries})


@monetizer_bp.route("/api/changelog", methods=["POST"])
@login_required
@owner_required
def add_changelog():
    data = request.json or {}
    with _conn() as conn:
        conn.execute("""
            INSERT INTO monetizer_changelog (version, title, body, category, published)
            VALUES (?, ?, ?, ?, ?)
        """, (data.get("version"), data["title"], data.get("body"),
              data.get("category", "feature"), 1 if data.get("published") else 0))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 11. ALERTS & MONITORING
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/alerts")
@login_required
@owner_required
def list_alerts():
    with _conn() as conn:
        alerts = _rows_to_list(conn.execute("""
            SELECT * FROM monetizer_alerts ORDER BY (status='open') DESC, acknowledged, created_at DESC LIMIT 50
        """).fetchall())
    return jsonify({"alerts": alerts})


@monetizer_bp.route("/api/alerts/<int:alert_id>/ack", methods=["POST"])
@login_required
@owner_required
def ack_alert(alert_id):
    with _conn() as conn:
        conn.execute("UPDATE monetizer_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    return jsonify({"ok": True})


@monetizer_bp.route("/api/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
@owner_required
def resolve_alert(alert_id):
    with _conn() as conn:
        conn.execute(
            "UPDATE monetizer_alerts SET status='resolved', acknowledged=1, resolved_at=datetime('now') WHERE id = ?",
            (alert_id,))
    return jsonify({"ok": True})


def create_alert(alert_type, message, severity="warning", metric_name=None, metric_value=None,
                  threshold=None, suggested_action=None, source_agent=None):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO monetizer_alerts
              (alert_type, severity, message, metric_name, metric_value, threshold,
               suggested_action, source_agent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """, (alert_type, severity, message, metric_name, metric_value, threshold,
              suggested_action, source_agent))


# ═══════════════════════════════════════════════════════════════════════════════
# 12. SYSTEM HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/system/health")
@login_required
@owner_required
def system_health():
    import shutil

    output_dir = config.OUTPUT_DIR
    output_size = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file()) if output_dir.exists() else 0

    # config.DATA_DIR is the mounted persistent disk (20GB on Render), not "/"
    # (the ephemeral container root) -- that's where output_dir above actually
    # lives, and where space actually runs out.
    disk = shutil.disk_usage(str(config.DATA_DIR))

    with _conn() as conn:
        stuck_jobs = conn.execute("""
            SELECT COUNT(*) as c FROM jobs
            WHERE status IN ('pending', 'running')
            AND created_at < NOW() - INTERVAL '1 hour'
        """).fetchone()["c"]

        error_jobs_24h = conn.execute("""
            SELECT COUNT(*) as c FROM jobs
            WHERE status = 'error'
            AND created_at > NOW() - INTERVAL '1 day'
        """).fetchone()["c"]

        total_jobs_24h = conn.execute("""
            SELECT COUNT(*) as c FROM jobs
            WHERE created_at > NOW() - INTERVAL '1 day'
        """).fetchone()["c"]

    # API key status
    api_keys = {
        "anthropic": bool(config.ANTHROPIC_API_KEY),
        "google": bool(config.GOOGLE_API_KEY),
        "pixabay": bool(config.PIXABAY_API_KEY),
        "elevenlabs": bool(config.ELEVENLABS_API_KEY),
        "higgsfield": bool(config.HIGGSFIELD_MCP_TOKEN),
        "stripe": bool(config.STRIPE_SECRET_KEY),
    }

    return jsonify({
        "database": "PostgreSQL (Supabase)",
        "output_size_mb": round(output_size / 1024 / 1024, 2),
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "disk_used_gb": round(disk.used / 1024**3, 2),
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "disk_usage_pct": round(disk.used / disk.total * 100, 1),
        "stuck_jobs": stuck_jobs,
        "error_jobs_24h": error_jobs_24h,
        "total_jobs_24h": total_jobs_24h,
        "error_rate_24h": round(error_jobs_24h / max(total_jobs_24h, 1) * 100, 1),
        "api_keys": api_keys,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 13. PRICING SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/pricing/simulate", methods=["POST"])
@login_required
@owner_required
def pricing_simulate():
    data = request.json or {}
    scenarios = data.get("scenarios", [])
    results = []

    with _conn() as conn:
        # Current user counts per tier
        current = {}
        for row in conn.execute("""
            SELECT subscription_tier, COUNT(*) as c FROM users
            WHERE subscription_status = 'active' AND COALESCE(is_admin,0)=0
            GROUP BY subscription_tier
        """).fetchall():
            current[row["subscription_tier"]] = row["c"]

    for scenario in scenarios:
        name = scenario.get("name", "Unnamed")
        prices = scenario.get("prices", {})
        projected_mrr = 0
        breakdown = {}
        for tier, price in prices.items():
            users = current.get(tier, 0)
            rev = users * price
            projected_mrr += rev
            breakdown[tier] = {"users": users, "price": price, "revenue": rev}
        results.append({
            "name": name,
            "mrr": round(projected_mrr, 2),
            "arr": round(projected_mrr * 12, 2),
            "breakdown": breakdown,
        })

    return jsonify({"results": results, "current_users": current})


# ═══════════════════════════════════════════════════════════════════════════════
# 14. EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/export/<report_type>")
@login_required
@owner_required
def export_report(report_type):
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    with _conn() as conn:
        if report_type == "users":
            writer.writerow(["ID", "Email", "Name", "Tier", "Status", "Videos Used", "Credits Used", "Created"])
            for r in conn.execute("SELECT id, email, name, subscription_tier, subscription_status, videos_used, credits_used, created_at FROM users ORDER BY id").fetchall():
                writer.writerow(list(r.values()))
        elif report_type == "revenue":
            writer.writerow(["ID", "User ID", "Event", "Amount", "Tier", "Date"])
            for r in conn.execute("SELECT id, user_id, event_type, amount, tier, created_at FROM monetizer_revenue_log ORDER BY created_at DESC").fetchall():
                writer.writerow(list(r.values()))
        elif report_type == "kpi":
            writer.writerow(["Date", "MRR", "ARR", "Total Users", "Paying", "Free", "Churned", "Conv Rate", "Churn Rate", "LTV"])
            for r in conn.execute("SELECT snapshot_date, mrr, arr, total_users, paying_users, free_users, churned_users, conversion_rate, churn_rate, ltv FROM monetizer_kpi_snapshots ORDER BY snapshot_date DESC").fetchall():
                writer.writerow(list(r.values()))
        elif report_type == "jobs":
            writer.writerow(["ID", "User ID", "Topic", "Type", "Status", "Created"])
            for r in conn.execute("SELECT id, user_id, topic, content_type, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 1000").fetchall():
                writer.writerow(list(r.values()))
        else:
            return jsonify({"error": f"Unknown report type: {report_type}"}), 400

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=monetizer_{report_type}_{_today()}.csv"}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# IEBC CONSULTANT C-SUITE — Executive Agent Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

EXEC_PERSONAS = {
    "marcus_vance": {
        "name": "Marcus Vance", "title": "Chief Growth Officer",
        "role": "Product-Led Growth, Virality Loops, Acquisition Engineering",
        "avatar": "M", "color": "#3b82f6",
        "status": "active", "interval": "14 hrs"
    },
    "elena_rostova": {
        "name": "Elena Rostova", "title": "VP of Enterprise Development",
        "role": "B2B Sales Automation, Enterprise Lead Scraping, Intent Detection",
        "avatar": "E", "color": "#8b5cf6",
        "status": "active", "interval": "14 hrs"
    },
    "julian_vance": {
        "name": "Dr. Julian Vance", "title": "Director of Retention & LTV",
        "role": "Churn Mitigation, Predictive Analytics, User Engagement",
        "avatar": "J", "color": "#10b981",
        "status": "active", "interval": "14 hrs"
    },
    "sterling_croft": {
        "name": "Sterling Croft", "title": "Chief Business Officer",
        "role": "Unit Economics, Strategic Partnerships, Pricing Models",
        "avatar": "S", "color": "#f59e0b",
        "status": "active", "interval": "14 hrs"
    },
    "vivian_cross": {
        "name": "Vivian Cross", "title": "Chief Financial Officer",
        "role": "IEBC Efficiency Accounting, Credit Monitoring, Subscription Renewals",
        "avatar": "V", "color": "#10b981",
        "status": "active", "interval": "6 hrs"
    },
    "nova_chen": {
        "name": "Nova Chen", "title": "Chief Product Officer",
        "role": "Studio Usage, Feature Adoption, Activation Rate, Product Health",
        "avatar": "N", "color": "#8b5cf6",
        "status": "active", "interval": "12 hrs"
    },
    "rex_dawson": {
        "name": "Rex Dawson", "title": "Director of Revenue Operations",
        "role": "Stripe Reconciliation, Failed Payments, Dunning, MRR Accuracy",
        "avatar": "R", "color": "#f59e0b",
        "status": "active", "interval": "4 hrs"
    },
    "aria_singh": {
        "name": "Aria Singh", "title": "Director of Customer Success",
        "role": "Activation Monitoring, Onboarding, First-Milestone Tracking, Plan Cohorts",
        "avatar": "A", "color": "#ec4899",
        "status": "active", "interval": "6 hrs"
    },
    "isabella_cruz": {
        "name": "Isabella Cruz", "title": "Director of Email Automation",
        "role": "Lifecycle Emails, Win-Back Sequences, Activation Nudges, Payment Recovery Emails",
        "avatar": "I", "color": "#f43f5e",
        "status": "active", "interval": "2 hrs"
    },
    "sterling_pierce": {
        "name": "Sterling Pierce", "title": "Chief Revenue Recovery Officer",
        "role": "Stripe Retry, Dunning Automation, Failed Payment Recovery, Involuntary Churn Prevention",
        "avatar": "SP", "color": "#0ea5e9",
        "status": "active", "interval": "8 hrs"
    },
}


@monetizer_bp.route("/executives")
@login_required
@owner_required
def executives_page():
    return render_template("monetizer_executives.html")


@monetizer_bp.route("/api/executives/overview")
@login_required
@owner_required
def api_executives_overview():
    from agents import executive_bus as bus
    stats = bus.get_agent_stats()
    personas = {}
    for key, persona in EXEC_PERSONAS.items():
        s = stats.get(key, {})
        personas[key] = {**persona, **s}
    return jsonify({"agents": personas})


@monetizer_bp.route("/api/executives/events")
@login_required
@owner_required
def api_executives_events():
    from agents import executive_bus as bus
    limit = request.args.get("limit", 50, type=int)
    return jsonify(bus.get_recent_events(limit))


@monetizer_bp.route("/api/executives/actions")
@login_required
@owner_required
def api_executives_actions():
    from agents import executive_bus as bus
    agent = request.args.get("agent")
    limit = request.args.get("limit", 50, type=int)
    return jsonify(bus.get_recent_actions(agent, limit))


@monetizer_bp.route("/api/executives/log")
@login_required
@owner_required
def api_executives_log():
    from agents import executive_bus as bus
    agent = request.args.get("agent")
    limit = request.args.get("limit", 100, type=int)
    return jsonify(bus.get_agent_log(agent, limit))


@monetizer_bp.route("/api/executives/trigger", methods=["POST"])
@login_required
@owner_required
def api_executives_trigger():
    """Manually trigger an executive agent to run now."""
    data = request.get_json(force=True)
    agent = data.get("agent")
    if agent == "marcus_vance":
        from agents.marcus_growth import _compute_growth_metrics, _check_upgrade_triggers
        metrics = _compute_growth_metrics()
        _check_upgrade_triggers()
        return jsonify({"ok": True, "metrics": metrics})
    elif agent == "elena_rostova":
        from agents.elena_enterprise import _identify_high_value_accounts, _compute_pipeline_metrics
        _identify_high_value_accounts()
        _compute_pipeline_metrics()
        return jsonify({"ok": True})
    elif agent == "julian_vance":
        from agents.julian_retention import _detect_churn_risks, _compute_retention_metrics
        risks = _detect_churn_risks()
        metrics = _compute_retention_metrics()
        return jsonify({"ok": True, "at_risk": len(risks), "metrics": metrics})
    elif agent == "sterling_croft":
        from agents.sterling_business import _compute_unit_economics
        economics = _compute_unit_economics()
        return jsonify({"ok": True, "economics": economics})
    elif agent == "vivian_cross":
        from agents.vivian_finance import _run_cycle
        _run_cycle()
        return jsonify({"ok": True})
    elif agent == "nova_chen":
        from agents.nova_product import _run_cycle
        _run_cycle()
        return jsonify({"ok": True})
    elif agent == "rex_dawson":
        from agents.rex_revops import _run_cycle
        _run_cycle()
        return jsonify({"ok": True})
    elif agent == "aria_singh":
        from agents.aria_success import _run_cycle
        _run_cycle()
        return jsonify({"ok": True})
    elif agent == "isabella_cruz":
        from agents.isabella_email import _run_cycle
        _run_cycle()
        return jsonify({"ok": True})
    elif agent == "sterling_pierce":
        from agents.sterling_pierce import _run_cycle
        _run_cycle()
        return jsonify({"ok": True})
    return jsonify({"error": "Unknown agent"}), 400


# ═══════════════════════════════════════════════════════════════════════════════
# BUSINESS PLAN — Progress Tracking
# ═══════════════════════════════════════════════════════════════════════════════

PLAN_TARGETS = {
    "launch_date": "2026-07-04",
    "target_arr_y1": 317_000,
    "target_arr_y2": 2_500_000,
    "target_arr_y3": 10_000_000,
    "target_arr_y4": 40_000_000,
    "target_arr_y5": 100_000_000,
    "target_users_y3": 20_325,
    "target_users_y5": 150_000,
    "gross_margin_target": 87,
    "arpu_target_y1": 22,
    "arpu_target_y3": 41,
    "arpu_target_y5": 56,
    "ltv_target": 780,
    "cac_target": 65,
    "breakeven_month": 20,
    "infra_upgrade_at": 100,
}


def _get_current_week():
    from datetime import timezone
    launch = datetime(2026, 7, 4, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc) if hasattr(datetime, 'now') else datetime.utcnow()
    try:
        now = datetime.now(timezone.utc)
    except Exception:
        now = datetime.utcnow()
    delta = (now - launch.replace(tzinfo=None) if now.tzinfo is None else now - launch)
    weeks = max(0, delta.days // 7)
    return weeks


@monetizer_bp.route("/plan")
@login_required
@owner_required
def plan_page():
    return render_template("monetizer_plan.html")


@monetizer_bp.route("/api/plan/overview")
@login_required
@owner_required
def api_plan_overview():
    current_week = _get_current_week()

    with _conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paying = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') "
            "AND subscription_tier IS NOT NULL AND COALESCE(is_admin,0)=0"
        ).fetchone()[0]

        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}
        mrr = 0
        for row in conn.execute("""
            SELECT subscription_tier, COUNT(*) as cnt FROM users
            WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL
              AND subscription_status='active' AND COALESCE(is_admin,0)=0
            GROUP BY subscription_tier
        """).fetchall():
            mrr += row["cnt"] * tier_prices.get(row["subscription_tier"], 0)
        arr = mrr * 12

        milestones = _rows_to_list(conn.execute(
            "SELECT * FROM business_plan_milestones ORDER BY week_number"
        ).fetchall())

        completed = sum(1 for m in milestones if m["status"] == "completed")
        in_progress = sum(1 for m in milestones if m["status"] == "in_progress")
        total = len(milestones)

    current_milestone = None
    for m in milestones:
        if m["week_number"] >= current_week and m["status"] != "completed":
            current_milestone = m
            break

    target_for_week = None
    for m in milestones:
        if m["week_number"] >= current_week:
            target_for_week = m
            break

    return jsonify({
        "current_week": current_week,
        "plan_targets": PLAN_TARGETS,
        "actual": {
            "total_users": total_users,
            "paying_users": paying,
            "mrr": round(mrr, 2),
            "arr": round(arr, 2),
        },
        "target": {
            "users": target_for_week["target_users"] if target_for_week else 0,
            "mrr": target_for_week["target_mrr"] if target_for_week else 0,
        },
        "progress": {
            "completed": completed,
            "in_progress": in_progress,
            "total": total,
            "pct": round(completed / total * 100, 1) if total else 0,
        },
        "milestones": milestones,
        "current_milestone": current_milestone,
    })


def sync_milestone_progress():
    """Automatically advance business_plan_milestones status based on real
    actuals (no admin has to click through the PATCH endpoint), and raise
    real task-queue alerts: 'milestone_completed' when actuals cross a
    milestone's target, 'milestone_behind' when a due milestone hasn't hit
    target yet. Dedups 'behind' alerts per milestone so an ongoing gap
    doesn't spam a fresh alert every time this runs."""
    current_week = _get_current_week()
    with _conn() as conn:
        paying = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') "
            "AND subscription_tier IS NOT NULL AND COALESCE(is_admin,0)=0"
        ).fetchone()[0]
        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}
        mrr = 0
        for row in conn.execute("""
            SELECT subscription_tier, COUNT(*) as cnt FROM users
            WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL
              AND subscription_status='active' AND COALESCE(is_admin,0)=0
            GROUP BY subscription_tier
        """).fetchall():
            mrr += row["cnt"] * tier_prices.get(row["subscription_tier"], 0)
        mrr = round(mrr, 2)

        due = _rows_to_list(conn.execute(
            "SELECT * FROM business_plan_milestones WHERE status != 'completed' "
            "AND week_number <= ? ORDER BY week_number", (current_week,)
        ).fetchall())

        completed_now, still_behind = [], []
        for m in due:
            conn.execute(
                "UPDATE business_plan_milestones SET actual_users=?, actual_mrr=? WHERE id=?",
                (paying, mrr, m["id"]),
            )
            hit_target = paying >= m["target_users"] and mrr >= m["target_mrr"]
            if hit_target:
                conn.execute(
                    "UPDATE business_plan_milestones SET status='completed', completed_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), m["id"]),
                )
                completed_now.append(m)
            else:
                if m["status"] == "pending":
                    conn.execute("UPDATE business_plan_milestones SET status='in_progress' WHERE id=?", (m["id"],))
                still_behind.append(m)

        tag = lambda m: f"milestone_week_{m['week_number']}"

        # Auto-resolve any lingering 'behind' alert for a milestone that just completed
        for m in completed_now:
            conn.execute(
                "UPDATE monetizer_alerts SET status='resolved', resolved_at=NOW() "
                "WHERE alert_type='milestone_behind' AND metric_name=? AND status='open'",
                (tag(m),),
            )

        # Dedup: skip milestones that already have an open 'behind' alert
        open_tags = {r["metric_name"] for r in conn.execute(
            "SELECT DISTINCT metric_name FROM monetizer_alerts WHERE alert_type='milestone_behind' AND status='open'"
        ).fetchall()}
        still_behind = [m for m in still_behind if tag(m) not in open_tags]

    for m in completed_now:
        create_alert("milestone_completed",
                      f"Week {m['week_number']} milestone hit: {m['focus']} ({paying} paying users, ${mrr:,.0f} MRR)",
                      severity="info", metric_name=f"milestone_week_{m['week_number']}",
                      source_agent="sterling_croft")
    for m in still_behind:
        gap_users = max(0, m["target_users"] - paying)
        gap_mrr = max(0, m["target_mrr"] - mrr)
        create_alert("milestone_behind",
                      f"Week {m['week_number']} ({m['focus']}) target not yet hit — "
                      f"need {gap_users} more paying users and ${gap_mrr:,.0f} more MRR",
                      severity="warning", metric_name=f"milestone_week_{m['week_number']}",
                      metric_value=gap_users, threshold=0,
                      suggested_action=m.get("deliverables") or "Review this week's plan focus.",
                      source_agent="sterling_croft")

    return {"current_week": current_week, "completed": len(completed_now),
            "still_behind": len(still_behind), "paying": paying, "mrr": mrr}


@monetizer_bp.route("/api/plan/milestone/<int:milestone_id>", methods=["PATCH"])
@login_required
@owner_required
def api_plan_update_milestone(milestone_id):
    data = request.get_json(force=True)
    status = data.get("status")
    notes = data.get("notes")
    with _conn() as conn:
        sets = []
        vals = []
        if status:
            sets.append("status=?")
            vals.append(status)
            if status == "completed":
                sets.append("completed_at=datetime('now')")
        if notes is not None:
            sets.append("notes=?")
            vals.append(notes)

        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paying = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') "
            "AND subscription_tier IS NOT NULL AND COALESCE(is_admin,0)=0"
        ).fetchone()[0]
        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}
        mrr = 0
        for row in conn.execute("""
            SELECT subscription_tier, COUNT(*) as cnt FROM users
            WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL
              AND subscription_status='active' AND COALESCE(is_admin,0)=0
            GROUP BY subscription_tier
        """).fetchall():
            mrr += row["cnt"] * tier_prices.get(row["subscription_tier"], 0)

        sets.extend(["actual_users=?", "actual_mrr=?"])
        vals.extend([total_users, round(mrr, 2)])
        vals.append(milestone_id)
        conn.execute(f"UPDATE business_plan_milestones SET {','.join(sets)} WHERE id=?", vals)
    return jsonify({"ok": True})
