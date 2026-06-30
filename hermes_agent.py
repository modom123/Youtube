"""
Hermes — in-app onboarding assistant.

A chat widget available on every Command Center page. Hermes answers
account/setup questions and can take action directly via tool-calling
against this app's own routes (connect a platform, check status, etc.)
instead of trying to puppet third-party dashboards.
"""
from __future__ import annotations
import json
import logging

import anthropic
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

import config
import database as db

log = logging.getLogger(__name__)

hermes_bp = Blueprint("hermes", __name__)

_client: anthropic.Anthropic | None = None
_MODEL = "claude-sonnet-4-6"

_PLATFORMS = ["youtube", "tiktok", "facebook", "instagram", "linkedin",
              "twitter", "threads", "twitch", "snapchat"]


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ── Tools ─────────────────────────────────────────────────────────────────

_TOOLS = [
    {
        "name": "get_account_status",
        "description": (
            "Get the current user's account overview: subscription tier, "
            "usage this period, and which social platforms are connected "
            "vs. not connected. Call this first whenever the user asks "
            "about their setup, what's missing, or seems stuck."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_platform_connect_link",
        "description": (
            "Get the URL the user should click to connect or reconnect a "
            "social platform account via OAuth. Use this when the user "
            "wants to connect a platform or fix a broken connection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": _PLATFORMS,
                    "description": "Which platform to connect.",
                }
            },
            "required": ["platform"],
        },
    },
    {
        "name": "get_recent_errors",
        "description": (
            "Get the user's most recent failed/errored jobs, so Hermes can "
            "explain what went wrong and how to fix it."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "highlight_element",
        "description": (
            "Point at a specific button, field, or section on the CURRENT "
            "Social Optimize page the user is looking at, by drawing a "
            "glowing outline around it. Use this for 'DIY' walkthroughs — "
            "when you've told the user what to click, also call this so "
            "they can see exactly where it is. selector must be a valid "
            "CSS selector that exists on Social Optimize pages (e.g. "
            "'#hermesBubble', 'a[href=\"/billing\"]', '.connect-btn')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to highlight.",
                },
                "message": {
                    "type": "string",
                    "description": "Short label shown next to the highlight, e.g. 'Click here to connect YouTube'.",
                },
            },
            "required": ["selector", "message"],
        },
    },
    {
        "name": "request_external_fix",
        "description": (
            "Use this when solving the user's problem requires logging into "
            "and clicking around on a THIRD-PARTY dashboard outside Social "
            "Optimize (Supabase, Render, Stripe, Google Cloud, etc.) — "
            "something Hermes cannot do itself because it would require the "
            "user's external login session. Instead, this hands the precise "
            "task off to 'Hermes Companion', a small script the user runs on "
            "their own computer, which drives their own already-logged-in "
            "Chrome browser to do exactly the task you describe and report "
            "back the result. Write `task` as clear, step-by-step "
            "instructions a browser-automation agent can follow on that "
            "dashboard (which page to go to, what to click, what to copy)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Precise step-by-step instructions for the external dashboard task.",
                }
            },
            "required": ["task"],
        },
    },
]


def _tool_get_account_status(user_id: int) -> dict:
    user = db.get_user_by_id(user_id) or {}
    accounts = db.get_accounts(user_id=user_id) or []
    connected = {a["platform"] for a in accounts if a.get("is_active")}
    tier = config.TIERS.get(user.get("subscription_tier", "free"), {})
    return {
        "subscription_tier": user.get("subscription_tier", "free"),
        "videos_used_this_month": user.get("videos_used_this_month", 0),
        "tier_limits": tier,
        "connected_platforms": sorted(connected),
        "not_connected_platforms": sorted(set(_PLATFORMS) - connected),
    }


def _tool_get_platform_connect_link(platform: str) -> dict:
    platform = (platform or "").lower().strip()
    if platform not in _PLATFORMS:
        return {"error": f"Unknown platform '{platform}'."}
    # OAuth start routes are registered directly on app.py as
    # /oauth/<platform>/start — build the path directly rather than
    # depending on Flask endpoint naming, which isn't consistent
    # across platforms (e.g. instagram has no dedicated callback).
    return {"connect_url": f"/oauth/{platform}/start"}


def _tool_highlight_element(selector: str, message: str) -> dict:
    return {"selector": selector, "message": message, "status": "ok"}


def _tool_request_external_fix(task: str) -> dict:
    return {
        "mode": "hermes_companion",
        "task": task,
        "instructions": (
            "This needs to happen on an external dashboard, so I can't do it "
            "from inside Social Optimize. Run Hermes Companion on your own "
            "computer — it drives your own already-logged-in Chrome, never "
            "our servers. Steps:\n"
            "1. Close Chrome, then reopen it with remote debugging enabled "
            "(see the comment at the top of scripts/hermes_companion.py for "
            "the exact command for your OS).\n"
            "2. Log into the dashboard you need in that Chrome window.\n"
            "3. Run: python scripts/hermes_companion.py --task \"" + task.replace('"', "'") + "\"\n"
            "It will narrate what it's doing and print the result when done."
        ),
    }


def _tool_get_recent_errors(user_id: int) -> dict:
    jobs = db.get_jobs(limit=50, user_id=user_id) or []
    failed = [j for j in jobs if j.get("status") == "failed"][:5]
    return {
        "failed_jobs": [
            {
                "id": j.get("id"),
                "type": j.get("job_type") or j.get("type"),
                "error": j.get("error") or j.get("error_message"),
                "created_at": str(j.get("created_at")),
            }
            for j in failed
        ]
    }


_TOOL_IMPLS = {
    "get_account_status": _tool_get_account_status,
    "get_platform_connect_link": _tool_get_platform_connect_link,
    "get_recent_errors": _tool_get_recent_errors,
    "highlight_element": _tool_highlight_element,
    "request_external_fix": _tool_request_external_fix,
}


_SYSTEM_PROMPT = """You are Hermes, the onboarding assistant inside Social Optimize (a social media \
automation platform). You help users who are stuck during signup or setup — connecting \
social accounts, understanding their plan, or diagnosing failed jobs.

Be concise and direct. Use your tools to check real account state before answering — \
never guess at what's connected or what plan the user is on. When the user needs to \
connect a platform, give them the connect link from get_platform_connect_link and tell \
them what to expect (a permission screen on that platform's site).

When you tell the user to click something on the CURRENT Social Optimize page, also call \
highlight_element so they can see exactly where it is — don't just describe it in words.

If the fix requires logging into an external dashboard (Supabase, Render, Stripe, Google \
Cloud, etc.) that Social Optimize itself doesn't control, call request_external_fix with \
precise step-by-step instructions for that dashboard. Never ask the user for passwords or \
API keys directly in chat.

If something needs a human (billing dispute, refund, a bug you can't diagnose), say so \
plainly and tell the user to use the support contact rather than inventing a fix."""


def _run_agent(user_id: int, messages: list[dict]) -> tuple[str, list[dict]]:
    client = _get_client()
    actions: list[dict] = []

    for _ in range(6):  # bounded tool-use loop
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks).strip(), actions

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            impl = _TOOL_IMPLS.get(block.name)
            if impl is None:
                result = {"error": f"Unknown tool '{block.name}'"}
            else:
                kwargs = dict(block.input or {})
                if block.name in ("get_account_status", "get_recent_errors"):
                    kwargs["user_id"] = user_id
                try:
                    result = impl(**kwargs)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Hermes tool %s failed", block.name)
                    result = {"error": str(exc)}
            if block.name in ("highlight_element", "request_external_fix") and "error" not in result:
                actions.append({"type": block.name, **result})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })
        messages.append({"role": "user", "content": tool_results})

    return "I'm having trouble finishing that — please try rephrasing, or reach out to support.", actions


@hermes_bp.route("/api/hermes/chat", methods=["POST"])
@login_required
def hermes_chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not user_message:
        return jsonify({"error": "message is required"}), 400
    if not config.ANTHROPIC_API_KEY:
        return jsonify({"error": "Hermes is not configured yet — missing API key."}), 503

    messages = []
    for turn in history[-10:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    try:
        reply, actions = _run_agent(current_user.id, messages)
    except Exception as exc:  # noqa: BLE001
        log.exception("Hermes chat failed")
        return jsonify({"error": "Hermes hit an error — please try again."}), 500

    return jsonify({"reply": reply, "actions": actions})
