"""
Social Optimize Machine - Web Dashboard
Flask application serving the command center UI.
"""
import json
import os
import csv

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
import database as db
import config
from auth import auth_bp, make_user
from billing import billing_bp, check_usage_gate

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    data = db.get_user_by_id(int(user_id))
    return make_user(data) if data else None

app.register_blueprint(auth_bp)
app.register_blueprint(billing_bp)

ALLOWED_EXTENSIONS = {"csv", "vcf", "vcard", "txt"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


_job_events: dict = {}
_job_lock = threading.Lock()


def push_event(job_id: int, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _job_lock:
        if job_id not in _job_events:
            _job_events[job_id] = []
        _job_events[job_id].append(payload)


def _run_job_thread(job_id: int, params: dict, user_id: int = None):
    import social_optimize
    steps = [
        (10, "Generating script with Claude AI..."),
        (25, "Creating voiceover audio..."),
        (40, "Fetching stock media..."),
        (55, "Generating thumbnail..."),
        (75, "Assembling video..."),
        (90, "Publishing to platforms..."),
    ]
    class ProgressHook:
        def __init__(self):
            self.step_idx = 0
        def advance(self, msg=None):
            if self.step_idx < len(steps):
                pct, label = steps[self.step_idx]
                m = msg or label
                db.update_job(job_id, progress=pct, current_step=m, status="running")
                push_event(job_id, {"progress": pct, "step": m, "status": "running"})
                self.step_idx += 1
    hook = ProgressHook()
    try:
        db.update_job(job_id, status="running", progress=5, current_step="Starting...")
        push_event(job_id, {"progress": 5, "step": "Starting...", "status": "running"})
        hook.advance()
        import utils.logger as ul
        _orig_step = ul.step
        _orig_success = ul.success
        _orig_warn = ul.warn
        def _hook_step(icon, msg):
            _orig_step(icon, msg)
            hook.advance(msg)
        def _hook_success(msg):
            _orig_success(msg)
            push_event(job_id, {"log": f"✓ {msg}", "status": "running"})
        def _hook_warn(msg):
            _orig_warn(msg)
            push_event(job_id, {"log": f"⚠ {msg}", "status": "running"})
        ul.step = _hook_step
        ul.success = _hook_success
        ul.warn = _hook_warn
        manifest = social_optimize.run(**params)
        ul.step = _orig_step
        ul.success = _orig_success
        ul.warn = _orig_warn
        job_title = manifest.get("title")
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
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        db.update_job(job_id, status="error", error_msg=str(e), current_step="Failed")
        push_event(job_id, {"progress": 0, "step": f"Error: {e}", "status": "error", "traceback": tb})
        if user_id:
            try:
                from notifications import send_notification
                send_notification(user_id, "job_error", {"job_id": job_id, "error": str(e)})
            except Exception:
                pass


@app.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html", tiers=config.TIERS)


@app.route("/pricing")
def pricing():
    if current_user.is_authenticated:
        return redirect(url_for("billing.billing_page"))
    return render_template("pricing.html", tiers=config.TIERS)


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
            "linkedin":  "LinkedIn: 300-500 chars, professional insight angle, 3-5 industry hashtags",
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
    "linkedin": "...",
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
    db.increment_user_usage(current_user.id, videos=1)
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
        # ai_model: "claude" (premium) or "gemini" (budget/batch)
        "ai_model": data.get("ai_model", "claude"),
    }
    t = threading.Thread(target=_run_job_thread, args=(job_id, params, current_user.id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<int:job_id>/stream")
@login_required
def job_stream(job_id):
    def generate():
        last_idx = 0
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
    return render_template("job_detail.html", job=job, dubs=dubs, dub_languages=DUB_LANGUAGES)


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


# ── Social Accounts ───────────────────────────────────────────────────────────

@app.route("/accounts")
@login_required
def accounts_page():
    accounts = db.get_accounts(user_id=current_user.id)
    connected = {a["platform"] for a in accounts if a.get("is_active", True)}
    return render_template(
        "accounts.html",
        accounts=accounts,
        connected=connected,
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
    import secrets, hashlib, base64
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
            try: name = str(vcard.fn.value)
            except Exception:
                try:
                    n = vcard.n.value
                    name = f"{n.given} {n.family}".strip()
                except Exception: pass
            email = ""
            try: email = str(vcard.email.value)
            except Exception: pass
            phone = ""
            try: phone = str(vcard.tel.value)
            except Exception: pass
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
        if not c.get("name"): continue
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
        "Hello! You've reached Social Optimize. "
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
    if updates:
        db.update_user(current_user.id, **updates)
    return jsonify({"status": "saved"})


@app.route("/api/research/preview", methods=["POST"])
def api_research_preview():
    topic = (request.json or {}).get("topic", "").strip()
    if not topic or len(topic) < 4:
        return jsonify({"facts": [], "sources": [], "data_points": []})
    try:
        from generators.researcher import research_topic, brief_to_context
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


@app.route("/api/settings/check")
def api_settings_check():
    return jsonify({
        "anthropic":   bool(config.ANTHROPIC_API_KEY),
        "pexels":      bool(config.PEXELS_API_KEY),
        "google_flow": bool(config.GOOGLE_API_KEY),
        "higgsville":  bool(config.HIGGSFIELD_MCP_TOKEN),
        "youtube":     bool(config.YOUTUBE_CLIENT_ID),
        "tiktok":      bool(config.TIKTOK_CLIENT_KEY),
        "instagram":   bool(config.INSTAGRAM_ACCESS_TOKEN),
    })


# ── Production Studio ─────────────────────────────────────────────────────────

_studio_jobs: dict = {}
_studio_events: dict = {}
_studio_lock = threading.Lock()


def _push_studio_event(job_id: str, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _studio_lock:
        if job_id not in _studio_events:
            _studio_events[job_id] = []
        _studio_events[job_id].append(payload)


def _run_studio_thread(studio_job_id: str, params: dict, user_id: int = None):
    from generators.production_engine import ProductionStudioEngine
    def _cb(msg: str, pct: int):
        with _studio_lock:
            if studio_job_id in _studio_jobs:
                _studio_jobs[studio_job_id].update({"progress": pct, "step": msg, "status": "running"})
        _push_studio_event(studio_job_id, {"progress": pct, "step": msg, "status": "running"})
    with _studio_lock:
        _studio_jobs[studio_job_id] = {"status": "running", "progress": 0, "step": "Initialising…"}
    try:
        user_tier = params.get("subscription_tier", "free")
        engine = ProductionStudioEngine(
            monthly_budget=params.get("monthly_budget", 500), progress_callback=_cb,
            subscription_tier=user_tier,
        )
        result = engine.run_daily_pipeline(
            niche=params["niche"], remaining_credits=params.get("remaining_credits", 500),
            target_duration=params.get("target_duration", 480),
            audience=params.get("audience", ""), is_portrait=params.get("is_portrait", False),
            voice=params.get("voice") or config.DEFAULT_VOICE,
            thumbnail_style=params.get("thumbnail_style", "fire"),
            privacy=params.get("privacy", "private"), dry_run=params.get("dry_run", False),
            research_enabled=params.get("research_enabled", True),
            competitor_titles=params.get("competitor_titles") or [],
            platforms=params.get("platforms") or [],
        )
        result_dict = result.model_dump()
        with _studio_lock:
            _studio_jobs[studio_job_id].update({
                "status": "done", "progress": 100,
                "step": "Production complete!", "result": result_dict,
            })
        _push_studio_event(studio_job_id, {
            "progress": 100, "step": "Production complete!",
            "status": "done", "result": result_dict,
        })
        if user_id:
            try:
                from notifications import send_notification
                send_notification(user_id, "job_complete", {
                    "job_id": studio_job_id, "title": result_dict.get("title", "Studio Production"),
                })
            except Exception:
                pass
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        with _studio_lock:
            _studio_jobs[studio_job_id].update({"status": "error", "step": f"Error: {e}", "traceback": tb})
        _push_studio_event(studio_job_id, {"status": "error", "step": f"Error: {e}", "traceback": tb})


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
        "dry_run": bool(data.get("dry_run", True)),
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


# ── Hollywood AI Agent ────────────────────────────────────────────────────────

@app.route("/hollywood")
@login_required
def hollywood_page():
    return render_template("hollywood.html")


@app.route("/api/hollywood/chat", methods=["POST"])
@login_required
def hollywood_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not message:
        return jsonify({"error": "No message"}), 400
    try:
        from generators.hollywood_agent import chat as hollywood_chat_fn
        reply = hollywood_chat_fn(message=message, history=history, user_id=current_user.id)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    user = db.get_user_by_id(current_user.id)
    tier = config.TIERS.get(user["subscription_tier"], config.TIERS["free"])
    limit = tier["videos_per_month"]
    if limit != -1:
        remaining = limit - user["videos_used"]
        if remaining < len(topics):
            return jsonify({
                "error": f"Not enough quota. You have {remaining} videos left this month but requested {len(topics)}.",
                "upgrade": True,
            }), 403
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
    try:
        accounts = db.get_accounts(user_id=user_id)
        yt_account = next((a for a in accounts if a["platform"] == "youtube" and a.get("access_token")), None)
        if not yt_account:
            return
        from google.oauth2.credentials import Credentials
        import googleapiclient.discovery
        creds = Credentials(
            token=yt_account["access_token"], refresh_token=yt_account.get("refresh_token"),
            client_id=config.YOUTUBE_CLIENT_ID, client_secret=config.YOUTUBE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
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
    except Exception:
        pass


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
        if platform == "youtube" and config.YOUTUBE_CLIENT_ID:
            accounts = db.get_accounts(user_id=current_user.id)
            yt_account = next((a for a in accounts if a["platform"] == "youtube" and a.get("access_token")), None)
            if yt_account:
                from google.oauth2.credentials import Credentials
                import googleapiclient.discovery
                creds = Credentials(
                    token=yt_account["access_token"], refresh_token=yt_account.get("refresh_token"),
                    client_id=config.YOUTUBE_CLIENT_ID, client_secret=config.YOUTUBE_CLIENT_SECRET,
                    token_uri="https://oauth2.googleapis.com/token",
                )
                yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
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
                    else:
                        resp = {"items": []}
                if resp.get("items"):
                    ch = resp["items"][0]
                    channel_id = ch["id"]
                    channel_name = ch["snippet"]["title"]
    except Exception:
        pass
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


# ── Commercial Studio ─────────────────────────────────────────────────────────

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

    file = request.files.get("media")
    brand     = (request.form.get("brand") or "").strip()
    tagline   = (request.form.get("tagline") or "").strip()
    audience  = (request.form.get("audience") or "general consumers").strip()
    style     = request.form.get("style") or "energetic"
    duration  = int(request.form.get("duration") or 15)
    platforms = request.form.getlist("platforms")
    voice     = request.form.get("voice") or config.DEFAULT_VOICE

    if not file or not _allowed_commercial(file.filename):
        return jsonify({"error": "Please upload a photo or video (jpg, png, mp4, mov)"}), 400

    job_id = str(uuid.uuid4())
    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    media_path = COMMERCIAL_UPLOADS / f"{job_id}.{ext}"
    file.save(str(media_path))

    params = {
        "brand": brand, "tagline": tagline, "audience": audience,
        "style": style, "duration": duration, "platforms": platforms,
        "voice": voice, "media_path": str(media_path), "ext": ext,
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
    payload = f"data: {json.dumps(data)}\n\n"
    with _commercial_lock:
        if job_id not in _commercial_jobs:
            _commercial_jobs[job_id] = []
        _commercial_jobs[job_id].append(payload)


def _run_commercial_thread(job_id: str, params: dict, user_id: int):
    import anthropic as _ant
    import base64

    def step(msg, pct):
        _push_commercial(job_id, {"status": "running", "step": msg, "progress": pct})

    try:
        step("Analyzing your media with AI...", 10)

        media_path = Path(params["media_path"])
        ext = params["ext"]
        is_video = ext in {"mp4", "mov", "avi", "webm"}
        brand    = params.get("brand") or "our product"
        tagline  = params.get("tagline") or ""
        audience = params.get("audience") or "general consumers"
        style    = params.get("style") or "energetic"
        duration = params.get("duration") or 15

        # ── Step 1: Analyze media with Claude Vision ──────────────────────────
        client = _ant.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        if is_video:
            media_description = f"a {ext} video clip"
            image_content = []
        else:
            img_bytes = media_path.read_bytes()
            b64 = base64.standard_b64encode(img_bytes).decode()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "webp": "image/webp",
                    "gif": "image/gif"}.get(ext, "image/jpeg")
            image_content = [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": "Describe this image in detail: what product or subject is shown, colors, mood, setting, and what makes it visually compelling for advertising."}
            ]
            analysis = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=400,
                messages=[{"role": "user", "content": image_content}]
            )
            media_description = analysis.content[0].text

        step("Writing commercial script...", 30)

        # ── Step 2: Write commercial script ──────────────────────────────────
        script_prompt = f"""You are a world-class commercial director and copywriter.

Media description: {media_description}
Brand: {brand}
Tagline: {tagline or '(none)'}
Target audience: {audience}
Ad style: {style}
Duration: {duration} seconds

Write a {duration}-second commercial script with:
1. HOOK (0-3s): An attention-grabbing opening line or visual
2. PROBLEM/DESIRE (3-8s): What the viewer wants or their pain point
3. SOLUTION (8-{duration-3}s): How this product/brand solves it, key benefit
4. CTA ({duration-3}-{duration}s): Strong call to action

Then write an AI VIDEO PROMPT (2-3 sentences) describing the exact visual to generate — cinematic, specific camera movements, lighting, colors. Make it feel like a real commercial.

Format:
SCRIPT:
[Hook]: ...
[Problem]: ...
[Solution]: ...
[CTA]: ...

VOICEOVER: [The actual words spoken, {duration} seconds worth]

VIDEO_PROMPT: [Detailed cinematic prompt for AI video generation]"""

        script_resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=800,
            messages=[{"role": "user", "content": script_prompt}]
        )
        script_text = script_resp.content[0].text

        # Parse video prompt
        video_prompt = ""
        if "VIDEO_PROMPT:" in script_text:
            video_prompt = script_text.split("VIDEO_PROMPT:")[-1].strip()
        else:
            video_prompt = f"Cinematic product commercial for {brand}. {style} style. Professional lighting, close-up product shots, dynamic camera movement. 4K quality."

        voiceover_text = ""
        if "VOICEOVER:" in script_text:
            raw = script_text.split("VOICEOVER:")[-1]
            voiceover_text = raw.split("VIDEO_PROMPT:")[0].strip()

        step("Generating AI commercial video...", 50)

        # ── Step 3: Generate video with Higgsfield ───────────────────────────
        from generators.ai_video_generator import generate_higgsville_clips, HIGGSVILLE_MODELS
        out_dir = COMMERCIAL_UPLOADS / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Use marketing_studio_video for product ads, grok for image-to-video
        model_id = "grok_video_v15" if not is_video else "marketing_studio_video"

        clips = generate_higgsville_clips(
            prompts=[video_prompt],
            output_dir=out_dir,
            model_id=model_id,
            aspect_ratio="9:16",
            duration=min(duration, 10),
        )

        step("Adding voiceover...", 75)

        # ── Step 4: Generate voiceover ────────────────────────────────────────
        final_video = str(clips[0]) if clips else None
        audio_path = None

        if voiceover_text and config.GOOGLE_API_KEY:
            try:
                from generators.audio_generator import generate_audio
                audio_out = out_dir / "voiceover.mp3"
                generate_audio(voiceover_text, str(audio_out), voice=params.get("voice"))
                audio_path = str(audio_out)
            except Exception as e:
                print(f"[commercial] Voiceover error: {e}")

        step("Commercial ready!", 100)

        db.increment_credits_used(user_id, 1)

        _push_commercial(job_id, {
            "status": "done",
            "progress": 100,
            "script": script_text,
            "voiceover": voiceover_text,
            "video_url": f"/api/commercial/{job_id}/download" if final_video else None,
            "video_path": final_video,
            "audio_path": audio_path,
            "media_description": media_description,
        })

    except Exception as e:
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
                "description": description or f"Commercial generated by Social Optimize Machine.",
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


@app.route("/api/commercial/<job_id>/download")
@login_required
def commercial_download(job_id):
    with _commercial_lock:
        events = _commercial_jobs.get(job_id, [])
    import json as _json
    for ev in reversed(events):
        if ev.startswith("data: "):
            try:
                data = _json.loads(ev[6:])
                if data.get("video_path") and Path(data["video_path"]).exists():
                    return send_file(data["video_path"], as_attachment=True,
                                     download_name="commercial.mp4")
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
    try:
        import social_optimize
        if platform == "youtube":
            social_optimize.publish_to_youtube(
                video_path=video_path, title=post.get("job_title") or "Scheduled Video", privacy="public",
            )
        elif platform == "tiktok":
            social_optimize.publish_to_tiktok(
                video_path=video_path, title=post.get("job_title") or "Scheduled Video",
            )
        elif platform == "instagram":
            social_optimize.publish_to_instagram(
                video_path=video_path, title=post.get("job_title") or "Scheduled Video",
            )
        else:
            raise ValueError(f"Unsupported platform: {platform}")
    except AttributeError:
        # social_optimize may not have these functions yet — fail gracefully
        raise ValueError(f"Platform publishing not implemented for: {platform}")


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


# ── Startup ───────────────────────────────────────────────────────────────────

db.init_db()
start_background_threads()

if __name__ == "__main__":
    print("\n  Social Optimize Machine - Command Center")
    print("  Open → http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
