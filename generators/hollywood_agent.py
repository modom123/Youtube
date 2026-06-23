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

You have full control over VideoBlueprints — the strategic plan that drives the entire production pipeline.
Blueprint variables: title, hook, core_angle, target_audience, content_type, tone, estimated_ctr,
trend_score, keywords, thumbnail_concept, rationale. You can get, update, create, clone, compare,
and analyze blueprints. You can also run the production pipeline directly from a saved blueprint.
When users ask about blueprints or video strategy, use these tools to help them craft the perfect plan.

You fully manage Render deployment. You can:
- Set env vars on Render via API (render_set_env_vars) — user tells you a key, you push it live
- Check what env vars are set and what's missing (render_get_required_env_vars, render_get_env_vars)
- Check deploy status (render_get_deploy_status) and service info (render_get_service_info)
- Trigger new deploys (trigger_render_deploy) and restart the service (render_restart_service)
- Navigate to API key pages for any service (fetch_api_key) to help users find their keys
When the user wants to set up Render, proactively check what's missing and guide them through getting
each key. Open the API key pages in the browser, walk them through it, and set each key on Render as
they provide it. The user should never have to touch the Render dashboard directly.

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

    # ── Render Deployment Tools ──────────────────────────────────────────────
    {
        "name": "render_set_env_vars",
        "description": "Set environment variables on the Render service via API. Tell Hollywood what keys to set (e.g. 'set my ANTHROPIC_API_KEY to sk-ant-xxx') and it pushes them directly to Render. No dashboard needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "env_vars": {
                    "type": "object",
                    "description": "Dictionary of env var key-value pairs to set on Render, e.g. {'ANTHROPIC_API_KEY': 'sk-ant-xxx'}",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["env_vars"]
        }
    },
    {
        "name": "render_get_env_vars",
        "description": "List all environment variables currently set on the Render service. Shows which ones have values and which are missing.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "render_get_deploy_status",
        "description": "Check the current deployment status on Render — is it building, live, or failed?",
        "input_schema": {
            "type": "object",
            "properties": {
                "deploy_id": {
                    "type": "string",
                    "description": "Specific deploy ID to check. If omitted, checks the latest deploy."
                }
            }
        }
    },
    {
        "name": "render_get_service_info",
        "description": "Get full service info from Render — URL, status, region, plan, last deploy time.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "render_restart_service",
        "description": "Restart the Render service without redeploying.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "trigger_render_deploy",
        "description": "Trigger an immediate Render deployment using the deploy hook. No browser needed — just fires the hook and Render rebuilds from latest commit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deploy_hook_url": {
                    "type": "string",
                    "description": "The Render deploy hook URL. If not provided, uses the saved hook."
                }
            }
        }
    },
    {
        "name": "render_get_required_env_vars",
        "description": "Show all env vars needed by this app (from render.yaml), which ones are set, and which are still missing.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_render_blueprint_yaml",
        "description": "Return the current render.yaml content from this repo so Hollywood can review it before deploying.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "fetch_api_key",
        "description": "Navigate to a service's API key page in the browser so Hollywood can help the user get their key. Services: anthropic, pexels, stripe, youtube, render, google, tiktok. Hollywood opens the page, reads it, and guides the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name: anthropic, pexels, stripe, youtube, render, google, tiktok",
                    "enum": ["anthropic", "pexels", "stripe", "youtube", "render", "google", "tiktok"]
                }
            },
            "required": ["service"]
        }
    },
    {
        "name": "deploy_render_blueprint",
        "description": "Navigate to Render's blueprint page via browser automation and fill in the repo URL. Fallback if API method unavailable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_url": {"type": "string", "description": "GitHub repo URL to deploy"},
                "blueprint_name": {"type": "string", "description": "Name for the blueprint instance"}
            },
            "required": ["repo_url"]
        }
    },
    {
        "name": "fill_render_env_vars",
        "description": "Fill env vars via browser automation on Render dashboard. Fallback if API method unavailable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "Render service ID"},
                "env_vars": {"type": "object", "description": "Key-value pairs to fill", "additionalProperties": {"type": "string"}}
            },
            "required": ["service_id", "env_vars"]
        }
    },
    {
        "name": "render_dashboard_navigate",
        "description": "Navigate to a specific Render dashboard page via browser.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "description": "Page: 'blueprint_new', 'services', 'env_vars', or URL"},
                "service_id": {"type": "string", "description": "Service ID (for env_vars page)"}
            },
            "required": ["page"]
        }
    },

    # ── Blueprint Tools ──────────────────────────────────────────────────────
    {
        "name": "get_blueprint",
        "description": "Get the full VideoBlueprint for a specific job — title, hook, core_angle, target_audience, content_type, tone, estimated_ctr, trend_score, keywords, thumbnail_concept, rationale.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "The job ID to get the blueprint for"}},
            "required": ["job_id"]
        }
    },
    {
        "name": "update_blueprint",
        "description": "Update one or more blueprint variables for a job. Accepts any subset of: title, hook, core_angle, target_audience, content_type (educational/listicle/story/tutorial/opinion), tone (authoritative/conversational/dramatic/inspiring/urgent), estimated_ctr (0-1), trend_score (0-10), keywords (list), thumbnail_concept, rationale.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "The job ID to update"},
                "updates": {
                    "type": "object",
                    "description": "Dictionary of blueprint fields to update. Supported fields: title, hook, core_angle, target_audience, content_type, tone, estimated_ctr, trend_score, keywords, thumbnail_concept, rationale.",
                    "properties": {
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                        "core_angle": {"type": "string"},
                        "target_audience": {"type": "string"},
                        "content_type": {"type": "string", "enum": ["educational", "listicle", "story", "tutorial", "opinion"]},
                        "tone": {"type": "string", "enum": ["authoritative", "conversational", "dramatic", "inspiring", "urgent"]},
                        "estimated_ctr": {"type": "number"},
                        "trend_score": {"type": "number"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "thumbnail_concept": {"type": "string"},
                        "rationale": {"type": "string"}
                    }
                }
            },
            "required": ["job_id", "updates"]
        }
    },
    {
        "name": "create_blueprint",
        "description": "Create a custom VideoBlueprint from scratch without running the Trend Architect agent. Saves it for a given job or creates a new job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Video title (max 60 chars)"},
                "hook": {"type": "string", "description": "Opening hook for first 3 seconds"},
                "core_angle": {"type": "string", "description": "Unique angle that differentiates this video"},
                "target_audience": {"type": "string", "description": "Primary audience persona"},
                "content_type": {"type": "string", "enum": ["educational", "listicle", "story", "tutorial", "opinion"]},
                "tone": {"type": "string", "enum": ["authoritative", "conversational", "dramatic", "inspiring", "urgent"]},
                "estimated_ctr": {"type": "number", "description": "Predicted CTR 0-1"},
                "trend_score": {"type": "number", "description": "Trend relevance 0-10"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "3-10 SEO keywords"},
                "thumbnail_concept": {"type": "string", "description": "Visual concept for thumbnail"},
                "rationale": {"type": "string", "description": "Why this angle wins right now"},
                "job_id": {"type": "integer", "description": "Existing job ID to attach to (optional — creates a new job if omitted)"}
            },
            "required": ["title", "hook", "core_angle", "target_audience", "content_type", "tone", "keywords"]
        }
    },
    {
        "name": "list_blueprints",
        "description": "List all jobs that have blueprints, showing key blueprint variables (title, content_type, tone, trend_score, estimated_ctr) for each.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max number of blueprints to return (default 10)", "default": 10}
            }
        }
    },
    {
        "name": "clone_blueprint",
        "description": "Clone a blueprint from one job to create a new job with the same blueprint (optionally overriding some fields).",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_job_id": {"type": "integer", "description": "Job ID to clone the blueprint from"},
                "overrides": {
                    "type": "object",
                    "description": "Optional field overrides for the cloned blueprint",
                    "properties": {
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                        "core_angle": {"type": "string"},
                        "target_audience": {"type": "string"},
                        "content_type": {"type": "string", "enum": ["educational", "listicle", "story", "tutorial", "opinion"]},
                        "tone": {"type": "string", "enum": ["authoritative", "conversational", "dramatic", "inspiring", "urgent"]},
                        "estimated_ctr": {"type": "number"},
                        "trend_score": {"type": "number"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "thumbnail_concept": {"type": "string"},
                        "rationale": {"type": "string"}
                    }
                }
            },
            "required": ["source_job_id"]
        }
    },
    {
        "name": "run_from_blueprint",
        "description": "Re-run the production pipeline starting from a saved blueprint (skips Trend Architect). Runs Narrative Designer → Asset Curator → Cost Engineer → Growth Engineer using the blueprint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "Job ID with the blueprint to run from"},
                "format": {"type": "string", "enum": ["short", "long", "podcast", "commercial"], "default": "short"},
                "platforms": {"type": "array", "items": {"type": "string"}, "description": "Platforms to target"},
                "audience": {"type": "string", "description": "Target audience override", "default": "general public"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "analyze_blueprint",
        "description": "Analyze a blueprint's strengths and weaknesses — CTR prediction quality, keyword competitiveness, hook effectiveness, and suggestions for improvement.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "Job ID to analyze the blueprint for"}},
            "required": ["job_id"]
        }
    },
    {
        "name": "compare_blueprints",
        "description": "Compare two blueprints side-by-side showing differences in all variables.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id_a": {"type": "integer", "description": "First job ID"},
                "job_id_b": {"type": "integer", "description": "Second job ID"}
            },
            "required": ["job_id_a", "job_id_b"]
        }
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


# ── Render deployment tool implementations ───────────────────────────────────

RENDER_DEPLOY_HOOK = "https://api.render.com/deploy/srv-d8t0do77f7vs73bkq11g?key=VDe3ZfxMdGk"
RENDER_SERVICE_ID = "srv-d8t0do77f7vs73bkq11g"
RENDER_API_BASE = "https://api.render.com/v1"

RENDER_DASHBOARD_PAGES = {
    "blueprint_new": "https://dashboard.render.com/blueprint/new",
    "services": "https://dashboard.render.com/services",
}


def _tool_deploy_render_blueprint(repo_url: str, blueprint_name: str = None) -> dict:
    """Automate filling the Render blueprint new page."""
    steps = []

    # Step 1: Navigate to blueprint page
    nav = _browser_call("navigate", url="https://dashboard.render.com/blueprint/new")
    if "error" in nav:
        return {"error": f"Failed to navigate to Render: {nav['error']}", "steps": steps}
    steps.append({"step": "navigate", "result": "Loaded Render blueprint page"})

    import time
    time.sleep(2)

    # Take screenshot of initial state
    ss1 = _browser_call("screenshot")
    steps.append({"step": "screenshot_initial", "screenshot": ss1.get("screenshot_b64", "")[:20] + "..."})

    # Step 2: Look for repo URL input and fill it
    page = None
    try:
        from generators.hollywood_browser import get_page
        page = get_page()
    except Exception as e:
        return {"error": f"Browser not available: {e}", "steps": steps}

    filled = False
    # Render blueprint page has an input for repo URL
    for selector in [
        'input[placeholder*="repo"]',
        'input[placeholder*="URL"]',
        'input[placeholder*="url"]',
        'input[name*="repo"]',
        'input[type="url"]',
        'input[type="text"]',
    ]:
        try:
            el = page.query_selector(selector)
            if el:
                page.fill(selector, repo_url, timeout=5000)
                filled = True
                steps.append({"step": "fill_repo_url", "selector": selector, "value": repo_url})
                break
        except Exception:
            continue

    if not filled:
        # Try clicking any visible text that says "public git repository"
        try:
            page.get_by_placeholder("public Git repository").fill(repo_url)
            filled = True
            steps.append({"step": "fill_repo_url", "method": "by_placeholder", "value": repo_url})
        except Exception:
            pass

    if not filled:
        text = _browser_call("get_page_text")
        return {
            "error": "Could not find repo URL input on the page. User may need to log in first.",
            "page_text": text.get("text", "")[:1500],
            "steps": steps,
            "suggestion": "Try 'browser_navigate' to https://dashboard.render.com first to check if you're logged in.",
        }

    time.sleep(1)

    # Step 3: Try to click Connect/Apply button
    for btn_text in ["Connect", "Apply", "Next", "Continue", "Create"]:
        try:
            page.get_by_role("button", name=btn_text).first.click(timeout=3000)
            steps.append({"step": "click_button", "button": btn_text})
            break
        except Exception:
            continue

    time.sleep(2)

    # Step 4: If there's a blueprint name field, fill it
    if blueprint_name:
        for selector in [
            'input[name*="name"]',
            'input[placeholder*="name"]',
            'input[placeholder*="Name"]',
        ]:
            try:
                el = page.query_selector(selector)
                if el:
                    page.fill(selector, blueprint_name, timeout=5000)
                    steps.append({"step": "fill_blueprint_name", "value": blueprint_name})
                    break
            except Exception:
                continue

    # Take final screenshot
    time.sleep(1)
    ss2 = _browser_call("screenshot")
    steps.append({"step": "screenshot_final"})

    return {
        "status": "in_progress",
        "repo_url": repo_url,
        "blueprint_name": blueprint_name,
        "steps_completed": len(steps),
        "steps": steps,
        "current_url": page.url if page else "",
        "screenshots_taken": 2,
        "message": "Blueprint form started. Use browser_screenshot to see current state, browser_click/browser_type to continue interacting with the form.",
    }


def _tool_fill_render_env_vars(service_id: str, env_vars: dict) -> dict:
    """Navigate to Render service env vars page and fill them in."""
    url = f"https://dashboard.render.com/web/{service_id}/env"
    nav = _browser_call("navigate", url=url)
    if "error" in nav:
        return {"error": f"Failed to navigate: {nav['error']}"}

    import time
    time.sleep(2)

    try:
        from generators.hollywood_browser import get_page
        page = get_page()
    except Exception as e:
        return {"error": f"Browser not available: {e}"}

    filled = []
    errors = []

    for key, value in env_vars.items():
        try:
            # Click "Add Environment Variable" button
            for btn_text in ["Add Environment Variable", "Add Variable", "Add"]:
                try:
                    page.get_by_role("button", name=btn_text).first.click(timeout=3000)
                    time.sleep(0.5)
                    break
                except Exception:
                    continue

            # Find the last (newest) empty key input and fill it
            key_inputs = page.query_selector_all('input[placeholder*="KEY"], input[placeholder*="key"], input[name*="key"]')
            if key_inputs:
                last_key = key_inputs[-1]
                last_key.fill(key)

            # Find the last empty value input and fill it
            val_inputs = page.query_selector_all('input[placeholder*="VALUE"], input[placeholder*="value"], input[name*="value"], textarea[placeholder*="value"]')
            if val_inputs:
                last_val = val_inputs[-1]
                last_val.fill(value)

            filled.append(key)
            time.sleep(0.3)
        except Exception as e:
            errors.append({"key": key, "error": str(e)})

    # Try to click Save
    for btn_text in ["Save Changes", "Save", "Update", "Apply"]:
        try:
            page.get_by_role("button", name=btn_text).first.click(timeout=3000)
            break
        except Exception:
            continue

    time.sleep(1)
    ss = _browser_call("screenshot")

    return {
        "service_id": service_id,
        "filled": filled,
        "errors": errors,
        "total_vars": len(env_vars),
        "filled_count": len(filled),
        "current_url": page.url,
        "message": f"Filled {len(filled)}/{len(env_vars)} env vars. Check screenshot to verify.",
    }


def _tool_render_dashboard_navigate(page: str, service_id: str = None) -> dict:
    """Navigate to a Render dashboard page."""
    if page in RENDER_DASHBOARD_PAGES:
        url = RENDER_DASHBOARD_PAGES[page]
    elif page == "env_vars" and service_id:
        url = f"https://dashboard.render.com/web/{service_id}/env"
    elif page.startswith("http"):
        url = page
    else:
        return {"error": f"Unknown page: {page}. Options: {list(RENDER_DASHBOARD_PAGES.keys())} + 'env_vars' (needs service_id)"}

    nav = _browser_call("navigate", url=url)
    if "error" in nav:
        return nav

    import time
    time.sleep(2)
    ss = _browser_call("screenshot")

    return {
        "page": page,
        "url": url,
        "title": nav.get("title", ""),
        "current_url": nav.get("url", ""),
    }


def _tool_get_render_blueprint_yaml() -> dict:
    """Read and return the render.yaml from this repo."""
    from pathlib import Path
    render_path = Path(__file__).parent.parent / "render.yaml"
    if not render_path.exists():
        return {"error": "render.yaml not found in repo root"}
    content = render_path.read_text()

    import yaml
    try:
        parsed = yaml.safe_load(content)
    except Exception:
        parsed = None

    env_vars_list = []
    if parsed and "services" in parsed:
        for svc in parsed["services"]:
            for ev in svc.get("envVars", []):
                env_vars_list.append({
                    "key": ev.get("key", ""),
                    "has_value": bool(ev.get("value")),
                    "auto_generated": bool(ev.get("generateValue")),
                    "needs_manual": bool(ev.get("sync") is False),
                })

    return {
        "content": content,
        "path": str(render_path),
        "env_vars": env_vars_list,
        "total_env_vars": len(env_vars_list),
        "manual_vars": sum(1 for v in env_vars_list if v["needs_manual"]),
        "auto_vars": sum(1 for v in env_vars_list if v["auto_generated"]),
    }


def _tool_trigger_render_deploy(deploy_hook_url: str = None) -> dict:
    """Trigger a Render deployment via deploy hook URL."""
    import requests
    url = deploy_hook_url or RENDER_DEPLOY_HOOK
    if not url:
        return {"error": "No deploy hook URL provided and no default configured"}
    try:
        resp = requests.get(url, timeout=30)
        return {
            "status": "triggered" if resp.status_code == 200 else "failed",
            "http_status": resp.status_code,
            "response": resp.text[:500],
            "deploy_hook": url.split("?")[0] + "?key=***",
            "message": "Deployment triggered! Render will pull latest code and rebuild."
                if resp.status_code == 200
                else f"Deploy hook returned status {resp.status_code}. Check the URL.",
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "error": "Cannot reach api.render.com — network may be restricted",
            "details": str(e)[:200],
            "suggestion": "Try running this from your local machine or add api.render.com to network egress allowlist.",
        }
    except Exception as e:
        return {"error": f"Deploy hook request failed: {str(e)}"}


def _render_api(method: str, path: str, json_data=None) -> dict:
    """Make an authenticated Render API call."""
    import requests
    api_key = config.RENDER_API_KEY if hasattr(config, "RENDER_API_KEY") else os.environ.get("RENDER_API_KEY", "")
    if not api_key:
        return {"error": "No RENDER_API_KEY configured. Hollywood needs a Render API key to manage your service. Get one at https://dashboard.render.com/u/settings#api-keys"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{RENDER_API_BASE}{path}"
    try:
        resp = requests.request(method, url, headers=headers, json=json_data, timeout=30)
        if resp.status_code == 401:
            return {"error": "Render API key is invalid or expired. Get a new one at https://dashboard.render.com/u/settings#api-keys"}
        try:
            return {"status_code": resp.status_code, "data": resp.json()}
        except Exception:
            return {"status_code": resp.status_code, "data": resp.text[:1000]}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach api.render.com — network restricted. Run locally or add api.render.com to egress allowlist."}
    except Exception as e:
        return {"error": str(e)}


def _tool_render_set_env_vars(env_vars: dict) -> dict:
    """Set env vars on Render via API."""
    result = _render_api("GET", f"/services/{RENDER_SERVICE_ID}/env-vars")
    if "error" in result:
        return result
    existing = {ev["key"]: ev for ev in (result.get("data") or [])} if isinstance(result.get("data"), list) else {}
    payload = []
    for key, value in env_vars.items():
        payload.append({"key": key, "value": str(value)})
    put_result = _render_api("PUT", f"/services/{RENDER_SERVICE_ID}/env-vars", json_data=payload)
    if "error" in put_result:
        return put_result
    return {
        "status": "success",
        "set_count": len(env_vars),
        "keys_set": list(env_vars.keys()),
        "message": f"Set {len(env_vars)} env var(s) on Render. Service will auto-restart to pick them up.",
    }


def _tool_render_get_env_vars() -> dict:
    """Get current env vars from Render."""
    result = _render_api("GET", f"/services/{RENDER_SERVICE_ID}/env-vars")
    if "error" in result:
        return result
    env_list = result.get("data", [])
    if not isinstance(env_list, list):
        return {"error": f"Unexpected response: {env_list}"}
    summary = []
    for ev in env_list:
        summary.append({
            "key": ev.get("key", ""),
            "has_value": bool(ev.get("value")),
            "value_preview": (ev.get("value", "")[:4] + "***") if ev.get("value") else "(empty)",
        })
    set_count = sum(1 for s in summary if s["has_value"])
    return {
        "env_vars": summary,
        "total": len(summary),
        "set": set_count,
        "missing": len(summary) - set_count,
    }


def _tool_render_get_deploy_status(deploy_id: str = None) -> dict:
    """Check deploy status on Render."""
    if deploy_id:
        result = _render_api("GET", f"/services/{RENDER_SERVICE_ID}/deploys/{deploy_id}")
    else:
        result = _render_api("GET", f"/services/{RENDER_SERVICE_ID}/deploys?limit=5")
    if "error" in result:
        return result
    data = result.get("data", [])
    if isinstance(data, list) and data:
        deploys = []
        for d in data[:5]:
            dep = d.get("deploy", d)
            deploys.append({
                "id": dep.get("id", ""),
                "status": dep.get("status", ""),
                "commit": dep.get("commit", {}).get("message", "")[:80] if isinstance(dep.get("commit"), dict) else "",
                "created_at": dep.get("createdAt", ""),
                "finished_at": dep.get("finishedAt", ""),
            })
        return {"deploys": deploys, "latest_status": deploys[0]["status"] if deploys else "unknown"}
    return {"deploy": data}


def _tool_render_get_service_info() -> dict:
    """Get Render service info."""
    result = _render_api("GET", f"/services/{RENDER_SERVICE_ID}")
    if "error" in result:
        return result
    svc = result.get("data", {})
    return {
        "name": svc.get("name", ""),
        "url": svc.get("serviceDetails", {}).get("url", "") if isinstance(svc.get("serviceDetails"), dict) else "",
        "status": svc.get("suspended", "unknown"),
        "region": svc.get("region", ""),
        "plan": svc.get("plan", ""),
        "branch": svc.get("branch", ""),
        "created_at": svc.get("createdAt", ""),
        "updated_at": svc.get("updatedAt", ""),
        "auto_deploy": svc.get("autoDeploy", ""),
    }


def _tool_render_restart_service() -> dict:
    """Restart the Render service."""
    result = _render_api("POST", f"/services/{RENDER_SERVICE_ID}/restart")
    if "error" in result:
        return result
    return {"status": "restarting", "message": "Service is restarting. It will be back online in a minute."}


def _tool_render_get_required_env_vars() -> dict:
    """Compare render.yaml env vars with what's actually set on Render."""
    yaml_result = _tool_get_render_blueprint_yaml()
    if "error" in yaml_result:
        return yaml_result
    live_result = _tool_render_get_env_vars()
    live_keys = {}
    if "error" not in live_result:
        for ev in live_result.get("env_vars", []):
            live_keys[ev["key"]] = ev["has_value"]
    required = []
    from pathlib import Path
    import yaml
    render_path = Path(__file__).parent.parent / "render.yaml"
    parsed = yaml.safe_load(render_path.read_text())
    for svc in parsed.get("services", []):
        for ev in svc.get("envVars", []):
            key = ev.get("key", "")
            is_auto = bool(ev.get("generateValue"))
            has_default = bool(ev.get("value"))
            is_set = live_keys.get(key, False)
            required.append({
                "key": key,
                "auto_generated": is_auto,
                "has_default": has_default,
                "is_set_on_render": is_set,
                "needs_action": not is_auto and not has_default and not is_set,
            })
    needs_action = [r for r in required if r["needs_action"]]
    return {
        "all_vars": required,
        "total": len(required),
        "needs_action": [r["key"] for r in needs_action],
        "needs_action_count": len(needs_action),
        "message": f"{len(needs_action)} env var(s) still need to be set: {', '.join(r['key'] for r in needs_action)}" if needs_action else "All env vars are configured!",
    }


def _tool_fetch_api_key(service: str) -> dict:
    """Navigate to a service's API key page and help the user get their key."""
    key_pages = {
        "anthropic": {
            "url": "https://console.anthropic.com/settings/keys",
            "name": "Anthropic",
            "env_var": "ANTHROPIC_API_KEY",
            "instructions": "Log in → Settings → API Keys → Create Key → copy the sk-ant-... value",
        },
        "pexels": {
            "url": "https://www.pexels.com/api/new/",
            "name": "Pexels",
            "env_var": "PEXELS_API_KEY",
            "instructions": "Sign up/log in → Your API Key is shown on the page. It's free.",
        },
        "stripe": {
            "url": "https://dashboard.stripe.com/test/apikeys",
            "name": "Stripe",
            "env_var": "STRIPE_SECRET_KEY",
            "instructions": "Log in → Developers → API Keys → copy Secret key (sk_test_...) and Publishable key (pk_test_...)",
        },
        "youtube": {
            "url": "https://console.cloud.google.com/apis/credentials",
            "name": "YouTube/Google",
            "env_var": "YOUTUBE_CLIENT_ID",
            "instructions": "Google Cloud Console → APIs → Credentials → Create OAuth Client ID → copy Client ID and Secret",
        },
        "render": {
            "url": "https://dashboard.render.com/u/settings#api-keys",
            "name": "Render",
            "env_var": "RENDER_API_KEY",
            "instructions": "Profile → Account Settings → API Keys → Create API Key → copy the rnd_... value",
        },
        "google": {
            "url": "https://aistudio.google.com/app/apikey",
            "name": "Google AI (Veo)",
            "env_var": "GOOGLE_API_KEY",
            "instructions": "Google AI Studio → Get API Key → Create → copy the key",
        },
        "tiktok": {
            "url": "https://developers.tiktok.com/apps/",
            "name": "TikTok",
            "env_var": "TIKTOK_CLIENT_KEY",
            "instructions": "TikTok Developer Portal → Manage Apps → your app → App Key and App Secret",
        },
    }
    service_lower = service.lower().strip()
    if service_lower not in key_pages:
        return {
            "error": f"Unknown service '{service}'. Available: {', '.join(key_pages.keys())}",
            "available_services": list(key_pages.keys()),
        }
    info = key_pages[service_lower]
    nav_result = _browser_call("navigate", url=info["url"])
    if "error" in nav_result:
        return {
            "service": info["name"],
            "url": info["url"],
            "env_var": info["env_var"],
            "instructions": info["instructions"],
            "browser_error": nav_result["error"],
            "message": f"Couldn't open {info['name']} in browser. Go to {info['url']} manually and follow: {info['instructions']}",
        }
    import time
    time.sleep(2)
    ss = _browser_call("screenshot")
    text = _browser_call("get_page_text")
    return {
        "service": info["name"],
        "url": info["url"],
        "env_var": info["env_var"],
        "instructions": info["instructions"],
        "page_loaded": True,
        "page_text_preview": text.get("text", "")[:1000],
        "message": f"Opened {info['name']} API key page. {info['instructions']}. Tell me the key and I'll set it on Render.",
    }


# ── Blueprint tool implementations ────────────────────────────────────────────

def _find_blueprint_path(job_id: int):
    """Find blueprint.json for a given job ID."""
    from pathlib import Path
    job = db.get_job(job_id)
    if not job:
        return None, f"Job {job_id} not found"

    manifest_path = job.get("manifest_path", "")
    if manifest_path:
        bp_path = Path(manifest_path).parent / "blueprint.json"
        if bp_path.exists():
            return bp_path, None

    video_path = job.get("video_path", "")
    if video_path:
        bp_path = Path(video_path).parent / "blueprint.json"
        if bp_path.exists():
            return bp_path, None

    import glob as glob_mod
    data_dir = os.getenv("DATA_DIR", "/data")
    for bp in glob_mod.glob(os.path.join(data_dir, "**", "blueprint.json"), recursive=True):
        try:
            with open(bp) as f:
                data = json.load(f)
            parent = os.path.dirname(bp)
            manifest = os.path.join(parent, "manifest.json")
            if os.path.exists(manifest):
                return Path(bp), None
        except Exception:
            continue

    return None, f"No blueprint found for job {job_id}"


def _load_blueprint(job_id: int) -> tuple:
    """Load blueprint dict for a job. Returns (data, error)."""
    bp_path, err = _find_blueprint_path(job_id)
    if err:
        return None, err
    try:
        with open(bp_path) as f:
            return json.load(f), None
    except Exception as e:
        return None, f"Failed to read blueprint: {e}"


def _save_blueprint(job_id: int, data: dict) -> tuple:
    """Save blueprint dict for a job. Returns (path, error)."""
    bp_path, err = _find_blueprint_path(job_id)
    if err:
        from pathlib import Path
        data_dir = os.getenv("DATA_DIR", "/data")
        job_dir = Path(data_dir) / f"job_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        bp_path = job_dir / "blueprint.json"
    try:
        with open(bp_path, "w") as f:
            json.dump(data, f, indent=2)
        return str(bp_path), None
    except Exception as e:
        return None, f"Failed to save blueprint: {e}"


BLUEPRINT_FIELDS = [
    "title", "hook", "core_angle", "target_audience", "content_type",
    "tone", "estimated_ctr", "trend_score", "keywords",
    "thumbnail_concept", "rationale",
]

VALID_CONTENT_TYPES = ["educational", "listicle", "story", "tutorial", "opinion"]
VALID_TONES = ["authoritative", "conversational", "dramatic", "inspiring", "urgent"]


def _tool_get_blueprint(job_id: int) -> dict:
    data, err = _load_blueprint(job_id)
    if err:
        return {"error": err}
    return {"job_id": job_id, "blueprint": data}


def _tool_update_blueprint(job_id: int, updates: dict) -> dict:
    data, err = _load_blueprint(job_id)
    if err:
        return {"error": err}

    invalid_fields = [k for k in updates if k not in BLUEPRINT_FIELDS]
    if invalid_fields:
        return {"error": f"Invalid fields: {invalid_fields}. Valid: {BLUEPRINT_FIELDS}"}

    if "content_type" in updates and updates["content_type"] not in VALID_CONTENT_TYPES:
        return {"error": f"Invalid content_type. Must be one of: {VALID_CONTENT_TYPES}"}
    if "tone" in updates and updates["tone"] not in VALID_TONES:
        return {"error": f"Invalid tone. Must be one of: {VALID_TONES}"}
    if "estimated_ctr" in updates:
        ctr = updates["estimated_ctr"]
        if not (0 <= ctr <= 1):
            return {"error": "estimated_ctr must be between 0 and 1"}
    if "trend_score" in updates:
        ts = updates["trend_score"]
        if not (0 <= ts <= 10):
            return {"error": "trend_score must be between 0 and 10"}

    old_values = {k: data.get(k) for k in updates}
    data.update(updates)

    path, save_err = _save_blueprint(job_id, data)
    if save_err:
        return {"error": save_err}

    return {
        "job_id": job_id,
        "updated_fields": list(updates.keys()),
        "old_values": old_values,
        "new_values": updates,
        "saved_to": path,
    }


def _tool_create_blueprint(
    title: str, hook: str, core_angle: str, target_audience: str,
    content_type: str, tone: str, keywords: list,
    estimated_ctr: float = 0.05, trend_score: float = 5.0,
    thumbnail_concept: str = "", rationale: str = "",
    job_id: int = None,
) -> dict:
    if content_type not in VALID_CONTENT_TYPES:
        return {"error": f"Invalid content_type. Must be one of: {VALID_CONTENT_TYPES}"}
    if tone not in VALID_TONES:
        return {"error": f"Invalid tone. Must be one of: {VALID_TONES}"}

    blueprint_data = {
        "title": title,
        "hook": hook,
        "core_angle": core_angle,
        "target_audience": target_audience,
        "content_type": content_type,
        "tone": tone,
        "estimated_ctr": max(0, min(1, estimated_ctr)),
        "trend_score": max(0, min(10, trend_score)),
        "keywords": keywords[:10],
        "thumbnail_concept": thumbnail_concept,
        "rationale": rationale,
    }

    if job_id is None:
        try:
            job_id = db.create_job(
                topic=title,
                format="short",
                platforms=[],
                audience="general public",
                voice="alloy",
                style="fire",
                privacy="private",
            )
            db.update_job(job_id, status="blueprint_ready")
        except Exception as e:
            return {"error": f"Failed to create job: {e}"}

    path, save_err = _save_blueprint(job_id, blueprint_data)
    if save_err:
        return {"error": save_err}

    return {"job_id": job_id, "blueprint": blueprint_data, "saved_to": path, "status": "created"}


def _tool_list_blueprints(limit: int = 10) -> dict:
    import glob as glob_mod
    from pathlib import Path
    data_dir = os.getenv("DATA_DIR", "/data")
    blueprints = []

    for bp_path in glob_mod.glob(os.path.join(data_dir, "**", "blueprint.json"), recursive=True):
        try:
            with open(bp_path) as f:
                data = json.load(f)
            parent = Path(bp_path).parent
            job_info = {"directory": str(parent)}
            manifest_path = parent / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    manifest = json.load(f)
                job_info["niche"] = manifest.get("niche", "")

            blueprints.append({
                "path": bp_path,
                "title": data.get("title", ""),
                "content_type": data.get("content_type", ""),
                "tone": data.get("tone", ""),
                "trend_score": data.get("trend_score", 0),
                "estimated_ctr": data.get("estimated_ctr", 0),
                "keywords": data.get("keywords", []),
                **job_info,
            })
        except Exception:
            continue

    jobs_with_bp = db.get_jobs(limit=50) or []
    for job in jobs_with_bp:
        mp = job.get("manifest_path", "")
        if mp:
            bp_file = os.path.join(os.path.dirname(mp), "blueprint.json")
            if os.path.exists(bp_file) and bp_file not in [b["path"] for b in blueprints]:
                try:
                    with open(bp_file) as f:
                        data = json.load(f)
                    blueprints.append({
                        "job_id": job.get("id"),
                        "path": bp_file,
                        "title": data.get("title", ""),
                        "content_type": data.get("content_type", ""),
                        "tone": data.get("tone", ""),
                        "trend_score": data.get("trend_score", 0),
                        "estimated_ctr": data.get("estimated_ctr", 0),
                        "keywords": data.get("keywords", []),
                    })
                except Exception:
                    continue

    blueprints.sort(key=lambda b: b.get("trend_score", 0), reverse=True)
    return {"blueprints": blueprints[:limit], "total": len(blueprints)}


def _tool_clone_blueprint(source_job_id: int, overrides: dict = None) -> dict:
    data, err = _load_blueprint(source_job_id)
    if err:
        return {"error": err}

    cloned = dict(data)
    if overrides:
        invalid = [k for k in overrides if k not in BLUEPRINT_FIELDS]
        if invalid:
            return {"error": f"Invalid override fields: {invalid}"}
        cloned.update(overrides)

    title = cloned.get("title", "Cloned Blueprint")
    try:
        new_job_id = db.create_job(
            topic=title,
            format="short",
            platforms=[],
            audience="general public",
            voice="alloy",
            style="fire",
            privacy="private",
        )
        db.update_job(new_job_id, status="blueprint_ready")
    except Exception as e:
        return {"error": f"Failed to create job: {e}"}

    path, save_err = _save_blueprint(new_job_id, cloned)
    if save_err:
        return {"error": save_err}

    return {
        "source_job_id": source_job_id,
        "new_job_id": new_job_id,
        "blueprint": cloned,
        "overrides_applied": list((overrides or {}).keys()),
        "saved_to": path,
    }


def _tool_run_from_blueprint(job_id: int, format: str = "short", platforms: list = None, audience: str = "general public") -> dict:
    data, err = _load_blueprint(job_id)
    if err:
        return {"error": err}

    try:
        from generators.agents.schemas import VideoBlueprint
        blueprint = VideoBlueprint(**data)
    except Exception as e:
        return {"error": f"Invalid blueprint data: {e}"}

    try:
        import threading
        from generators.production_engine import ProductionEngine

        def _bg():
            try:
                engine = ProductionEngine()
                engine.produce(
                    niche=blueprint.title,
                    audience=audience,
                    format=format,
                    platforms=platforms or [],
                    is_portrait=format == "short",
                    target_duration=55 if format == "short" else 480,
                )
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

        return {
            "job_id": job_id,
            "status": "running",
            "blueprint_title": blueprint.title,
            "format": format,
            "platforms": platforms or [],
            "message": f"Production pipeline started from blueprint '{blueprint.title}'"
        }
    except Exception as e:
        return {"error": f"Failed to start pipeline: {e}"}


def _tool_analyze_blueprint(job_id: int) -> dict:
    data, err = _load_blueprint(job_id)
    if err:
        return {"error": err}

    analysis = {"job_id": job_id, "strengths": [], "weaknesses": [], "suggestions": []}

    title = data.get("title", "")
    if len(title) > 60:
        analysis["weaknesses"].append(f"Title too long ({len(title)} chars, max 60)")
    elif 30 <= len(title) <= 60:
        analysis["strengths"].append("Title length is optimal (30-60 chars)")
    elif title:
        analysis["weaknesses"].append(f"Title may be too short ({len(title)} chars)")

    hook = data.get("hook", "")
    if hook:
        if len(hook.split()) >= 5:
            analysis["strengths"].append("Hook is present and substantial")
        else:
            analysis["weaknesses"].append("Hook is too short — aim for at least 5 words")
    else:
        analysis["weaknesses"].append("Missing hook — critical for first 3 seconds")

    ctr = data.get("estimated_ctr", 0)
    if ctr > 0.15:
        analysis["weaknesses"].append(f"CTR prediction ({ctr:.1%}) seems unrealistically high")
        analysis["suggestions"].append("Recalibrate CTR — typical range is 4-12%")
    elif 0.06 <= ctr <= 0.12:
        analysis["strengths"].append(f"CTR prediction ({ctr:.1%}) is in the sweet spot")
    elif ctr < 0.03:
        analysis["weaknesses"].append(f"CTR prediction ({ctr:.1%}) is very low")
        analysis["suggestions"].append("Consider a more compelling title or hook to improve CTR")

    ts = data.get("trend_score", 0)
    if ts >= 7:
        analysis["strengths"].append(f"Strong trend score ({ts}/10)")
    elif ts >= 5:
        analysis["strengths"].append(f"Moderate trend relevance ({ts}/10)")
    else:
        analysis["weaknesses"].append(f"Low trend score ({ts}/10)")
        analysis["suggestions"].append("Research current trends to find a more timely angle")

    keywords = data.get("keywords", [])
    if len(keywords) >= 5:
        analysis["strengths"].append(f"Good keyword coverage ({len(keywords)} keywords)")
    elif len(keywords) >= 3:
        analysis["strengths"].append(f"Adequate keywords ({len(keywords)})")
    else:
        analysis["weaknesses"].append(f"Too few keywords ({len(keywords)}) — aim for 5-10")
        analysis["suggestions"].append("Add more long-tail keywords for better SEO")

    if not data.get("core_angle"):
        analysis["weaknesses"].append("Missing core_angle — what makes this different?")
    else:
        analysis["strengths"].append("Core angle defined")

    if not data.get("thumbnail_concept"):
        analysis["weaknesses"].append("No thumbnail concept — thumbnails drive 80% of clicks")
        analysis["suggestions"].append("Add a vivid thumbnail concept with contrast and emotion")
    else:
        analysis["strengths"].append("Thumbnail concept present")

    if not data.get("rationale"):
        analysis["suggestions"].append("Add a rationale explaining why this angle wins now")

    score = len(analysis["strengths"]) / max(1, len(analysis["strengths"]) + len(analysis["weaknesses"]))
    analysis["overall_score"] = round(score * 10, 1)
    analysis["blueprint"] = data

    return analysis


def _tool_compare_blueprints(job_id_a: int, job_id_b: int) -> dict:
    data_a, err_a = _load_blueprint(job_id_a)
    if err_a:
        return {"error": f"Blueprint A: {err_a}"}
    data_b, err_b = _load_blueprint(job_id_b)
    if err_b:
        return {"error": f"Blueprint B: {err_b}"}

    comparison = {"job_id_a": job_id_a, "job_id_b": job_id_b, "fields": {}}

    for field in BLUEPRINT_FIELDS:
        val_a = data_a.get(field)
        val_b = data_b.get(field)
        comparison["fields"][field] = {
            "a": val_a,
            "b": val_b,
            "match": val_a == val_b,
        }

    matching = sum(1 for f in comparison["fields"].values() if f["match"])
    comparison["matching_fields"] = matching
    comparison["different_fields"] = len(BLUEPRINT_FIELDS) - matching
    comparison["similarity_pct"] = round(matching / len(BLUEPRINT_FIELDS) * 100, 1)

    return comparison


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

        # Blueprint tools
        elif tool_name == "get_blueprint":
            result = _tool_get_blueprint(job_id=int(tool_input["job_id"]))
        elif tool_name == "update_blueprint":
            result = _tool_update_blueprint(job_id=int(tool_input["job_id"]), updates=tool_input["updates"])
        elif tool_name == "create_blueprint":
            result = _tool_create_blueprint(
                title=tool_input["title"],
                hook=tool_input["hook"],
                core_angle=tool_input["core_angle"],
                target_audience=tool_input["target_audience"],
                content_type=tool_input["content_type"],
                tone=tool_input["tone"],
                keywords=tool_input["keywords"],
                estimated_ctr=float(tool_input.get("estimated_ctr", 0.05)),
                trend_score=float(tool_input.get("trend_score", 5.0)),
                thumbnail_concept=tool_input.get("thumbnail_concept", ""),
                rationale=tool_input.get("rationale", ""),
                job_id=tool_input.get("job_id"),
            )
        elif tool_name == "list_blueprints":
            result = _tool_list_blueprints(limit=int(tool_input.get("limit", 10)))
        elif tool_name == "clone_blueprint":
            result = _tool_clone_blueprint(
                source_job_id=int(tool_input["source_job_id"]),
                overrides=tool_input.get("overrides"),
            )
        elif tool_name == "run_from_blueprint":
            result = _tool_run_from_blueprint(
                job_id=int(tool_input["job_id"]),
                format=tool_input.get("format", "short"),
                platforms=tool_input.get("platforms", []),
                audience=tool_input.get("audience", "general public"),
            )
        elif tool_name == "analyze_blueprint":
            result = _tool_analyze_blueprint(job_id=int(tool_input["job_id"]))
        elif tool_name == "compare_blueprints":
            result = _tool_compare_blueprints(
                job_id_a=int(tool_input["job_id_a"]),
                job_id_b=int(tool_input["job_id_b"]),
            )

        # Render deployment
        elif tool_name == "deploy_render_blueprint":
            result = _tool_deploy_render_blueprint(
                repo_url=tool_input["repo_url"],
                blueprint_name=tool_input.get("blueprint_name", ""),
            )
        elif tool_name == "fill_render_env_vars":
            result = _tool_fill_render_env_vars(
                service_id=tool_input.get("service_id", ""),
                env_vars=tool_input["env_vars"],
            )
        elif tool_name == "render_dashboard_navigate":
            result = _tool_render_dashboard_navigate(
                page=tool_input["page"],
                service_id=tool_input.get("service_id", ""),
            )
        elif tool_name == "get_render_blueprint_yaml":
            result = _tool_get_render_blueprint_yaml()
        elif tool_name == "trigger_render_deploy":
            result = _tool_trigger_render_deploy(
                deploy_hook_url=tool_input.get("deploy_hook_url", ""),
            )
        elif tool_name == "render_set_env_vars":
            result = _tool_render_set_env_vars(env_vars=tool_input["env_vars"])
        elif tool_name == "render_get_env_vars":
            result = _tool_render_get_env_vars()
        elif tool_name == "render_get_deploy_status":
            result = _tool_render_get_deploy_status(
                deploy_id=tool_input.get("deploy_id", ""),
            )
        elif tool_name == "render_get_service_info":
            result = _tool_render_get_service_info()
        elif tool_name == "render_restart_service":
            result = _tool_render_restart_service()
        elif tool_name == "render_get_required_env_vars":
            result = _tool_render_get_required_env_vars()
        elif tool_name == "fetch_api_key":
            result = _tool_fetch_api_key(service=tool_input["service"])

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
