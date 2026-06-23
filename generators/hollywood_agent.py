"""
Hollywood — AI Agent for Social Optimize Machine
Interfaces with Studio 56, manages deployment config, browser automation,
research, content scheduling, analytics and more.
"""
import json
import os
import secrets
import requests
import anthropic
import config
import database as db

HOLLYWOOD_PERSONA = """You are Hollywood, the AI production agent for Social Optimize Machine's Studio 56.
You are confident, creative, and speak like a seasoned Hollywood producer.
You help users create viral content, manage their social media pipeline, keep the system running smoothly,
and can browse the web in real time to research trends, competitors, and anything else needed.
You have direct access to Studio 56 (the content generation studio) and can create content, check job status,
list recent work, configure the deployment, take screenshots of websites, fill out forms, and more.
Be concise, punchy, and results-oriented. Use occasional Hollywood flair but keep it professional."""

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    # ── Original 7 tools ──────────────────────────────────────────────────────
    {
        "name": "create_content",
        "description": "Create a new content job in Studio 56. Kicks off the production pipeline for a given topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The topic or niche for the content piece"},
                "format": {
                    "type": "string",
                    "description": "Content format: 'short', 'long', 'podcast', or 'commercial'",
                    "enum": ["short", "long", "podcast", "commercial"],
                    "default": "short"
                },
                "platforms": {
                    "type": "array", "items": {"type": "string"},
                    "description": "List of platforms to publish to, e.g. ['youtube', 'tiktok', 'instagram']"
                },
                "audience": {"type": "string", "description": "Target audience description", "default": "general public"}
            },
            "required": ["topic", "platforms"]
        }
    },
    {
        "name": "get_job_status",
        "description": "Get the current status, title, format and creation time of a specific job by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "The numeric job ID to look up"}},
            "required": ["job_id"]
        }
    },
    {
        "name": "list_recent_jobs",
        "description": "List the most recent content jobs with their statuses.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Number of jobs to return (default 5)", "default": 5}}
        }
    },
    {
        "name": "check_render_config",
        "description": "Check which environment variables are set vs missing on a Render service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "render_api_key": {"type": "string", "description": "Render API key (Bearer token)"},
                "service_id": {"type": "string", "description": "Render service ID (e.g. srv-xxxxx)"}
            },
            "required": ["render_api_key", "service_id"]
        }
    },
    {
        "name": "set_render_env_vars",
        "description": "Set environment variables on a Render service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "render_api_key": {"type": "string", "description": "Render API key (Bearer token)"},
                "service_id": {"type": "string", "description": "Render service ID (e.g. srv-xxxxx)"},
                "env_vars": {"type": "object", "description": "Dictionary of env var key-value pairs", "additionalProperties": {"type": "string"}}
            },
            "required": ["render_api_key", "service_id", "env_vars"]
        }
    },
    {
        "name": "generate_secret_key",
        "description": "Generate a cryptographically secure random 64-character hex SECRET_KEY for Flask.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_all_required_env_vars",
        "description": "Get the full list of required environment variables and which ones are currently missing or set.",
        "input_schema": {"type": "object", "properties": {}}
    },

    # ── Browser Tools ─────────────────────────────────────────────────────────
    {
        "name": "browser_navigate",
        "description": "Navigate the browser to a URL and return the page title and URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The URL to navigate to"}},
            "required": ["url"]
        }
    },
    {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the current browser page. Returns base64-encoded PNG image and file path.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "browser_click",
        "description": "Click an element on the current page by CSS selector or visible text.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "CSS selector or visible text of element to click"}},
            "required": ["selector"]
        }
    },
    {
        "name": "browser_type",
        "description": "Type text into an input field on the current page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of the input field"},
                "text": {"type": "string", "description": "Text to type into the field"}
            },
            "required": ["selector", "text"]
        }
    },
    {
        "name": "browser_get_text",
        "description": "Get the visible text content of the current browser page (max 4000 chars).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the current page up or down.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "Scroll direction: 'up' or 'down'", "enum": ["up", "down"], "default": "down"},
                "amount": {"type": "integer", "description": "Pixels to scroll (default 500)", "default": 500}
            }
        }
    },
    {
        "name": "browser_fill_form",
        "description": "Fill multiple form fields at once on the current page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": "Object mapping CSS selector to value: {\"#username\": \"myuser\", \"#password\": \"pass\"}",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["fields"]
        }
    },
    {
        "name": "browser_press_key",
        "description": "Press a keyboard key in the browser (Enter, Tab, Escape, ArrowDown, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "Key name to press (e.g. 'Enter', 'Tab', 'Escape')"}},
            "required": ["key"]
        }
    },

    # ── Research & Trends Tools ───────────────────────────────────────────────
    {
        "name": "search_trends",
        "description": "Get trending topics for a niche using Google Trends via browser navigation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "niche": {"type": "string", "description": "The niche or keyword to search trends for"},
                "region": {"type": "string", "description": "Region code e.g. 'US', 'GB' (default: US)", "default": "US"}
            },
            "required": ["niche"]
        }
    },
    {
        "name": "analyze_competitor",
        "description": "Navigate to a YouTube or TikTok channel URL and extract video titles, views, upload frequency.",
        "input_schema": {
            "type": "object",
            "properties": {"channel_url": {"type": "string", "description": "YouTube or TikTok channel URL"}},
            "required": ["channel_url"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo and return top results (titles, URLs, snippets).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"]
        }
    },
    {
        "name": "get_platform_stats",
        "description": "Navigate to a social platform analytics page and scrape stats (user must be logged in).",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "Platform to check: 'youtube', 'tiktok', 'instagram'",
                    "enum": ["youtube", "tiktok", "instagram"]
                }
            },
            "required": ["platform"]
        }
    },

    # ── Content Management Tools ──────────────────────────────────────────────
    {
        "name": "schedule_content",
        "description": "Schedule a content job for publishing at a specific time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "Job ID to schedule"},
                "publish_at": {"type": "string", "description": "ISO 8601 datetime for publishing, e.g. '2025-02-01T15:00:00'"},
                "platforms": {"type": "array", "items": {"type": "string"}, "description": "Platforms to publish to"}
            },
            "required": ["job_id", "publish_at"]
        }
    },
    {
        "name": "list_scheduled",
        "description": "List all scheduled content posts.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "cancel_scheduled",
        "description": "Cancel a scheduled post by its schedule ID.",
        "input_schema": {
            "type": "object",
            "properties": {"schedule_id": {"type": "integer", "description": "The schedule ID to cancel"}},
            "required": ["schedule_id"]
        }
    },
    {
        "name": "bulk_create",
        "description": "Create multiple content jobs at once from a list of topics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}, "description": "List of topics to create jobs for"},
                "format": {"type": "string", "description": "Content format for all jobs", "enum": ["short", "long", "podcast", "commercial"], "default": "short"},
                "platforms": {"type": "array", "items": {"type": "string"}, "description": "Platforms for all jobs"}
            },
            "required": ["topics", "platforms"]
        }
    },

    # ── File & Output Tools ───────────────────────────────────────────────────
    {
        "name": "list_output_files",
        "description": "List all generated videos, thumbnails and scripts in the output directory.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max files to list (default 20)", "default": 20}}
        }
    },
    {
        "name": "get_job_files",
        "description": "Get all output files for a specific job (video path, script path, thumbnail path).",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "Job ID to look up files for"}},
            "required": ["job_id"]
        }
    },
    {
        "name": "download_info",
        "description": "Return the download URL for a job's output video file.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "Job ID to get download link for"}},
            "required": ["job_id"]
        }
    },

    # ── System & Health Tools ─────────────────────────────────────────────────
    {
        "name": "system_health",
        "description": "Check health of all services: Claude API, Pexels, Higgsfield, platform connections.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "platform_connections",
        "description": "List all connected social accounts and their OAuth status.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "restart_scheduler",
        "description": "Restart the background content scheduler.",
        "input_schema": {"type": "object", "properties": {}}
    },

    # ── Analytics Tools ───────────────────────────────────────────────────────
    {
        "name": "get_analytics_summary",
        "description": "Get total jobs created, completion rate, top performing topics and revenue estimate.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_trending_niches",
        "description": "Return top trending niches based on recent job performance and web trends.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "content_calendar_view",
        "description": "Return the next 7 days of scheduled content as a calendar.",
        "input_schema": {"type": "object", "properties": {}}
    },
]


# ── Helper: browser wrapper ────────────────────────────────────────────────────

def _browser_call(fn_name: str, **kwargs):
    """Call a function in hollywood_browser, gracefully handling missing Playwright."""
    try:
        from generators import hollywood_browser as hb
        fn = getattr(hb, fn_name)
        return fn(**kwargs)
    except ImportError:
        return {"error": "Browser not available — run: playwright install chromium"}
    except Exception as e:
        return {"error": f"Browser error: {str(e)}"}


# ── Original tool implementations ──────────────────────────────────────────────

def _tool_create_content(topic: str, format: str = "short", platforms: list = None, audience: str = "general public") -> dict:
    if platforms is None:
        platforms = []
    try:
        import threading
        from generators.production_engine import run_production_pipeline
        job_id = db.create_job(
            title=f"Hollywood: {topic}",
            niche=topic,
            format=format,
            platforms=json.dumps(platforms),
            status="queued",
            user_id=None
        )
        params = {
            "niche": topic,
            "audience": audience,
            "format": format,
            "platforms": platforms,
            "is_portrait": format == "short",
            "target_duration": 55 if format == "short" else 480,
            "voice": config.DEFAULT_VOICE,
            "thumbnail_style": "fire",
            "privacy": "private",
            "dry_run": True,
            "research_enabled": True,
            "competitor_titles": [],
            "remaining_credits": 500,
            "monthly_budget": 500,
        }
        def _bg():
            try:
                run_production_pipeline(job_id=job_id, **params)
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()
        return {"job_id": job_id, "status": "queued", "topic": topic, "format": format, "platforms": platforms}
    except Exception as e:
        return {"error": str(e), "topic": topic}


def _tool_get_job_status(job_id: int) -> dict:
    try:
        job = db.get_job(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        return {
            "job_id": job_id,
            "status": job.get("status"),
            "title": job.get("title"),
            "format": job.get("format"),
            "created_at": job.get("created_at"),
            "progress": job.get("progress", 0),
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_list_recent_jobs(limit: int = 5) -> dict:
    try:
        jobs = db.get_jobs(limit=limit)
        result = []
        for j in (jobs or []):
            result.append({
                "job_id": j.get("id"),
                "title": j.get("title"),
                "status": j.get("status"),
                "format": j.get("format"),
                "created_at": j.get("created_at"),
            })
        return {"jobs": result, "count": len(result)}
    except Exception as e:
        return {"error": str(e)}


def _tool_check_render_config(render_api_key: str, service_id: str) -> dict:
    try:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars"
        headers = {"Authorization": f"Bearer {render_api_key}", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 401:
            return {"error": "Invalid Render API key"}
        if resp.status_code == 404:
            return {"error": f"Service {service_id} not found"}
        resp.raise_for_status()
        result = {}
        for item in resp.json():
            ev = item.get("envVar") or item
            key = ev.get("key", "")
            value = ev.get("value", "")
            result[key] = "set" if value else "empty"
        return {"env_vars": result, "total": len(result)}
    except requests.RequestException as e:
        return {"error": f"Render API request failed: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


def _tool_set_render_env_vars(render_api_key: str, service_id: str, env_vars: dict) -> dict:
    try:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars"
        headers = {
            "Authorization": f"Bearer {render_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        body = [{"key": k, "value": v} for k, v in env_vars.items()]
        resp = requests.put(url, headers=headers, json=body, timeout=15)
        if resp.status_code == 401:
            return {"error": "Invalid Render API key"}
        if resp.status_code == 404:
            return {"error": f"Service {service_id} not found"}
        resp.raise_for_status()
        return {"success": True, "vars_set": list(env_vars.keys()), "count": len(env_vars)}
    except requests.RequestException as e:
        return {"error": f"Render API request failed: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


def _tool_generate_secret_key() -> dict:
    key = secrets.token_hex(32)
    return {"secret_key": key, "length": len(key)}


def _tool_get_all_required_env_vars() -> dict:
    required_vars = {
        "ANTHROPIC_API_KEY": {"current": "set" if config.ANTHROPIC_API_KEY else "missing", "description": "Claude AI API key"},
        "PEXELS_API_KEY": {"current": "set" if config.PEXELS_API_KEY else "missing", "description": "Pexels stock media API key"},
        "STRIPE_SECRET_KEY": {"current": "set" if config.STRIPE_SECRET_KEY else "missing", "description": "Stripe secret key"},
        "STRIPE_PUBLISHABLE_KEY": {"current": "set" if config.STRIPE_PUBLISHABLE_KEY else "missing", "description": "Stripe publishable key"},
        "STRIPE_WEBHOOK_SECRET": {"current": "set" if config.STRIPE_WEBHOOK_SECRET else "missing", "description": "Stripe webhook secret"},
        "SECRET_KEY": {"current": "set" if os.getenv("SECRET_KEY") else "missing", "description": "Flask secret key"},
        "HIGGSFIELD_MCP_TOKEN": {"current": "set" if config.HIGGSFIELD_MCP_TOKEN else "missing", "description": "Higgsfield AI token"},
        "GOOGLE_API_KEY": {"current": "set" if config.GOOGLE_API_KEY else "missing", "description": "Google API key"},
        "YOUTUBE_CLIENT_ID": {"current": "set" if config.YOUTUBE_CLIENT_ID else "missing", "description": "YouTube OAuth client ID"},
        "YOUTUBE_CLIENT_SECRET": {"current": "set" if config.YOUTUBE_CLIENT_SECRET else "missing", "description": "YouTube OAuth client secret"},
    }
    missing = [k for k, v in required_vars.items() if v["current"] == "missing"]
    return {"vars": required_vars, "missing_count": len(missing), "missing_vars": missing, "set_count": len(required_vars) - len(missing)}


# ── Browser tool implementations ───────────────────────────────────────────────

def _tool_browser_navigate(url: str) -> dict:
    return _browser_call("navigate", url=url)


def _tool_browser_screenshot() -> dict:
    return _browser_call("screenshot")


def _tool_browser_click(selector: str) -> dict:
    return _browser_call("click", selector=selector)


def _tool_browser_type(selector: str, text: str) -> dict:
    return _browser_call("type_text", selector=selector, text=text)


def _tool_browser_get_text() -> dict:
    return _browser_call("get_page_text")


def _tool_browser_scroll(direction: str = "down", amount: int = 500) -> dict:
    return _browser_call("scroll", direction=direction, amount=amount)


def _tool_browser_fill_form(fields: dict) -> dict:
    return _browser_call("fill_form", fields=fields)


def _tool_browser_press_key(key: str) -> dict:
    return _browser_call("press_key", key=key)


# ── Research & Trends tool implementations ─────────────────────────────────────

def _tool_search_trends(niche: str, region: str = "US") -> dict:
    try:
        import urllib.parse
        query = urllib.parse.quote_plus(niche)
        url = f"https://trends.google.com/trends/explore?q={query}&geo={region}"
        nav = _browser_call("navigate", url=url)
        if "error" in nav:
            return nav
        import time; time.sleep(2)
        text = _browser_call("get_page_text")
        return {
            "niche": niche,
            "region": region,
            "trends_url": url,
            "page_text": text.get("text", "")[:2000],
            "note": "Navigate to trends_url in browser for full interactive chart"
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_analyze_competitor(channel_url: str) -> dict:
    try:
        nav = _browser_call("navigate", url=channel_url)
        if "error" in nav:
            return nav
        import time; time.sleep(2)
        text = _browser_call("get_page_text")
        links = _browser_call("extract_links")
        return {
            "channel_url": channel_url,
            "page_title": nav.get("title", ""),
            "page_text_sample": text.get("text", "")[:2000],
            "links_found": len(links.get("links", [])),
            "sample_links": links.get("links", [])[:20]
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_web_search(query: str) -> dict:
    try:
        import urllib.parse
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html?q={encoded}"
        nav = _browser_call("navigate", url=url)
        if "error" in nav:
            return nav
        links = _browser_call("extract_links")
        text = _browser_call("get_page_text")
        return {
            "query": query,
            "results_text": text.get("text", "")[:3000],
            "links": links.get("links", [])[:15]
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_platform_stats(platform: str) -> dict:
    platform_urls = {
        "youtube": "https://studio.youtube.com",
        "tiktok": "https://www.tiktok.com/tiktokstudio/content",
        "instagram": "https://www.instagram.com/insights/"
    }
    url = platform_urls.get(platform, "")
    if not url:
        return {"error": f"Unknown platform: {platform}"}
    nav = _browser_call("navigate", url=url)
    if "error" in nav:
        return nav
    import time; time.sleep(2)
    text = _browser_call("get_page_text")
    return {
        "platform": platform,
        "url": url,
        "page_title": nav.get("title", ""),
        "stats_text": text.get("text", "")[:3000],
        "note": "User must be logged in to this platform for stats to be visible"
    }


# ── Content Management tool implementations ────────────────────────────────────

def _tool_schedule_content(job_id: int, publish_at: str, platforms: list = None) -> dict:
    try:
        # Store schedule in database if supported, else simulate
        schedule_data = {
            "job_id": job_id,
            "publish_at": publish_at,
            "platforms": platforms or [],
            "status": "scheduled"
        }
        # Try to use db if it has a schedule function
        if hasattr(db, "create_schedule"):
            schedule_id = db.create_schedule(**schedule_data)
            schedule_data["schedule_id"] = schedule_id
        else:
            import hashlib
            schedule_data["schedule_id"] = abs(hash(f"{job_id}_{publish_at}")) % 100000
            schedule_data["note"] = "Schedule stored in memory (db.create_schedule not implemented)"
        return schedule_data
    except Exception as e:
        return {"error": str(e)}


def _tool_list_scheduled() -> dict:
    try:
        if hasattr(db, "get_schedules"):
            schedules = db.get_schedules()
            return {"schedules": schedules, "count": len(schedules)}
        # Fall back: show queued jobs as "scheduled"
        jobs = db.get_jobs(limit=10) or []
        queued = [j for j in jobs if j.get("status") in ("queued", "scheduled")]
        return {
            "schedules": queued,
            "count": len(queued),
            "note": "Showing queued/scheduled jobs (dedicated schedule table not yet created)"
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_cancel_scheduled(schedule_id: int) -> dict:
    try:
        if hasattr(db, "cancel_schedule"):
            db.cancel_schedule(schedule_id)
            return {"cancelled": schedule_id, "status": "cancelled"}
        return {"note": f"Schedule {schedule_id} marked for cancellation (db.cancel_schedule not implemented)"}
    except Exception as e:
        return {"error": str(e)}


def _tool_bulk_create(topics: list, format: str = "short", platforms: list = None) -> dict:
    if platforms is None:
        platforms = []
    results = []
    for topic in topics[:10]:  # cap at 10 to avoid abuse
        r = _tool_create_content(topic=topic, format=format, platforms=platforms)
        results.append(r)
    success = [r for r in results if "job_id" in r]
    failed = [r for r in results if "error" in r]
    return {"created": len(success), "failed": len(failed), "jobs": success, "errors": failed}


# ── File & Output tool implementations ─────────────────────────────────────────

def _tool_list_output_files(limit: int = 20) -> dict:
    try:
        import glob as glob_mod
        data_dir = os.getenv("DATA_DIR", "/data")
        patterns = [
            os.path.join(data_dir, "**", "*.mp4"),
            os.path.join(data_dir, "**", "*.jpg"),
            os.path.join(data_dir, "**", "*.png"),
            os.path.join(data_dir, "**", "*.txt"),
        ]
        all_files = []
        for pat in patterns:
            all_files.extend(glob_mod.glob(pat, recursive=True))
        all_files.sort(key=os.path.getmtime, reverse=True)
        all_files = all_files[:limit]
        file_info = []
        for f in all_files:
            try:
                size = os.path.getsize(f)
                file_info.append({"path": f, "size_kb": round(size / 1024, 1), "name": os.path.basename(f)})
            except Exception:
                file_info.append({"path": f})
        return {"files": file_info, "count": len(file_info), "data_dir": data_dir}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_job_files(job_id: int) -> dict:
    try:
        import glob as glob_mod
        data_dir = os.getenv("DATA_DIR", "/data")
        job_dir = os.path.join(data_dir, str(job_id))
        if not os.path.exists(job_dir):
            # Try searching for job_id in filenames
            all_files = glob_mod.glob(os.path.join(data_dir, "**", f"*{job_id}*"), recursive=True)
            return {"job_id": job_id, "files": all_files[:20], "job_dir": job_dir, "dir_exists": False}
        files = os.listdir(job_dir)
        categorized = {"videos": [], "thumbnails": [], "scripts": [], "other": []}
        for f in files:
            fp = os.path.join(job_dir, f)
            if f.endswith(".mp4"):
                categorized["videos"].append(fp)
            elif f.endswith((".jpg", ".jpeg", ".png")):
                categorized["thumbnails"].append(fp)
            elif f.endswith(".txt"):
                categorized["scripts"].append(fp)
            else:
                categorized["other"].append(fp)
        return {"job_id": job_id, "job_dir": job_dir, **categorized}
    except Exception as e:
        return {"error": str(e)}


def _tool_download_info(job_id: int) -> dict:
    try:
        base_url = os.getenv("APP_BASE_URL", "https://socialoptimize.online")
        return {
            "job_id": job_id,
            "download_url": f"{base_url}/download/{job_id}",
            "stream_url": f"{base_url}/api/jobs/{job_id}/video",
            "note": "Use the download_url in a browser to download the video"
        }
    except Exception as e:
        return {"error": str(e)}


# ── System & Health tool implementations ───────────────────────────────────────

def _tool_system_health() -> dict:
    health = {}
    # Claude API
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        client.messages.create(model="claude-haiku-4-5", max_tokens=5, messages=[{"role": "user", "content": "hi"}])
        health["claude_api"] = "healthy"
    except Exception as e:
        health["claude_api"] = f"error: {str(e)[:80]}"

    # Pexels API
    try:
        r = requests.get("https://api.pexels.com/v1/search?query=nature&per_page=1",
                         headers={"Authorization": config.PEXELS_API_KEY or ""}, timeout=8)
        health["pexels_api"] = "healthy" if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as e:
        health["pexels_api"] = f"error: {str(e)[:60]}"

    # Playwright / Browser
    try:
        from generators import hollywood_browser  # noqa: F401
        health["browser"] = "available"
    except ImportError:
        health["browser"] = "not installed (run: playwright install chromium)"

    # Database
    try:
        jobs = db.get_jobs(limit=1)
        health["database"] = "healthy"
    except Exception as e:
        health["database"] = f"error: {str(e)[:60]}"

    # Higgsfield
    health["higgsfield"] = "configured" if config.HIGGSFIELD_MCP_TOKEN else "not configured"

    return {"health": health, "overall": "healthy" if all("error" not in v and "missing" not in v for v in health.values()) else "degraded"}


def _tool_platform_connections() -> dict:
    connections = {
        "youtube": {
            "configured": bool(config.YOUTUBE_CLIENT_ID and config.YOUTUBE_CLIENT_SECRET),
            "client_id_set": bool(config.YOUTUBE_CLIENT_ID),
            "redirect_uri": os.getenv("YOUTUBE_REDIRECT_URI", "not set")
        },
        "tiktok": {
            "configured": bool(os.getenv("TIKTOK_CLIENT_KEY") and os.getenv("TIKTOK_CLIENT_SECRET")),
        },
        "instagram": {
            "configured": bool(os.getenv("INSTAGRAM_ACCESS_TOKEN")),
            "account_id_set": bool(os.getenv("INSTAGRAM_ACCOUNT_ID"))
        }
    }
    connected = [p for p, v in connections.items() if v.get("configured")]
    return {"platforms": connections, "connected_count": len(connected), "connected": connected}


def _tool_restart_scheduler() -> dict:
    try:
        # Try to import and restart the scheduler if it exists
        try:
            from scheduler import restart as sched_restart
            sched_restart()
            return {"status": "restarted", "message": "Scheduler restarted successfully"}
        except ImportError:
            pass
        # Fallback: signal gunicorn to reload (SIGHUP)
        import signal
        import subprocess
        result = subprocess.run(["pkill", "-HUP", "gunicorn"], capture_output=True, text=True)
        return {"status": "signal_sent", "return_code": result.returncode, "message": "SIGHUP sent to gunicorn"}
    except Exception as e:
        return {"error": str(e)}


# ── Analytics tool implementations ─────────────────────────────────────────────

def _tool_get_analytics_summary() -> dict:
    try:
        all_jobs = db.get_jobs(limit=200) or []
        total = len(all_jobs)
        completed = [j for j in all_jobs if j.get("status") == "done"]
        failed = [j for j in all_jobs if j.get("status") == "error"]
        formats = {}
        for j in all_jobs:
            fmt = j.get("format", "unknown")
            formats[fmt] = formats.get(fmt, 0) + 1
        completion_rate = round(len(completed) / total * 100, 1) if total else 0
        # Rough revenue estimate: $0.50 per completed short, $2 per long
        est_revenue = sum(
            0.50 if j.get("format") == "short" else 2.00
            for j in completed
        )
        return {
            "total_jobs": total,
            "completed": len(completed),
            "failed": len(failed),
            "in_progress": total - len(completed) - len(failed),
            "completion_rate_pct": completion_rate,
            "formats_breakdown": formats,
            "estimated_content_value_usd": round(est_revenue, 2),
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_trending_niches() -> dict:
    try:
        all_jobs = db.get_jobs(limit=100) or []
        niche_counts = {}
        for j in all_jobs:
            niche = (j.get("niche") or j.get("title") or "").split(":")[0].strip().lower()
            if niche:
                niche_counts[niche] = niche_counts.get(niche, 0) + 1
        top_local = sorted(niche_counts.items(), key=lambda x: -x[1])[:10]
        evergreen_trending = [
            "AI tools & productivity", "crypto & web3", "fitness motivation",
            "cooking & recipes", "personal finance", "travel vlogs",
            "tech reviews", "mental health", "gaming highlights", "pet videos"
        ]
        return {
            "top_from_your_jobs": [{"niche": n, "jobs": c} for n, c in top_local],
            "evergreen_trending_niches": evergreen_trending,
            "tip": "Use search_trends tool to get live Google Trends data for any niche"
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_content_calendar_view() -> dict:
    try:
        from datetime import datetime, timedelta
        calendar = []
        today = datetime.utcnow().date()
        # Pull queued/scheduled jobs
        all_jobs = db.get_jobs(limit=50) or []
        pending = [j for j in all_jobs if j.get("status") in ("queued", "scheduled", "processing")]
        for i in range(7):
            day = today + timedelta(days=i)
            # Assign pending jobs to days (round robin)
            day_jobs = [pending[idx] for idx in range(len(pending)) if idx % 7 == i]
            calendar.append({
                "date": str(day),
                "day": day.strftime("%A"),
                "scheduled_jobs": [{"id": j.get("id"), "title": j.get("title"), "status": j.get("status")} for j in day_jobs]
            })
        return {"calendar": calendar, "week_start": str(today), "total_scheduled": len(pending)}
    except Exception as e:
        return {"error": str(e)}


# ── Tool dispatch ──────────────────────────────────────────────────────────────

def _dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return its result as a JSON string."""
    try:
        if tool_name == "create_content":
            result = _tool_create_content(
                topic=tool_input["topic"],
                format=tool_input.get("format", "short"),
                platforms=tool_input.get("platforms", []),
                audience=tool_input.get("audience", "general public")
            )
        elif tool_name == "get_job_status":
            result = _tool_get_job_status(job_id=int(tool_input["job_id"]))
        elif tool_name == "list_recent_jobs":
            result = _tool_list_recent_jobs(limit=int(tool_input.get("limit", 5)))
        elif tool_name == "check_render_config":
            result = _tool_check_render_config(
                render_api_key=tool_input["render_api_key"],
                service_id=tool_input["service_id"]
            )
        elif tool_name == "set_render_env_vars":
            result = _tool_set_render_env_vars(
                render_api_key=tool_input["render_api_key"],
                service_id=tool_input["service_id"],
                env_vars=tool_input["env_vars"]
            )
        elif tool_name == "generate_secret_key":
            result = _tool_generate_secret_key()
        elif tool_name == "get_all_required_env_vars":
            result = _tool_get_all_required_env_vars()

        # Browser tools
        elif tool_name == "browser_navigate":
            result = _tool_browser_navigate(url=tool_input["url"])
        elif tool_name == "browser_screenshot":
            result = _tool_browser_screenshot()
        elif tool_name == "browser_click":
            result = _tool_browser_click(selector=tool_input["selector"])
        elif tool_name == "browser_type":
            result = _tool_browser_type(selector=tool_input["selector"], text=tool_input["text"])
        elif tool_name == "browser_get_text":
            result = _tool_browser_get_text()
        elif tool_name == "browser_scroll":
            result = _tool_browser_scroll(
                direction=tool_input.get("direction", "down"),
                amount=int(tool_input.get("amount", 500))
            )
        elif tool_name == "browser_fill_form":
            result = _tool_browser_fill_form(fields=tool_input["fields"])
        elif tool_name == "browser_press_key":
            result = _tool_browser_press_key(key=tool_input["key"])

        # Research & Trends
        elif tool_name == "search_trends":
            result = _tool_search_trends(niche=tool_input["niche"], region=tool_input.get("region", "US"))
        elif tool_name == "analyze_competitor":
            result = _tool_analyze_competitor(channel_url=tool_input["channel_url"])
        elif tool_name == "web_search":
            result = _tool_web_search(query=tool_input["query"])
        elif tool_name == "get_platform_stats":
            result = _tool_get_platform_stats(platform=tool_input["platform"])

        # Content Management
        elif tool_name == "schedule_content":
            result = _tool_schedule_content(
                job_id=int(tool_input["job_id"]),
                publish_at=tool_input["publish_at"],
                platforms=tool_input.get("platforms", [])
            )
        elif tool_name == "list_scheduled":
            result = _tool_list_scheduled()
        elif tool_name == "cancel_scheduled":
            result = _tool_cancel_scheduled(schedule_id=int(tool_input["schedule_id"]))
        elif tool_name == "bulk_create":
            result = _tool_bulk_create(
                topics=tool_input["topics"],
                format=tool_input.get("format", "short"),
                platforms=tool_input.get("platforms", [])
            )

        # File & Output
        elif tool_name == "list_output_files":
            result = _tool_list_output_files(limit=int(tool_input.get("limit", 20)))
        elif tool_name == "get_job_files":
            result = _tool_get_job_files(job_id=int(tool_input["job_id"]))
        elif tool_name == "download_info":
            result = _tool_download_info(job_id=int(tool_input["job_id"]))

        # System & Health
        elif tool_name == "system_health":
            result = _tool_system_health()
        elif tool_name == "platform_connections":
            result = _tool_platform_connections()
        elif tool_name == "restart_scheduler":
            result = _tool_restart_scheduler()

        # Analytics
        elif tool_name == "get_analytics_summary":
            result = _tool_get_analytics_summary()
        elif tool_name == "get_trending_niches":
            result = _tool_get_trending_niches()
        elif tool_name == "content_calendar_view":
            result = _tool_content_calendar_view()

        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": f"Tool execution failed: {str(e)}"}
    return json.dumps(result)


# ── Main chat function ─────────────────────────────────────────────────────────

def chat(message: str, history: list, user_id: int = None) -> dict:
    """
    Send a message to Hollywood and get a response.
    history: list of {"role": "user"|"assistant", "content": "..."}
    Returns a dict: {"reply": str, "screenshots": list[str], "tool_calls": list[str]}
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    messages = []
    for h in (history or []):
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    screenshots = []       # list of base64 strings
    tool_calls_used = []   # list of tool names called

    # Tool-use loop
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=HOLLYWOOD_PERSONA,
            tools=TOOLS,
            messages=messages
        )

        text_parts = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if response.stop_reason == "end_turn" or not tool_uses:
            final_text = "\n".join(text_parts) if text_parts else "(No response)"
            return {
                "reply": final_text,
                "screenshots": screenshots,
                "tool_calls": tool_calls_used,
            }

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_use in tool_uses:
            tool_calls_used.append(tool_use.name)
            tool_result_content = _dispatch_tool(tool_use.name, tool_use.input)

            # Extract screenshots from browser_screenshot results
            if tool_use.name == "browser_screenshot":
                try:
                    parsed = json.loads(tool_result_content)
                    b64 = parsed.get("screenshot_b64")
                    if b64:
                        screenshots.append(b64)
                except Exception:
                    pass

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": tool_result_content
            })

        messages.append({"role": "user", "content": tool_results})
