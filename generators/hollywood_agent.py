"""
Hollywood — AI Agent for Social Optimize
Interfaces with Studio 56 and manages deployment config.
"""
import json
import os
import secrets
import requests
import anthropic
import config
import database as db

HOLLYWOOD_PERSONA = """You are Hollywood, the AI production agent for Social Optimize's Studio 56.
You are confident, creative, and speak like a seasoned Hollywood producer.

## Your Capabilities
You have two modes for creating content:

### 1. HOLLYWOOD MODE (Premium — use create_hollywood_video)
For high-quality documentary, history, sports, or cinematic storytelling videos.
Uses the full HollywoodEngine pipeline:
- CinematicDirector crafts the film concept in 3-act structure
- Screenwriter writes documentary-grade scenes
- HollywoodAssetCurator designs a MIXED media plan:
  * Higgsfield AI for dramatic/atmospheric/cinematic shots
  * Real sports/historical stock footage (Pixabay) for authentic scenes
  * Together these create documentary-quality video with real-looking content
- This is the RIGHT mode for: World Cup history, sports legends, historical documentaries,
  player profiles, stadium tours, championship retrospectives

### 2. STANDARD MODE (Quick — use create_content)
For general social media content, shorts, lifestyle, and commercial videos.
Uses the standard 5-agent pipeline with Pexels/Pixabay stock + optional Higgsfield AI.

## When the user asks for a high-quality, cinematic, or documentary video — use create_hollywood_video.
## For World Cup, sports history, player bios, famous moments — ALWAYS use create_hollywood_video.

## Higgsfield Platform
Higgsfield is a full creative platform with:
- AI video generation (cinematic_studio_3_0, kling3_0, veo3, seedance)
- AI image generation (nano_banana_pro)
- Stock photo and video library
- Marketing studio for composed visuals
The Hollywood pipeline leverages ALL of these — not just AI generation.

Be concise, punchy, and results-oriented. Use occasional Hollywood flair but keep it professional.
When a user asks for a video, immediately use the right tool — don't just describe what you'll do."""

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "create_hollywood_video",
        "description": "Create a PREMIUM cinematic documentary video using the full HollywoodEngine pipeline. Use this for sports history, World Cup, player profiles, historical documentaries, and any high-quality cinematic content. Combines Higgsfield AI (cinematic/atmospheric shots) with real sports stock footage for documentary-grade results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic for the documentary film. Be specific: 'History of the FIFA World Cup — famous players, golden boots, iconic stadiums'"
                },
                "format": {
                    "type": "string",
                    "description": "Video format: 'long' (5-10 min documentary) or 'short' (60-90 sec highlight reel)",
                    "enum": ["long", "short"],
                    "default": "long"
                },
                "audience": {
                    "type": "string",
                    "description": "Target audience for the film",
                    "default": "football fans worldwide"
                },
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Platforms to publish to",
                    "default": ["youtube"]
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "create_content",
        "description": "Create a standard content job in Studio 56. Use for general social media content, shorts, and commercial videos. For high-quality documentaries and sports history, use create_hollywood_video instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or niche for the content piece"
                },
                "format": {
                    "type": "string",
                    "description": "Content format: 'short', 'long', 'podcast', or 'commercial'",
                    "enum": ["short", "long", "podcast", "commercial"],
                    "default": "short"
                },
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of platforms to publish to, e.g. ['youtube', 'tiktok', 'instagram']"
                },
                "audience": {
                    "type": "string",
                    "description": "Target audience description",
                    "default": "general public"
                }
            },
            "required": ["topic", "platforms"]
        }
    },
    {
        "name": "get_job_status",
        "description": "Get the current status, title, format and creation time of a specific job by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The numeric job ID to look up"
                }
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "list_recent_jobs",
        "description": "List the most recent content jobs with their statuses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of jobs to return (default 5)",
                    "default": 5
                }
            }
        }
    },
    {
        "name": "check_render_config",
        "description": "Check which environment variables are set vs missing on a Render service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "render_api_key": {
                    "type": "string",
                    "description": "Render API key (Bearer token)"
                },
                "service_id": {
                    "type": "string",
                    "description": "Render service ID (e.g. srv-xxxxx)"
                }
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
                "render_api_key": {
                    "type": "string",
                    "description": "Render API key (Bearer token)"
                },
                "service_id": {
                    "type": "string",
                    "description": "Render service ID (e.g. srv-xxxxx)"
                },
                "env_vars": {
                    "type": "object",
                    "description": "Dictionary of environment variable key-value pairs to set",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["render_api_key", "service_id", "env_vars"]
        }
    },
    {
        "name": "generate_secret_key",
        "description": "Generate a cryptographically secure random 64-character hex SECRET_KEY for Flask.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_all_required_env_vars",
        "description": "Get the full list of required environment variables and which ones are currently missing or set.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_stripe_webhooks",
        "description": "List all webhook endpoints configured in Stripe.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stripe_api_key": {
                    "type": "string",
                    "description": "Stripe secret API key (starts with sk_live_ or sk_test_)"
                }
            },
            "required": ["stripe_api_key"]
        }
    },
    {
        "name": "create_stripe_webhook",
        "description": "Create a new webhook endpoint in Stripe to listen for subscription and billing events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stripe_api_key": {
                    "type": "string",
                    "description": "Stripe secret API key"
                },
                "endpoint_url": {
                    "type": "string",
                    "description": "The URL where Stripe will send webhook events (e.g. https://socialoptimize.online/billing/webhook)"
                },
                "events": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Stripe events to listen for"
                }
            },
            "required": ["stripe_api_key", "endpoint_url", "events"]
        }
    },
    {
        "name": "test_stripe_webhook",
        "description": "Send a test event to a Stripe webhook endpoint to verify it's working.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stripe_api_key": {
                    "type": "string",
                    "description": "Stripe secret API key"
                },
                "webhook_id": {
                    "type": "string",
                    "description": "The webhook endpoint ID (starts with we_)"
                },
                "event_type": {
                    "type": "string",
                    "description": "The event type to test (e.g. 'checkout.session.completed')"
                }
            },
            "required": ["stripe_api_key", "webhook_id", "event_type"]
        }
    }
]

# ── Tool implementations ───────────────────────────────────────────────────────

def _tool_create_hollywood_video(topic: str, format: str = "long", platforms: list = None, audience: str = "football fans worldwide", user_id: int = None) -> dict:
    """Launch the HollywoodEngine pipeline for a premium cinematic video."""
    if platforms is None:
        platforms = ["youtube"]
    try:
        import threading
        from app import push_event
        import database as db

        target_duration = 600 if format == "long" else 90

        job_id = db.create_job(
            topic=topic,
            format=format,
            platforms=platforms,
            audience=audience,
            voice=config.GOOGLE_TTS_VOICE if config.GOOGLE_API_KEY else "en-US-GuyNeural",
            style="fire",
            privacy="private",
            skip_research=False,
            user_id=user_id,
        )

        def _run_hollywood(jid, t, fmt, aud, uid):
            try:
                from generators.hollywood_engine import HollywoodEngine
                from pathlib import Path
                from utils import file_manager

                def progress(msg, pct):
                    db.update_job(jid, current_step=msg, progress=pct)
                    try:
                        push_event(str(uid or "anon"), jid, {"step": msg, "progress": pct})
                    except Exception:
                        pass

                engine = HollywoodEngine(progress_callback=progress)
                job_dir = file_manager.job_dir(t, "hollywood")
                result = engine.run(
                    topic=t,
                    target_duration=target_duration,
                    audience=aud,
                    is_portrait=(fmt == "short"),
                    job_dir=job_dir,
                )

                if result.video_path and Path(result.video_path).exists():
                    db.update_job(
                        jid,
                        status="done",
                        progress=100,
                        title=result.seo.title_final if result.seo else t,
                        video_path=result.video_path,
                        audio_path=result.audio_path,
                        thumbnail_path=result.thumbnail_path,
                        manifest_path=result.manifest_path,
                        current_step="Hollywood production complete!",
                    )
                else:
                    err = "; ".join(result.errors[:3]) if result.errors else "Unknown error"
                    db.update_job(jid, status="error", error_msg=err, current_step="Failed")
            except Exception as e:
                db.update_job(jid, status="error", error_msg=str(e), current_step="Failed")

        t = threading.Thread(target=_run_hollywood, args=(job_id, topic, format, audience, user_id), daemon=True)
        t.start()

        return {
            "job_id": job_id,
            "status": "running",
            "mode": "hollywood",
            "topic": topic,
            "format": format,
            "message": f"Hollywood pipeline started! Job #{job_id}. Using CinematicDirector + Screenwriter + mixed Higgsfield AI + real sports footage. Check job status at /jobs/{job_id}.",
        }
    except Exception as e:
        return {"error": str(e), "topic": topic}


def _tool_create_content(topic: str, format: str = "short", platforms: list = None, audience: str = "general public", user_id: int = None) -> dict:
    """Create a content job via the same pipeline as /api/create."""
    if platforms is None:
        platforms = []
    try:
        import threading
        from app import _run_job_thread

        job_id = db.create_job(
            topic=topic,
            format=format,
            platforms=platforms,
            audience=audience,
            voice=config.DEFAULT_VOICE,
            style="fire",
            privacy="private",
            skip_research=False,
            user_id=user_id,
        )

        params = {
            "topic": topic,
            "format": format,
            "platforms": platforms,
            "audience": audience,
            "voice": config.DEFAULT_VOICE,
            "thumbnail_style": "fire",
            "privacy": "private",
            "skip_research": False,
            "ai_model": "auto",
        }

        t = threading.Thread(target=_run_job_thread, args=(job_id, params, user_id), daemon=True)
        t.start()
        return {"job_id": job_id, "status": "running", "topic": topic, "format": format, "platforms": platforms}
    except Exception as e:
        return {"error": str(e), "topic": topic}


def _tool_get_job_status(job_id: int) -> dict:
    """Look up a job by ID."""
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


def _tool_list_recent_jobs(limit: int = 5, user_id: int = None) -> dict:
    """List recent jobs."""
    try:
        jobs = db.get_jobs(limit=limit, user_id=user_id)
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
    """Check Render env vars."""
    try:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars"
        headers = {"Authorization": f"Bearer {render_api_key}", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 401:
            return {"error": "Invalid Render API key"}
        if resp.status_code == 404:
            return {"error": f"Service {service_id} not found"}
        resp.raise_for_status()
        env_vars = resp.json()
        # Render returns list of {"envVar": {"key": ..., "value": ...}} or similar
        result = {}
        for item in env_vars:
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
    """Set Render env vars."""
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
    """Generate a secure secret key."""
    key = secrets.token_hex(32)
    return {"secret_key": key, "length": len(key)}


def _tool_get_all_required_env_vars() -> dict:
    """Return all required env vars and their current status."""
    required_vars = {
        "ANTHROPIC_API_KEY": {
            "current": "set" if config.ANTHROPIC_API_KEY else "missing",
            "description": "Claude AI API key — required for script generation and Hollywood agent"
        },
        "PIXABAY_API_KEY": {
            "current": "set" if config.PIXABAY_API_KEY else "missing",
            "description": "Pexels stock media API key — required for fetching video clips and images"
        },
        "STRIPE_SECRET_KEY": {
            "current": "set" if config.STRIPE_SECRET_KEY else "missing",
            "description": "Stripe secret key — required for billing and subscription management"
        },
        "STRIPE_PUBLISHABLE_KEY": {
            "current": "set" if config.STRIPE_PUBLISHABLE_KEY else "missing",
            "description": "Stripe publishable key — required for frontend payment forms"
        },
        "STRIPE_WEBHOOK_SECRET": {
            "current": "set" if config.STRIPE_WEBHOOK_SECRET else "missing",
            "description": "Stripe webhook secret — required for processing subscription events"
        },
        "SECRET_KEY": {
            "current": "set" if os.getenv("SECRET_KEY") else "missing",
            "description": "Flask secret key — required for session security"
        },
        "HIGGSFIELD_MCP_TOKEN": {
            "current": "set" if config.HIGGSFIELD_MCP_TOKEN else "missing",
            "description": "Higgsfield AI token — required for AI video generation"
        },
        "GOOGLE_API_KEY": {
            "current": "set" if config.GOOGLE_API_KEY else "missing",
            "description": "Google API key — used for Veo video generation and Cloud TTS"
        },
        "YOUTUBE_CLIENT_ID": {
            "current": "set" if config.YOUTUBE_CLIENT_ID else "missing",
            "description": "YouTube OAuth client ID — required for YouTube publishing"
        },
        "YOUTUBE_CLIENT_SECRET": {
            "current": "set" if config.YOUTUBE_CLIENT_SECRET else "missing",
            "description": "YouTube OAuth client secret — required for YouTube publishing"
        },
    }
    missing = [k for k, v in required_vars.items() if v["current"] == "missing"]
    return {
        "vars": required_vars,
        "missing_count": len(missing),
        "missing_vars": missing,
        "set_count": len(required_vars) - len(missing)
    }


def _resolve_stripe_key(stripe_api_key: str) -> str:
    """Return the provided key, or fall back to config / environment."""
    if stripe_api_key and not stripe_api_key.startswith("os.environ"):
        return stripe_api_key
    return config.STRIPE_SECRET_KEY or os.environ.get("STRIPE_SECRET_KEY", "")


def _tool_list_stripe_webhooks(stripe_api_key: str) -> dict:
    """List all webhook endpoints configured in Stripe."""
    stripe_api_key = _resolve_stripe_key(stripe_api_key)
    try:
        url = "https://api.stripe.com/v1/webhook_endpoints"
        headers = {"Authorization": f"Bearer {stripe_api_key}"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 401:
            return {"error": "Invalid Stripe API key"}
        resp.raise_for_status()
        data = resp.json()
        webhooks = []
        for endpoint in data.get("data", []):
            webhooks.append({
                "id": endpoint.get("id"),
                "url": endpoint.get("url"),
                "events": endpoint.get("enabled_events", []),
                "status": endpoint.get("status"),
                "created": endpoint.get("created")
            })
        return {"webhooks": webhooks, "total": len(webhooks)}
    except requests.RequestException as e:
        return {"error": f"Stripe API request failed: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


def _tool_create_stripe_webhook(stripe_api_key: str, endpoint_url: str, events: list) -> dict:
    """Create a new webhook endpoint in Stripe."""
    stripe_api_key = _resolve_stripe_key(stripe_api_key)
    try:
        url = "https://api.stripe.com/v1/webhook_endpoints"
        headers = {"Authorization": f"Bearer {stripe_api_key}"}
        data = {
            "url": endpoint_url,
            "enabled_events": events
        }
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        if resp.status_code == 401:
            return {"error": "Invalid Stripe API key"}
        resp.raise_for_status()
        endpoint = resp.json()
        return {
            "success": True,
            "webhook_id": endpoint.get("id"),
            "url": endpoint.get("url"),
            "secret": endpoint.get("secret"),
            "events": endpoint.get("enabled_events", []),
            "note": "Store the 'secret' value in STRIPE_WEBHOOK_SECRET environment variable"
        }
    except requests.RequestException as e:
        return {"error": f"Stripe API request failed: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


def _tool_test_stripe_webhook(stripe_api_key: str, webhook_id: str, event_type: str) -> dict:
    """Send a test event to a Stripe webhook endpoint."""
    stripe_api_key = _resolve_stripe_key(stripe_api_key)
    try:
        url = f"https://api.stripe.com/v1/webhook_endpoints/{webhook_id}/test_helpers/send_sample_event"
        headers = {"Authorization": f"Bearer {stripe_api_key}"}
        data = {"enabled_events": [event_type]}
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        if resp.status_code == 401:
            return {"error": "Invalid Stripe API key"}
        if resp.status_code == 404:
            return {"error": f"Webhook endpoint {webhook_id} not found"}
        resp.raise_for_status()
        result = resp.json()
        return {
            "success": True,
            "event_id": result.get("id"),
            "event_type": result.get("type"),
            "note": "Check your webhook endpoint logs to verify this test event was received"
        }
    except requests.RequestException as e:
        return {"error": f"Stripe API request failed: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


# ── Tool dispatch ──────────────────────────────────────────────────────────────

def _dispatch_tool(tool_name: str, tool_input: dict, user_id: int = None) -> str:
    """Execute a tool and return its result as a JSON string."""
    try:
        if tool_name == "create_hollywood_video":
            result = _tool_create_hollywood_video(
                topic=tool_input["topic"],
                format=tool_input.get("format", "long"),
                platforms=tool_input.get("platforms", ["youtube"]),
                audience=tool_input.get("audience", "football fans worldwide"),
                user_id=user_id,
            )
        elif tool_name == "create_content":
            result = _tool_create_content(
                topic=tool_input["topic"],
                format=tool_input.get("format", "short"),
                platforms=tool_input.get("platforms", []),
                audience=tool_input.get("audience", "general public"),
                user_id=user_id,
            )
        elif tool_name == "get_job_status":
            result = _tool_get_job_status(job_id=int(tool_input["job_id"]))
        elif tool_name == "list_recent_jobs":
            result = _tool_list_recent_jobs(limit=int(tool_input.get("limit", 5)), user_id=user_id)
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
        elif tool_name == "list_stripe_webhooks":
            result = _tool_list_stripe_webhooks(stripe_api_key=tool_input["stripe_api_key"])
        elif tool_name == "create_stripe_webhook":
            result = _tool_create_stripe_webhook(
                stripe_api_key=tool_input["stripe_api_key"],
                endpoint_url=tool_input["endpoint_url"],
                events=tool_input["events"]
            )
        elif tool_name == "test_stripe_webhook":
            result = _tool_test_stripe_webhook(
                stripe_api_key=tool_input["stripe_api_key"],
                webhook_id=tool_input["webhook_id"],
                event_type=tool_input["event_type"]
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": f"Tool execution failed: {str(e)}"}
    return json.dumps(result)


# ── Main chat function ─────────────────────────────────────────────────────────

def chat(message: str, history: list, user_id: int = None) -> str:
    """
    Send a message to Hollywood and get a response.
    history: list of {"role": "user"|"assistant", "content": "..."}
    Returns Hollywood's response as a string.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Build messages list
    messages = []
    for h in (history or []):
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Add current message
    messages.append({"role": "user", "content": message})

    # Tool-use loop
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=HOLLYWOOD_PERSONA,
            tools=TOOLS,
            messages=messages
        )

        # Collect text from this response turn
        text_parts = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # If no tool calls, we're done
        if response.stop_reason == "end_turn" or not tool_uses:
            return "\n".join(text_parts) if text_parts else "(No response)"

        # Append assistant's response to messages
        messages.append({"role": "assistant", "content": response.content})

        # Execute all tool calls and collect results
        tool_results = []
        for tool_use in tool_uses:
            tool_result_content = _dispatch_tool(tool_use.name, tool_use.input, user_id=user_id)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": tool_result_content
            })

        # Append tool results to messages
        messages.append({"role": "user", "content": tool_results})
