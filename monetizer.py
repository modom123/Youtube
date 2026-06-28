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
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS monetizer_revenue_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            event_type  TEXT NOT NULL,
            amount      REAL NOT NULL DEFAULT 0,
            currency    TEXT DEFAULT 'usd',
            tier        TEXT,
            stripe_event_id TEXT,
            notes       TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT NOT NULL,
            vendor      TEXT,
            description TEXT,
            amount      REAL NOT NULL,
            currency    TEXT DEFAULT 'usd',
            recurring   INTEGER DEFAULT 0,
            period      TEXT DEFAULT 'monthly',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_kpi_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(snapshot_date)
        );

        CREATE TABLE IF NOT EXISTS monetizer_goals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            metric      TEXT NOT NULL,
            target_value REAL NOT NULL,
            current_value REAL DEFAULT 0,
            deadline    TEXT,
            status      TEXT DEFAULT 'active',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_cost_centers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            category    TEXT NOT NULL,
            monthly_budget REAL DEFAULT 0,
            actual_spend REAL DEFAULT 0,
            notes       TEXT,
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_campaigns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_feature_flags (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            enabled     INTEGER DEFAULT 0,
            tier_min    TEXT DEFAULT 'free',
            rollout_pct INTEGER DEFAULT 100,
            description TEXT,
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_support_tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            subject     TEXT NOT NULL,
            body        TEXT,
            priority    TEXT DEFAULT 'normal',
            status      TEXT DEFAULT 'open',
            assigned_to TEXT,
            resolution  TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS monetizer_changelog (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            version     TEXT,
            title       TEXT NOT NULL,
            body        TEXT,
            category    TEXT DEFAULT 'feature',
            published   INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS monetizer_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type  TEXT NOT NULL,
            severity    TEXT DEFAULT 'info',
            message     TEXT NOT NULL,
            metric_name TEXT,
            metric_value REAL,
            threshold   REAL,
            acknowledged INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS business_plan_milestones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(week_number)
        );
        """)
    _seed_milestones()


def _seed_milestones():
    """Populate business plan milestones. Re-seeds if plan version changed."""
    PLAN_VERSION = "v2_smooth"
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
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('plan_version', ?)", (PLAN_VERSION,))
        except Exception:
            pass

        milestones = [
            (1,"Launch & Validate",1,"Jul 4-10","LAUNCH","Public launch, ProductHunt post, social blast",5,149),
            (1,"Launch & Validate",2,"Jul 11-17","Onboarding","Fix friction, welcome flow, tutorial video",8,149),
            (1,"Launch & Validate",3,"Jul 18-24","Stability","Monitor errors, fix crashes, add Sentry",10,149),
            (1,"Launch & Validate",4,"Jul 25-31","Feedback Loop","User interviews, NPS survey, prioritize complaints",12,149),
            (1,"Launch & Validate",5,"Aug 1-7","Conversion","Optimize free->paid funnel, trial nudges, email drip",15,223),
            (1,"Launch & Validate",6,"Aug 8-14","Content","Create 10 demo videos, post on socials",15,223),
            (1,"Launch & Validate",7,"Aug 15-21","SEO","Blog posts, landing page optimization",18,223),
            (1,"Launch & Validate",8,"Aug 22-28","Referral v1","Invite a friend, get 5 free videos",20,223),
            (2,"Product-Market Fit",9,"Aug 29-Sep 4","Analytics","Add Mixpanel/Amplitude, track funnel",25,446),
            (2,"Product-Market Fit",10,"Sep 5-11","Templates","20 pre-built video templates",30,446),
            (2,"Product-Market Fit",11,"Sep 12-18","Mobile Web","Responsive UI overhaul",35,446),
            (2,"Product-Market Fit",12,"Sep 19-25","Speed","Redis caching, async queue, 2x faster",40,446),
            (2,"Product-Market Fit",13,"Sep 26-Oct 2","Niche Targeting","Creator-focused landing pages",50,893),
            (2,"Product-Market Fit",14,"Oct 3-9","Partnerships","50 micro-influencer affiliate deals",60,893),
            (2,"Product-Market Fit",15,"Oct 10-16","Self-Marketing v1","App generates own TikTok/IG ads",70,893),
            (2,"Product-Market Fit",16,"Oct 17-23","Iteration","A/B test pricing page",80,893),
            (3,"Growth Engine",17,"Oct 24-30","Paid Ads v1","$200 Meta ads, test 5 creatives",95,1786),
            (3,"Growth Engine",18,"Oct 31-Nov 6","Viral Loop","Watermark on free tier, share buttons",110,1786),
            (3,"Growth Engine",19,"Nov 7-13","DB Migration","SQLite -> PostgreSQL",130,1786),
            (3,"Growth Engine",20,"Nov 14-20","Workers","Celery + Redis async video gen",150,1786),
            (3,"Growth Engine",21,"Nov 21-27","Holiday Push","Black Friday 40% off annual",180,3571),
            (3,"Growth Engine",22,"Nov 28-Dec 4","API v1","Public API for Agency tier",210,3571),
            (3,"Growth Engine",23,"Dec 5-11","Multi-Region","Deploy to EU Frankfurt",250,3571),
            (3,"Growth Engine",24,"Dec 12-18","Team Features","Multi-seat Agency, shared workspace",300,3571),
            (3,"Growth Engine",25,"Dec 19-25","Year-End Push","New Year Content Kit",320,3571),
            (3,"Growth Engine",26,"Dec 26-Jan 1","Infra Hardening","Load testing, auto-scaling",320,3571),
            (4,"Scale",27,"Jan 2-8","Mobile App","React Native shell, auth, preview",400,7142),
            (4,"Scale",28,"Jan 9-15","Mobile Create","Video creation from phone",500,7142),
            (4,"Scale",29,"Jan 16-22","Mobile Publish","One-tap publish from phone",600,7142),
            (4,"Scale",30,"Jan 23-29","App Store","iOS + Android, ASO optimization",700,7142),
            (4,"Scale",31,"Jan 30-Feb 5","Ad Ramp","$2K/mo across Meta, Google, TikTok",850,14285),
            (4,"Scale",32,"Feb 6-12","Affiliates","20% recurring commission program",1000,14285),
            (4,"Scale",33,"Feb 13-19","Enterprise","SSO, custom branding, SLA",1100,14285),
            (4,"Scale",34,"Feb 20-26","Content Machine","50 YouTube tutorials, weekly blog",1280,14285),
            (4,"Scale",35,"Feb 27-Mar 5","Marketplace v1","Users sell templates (10% cut)",1500,28570),
            (4,"Scale",36,"Mar 6-12","AI Improvements","Better scripts, more styles, faster",1800,28570),
            (4,"Scale",37,"Mar 13-19","Localization","Spanish, Portuguese, French, German",2100,28570),
            (4,"Scale",38,"Mar 20-26","CRM Integration","HubSpot, Salesforce connectors",2400,28570),
            (4,"Scale",39,"Mar 27-Apr 2","Webinars","Weekly AI Video Masterclass",2580,57586),
            (4,"Scale",40,"Apr 3-9","Scaling Infra","Kubernetes, auto-scaling, global CDN",3000,57586),
            (5,"Hockey Stick",41,"Apr 10-16","Ad Spend $5K","Scale winning creatives",3500,57586),
            (5,"Hockey Stick",42,"Apr 17-23","TikTok Shop","Sell through TikTok marketplace",4000,57586),
            (5,"Hockey Stick",43,"Apr 24-30","White-Label v2","Agencies resell, rev share",4500,111600),
            (5,"Hockey Stick",44,"May 1-7","Conferences","VidCon, Creator Economy Expo",5000,111600),
            (5,"Hockey Stick",45,"May 8-14","Ad Spend $10K","Double down on best channels",6000,111600),
            (5,"Hockey Stick",46,"May 15-21","Self-Marketing v2","App optimizes own ad spend",7000,111600),
            (5,"Hockey Stick",47,"May 22-28","Partnerships","Canva, Notion, Shopify integrations",8000,223200),
            (5,"Hockey Stick",48,"May 29-Jun 4","Press/PR","TechCrunch, Product Hunt relaunch",9000,223200),
            (5,"Hockey Stick",49,"Jun 5-11","Series A Prep","Pitch deck, financial model",9500,223200),
            (5,"Hockey Stick",50,"Jun 12-18","Enterprise Push","2 outbound reps, Fortune 500",10000,223200),
            (5,"Hockey Stick",51,"Jun 19-25","Platform Stability","Security audit, SOC 2 prep",10000,223200),
            (5,"Hockey Stick",52,"Jun 26-Jul 2","YEAR ONE","Celebrate, retro, plan Year 2",10000,223200),
            (6,"Scale-Up",55,"Jul-Aug 2027","Growth Acceleration","Ambassador program, referral 2.0",15000,334800),
            (6,"Scale-Up",58,"Aug-Sep 2027","Channel Expansion","TikTok challenges, YT shorts, IG reels",22000,491040),
            (6,"Scale-Up",61,"Sep-Oct 2027","Enterprise v2","Dedicated sales, custom onboarding",32000,714240),
            (6,"Scale-Up",64,"Oct-Nov 2027","International v1","Spanish + Portuguese, LATAM partners",47000,1049040),
            (6,"Scale-Up",67,"Nov-Dec 2027","Platform Play","Marketplace, plugin ecosystem, dev API",68000,1517760),
            (6,"Scale-Up",70,"Dec 2027-Jan 2028","International v2","Japan, Korea, India launch",100000,2232000),
            (6,"Scale-Up",73,"Jan-Feb 2028","Scale Operations","SOC 2, enterprise SLAs, infra team",145000,3236400),
            (7,"Dominance",78,"Feb-Apr 2028","Market Leadership","Acquire competitors, Fortune 500",305000,6807600),
            (7,"Dominance",86,"Apr-May 2028","Category Ownership","Industry partnerships, standards",620000,13838400),
            (7,"Dominance",96,"May-Jul 2028","IPO Runway","$100M+ ARR, board, IPO prep",1000000,22320000),
        ]
        for m in milestones:
            conn.execute("""INSERT INTO business_plan_milestones
                (phase, phase_name, week_number, week_dates, focus, deliverables, target_users, target_mrr)
                VALUES (?,?,?,?,?,?,?,?)""", m)


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
            FROM users GROUP BY subscription_tier, subscription_status
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
            SELECT strftime('%Y-%m', created_at) as cohort_month,
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
            SELECT date(created_at) as day, COUNT(*) as signups
            FROM users WHERE created_at >= ?
            GROUP BY day ORDER BY day
        """, (thirty_ago,)).fetchall())

        # Conversion funnel
        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        starter = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_tier='starter' AND subscription_status='active'").fetchone()["c"]
        creator = conn.execute("SELECT COUNT(*) as c FROM users WHERE subscription_tier='creator' AND subscription_status='active'").fetchone()["c"]
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
            "free": total - starter - creator - agency,
            "starter": starter,
            "creator": creator,
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
            SELECT date(created_at) as day, COUNT(*) as videos,
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as completed
            FROM jobs WHERE created_at >= ?
            GROUP BY day ORDER BY day
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
            UPDATE monetizer_feature_flags SET enabled = NOT enabled, updated_at = ? WHERE id = ?
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
            SELECT COUNT(*) as c FROM users WHERE date(created_at) = ?
        """, (today,)).fetchone()["c"]

        total_videos = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status='done'").fetchone()["c"]
        total_credits = conn.execute("SELECT COALESCE(SUM(credits_used), 0) as c FROM users").fetchone()["c"]

        arpu = mrr / paying if paying else 0
        conversion = (paying / total * 100) if total else 0
        churn_rate = (churned / (churned + paying) * 100) if (churned + paying) else 0
        ltv = arpu / (churn_rate / 100) if churn_rate > 0 else arpu * 24

        conn.execute("""
            INSERT OR REPLACE INTO monetizer_kpi_snapshots
            (snapshot_date, mrr, arr, total_users, paying_users, free_users,
             churned_users, new_signups, total_videos, total_credits_used,
             avg_revenue_per_user, conversion_rate, churn_rate, ltv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            SELECT * FROM monetizer_alerts ORDER BY acknowledged, created_at DESC LIMIT 50
        """).fetchall())
    return jsonify({"alerts": alerts})


@monetizer_bp.route("/api/alerts/<int:alert_id>/ack", methods=["POST"])
@login_required
@owner_required
def ack_alert(alert_id):
    with _conn() as conn:
        conn.execute("UPDATE monetizer_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    return jsonify({"ok": True})


def create_alert(alert_type, message, severity="warning", metric_name=None, metric_value=None, threshold=None):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO monetizer_alerts (alert_type, severity, message, metric_name, metric_value, threshold)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (alert_type, severity, message, metric_name, metric_value, threshold))


# ═══════════════════════════════════════════════════════════════════════════════
# 12. SYSTEM HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@monetizer_bp.route("/api/system/health")
@login_required
@owner_required
def system_health():
    import shutil

    db_path = Path(db.DB_PATH)
    db_size = db_path.stat().st_size if db_path.exists() else 0

    output_dir = config.OUTPUT_DIR
    output_size = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file()) if output_dir.exists() else 0

    disk = shutil.disk_usage("/")

    with _conn() as conn:
        stuck_jobs = conn.execute("""
            SELECT COUNT(*) as c FROM jobs
            WHERE status IN ('pending', 'running')
            AND datetime(created_at) < datetime('now', '-1 hour')
        """).fetchone()["c"]

        error_jobs_24h = conn.execute("""
            SELECT COUNT(*) as c FROM jobs
            WHERE status = 'error'
            AND datetime(created_at) > datetime('now', '-1 day')
        """).fetchone()["c"]

        total_jobs_24h = conn.execute("""
            SELECT COUNT(*) as c FROM jobs
            WHERE datetime(created_at) > datetime('now', '-1 day')
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
        "database_size_mb": round(db_size / 1024 / 1024, 2),
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
            WHERE subscription_status = 'active' GROUP BY subscription_tier
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
                writer.writerow(list(r))
        elif report_type == "revenue":
            writer.writerow(["ID", "User ID", "Event", "Amount", "Tier", "Date"])
            for r in conn.execute("SELECT id, user_id, event_type, amount, tier, created_at FROM monetizer_revenue_log ORDER BY created_at DESC").fetchall():
                writer.writerow(list(r))
        elif report_type == "kpi":
            writer.writerow(["Date", "MRR", "ARR", "Total Users", "Paying", "Free", "Churned", "Conv Rate", "Churn Rate", "LTV"])
            for r in conn.execute("SELECT snapshot_date, mrr, arr, total_users, paying_users, free_users, churned_users, conversion_rate, churn_rate, ltv FROM monetizer_kpi_snapshots ORDER BY snapshot_date DESC").fetchall():
                writer.writerow(list(r))
        elif report_type == "jobs":
            writer.writerow(["ID", "User ID", "Topic", "Type", "Status", "Created"])
            for r in conn.execute("SELECT id, user_id, topic, content_type, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 1000").fetchall():
                writer.writerow(list(r))
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
        "avatar": "M", "color": "#7c3aed",
        "status": "active", "interval": "14 hrs"
    },
    "elena_rostova": {
        "name": "Elena Rostova", "title": "VP of Enterprise Development",
        "role": "B2B Sales Automation, Enterprise Lead Scraping, Intent Detection",
        "avatar": "E", "color": "#2563eb",
        "status": "active", "interval": "14 hrs"
    },
    "julian_vance": {
        "name": "Dr. Julian Vance", "title": "Director of Retention & LTV",
        "role": "Churn Mitigation, Predictive Analytics, User Engagement",
        "avatar": "J", "color": "#059669",
        "status": "active", "interval": "14 hrs"
    },
    "sterling_croft": {
        "name": "Sterling Croft", "title": "Chief Business Officer",
        "role": "Unit Economics, Strategic Partnerships, Pricing Models",
        "avatar": "S", "color": "#d97706",
        "status": "active", "interval": "14 hrs"
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
    return jsonify({"error": "Unknown agent"}), 400


# ═══════════════════════════════════════════════════════════════════════════════
# BUSINESS PLAN — Progress Tracking
# ═══════════════════════════════════════════════════════════════════════════════

PLAN_TARGETS = {
    "launch_date": "2026-07-04",
    "target_arr": 10_000_000,
    "target_users": 1_000_000,
    "gross_margin_target": 92,
    "arpu_target": 74.40,
    "ltv_target": 595,
    "cac_target": 20,
    "breakeven_month": 3,
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
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL"
        ).fetchone()[0]

        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}
        mrr = 0
        for row in conn.execute("SELECT subscription_tier, COUNT(*) as cnt FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL AND subscription_status='active' GROUP BY subscription_tier").fetchall():
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
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL"
        ).fetchone()[0]
        tier_prices = {k: v["price_monthly"] for k, v in config.TIERS.items()}
        mrr = 0
        for row in conn.execute("SELECT subscription_tier, COUNT(*) as cnt FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL AND subscription_status='active' GROUP BY subscription_tier").fetchall():
            mrr += row["cnt"] * tier_prices.get(row["subscription_tier"], 0)

        sets.extend(["actual_users=?", "actual_mrr=?"])
        vals.extend([total_users, round(mrr, 2)])
        vals.append(milestone_id)
        conn.execute(f"UPDATE business_plan_milestones SET {','.join(sets)} WHERE id=?", vals)
    return jsonify({"ok": True})
