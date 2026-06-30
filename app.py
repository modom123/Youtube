"""
Social Money - Web Dashboard
Flask application serving the command center UI.
"""
import json
import os
import csv
import subprocess

# Allow OAuth over HTTP for local development
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
import io
import threading
import time
import uuid
import vobject
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for,
    send_file, Response, stream_with_context, session
)
from flask_login import LoginManager, login_required, current_user
from werkzeug.utils import secure_filename
import requests
import database as db
import config
from auth import auth_bp, make_user
from billing import billing_bp, check_usage_gate
from admin import admin_bp
from notifications import send_notification
from monetizer import monetizer_bp, init_monetizer_tables
from hermes_agent import hermes_bp

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

@app.template_filter("datefmt")
def _datefmt(val, fmt="%Y-%m-%d %H:%M"):
    """Format a datetime object or ISO string for display in templates."""
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        return val.strftime(fmt)
    s = str(val)
    return s[:16].replace("T", " ")

# Trust Render's reverse-proxy headers so request.url_root returns the
# correct public HTTPS URL instead of the internal http://service:10000 address.
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"

@login_manager.unauthorized_handler
def _unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Session expired — please sign in again"}), 401
    return redirect(url_for("auth.login"))

@login_manager.user_loader
def load_user(user_id):
    data = db.get_user_by_id(int(user_id))
    return make_user(data) if data else None

from sales_channels import sales_bp
app.register_blueprint(auth_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(monetizer_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(hermes_bp)

db.init_db()

from admin import load_env_from_db
load_env_from_db()

@app.errorhandler(500)
def _handle_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Internal server error: {e}"}), 500
    return render_template("error.html", error=str(e)), 500

ALLOWED_EXTENSIONS = {"csv", "vcf", "vcard", "txt"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


_job_events: dict = {}
_job_lock = threading.Lock()
_JOB_TTL = 3600          # seconds before completed job events are evicted
_JOB_MAX_EVENTS = 50     # max SSE frames stored per job


def _evict_old_job_events(store: dict, lock: threading.Lock, ttl: int = _JOB_TTL):
    """Remove completed-job event lists older than ttl seconds."""
    import time as _time
    now = _time.time()
    with lock:
        stale = [k for k, v in store.items()
                 if isinstance(v, dict) and now - v.get("_ts", now) > ttl]
        for k in stale:
            del store[k]


def push_event(job_id: int, data: dict):
    import time as _time
    payload = f"data: {json.dumps(data)}\n\n"
    with _job_lock:
        if job_id not in _job_events:
            _job_events[job_id] = []
        _job_events[job_id].append(payload)
        # Keep only the last N events per job to bound memory usage
        if len(_job_events[job_id]) > _JOB_MAX_EVENTS:
            _job_events[job_id] = _job_events[job_id][-_JOB_MAX_EVENTS:]
        # Mark completion time so eviction can clean it up later
        if data.get("status") in ("done", "error", "cancelled"):
            _job_events[f"_ts_{job_id}"] = _time.time()


def _run_job_thread(job_id: int, params: dict, user_id: int = None):
    try:
        print(f"[job #{job_id}] Thread started")
        db.update_job(job_id, status="running", progress=1, current_step="Initializing...")
        push_event(job_id, {"progress": 1, "step": "Initializing...", "status": "running"})
        _run_job_thread_inner(job_id, params, user_id)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[job #{job_id}] FATAL: {e}\n{tb}")
        try:
            db.update_job(job_id, status="error", error_msg=str(e), current_step="Failed")
            push_event(job_id, {"progress": 0, "step": f"Error: {e}", "status": "error", "traceback": tb})
        except Exception:
            pass


def _run_job_thread_inner(job_id: int, params: dict, user_id: int = None):
    import social_optimize
    from generators.ai_router import route as _route_model
    from utils.build_log import BuildLog
    print(f"[job #{job_id}] Thread inner started, setting up...")
    blog = BuildLog(job_id)

    try:
        from generators import ai_video_generator as _avg, higgsfield_mcp as _hmcp
        if user_id:
            _tok = _get_user_higgsfield_token(user_id)
            _avg._session_token.value = _tok
            _hmcp._session_token.value = _tok
        blog.info("Higgsfield token loaded" if user_id else "No user_id — skipping Higgsfield token")
    except Exception as e:
        print(f"[job #{job_id}] Higgsfield token setup failed (non-fatal): {e}")
        blog.warn(f"Higgsfield token setup failed: {e}")

    raw_model = params.get("ai_model", "auto")
    user_row = db.get_user_by_id(user_id) if user_id else {}
    tier = (user_row or {}).get("subscription_tier", "starter")
    routed_model = _route_model(
        content_type=params.get("format", "short"),
        subscription_tier=tier,
        user_preference=raw_model,
    )
    params["ai_model"] = routed_model
    params.setdefault("subscription_tier", tier)
    print(f"[router] Job #{job_id} format={params.get('format')} tier={tier} "
          f"requested={raw_model} → using={routed_model}")
    blog.info(f"AI model routed: {raw_model} → {routed_model}", tier=tier, format=params.get("format"))

    # Hard watchdog: mark job as failed if thread runs longer than 15 minutes
    _WATCHDOG_SECONDS = 900
    _job_cancelled = threading.Event()
    def _watchdog():
        import time as _t
        _t.sleep(_WATCHDOG_SECONDS)
        if _job_cancelled.is_set():
            return
        print(f"[watchdog] Job #{job_id} exceeded {_WATCHDOG_SECONDS}s — forcing error status")
        _job_cancelled.set()
        try:
            db.update_job(job_id, status="error", error_msg=f"Job timed out after {_WATCHDOG_SECONDS}s",
                          current_step="Timed out")
            push_event(job_id, {"progress": 0, "step": "Job timed out", "status": "error"})
        except Exception:
            pass
    _wd = threading.Thread(target=_watchdog, daemon=True)
    _wd.start()

    def progress_cb(pct: int, msg: str):
        db.update_job(job_id, progress=pct, current_step=msg, status="running")
        push_event(job_id, {"progress": pct, "step": msg, "status": "running"})

    db.update_job(job_id, status="running", progress=3, current_step="Starting...")
    push_event(job_id, {"progress": 3, "step": "Starting...", "status": "running"})
    import utils.logger as ul
    _orig_success = ul.success
    _orig_warn = ul.warn
    _orig_error = ul.error
    def _hook_success(msg):
        try:
            _orig_success(msg)
        except Exception:
            pass
        push_event(job_id, {"log": f"✓ {msg}", "status": "running"})
    def _hook_warn(msg):
        try:
            _orig_warn(msg)
        except Exception:
            pass
        push_event(job_id, {"log": f"⚠ {msg}", "status": "running"})
    def _hook_error(msg):
        try:
            _orig_error(msg)
        except Exception:
            pass
        push_event(job_id, {"log": f"✗ {msg}", "status": "running"})
    ul.success = _hook_success
    ul.warn = _hook_warn
    ul.error = _hook_error
    try:
        params["progress_cb"] = progress_cb
        params["build_log"] = blog
        print(f"[job #{job_id}] Entering social_optimize.run()...")
        try:
            manifest = social_optimize.run(**params)
        except Exception as e:
            import traceback as _tb
            blog.error(f"Pipeline crashed: {e}", exc=e)
            db.update_job(job_id, status="error", error_msg=str(e),
                          current_step="Failed", build_log=blog.to_text())
            push_event(job_id, {"progress": 0, "step": f"Error: {e}", "status": "error",
                                "traceback": _tb.format_exc()})
            _job_cancelled.set()
            return
        print(f"[job #{job_id}] Pipeline completed successfully!")
        _job_cancelled.set()
        if user_id:
            try:
                db.increment_user_usage(user_id, videos=1)
            except Exception as _ue:
                print(f"[job #{job_id}] increment_user_usage failed (non-fatal): {_ue}")
        job_title = manifest.get("title")
        blog.success("Job completed successfully")

        from generators.studio_intelligence import record_job as _record
        _record(
            studio="create", job_id=job_id, user_id=user_id or 0,
            topic=params.get("topic", ""), genre=params.get("topic", ""),
            format=params.get("format", "long"),
            voice_used=params.get("voice", ""),
            completed=1,
            duration_seconds=manifest.get("duration", 0),
        )

        db.update_job(
            job_id, status="done", progress=100, current_step="Complete!",
            title=job_title, duration=manifest.get("duration", 0),
            video_path=manifest.get("files", {}).get("video"),
            audio_path=manifest.get("files", {}).get("audio"),
            thumbnail_path=manifest.get("files", {}).get("thumbnail"),
            script_path=manifest.get("files", {}).get("script"),
            manifest_path=manifest.get("files", {}).get("manifest"),
            publish_results=manifest.get("publish_results", {}),
            completed_at=datetime.now().isoformat(),
            build_log=blog.to_text(),
        )
        push_event(job_id, {
            "progress": 100, "step": "Complete!", "status": "done",
            "title": job_title,
            "video_path": manifest.get("files", {}).get("video"),
        })
        if user_id:
            try:
                from notifications import send_notification
                send_notification(user_id, "job_complete", {"job_id": job_id, "title": job_title})
            except Exception:
                pass
    finally:
        ul.success = _orig_success
        ul.warn = _orig_warn
        ul.error = _orig_error


@app.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html", tiers=config.TIERS)


@app.route("/pricing")
def pricing():
    if current_user.is_authenticated:
        return redirect(url_for("billing.billing_page"))
    whop_plans = {
        "starter": config.WHOP_PLAN_STARTER,
        "creator": config.WHOP_PLAN_CREATOR,
        "pro": config.WHOP_PLAN_PRO,
        "agency": config.WHOP_PLAN_AGENCY,
    }
    return render_template("pricing.html", tiers=config.TIERS, whop_plans=whop_plans)


# ── Quick Post ────────────────────────────────────────────────────────────────

QUICKPOST_UPLOADS = Path(config.DATA_DIR) / "quickpost_uploads"
QUICKPOST_UPLOADS.mkdir(parents=True, exist_ok=True)
QUICKPOST_ALLOWED = {"jpg", "jpeg", "png", "webp", "gif", "mp4", "mov", "avi", "webm"}

_quickpost_jobs: dict = {}
_quickpost_lock = threading.Lock()


def _allowed_quickpost(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in QUICKPOST_ALLOWED


@app.route("/quickpost")
@login_required
def quickpost_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a["is_active"]}
    return render_template("quickpost.html", connected_platforms=connected)


@app.route("/api/quickpost/generate", methods=["POST"])
@login_required
def api_quickpost_generate():
    file = request.files.get("media")
    tone        = request.form.get("tone") or "engaging"
    extra_ctx   = (request.form.get("context") or "").strip()
    platforms   = request.form.getlist("platforms") or ["instagram", "tiktok", "facebook", "twitter"]

    if not file or not _allowed_quickpost(file.filename):
        return jsonify({"error": "Please upload a photo or video (jpg, png, mp4, mov)"}), 400

    job_id = str(uuid.uuid4())
    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    media_path = QUICKPOST_UPLOADS / f"{job_id}.{ext}"
    file.save(str(media_path))

    params = {"tone": tone, "extra_ctx": extra_ctx, "platforms": platforms,
              "media_path": str(media_path), "ext": ext}

    t = threading.Thread(target=_run_quickpost_thread,
                         args=(job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/quickpost/<job_id>/status")
@login_required
def quickpost_status(job_id):
    with _quickpost_lock:
        result = _quickpost_jobs.get(job_id)
    if not result:
        return jsonify({"status": "pending"})
    return jsonify(result)


@app.route("/api/quickpost/<job_id>/publish", methods=["POST"])
@login_required
def quickpost_publish(job_id):
    data = request.json or {}
    platform  = data.get("platform", "")
    caption   = data.get("caption", "")
    schedule  = data.get("schedule_at")  # ISO string or None = post now

    with _quickpost_lock:
        result = _quickpost_jobs.get(job_id)
    if not result or result.get("status") != "done":
        return jsonify({"error": "Post not ready"}), 400

    media_path = result.get("media_path")
    if schedule:
        post_id = db.schedule_post(
            user_id=current_user.id,
            platform=platform,
            caption=caption,
            media_path=media_path,
            scheduled_at=schedule,
        )
        return jsonify({"ok": True, "scheduled": True, "post_id": post_id})

    return jsonify({"ok": True, "queued": True,
                    "message": f"Post queued for {platform}. Connect your account to publish."})


def _run_quickpost_thread(job_id: str, params: dict, user_id: int):
    import anthropic as _ant
    import base64

    def done(data):
        with _quickpost_lock:
            _quickpost_jobs[job_id] = data

    try:
        done({"status": "running", "step": "Analyzing your media..."})

        media_path = Path(params["media_path"])
        ext        = params["ext"]
        tone       = params.get("tone", "engaging")
        extra_ctx  = params.get("extra_ctx", "")
        platforms  = params.get("platforms", ["instagram", "tiktok", "facebook", "twitter"])
        is_video   = ext in {"mp4", "mov", "avi", "webm"}

        client = _ant.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        # ── Analyze image with Claude Vision ─────────────────────────────────
        if not is_video:
            img_bytes = media_path.read_bytes()
            b64  = base64.standard_b64encode(img_bytes).decode()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "webp": "image/webp",
                    "gif": "image/gif"}.get(ext, "image/jpeg")
            analysis = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=300,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text", "text": "Describe this image concisely: subject, mood, colors, setting, and what makes it interesting or shareable on social media."}
                ]}]
            )
            media_desc = analysis.content[0].text
        else:
            media_desc = f"A {ext} video clip" + (f" — {extra_ctx}" if extra_ctx else "")

        done({"status": "running", "step": "Writing captions for each platform..."})

        # ── Generate platform-specific captions ───────────────────────────────
        platform_rules = {
            "instagram": "Instagram: 150-220 chars, storytelling tone, 20-30 hashtags at end, emojis encouraged",
            "tiktok":    "TikTok: 100-150 chars, punchy hook first, 3-5 trending hashtags, very energetic",
            "facebook":  "Facebook: 200-400 chars, conversational, question at end drives comments, 3-5 hashtags",
            "twitter":   "X/Twitter: max 240 chars, witty or bold, 1-3 hashtags, no fluff",
            "twitch":    "Twitch: casual gaming/entertainment tone, 150-200 chars, hype the stream, 2-3 hashtags",
            "threads":   "Threads: casual and conversational, 200 chars max, 2-3 hashtags",
            "youtube":   "YouTube community post: engaging question, 200-300 chars",
            "snapchat":  "Snapchat: very short, fun, 50-80 chars, 1-2 emojis",
        }

        rules_block = "\n".join(
            f"- {platform_rules[p]}" for p in platforms if p in platform_rules
        )

        prompt = f"""You are a top social media strategist.

Media: {media_desc}
{f'Additional context: {extra_ctx}' if extra_ctx else ''}
Tone: {tone}

Write an optimized post caption for EACH of these platforms:
{rules_block}

Also generate:
- SUGGESTED_TAGS: 30 general hashtags that fit this content (comma-separated, no #)
- ALT_TEXT: a brief accessibility description of the image
- BEST_TIME: best day and time to post for maximum engagement

Format your response as JSON exactly like this:
{{
  "captions": {{
    "instagram": "...",
    "tiktok": "...",
    "facebook": "...",
    "twitter": "...",
    "twitch": "...",
    "threads": "...",
    "youtube": "...",
    "snapchat": "..."
  }},
  "suggested_tags": ["tag1", "tag2", ...],
  "alt_text": "...",
  "best_time": "...",
  "media_description": "..."
}}

Only include platforms in captions that were requested: {platforms}"""

        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = resp.content[0].text.strip()
        # Extract JSON block
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        import json as _json
        post_data = _json.loads(raw)

        done({
            "status": "done",
            "captions": post_data.get("captions", {}),
            "suggested_tags": post_data.get("suggested_tags", []),
            "alt_text": post_data.get("alt_text", ""),
            "best_time": post_data.get("best_time", ""),
            "media_description": post_data.get("media_description", media_desc),
            "media_path": str(media_path),
            "is_video": is_video,
        })

    except Exception as e:
        done({"status": "error", "error": str(e)})


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/docs")
def docs():
    return render_template("docs.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/blog")
def blog():
    return render_template("blog.html")


@app.route("/tiktoktZP2Ao6MnBjhPb6PTnJsMZ2dzTLrSfPy.txt")
def tiktok_verify():
    return "tiktok-developers-site-verification=tZP2Ao6MnBjhPb6PTnJsMZ2dzTLrSfPy", 200, {"Content-Type": "text/plain"}


@app.route("/dashboard")
@login_required
def dashboard():
    db.reset_usage_if_new_period(current_user.id)
    stats = db.get_stats(user_id=current_user.id)
    recent_jobs = db.get_jobs(limit=5, user_id=current_user.id)
    accounts = db.get_accounts(user_id=current_user.id)
    tier = config.TIERS.get(current_user.subscription_tier, config.TIERS["free"])
    return render_template("index.html", stats=stats, recent_jobs=recent_jobs,
                           accounts=accounts, tier=tier)


@app.route("/home")
def home_redirect():
    return redirect(url_for("dashboard"))


@app.route("/create")
@login_required
def create_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a["is_active"]}
    return render_template(
        "create.html",
        connected_platforms=connected,
        voices=config.AVAILABLE_VOICES,
        google_tts_voices=config.GOOGLE_TTS_VOICES,
        google_api_key=bool(config.GOOGLE_API_KEY),
        deepseek_api_key=bool(config.DEEPSEEK_API_KEY),
        ai_models=__import__("generators.ai_router", fromlist=["get_model_info"]).get_model_info(),
    )


@app.route("/api/create", methods=["POST"])
@login_required
def api_create():
    allowed, err = check_usage_gate(current_user.id)
    if not allowed:
        return jsonify({"error": err, "upgrade": True}), 403
    data = request.json
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400
    platforms = data.get("platforms", [])
    skip_research = data.get("skip_research", False)
    job_id = db.create_job(
        topic=topic, format=data.get("format", "short"), platforms=platforms,
        audience=data.get("audience", "general public"),
        voice=data.get("voice") or config.DEFAULT_VOICE,
        style=data.get("style", "fire"), privacy=data.get("privacy", "private"),
        skip_research=skip_research, user_id=current_user.id,
    )
    agency_client = data.get("agency_client_id")
    agency_project = data.get("agency_project_id")
    if agency_client:
        db.link_job_to_client(job_id, int(agency_client), int(agency_project) if agency_project else None)
    fmt = data.get("format", "short")
    params = {
        "topic": topic, "format": fmt,
        "platforms": platforms, "audience": data.get("audience", "general public"),
        "voice": data.get("voice") or config.DEFAULT_VOICE,
        "thumbnail_style": data.get("style", "fire"),
        "privacy": data.get("privacy", "private"),
        "custom_instructions": data.get("instructions"),
        "dry_run": data.get("dry_run", False),
        "cleanup": data.get("cleanup", False),
        "skip_research": skip_research,
        "ai_video_provider": data.get("ai_video_provider", "none"),
        "higgsfield_model": data.get("higgsfield_model", "kling3_0"),
        "podcast_name": (data.get("podcast_name") or "").strip() or topic,
        "episode_number": int(data.get("episode_number") or 1),
        "guest_name": (data.get("guest_name") or "").strip(),
        "target_duration": int(data.get("target_duration") or 0) or None,
        # Commercial params
        "ad_format": data.get("ad_format") or "",
        "ad_brand": (data.get("ad_brand") or "").strip(),
        "ad_product": (data.get("ad_product") or "").strip(),
        "ad_benefit": (data.get("ad_benefit") or "").strip(),
        "ad_cta": (data.get("ad_cta") or "").strip(),
        "ad_style": data.get("ad_style") or "cinematic",
        "ad_platforms": data.get("ad_platforms") or [],
        # Documentary params
        "doc_style": data.get("doc_style") or "natgeo",
        # Animation params
        "animation_style": data.get("animation_style") or "lego",
        "ai_model": data.get("ai_model", "auto"),
        "subscription_tier": db.get_user_by_id(current_user.id).get("subscription_tier", "starter"),
        "tone": (data.get("tone") or "").strip(),
        "keywords": [k.strip() for k in (data.get("keywords") or "").split(",") if k.strip()],
    }
    t = threading.Thread(target=_run_job_thread, args=(job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<int:job_id>/stream")
@login_required
def job_stream(job_id):
    def generate():
        last_idx = 0
        heartbeat_counter = 0
        while True:
            with _job_lock:
                events = _job_events.get(job_id, [])
                new = events[last_idx:]
                last_idx = len(events)
            for event in new:
                yield event
            job = db.get_job(job_id)
            if job and job["status"] in ("done", "error"):
                if not new:
                    yield f"data: {json.dumps({'status': job['status'], 'progress': job['progress']})}\n\n"
                time.sleep(0.5)
                break
            heartbeat_counter += 1
            if heartbeat_counter >= 20:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0
            time.sleep(0.5)
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/job/<int:job_id>")
@login_required
def api_get_job(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


@app.route("/jobs")
@login_required
def jobs_page():
    jobs = db.get_jobs(limit=100, user_id=current_user.id)
    return render_template("jobs.html", jobs=jobs)


@app.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return redirect("/jobs")
    dubs = db.get_dub_jobs_for_source(user_id=current_user.id, source_job_id=job_id)
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a["is_active"]}
    return render_template("job_detail.html", job=job, dubs=dubs, dub_languages=DUB_LANGUAGES,
                           connected_platforms=connected)


@app.route("/api/jobs/<int:job_id>/publish", methods=["POST"])
@login_required
def api_publish_job(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    if job["status"] != "done":
        return jsonify({"error": "Job must be complete before publishing"}), 400
    if not job.get("video_path"):
        return jsonify({"error": "No video file found for this job"}), 400

    data = request.json or {}
    platforms = data.get("platforms", [])
    privacy = data.get("privacy", "private")
    if not platforms:
        return jsonify({"error": "Select at least one platform"}), 400

    title = job.get("title") or job.get("topic", "")
    description = job.get("description", "")
    hashtags, keywords, cdn_url = [], [], ""
    is_short = job.get("format") in ("short", "reel")

    if job.get("manifest_path"):
        try:
            with open(job["manifest_path"]) as f:
                manifest_data = json.load(f)
            hashtags = manifest_data.get("hashtags", [])
            keywords = manifest_data.get("keywords", [])
            cdn_url = manifest_data.get("files", {}).get("cdn_url", "")
            if not description:
                description = manifest_data.get("description", "")
        except Exception:
            pass

    import social_optimize
    results = social_optimize.publish_to_platforms(
        video_path=job["video_path"],
        title=title, description=description,
        hashtags=hashtags, keywords=keywords,
        platforms=platforms, privacy=privacy,
        is_short=is_short, cdn_url=cdn_url,
    )

    existing = job.get("publish_results") or {}
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except Exception:
            existing = {}
    existing.update(results)
    db.update_job(job_id, publish_results=existing)

    return jsonify({"publish_results": results})


@app.route("/api/jobs/<int:job_id>/research")
@login_required
def get_research(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job or not job.get("research_path"):
        if job and job.get("manifest_path"):
            try:
                with open(job["manifest_path"]) as f:
                    m = json.load(f)
                rpath = m.get("files", {}).get("research")
                if rpath:
                    with open(rpath) as f:
                        return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify({"error": "Research not available"}), 404
    try:
        with open(job["research_path"]) as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({"error": "Could not load research file"}), 404


@app.route("/api/jobs/<int:job_id>/download")
@login_required
def download_video(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job or not job.get("video_path"):
        return jsonify({"error": "Video not found"}), 404
    path = Path(job["video_path"])
    if not path.exists():
        return jsonify({"error": "File missing"}), 404
    return send_file(str(path), as_attachment=True, download_name=f"som_{job_id}.mp4")


@app.route("/api/jobs/<int:job_id>/retry", methods=["POST"])
@login_required
def retry_job(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] == "running":
        return jsonify({"error": "Job is still running"}), 400
    # Reset status fields on the existing record
    db.update_job(job_id, status="running", progress=0, current_step="Retrying...",
                  error_msg=None, video_path=None, audio_path=None,
                  thumbnail_path=None, title=None, completed_at=None)
    platforms = job.get("platforms") or []
    if isinstance(platforms, str):
        import json as _json
        try:
            platforms = _json.loads(platforms)
        except Exception:
            platforms = []
    params = {
        "topic": job["topic"],
        "format": job["format"],
        "platforms": platforms,
        "audience": job.get("audience", "general public"),
        "voice": job.get("voice") or config.DEFAULT_VOICE,
        "thumbnail_style": job.get("style", "fire"),
        "privacy": job.get("privacy", "private"),
        "skip_research": bool(job.get("skip_research")),
        "ai_video_provider": "none",
        "higgsfield_model": "kling3_0",
        "podcast_name": job["topic"],
        "episode_number": 1,
        "guest_name": "",
        "target_duration": None,
        "dry_run": False,
        "cleanup": False,
        "subscription_tier": (db.get_user_by_id(current_user.id) or {}).get("subscription_tier", "starter"),
    }
    threading.Thread(target=_run_job_thread, args=(job_id, params, current_user.id), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel_job(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    db.update_job(job_id, status="error", error_msg="Cancelled by user", current_step="Cancelled")
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job_route(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    db.delete_job(job_id, user_id=current_user.id)
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>/thumbnail")
@login_required
def get_thumbnail(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job or not job.get("thumbnail_path"):
        return "", 404
    path = Path(job["thumbnail_path"])
    if not path.exists():
        return "", 404
    return send_file(str(path), mimetype="image/jpeg")


@app.route("/api/jobs/<int:job_id>/thumbnail/download")
@login_required
def download_thumbnail(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job or not job.get("thumbnail_path"):
        return "", 404
    path = Path(job["thumbnail_path"])
    if not path.exists():
        return "", 404
    title_slug = (job.get("title") or job.get("topic") or f"job{job_id}")[:40]
    title_slug = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title_slug).strip()
    return send_file(str(path), mimetype="image/jpeg",
                     as_attachment=True, download_name=f"thumbnail_{title_slug}.jpg")


@app.route("/api/jobs/<int:job_id>/thumbnail/upload", methods=["POST"])
@login_required
def upload_thumbnail(job_id):
    """Replace thumbnail with an uploaded image."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return jsonify({"error": "Must be a JPG, PNG, or WebP image"}), 400

    # Derive thumbnail path from existing job dir or create one
    if job.get("thumbnail_path"):
        thumb_path = Path(job["thumbnail_path"])
    else:
        from utils import file_manager
        job_dir = file_manager.job_dir(job.get("topic", "job"), "upload")
        thumb_path = job_dir / "thumbnail.jpg"

    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image as PILImage
    from io import BytesIO
    img = PILImage.open(BytesIO(f.read())).convert("RGB")
    img = img.resize((1280, 720), PILImage.LANCZOS)
    img.save(str(thumb_path), "JPEG", quality=92)

    db.update_job(job_id, thumbnail_path=str(thumb_path))
    return jsonify({"status": "ok", "thumbnail_path": str(thumb_path)})


@app.route("/api/jobs/<int:job_id>/thumbnail/regenerate", methods=["POST"])
@login_required
def regenerate_thumbnail(job_id):
    """Regenerate thumbnail with new text and/or style."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.json or {}
    title_text = (data.get("title") or job.get("title") or job.get("topic") or "").strip()
    style = data.get("style") or "fire"
    subtitle = (data.get("subtitle") or "").strip() or None

    if job.get("thumbnail_path"):
        thumb_path = Path(job["thumbnail_path"])
    else:
        from utils import file_manager
        job_dir = file_manager.job_dir(job.get("topic", "job"), "regen")
        thumb_path = job_dir / "thumbnail.jpg"

    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    # Try to use existing background image from job's stock folder
    bg_path = None
    if job.get("thumbnail_path"):
        stock_dir = Path(job["thumbnail_path"]).parent / "stock_images"
        if stock_dir.exists():
            imgs = list(stock_dir.glob("*.jpg")) + list(stock_dir.glob("*.png"))
            if imgs:
                bg_path = imgs[0]

    from generators import thumbnail_generator
    thumbnail_generator.generate_thumbnail(
        title=title_text,
        output_path=thumb_path,
        background_image_path=bg_path,
        style=style,
        subtitle=subtitle,
        width=1280,
        height=720,
    )
    db.update_job(job_id, thumbnail_path=str(thumb_path))
    return jsonify({"status": "ok", "bust": int(time.time())})


@app.route("/api/jobs/<int:job_id>/video")
@login_required
def stream_video(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job or not job.get("video_path"):
        return jsonify({"error": "Video not found"}), 404
    path = Path(job["video_path"])
    if not path.exists():
        return jsonify({"error": "File missing on disk"}), 404
    return send_file(str(path), mimetype="video/mp4", conditional=True)


@app.route("/api/jobs/<int:job_id>/audio")
@login_required
def stream_audio(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job or not job.get("audio_path"):
        return jsonify({"error": "Audio not found"}), 404
    path = Path(job["audio_path"])
    if not path.exists():
        return jsonify({"error": "File missing on disk"}), 404
    mime = "audio/mpeg" if str(path).endswith(".mp3") else "audio/wav"
    return send_file(str(path), mimetype=mime, conditional=True)


@app.route("/api/jobs/<int:job_id>/upload-video", methods=["POST"])
@login_required
def upload_job_video(job_id):
    """Replace the video file for a job (user uploads their own footage)."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400
    from utils import file_manager
    job_dir = Path(file_manager.job_dir(job.get("topic", "job"), "upload"))
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = job_dir / f"video_upload_{int(time.time())}.mp4"
    f.save(str(dest))
    db.update_job(job_id, video_path=str(dest))
    return jsonify({"ok": True, "video_path": str(dest)})


@app.route("/api/jobs/<int:job_id>/upload-audio", methods=["POST"])
@login_required
def upload_job_audio(job_id):
    """Replace or set the audio/narration file for a job."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400
    from utils import file_manager
    job_dir = Path(file_manager.job_dir(job.get("topic", "job"), "upload"))
    job_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(f.filename).suffix or ".mp3"
    dest = job_dir / f"audio_upload_{int(time.time())}{ext}"
    f.save(str(dest))
    db.update_job(job_id, audio_path=str(dest))
    return jsonify({"ok": True, "audio_path": str(dest)})


@app.route("/api/jobs/<int:job_id>/convert", methods=["POST"])
@login_required
def convert_job_video(job_id):
    """Convert a job's video to a different format using ffmpeg."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    if not job.get("video_path") or not Path(job["video_path"]).exists():
        return jsonify({"error": "No video file found for this job"}), 400
    data = request.get_json(force=True)
    target = data.get("format", "mp4")
    if target not in ("mp4", "mov", "webm", "avi", "mkv", "gif"):
        return jsonify({"error": "Unsupported target format"}), 400
    src = Path(job["video_path"])
    dest = src.with_name(src.stem + f"_converted.{target}")
    codec_args = {
        "mp4":  ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"],
        "mov":  ["-c:v", "libx264", "-c:a", "aac"],
        "webm": ["-c:v", "libvpx-vp9", "-c:a", "libopus", "-b:v", "2M"],
        "avi":  ["-c:v", "libx264", "-c:a", "mp3"],
        "mkv":  ["-c:v", "libx264", "-c:a", "aac"],
        "gif":  ["-vf", "fps=15,scale=480:-1:flags=lanczos", "-an"],
    }
    cmd = ["ffmpeg", "-y", "-i", str(src)] + codec_args[target] + [str(dest)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            return jsonify({"error": "Conversion failed: " + result.stderr.decode()[:300]}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out (video too long)"}), 500
    db.update_job(job_id, video_path=str(dest))
    return jsonify({"ok": True, "video_path": str(dest), "format": target})


@app.route("/api/jobs/<int:job_id>/mix", methods=["POST"])
@login_required
def mix_job_audio_video(job_id):
    """Combine job's audio_path + video_path via ffmpeg and save as final video."""
    import subprocess
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    audio = job.get("audio_path")
    video = job.get("video_path")
    if not audio or not video:
        return jsonify({"error": "Job must have both audio and video files"}), 400
    if not Path(audio).exists():
        return jsonify({"error": "Audio file missing on disk"}), 404
    if not Path(video).exists():
        return jsonify({"error": "Video file missing on disk"}), 404
    out_path = Path(video).parent / f"final_mixed_{int(time.time())}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", video,
        "-i", audio,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(out_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            return jsonify({"error": "ffmpeg failed: " + result.stderr.decode()[:300]}), 500
        db.update_job(job_id, video_path=str(out_path), status="done")
        return jsonify({"ok": True})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Mix timed out"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/jobs/<int:job_id>/check-files")
@login_required
def check_job_files(job_id):
    """Return which files exist on disk for this job."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "has_video": bool(job.get("video_path") and Path(job["video_path"]).exists()),
        "has_audio": bool(job.get("audio_path") and Path(job["audio_path"]).exists()),
        "has_thumbnail": bool(job.get("thumbnail_path") and Path(job["thumbnail_path"]).exists()),
    })


@app.route("/api/jobs/<int:job_id>/script")
@login_required
def get_script(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    # Try script_path first, then manifest
    spath = job.get("script_path")
    if not spath and job.get("manifest_path"):
        try:
            with open(job["manifest_path"]) as f:
                spath = json.load(f).get("files", {}).get("script")
        except Exception:
            pass
    if spath:
        try:
            with open(spath) as f:
                content = f.read()
            fmt = request.args.get("format", "text")
            if fmt == "json":
                try:
                    return jsonify(json.loads(content))
                except Exception:
                    pass
            return content, 200, {"Content-Type": "text/plain; charset=utf-8"}
        except Exception:
            pass
    return jsonify({"error": "Script not available"}), 404


@app.route("/api/jobs/<int:job_id>/force-reset", methods=["POST"])
@login_required
def force_reset_job(job_id):
    """Unstick a job that is hung as 'running' so it can be retried."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    db.update_job(job_id, status="error", progress=0,
                  current_step="Reset by user — ready to retry",
                  error_msg="Job was force-reset (was stuck as running)")
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>/build-log")
@login_required
def get_build_log(job_id):
    """Return the full diagnostic build log for a job."""
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    log_text = job.get("build_log") or ""
    if not log_text:
        log_text = f"No build log available for Job #{job_id}.\n"
        if job.get("status") == "running":
            log_text += "The job is still running — the log will be saved when it finishes.\n"
        elif job.get("status") == "pending":
            log_text += "The job hasn't started yet.\n"
        elif job.get("error_msg"):
            log_text += f"\nError message: {job['error_msg']}\n"
    return log_text, 200, {"Content-Type": "text/plain; charset=utf-8"}


# ── Social Accounts ───────────────────────────────────────────────────────────

@app.route("/accounts")
@login_required
def accounts_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a.get("is_active", True)}
    higgsfield_connected = any(
        a.get("platform") == "higgsfield" and a.get("is_active") and a.get("access_token")
        for a in accounts
    )
    return render_template(
        "accounts.html",
        accounts=accounts,
        connected=connected,
        higgsfield_connected=higgsfield_connected,
        is_admin=current_user.is_admin,
        youtube_configured=bool(config.YOUTUBE_CLIENT_ID),
        tiktok_configured=bool(config.TIKTOK_CLIENT_KEY),
        meta_configured=bool(config.FACEBOOK_APP_ID),
        linkedin_configured=bool(config.LINKEDIN_CLIENT_ID),
        twitter_configured=bool(config.TWITTER_CLIENT_ID),
        threads_configured=bool(config.THREADS_APP_ID),
        twitch_configured=bool(config.TWITCH_CLIENT_ID),
        snapchat_configured=bool(config.SNAP_CLIENT_ID),
    )


@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    return jsonify(db.get_accounts(user_id=current_user.id))


@app.route("/api/accounts/connect", methods=["POST"])
@login_required
def api_connect_account():
    data = request.json
    platform = data.get("platform", "").lower()
    username = (data.get("username") or "").strip()
    if not platform or not username:
        return jsonify({"error": "platform and username required"}), 400
    acc_id = db.upsert_account(
        platform=platform, username=username,
        display_name=data.get("display_name", username),
        avatar_url=data.get("avatar_url"),
        access_token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        account_id=data.get("account_id"),
        followers=int(data.get("followers", 0)),
        user_id=current_user.id,
    )
    return jsonify({"id": acc_id, "status": "connected"})


@app.route("/api/accounts/<int:acc_id>", methods=["DELETE"])
def api_delete_account(acc_id):
    db.delete_account(acc_id)
    return jsonify({"status": "deleted"})


@app.route("/oauth/youtube/start")
def oauth_youtube_start():
    if not config.YOUTUBE_CLIENT_ID:
        return jsonify({"error": "YouTube credentials not configured in .env"}), 400
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {"web": {
            "client_id": config.YOUTUBE_CLIENT_ID,
            "client_secret": config.YOUTUBE_CLIENT_SECRET,
            "redirect_uris": [config.APP_BASE_URL + "/oauth/youtube/callback"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }},
        scopes=config.YOUTUBE_SCOPES + ["https://www.googleapis.com/auth/youtube.readonly"],
        redirect_uri=config.APP_BASE_URL + "/oauth/youtube/callback",
    )
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    session["youtube_state"] = state
    return redirect(auth_url)


@app.route("/oauth/youtube/callback")
@login_required
def oauth_youtube_callback():
    from google_auth_oauthlib.flow import Flow
    import googleapiclient.discovery
    flow = Flow.from_client_config(
        {"web": {
            "client_id": config.YOUTUBE_CLIENT_ID,
            "client_secret": config.YOUTUBE_CLIENT_SECRET,
            "redirect_uris": [config.APP_BASE_URL + "/oauth/youtube/callback"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }},
        scopes=config.YOUTUBE_SCOPES + ["https://www.googleapis.com/auth/youtube.readonly"],
        redirect_uri=config.APP_BASE_URL + "/oauth/youtube/callback",
        state=session.get("youtube_state"),
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    channels = yt.channels().list(part="snippet,statistics", mine=True).execute()
    channel = channels["items"][0] if channels.get("items") else {}
    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    db.upsert_account(
        platform="youtube",
        username=snippet.get("customUrl", snippet.get("title", "YouTube")),
        display_name=snippet.get("title"),
        avatar_url=snippet.get("thumbnails", {}).get("default", {}).get("url"),
        access_token=creds.token,
        refresh_token=creds.refresh_token,
        account_id=channel.get("id"),
        followers=int(stats.get("subscriberCount", 0)),
        user_id=current_user.id,
    )
    return redirect("/accounts?connected=youtube")


@app.route("/oauth/tiktok/start")
def oauth_tiktok_start():
    if not config.TIKTOK_CLIENT_KEY:
        return jsonify({"error": "TikTok credentials not configured in .env"}), 400
    redirect_uri = config.APP_BASE_URL + "/oauth/tiktok/callback"
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={config.TIKTOK_CLIENT_KEY}"
        f"&scope=user.info.basic,video.publish,video.upload"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&state=som_tiktok"
    )
    return redirect(auth_url)


@app.route("/oauth/tiktok/callback")
def oauth_tiktok_callback():
    import requests as req
    code = request.args.get("code")
    redirect_uri = config.APP_BASE_URL + "/oauth/tiktok/callback"
    token_resp = req.post("https://open.tiktokapis.com/v2/oauth/token/", data={
        "client_key": config.TIKTOK_CLIENT_KEY,
        "client_secret": config.TIKTOK_CLIENT_SECRET,
        "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    }).json()
    access_token = token_resp.get("access_token")
    open_id = token_resp.get("open_id")
    user_resp = req.get(
        "https://open.tiktokapis.com/v2/user/info/",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "display_name,avatar_url,follower_count,open_id"},
    ).json()
    user = user_resp.get("data", {}).get("user", {})
    db.upsert_account(
        platform="tiktok", username=user.get("display_name", "TikTok User"),
        display_name=user.get("display_name"), avatar_url=user.get("avatar_url"),
        access_token=access_token, account_id=open_id, followers=user.get("follower_count", 0),
        user_id=current_user.id,
    )
    return redirect("/accounts?connected=tiktok")


# ── Meta OAuth (Facebook + Instagram) ────────────────────────────────────────

@app.route("/oauth/facebook/start")
@login_required
def oauth_facebook_start():
    if not config.FACEBOOK_APP_ID:
        return redirect("/accounts?error=facebook_not_configured")
    redirect_uri = config.APP_BASE_URL + "/oauth/facebook/callback"
    scope = "pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish"
    auth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth"
        f"?client_id={config.FACEBOOK_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state=som_fb_{current_user.id}"
    )
    return redirect(auth_url)


@app.route("/oauth/facebook/callback")
@login_required
def oauth_facebook_callback():
    import requests as req
    code = request.args.get("code")
    error = request.args.get("error")
    if error or not code:
        return redirect("/accounts?error=facebook_denied")

    redirect_uri = config.APP_BASE_URL + "/oauth/facebook/callback"
    # Exchange code for user access token
    token_resp = req.get("https://graph.facebook.com/v18.0/oauth/access_token", params={
        "client_id": config.FACEBOOK_APP_ID,
        "client_secret": config.FACEBOOK_APP_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    }).json()
    user_token = token_resp.get("access_token")
    if not user_token:
        return redirect("/accounts?error=facebook_token_failed")

    # Exchange for long-lived token (60 days)
    long_resp = req.get("https://graph.facebook.com/v18.0/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": config.FACEBOOK_APP_ID,
        "client_secret": config.FACEBOOK_APP_SECRET,
        "fb_exchange_token": user_token,
    }).json()
    long_token = long_resp.get("access_token", user_token)

    # Get user profile
    me = req.get("https://graph.facebook.com/v18.0/me", params={
        "fields": "id,name,picture", "access_token": long_token,
    }).json()

    db.upsert_account(
        platform="facebook", username=me.get("name", "Facebook User"),
        display_name=me.get("name"),
        avatar_url=me.get("picture", {}).get("data", {}).get("url"),
        access_token=long_token, account_id=me.get("id"), followers=0,
        user_id=current_user.id,
    )

    # Also pull connected Pages and Instagram business accounts
    pages_resp = req.get("https://graph.facebook.com/v18.0/me/accounts", params={
        "access_token": long_token,
    }).json()
    for page in pages_resp.get("data", []):
        page_token = page.get("access_token")
        page_id = page.get("id")
        # Check for connected Instagram business account
        ig_resp = req.get(f"https://graph.facebook.com/v18.0/{page_id}", params={
            "fields": "instagram_business_account", "access_token": page_token,
        }).json()
        ig_id = ig_resp.get("instagram_business_account", {}).get("id")
        if ig_id:
            ig_user = req.get(f"https://graph.facebook.com/v18.0/{ig_id}", params={
                "fields": "username,name,profile_picture_url,followers_count",
                "access_token": page_token,
            }).json()
            db.upsert_account(
                platform="instagram",
                username=ig_user.get("username", ig_user.get("name", "Instagram")),
                display_name=ig_user.get("name"),
                avatar_url=ig_user.get("profile_picture_url"),
                access_token=page_token, account_id=ig_id,
                followers=int(ig_user.get("followers_count", 0)),
                user_id=current_user.id,
            )

    return redirect("/accounts?connected=facebook")


# ── LinkedIn OAuth ────────────────────────────────────────────────────────────

@app.route("/oauth/linkedin/start")
@login_required
def oauth_linkedin_start():
    if not config.LINKEDIN_CLIENT_ID:
        return redirect("/accounts?error=linkedin_not_configured")
    redirect_uri = config.APP_BASE_URL + "/oauth/linkedin/callback"
    scope = "openid profile email w_member_social"
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={config.LINKEDIN_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state=som_li_{current_user.id}"
    )
    return redirect(auth_url)


@app.route("/oauth/linkedin/callback")
@login_required
def oauth_linkedin_callback():
    import requests as req
    code = request.args.get("code")
    if not code:
        return redirect("/accounts?error=linkedin_denied")
    redirect_uri = config.APP_BASE_URL + "/oauth/linkedin/callback"
    token_resp = req.post("https://www.linkedin.com/oauth/v2/accessToken", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.LINKEDIN_CLIENT_ID,
        "client_secret": config.LINKEDIN_CLIENT_SECRET,
    }).json()
    access_token = token_resp.get("access_token")
    if not access_token:
        return redirect("/accounts?error=linkedin_token_failed")
    me = req.get("https://api.linkedin.com/v2/userinfo", headers={
        "Authorization": f"Bearer {access_token}",
    }).json()
    db.upsert_account(
        platform="linkedin",
        username=me.get("name", "LinkedIn User"),
        display_name=me.get("name"),
        avatar_url=me.get("picture"),
        access_token=access_token, account_id=me.get("sub"), followers=0,
        user_id=current_user.id,
    )
    return redirect("/accounts?connected=linkedin")


@app.route("/oauth/instagram/start")
@login_required
def oauth_instagram_start():
    return redirect(url_for("oauth_facebook_start"))


# ── X (Twitter) OAuth 2.0 ─────────────────────────────────────────────────────

@app.route("/oauth/twitter/start")
@login_required
def oauth_twitter_start():
    import secrets
    import hashlib
    import base64
    if not config.TWITTER_CLIENT_ID:
        return redirect(url_for("accounts_page"))
    verifier = secrets.token_urlsafe(32)
    session["twitter_verifier"] = verifier
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    params = {
        "response_type": "code",
        "client_id": config.TWITTER_CLIENT_ID,
        "redirect_uri": config.TWITTER_REDIRECT_URI,
        "scope": "tweet.read tweet.write users.read offline.access media.write",
        "state": secrets.token_hex(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    from urllib.parse import urlencode
    return redirect("https://twitter.com/i/oauth2/authorize?" + urlencode(params))


@app.route("/oauth/twitter/callback")
@login_required
def oauth_twitter_callback():
    import base64
    code = request.args.get("code")
    verifier = session.pop("twitter_verifier", None)
    if not code or not verifier:
        return redirect(url_for("accounts_page"))
    credentials = base64.b64encode(
        f"{config.TWITTER_CLIENT_ID}:{config.TWITTER_CLIENT_SECRET}".encode()
    ).decode()
    resp = requests.post(
        "https://api.twitter.com/2/oauth2/token",
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.TWITTER_REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    if resp.status_code != 200:
        return redirect(url_for("accounts_page"))
    tokens = resp.json()
    access_token = tokens.get("access_token")
    # Fetch user profile
    me = requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"user.fields": "name,username,public_metrics"},
    ).json().get("data", {})
    db.upsert_account(
        user_id=current_user.id, platform="twitter",
        platform_user_id=me.get("id", ""),
        username=me.get("username", ""),
        display_name=me.get("name", ""),
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", ""),
        followers=me.get("public_metrics", {}).get("followers_count", 0),
    )
    return redirect(url_for("accounts_page"))


# ── Threads OAuth ─────────────────────────────────────────────────────────────

@app.route("/oauth/threads/start")
@login_required
def oauth_threads_start():
    import secrets
    if not config.THREADS_APP_ID:
        return redirect(url_for("accounts_page"))
    state = secrets.token_hex(16)
    session["threads_state"] = state
    from urllib.parse import urlencode
    params = {
        "client_id": config.THREADS_APP_ID,
        "redirect_uri": config.THREADS_REDIRECT_URI,
        "scope": "threads_basic,threads_content_publish,threads_manage_insights",
        "response_type": "code",
        "state": state,
    }
    return redirect("https://threads.net/oauth/authorize?" + urlencode(params))


@app.route("/oauth/threads/callback")
@login_required
def oauth_threads_callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("accounts_page"))
    # Exchange code for short-lived token
    resp = requests.post("https://graph.threads.net/oauth/access_token", data={
        "client_id": config.THREADS_APP_ID,
        "client_secret": config.THREADS_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": config.THREADS_REDIRECT_URI,
        "code": code,
    })
    if resp.status_code != 200:
        return redirect(url_for("accounts_page"))
    short = resp.json()
    # Exchange for long-lived token (60 days)
    long_resp = requests.get("https://graph.threads.net/access_token", params={
        "grant_type": "th_exchange_token",
        "client_secret": config.THREADS_APP_SECRET,
        "access_token": short.get("access_token"),
    })
    access_token = long_resp.json().get("access_token", short.get("access_token"))
    user_id_threads = short.get("user_id", "")
    # Fetch profile
    me = requests.get(
        f"https://graph.threads.net/v1.0/{user_id_threads}",
        params={"fields": "id,username,name,threads_profile_picture_url,threads_biography",
                "access_token": access_token},
    ).json()
    db.upsert_account(
        user_id=current_user.id, platform="threads",
        platform_user_id=str(me.get("id", user_id_threads)),
        username=me.get("username", ""),
        display_name=me.get("name", ""),
        access_token=access_token,
    )
    return redirect(url_for("accounts_page"))


# ── Twitch OAuth ──────────────────────────────────────────────────────────────

@app.route("/oauth/twitch/start")
@login_required
def oauth_twitch_start():
    import secrets
    if not config.TWITCH_CLIENT_ID:
        return redirect(url_for("accounts_page"))
    state = secrets.token_hex(16)
    session["twitch_state"] = state
    from urllib.parse import urlencode
    params = {
        "client_id": config.TWITCH_CLIENT_ID,
        "redirect_uri": config.TWITCH_REDIRECT_URI,
        "response_type": "code",
        "scope": "channel:manage:broadcast channel:read:stream_key clips:edit user:read:email channel:manage:videos",
        "state": state,
    }
    return redirect("https://id.twitch.tv/oauth2/authorize?" + urlencode(params))


@app.route("/oauth/twitch/callback")
@login_required
def oauth_twitch_callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("accounts_page"))
    resp = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": config.TWITCH_CLIENT_ID,
        "client_secret": config.TWITCH_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config.TWITCH_REDIRECT_URI,
    })
    if resp.status_code != 200:
        return redirect(url_for("accounts_page"))
    tokens = resp.json()
    access_token = tokens.get("access_token")
    # Fetch user info
    me_resp = requests.get(
        "https://api.twitch.tv/helix/users",
        headers={"Authorization": f"Bearer {access_token}", "Client-Id": config.TWITCH_CLIENT_ID},
    )
    me = me_resp.json().get("data", [{}])[0]
    db.upsert_account(
        user_id=current_user.id, platform="twitch",
        platform_user_id=me.get("id", ""),
        username=me.get("login", ""),
        display_name=me.get("display_name", ""),
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", ""),
        avatar_url=me.get("profile_image_url", ""),
    )
    return redirect(url_for("accounts_page"))


# ── Snapchat OAuth ────────────────────────────────────────────────────────────

@app.route("/oauth/snapchat/start")
@login_required
def oauth_snapchat_start():
    import secrets
    if not config.SNAP_CLIENT_ID:
        return redirect(url_for("accounts_page"))
    state = secrets.token_hex(16)
    session["snap_state"] = state
    from urllib.parse import urlencode
    params = {
        "client_id": config.SNAP_CLIENT_ID,
        "redirect_uri": config.SNAP_REDIRECT_URI,
        "response_type": "code",
        "scope": "snapchat-marketing-api",
        "state": state,
    }
    return redirect("https://accounts.snapchat.com/accounts/oauth2/auth?" + urlencode(params))


@app.route("/oauth/snapchat/callback")
@login_required
def oauth_snapchat_callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("accounts_page"))
    resp = requests.post(
        "https://accounts.snapchat.com/accounts/oauth2/token",
        auth=(config.SNAP_CLIENT_ID, config.SNAP_CLIENT_SECRET),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.SNAP_REDIRECT_URI,
        },
    )
    if resp.status_code != 200:
        return redirect(url_for("accounts_page"))
    tokens = resp.json()
    access_token = tokens.get("access_token")
    # Fetch user info from Snapchat Marketing API
    me_resp = requests.get(
        "https://adsapi.snapchat.com/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    me = me_resp.json().get("me", {})
    display_name = me.get("display_name") or me.get("email", "Snapchat User")
    db.upsert_account(
        user_id=current_user.id, platform="snapchat",
        platform_user_id=me.get("id", ""),
        username=display_name.lower().replace(" ", ""),
        display_name=display_name,
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", ""),
    )
    return redirect(url_for("accounts_page"))


# ── Higgsfield OAuth (MCP PKCE — no client_secret) ───────────────────────────

_HIGGSFIELD_MCP_BASE = "https://mcp.higgsfield.ai"
_hf_pkce_store: dict = {}  # state -> {code_verifier, user_id}


def _public_callback_base() -> str:
    """
    Return the correct public-facing base URL for OAuth callbacks.

    Render only forwards X-Forwarded-Proto and X-Forwarded-For — NOT
    X-Forwarded-Host — so request.url_root stays as the internal
    http://social-optimize:10000 address even with ProxyFix.

    Priority:
      1. APP_BASE_URL env var (set this on Render to your public URL)
      2. X-Forwarded-Host header if present
      3. request.url_root as last resort
    """
    base = (config.APP_BASE_URL or "").rstrip("/")
    # Reject internal Render addresses (contain a port but no real domain)
    if base and ":" not in base.split("//")[-1]:
        return base  # looks like a real domain with no port — use it
    # Try X-Forwarded-Host (some proxies do send it)
    fwd_host = request.headers.get("X-Forwarded-Host", "")
    fwd_proto = request.headers.get("X-Forwarded-Proto", "https")
    if fwd_host and ":" not in fwd_host:
        return f"{fwd_proto}://{fwd_host}"
    return request.url_root.rstrip("/")


def _hf_discover() -> dict:
    """Fetch OAuth server metadata from Higgsfield MCP discovery endpoint."""
    try:
        r = requests.get(f"{_HIGGSFIELD_MCP_BASE}/.well-known/oauth-authorization-server", timeout=6)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {
        "authorization_endpoint": f"{_HIGGSFIELD_MCP_BASE}/oauth/authorize",
        "token_endpoint": f"{_HIGGSFIELD_MCP_BASE}/oauth/token",
    }


@app.route("/oauth/higgsfield/start")
@login_required
def oauth_higgsfield_start():
    import hashlib
    import base64
    import secrets as _sec
    disc = _hf_discover()
    auth_ep = disc.get("authorization_endpoint", f"{_HIGGSFIELD_MCP_BASE}/oauth/authorize")

    # PKCE — no client_secret required
    verifier = _sec.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = _sec.token_urlsafe(16)

    _hf_pkce_store[state] = {
        "code_verifier": verifier,
        "token_endpoint": disc.get("token_endpoint", f"{_HIGGSFIELD_MCP_BASE}/oauth/token"),
        "user_id": current_user.id,
    }

    callback_uri = _public_callback_base() + "/oauth/higgsfield/callback"
    from urllib.parse import urlencode
    qs = urlencode({
        "response_type": "code",
        "client_id": "social-money",
        "redirect_uri": callback_uri,
        "scope": "openid profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return redirect(f"{auth_ep}?{qs}")


@app.route("/oauth/higgsfield/callback")
@login_required
def oauth_higgsfield_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error or not code:
        return redirect(url_for("accounts_page") + "?error=higgsfield_auth_failed")

    pkce = _hf_pkce_store.pop(state, None)
    if not pkce:
        return redirect(url_for("accounts_page") + "?error=higgsfield_state_mismatch")

    callback_uri = _public_callback_base() + "/oauth/higgsfield/callback"
    try:
        resp = requests.post(
            pkce["token_endpoint"],
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_uri,
                "client_id": "social-money",
                "code_verifier": pkce["code_verifier"],
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        tokens = resp.json()
        access_token = tokens.get("access_token", "")
    except Exception:
        return redirect(url_for("accounts_page") + "?error=higgsfield_token_failed")

    if not access_token:
        return redirect(url_for("accounts_page") + "?error=higgsfield_no_token")

    db.upsert_account(
        user_id=pkce["user_id"],
        platform="higgsfield",
        platform_user_id=pkce["user_id"],
        username="higgsfield",
        display_name="Social Money AI",
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", ""),
        is_active=True,
    )
    return redirect(url_for("accounts_page") + "?connected=higgsfield")


def _get_user_higgsfield_token(user_id: int) -> str:
    """Return this user's Higgsfield OAuth token (DB first, env var fallback)."""
    accounts = db.get_accounts(user_id=user_id)
    for acc in accounts:
        if acc.get("platform") == "higgsfield" and acc.get("is_active"):
            tok = acc.get("access_token", "")
            if tok:
                return tok
    return config.HIGGSFIELD_MCP_TOKEN  # global fallback


# ── Madison Avenue (unified CRM: Contacts + Inbox + Engagement + Outreach) ─────

@app.route("/madison-avenue")
@login_required
def madison_avenue_page():
    return render_template("madison_avenue.html", active_page="madison_avenue")


# ── Contacts ─────────────────────────────────────────────────────────────────

@app.route("/contacts")
@login_required
def contacts_page():
    platform_filter = request.args.get("platform")
    search = request.args.get("q")
    contacts = db.get_contacts(platform=platform_filter, search=search, limit=200, user_id=current_user.id)
    total = db.count_contacts(user_id=current_user.id)
    platforms = ["youtube", "tiktok", "instagram", "phone", "other"]
    return render_template("contacts.html", contacts=contacts, total=total,
                           platforms=platforms, active_platform=platform_filter, search=search)


@app.route("/api/contacts", methods=["GET"])
@login_required
def api_contacts():
    contacts = db.get_contacts(
        platform=request.args.get("platform"), search=request.args.get("q"),
        limit=int(request.args.get("limit", 100)), offset=int(request.args.get("offset", 0)),
        user_id=current_user.id,
    )
    return jsonify(contacts)


@app.route("/api/contacts/import/csv", methods=["POST"])
@login_required
def import_contacts_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f or not allowed_file(f.filename):
        return jsonify({"error": "Invalid file type. Use CSV."}), 400
    platform = request.form.get("platform", "other")
    content = f.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    contacts = []
    for row in reader:
        name = row.get("name") or row.get("Name") or row.get("Full Name") or row.get("full_name") or ""
        if not name.strip():
            first = row.get("First Name") or row.get("first_name") or ""
            last = row.get("Last Name") or row.get("last_name") or ""
            name = f"{first} {last}".strip()
        if not name:
            continue
        contacts.append({
            "name": name.strip(),
            "handle": (row.get("handle") or row.get("username") or row.get("Handle") or "").strip(),
            "email": (row.get("email") or row.get("Email") or row.get("E-mail Address") or "").strip(),
            "phone": (row.get("phone") or row.get("Phone") or row.get("Mobile Phone") or "").strip(),
            "platform": platform, "avatar_url": "", "followers": 0, "tags": "[]",
        })
    count = db.insert_contacts_bulk(contacts, user_id=current_user.id)
    return jsonify({"imported": count})


@app.route("/api/contacts/import/vcf", methods=["POST"])
@login_required
def import_contacts_vcf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    content = f.read().decode("utf-8", errors="replace")
    contacts = []
    try:
        for vcard in vobject.readComponents(content):
            name = ""
            try:
                name = str(vcard.fn.value)
            except Exception:
                try:
                    n = vcard.n.value
                    name = f"{n.given} {n.family}".strip()
                except Exception:
                    pass
            email = ""
            try:
                email = str(vcard.email.value)
            except Exception:
                pass
            phone = ""
            try:
                phone = str(vcard.tel.value)
            except Exception:
                pass
            if name:
                contacts.append({"name": name, "handle": "", "email": email, "phone": phone,
                                  "platform": "phone", "avatar_url": "", "followers": 0, "tags": "[]"})
    except Exception as e:
        return jsonify({"error": f"Failed to parse vCard: {e}"}), 400
    count = db.insert_contacts_bulk(contacts, user_id=current_user.id)
    return jsonify({"imported": count})


@app.route("/api/contacts/import/manual", methods=["POST"])
@login_required
def import_contacts_manual():
    data = request.json
    contacts = data.get("contacts", [])
    cleaned = []
    for c in contacts:
        if not c.get("name"):
            continue
        cleaned.append({
            "name": c.get("name", "").strip(), "handle": c.get("handle", "").strip(),
            "email": c.get("email", "").strip(), "phone": c.get("phone", "").strip(),
            "platform": c.get("platform", "other"), "avatar_url": c.get("avatar_url", ""),
            "followers": int(c.get("followers", 0)), "tags": json.dumps(c.get("tags", [])),
        })
    count = db.insert_contacts_bulk(cleaned, user_id=current_user.id)
    return jsonify({"imported": count})


@app.route("/api/contacts/clear", methods=["POST"])
@login_required
def clear_contacts():
    platform = request.json.get("platform") if request.json else None
    db.delete_contacts(platform=platform, user_id=current_user.id)
    return jsonify({"status": "cleared"})


# ── Outreach / Campaigns ─────────────────────────────────────────────────────

@app.route("/outreach")
@login_required
def outreach_page():
    campaigns = db.get_campaigns(current_user.id)
    return render_template("outreach.html", campaigns=campaigns, active_page="outreach")


@app.route("/api/outreach/campaigns", methods=["POST"])
@login_required
def create_campaign():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    type_ = data.get("type", "email")
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not name or not body:
        return jsonify({"error": "Name and body are required"}), 400
    if type_ not in ("email", "sms"):
        return jsonify({"error": "Type must be email or sms"}), 400
    cid = db.create_campaign(current_user.id, name, type_, subject, body)
    return jsonify({"id": cid, "ok": True})


@app.route("/api/outreach/campaigns/<int:cid>", methods=["DELETE"])
@login_required
def delete_campaign(cid):
    db.delete_campaign(cid, current_user.id)
    return jsonify({"ok": True})


@app.route("/api/outreach/campaigns/<int:cid>/send", methods=["POST"])
@login_required
def send_campaign(cid):
    campaign = db.get_campaign(cid, current_user.id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.json or {}
    contact_ids = data.get("contact_ids") or []  # empty = all contacts with valid channel
    platform_filter = data.get("platform")  # optional filter

    # Get target contacts
    all_contacts = db.get_contacts(platform=platform_filter, limit=5000, user_id=current_user.id)
    if contact_ids:
        all_contacts = [c for c in all_contacts if c["id"] in contact_ids]

    if campaign["type"] == "email":
        targets = [c for c in all_contacts if c.get("email")]
    else:
        targets = [c for c in all_contacts if c.get("phone")]

    if not targets:
        return jsonify({"error": "No contacts with valid email/phone found"}), 400

    sent, failed = 0, 0
    if campaign["type"] == "email":
        sent, failed = _send_email_campaign(campaign, targets, current_user.id)
    else:
        sent, failed = _send_sms_campaign(campaign, targets, current_user.id)

    db.increment_campaign_sent(cid, sent)
    return jsonify({"ok": True, "sent": sent, "failed": failed, "total": len(targets)})


def _send_email_campaign(campaign, contacts, user_id):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    if not config.SMTP_HOST or not config.SMTP_USER:
        # Log as sent anyway if no SMTP configured (dev mode)
        for c in contacts:
            db.log_send(campaign["id"], c["id"], user_id, "sent")
        return len(contacts), 0

    sent, failed = 0, 0
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASS)
            for contact in contacts:
                try:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = campaign["subject"] or campaign["name"]
                    msg["From"] = config.SMTP_FROM
                    msg["To"] = contact["email"]
                    body = campaign["body"].replace("{{name}}", contact["name"] or "")
                    msg.attach(MIMEText(body, "plain"))
                    msg.attach(MIMEText(f"<p>{body}</p>", "html"))
                    server.sendmail(config.SMTP_FROM, contact["email"], msg.as_string())
                    db.log_send(campaign["id"], contact["id"], user_id, "sent")
                    sent += 1
                except Exception as e:
                    db.log_send(campaign["id"], contact["id"], user_id, "failed", str(e))
                    failed += 1
    except Exception as e:
        for c in contacts:
            db.log_send(campaign["id"], c["id"], user_id, "failed", str(e))
        return 0, len(contacts)
    return sent, failed


def _send_sms_campaign(campaign, contacts, user_id):
    from utils.twilio_client import send_sms_bulk, _is_configured

    if not _is_configured():
        for c in contacts:
            db.log_send(campaign["id"], c["id"], user_id, "sent")
        return len(contacts), 0

    status_cb = config.APP_BASE_URL + "/twilio/status"
    try:
        sent, failed, errors = send_sms_bulk(
            contacts=contacts,
            body_template=campaign["body"],
            status_callback=status_cb,
        )
        for i, c in enumerate(contacts):
            status = "failed" if i >= sent else "sent"
            err = errors[i - sent] if status == "failed" and (i - sent) < len(errors) else None
            db.log_send(campaign["id"], c["id"], user_id, status, err)
    except Exception as e:
        for c in contacts:
            db.log_send(campaign["id"], c["id"], user_id, "failed", str(e))
        return 0, len(contacts)
    return sent, failed


@app.route("/api/outreach/campaigns/<int:cid>/sends")
@login_required
def campaign_sends(cid):
    campaign = db.get_campaign(cid, current_user.id)
    if not campaign:
        return jsonify({"error": "Not found"}), 404
    sends = db.get_campaign_sends(cid)
    return jsonify(sends)


# ── Twilio Webhooks ───────────────────────────────────────────────────────────

@app.route("/twilio/status", methods=["POST"])
def twilio_status_callback():
    """Twilio calls this URL to report delivery status updates for outbound SMS."""
    from utils.twilio_client import validate_signature
    sig = request.headers.get("X-Twilio-Signature", "")
    if config.TWILIO_AUTH_TOKEN and not validate_signature(request.url, request.form, sig):
        return jsonify({"error": "Invalid signature"}), 403

    sid    = request.form.get("MessageSid")
    status = request.form.get("MessageStatus")  # queued, sent, delivered, failed, undelivered
    if sid and status:
        db.update_send_status_by_sid(sid, status)
    return ("", 204)


@app.route("/twilio/voice", methods=["POST"])
def twilio_voice_inbound():
    """Twilio calls this URL when someone calls your Twilio number.
    Webhook URL to set in Twilio console:
        https://socialoptimize.online/twilio/voice
    """
    from utils.twilio_client import validate_signature
    sig = request.headers.get("X-Twilio-Signature", "")
    if config.TWILIO_AUTH_TOKEN and not validate_signature(request.url, request.form, sig):
        return ("Forbidden", 403)

    call_sid = request.form.get("CallSid", "")
    from_num = request.form.get("From", "")
    to_num   = request.form.get("To", "")
    status   = request.form.get("CallStatus", "ringing")
    city     = request.form.get("FromCity")
    state    = request.form.get("FromState")
    country  = request.form.get("FromCountry")

    db.log_inbound_call(call_sid, from_num, to_num, status, city, state, country)

    greeting = (
        "Hello! You've reached Social Money. "
        "We're not available right now. "
        "Please leave a message after the tone and we'll get back to you shortly. "
        "Thank you!"
    )
    recording_cb = config.APP_BASE_URL + "/twilio/voice/recording"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{greeting}</Say>
  <Record
    maxLength="120"
    playBeep="true"
    recordingStatusCallback="{recording_cb}"
    recordingStatusCallbackMethod="POST"
    transcribe="true"
    transcribeCallback="{config.APP_BASE_URL}/twilio/voice/transcription"
  />
  <Say voice="Polly.Joanna">Thank you for calling. Goodbye!</Say>
</Response>"""
    return (twiml, 200, {"Content-Type": "text/xml"})


@app.route("/twilio/voice/status", methods=["POST"])
def twilio_voice_status():
    """Twilio posts call status updates (completed, busy, no-answer, etc.)
    Set as Status Callback URL in Twilio console.
    """
    from utils.twilio_client import validate_signature
    sig = request.headers.get("X-Twilio-Signature", "")
    if config.TWILIO_AUTH_TOKEN and not validate_signature(request.url, request.form, sig):
        return ("Forbidden", 403)

    call_sid = request.form.get("CallSid", "")
    status   = request.form.get("CallStatus", "")
    duration = request.form.get("CallDuration", 0)
    if call_sid:
        db.update_inbound_call(call_sid, call_status=status, duration=int(duration or 0))
    return ("", 204)


@app.route("/twilio/voice/recording", methods=["POST"])
def twilio_voice_recording():
    """Twilio posts recording details once a recording is ready."""
    from utils.twilio_client import validate_signature
    sig = request.headers.get("X-Twilio-Signature", "")
    if config.TWILIO_AUTH_TOKEN and not validate_signature(request.url, request.form, sig):
        return ("Forbidden", 403)

    call_sid     = request.form.get("CallSid", "")
    rec_sid      = request.form.get("RecordingSid", "")
    rec_url      = request.form.get("RecordingUrl", "")
    rec_duration = request.form.get("RecordingDuration", 0)
    rec_status   = request.form.get("RecordingStatus", "")

    if call_sid and rec_sid and rec_status == "completed":
        db.update_inbound_call(
            call_sid,
            recording_sid=rec_sid,
            recording_url=rec_url + ".mp3",
            recording_duration=int(rec_duration or 0),
        )
    return ("", 204)


@app.route("/twilio/voice/transcription", methods=["POST"])
def twilio_voice_transcription():
    """Twilio posts transcription when it finishes transcribing a recording."""
    call_sid      = request.form.get("CallSid", "")
    transcription = request.form.get("TranscriptionText", "")
    trans_status  = request.form.get("TranscriptionStatus", "")

    if call_sid and trans_status == "completed" and transcription:
        db.update_inbound_call(call_sid, transcription=transcription)
    return ("", 204)


@app.route("/api/calls")
@login_required
def api_get_calls():
    """Return recent inbound calls for the dashboard."""
    calls = db.get_inbound_calls(limit=50)
    return jsonify(calls)


@app.route("/twilio/inbound", methods=["POST"])
def twilio_inbound_sms():
    """Twilio calls this URL when someone texts your Twilio number.
    Webhook URL: https://socialoptimize.online/twilio/inbound
    """
    from utils.twilio_client import validate_signature, parse_inbound_sms
    sig = request.headers.get("X-Twilio-Signature", "")
    if config.TWILIO_AUTH_TOKEN and not validate_signature(request.url, request.form, sig):
        return ("Forbidden", 403)

    msg = parse_inbound_sms(request.form)
    db.log_inbound_sms(
        from_=msg["from_"],
        to=msg["to"],
        body=msg["body"],
        message_sid=msg["message_sid"],
    )

    # Push an in-app notification to all admin users
    try:
        admins = db.get_admin_users()
        for admin in admins:
            send_notification(admin["id"], "inbound_sms", {
                "from": msg["from_"],
                "preview": msg["body"][:80],
            })
    except Exception:
        pass

    # Auto-reply
    auto_reply = "Thanks for reaching out! We received your message and will get back to you shortly."
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>{auto_reply}</Message>
</Response>"""
    return (twiml, 200, {"Content-Type": "text/xml"})


@app.route("/inbox")
@login_required
def inbox_page():
    sms = db.get_inbound_sms(limit=100)
    calls = db.get_inbound_calls(limit=50)
    return render_template("inbox.html", sms=sms, calls=calls, active_page="inbox")


@app.route("/api/messages")
@login_required
def api_get_messages():
    sms = db.get_inbound_sms(limit=100)
    calls = db.get_inbound_calls(limit=50)
    return jsonify({"sms": sms, "calls": calls})


@app.route("/api/messages/reply", methods=["POST"])
@login_required
def api_reply_sms():
    data = request.json or {}
    to = (data.get("to") or "").strip()
    body = (data.get("body") or "").strip()
    if not to or not body:
        return jsonify({"error": "to and body are required"}), 400
    try:
        from utils.twilio_client import send_sms
        result = send_sms(to=to, body=body)
        return jsonify({"ok": True, "sid": result["sid"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/settings")
@login_required
def settings_page():
    user = db.get_user_by_id(current_user.id)
    return render_template("settings.html", user=user)


@app.route("/api/settings", methods=["POST"])
@login_required
def api_update_settings():
    data = request.json or {}
    updates = {}
    if "name" in data:
        updates["name"] = data["name"].strip()
    if "notify_email" in data:
        updates["notify_email"] = 1 if data["notify_email"] else 0
    if "webhook_url" in data:
        updates["webhook_url"] = (data["webhook_url"] or "").strip()
    if "assistant_enabled" in data:
        updates["assistant_enabled"] = 1 if data["assistant_enabled"] else 0
    if updates:
        db.update_user(current_user.id, **updates)
    return jsonify({"status": "saved"})


@app.route("/api/research/preview", methods=["POST"])
def api_research_preview():
    topic = (request.json or {}).get("topic", "").strip()
    if not topic or len(topic) < 4:
        return jsonify({"facts": [], "sources": [], "data_points": []})
    try:
        from generators.researcher import research_topic
        brief = research_topic(topic)
        return jsonify({
            "summary": brief.summary[:400] if brief.summary else "",
            "key_facts": brief.key_facts[:10],
            "data_points": brief.data_points[:10],
            "sources": brief.sources,
            "related_topics": brief.related_topics[:5],
        })
    except Exception as e:
        return jsonify({"error": str(e), "facts": [], "sources": [], "data_points": []})


@app.route("/api/settings/platform-creds", methods=["POST"])
@login_required
def api_save_platform_creds():
    """Save platform OAuth credentials to DB and patch config live."""
    data = request.json or {}
    platform = data.get("platform", "").lower()

    PLATFORM_CONFIG = {
        "youtube":   [("YOUTUBE_CLIENT_ID", "client_id"), ("YOUTUBE_CLIENT_SECRET", "client_secret")],
        "tiktok":    [("TIKTOK_CLIENT_KEY", "client_id"), ("TIKTOK_CLIENT_SECRET", "client_secret")],
        "facebook":  [("FACEBOOK_APP_ID", "client_id"), ("FACEBOOK_APP_SECRET", "client_secret")],
        "instagram": [("FACEBOOK_APP_ID", "client_id"), ("FACEBOOK_APP_SECRET", "client_secret")],
        "twitter":   [("TWITTER_CLIENT_ID", "client_id"), ("TWITTER_CLIENT_SECRET", "client_secret")],
        "threads":   [("THREADS_APP_ID", "client_id"), ("THREADS_APP_SECRET", "client_secret")],
        "twitch":    [("TWITCH_CLIENT_ID", "client_id"), ("TWITCH_CLIENT_SECRET", "client_secret")],
        "snapchat":  [("SNAP_CLIENT_ID", "client_id"), ("SNAP_CLIENT_SECRET", "client_secret")],
        "linkedin":  [("LINKEDIN_CLIENT_ID", "client_id"), ("LINKEDIN_CLIENT_SECRET", "client_secret")],
    }

    if platform not in PLATFORM_CONFIG:
        return jsonify({"error": "Unknown platform"}), 400

    client_id = (data.get("client_id") or "").strip()
    client_secret = (data.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return jsonify({"error": "Both Client ID and Client Secret are required"}), 400

    for config_key, field in PLATFORM_CONFIG[platform]:
        val = client_id if field == "client_id" else client_secret
        db.set_setting(f"oauth_{config_key}", val)
        setattr(config, config_key, val)

    return jsonify({"status": "saved", "platform": platform, "ready": True})


@app.route("/api/settings/api-key", methods=["POST"])
@login_required
def api_save_api_key():
    """Save an API key to DB and patch config live."""
    data = request.json or {}
    service = data.get("service", "").upper()
    key = (data.get("key") or "").strip()

    ALLOWED = {
        "ANTHROPIC_API_KEY", "PIXABAY_API_KEY", "GOOGLE_API_KEY",
        "HIGGSFIELD_MCP_TOKEN", "ELEVENLABS_API_KEY", "PIXABAY_API_KEY",
    }
    if service not in ALLOWED:
        return jsonify({"error": "Unknown service"}), 400
    if not key:
        return jsonify({"error": "Key is required"}), 400

    db.set_setting(f"apikey_{service}", key)
    setattr(config, service, key)
    return jsonify({"status": "saved", "service": service})


def _load_platform_creds_from_db():
    """Load OAuth credentials and API keys saved via UI into config at startup."""
    oauth_keys = [
        "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
        "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
        "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET",
        "TWITTER_CLIENT_ID", "TWITTER_CLIENT_SECRET",
        "THREADS_APP_ID", "THREADS_APP_SECRET",
        "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET",
        "SNAP_CLIENT_ID", "SNAP_CLIENT_SECRET",
        "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET",
    ]
    for key in oauth_keys:
        val = db.get_setting(f"oauth_{key}")
        if val and not getattr(config, key, ""):
            setattr(config, key, val)

    api_keys = [
        "ANTHROPIC_API_KEY", "PIXABAY_API_KEY", "GOOGLE_API_KEY",
        "HIGGSFIELD_MCP_TOKEN", "ELEVENLABS_API_KEY", "PIXABAY_API_KEY",
    ]
    for key in api_keys:
        val = db.get_setting(f"apikey_{key}")
        if val and not getattr(config, key, ""):
            setattr(config, key, val)


@app.route("/api/settings/check")
def api_settings_check():
    # Higgsfield is connected if: (a) env var token set, OR (b) user has OAuth'd via Accounts page
    global_tok = config.HIGGSFIELD_MCP_TOKEN or ""
    # Strip accidental URL entries (user pasted the MCP URL instead of a token)
    if global_tok.startswith("http://") or global_tok.startswith("https://"):
        global_tok = ""

    user_hf_connected = False
    # Check user's connected social accounts (OAuth-based platforms)
    user_platforms = set()
    try:
        if current_user.is_authenticated:
            accounts = db.get_accounts(user_id=current_user.id)
            user_platforms = {a["platform"] for a in accounts if a.get("is_active", True)}
            user_hf_connected = any(
                a.get("platform") == "higgsfield" and a.get("is_active") and a.get("access_token")
                for a in accounts
            )
    except Exception:
        pass

    higgsville_ok = bool(global_tok) or user_hf_connected

    from generators.ai_router import _available_models as _avm
    _ai_available = _avm()
    return jsonify({
        "anthropic":        bool(config.ANTHROPIC_API_KEY),
        "pixabay":          bool(config.PIXABAY_API_KEY),
        "elevenlabs":       bool(getattr(config, "ELEVENLABS_API_KEY", "")),
        "google_flow":      bool(config.GOOGLE_API_KEY),
        "higgsville":       higgsville_ok,
        "youtube":          bool(config.YOUTUBE_CLIENT_ID) or "youtube" in user_platforms,
        "tiktok":           bool(config.TIKTOK_CLIENT_KEY) or "tiktok" in user_platforms,
        "instagram":        bool(config.INSTAGRAM_ACCESS_TOKEN) or "instagram" in user_platforms,
        # AI script engine key status
        "ai_keys": {
            "claude":      bool(config.ANTHROPIC_API_KEY and config.ANTHROPIC_API_KEY.startswith("sk-")),
            "groq":        bool(getattr(config, "GROQ_API_KEY", "")),
            "openrouter":  bool(getattr(config, "OPENROUTER_API_KEY", "")),
            "deepseek":    bool(getattr(config, "DEEPSEEK_API_KEY", "")),
            "gemini":      bool(config.GOOGLE_API_KEY),
            "qwen":        bool(getattr(config, "QWEN_API_KEY", "")),
        },
        "ai_available_models": sorted(_ai_available),
    })


@app.route("/api/debug/higgsville")
def api_debug_higgsville():
    """Diagnostic endpoint — shows which env var name supplied the Higgsfield token."""
    import os
    names = [
        "HIGGSFIELD_MCP_TOKEN", "HIGGSFIELD_TOKEN",
        "HIGGSVILLE_TOKEN", "HIGGSVILLE_MCP_TOKEN", "HIGGSFIELD_API_KEY",
    ]
    found = {n: bool(os.getenv(n)) for n in names}
    tok = config.HIGGSFIELD_MCP_TOKEN or ""
    return jsonify({
        "token_set": bool(tok),
        "token_length": len(tok),
        "token_preview": tok[:8] + "..." if len(tok) > 8 else "(empty)",
        "env_vars_checked": found,
        "mcp_url": config.HIGGSFIELD_MCP_URL,
    })


@app.route("/api/test-ai-keys")
def api_test_ai_keys():
    """Live-test every configured AI key with a minimal real API call."""
    import time as _time
    results = {}

    def _test(name, fn):
        t0 = _time.time()
        try:
            fn()
            results[name] = {"ok": True, "ms": int((_time.time() - t0) * 1000)}
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:200], "ms": int((_time.time() - t0) * 1000)}

    # Claude
    if config.ANTHROPIC_API_KEY:
        def _claude():
            import anthropic as _a
            _a.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=5,
                messages=[{"role": "user", "content": "Hi"}])
        _test("claude", _claude)

    # Groq
    if getattr(config, "GROQ_API_KEY", ""):
        def _groq():
            from openai import OpenAI as _OAI
            _OAI(api_key=config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1").chat.completions.create(
                model="llama-3.1-8b-instant", max_tokens=5,
                messages=[{"role": "user", "content": "Hi"}])
        _test("groq", _groq)

    # OpenRouter
    if getattr(config, "OPENROUTER_API_KEY", ""):
        def _openrouter():
            from openai import OpenAI as _OAI
            _OAI(api_key=config.OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1").chat.completions.create(
                model="meta-llama/llama-3.1-8b-instruct:free", max_tokens=5,
                messages=[{"role": "user", "content": "Hi"}])
        _test("openrouter", _openrouter)

    # Gemini
    if config.GOOGLE_API_KEY:
        def _gemini():
            from google import genai as _g
            _g.Client(api_key=config.GOOGLE_API_KEY).models.generate_content(
                model="gemini-2.0-flash", contents="Hi")
        _test("gemini", _gemini)

    # DeepSeek
    if getattr(config, "DEEPSEEK_API_KEY", ""):
        def _deepseek():
            from openai import OpenAI as _OAI
            _OAI(api_key=config.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com").chat.completions.create(
                model="deepseek-chat", max_tokens=5,
                messages=[{"role": "user", "content": "Hi"}])
        _test("deepseek", _deepseek)

    working = [k for k, v in results.items() if v["ok"]]
    return jsonify({"results": results, "working": working,
                    "verdict": "OK" if working else "ALL KEYS BROKEN"})


# ── The Forge ─────────────────────────────────────────────────────────────────

_studio_jobs: dict = {}
_studio_events: dict = {}
_studio_lock = threading.Lock()


def _push_studio_event(job_id: str, data: dict):
    import time as _time
    payload = f"data: {json.dumps(data)}\n\n"
    with _studio_lock:
        if job_id not in _studio_events:
            _studio_events[job_id] = []
        _studio_events[job_id].append(payload)
        if len(_studio_events[job_id]) > _JOB_MAX_EVENTS:
            _studio_events[job_id] = _studio_events[job_id][-_JOB_MAX_EVENTS:]
        if data.get("status") in ("done", "error"):
            _studio_events[f"_ts_{job_id}"] = _time.time()


def _run_studio_thread(studio_job_id: str, params: dict, user_id: int = None):
    from generators.production_engine import ProductionStudioEngine
    niche = params["niche"]

    # Create a DB job record so the output appears in the Jobs list
    db_job_id = db.create_job(
        topic=niche, format="long", platforms=[],
        audience=params.get("audience", "general public"),
        voice=params.get("voice") or config.DEFAULT_VOICE,
        style=params.get("thumbnail_style", "fire"),
        privacy=params.get("privacy", "private"),
        user_id=user_id,
    )
    db.update_job(db_job_id, status="running", progress=5, current_step="Starting The Forge…")


    def _cb(msg: str, pct: int):
        db.update_job(db_job_id, progress=pct, current_step=msg)
        with _studio_lock:
            if studio_job_id in _studio_jobs:
                _studio_jobs[studio_job_id].update({"progress": pct, "step": msg, "status": "running"})
        _push_studio_event(studio_job_id, {"progress": pct, "step": msg, "status": "running"})

    with _studio_lock:
        _studio_jobs[studio_job_id] = {
            "status": "running", "progress": 0, "step": "Initialising…", "db_job_id": db_job_id,
        }
    try:
        user_tier = params.get("subscription_tier", "free")
        engine = ProductionStudioEngine(
            monthly_budget=params.get("monthly_budget", 500), progress_callback=_cb,
            subscription_tier=user_tier,
        )
        result = engine.run_daily_pipeline(
            niche=niche, remaining_credits=params.get("remaining_credits", 500),
            target_duration=params.get("target_duration", 480),
            audience=params.get("audience", ""), is_portrait=params.get("is_portrait", False),
            voice=params.get("voice") or config.DEFAULT_VOICE,
            thumbnail_style=params.get("thumbnail_style", "fire"),
            privacy=params.get("privacy", "private"), dry_run=params.get("dry_run", False),
            research_enabled=params.get("research_enabled", True),
            competitor_titles=params.get("competitor_titles") or [],
            platforms=[],
        )
        result_dict = result.model_dump()
        job_title = result.seo.title_final if result.seo else niche

        # Save completed output to the DB job
        db.update_job(
            db_job_id, status="done", progress=100, current_step="Complete!",
            title=job_title,
            video_path=result.video_path or None,
            audio_path=result.audio_path or None,
            thumbnail_path=result.thumbnail_path or None,
            manifest_path=result.manifest_path or None,
            completed_at=datetime.now().isoformat(),
        )

        with _studio_lock:
            _studio_jobs[studio_job_id].update({
                "status": "done", "progress": 100,
                "step": "Production complete!", "result": result_dict,
                "db_job_id": db_job_id,
            })
        _push_studio_event(studio_job_id, {
            "progress": 100, "step": "Production complete!",
            "status": "done", "result": result_dict, "db_job_id": db_job_id,
        })
        if user_id:
            try:
                from notifications import send_notification
                send_notification(user_id, "job_complete", {
                    "job_id": db_job_id, "title": job_title,
                })
            except Exception:
                pass
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        db.update_job(db_job_id, status="error", error_msg=str(e), current_step="Failed")
        with _studio_lock:
            _studio_jobs[studio_job_id].update({
                "status": "error", "step": f"Error: {e}", "traceback": tb, "db_job_id": db_job_id,
            })
        _push_studio_event(studio_job_id, {
            "status": "error", "step": f"Error: {e}", "traceback": tb, "db_job_id": db_job_id,
        })


@app.route("/studio")
@login_required
def studio_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a["is_active"]}
    templates = db.get_templates(user_id=current_user.id)
    return render_template(
        "studio.html", connected_platforms=connected, voices=config.AVAILABLE_VOICES,
        higgsfield_models=config.HIGGSVILLE_MODELS, config=config, templates=templates,
        google_tts_voices=config.GOOGLE_TTS_VOICES,
        google_api_key=bool(config.GOOGLE_API_KEY),
    )


@app.route("/api/studio/run", methods=["POST"])
@login_required
def api_studio_run():
    allowed, err = check_usage_gate(current_user.id)
    if not allowed:
        return jsonify({"error": err, "upgrade": True}), 403
    data = request.json or {}
    niche = (data.get("niche") or "").strip()
    if not niche:
        return jsonify({"error": "Niche is required"}), 400
    studio_job_id = str(uuid.uuid4())
    _u_tier = config.TIERS.get(current_user.subscription_tier, config.TIERS["free"])
    _credits_remaining = max(0, _u_tier["higgsfield_credits"] - (current_user.credits_used or 0))
    params = {
        "niche": niche,
        "remaining_credits": _credits_remaining,
        "monthly_budget": _credits_remaining,
        "subscription_tier": current_user.subscription_tier or "free",
        "target_duration": int(data.get("target_duration") or 480),
        "audience": (data.get("audience") or "").strip(),
        "is_portrait": bool(data.get("is_portrait", False)),
        "voice": data.get("voice") or config.DEFAULT_VOICE,
        "thumbnail_style": data.get("thumbnail_style") or "fire",
        "privacy": data.get("privacy") or "private",
        "dry_run": bool(data.get("dry_run", False)),
        "research_enabled": bool(data.get("research_enabled", True)),
        "competitor_titles": data.get("competitor_titles") or [],
        "platforms": data.get("platforms") or [],
    }
    t = threading.Thread(target=_run_studio_thread, args=(studio_job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"studio_job_id": studio_job_id})


@app.route("/api/studio/stream/<studio_job_id>")
@login_required
def studio_stream(studio_job_id):
    def generate():
        last_idx = 0
        while True:
            with _studio_lock:
                events = _studio_events.get(studio_job_id, [])
                new = events[last_idx:]
                last_idx = len(events)
                job = _studio_jobs.get(studio_job_id, {})
            for event in new:
                yield event
            if job.get("status") in ("done", "error"):
                if not new:
                    yield f"data: {json.dumps({'status': job.get('status'), 'progress': job.get('progress', 0)})}\n\n"
                time.sleep(0.3)
                break
            time.sleep(0.4)
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/studio/status/<studio_job_id>")
@login_required
def studio_status(studio_job_id):
    with _studio_lock:
        job = _studio_jobs.get(studio_job_id)
    if job is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


# ── Cinema House ──────────────────────────────────────────────────────────────

_hw_jobs: dict = {}
_hw_events: dict = {}
_hw_lock = threading.Lock()


def _push_hw_event(job_id: str, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _hw_lock:
        if job_id not in _hw_events:
            _hw_events[job_id] = []
        _hw_events[job_id].append(payload)


def _run_hw_thread(hw_job_id: str, params: dict, user_id: int = None):
    from generators.hollywood_engine import HollywoodEngine
    from generators import ai_video_generator as _avg, higgsfield_mcp as _hmcp
    if user_id:
        _tok = _get_user_higgsfield_token(user_id)
        _avg._session_token.value = _tok
        _hmcp._session_token.value = _tok
    topic = params["topic"]

    # Create a DB job record so the output appears in the Jobs list
    db_job_id = db.create_job(
        topic=topic, format="hollywood", platforms=[],
        audience=params.get("audience", "general public"),
        voice=params.get("voice") or config.GOOGLE_TTS_VOICE or config.DEFAULT_VOICE,
        style=params.get("thumbnail_style", "dark"),
        privacy=params.get("privacy", "private"),
        user_id=user_id,
    )
    db.update_job(db_job_id, status="running", progress=5, current_step="Starting Cinema House…")

    def _cb(msg: str, pct: int):
        db.update_job(db_job_id, progress=pct, current_step=msg)
        with _hw_lock:
            if hw_job_id in _hw_jobs:
                _hw_jobs[hw_job_id].update({"progress": pct, "step": msg, "status": "running"})
        _push_hw_event(hw_job_id, {"progress": pct, "step": msg, "status": "running"})

    with _hw_lock:
        _hw_jobs[hw_job_id] = {
            "status": "running", "progress": 0, "step": "Initialising Hollywood pipeline…",
            "db_job_id": db_job_id,
        }

    try:
        engine = HollywoodEngine(progress_callback=_cb)
        result = engine.run(
            topic=topic,
            target_duration=params.get("target_duration", 600),
            audience=params.get("audience", ""),
            voice=params.get("voice") or None,
            is_portrait=params.get("is_portrait", False),
            thumbnail_style=params.get("thumbnail_style", "dark"),
            privacy=params.get("privacy", "private"),
            research_enabled=params.get("research_enabled", True),
            competitor_titles=params.get("competitor_titles") or [],
        )
        result_dict = result.model_dump()
        job_title = result.seo.title_final if result.seo else topic

        db.update_job(
            db_job_id, status="done", progress=100, current_step="Complete!",
            title=job_title,
            video_path=result.video_path or None,
            audio_path=result.audio_path or None,
            thumbnail_path=result.thumbnail_path or None,
            manifest_path=result.manifest_path or None,
            completed_at=datetime.now().isoformat(),
        )

        with _hw_lock:
            _hw_jobs[hw_job_id].update({
                "status": "done", "progress": 100,
                "step": "Hollywood production complete!", "result": result_dict,
                "db_job_id": db_job_id,
            })
        _push_hw_event(hw_job_id, {
            "progress": 100, "step": "Hollywood production complete!",
            "status": "done", "result": result_dict, "db_job_id": db_job_id,
        })
        if user_id:
            try:
                from notifications import send_notification
                send_notification(user_id, "job_complete", {
                    "job_id": db_job_id, "title": job_title,
                })
            except Exception:
                pass
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        db.update_job(db_job_id, status="error", error_msg=str(e), current_step="Failed")
        with _hw_lock:
            _hw_jobs[hw_job_id].update({
                "status": "error", "step": f"Error: {e}", "traceback": tb, "db_job_id": db_job_id,
            })
        _push_hw_event(hw_job_id, {
            "status": "error", "step": f"Error: {e}", "traceback": tb, "db_job_id": db_job_id,
        })


@app.route("/hollywood")
@login_required
def hollywood_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a["is_active"]}
    return render_template(
        "hollywood.html",
        connected_platforms=connected,
        voices=config.AVAILABLE_VOICES,
        google_tts_voices=config.GOOGLE_TTS_VOICES,
        google_api_key=bool(config.GOOGLE_API_KEY),
        higgsfield_token=bool(config.HIGGSFIELD_MCP_TOKEN),
        config=config,
    )


@app.route("/api/hollywood/run", methods=["POST"])
@login_required
def api_hollywood_run():
    # Hollywood is a separate premium pipeline — not gated by standard video counter
    data = request.json or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400
    hw_job_id = str(uuid.uuid4())
    params = {
        "topic": topic,
        "target_duration": int(data.get("target_duration") or 600),
        "audience": (data.get("audience") or "").strip(),
        "is_portrait": bool(data.get("is_portrait", False)),
        "voice": data.get("voice") or None,
        "thumbnail_style": data.get("thumbnail_style") or "dark",
        "privacy": data.get("privacy") or "private",
        "research_enabled": bool(data.get("research_enabled", True)),
        "competitor_titles": data.get("competitor_titles") or [],
    }
    t = threading.Thread(target=_run_hw_thread, args=(hw_job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"hw_job_id": hw_job_id})


@app.route("/api/hollywood/stream/<hw_job_id>")
@login_required
def hollywood_stream(hw_job_id):
    def generate():
        last_idx = 0
        while True:
            with _hw_lock:
                events = _hw_events.get(hw_job_id, [])
                new = events[last_idx:]
                last_idx = len(events)
                job = _hw_jobs.get(hw_job_id, {})
            for event in new:
                yield event
            if job.get("status") in ("done", "error"):
                if not new:
                    yield f"data: {json.dumps({'status': job.get('status'), 'progress': job.get('progress', 0)})}\n\n"
                time.sleep(0.3)
                break
            time.sleep(0.4)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/hollywood/status/<hw_job_id>")
@login_required
def hollywood_status(hw_job_id):
    with _hw_lock:
        job = _hw_jobs.get(hw_job_id)
    if job is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


@app.route("/api/hollywood/log/<hw_job_id>")
@login_required
def hollywood_log(hw_job_id):
    """Return all log lines for a Hollywood job (for polling fallback)."""
    with _hw_lock:
        job = _hw_jobs.get(hw_job_id, {})
        events = _hw_events.get(hw_job_id, [])
    # Parse events back to dicts
    log_lines = []
    for raw in events:
        try:
            import json as _json
            d = _json.loads(raw.replace("data: ", "").strip())
            log_lines.append(d)
        except Exception:
            pass
    return jsonify({"job": job, "log": log_lines, "count": len(log_lines)})


@app.route("/api/hollywood/reassemble", methods=["POST"])
@login_required
def api_hollywood_reassemble():
    """Re-assemble video with edited script scenes."""
    data = request.json or {}
    db_job_id = data.get("db_job_id")
    _edited_scenes = data.get("scenes", [])  # [{section_id, narration}, ...]
    # For now, just note the edit was requested and return job URL
    return jsonify({"ok": True, "message": "Re-assembly queued", "job_id": db_job_id})


# ── Hit Factory ───────────────────────────────────────────────────────────────

_music_jobs: dict = {}
_music_events: dict = {}
_music_lock = threading.Lock()


def _push_music_event(job_id: str, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _music_lock:
        _music_events.setdefault(job_id, []).append(payload)


def _run_music_thread(job_id: str, params: dict, user_id: int = None):
    from generators.music_generator import MusicEngine
    from utils import file_manager

    job_dir = file_manager.job_dir(params.get("title", "song"), "music")

    def cb(msg: str, pct: int):
        with _music_lock:
            if job_id in _music_jobs:
                _music_jobs[job_id].update({"progress": pct, "step": msg, "status": "running"})
        _push_music_event(job_id, {"type": "progress", "pct": pct, "message": msg, "status": "running"})

    with _music_lock:
        _music_jobs[job_id] = {"status": "running", "progress": 0, "step": "Starting…"}

    try:
        engine = MusicEngine()
        result = engine.generate(job_dir=job_dir, progress_cb=cb, **params)

        audio_url = f"/api/music/download/{job_id}" if result.get("audio_path") else None

        # Emit lyrics event if we have them
        if result.get("lyrics"):
            _push_music_event(job_id, {"type": "lyrics", "lyrics": result["lyrics"]})

        # Save track to database for DJ booth / library access
        track_record = {
            "id": job_id,
            "title": params.get("title", "Untitled"),
            "genre": params.get("genre", ""),
            "bpm": params.get("bpm", 120),
            "duration": params.get("duration_seconds", 60),
            "audio_url": audio_url,
            "audio_path": result.get("audio_path", ""),
            "lyrics": result.get("lyrics", ""),
            "provider": result.get("provider", "AI"),
            "created_at": datetime.now().isoformat(),
            "user_id": user_id,
        }
        db.set_setting(f"music_track:{job_id}", json.dumps(track_record))

        with _music_lock:
            _music_jobs[job_id].update({"status": "done", "progress": 100, "result": result, "audio_url": audio_url})
        _push_music_event(job_id, {
            "type": "complete",
            "audio_url": audio_url,
            "provider": result.get("provider", "AI"),
            "lyrics": result.get("lyrics", ""),
            "title": result.get("title", ""),
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        with _music_lock:
            _music_jobs[job_id].update({"status": "error", "step": str(e), "traceback": tb})
        _push_music_event(job_id, {"type": "error", "message": str(e)})


@app.route("/music-studio")
@login_required
def music_studio_page():
    return render_template("music_studio.html", active_page="music")


@app.route("/api/music/generate", methods=["POST"])
@login_required
def api_music_generate():
    data = request.json or {}
    job_id = str(uuid.uuid4())
    params = {
        "title": (data.get("title") or "My Song").strip(),
        "genre": data.get("genre") or "pop",
        "mood": data.get("mood") or "energetic",
        "bpm": int(data.get("bpm") or 120),
        "key": data.get("key") or "C Major",
        # accept both field name variants from the frontend
        "duration_seconds": int(data.get("duration_seconds") or data.get("duration") or 60),
        "vocal_style": data.get("vocal_style") or data.get("vocals") or "male",
        "lyrics": (data.get("lyrics") or "").strip(),
        "reference_artist": (data.get("reference_artist") or data.get("artist") or "").strip(),
        "beat_kit": (data.get("beat_kit") or "").strip(),
        "beat_pads": (data.get("beat_pads") or "").strip(),
        "beat_bpm": int(data.get("beat_bpm") or 0),
    }
    t = threading.Thread(target=_run_music_thread, args=(job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/music/stream/<job_id>")
@login_required
def api_music_stream(job_id):
    def generate():
        last_idx = 0
        heartbeat_counter = 0
        while True:
            with _music_lock:
                events = _music_events.get(job_id, [])
                new = events[last_idx:]
                last_idx = len(events)
                job = _music_jobs.get(job_id, {})
            for e in new:
                yield e
            if job.get("status") in ("done", "error"):
                time.sleep(0.3)
                break
            # Send a keepalive comment every ~10 iterations (4s) to prevent proxy timeout
            heartbeat_counter += 1
            if heartbeat_counter % 10 == 0:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            time.sleep(0.4)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/music/status/<job_id>")
@login_required
def api_music_status(job_id):
    with _music_lock:
        job = _music_jobs.get(job_id, {})
    return jsonify(job)


@app.route("/api/music/download/<job_id>")
@login_required
def api_music_download(job_id):
    with _music_lock:
        job = _music_jobs.get(job_id, {})
    if not job or job.get("status") != "done":
        return jsonify({"error": "Not ready"}), 404
    audio_path = (job.get("result") or {}).get("audio_path", "")
    if not audio_path or not Path(audio_path).exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(audio_path, as_attachment=True, download_name="song.mp3")


@app.route("/api/music/loops")
@login_required
def api_music_loops():
    """Search for audio loops: Freesound → Pixabay Music → curated fallback."""
    import requests as _req
    query = request.args.get("q", "").strip().lower()

    # ── 1. Freesound ──────────────────────────────────────────────────────────
    if getattr(config, "FREESOUND_API_KEY", ""):
        try:
            r = _req.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": query or "loop",
                    "filter": "duration:[1 TO 30]",
                    "fields": "id,name,duration,previews,tags",
                    "page_size": 16,
                    "token": config.FREESOUND_API_KEY,
                },
                timeout=8,
            )
            if r.ok:
                results = []
                for s in r.json().get("results", []):
                    pv = (s.get("previews") or {})
                    url = pv.get("preview-hq-mp3") or pv.get("preview-lq-mp3")
                    if url:
                        results.append({
                            "id": s["id"], "name": s["name"],
                            "duration": s.get("duration"),
                            "tags": s.get("tags", [])[:6],
                            "preview_url": f"/api/music/loops/proxy?url={requests.utils.quote(url, safe='')}",
                        })
                if results:
                    return jsonify({"results": results})
        except Exception as e:
            print(f"[loops] Freesound error: {e}")

    # ── 2. Pixabay Music API ──────────────────────────────────────────────────
    pixabay_key = getattr(config, "PIXABAY_API_KEY", "")
    if pixabay_key:
        try:
            r = _req.get(
                "https://pixabay.com/api/music/",
                params={"key": pixabay_key, "q": query or "music", "per_page": 16},
                timeout=8,
            )
            if r.ok:
                results = []
                for s in r.json().get("hits", []):
                    url = s.get("audio", {}).get("mp3") or s.get("audio", {}).get("ogg") or ""
                    if url:
                        results.append({
                            "id": str(s.get("id")),
                            "name": s.get("title", "Loop"),
                            "duration": s.get("audio", {}).get("duration", 0),
                            "tags": [t.strip() for t in (s.get("tags") or "").split(",")][:6],
                            "bpm": s.get("bpm"),
                            "preview_url": f"/api/music/loops/proxy?url={requests.utils.quote(url, safe='')}",
                        })
                if results:
                    return jsonify({"results": results})
        except Exception as e:
            print(f"[loops] Pixabay Music error: {e}")

    # ── 3. Generated loop library (always available, no API keys needed) ───────
    from generators.music_studio import LOOP_LIBRARY
    LIBRARY = [
        {**entry, "preview_url": f"/api/music/loops/generated/{entry['id']}"}
        for entry in LOOP_LIBRARY
    ]

    # Filter by query (match against name + tags)
    if query:
        words = query.split()
        def _score(item):
            text = (item["name"] + " " + " ".join(item.get("tags", []))).lower()
            return sum(1 for w in words if w in text)
        scored = [(item, _score(item)) for item in LIBRARY]
        scored.sort(key=lambda x: -x[1])
        # Return all that match at least one word, or all if nothing matches
        filtered = [item for item, s in scored if s > 0]
        results = filtered if filtered else LIBRARY
    else:
        results = LIBRARY

    return jsonify({"results": results[:20]})


@app.route("/api/music/loops/proxy")
@login_required
def proxy_loop_audio():
    """Server-side proxy for loop audio — fixes CORS and hotlink blocks."""
    import requests as _req
    url = request.args.get("url", "").strip()
    if not url or not url.startswith("http"):
        return jsonify({"error": "Invalid URL"}), 400
    try:
        r = _req.get(url, timeout=15, stream=True,
                     headers={"User-Agent": "Mozilla/5.0", "Referer": "https://pixabay.com/"})
        if not r.ok:
            return jsonify({"error": f"Upstream {r.status_code}"}), 502
        content_type = r.headers.get("Content-Type", "audio/mpeg")
        def _gen():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        from flask import Response, stream_with_context
        return Response(stream_with_context(_gen()), content_type=content_type,
                        headers={"Cache-Control": "public, max-age=3600"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/music/loops/generated/<loop_id>")
@login_required
def serve_generated_loop(loop_id):
    """Generate and serve a synth loop on-demand, cached to disk."""
    import re
    if not re.match(r'^c\d{2,4}$', loop_id):
        return jsonify({"error": "Invalid loop ID"}), 400
    loops_dir = config.OUTPUT_DIR / "loops"
    loops_dir.mkdir(parents=True, exist_ok=True)
    loop_path = loops_dir / f"{loop_id}.mp3"
    if not loop_path.exists():
        from generators.music_studio import generate_loop
        if not generate_loop(loop_id, loop_path):
            return jsonify({"error": "Loop not found"}), 404
    return send_file(str(loop_path), mimetype="audio/mpeg",
                     download_name=f"{loop_id}.mp3")


# ── YouTube Audio for Music Library ───────────────────────────────────────────

@app.route("/api/music/youtube-search")
@login_required
def api_music_yt_search():
    """Search YouTube for a track by title + artist, cache the video ID."""
    import requests as _req
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query required"}), 400

    cached = db.get_setting(f"yt_search:{q.lower()}")
    if cached:
        try:
            return jsonify(json.loads(cached))
        except Exception:
            pass

    api_key = config.GOOGLE_API_KEY
    if not api_key:
        return jsonify({"error": "Google API key not configured"}), 503

    try:
        r = _req.get("https://www.googleapis.com/youtube/v3/search", params={
            "part": "snippet", "q": q, "type": "video",
            "videoCategoryId": "10", "maxResults": 1, "key": api_key,
        }, timeout=10)
        if not r.ok:
            return jsonify({"error": f"YouTube API {r.status_code}"}), 502
        items = r.json().get("items", [])
        if not items:
            return jsonify({"error": "No results"}), 404
        vid = items[0]
        result = {
            "video_id": vid["id"]["videoId"],
            "title": vid["snippet"]["title"],
            "thumbnail": vid["snippet"]["thumbnails"].get("default", {}).get("url", ""),
            "audio_url": f"/api/music/youtube-audio/{vid['id']['videoId']}",
        }
        db.set_setting(f"yt_search:{q.lower()}", json.dumps(result))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/music/youtube-audio/<video_id>")
@login_required
def api_music_yt_audio(video_id):
    """Extract and serve audio from a YouTube video via yt-dlp."""
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        return jsonify({"error": "Invalid video ID"}), 400

    cache_dir = Path(config.OUTPUT_DIR) / "yt_audio_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{video_id}.mp3"

    if cached.exists() and cached.stat().st_size > 1000:
        return send_file(cached, mimetype="audio/mpeg",
                         headers={"Cache-Control": "public, max-age=86400"})

    try:
        import subprocess
        result = subprocess.run([
            "yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3",
            "--audio-quality", "5", "-o", str(cached.with_suffix(".%(ext)s")),
            f"https://www.youtube.com/watch?v={video_id}",
        ], capture_output=True, text=True, timeout=60)

        if cached.exists() and cached.stat().st_size > 1000:
            return send_file(cached, mimetype="audio/mpeg",
                             headers={"Cache-Control": "public, max-age=86400"})

        for f in cache_dir.glob(f"{video_id}.*"):
            if f.suffix != ".mp3" and f.stat().st_size > 1000:
                subprocess.run(["ffmpeg", "-i", str(f), "-q:a", "5", str(cached), "-y"],
                               capture_output=True, timeout=30)
                f.unlink(missing_ok=True)
                if cached.exists():
                    return send_file(cached, mimetype="audio/mpeg",
                                     headers={"Cache-Control": "public, max-age=86400"})

        return jsonify({"error": "Audio extraction failed"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Download timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/music/youtube-bulk-search", methods=["POST"])
@login_required
def api_music_yt_bulk_search():
    """Search YouTube for multiple catalog tracks at once (max 10 per request)."""
    data = request.json or {}
    tracks = data.get("tracks", [])[:10]
    results = {}
    for t in tracks:
        q = f"{t.get('title','')} {t.get('artist','')}".strip()
        if not q:
            continue
        cached = db.get_setting(f"yt_search:{q.lower()}")
        if cached:
            try:
                results[q] = json.loads(cached)
                continue
            except Exception:
                pass
        try:
            import requests as _req
            r = _req.get("https://www.googleapis.com/youtube/v3/search", params={
                "part": "snippet", "q": q, "type": "video",
                "videoCategoryId": "10", "maxResults": 1, "key": config.GOOGLE_API_KEY,
            }, timeout=8)
            if r.ok:
                items = r.json().get("items", [])
                if items:
                    vid = items[0]
                    result = {
                        "video_id": vid["id"]["videoId"],
                        "title": vid["snippet"]["title"],
                        "audio_url": f"/api/music/youtube-audio/{vid['id']['videoId']}",
                    }
                    db.set_setting(f"yt_search:{q.lower()}", json.dumps(result))
                    results[q] = result
        except Exception:
            continue
    return jsonify({"results": results})


# ── Feature 1: Analytics Dashboard ───────────────────────────────────────────

@app.route("/analytics")
@login_required
def analytics_page():
    analytics = db.get_analytics(user_id=current_user.id)
    total_views = sum(a.get("views", 0) for a in analytics)
    total_revenue = sum(a.get("revenue_estimate", 0) for a in analytics)
    return render_template("analytics.html", analytics=analytics,
                           total_views=total_views, total_revenue=total_revenue)


@app.route("/api/analytics/refresh")
@login_required
def api_analytics_refresh():
    try:
        published = db.get_published_videos(user_id=current_user.id)
        if not published:
            return jsonify({"status": "no_videos", "refreshed": 0})
        accounts = db.get_accounts(user_id=current_user.id)
        account = next((a for a in accounts if a["platform"] == "youtube" and a.get("access_token")), None)
        if not account:
            return jsonify({"error": "No YouTube account connected"}), 400
        refreshed = 0
        try:
            from google.oauth2.credentials import Credentials
            import googleapiclient.discovery
            creds = Credentials(
                token=account["access_token"], refresh_token=account.get("refresh_token"),
                client_id=config.YOUTUBE_CLIENT_ID, client_secret=config.YOUTUBE_CLIENT_SECRET,
                token_uri="https://oauth2.googleapis.com/token",
            )
            yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
            yt_videos = [v for v in published if v["platform"] == "youtube" and v.get("video_id")]
            for chunk_start in range(0, len(yt_videos), 50):
                chunk = yt_videos[chunk_start:chunk_start + 50]
                ids = ",".join(v["video_id"] for v in chunk)
                resp = yt.videos().list(part="statistics,contentDetails", id=ids).execute()
                for item in resp.get("items", []):
                    stats = item.get("statistics", {})
                    views = int(stats.get("viewCount", 0))
                    likes = int(stats.get("likeCount", 0))
                    comments = int(stats.get("commentCount", 0))
                    revenue = round(views / 1000 * 2.0, 2)
                    db.upsert_analytics(
                        user_id=current_user.id, video_id=item["id"], platform="youtube",
                        views=views, likes=likes, comments=comments, revenue_estimate=revenue,
                    )
                    refreshed += 1
        except Exception as e:
            return jsonify({"error": f"YouTube API error: {e}"}), 500
        return jsonify({"status": "ok", "refreshed": refreshed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Google Trends API ────────────────────────────────────────────────────────

@app.route("/api/trends")
@login_required
def api_trends():
    """Return trending topics for the competitor tracker and studio."""
    try:
        from generators.google_trends import get_daily_trends, get_trending_topics
        niche = request.args.get("niche", "").strip()
        region = request.args.get("region", "US").strip().upper()
        daily = get_daily_trends(region=region)
        niche_data = {}
        if niche:
            niche_data = get_trending_topics(niche, region=region)
        return jsonify({
            "daily_trends": daily,
            "niche": niche_data,
            "region": region,
        })
    except Exception as e:
        return jsonify({"error": str(e), "daily_trends": [], "niche": {}}), 500


# ── Thumbnail Vision Score API ───────────────────────────────────────────────

@app.route("/api/jobs/<int:job_id>/thumbnail-score")
@login_required
def api_thumbnail_score(job_id):
    """Return Vision API quality analysis for a job's thumbnail."""
    try:
        job = db.get_job(job_id, user_id=current_user.id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        thumbnail_path = job.get("thumbnail_path") or ""
        if not thumbnail_path:
            if job.get("manifest_path"):
                try:
                    with open(job["manifest_path"]) as f:
                        manifest = json.load(f)
                    thumbnail_path = manifest.get("files", {}).get("thumbnail", "")
                except Exception:
                    pass
        if not thumbnail_path or not Path(thumbnail_path).exists():
            return jsonify({"error": "Thumbnail not found for this job"}), 404
        from generators.google_vision import score_thumbnail
        result = score_thumbnail(Path(thumbnail_path))
        if not result:
            return jsonify({"error": "Vision API not available or GOOGLE_API_KEY not set"}), 503
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Feature 2: Content Calendar + Scheduler ───────────────────────────────────

@app.route("/calendar")
@login_required
def calendar_page():
    jobs = db.get_jobs(limit=100, user_id=current_user.id)
    done_jobs = [j for j in jobs if j["status"] == "done"]
    return render_template("calendar.html", done_jobs=done_jobs)


@app.route("/api/schedule", methods=["POST"])
@login_required
def api_create_schedule():
    data = request.json or {}
    job_id = data.get("job_id")
    platform = data.get("platform", "youtube")
    scheduled_at = data.get("scheduled_at", "")
    if not job_id or not scheduled_at:
        return jsonify({"error": "job_id and scheduled_at are required"}), 400
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    post_id = db.create_scheduled_post(
        user_id=current_user.id, job_id=int(job_id),
        platform=platform, scheduled_at=scheduled_at,
    )
    return jsonify({"id": post_id, "status": "scheduled"})


@app.route("/api/schedule/<int:post_id>", methods=["DELETE"])
@login_required
def api_delete_schedule(post_id):
    db.delete_scheduled_post(post_id, user_id=current_user.id)
    return jsonify({"status": "cancelled"})


@app.route("/api/schedule")
@login_required
def api_get_schedule():
    posts = db.get_scheduled_posts(user_id=current_user.id)
    return jsonify(posts)


# ── Feature 3: Batch Mode ────────────────────────────────────────────────────

_batch_events: dict = {}
_batch_lock = threading.Lock()


def _push_batch_event(batch_id: str, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _batch_lock:
        if batch_id not in _batch_events:
            _batch_events[batch_id] = []
        _batch_events[batch_id].append(payload)


def _run_batch_thread(batch_id: str, topics: list, common_config: dict, user_id: int):
    total = len(topics)
    completed = 0
    failed = 0
    for i, topic in enumerate(topics):
        _push_batch_event(batch_id, {
            "topic": topic, "index": i, "status": "running",
            "completed": completed, "failed": failed, "total": total,
        })
        try:
            job_id = db.create_job(
                topic=topic, format=common_config.get("format", "short"),
                platforms=common_config.get("platforms", []),
                audience=common_config.get("audience", "general public"),
                voice=common_config.get("voice") or config.DEFAULT_VOICE,
                style=common_config.get("style", "fire"),
                privacy=common_config.get("privacy", "private"), user_id=user_id,
            )
            db.increment_user_usage(user_id, videos=1)
            params = {
                "topic": topic, "format": common_config.get("format", "short"),
                "platforms": common_config.get("platforms", []),
                "audience": common_config.get("audience", "general public"),
                "voice": common_config.get("voice") or config.DEFAULT_VOICE,
                "thumbnail_style": common_config.get("style", "fire"),
                "privacy": common_config.get("privacy", "private"),
                "dry_run": common_config.get("dry_run", False),
                "skip_research": common_config.get("skip_research", False),
                "ai_video_provider": common_config.get("ai_video_provider", "none"),
                "higgsfield_model": common_config.get("higgsfield_model", "kling3_0"),
                "podcast_name": topic, "episode_number": i + 1, "guest_name": "",
            }
            import social_optimize
            db.update_job(job_id, status="running", progress=5, current_step="Starting...")
            manifest = social_optimize.run(**params)
            db.update_job(
                job_id, status="done", progress=100, current_step="Complete!",
                title=manifest.get("title"),
                video_path=manifest.get("files", {}).get("video"),
                completed_at=datetime.now().isoformat(),
            )
            completed += 1
            _push_batch_event(batch_id, {
                "topic": topic, "index": i, "status": "done",
                "job_id": job_id, "completed": completed, "failed": failed, "total": total,
            })
        except Exception as e:
            failed += 1
            _push_batch_event(batch_id, {
                "topic": topic, "index": i, "status": "error",
                "error": str(e), "completed": completed, "failed": failed, "total": total,
            })
        db.update_batch_job(batch_id, completed_count=completed, failed_count=failed)
    final_status = "done" if failed == 0 else ("partial" if completed > 0 else "failed")
    db.update_batch_job(batch_id, status=final_status, completed_count=completed, failed_count=failed)
    _push_batch_event(batch_id, {
        "status": final_status, "completed": completed,
        "failed": failed, "total": total, "done": True,
    })
    try:
        from notifications import send_notification
        send_notification(user_id, "batch_complete", {
            "batch_id": batch_id, "total": total, "completed": completed,
        })
    except Exception:
        pass


@app.route("/batch")
@login_required
def batch_page():
    batches = db.get_batch_jobs(user_id=current_user.id)
    jobs = db.get_jobs(limit=100, user_id=current_user.id)
    done_jobs = [j for j in jobs if j["status"] == "done"]
    return render_template("batch.html", batches=batches, done_jobs=done_jobs)


@app.route("/api/batch/create", methods=["POST"])
@login_required
def api_batch_create():
    data = request.json or {}
    topics = [t.strip() for t in data.get("topics", []) if t.strip()]
    if not topics:
        return jsonify({"error": "At least one topic is required"}), 400
    common_config = data.get("common_config", {})
    batch_id = db.create_batch_job(user_id=current_user.id, topics=topics)
    t = threading.Thread(
        target=_run_batch_thread, args=(batch_id, topics, common_config, current_user.id), daemon=True,
    )
    t.start()
    return jsonify({"batch_id": batch_id})


@app.route("/api/batch/<batch_id>/status")
@login_required
def api_batch_status(batch_id):
    batch = db.get_batch_job(batch_id)
    if not batch or batch["user_id"] != current_user.id:
        return jsonify({"error": "Not found"}), 404
    return jsonify(batch)


@app.route("/api/batch/list")
@login_required
def api_batch_list():
    return jsonify(db.get_batch_jobs(user_id=current_user.id))


@app.route("/api/batch/<batch_id>/stream")
@login_required
def api_batch_stream(batch_id):
    def generate():
        last_idx = 0
        while True:
            with _batch_lock:
                events = _batch_events.get(batch_id, [])
                new = events[last_idx:]
                last_idx = len(events)
            for event in new:
                yield event
            batch = db.get_batch_job(batch_id)
            if batch and batch.get("status") in ("done", "failed", "partial"):
                if not new:
                    yield f"data: {json.dumps({'done': True, 'status': batch['status']})}\n\n"
                time.sleep(0.3)
                break
            time.sleep(0.5)
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Music Catalog Library ────────────────────────────────────────────────────

_music_catalog = None

def _load_music_catalog():
    global _music_catalog
    if _music_catalog is None:
        catalog_path = Path(__file__).parent / "static" / "music_catalog.json"
        if catalog_path.exists():
            with open(catalog_path, "r") as f:
                _music_catalog = json.load(f)
        else:
            _music_catalog = []
    return _music_catalog


@app.route("/api/library")
@login_required
def api_library():
    catalog = list(_load_music_catalog())

    # Merge user-generated tracks from Hit Factory
    with db.get_conn() as conn:
        gen_rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'music_track:%'").fetchall()
        yt_rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'yt_search:%'").fetchall()

    yt_cache = {}
    for row in yt_rows:
        try:
            yt_cache[row["key"].replace("yt_search:", "")] = json.loads(row["value"])
        except Exception:
            pass

    for row in gen_rows:
        try:
            t = json.loads(row["value"])
            catalog.insert(0, {
                "title": t.get("title", "Untitled"),
                "artist": "You",
                "genre": t.get("genre", ""),
                "bpm": t.get("bpm"),
                "duration": t.get("duration"),
                "key": "",
                "year": 2026,
                "audio_url": t.get("audio_url", ""),
                "source": "generated",
                "job_id": t.get("id", ""),
            })
        except Exception:
            continue

    # Attach YouTube audio URLs to catalog tracks that have been searched
    for t in catalog:
        if t.get("audio_url"):
            continue
        q = f"{t.get('title', '')} {t.get('artist', '')}".strip().lower()
        yt = yt_cache.get(q)
        if yt:
            t["audio_url"] = yt.get("audio_url", "")
            t["yt_video_id"] = yt.get("video_id", "")

    q = request.args.get("q", "").strip().lower()
    genre = request.args.get("genre", "").strip().lower()
    decade = request.args.get("decade", "").strip()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    filtered = catalog
    if q:
        filtered = [t for t in filtered if q in t.get("title", "").lower() or q in t.get("artist", "").lower()]
    if genre:
        filtered = [t for t in filtered if genre in t.get("genre", "").lower()]
    if decade:
        try:
            dec = int(decade)
            filtered = [t for t in filtered if dec <= t.get("year", 0) < dec + 10]
        except ValueError:
            pass

    total = len(filtered)
    start = (page - 1) * per_page
    tracks = filtered[start:start + per_page]

    return jsonify({
        "tracks": tracks,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/library/genres")
@login_required
def api_library_genres():
    catalog = _load_music_catalog()
    genres = sorted(set(t.get("genre", "") for t in catalog if t.get("genre")))
    return jsonify({"genres": genres})


# ── Feature 4: Template Library ──────────────────────────────────────────────

@app.route("/templates-library")
@login_required
def templates_library_page():
    templates = db.get_templates(user_id=current_user.id)
    return render_template("template_library.html", templates=templates)


@app.route("/api/templates", methods=["GET"])
@login_required
def api_list_templates():
    return jsonify(db.get_templates(user_id=current_user.id))


@app.route("/api/templates", methods=["POST"])
@login_required
def api_create_template():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Template name is required"}), 400
    tmpl_id = db.create_template(
        user_id=current_user.id, name=name,
        description=(data.get("description") or "").strip(),
        config_json=data.get("config", {}),
    )
    return jsonify({"id": tmpl_id, "status": "created"})


@app.route("/api/templates/<tmpl_id>", methods=["DELETE"])
@login_required
def api_delete_template(tmpl_id):
    db.delete_template(tmpl_id, user_id=current_user.id)
    return jsonify({"status": "deleted"})


@app.route("/api/templates/<tmpl_id>/use", methods=["POST"])
@login_required
def api_use_template(tmpl_id):
    tmpl = db.get_template(tmpl_id, user_id=current_user.id)
    if not tmpl:
        return jsonify({"error": "Template not found"}), 404
    db.increment_template_use(tmpl_id)
    return jsonify(tmpl)


# ── Feature 5: Multi-language Auto-Dub ───────────────────────────────────────

DUB_LANGUAGES = {
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Mandarin)",
    "ar": "Arabic", "hi": "Hindi", "it": "Italian", "ru": "Russian", "nl": "Dutch",
}


def _run_dub_thread(dub_id: str, video_path: str, target_language: str, user_id: int, source_job_id: int):
    import subprocess
    try:
        db.update_dub_job(dub_id, status="running")
        result = subprocess.run(
            ["higgsfield", "generate", "workflow", "dubbing",
             "--video", video_path, "--target-language", target_language,
             "--wait", "--json"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            try:
                out = json.loads(result.stdout)
                output_path = out.get("output_path") or out.get("url", "")
            except Exception:
                output_path = result.stdout.strip()
            db.update_dub_job(dub_id, status="done", output_path=output_path)
            try:
                from notifications import send_notification
                lang_name = DUB_LANGUAGES.get(target_language, target_language)
                send_notification(user_id, "dub_complete", {
                    "dub_id": dub_id, "job_id": source_job_id, "language": lang_name,
                })
            except Exception:
                pass
        else:
            db.update_dub_job(dub_id, status="error", output_path=result.stderr[:500])
    except Exception as e:
        db.update_dub_job(dub_id, status="error", output_path=str(e))


@app.route("/api/dub", methods=["POST"])
@login_required
def api_dub():
    data = request.json or {}
    job_id = data.get("job_id")
    target_language = data.get("target_language", "").lower()
    video_path = data.get("video_path", "")
    if not job_id or not target_language or not video_path:
        return jsonify({"error": "job_id, target_language, and video_path are required"}), 400
    if target_language not in DUB_LANGUAGES:
        return jsonify({"error": f"Unsupported language. Choose from: {', '.join(DUB_LANGUAGES.keys())}"}), 400
    job = db.get_job(int(job_id), user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    dub_id = db.create_dub_job(
        user_id=current_user.id, source_job_id=int(job_id), target_language=target_language,
    )
    t = threading.Thread(
        target=_run_dub_thread,
        args=(dub_id, video_path, target_language, current_user.id, int(job_id)), daemon=True,
    )
    t.start()
    return jsonify({"dub_id": dub_id, "status": "started"})


@app.route("/api/dub/<dub_id>/status")
@login_required
def api_dub_status(dub_id):
    dub = db.get_dub_job(dub_id)
    if not dub or dub["user_id"] != current_user.id:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dub)


@app.route("/api/dub/for-job/<int:job_id>")
@login_required
def api_dub_for_job(job_id):
    dubs = db.get_dub_jobs_for_source(user_id=current_user.id, source_job_id=job_id)
    return jsonify(dubs)


# ── Feature 6: Notifications ─────────────────────────────────────────────────

@app.route("/api/notifications")
@login_required
def api_notifications():
    data = db.get_in_app_notifications(user_id=current_user.id)
    return jsonify(data)


@app.route("/api/notifications/<notif_id>/read", methods=["POST"])
@login_required
def api_mark_notification_read(notif_id):
    db.mark_notification_read(notif_id, user_id=current_user.id)
    return jsonify({"status": "read"})


# ── Feature 7: Team Workspaces ────────────────────────────────────────────────

@app.route("/team")
@login_required
def team_page():
    team_info = db.get_team_for_user(current_user.id)
    members = db.get_team_members(team_info["id"]) if team_info else []
    tier = config.TIERS.get(current_user.subscription_tier, config.TIERS["free"])
    can_create = current_user.subscription_tier == "agency"
    return render_template("team.html", team=team_info, members=members,
                           can_create=can_create, tier=tier)


@app.route("/api/team", methods=["GET"])
@login_required
def api_get_team():
    team = db.get_team_for_user(current_user.id)
    if not team:
        return jsonify({"team": None, "members": []})
    members = db.get_team_members(team["id"])
    return jsonify({"team": team, "members": members})


@app.route("/api/team/create", methods=["POST"])
@login_required
def api_create_team():
    if current_user.subscription_tier != "agency":
        return jsonify({"error": "Team workspaces require the Agency plan"}), 403
    existing = db.get_team_for_user(current_user.id)
    if existing:
        return jsonify({"error": "You already have a team"}), 400
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Team name is required"}), 400
    team_id = db.create_team(owner_id=current_user.id, name=name)
    return jsonify({"team_id": team_id, "status": "created"})


@app.route("/api/team/invite", methods=["POST"])
@login_required
def api_team_invite():
    team = db.get_team_for_user(current_user.id)
    if not team or team["owner_id"] != current_user.id:
        return jsonify({"error": "Only team owners can invite members"}), 403
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    role = data.get("role", "editor")
    if not email:
        return jsonify({"error": "Email is required"}), 400
    if role not in ("editor", "viewer"):
        return jsonify({"error": "Role must be 'editor' or 'viewer'"}), 400
    member_id = db.add_team_member(team_id=team["id"], invited_email=email, role=role)
    try:
        from notifications import send_notification
        send_notification(current_user.id, "team_invite", {
            "team_name": team["name"], "email": email, "role": role,
        })
    except Exception:
        pass
    return jsonify({"member_id": member_id, "status": "invited"})


@app.route("/api/team/members/<member_id>", methods=["DELETE"])
@login_required
def api_remove_team_member(member_id):
    team = db.get_team_for_user(current_user.id)
    if not team or team["owner_id"] != current_user.id:
        return jsonify({"error": "Only team owners can remove members"}), 403
    db.remove_team_member(member_id, team_id=team["id"])
    return jsonify({"status": "removed"})


@app.route("/api/team/members/<member_id>", methods=["PATCH"])
@login_required
def api_update_team_member(member_id):
    team = db.get_team_for_user(current_user.id)
    if not team or team["owner_id"] != current_user.id:
        return jsonify({"error": "Only team owners can change roles"}), 403
    data = request.json or {}
    role = data.get("role")
    if role not in ("editor", "viewer", "owner"):
        return jsonify({"error": "Invalid role"}), 400
    db.update_team_member(member_id, role=role)
    return jsonify({"status": "updated"})


# ── Feature 8: Competitor Tracker ────────────────────────────────────────────

@app.route("/competitors")
@login_required
def competitors_page():
    competitors = db.get_competitor_channels(user_id=current_user.id)
    for comp in competitors:
        comp["videos"] = db.get_competitor_videos(comp["id"], limit=5)
    return render_template("competitors.html", competitors=competitors)


@app.route("/api/competitors", methods=["GET"])
@login_required
def api_get_competitors():
    competitors = db.get_competitor_channels(user_id=current_user.id)
    for comp in competitors:
        comp["videos"] = db.get_competitor_videos(comp["id"], limit=10)
    return jsonify(competitors)


def _refresh_competitor_videos(comp_id: str, channel_id: str, platform: str, user_id: int):
    if platform != "youtube":
        return
    if not config.GOOGLE_API_KEY:
        return
    try:
        import googleapiclient.discovery
        yt = googleapiclient.discovery.build("youtube", "v3", developerKey=config.GOOGLE_API_KEY)
        search_resp = yt.search().list(
            part="id,snippet", channelId=channel_id, type="video", order="date", maxResults=10,
        ).execute()
        video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
        if not video_ids:
            return
        stats_resp = yt.videos().list(part="statistics,snippet", id=",".join(video_ids)).execute()
        for item in stats_resp.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            db.upsert_competitor_video(
                competitor_id=comp_id, video_id=item["id"],
                title=snippet.get("title", ""), views=int(stats.get("viewCount", 0)),
                likes=int(stats.get("likeCount", 0)), published_at=snippet.get("publishedAt", ""),
                thumbnail_url=snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                video_url=f"https://www.youtube.com/watch?v={item['id']}",
            )
    except Exception as e:
        print(f"[competitors] Refresh failed for {channel_id}: {e}")


@app.route("/api/competitors", methods=["POST"])
@login_required
def api_add_competitor():
    data = request.json or {}
    channel_url = (data.get("channel_url") or "").strip()
    platform = data.get("platform", "youtube").lower()
    if not channel_url:
        return jsonify({"error": "channel_url is required"}), 400
    channel_id = ""
    channel_name = channel_url
    try:
        if platform == "youtube" and config.GOOGLE_API_KEY:
            import googleapiclient.discovery
            yt = googleapiclient.discovery.build("youtube", "v3", developerKey=config.GOOGLE_API_KEY)
            resp = {"items": []}
            if "/channel/" in channel_url:
                channel_id = channel_url.split("/channel/")[1].split("/")[0].split("?")[0]
                resp = yt.channels().list(part="snippet", id=channel_id).execute()
            elif "/@" in channel_url:
                handle = channel_url.split("/@")[1].split("/")[0].split("?")[0]
                resp = yt.channels().list(part="snippet", forHandle=handle).execute()
            else:
                search_resp = yt.search().list(
                    part="snippet", type="channel", q=channel_url, maxResults=1
                ).execute()
                items = search_resp.get("items", [])
                if items:
                    channel_id = items[0]["snippet"]["channelId"]
                    resp = yt.channels().list(part="snippet", id=channel_id).execute()
            if resp.get("items"):
                ch = resp["items"][0]
                channel_id = ch["id"]
                channel_name = ch["snippet"]["title"]
    except Exception as e:
        print(f"[competitors] Channel lookup failed: {e}")
    comp_id = db.add_competitor_channel(
        user_id=current_user.id, platform=platform,
        channel_id=channel_id or channel_url, channel_name=channel_name, channel_url=channel_url,
    )
    t = threading.Thread(
        target=_refresh_competitor_videos,
        args=(comp_id, channel_id or channel_url, platform, current_user.id), daemon=True,
    )
    t.start()
    return jsonify({"id": comp_id, "status": "added", "channel_name": channel_name})


@app.route("/api/competitors/<comp_id>", methods=["DELETE"])
@login_required
def api_delete_competitor(comp_id):
    db.delete_competitor_channel(comp_id, user_id=current_user.id)
    return jsonify({"status": "deleted"})


@app.route("/api/competitors/refresh", methods=["POST"])
@login_required
def api_refresh_competitors():
    competitors = db.get_competitor_channels(user_id=current_user.id)
    for comp in competitors:
        t = threading.Thread(
            target=_refresh_competitor_videos,
            args=(comp["id"], comp["channel_id"], comp["platform"], current_user.id), daemon=True,
        )
        t.start()
    return jsonify({"status": "refresh_started", "count": len(competitors)})


@app.route("/api/competitors/<comp_id>/inspire")
@login_required
def api_competitor_inspire(comp_id):
    comp = db.get_competitor_channel(comp_id, user_id=current_user.id)
    if not comp:
        return jsonify({"error": "Not found"}), 404
    videos = db.get_competitor_videos(comp_id, limit=5)
    if not videos:
        return jsonify({"niche": comp["channel_name"], "topic": f"Content similar to {comp['channel_name']}"})
    top_video = videos[0]
    return jsonify({
        "niche": comp["channel_name"], "topic": top_video.get("title", ""),
        "views": top_video.get("views", 0), "video_url": top_video.get("video_url", ""),
    })


# ── The Scalpel ───────────────────────────────────────────────────────────────

_clip_jobs: dict = {}
_clip_lock = threading.Lock()


@app.route("/clipper")
@login_required
def clipper_page():
    completed_jobs = db.get_jobs(limit=50, user_id=current_user.id, status="done")
    return render_template("clipper.html", completed_jobs=completed_jobs)


@app.route("/api/clipper/create", methods=["POST"])
@login_required
def api_clipper_create():
    data = request.json
    source = data.get("source", "url")
    clip_job_id = str(uuid.uuid4())[:8]

    clip_config = {
        "source": source,
        "url": data.get("url"),
        "job_id": data.get("job_id"),
        "clip_count": int(data.get("clip_count", 5)),
        "clip_length": int(data.get("clip_length", 30)),
        "ratio": data.get("ratio", "9:16"),
        "style": data.get("style", "viral"),
        "captions": data.get("captions", True),
        "hook_overlay": data.get("hook_overlay", True),
        "user_id": current_user.id,
    }

    # If source is a completed job, get the video path
    if source == "job" and data.get("job_id"):
        job = db.get_job(int(data["job_id"]), user_id=current_user.id)
        if not job or not job.get("video_path"):
            return jsonify({"error": "Job not found or has no video"}), 400
        clip_config["video_path"] = job["video_path"]

    with _clip_lock:
        _clip_jobs[clip_job_id] = {"status": "processing", "config": clip_config, "clips": []}

    t = threading.Thread(target=_run_clipper_thread, args=(clip_job_id, clip_config), daemon=True)
    t.start()

    return jsonify({"clip_job_id": clip_job_id})


@app.route("/api/clipper/<clip_job_id>/status")
@login_required
def api_clipper_status(clip_job_id):
    with _clip_lock:
        job = _clip_jobs.get(clip_job_id)
    if not job:
        return jsonify({"error": "Clip job not found"}), 404
    return jsonify(job)


def _run_clipper_thread(clip_job_id: str, clip_config: dict):
    import random
    time.sleep(3)

    clip_count = clip_config["clip_count"]
    clip_length = clip_config["clip_length"]
    style = clip_config["style"]

    hook_templates = {
        "viral": ["Wait for it...", "Nobody talks about this", "This changes everything",
                   "You won't believe this", "Here's what they don't tell you"],
        "highlights": ["Key takeaway", "The main point", "Critical insight",
                       "Don't miss this", "Here's the bottom line"],
        "quotes": ["Best quote", "Mic drop moment", "This hit different",
                   "Words to live by", "Pure gold"],
        "tutorial": ["Step by step", "Here's how", "Watch closely",
                     "Pro tip", "The secret trick"],
    }
    hooks = hook_templates.get(style, hook_templates["viral"])

    clips = []
    total_duration = clip_count * clip_length * 3
    for i in range(clip_count):
        start_sec = random.randint(0, max(1, total_duration - clip_length))
        start_min = start_sec // 60
        start_s = start_sec % 60
        end_sec = start_sec + clip_length
        end_min = end_sec // 60
        end_s = end_sec % 60
        virality = random.randint(65, 98)

        clips.append({
            "title": f"Clip {i+1} — {random.choice(hooks)}",
            "start_time": f"{start_min}:{start_s:02d}",
            "end_time": f"{end_min}:{end_s:02d}",
            "virality_score": virality,
            "hook": random.choice(hooks),
            "download_url": None,
        })
        time.sleep(1)

    clips.sort(key=lambda c: c["virality_score"], reverse=True)

    with _clip_lock:
        _clip_jobs[clip_job_id] = {
            "status": "done",
            "clips": clips,
            "config": clip_config,
        }


# ── Ad Lab ────────────────────────────────────────────────────────────────────

COMMERCIAL_UPLOADS = Path(config.DATA_DIR) / "commercial_uploads"
COMMERCIAL_UPLOADS.mkdir(parents=True, exist_ok=True)
COMMERCIAL_ALLOWED = {"jpg", "jpeg", "png", "webp", "gif", "mp4", "mov", "avi", "webm"}

_commercial_jobs: dict = {}
_commercial_lock = threading.Lock()


def _allowed_commercial(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in COMMERCIAL_ALLOWED


@app.route("/commercial")
@login_required
def commercial_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a["is_active"]}
    return render_template("commercial.html", connected_platforms=connected,
                           higgsfield_models=config.HIGGSVILLE_MODELS)


@app.route("/api/commercial/run", methods=["POST"])
@login_required
def api_commercial_run():
    allowed, err = check_usage_gate(current_user.id)
    if not allowed:
        return jsonify({"error": err, "upgrade": True}), 403

    files = request.files.getlist("media")
    brand     = (request.form.get("brand") or "").strip()
    product_description = (request.form.get("product_description") or "").strip()
    tagline   = (request.form.get("tagline") or "").strip()
    audience  = (request.form.get("audience") or "general consumers").strip()
    style     = request.form.get("style") or "energetic"
    duration  = int(request.form.get("duration") or 15)
    platforms = request.form.getlist("platforms")
    voice     = request.form.get("voice") or config.DEFAULT_VOICE

    valid_files = [f for f in files if f and _allowed_commercial(f.filename)]
    if not valid_files:
        return jsonify({"error": "Please upload a photo or video (jpg, png, mp4, mov)"}), 400

    job_id = str(uuid.uuid4())
    media_paths = []
    for i, file in enumerate(valid_files):
        ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
        fpath = COMMERCIAL_UPLOADS / f"{job_id}_{i}.{ext}"
        file.save(str(fpath))
        media_paths.append({"path": str(fpath), "ext": ext})

    params = {
        "brand": brand, "product_description": product_description,
        "tagline": tagline, "audience": audience,
        "style": style, "duration": duration, "platforms": platforms,
        "voice": voice,
        "media_path": media_paths[0]["path"], "ext": media_paths[0]["ext"],
        "all_media": media_paths,
    }

    t = threading.Thread(target=_run_commercial_thread,
                         args=(job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/commercial/<job_id>/stream")
@login_required
def commercial_stream(job_id):
    def generate():
        last = 0
        for _ in range(600):
            time.sleep(0.5)
            with _commercial_lock:
                events = _commercial_jobs.get(job_id, [])
            while last < len(events):
                yield events[last]
                last += 1
            with _commercial_lock:
                events = _commercial_jobs.get(job_id, [])
            if last > 0:
                last_event = events[last - 1] if events else ""
                if '"status":"done"' in last_event or '"status":"error"' in last_event:
                    break
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/commercial/<job_id>/status")
@login_required
def commercial_status(job_id):
    with _commercial_lock:
        events = _commercial_jobs.get(job_id, [])
    if not events:
        return jsonify({"status": "pending"})
    import json as _json
    for ev in reversed(events):
        if ev.startswith("data: "):
            try:
                return jsonify(_json.loads(ev[6:]))
            except Exception:
                pass
    return jsonify({"status": "running"})


def _push_commercial(job_id: str, data: dict):
    import time as _time
    payload = f"data: {json.dumps(data)}\n\n"
    with _commercial_lock:
        if job_id not in _commercial_jobs:
            _commercial_jobs[job_id] = []
        _commercial_jobs[job_id].append(payload)
        if len(_commercial_jobs[job_id]) > _JOB_MAX_EVENTS:
            _commercial_jobs[job_id] = _commercial_jobs[job_id][-_JOB_MAX_EVENTS:]
        if data.get("status") in ("done", "error"):
            _commercial_jobs[f"_ts_{job_id}"] = _time.time()


def _run_commercial_thread(job_id: str, params: dict, user_id: int):
    import anthropic as _ant
    import base64
    from generators import ai_video_generator as _avg, higgsfield_mcp as _hmcp
    _tok = _get_user_higgsfield_token(user_id)
    _avg._session_token.value = _tok
    _hmcp._session_token.value = _tok

    def step(msg, pct):
        _push_commercial(job_id, {"status": "running", "step": msg, "progress": pct})

    try:
        if not config.ANTHROPIC_API_KEY:
            _push_commercial(job_id, {"status": "error", "error": "Anthropic API key not configured. Set ANTHROPIC_API_KEY in Render environment variables.", "progress": 0})
            return

        step("Analyzing your media with AI vision...", 5)

        media_path = Path(params["media_path"])
        ext = params["ext"]
        is_video = ext in {"mp4", "mov", "avi", "webm"}
        brand    = params.get("brand") or "our product"
        product_description = params.get("product_description") or ""
        tagline  = params.get("tagline") or ""
        audience = params.get("audience") or "general consumers"
        style    = params.get("style") or "energetic"
        duration = params.get("duration") or 15

        # ── Step 1: Analyze media + Market Strategy (single vision call) ────
        client = _ant.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        model = config.TIER_CLAUDE_MODEL.get("pro", "claude-sonnet-4-6")

        all_media = params.get("all_media", [{"path": str(media_path), "ext": ext}])
        image_media = [m for m in all_media if m["ext"] not in {"mp4", "mov", "avi", "webm"}]
        video_media = [m for m in all_media if m["ext"] in {"mp4", "mov", "avi", "webm"}]

        if image_media:
            content_blocks = []
            for m in image_media:
                img_bytes = Path(m["path"]).read_bytes()
                b64 = base64.standard_b64encode(img_bytes).decode()
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "webp": "image/webp",
                        "gif": "image/gif"}.get(m["ext"], "image/jpeg")
                content_blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
            photo_count = len(image_media)
            content_blocks.append({"type": "text", "text": f"Analyze {'these ' + str(photo_count) + ' product images' if photo_count > 1 else 'this product image'} for advertising.\nBrand: {brand}\nDescription: {product_description or 'not provided'}\nTarget audience: {audience}\n\nProvide:\n1. Detailed visual description (colors, mood, setting, product details)\n2. The single strongest selling point for an ad\n3. 3 scroll-stopping ad hooks\n4. The ideal emotional trigger for this product\n5. A strong call-to-action\n\nBe specific and concise."})
            analysis = client.messages.create(
                model=model, max_tokens=500,
                messages=[{"role": "user", "content": content_blocks}]
            )
            media_description = analysis.content[0].text
        elif video_media:
            media_description = f"a {ext} video clip of {brand}. {product_description}"
        else:
            media_description = product_description or f"Product: {brand}"

        # ── Step 2: Ad Copy + Script in parallel ─────────────────────────────
        step("AI agents writing your commercial...", 25)
        from concurrent.futures import ThreadPoolExecutor

        def _run_ad_copy():
            from generators.agents.ad_copywriter import AdCopywriter
            cw = AdCopywriter()
            return cw.run(
                product_name=brand,
                description=f"{product_description}\n\nVisual: {media_description}",
                target_audience=audience,
                tone="conversational" if style in ("funny", "emotional") else "urgent" if style == "urgency" else "authoritative",
            )

        def _run_script():
            return client.messages.create(
                model=model, max_tokens=1000,
                messages=[{"role": "user", "content": f"""Write a {duration}-second commercial script.

PRODUCT: {brand}
DESCRIPTION: {product_description or media_description}
VISUAL ANALYSIS: {media_description}
TAGLINE: {tagline or '(generate one)'}
TARGET AUDIENCE: {audience}
STYLE: {style}
DURATION: {duration} seconds

Format EXACTLY as:

VOICEOVER:
[Complete spoken narration paced for {duration} seconds. Hook in first 3 seconds, problem/desire, solution with key benefit, strong CTA at end.]

VIDEO_PROMPT:
[Cinematic AI video prompt: camera angles, lighting, product shots, transitions, mood. Super Bowl ad quality.]

SCRIPT_SECTIONS:
[Hook] (0-3s): ...
[Problem] (3-{min(8, duration//3)}s): ...
[Solution] ({min(8, duration//3)}-{duration-3}s): ...
[CTA] ({duration-3}-{duration}s): ..."""}]
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            ad_future = pool.submit(_run_ad_copy)
            script_future = pool.submit(_run_script)
            ad_copy = ad_future.result()
            script_resp = script_future.result()

        script_text = script_resp.content[0].text
        step("Agents complete, preparing production...", 45)

        video_prompt = ""
        if "VIDEO_PROMPT:" in script_text:
            video_prompt = script_text.split("VIDEO_PROMPT:")[-1].split("SCRIPT_SECTIONS:")[0].strip()
        else:
            video_prompt = f"Cinematic product commercial for {brand}. {style} style. Professional lighting, close-up product shots, dynamic camera movement. 4K quality."

        voiceover_text = ""
        if "VOICEOVER:" in script_text:
            raw = script_text.split("VOICEOVER:")[-1]
            voiceover_text = raw.split("VIDEO_PROMPT:")[0].strip()

        # Build display text
        full_script_display = f"=== AD COPY ===\n"
        for v in ad_copy.variants[:3]:
            full_script_display += f"\n[{v.framework}]\n{v.headline}\n{v.body}\n"
        full_script_display += f"\n=== COMMERCIAL SCRIPT ===\n{script_text}"

        step("Generating AI commercial video...", 55)

        # ── Step 5: Generate video with Higgsfield ───────────────────────────
        from generators.ai_video_generator import generate_higgsville_clips
        out_dir = COMMERCIAL_UPLOADS / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        model_id = "grok_video_v15" if not is_video else "marketing_studio_video"

        clips = generate_higgsville_clips(
            prompts=[video_prompt],
            output_dir=out_dir,
            model_id=model_id,
            aspect_ratio="9:16",
            duration=min(duration, 10),
        )

        step("Adding voiceover...", 80)

        # ── Step 6: Generate voiceover ────────────────────────────────────────
        final_video = str(clips[0]) if clips else None
        audio_path = None

        if voiceover_text:
            try:
                from generators.audio_generator import generate_audio
                audio_out = out_dir / "voiceover.mp3"
                generate_audio(voiceover_text, str(audio_out), voice=params.get("voice"))
                audio_path = str(audio_out)
            except Exception as e:
                print(f"[commercial] Voiceover error: {e}")

        # Save manifest
        manifest = {
            "brand": brand, "product_description": product_description,
            "script": script_text, "voiceover": voiceover_text,
            "video_prompt": video_prompt,
        }
        with open(out_dir / "manifest.json", "w") as mf:
            json.dump(manifest, mf, indent=2)

        step("Commercial ready!", 100)

        db.increment_videos_used(user_id)

        # Extract hooks/CTAs from ad copy variants for display
        hooks = [v.headline for v in ad_copy.variants[:3]]
        ctas = [v.cta for v in ad_copy.variants[:3]]

        _push_commercial(job_id, {
            "status": "done",
            "progress": 100,
            "script": full_script_display,
            "voiceover": voiceover_text,
            "video_url": f"/api/commercial/{job_id}/download" if final_video else None,
            "video_path": final_video,
            "audio_path": audio_path,
            "media_description": media_description,
            "strategy": {
                "usp": ad_copy.variants[0].headline if ad_copy.variants else brand,
                "target": audience,
                "hooks": hooks,
                "ctas": ctas,
                "angle": style,
            },
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        _push_commercial(job_id, {"status": "error", "error": str(e), "progress": 0})


def _commercial_video_path(job_id: str):
    """Return the video file path from a finished commercial job, or None."""
    import json as _json
    with _commercial_lock:
        events = list(_commercial_jobs.get(job_id, []))
    for ev in reversed(events):
        if ev.startswith("data: "):
            try:
                d = _json.loads(ev[6:])
                vp = d.get("video_path")
                if vp and Path(vp).exists():
                    return vp
            except Exception:
                pass
    return None


# ── Commercial broadcast: YouTube upload ─────────────────────────────────────

@app.route("/api/commercial/<job_id>/broadcast/youtube", methods=["POST"])
@login_required
def commercial_broadcast_youtube(job_id):
    data = request.get_json(silent=True) or {}
    video_path = _commercial_video_path(job_id)
    if not video_path:
        return jsonify({"error": "Video not ready. Generate the commercial first."}), 400

    if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
        return jsonify({"error": "YouTube OAuth not configured. Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in Render environment variables."}), 400

    accounts = db.get_accounts(current_user.id)
    yt_account = next((a for a in accounts if a["platform"] == "youtube"), None)
    if not yt_account:
        return jsonify({"error": "YouTube not connected.", "needs_auth": True,
                        "auth_url": "/oauth/youtube/start"}), 401

    title = (data.get("title") or "").strip() or "AI Commercial"
    description = (data.get("description") or "").strip()
    privacy = data.get("privacy", "public")
    if privacy not in ("public", "unlisted", "private"):
        privacy = "public"

    try:
        import googleapiclient.discovery
        import googleapiclient.http
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest

        creds = Credentials(
            token=yt_account["access_token"],
            refresh_token=yt_account.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.YOUTUBE_CLIENT_ID,
            client_secret=config.YOUTUBE_CLIENT_SECRET,
            scopes=config.YOUTUBE_SCOPES,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            db.upsert_account(
                platform="youtube",
                username=yt_account["username"],
                display_name=yt_account.get("display_name"),
                avatar_url=yt_account.get("avatar_url"),
                access_token=creds.token,
                refresh_token=creds.refresh_token,
                account_id=yt_account.get("account_id"),
                followers=yt_account.get("followers", 0),
                user_id=current_user.id,
            )

        yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds,
                                             cache_discovery=False)
        body = {
            "snippet": {
                "title": title,
                "description": description or "Commercial generated by Social Money.",
                "categoryId": "22",
                "tags": ["commercial", "advertisement", "ai generated"],
            },
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
        media = googleapiclient.http.MediaFileUpload(
            video_path, mimetype="video/mp4", chunksize=-1, resumable=True,
        )
        insert_req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = insert_req.next_chunk()

        video_id = response["id"]
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        return jsonify({"success": True, "url": youtube_url, "video_id": video_id,
                        "platform": "youtube"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Commercial broadcast: Twitch RTMP stream ──────────────────────────────────

_twitch_broadcast_jobs: dict = {}   # job_id -> {status, error, channel_url}
_twitch_broadcast_lock = threading.Lock()


def _run_twitch_broadcast(job_id: str, video_path: str, stream_key: str,
                          channel_url: str, title: str):
    """Background thread: stream an MP4 to Twitch via RTMP using imageio-ffmpeg."""
    try:
        import subprocess
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        with _twitch_broadcast_lock:
            _twitch_broadcast_jobs[job_id] = {"status": "streaming", "channel_url": channel_url}

        rtmp_url = f"rtmp://live.twitch.tv/live/{stream_key}"
        cmd = [
            ffmpeg_exe, "-re", "-i", video_path,
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", "3000k", "-maxrate", "3000k", "-bufsize", "6000k",
            "-pix_fmt", "yuv420p", "-g", "50",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100",
            "-f", "flv", rtmp_url,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = proc.communicate(timeout=300)

        if proc.returncode == 0:
            with _twitch_broadcast_lock:
                _twitch_broadcast_jobs[job_id] = {"status": "done", "channel_url": channel_url}
        else:
            err_text = stderr.decode("utf-8", errors="replace")[-400:]
            with _twitch_broadcast_lock:
                _twitch_broadcast_jobs[job_id] = {"status": "error",
                                                   "error": err_text,
                                                   "channel_url": channel_url}
    except Exception as exc:
        with _twitch_broadcast_lock:
            _twitch_broadcast_jobs[job_id] = {"status": "error", "error": str(exc),
                                               "channel_url": channel_url}


@app.route("/api/commercial/<job_id>/broadcast/twitch", methods=["POST"])
@login_required
def commercial_broadcast_twitch(job_id):
    data = request.get_json(silent=True) or {}
    video_path = _commercial_video_path(job_id)
    if not video_path:
        return jsonify({"error": "Video not ready. Generate the commercial first."}), 400

    accounts = db.get_accounts(current_user.id)
    tw_account = next((a for a in accounts if a["platform"] == "twitch"), None)
    if not tw_account:
        return jsonify({"error": "Twitch not connected.", "needs_auth": True,
                        "auth_url": "/oauth/twitch/start"}), 401

    access_token = tw_account["access_token"]
    broadcaster_id = tw_account.get("account_id", "")
    username = tw_account.get("username", "")

    try:
        # Fetch stream key
        key_resp = requests.get(
            "https://api.twitch.tv/helix/streams/key",
            params={"broadcaster_id": broadcaster_id},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": config.TWITCH_CLIENT_ID,
            },
            timeout=10,
        )
        if key_resp.status_code != 200:
            return jsonify({"error": f"Could not fetch stream key: {key_resp.text}"}), 502
        stream_key = key_resp.json().get("data", [{}])[0].get("stream_key", "")
        if not stream_key:
            return jsonify({"error": "Stream key not found. Make sure your Twitch account has streaming enabled."}), 400

        # Optionally update channel title
        title = (data.get("title") or "").strip() or "AI Commercial — Live Now"
        requests.patch(
            "https://api.twitch.tv/helix/channels",
            params={"broadcaster_id": broadcaster_id},
            json={"title": title, "game_id": "509670"},  # 509670 = "Just Chatting"
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": config.TWITCH_CLIENT_ID,
                "Content-Type": "application/json",
            },
            timeout=10,
        )

        channel_url = f"https://www.twitch.tv/{username}"
        bcast_job_id = f"{job_id}-twitch"
        t = threading.Thread(
            target=_run_twitch_broadcast,
            args=(bcast_job_id, video_path, stream_key, channel_url, title),
            daemon=True,
        )
        t.start()
        return jsonify({"success": True, "broadcast_id": bcast_job_id,
                        "channel_url": channel_url, "platform": "twitch"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/commercial/broadcast/twitch/<broadcast_id>/status")
@login_required
def commercial_twitch_broadcast_status(broadcast_id):
    with _twitch_broadcast_lock:
        info = dict(_twitch_broadcast_jobs.get(broadcast_id, {"status": "unknown"}))
    return jsonify(info)


@app.route("/api/commercial/<job_id>/audio")
@login_required
def commercial_audio(job_id):
    with _commercial_lock:
        events = _commercial_jobs.get(job_id, [])
    import json as _json
    for ev in reversed(events):
        if ev.startswith("data: "):
            try:
                data = _json.loads(ev[6:])
                if data.get("audio_path") and Path(data["audio_path"]).exists():
                    return send_file(data["audio_path"], mimetype="audio/mpeg")
            except Exception:
                pass
    return jsonify({"error": "Audio not ready"}), 404


@app.route("/api/commercial/<job_id>/download")
@login_required
def commercial_download(job_id):
    force_dl = request.args.get("dl") == "1"
    with _commercial_lock:
        events = _commercial_jobs.get(job_id, [])
    import json as _json
    for ev in reversed(events):
        if ev.startswith("data: "):
            try:
                data = _json.loads(ev[6:])
                vp = data.get("video_path")
                if vp and Path(vp).exists():
                    p = Path(vp)
                    mime = "video/mp4"
                    ext = p.suffix.lower()
                    if ext == ".webm":
                        mime = "video/webm"
                    elif ext == ".mov":
                        mime = "video/quicktime"
                    return send_file(p, mimetype=mime,
                                     as_attachment=force_dl,
                                     download_name=f"commercial{ext or '.mp4'}")
            except Exception:
                pass
    return jsonify({"error": "Video not ready"}), 404


# ── Health check (required by Render) ────────────────────────────────────────

@app.route("/health")
def health():
    from generators.higgsfield_cli import is_authenticated as hf_cli_ok
    return jsonify({"status": "ok", "version": "1.0", "higgsfield_cli": hf_cli_ok()})


@app.route("/api/admin/higgsfield-token", methods=["POST"])
@login_required
def set_higgsfield_token():
    if not current_user.is_admin:
        return jsonify({"error": "Admin only"}), 403
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "token is required"}), 400
    cred_file = Path.home() / ".config" / "higgsfield" / "credentials.json"
    cred_file.parent.mkdir(parents=True, exist_ok=True)
    cred_file.write_text(json.dumps({"access_token": token, "token_type": "Bearer"}))
    import generators.higgsfield_cli as _hf_cli
    _hf_cli._SEEDED = False
    return jsonify({"ok": True, "message": "Higgsfield CLI token updated"})


# ── Credit / Cost Manager (Admin) ─────────────────────────────────────────────

@app.route("/admin/credits")
@login_required
def admin_credits_page():
    if not current_user.is_admin:
        abort(403)
    return render_template("admin/credits.html")


@app.route("/api/admin/credits")
@login_required
def admin_credits_api():
    if not current_user.is_admin:
        return jsonify({"error": "Admin only"}), 403
    import requests as _req
    from generators.ai_video_generator import HIGGSVILLE_API_BASE
    try:
        token = config.HIGGSFIELD_MCP_TOKEN
        if not token:
            from generators.higgsfield_cli import _CRED_FILE
            if _CRED_FILE.exists():
                token = json.loads(_CRED_FILE.read_text()).get("access_token", "")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"} if token else {}
        bal_r = _req.get(f"{HIGGSVILLE_API_BASE}/billing/balance", headers=headers, timeout=10)
        bal = bal_r.json() if bal_r.ok else {}
        txn_r = _req.get(f"{HIGGSVILLE_API_BASE}/billing/transactions?size=50", headers=headers, timeout=10)
        txn = txn_r.json() if txn_r.ok else {}
    except Exception:
        bal, txn = {}, {}

    credits = bal.get("credits", 0)
    plan = bal.get("subscription_plan_type", "unknown")
    items = txn.get("items", [])

    total_spent = sum(abs(t["credits"]) for t in items if t.get("action") == "spend")
    total_refund = sum(abs(t["credits"]) for t in items if t.get("action") == "refund")
    total_grant = sum(abs(t["credits"]) for t in items if t.get("action") == "grant")
    net_used = total_spent - total_refund

    model_costs = {}
    for t in items:
        if t.get("action") == "spend":
            name = t.get("display_name", "Unknown")
            model_costs.setdefault(name, {"count": 0, "total": 0})
            model_costs[name]["count"] += 1
            model_costs[name]["total"] += abs(t["credits"])

    user_count = 0
    try:
        user_count = db.get_admin_stats().get("total_users", 0)
    except Exception:
        pass

    return jsonify({
        "credits": credits,
        "plan": plan,
        "total_spent": total_spent,
        "total_refund": total_refund,
        "total_grant": total_grant,
        "net_used": net_used,
        "model_costs": model_costs,
        "transactions": items[:30],
        "user_count": user_count,
        "low_credit_warning": credits < 50,
        "critical_warning": credits < 20,
    })


# ── Background Threads ────────────────────────────────────────────────────────

_bg_threads_started = False
_bg_threads_lock = threading.Lock()


def _scheduler_thread():
    """Check scheduled posts every 60 seconds and publish due ones."""
    while True:
        try:
            due_posts = db.get_due_scheduled_posts()
            for post in due_posts:
                db.update_scheduled_post(post["id"], status="posting")
                try:
                    _execute_scheduled_post(post)
                    db.update_scheduled_post(
                        post["id"], status="posted", posted_at=datetime.utcnow().isoformat()
                    )
                    try:
                        from notifications import send_notification
                        send_notification(post["user_id"], "schedule_posted", {
                            "platform": post["platform"], "job_id": post["job_id"],
                        })
                    except Exception:
                        pass
                except Exception as e:
                    db.update_scheduled_post(post["id"], status="error", error_msg=str(e))
                    try:
                        from notifications import send_notification
                        send_notification(post["user_id"], "schedule_error", {
                            "platform": post["platform"], "error": str(e),
                        })
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(60)


def _execute_scheduled_post(post: dict):
    """Upload/publish a scheduled post to the target platform."""
    video_path = post.get("video_path")
    if not video_path or not Path(video_path).exists():
        raise ValueError("Video file not found")
    platform = post.get("platform", "youtube")
    import social_optimize
    title = post.get("job_title") or "Scheduled Video"
    description = post.get("description") or title
    social_optimize.publish_to_platforms(
        video_path=video_path,
        title=title,
        description=description,
        hashtags=post.get("hashtags") or [],
        keywords=post.get("keywords") or [],
        platforms=[platform],
        privacy="public",
        is_short=(post.get("format") == "short"),
        cdn_url=post.get("cdn_url") or "",
    )


def _competitor_refresh_thread():
    """Refresh competitor channel data every 6 hours."""
    while True:
        time.sleep(6 * 3600)
        try:
            channels = db.get_all_competitor_channels_for_refresh()
            for comp in channels:
                _refresh_competitor_videos(
                    comp["id"], comp["channel_id"], comp["platform"], comp["user_id"]
                )
        except Exception:
            pass


def _memory_eviction_thread():
    """Hourly sweep: remove stale in-memory job event lists to prevent RAM growth."""
    while True:
        time.sleep(3600)
        try:
            for store, lock in (
                (_job_events, _job_lock),
                (_studio_events, _studio_lock),
                (_commercial_jobs, _commercial_lock),
            ):
                _evict_old_job_events(store, lock)
        except Exception:
            pass


def start_background_threads():
    global _bg_threads_started
    with _bg_threads_lock:
        if _bg_threads_started:
            return
        _bg_threads_started = True
    t1 = threading.Thread(target=_scheduler_thread, daemon=True, name="scheduler")
    t1.start()
    t2 = threading.Thread(target=_competitor_refresh_thread, daemon=True, name="competitor_refresh")
    t2.start()
    t3 = threading.Thread(target=_memory_eviction_thread, daemon=True, name="mem_evict")
    t3.start()


# ── RSS Feeds ────────────────────────────────────────────────────────────────

@app.route("/api/rss/feeds", methods=["GET"])
@login_required
def api_rss_feeds():
    feeds = db.get_rss_feeds(current_user.id)
    return jsonify(feeds)

@app.route("/api/rss/feeds", methods=["POST"])
@login_required
def api_rss_add_feed():
    data = request.json or {}
    if not data.get("url"):
        return jsonify({"error": "url required"}), 400
    feed_id = db.add_rss_feed(current_user.id, data["url"], data.get("name", ""), data.get("category", ""))
    return jsonify({"status": "added", "id": feed_id})

@app.route("/api/rss/feeds/<int:feed_id>", methods=["DELETE"])
@login_required
def api_rss_delete_feed(feed_id):
    db.delete_rss_feed(feed_id, current_user.id)
    return jsonify({"status": "deleted"})


# ── DM Templates ────────────────────────────────────────────────────────────

@app.route("/api/dm/templates", methods=["GET"])
@login_required
def api_dm_templates():
    return jsonify(db.get_dm_templates(current_user.id))

@app.route("/api/dm/templates", methods=["POST"])
@login_required
def api_dm_add_template():
    data = request.json or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    tmpl_id = db.create_dm_template(
        current_user.id, data["name"], data.get("message_template", ""),
        platform=data.get("platform", ""), trigger_on=data.get("trigger_on", ""))
    return jsonify({"status": "created", "id": tmpl_id})

@app.route("/api/dm/templates/<int:tmpl_id>", methods=["DELETE"])
@login_required
def api_dm_delete_template(tmpl_id):
    db.delete_dm_template(tmpl_id, current_user.id)
    return jsonify({"status": "deleted"})

@app.route("/api/dm/send", methods=["POST"])
@login_required
def api_dm_send():
    data = request.json or {}
    from generators.engagement_engine import send_dm
    result = send_dm(current_user.id, data.get("platform", ""), data.get("target_username", ""),
                     message=data.get("message"))
    return jsonify(result)


# ── Auto-Reply Rules ────────────────────────────────────────────────────────

@app.route("/api/auto-reply/rules", methods=["GET"])
@login_required
def api_auto_reply_rules():
    platform = request.args.get("platform")
    return jsonify(db.get_auto_reply_rules(current_user.id, platform))

@app.route("/api/auto-reply/rules", methods=["POST"])
@login_required
def api_auto_reply_add_rule():
    data = request.json or {}
    if not data.get("trigger_value") or not data.get("reply_template"):
        return jsonify({"error": "trigger_value and reply_template required"}), 400
    rule_id = db.create_auto_reply_rule(
        current_user.id, data.get("platform", ""), data.get("trigger_type", "keyword"),
        data["trigger_value"], data["reply_template"], data.get("uses_spintax", False))
    return jsonify({"status": "created", "id": rule_id})

@app.route("/api/auto-reply/rules/<int:rule_id>", methods=["DELETE"])
@login_required
def api_auto_reply_delete_rule(rule_id):
    db.delete_auto_reply_rule(rule_id, current_user.id)
    return jsonify({"status": "deleted"})


# ── Follow Tracking ──────────────────────────────────────────────────────────

@app.route("/api/follows", methods=["GET"])
@login_required
def api_follows():
    return jsonify(db.get_follows(current_user.id))

@app.route("/api/follows", methods=["POST"])
@login_required
def api_follow_track():
    data = request.json or {}
    if not data.get("target_username"):
        return jsonify({"error": "target_username required"}), 400
    fid = db.track_follow(current_user.id, data.get("platform", ""), data["target_username"])
    return jsonify({"status": "tracked", "id": fid})

@app.route("/api/follows/stale", methods=["GET"])
@login_required
def api_follows_stale():
    days = int(request.args.get("days", 7))
    return jsonify(db.get_stale_follows(current_user.id, days))

@app.route("/api/follows/auto-unfollow", methods=["POST"])
@login_required
def api_auto_unfollow():
    data = request.json or {}
    from generators.engagement_engine import auto_unfollow_stale
    results = auto_unfollow_stale(current_user.id, days_threshold=data.get("days", 7))
    return jsonify({"unfollowed": results})


# ── Growth Analytics ─────────────────────────────────────────────────────────

@app.route("/api/growth/snapshot", methods=["POST"])
@login_required
def api_growth_snapshot():
    data = request.json or {}
    if not data.get("account_id") or not data.get("platform"):
        return jsonify({"error": "account_id and platform required"}), 400
    snap_id = db.add_growth_snapshot(
        current_user.id, data["account_id"], data["platform"],
        followers=data.get("followers", 0), following=data.get("following", 0),
        posts=data.get("posts", 0), engagement_rate=data.get("engagement_rate", 0),
        views_total=data.get("views_total", 0), likes_total=data.get("likes_total", 0))
    return jsonify({"status": "recorded", "id": snap_id})

@app.route("/api/growth/history", methods=["GET"])
@login_required
def api_growth_history():
    account_id = request.args.get("account_id", type=int)
    return jsonify(db.get_growth_history(current_user.id, account_id))

@app.route("/api/growth/summary", methods=["GET"])
@login_required
def api_growth_summary():
    return jsonify(db.get_growth_summary(current_user.id))


# ── Hashtag Research ─────────────────────────────────────────────────────────

@app.route("/api/hashtags/research", methods=["GET"])
@login_required
def api_hashtag_research():
    topic = request.args.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required"}), 400
    hashtags = [f"#{topic.lower().replace(' ', '')}", f"#{topic.lower().replace(' ', '')}tips",
                f"#{topic.lower().replace(' ', '')}2024", "#viral", "#trending"]
    return jsonify({"hashtags": hashtags, "topic": topic})


# ── Account Warmup ───────────────────────────────────────────────────────────

@app.route("/api/warmup/status", methods=["GET"])
@login_required
def api_warmup_status():
    account_created = request.args.get("account_created")
    if not account_created:
        return jsonify({"error": "account_created required"}), 400
    from datetime import datetime
    try:
        created = datetime.fromisoformat(account_created.replace("Z", "+00:00"))
    except Exception:
        created = datetime.utcnow()
    age_days = (datetime.utcnow() - created.replace(tzinfo=None)).days
    if age_days < 7:
        phase = "seedling"
    elif age_days < 30:
        phase = "growing"
    elif age_days < 90:
        phase = "established"
    else:
        phase = "mature"
    return jsonify({"phase": phase, "age_days": age_days, "account_created": account_created})

@app.route("/api/warmup/limits", methods=["GET"])
@login_required
def api_warmup_limits():
    platform = request.args.get("platform", "")
    account_created = request.args.get("account_created", "")
    if not account_created:
        return jsonify({"error": "account_created required"}), 400
    limits = {"follows_per_day": 20, "likes_per_day": 50, "comments_per_day": 10, "dms_per_day": 5}
    return jsonify({"limits": limits, "platform": platform})


# ── Spintax Preview ──────────────────────────────────────────────────────────

@app.route("/api/spintax/preview", methods=["POST"])
@login_required
def api_spintax_preview():
    data = request.json or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required"}), 400
    from utils.spintax import validate, spin_batch, estimate_variations
    ok, msg = validate(text)
    if not ok:
        return jsonify({"error": msg}), 400
    count = data.get("count", 5)
    variations = spin_batch(text, count)
    return jsonify({"variations": variations, "total_possible": estimate_variations(text)})


# ── User Scraper ─────────────────────────────────────────────────────────────

@app.route("/api/scraper/run", methods=["POST"])
@login_required
def api_scraper_run():
    data = request.json or {}
    if not data.get("target"):
        return jsonify({"error": "target required"}), 400
    return jsonify({"status": "complete", "platform": data.get("platform", ""), "target": data["target"], "count": 0, "users": []})


# ── Engagement Center ─────────────────────────────────────────────────────────

@app.route("/engagement")
@login_required
def engagement_page():
    stats = db.get_engagement_stats(current_user.id)
    campaigns = db.get_engagement_campaigns(current_user.id)
    return render_template("engagement.html", stats=stats, campaigns=campaigns)


@app.route("/api/engagement/campaigns", methods=["GET"])
@login_required
def api_engagement_campaigns_list():
    camps = db.get_engagement_campaigns(current_user.id)
    return jsonify(camps)


@app.route("/api/engagement/campaigns", methods=["POST"])
@login_required
def api_engagement_campaigns_create():
    data = request.json or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    if not data.get("platforms"):
        return jsonify({"error": "platforms required"}), 400
    camp_id = db.create_engagement_campaign(
        user_id=current_user.id,
        name=data["name"],
        platforms=data.get("platforms"),
        target_niche=data.get("target_niche", ""),
        strategy=data.get("strategy", "growth"),
        daily_limit=data.get("daily_limit", 50),
    )
    return jsonify({"status": "created", "campaign_id": camp_id})


@app.route("/api/engagement/campaigns/<campaign_id>", methods=["GET"])
@login_required
def api_engagement_campaign_get(campaign_id):
    try:
        campaign_id = int(campaign_id)
    except (ValueError, TypeError):
        return jsonify({"error": "not found"}), 404
    camp = db.get_engagement_campaign(campaign_id, current_user.id)
    if not camp:
        return jsonify({"error": "not found"}), 404
    stats = db.get_engagement_stats(current_user.id)
    recent = db.get_engagement_actions(current_user.id, campaign_id=campaign_id, limit=10)
    targets = db.get_engagement_targets(current_user.id, campaign_id)
    return jsonify({"campaign": camp, "stats": stats, "recent_actions": recent, "targets": targets})


@app.route("/api/engagement/campaigns/<campaign_id>", methods=["PUT"])
@login_required
def api_engagement_campaign_update(campaign_id):
    try:
        campaign_id = int(campaign_id)
    except (ValueError, TypeError):
        return jsonify({"error": "not found"}), 404
    data = request.json or {}
    db.update_engagement_campaign(campaign_id, **data)
    return jsonify({"status": "updated"})


@app.route("/api/engagement/campaigns/<campaign_id>", methods=["DELETE"])
@login_required
def api_engagement_campaign_delete(campaign_id):
    try:
        campaign_id = int(campaign_id)
    except (ValueError, TypeError):
        return jsonify({"error": "not found"}), 404
    db.delete_engagement_campaign(campaign_id, current_user.id)
    return jsonify({"status": "deleted"})


@app.route("/api/engagement/campaigns/<campaign_id>/targets", methods=["POST"])
@login_required
def api_engagement_targets_add(campaign_id):
    try:
        campaign_id = int(campaign_id)
    except (ValueError, TypeError):
        return jsonify({"error": "not found"}), 404
    camp = db.get_engagement_campaign(campaign_id, current_user.id)
    if not camp:
        return jsonify({"error": "campaign not found"}), 404
    data = request.json or {}
    targets = data.get("targets", [])
    if not targets:
        return jsonify({"error": "targets list required"}), 400
    added = 0
    for t in targets:
        db.add_engagement_target(
            user_id=current_user.id,
            campaign_id=campaign_id,
            platform=t.get("platform", ""),
            username=t.get("username", ""),
            followers=t.get("followers", 0),
        )
        added += 1
    return jsonify({"status": "added", "added": added})


@app.route("/api/engagement/actions", methods=["POST"])
@login_required
def api_engagement_actions_create():
    data = request.json or {}
    if not data.get("platform") or not data.get("action_type") or not data.get("target_url"):
        return jsonify({"error": "platform, action_type, and target_url required"}), 400
    action_id = db.create_engagement_action(
        user_id=current_user.id,
        platform=data["platform"],
        action_type=data["action_type"],
        target_url=data.get("target_url", ""),
        comment_text=data.get("comment_text", ""),
        campaign_id=data.get("campaign_id"),
    )
    return jsonify({"status": "queued", "action_id": action_id})


@app.route("/api/engagement/stats", methods=["GET"])
@login_required
def api_engagement_stats():
    stats = db.get_engagement_stats(current_user.id)
    return jsonify(stats)


# ── The Cut ───────────────────────────────────────────────────────────────────

_editing_jobs: dict = {}
_editing_events: dict = {}
_editing_lock = threading.Lock()


def _push_editing_event(job_id: str, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _editing_lock:
        if job_id not in _editing_events:
            _editing_events[job_id] = []
        _editing_events[job_id].append(payload)


def _run_editing_thread(editing_job_id: str, params: dict, user_id: int = None):
    from generators.editing_room import produce, STUDIO_PRESETS
    from pathlib import Path as P

    def _cb(msg, pct):
        with _editing_lock:
            if editing_job_id in _editing_jobs:
                _editing_jobs[editing_job_id].update({"progress": pct, "step": msg, "status": "running"})
        _push_editing_event(editing_job_id, {"progress": pct, "step": msg, "status": "running"})

    with _editing_lock:
        _editing_jobs[editing_job_id] = {"status": "running", "progress": 0, "step": "Starting..."}

    try:
        studio = params.get("studio", "hollywood")
        topic = params.get("topic", STUDIO_PRESETS.get(studio, {}).get("default_topic", "Untitled"))
        sections = params.get("sections", [])
        subtitle = params.get("subtitle", "")
        source_job_id = params.get("source_job_id")

        output_dir = P(config.OUTPUT_DIR) / "editing_room" / editing_job_id
        use_ai_clips = params.get("use_ai_clips", False)
        custom_bgm = params.get("custom_bgm_path")
        section_media = params.get("section_media", {})
        result = produce(
            studio=studio, topic=topic, sections=sections,
            output_dir=output_dir, subtitle=subtitle, progress_cb=_cb,
            use_ai_clips=use_ai_clips, custom_bgm_path=custom_bgm,
            section_media=section_media,
        )

        # Create a job record in the DB so it shows in /jobs and can be remixed
        db_job_id = db.create_job(
            topic=topic, format=f"editing_{studio}",
            platforms=[], audience="general public",
            voice="espeak", style=studio, privacy="private",
            user_id=user_id,
        )
        db.update_job(
            db_job_id, status="done", progress=100,
            current_step="Complete!", title=topic,
            duration=result["duration"],
            video_path=result["output_path"],
            manifest_path=str(output_dir / "manifest.json"),
            completed_at=datetime.now().isoformat(),
        )
        # Save manifest
        import json as _json
        manifest = {**result, "db_job_id": db_job_id, "source_job_id": source_job_id, "sections": sections}
        with open(output_dir / "manifest.json", "w") as f:
            _json.dump(manifest, f, indent=2)

        if user_id:
            db.increment_user_usage(user_id, videos=1)

        with _editing_lock:
            _editing_jobs[editing_job_id].update({
                "status": "done", "progress": 100, "step": "Complete!",
                "result": result, "db_job_id": db_job_id,
            })
        _push_editing_event(editing_job_id, {
            "progress": 100, "step": "Complete!", "status": "done",
            "result": result, "db_job_id": db_job_id,
        })

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        with _editing_lock:
            _editing_jobs[editing_job_id].update({"status": "error", "step": f"Error: {e}", "traceback": tb})
        _push_editing_event(editing_job_id, {"status": "error", "step": f"Error: {e}", "traceback": tb})


@app.route("/editing-room")
@login_required
def editing_room_page():
    jobs = db.get_jobs(limit=50, user_id=current_user.id)
    return render_template("editing_room.html", jobs=jobs, active_page="editing-room")


@app.route("/editing-room/remix/<int:job_id>")
@login_required
def editing_room_remix(job_id):
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return redirect("/editing-room")
    jobs = db.get_jobs(limit=50, user_id=current_user.id)
    return render_template("editing_room.html", jobs=jobs, remix_job=job, active_page="editing-room")


@app.route("/api/editing-room/produce", methods=["POST"])
@login_required
def api_editing_room_produce():
    allowed, err = check_usage_gate(current_user.id)
    if not allowed:
        return jsonify({"error": err, "upgrade": True}), 403

    data = request.json or {}
    studio = data.get("studio", "hollywood")
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Topic/title is required"}), 400

    sections = data.get("sections", [])
    if not sections:
        return jsonify({"error": "At least one section is required"}), 400

    # Resolve custom BGM track
    bgm_track_id = data.get("bgm_track_id")
    bgm_type = data.get("bgm_type", "track")
    custom_bgm_path = None
    if bgm_track_id:
        if bgm_type == "catalog":
            p = Path(config.OUTPUT_DIR) / "music_catalog" / f"{bgm_track_id}.mp3"
            if p.exists():
                custom_bgm_path = str(p)
        elif bgm_type == "upload":
            meta_path = Path(config.OUTPUT_DIR) / "music_uploads" / str(current_user.id) / f"{bgm_track_id}.json"
            if meta_path.exists():
                with open(meta_path) as _mf:
                    _meta = json.load(_mf)
                p = Path(_meta.get("path", ""))
                if p.exists():
                    custom_bgm_path = str(p)
        else:
            bgm_dir = Path(config.OUTPUT_DIR) / "music_studio" / bgm_track_id
            for name in ("track.mp3", "beat.mp3"):
                p = bgm_dir / name
                if p.exists():
                    custom_bgm_path = str(p)
                    break

    editing_job_id = str(uuid.uuid4())
    params = {
        "studio": studio,
        "topic": topic,
        "sections": sections,
        "subtitle": (data.get("subtitle") or "").strip(),
        "source_job_id": data.get("source_job_id"),
        "use_ai_clips": bool(data.get("use_ai_clips", False)),
        "custom_bgm_path": custom_bgm_path,
        "section_media": data.get("section_media", {}),
    }

    t = threading.Thread(
        target=_run_editing_thread,
        args=(editing_job_id, params, current_user.id),
        daemon=True,
    )
    t.start()
    return jsonify({"editing_job_id": editing_job_id})


@app.route("/api/editing-room/stream/<editing_job_id>")
@login_required
def editing_room_stream(editing_job_id):
    def generate():
        last_idx = 0
        while True:
            with _editing_lock:
                events = _editing_events.get(editing_job_id, [])
                new = events[last_idx:]
                last_idx = len(events)
                job = _editing_jobs.get(editing_job_id, {})
            for event in new:
                yield event
            if job.get("status") in ("done", "error"):
                if not new:
                    yield f"data: {json.dumps({'status': job.get('status'), 'progress': job.get('progress', 0)})}\n\n"
                time.sleep(0.3)
                break
            time.sleep(0.4)
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/editing-room/status/<editing_job_id>")
@login_required
def editing_room_status(editing_job_id):
    with _editing_lock:
        job = _editing_jobs.get(editing_job_id)
    if job is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


# ── The Cut Media Upload ──────────────────────────────────────────────────
@app.route("/api/editing-room/upload-media", methods=["POST"])
@login_required
def editing_room_upload_media():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file"}), 400
    ext = Path(f.filename).suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    video_exts = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".flv", ".3gp", ".ts", ".mts", ".wmv", ".mpg", ".mpeg"}
    if ext not in image_exts | video_exts:
        return jsonify({"error": "Unsupported file type"}), 400
    media_id = str(uuid.uuid4())
    media_dir = Path(config.OUTPUT_DIR) / "editing_media" / str(current_user.id)
    media_dir.mkdir(parents=True, exist_ok=True)
    is_video = ext in video_exts
    dest = media_dir / f"{media_id}{ext}"
    f.save(str(dest))
    if is_video and ext != ".mp4":
        converted = media_dir / f"{media_id}.mp4"
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(dest), "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(converted)],
            capture_output=True, timeout=300,
        )
        if result.returncode == 0:
            dest.unlink(missing_ok=True)
            dest = converted
            ext = ".mp4"
    return jsonify({"media_id": media_id, "path": str(dest), "type": "video" if is_video else "image", "filename": f.filename})


@app.route("/api/editing-room/upload-media/<media_id>")
@login_required
def editing_room_serve_media(media_id):
    media_dir = Path(config.OUTPUT_DIR) / "editing_media" / str(current_user.id)
    for f in media_dir.glob(f"{media_id}.*"):
        return send_file(str(f))
    return "", 404


# ── Studio Intelligence API ──────────────────────────────────────────────────

@app.route("/api/studio-intelligence")
@login_required
def api_studio_intelligence():
    """Get learning stats and recommendations for all studios."""
    from generators.studio_intelligence import get_studio_stats, get_recommendations
    from generators.studio_blueprints import BLUEPRINTS
    studios = {}
    for name, bp in BLUEPRINTS.items():
        studios[name] = {
            "identity": bp["identity"],
            "great_at": bp["great_at"],
            "stats": get_studio_stats(name),
            "recommendations": get_recommendations(name),
        }
    return jsonify(studios)


@app.route("/api/studio-intelligence/<studio_name>")
@login_required
def api_studio_intelligence_detail(studio_name):
    """Get detailed intelligence for a specific studio."""
    from generators.studio_intelligence import get_studio_stats, get_recommendations
    from generators.studio_blueprints import get_blueprint
    try:
        bp = get_blueprint(studio_name)
    except ValueError:
        return jsonify({"error": "Unknown studio"}), 404
    genre = request.args.get("genre", "")
    return jsonify({
        "identity": bp["identity"],
        "great_at": bp["great_at"],
        "blueprint": bp,
        "stats": get_studio_stats(studio_name),
        "recommendations": get_recommendations(studio_name, genre=genre),
    })


@app.route("/api/job/<int:job_id>/rate", methods=["POST"])
@login_required
def api_rate_job(job_id):
    """User rates a job output 1-5 to feed the learning loop."""
    from generators.studio_intelligence import record_user_rating
    rating = request.json.get("rating", 0)
    if not 1 <= rating <= 5:
        return jsonify({"error": "Rating must be 1-5"}), 400
    record_user_rating(job_id, rating)
    return jsonify({"ok": True, "rating": rating})


# ── Startup ───────────────────────────────────────────────────────────────────

init_monetizer_tables()
from generators.studio_intelligence import init_intelligence_tables
init_intelligence_tables()
_load_platform_creds_from_db()
# ── Agency Command Center ─────────────────────────────────────────────────────

@app.route("/agency")
@login_required
def agency_page():
    stats = db.get_agency_stats(current_user.id)
    clients = db.get_agency_clients(current_user.id)
    deals = db.get_agency_deals(current_user.id)
    projects = db.get_agency_projects(current_user.id)
    return render_template("agency.html", stats=stats, clients=clients, deals=deals, projects=projects)

@app.route("/api/agency/clients", methods=["GET"])
@login_required
def api_agency_clients_list():
    status = request.args.get("status")
    return jsonify(db.get_agency_clients(current_user.id, status=status))

@app.route("/api/agency/clients", methods=["POST"])
@login_required
def api_agency_clients_create():
    data = request.get_json(force=True)
    if not data.get("name"):
        return jsonify({"error": "Name required"}), 400
    cid = db.create_agency_client(current_user.id, data)
    return jsonify({"id": cid, "ok": True}), 201

@app.route("/api/agency/clients/<int:cid>", methods=["PUT"])
@login_required
def api_agency_clients_update(cid):
    data = request.get_json(force=True)
    db.update_agency_client(current_user.id, cid, data)
    return jsonify({"ok": True})

@app.route("/api/agency/clients/<int:cid>", methods=["DELETE"])
@login_required
def api_agency_clients_delete(cid):
    db.delete_agency_client(current_user.id, cid)
    return jsonify({"ok": True})

@app.route("/api/agency/deals", methods=["GET"])
@login_required
def api_agency_deals_list():
    client_id = request.args.get("client_id", type=int)
    stage = request.args.get("stage")
    return jsonify(db.get_agency_deals(current_user.id, client_id=client_id, stage=stage))

@app.route("/api/agency/deals", methods=["POST"])
@login_required
def api_agency_deals_create():
    data = request.get_json(force=True)
    if not data.get("title"):
        return jsonify({"error": "Title required"}), 400
    did = db.create_agency_deal(current_user.id, data)
    return jsonify({"id": did, "ok": True}), 201

@app.route("/api/agency/deals/<int:did>", methods=["PUT"])
@login_required
def api_agency_deals_update(did):
    data = request.get_json(force=True)
    db.update_agency_deal(current_user.id, did, data)
    return jsonify({"ok": True})

@app.route("/api/agency/deals/<int:did>", methods=["DELETE"])
@login_required
def api_agency_deals_delete(did):
    db.delete_agency_deal(current_user.id, did)
    return jsonify({"ok": True})

@app.route("/api/agency/projects", methods=["GET"])
@login_required
def api_agency_projects_list():
    client_id = request.args.get("client_id", type=int)
    status = request.args.get("status")
    return jsonify(db.get_agency_projects(current_user.id, client_id=client_id, status=status))

@app.route("/api/agency/projects", methods=["POST"])
@login_required
def api_agency_projects_create():
    data = request.get_json(force=True)
    if not data.get("name"):
        return jsonify({"error": "Name required"}), 400
    pid = db.create_agency_project(current_user.id, data)
    return jsonify({"id": pid, "ok": True}), 201

@app.route("/api/agency/projects/<int:pid>", methods=["PUT"])
@login_required
def api_agency_projects_update(pid):
    data = request.get_json(force=True)
    db.update_agency_project(current_user.id, pid, data)
    return jsonify({"ok": True})

@app.route("/api/agency/revenue", methods=["GET"])
@login_required
def api_agency_revenue_list():
    client_id = request.args.get("client_id", type=int)
    period = request.args.get("period")
    return jsonify(db.get_agency_revenue(current_user.id, client_id=client_id, period=period))

@app.route("/api/agency/revenue", methods=["POST"])
@login_required
def api_agency_revenue_create():
    data = request.get_json(force=True)
    if not data.get("amount"):
        return jsonify({"error": "Amount required"}), 400
    db.create_agency_revenue(current_user.id, data)
    return jsonify({"ok": True}), 201

@app.route("/api/agency/stats")
@login_required
def api_agency_stats():
    return jsonify(db.get_agency_stats(current_user.id))

@app.route("/api/agency/proposals", methods=["POST"])
@login_required
def api_agency_proposal_generate():
    """Use Claude to generate a professional proposal for a deal."""
    data = request.get_json(force=True)
    deal_id = data.get("deal_id")
    if not deal_id:
        return jsonify({"error": "deal_id required"}), 400
    deals = db.get_agency_deals(current_user.id)
    deal = next((d for d in deals if d["id"] == deal_id), None)
    if not deal:
        return jsonify({"error": "Deal not found"}), 404
    client = None
    if deal.get("client_id"):
        clients = db.get_agency_clients(current_user.id)
        client = next((c for c in clients if c["id"] == deal["client_id"]), None)

    prompt = f"""Generate a professional agency proposal for the following deal:
Client: {client['name'] if client else 'Unknown'} ({client.get('company','') if client else ''})
Industry: {client.get('industry','') if client else ''}
Deal: {deal['title']}
Value: ${deal['value']:,.2f}
Service: {deal.get('service_type','content creation')}
Description: {deal.get('description','')}

Create a compelling proposal with:
1. Executive Summary
2. Proposed Services & Deliverables
3. Timeline & Milestones
4. Pricing Breakdown
5. Why Social Optimize (our AI-powered platform creates content 10x faster)

Format in clean HTML with inline styles. Professional, concise, persuasive."""

    try:
        import anthropic
        ac = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = ac.messages.create(model="claude-sonnet-4-6", max_tokens=2000,
                                 messages=[{"role": "user", "content": prompt}])
        html = msg.content[0].text
        return jsonify({"proposal_html": html, "ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Agency Assets ─────────────────────────────────────────────────────────────

@app.route("/api/agency/assets", methods=["GET"])
@login_required
def api_agency_assets_list():
    client_id = request.args.get("client_id", type=int)
    project_id = request.args.get("project_id", type=int)
    status = request.args.get("status")
    return jsonify(db.get_agency_assets(current_user.id, client_id=client_id, project_id=project_id, status=status))

@app.route("/api/agency/assets", methods=["POST"])
@login_required
def api_agency_assets_create():
    data = request.get_json(force=True)
    result = db.create_agency_asset(current_user.id, data)
    return jsonify(result), 201

@app.route("/api/agency/assets/<int:aid>", methods=["PUT"])
@login_required
def api_agency_assets_update(aid):
    data = request.get_json(force=True)
    db.update_agency_asset(current_user.id, aid, data)
    return jsonify({"ok": True})

@app.route("/api/agency/jobs/<int:job_id>/link", methods=["POST"])
@login_required
def api_agency_link_job(job_id):
    data = request.get_json(force=True)
    client_id = data.get("client_id")
    project_id = data.get("project_id")
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    job = db.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    db.link_job_to_client(job_id, client_id, project_id)
    return jsonify({"ok": True})


# ── Agency Follow-ups ─────────────────────────────────────────────────────────

@app.route("/api/agency/followups", methods=["GET"])
@login_required
def api_agency_followups_list():
    client_id = request.args.get("client_id", type=int)
    status = request.args.get("status")
    return jsonify(db.get_agency_followups(current_user.id, client_id=client_id, status=status))

@app.route("/api/agency/followups", methods=["POST"])
@login_required
def api_agency_followups_create():
    data = request.get_json(force=True)
    if not data.get("client_id"):
        return jsonify({"error": "client_id required"}), 400
    if not data.get("scheduled_at"):
        from datetime import datetime, timezone
        data["scheduled_at"] = datetime.now(timezone.utc).isoformat()
    fid = db.create_agency_followup(current_user.id, data)
    return jsonify({"id": fid, "ok": True}), 201

@app.route("/api/agency/followups/<int:fid>", methods=["PUT"])
@login_required
def api_agency_followups_update(fid):
    data = request.get_json(force=True)
    db.update_agency_followup(fid, data)
    return jsonify({"ok": True})

@app.route("/api/agency/followups/<int:fid>", methods=["DELETE"])
@login_required
def api_agency_followups_delete(fid):
    db.delete_agency_followup(current_user.id, fid)
    return jsonify({"ok": True})

@app.route("/api/agency/followups/generate", methods=["POST"])
@login_required
def api_agency_followup_ai_generate():
    """Use Claude to generate a personalized follow-up email."""
    data = request.get_json(force=True)
    client_id = data.get("client_id")
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    clients = db.get_agency_clients(current_user.id)
    client = next((c for c in clients if c["id"] == client_id), None)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    context = data.get("context", "initial outreach")
    prompt = f"""Write a professional, warm follow-up email for an agency client.

Client: {client['name']}
Company: {client.get('company', '')}
Industry: {client.get('industry', '')}
Status: {client.get('status', 'lead')}
Context: {context}

Write a compelling, personalized email. Be concise (under 150 words).
Return JSON with "subject" and "body" keys only."""

    try:
        import anthropic
        ac = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = ac.messages.create(model="claude-sonnet-4-6", max_tokens=500,
                                 messages=[{"role": "user", "content": prompt}])
        text = msg.content[0].text
        import re
        json_match = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = {"subject": "Following up", "body": text}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


start_background_threads()

# Start the job monitor agent (auto-resets stuck jobs every 5 min)
from agents.job_monitor import start as _start_monitor  # noqa: E402
_start_monitor()

# Start agency workers
from agents.followup_agent import start as _start_followup  # noqa: E402
_start_followup()
from agents.asset_tracker import start as _start_asset_tracker  # noqa: E402
_start_asset_tracker()

# Start executive C-suite agents (IEBC Consultants)
from agents.executive_bus import init_bus_tables as _init_bus  # noqa: E402
_init_bus()
from agents.marcus_growth import start as _start_marcus  # noqa: E402
_start_marcus()
from agents.elena_enterprise import start as _start_elena  # noqa: E402
_start_elena()
from agents.julian_retention import start as _start_julian  # noqa: E402
_start_julian()
from agents.sterling_business import start as _start_sterling  # noqa: E402
_start_sterling()

if __name__ == "__main__":
    print("\n  Social Money - Command Center")
    print("  Open → http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
