"""
Agent Dispatch System — Wires the 10-agent operational framework into every pipeline.

This module is the central nervous system that connects:
  - Website (content creation, dashboard, media library)
  - Command Center (admin, orchestration, cost routing, QA)
  - Social Optimize (content generation, platform optimization)
  - Mobile App (notifications, push alerts, mobile bridge)

Every operation flows through the relevant agents, creating real activity logs
and tracking tasks across the system.
"""
import threading
import time
from datetime import datetime

import database as db

_lock = threading.Lock()

# Maps agent IDs to the subsystems they serve
AGENT_PIPELINES = {
    "content_create": [
        ("agent-showrunner", "Dispatching content creation job"),
        ("agent-scout", "Scanning trends and research data"),
        ("agent-ledger", "Routing to optimal AI model tier"),
        ("client-trend-architect", "Researching topic and viral angles for client"),
        ("client-narrative-designer", "Writing optimized script for client"),
        ("client-asset-curator", "Sourcing visual and audio assets"),
        ("client-cost-engineer", "Optimizing client's production budget"),
        ("client-producer", "Assembling final video package"),
        ("client-growth-engineer", "Optimizing metadata for platform reach"),
        ("agent-editor", "Running compliance and quality checks"),
        ("agent-growth-engine", "Final platform optimization pass"),
    ],
    "studio_production": [
        ("agent-showrunner", "Orchestrating 5-agent studio pipeline"),
        ("agent-scout", "Feeding trend data to pipeline"),
        ("agent-ledger", "Cost-optimizing multi-model routing"),
        ("client-trend-architect", "Analyzing niche trends for client"),
        ("client-narrative-designer", "Designing narrative structure"),
        ("client-asset-curator", "Curating production assets"),
        ("client-cost-engineer", "Routing to cost-efficient models"),
        ("client-producer", "Rendering final production"),
        ("client-growth-engineer", "Platform-specific SEO optimization"),
        ("agent-ghost", "Preparing anti-detect publishing layer"),
        ("agent-editor", "Final QA before delivery"),
        ("agent-growth-engine", "Multi-platform optimization pass"),
    ],
    "scheduled_publish": [
        ("agent-showrunner", "Executing scheduled publish"),
        ("agent-ghost", "Applying fingerprint randomization"),
        ("agent-editor", "Pre-publish compliance check"),
        ("agent-growth-engine", "Injecting platform-optimized metadata"),
    ],
    "engagement_action": [
        ("agent-showrunner", "Dispatching engagement action"),
        ("agent-ghost", "Applying anti-detect shield"),
        ("agent-editor", "Checking ToS compliance"),
    ],
    "trend_scan": [
        ("agent-scout", "Running real-time trend scan"),
        ("agent-growth-engine", "Analyzing viral potential"),
    ],
    "competitor_refresh": [
        ("agent-scout", "Refreshing competitor intelligence"),
        ("agent-growth-engine", "Benchmarking performance metrics"),
    ],
    "media_upload": [
        ("agent-conduit", "Processing inbound media asset"),
        ("agent-architect", "Updating media library UI state"),
    ],
    "user_signup": [
        ("agent-conduit", "Provisioning new user account"),
        ("agent-architect", "Initializing dashboard workspace"),
        ("agent-courier", "Queuing welcome notification"),
    ],
    "mobile_notification": [
        ("agent-courier", "Formatting push notification"),
        ("agent-native", "Delivering to mobile client"),
    ],
    "website_update": [
        ("agent-architect", "Rendering UI update"),
        ("agent-conduit", "Syncing state to frontend"),
    ],
    "spintax_process": [
        ("agent-ghost", "Processing spintax content mutation"),
    ],
    "cost_routing": [
        ("agent-ledger", "Evaluating model tier for request"),
    ],
}


def dispatch(pipeline_name: str, context: dict = None):
    """
    Run a task through the named agent pipeline.
    Logs activity for each agent and increments task counters.
    Returns list of agent IDs that were activated.
    """
    agents = AGENT_PIPELINES.get(pipeline_name, [])
    if not agents:
        return []

    activated = []
    ctx = context or {}
    summary = ctx.get("summary", "")
    user_id = ctx.get("user_id")
    job_id = ctx.get("job_id")

    detail_base = {
        "pipeline": pipeline_name,
        "user_id": user_id,
        "job_id": job_id,
    }

    for agent_id, default_msg in agents:
        try:
            msg = f"{default_msg}"
            if summary:
                msg += f" — {summary[:120]}"

            db.add_agent_log(
                agent_id,
                event_type="task_executed",
                message=msg,
                details={**detail_base, **{k: str(v)[:200] for k, v in ctx.items() if k not in ("summary",)}},
            )

            with _lock:
                agent = db.get_agent(agent_id)
                if agent:
                    db.update_agent(
                        agent_id,
                        tasks_completed=(agent.get("tasks_completed") or 0) + 1,
                    )
            activated.append(agent_id)
        except Exception:
            try:
                db.add_agent_log(agent_id, "error", f"Failed during pipeline: {pipeline_name}")
                agent = db.get_agent(agent_id)
                if agent:
                    db.update_agent(
                        agent_id,
                        tasks_failed=(agent.get("tasks_failed") or 0) + 1,
                    )
            except Exception:
                pass

    return activated


def dispatch_async(pipeline_name: str, context: dict = None):
    """Fire-and-forget dispatch in a background thread."""
    t = threading.Thread(
        target=dispatch,
        args=(pipeline_name, context),
        daemon=True,
    )
    t.start()
    return t


def get_system_status() -> dict:
    """
    Returns real-time status of all four system pillars and their interconnections.
    """
    agents = db.get_agents()
    stats = db.get_agent_stats()

    def _team_status(team_key):
        team_agents = [a for a in agents if a["team"] == team_key]
        online = sum(1 for a in team_agents if a["status"] == "online")
        total = len(team_agents)
        total_tasks = sum(a.get("tasks_completed") or 0 for a in team_agents)
        total_failed = sum(a.get("tasks_failed") or 0 for a in team_agents)
        health = "healthy" if online == total else "degraded" if online > 0 else "offline"
        return {
            "agents": [{
                "id": a["id"],
                "codename": a["codename"],
                "title": a["title"],
                "status": a["status"],
                "tasks_completed": a.get("tasks_completed") or 0,
                "tasks_failed": a.get("tasks_failed") or 0,
                "last_active": a.get("last_active"),
            } for a in team_agents],
            "online": online,
            "total": total,
            "tasks_completed": total_tasks,
            "tasks_failed": total_failed,
            "health": health,
        }

    # Build connection map showing how all systems interconnect
    connections = [
        {"from": "website", "to": "command_center", "label": "API Pipeline", "agent": "The Conduit", "status": "active"},
        {"from": "command_center", "to": "client_pipeline", "label": "Job Dispatch", "agent": "The Showrunner", "status": "active"},
        {"from": "client_pipeline", "to": "social_optimize", "label": "Content Output", "agent": "The Growth Engine", "status": "active"},
        {"from": "social_optimize", "to": "command_center", "label": "Platform Results", "agent": "The Growth Engine", "status": "active"},
        {"from": "command_center", "to": "mobile", "label": "Push Notifications", "agent": "The Courier", "status": "active"},
        {"from": "website", "to": "mobile", "label": "WebView Bridge", "agent": "The Native", "status": "active"},
        {"from": "command_center", "to": "website", "label": "Real-Time Dashboard", "agent": "The Architect", "status": "active"},
        {"from": "client_pipeline", "to": "command_center", "label": "Cost & QA Reports", "agent": "Cost Engineer", "status": "active"},
    ]

    for conn in connections:
        agent_name = conn["agent"]
        for a in agents:
            if a["codename"] == agent_name:
                conn["status"] = "active" if a["status"] == "online" else "degraded"
                break

    return {
        "pillars": {
            "command_center": _team_status("command_center"),
            "website": _team_status("website"),
            "mobile": _team_status("mobile"),
            "social_optimize": _team_status("social_optimize"),
            "client_pipeline": _team_status("client_pipeline"),
        },
        "connections": connections,
        "global_stats": stats,
    }
