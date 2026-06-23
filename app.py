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
import agent_dispatch
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

UPLOAD_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent)) / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _auto_save_to_library(user_id, manifest):
    """Save generated video/thumbnail/audio to the user's media library."""
    if not user_id or not manifest:
        return
    files = manifest.get("files", {})
    title = manifest.get("title", "Untitled")
    for key, category in [("video", "generated-video"), ("thumbnail", "generated-thumbnail"),
                          ("audio", "generated-audio"), ("script", "generated-script")]:
        path = files.get(key)
        if not path or not Path(path).exists():
            continue
        try:
            p = Path(path)
            db.add_media(
                user_id=user_id,
                filename=p.name,
                original_name=f"{title} - {key}{p.suffix}",
                file_path=str(p),
                file_size=p.stat().st_size,
                mime_type={"video": "video/mp4", "thumbnail": "image/png",
                           "audio": "audio/mpeg", "script": "text/plain"}.get(key, ""),
                category=category,
                tags=[title, key, "auto-generated"],
                description=f"Auto-saved from job: {title}",
            )
        except Exception:
            pass


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
    agent_dispatch.dispatch_async("content_create", {
        "summary": params.get("topic", "")[:100],
        "user_id": user_id,
        "job_id": job_id,
        "format": params.get("format", "short"),
    })
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
            _auto_save_to_library(user_id, manifest)
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


# ── Social Accounts ───────────────────────────────────────────────────────────────────────────────

@app.route("/accounts")
@login_required
def accounts_page():
    accounts = db.get_accounts(user_id=current_user.id)
    return render_template("accounts.html", accounts=accounts)


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
    )
    return redirect("/accounts?connected=tiktok")


@app.route("/oauth/instagram/start")
def oauth_instagram_start():
    if not config.INSTAGRAM_ACCESS_TOKEN:
        return jsonify({"error": "Instagram credentials not configured in .env"}), 400
    return redirect("/accounts?modal=instagram")


# ── Contacts ─────────────────────────────────────────────────────────────────────────────────

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


# ── Settings ─────────────────────────────────────────────────────────────────────────────────

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


# ── Production Studio ─────────────────────────────────────────────────────────────────────────────

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
    agent_dispatch.dispatch_async("studio_production", {
        "summary": params.get("niche", "")[:100],
        "user_id": user_id,
        "job_id": studio_job_id,
    })
    from generators.production_engine import ProductionStudioEngine
    def _cb(msg: str, pct: int):
        with _studio_lock:
            if studio_job_id in _studio_jobs:
                _studio_jobs[studio_job_id].update({"progress": pct, "step": msg, "status": "running"})
        _push_studio_event(studio_job_id, {"progress": pct, "step": msg, "status": "running"})
    with _studio_lock:
        _studio_jobs[studio_job_id] = {"status": "running", "progress": 0, "step": "Initialising…"}
    try:
        engine = ProductionStudioEngine(
            monthly_budget=params.get("monthly_budget", 500), progress_callback=_cb,
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
            try:
                _auto_save_to_library(user_id, result_dict)
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
    params = {
        "niche": niche,
        "remaining_credits": int(data.get("remaining_credits") or 500),
        "monthly_budget": int(data.get("monthly_budget") or 500),
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


# ── Hollywood AI Agent ────────────────────────────────────────────────────────────────────────────

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


# ── Feature 1: Analytics Dashboard ─────────────────────────────────────────────────────────────────

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


# ── Google Trends API ────────────────────────────────────────────────────────────────────────────

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


# ── Thumbnail Vision Score API ──────────────────────────────────────────────────────────────────────

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


# ── Feature 2: Content Calendar + Scheduler ───────────────────────────────────────────────────

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


# ── Feature 3: Batch Mode ──────────────────────────────────────────────────────────────────────────

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


# ── Feature 4: Template Library ────────────────────────────────────────────────────────────────────────

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


# ── Feature 5: Multi-language Auto-Dub ─────────────────────────────────────────────────────────────────

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


# ── Feature 6: Notifications ────────────────────────────────────────────────────────────────────────

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


# ── Feature 7: Team Workspaces ───────────────────────────────────────────────────────────────────────────

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


# ── Feature 8: Competitor Tracker ────────────────────────────────────────────────────────────────────────

@app.route("/engagement")
@login_required
def engagement_page():
    campaigns = db.get_engagement_campaigns(current_user.id)
    stats = db.get_engagement_stats(current_user.id)
    return render_template("engagement.html", campaigns=campaigns, stats=stats)


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


# ── RSS Feeds ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/rss/feeds", methods=["GET"])
@login_required
def api_rss_feeds():
    feeds = db.get_rss_feeds(current_user.id)
    return jsonify(feeds)


@app.route("/api/rss/feeds", methods=["POST"])
@login_required
def api_add_rss_feed():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    name = data.get("name", "")
    category = data.get("category", "")
    feed_id = db.add_rss_feed(current_user.id, url, name, category)
    return jsonify({"status": "added", "id": feed_id})


@app.route("/api/rss/feeds/<int:feed_id>", methods=["DELETE"])
@login_required
def api_delete_rss_feed(feed_id):
    db.delete_rss_feed(feed_id, current_user.id)
    return jsonify({"status": "deleted"})


# ── DM Templates ───────────────────────────────────────────────────────────────────────────

@app.route("/api/dm/templates", methods=["GET"])
@login_required
def api_dm_templates():
    return jsonify(db.get_dm_templates(current_user.id))


@app.route("/api/dm/templates", methods=["POST"])
@login_required
def api_add_dm_template():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    message_template = (data.get("message_template") or "").strip()
    if not name or not message_template:
        return jsonify({"error": "name and message_template are required"}), 400
    tmpl_id = db.create_dm_template(
        current_user.id, name, message_template,
        platform=data.get("platform"),
        trigger_on=data.get("trigger_on"),
        uses_spintax=bool(data.get("uses_spintax")),
    )
    return jsonify({"status": "created", "id": tmpl_id})


@app.route("/api/dm/templates/<int:tmpl_id>", methods=["DELETE"])
@login_required
def api_delete_dm_template(tmpl_id):
    db.delete_dm_template(tmpl_id, current_user.id)
    return jsonify({"status": "deleted"})


@app.route("/api/dm/send", methods=["POST"])
@login_required
def api_dm_send():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    target = (data.get("target_username") or "").strip()
    message = (data.get("message") or "").strip()
    if not platform or not target:
        return jsonify({"error": "platform and target_username required"}), 400
    from generators.engagement_engine import send_dm
    result = send_dm(current_user.id, platform, target, message=message)
    return jsonify(result)


# ── Auto-Reply Rules ──────────────────────────────────────────────────────────────────────

@app.route("/api/auto-reply/rules", methods=["GET"])
@login_required
def api_auto_reply_rules():
    return jsonify(db.get_auto_reply_rules(current_user.id))


@app.route("/api/auto-reply/rules", methods=["POST"])
@login_required
def api_add_auto_reply_rule():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    trigger_type = (data.get("trigger_type") or "").strip()
    trigger_value = (data.get("trigger_value") or "").strip()
    reply_template = (data.get("reply_template") or "").strip()
    if not all([platform, trigger_type, trigger_value, reply_template]):
        return jsonify({"error": "platform, trigger_type, trigger_value, and reply_template are required"}), 400
    rule_id = db.create_auto_reply_rule(
        current_user.id, platform, trigger_type, trigger_value, reply_template,
        uses_spintax=bool(data.get("uses_spintax")),
    )
    return jsonify({"status": "created", "id": rule_id})


@app.route("/api/auto-reply/rules/<int:rule_id>", methods=["DELETE"])
@login_required
def api_delete_auto_reply_rule(rule_id):
    db.delete_auto_reply_rule(rule_id, current_user.id)
    return jsonify({"status": "deleted"})


# ── Hashtag Research ──────────────────────────────────────────────────────────────────────

@app.route("/api/hashtags/research")
@login_required
def api_hashtag_research():
    topic = request.args.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "topic parameter is required"}), 400
    platform = request.args.get("platform", "youtube")
    count = int(request.args.get("count", 10))
    from generators.hashtag_research import get_best_hashtags
    hashtags = get_best_hashtags(topic, platform=platform, count=count)
    return jsonify({"hashtags": hashtags, "topic": topic, "platform": platform})


# ── Growth Analytics ──────────────────────────────────────────────────────────────────────

@app.route("/api/growth/snapshot", methods=["POST"])
@login_required
def api_growth_snapshot():
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    platform = data.get("platform", "")
    if not account_id:
        return jsonify({"error": "account_id is required"}), 400
    snap_id = db.add_growth_snapshot(
        current_user.id, account_id, platform,
        followers=int(data.get("followers", 0)),
        following=int(data.get("following", 0)),
        posts=int(data.get("posts", 0)),
        engagement_rate=float(data.get("engagement_rate", 0)),
        views_total=int(data.get("views_total", 0)),
        likes_total=int(data.get("likes_total", 0)),
    )
    return jsonify({"status": "recorded", "id": snap_id})


@app.route("/api/growth/history")
@login_required
def api_growth_history():
    account_id = request.args.get("account_id", type=int)
    platform = request.args.get("platform")
    history = db.get_growth_history(current_user.id, account_id=account_id, platform=platform)
    return jsonify(history)


@app.route("/api/growth/summary")
@login_required
def api_growth_summary():
    return jsonify(db.get_growth_summary(current_user.id))


# ── Follow Tracking ──────────────────────────────────────────────────────────────────────

@app.route("/api/follows", methods=["GET"])
@login_required
def api_get_follows():
    platform = request.args.get("platform")
    status = request.args.get("status")
    return jsonify(db.get_follows(current_user.id, platform=platform, status=status))


@app.route("/api/follows", methods=["POST"])
@login_required
def api_track_follow():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    target = (data.get("target_username") or "").strip()
    if not platform or not target:
        return jsonify({"error": "platform and target_username are required"}), 400
    fid = db.track_follow(current_user.id, platform, target)
    return jsonify({"status": "tracked", "id": fid})


@app.route("/api/follows/stale")
@login_required
def api_stale_follows():
    days = int(request.args.get("days", 3))
    platform = request.args.get("platform")
    stale = db.get_stale_follows(current_user.id, platform=platform, days_threshold=days)
    return jsonify(stale)


@app.route("/api/follows/auto-unfollow", methods=["POST"])
@login_required
def api_auto_unfollow():
    data = request.get_json(silent=True) or {}
    days = int(data.get("days", 3))
    platform = data.get("platform")
    from generators.engagement_engine import auto_unfollow_stale
    results = auto_unfollow_stale(current_user.id, platform=platform, days_threshold=days)
    return jsonify({"unfollowed": results, "count": len(results)})


# ── Account Warmup ───────────────────────────────────────────────────────────────────────

@app.route("/api/warmup/status")
@login_required
def api_warmup_status():
    account_created = request.args.get("account_created", "").strip()
    if not account_created:
        return jsonify({"error": "account_created parameter is required"}), 400
    from generators.account_warmup import get_warmup_status
    return jsonify(get_warmup_status(account_created))


@app.route("/api/warmup/limits")
@login_required
def api_warmup_limits():
    platform = request.args.get("platform", "youtube")
    account_created = request.args.get("account_created", "")
    if not account_created:
        return jsonify({"error": "account_created parameter is required"}), 400
    from generators.account_warmup import get_warmed_limits
    limits = get_warmed_limits(platform, account_created)
    return jsonify({"limits": limits, "platform": platform})


# ── Spintax Preview ──────────────────────────────────────────────────────────────────────

@app.route("/api/spintax/preview", methods=["POST"])
@login_required
def api_spintax_preview():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    from utils.spintax import validate, spin_batch, estimate_variations
    ok, msg = validate(text)
    if not ok:
        return jsonify({"error": msg}), 400
    count = int(data.get("count", 5))
    variations = spin_batch(text, count)
    total = estimate_variations(text)
    agent_dispatch.dispatch_async("spintax_process", {
        "summary": f"Generated {count} variations",
        "user_id": current_user.id,
    })
    return jsonify({"variations": variations, "total_possible": total})


# ── User Scraper ─────────────────────────────────────────────────────────────────────────

@app.route("/api/scraper/run", methods=["POST"])
@login_required
def api_scraper_run():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    target = (data.get("target") or "").strip()
    if not platform or not target:
        return jsonify({"error": "platform and target are required"}), 400
    method = data.get("method", "commenters")
    from generators.user_scraper import scrape_by_platform
    users = scrape_by_platform(platform, target, method=method)
    return jsonify({"users": [u.to_dict() if hasattr(u, 'to_dict') else u for u in users], "count": len(users)})


# ── Engagement Campaigns ─────────────────────────────────────────────────────────────────

@app.route("/api/engagement/campaigns", methods=["GET"])
@login_required
def api_engagement_campaigns():
    return jsonify(db.get_engagement_campaigns(current_user.id))


@app.route("/api/engagement/campaigns", methods=["POST"])
@login_required
def api_create_engagement_campaign():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    platforms = data.get("platforms", [])
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not platforms:
        return jsonify({"error": "platforms is required"}), 400
    campaign_id = db.create_engagement_campaign(
        current_user.id, name, platforms, data.get("config", {}),
    )
    return jsonify({"status": "created", "campaign_id": campaign_id})


@app.route("/api/engagement/campaigns/<campaign_id>", methods=["GET"])
@login_required
def api_get_engagement_campaign(campaign_id):
    campaign = db.get_engagement_campaign(campaign_id, current_user.id)
    if not campaign:
        return jsonify({"error": "not found"}), 404
    targets = db.get_engagement_targets(current_user.id, campaign_id)
    actions = db.get_engagement_actions(current_user.id, campaign_id=campaign_id)
    stats = db.get_engagement_stats(current_user.id)
    return jsonify({
        "campaign": campaign,
        "targets": targets,
        "recent_actions": actions[:20],
        "stats": stats,
    })


@app.route("/api/engagement/campaigns/<campaign_id>", methods=["PUT", "PATCH"])
@login_required
def api_update_engagement_campaign(campaign_id):
    data = request.get_json(silent=True) or {}
    db.update_engagement_campaign(campaign_id, current_user.id, **data)
    return jsonify({"status": "updated"})


@app.route("/api/engagement/campaigns/<campaign_id>", methods=["DELETE"])
@login_required
def api_delete_engagement_campaign(campaign_id):
    db.delete_engagement_campaign(campaign_id, current_user.id)
    return jsonify({"status": "deleted"})


@app.route("/api/engagement/campaigns/<campaign_id>/targets", methods=["POST"])
@login_required
def api_add_engagement_targets(campaign_id):
    data = request.get_json(silent=True) or {}
    targets = data.get("targets", [])
    if not targets:
        return jsonify({"error": "targets list is required"}), 400
    campaign = db.get_engagement_campaign(campaign_id, current_user.id)
    if not campaign:
        return jsonify({"error": "campaign not found"}), 404
    count = db.add_engagement_targets(campaign_id, targets)
    return jsonify({"status": "added", "added": count})


@app.route("/api/engagement/campaigns/<campaign_id>/actions", methods=["POST"])
@login_required
def api_create_campaign_action(campaign_id):
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    action_type = (data.get("action_type") or "").strip()
    if not platform or not action_type:
        return jsonify({"error": "platform and action_type are required"}), 400
    action_id = db.create_engagement_action(
        user_id=current_user.id, platform=platform, action_type=action_type,
        target_username=data.get("target_username", ""),
        target_content_id=data.get("target_content_id", ""),
        campaign_id=campaign_id,
    )
    return jsonify({"status": "created", "id": action_id})


@app.route("/api/engagement/actions", methods=["POST"])
@login_required
def api_create_engagement_action():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    action_type = (data.get("action_type") or "").strip()
    if not platform or not action_type:
        return jsonify({"error": "platform and action_type are required"}), 400
    action_id = db.create_engagement_action(
        user_id=current_user.id,
        platform=platform,
        action_type=action_type,
        target_username=data.get("target_username", ""),
        target_url=data.get("target_url", ""),
        comment_text=data.get("comment_text", ""),
    )
    agent_dispatch.dispatch_async("engagement_action", {
        "summary": f"{action_type} on {platform}",
        "user_id": current_user.id,
        "platform": platform,
        "action_type": action_type,
    })
    return jsonify({"status": "queued", "action_id": action_id})


@app.route("/api/engagement/stats")
@login_required
def api_engagement_stats():
    return jsonify(db.get_engagement_stats(current_user.id))


# ── Health check (required by Render) ────────────────────────────────────────────────────────────────────

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


# ── Background Threads ──────────────────────────────────────────────────────────────────────────────

_bg_threads_started = False
_bg_threads_lock = threading.Lock()


def _scheduler_thread():
    """Check scheduled posts every 60 seconds and publish due ones."""
    while True:
        try:
            due_posts = db.get_due_scheduled_posts()
            for post in due_posts:
                db.update_scheduled_post(post["id"], status="posting")
                agent_dispatch.dispatch_async("scheduled_publish", {
                    "summary": f"Publishing to {post.get('platform', 'unknown')}",
                    "user_id": post.get("user_id"),
                    "job_id": post.get("job_id"),
                    "platform": post.get("platform"),
                })
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
            agent_dispatch.dispatch_async("competitor_refresh", {"summary": "Periodic competitor scan"})
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


# ── Admin Command Center ─────────────────────────────────────────────────────────────────────

def admin_required(f):
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


@app.route("/admin")
@login_required
def admin_page():
    if not getattr(current_user, "is_admin", False):
        return redirect(url_for("dashboard"))
    return render_template("admin.html")


@app.route("/api/admin/overview")
@admin_required
def api_admin_overview():
    return jsonify(db.admin_get_overview())


@app.route("/api/admin/revenue")
@admin_required
def api_admin_revenue():
    return jsonify(db.admin_get_revenue_estimate())


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_users():
    search = request.args.get("search")
    tier = request.args.get("tier")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    users = db.admin_list_users(limit=limit, offset=offset, search=search, tier=tier)
    total = db.admin_get_user_count()
    return jsonify({"users": users, "total": total})


@app.route("/api/admin/users/<int:user_id>", methods=["PATCH"])
@admin_required
def api_admin_update_user(user_id):
    data = request.get_json(silent=True) or {}
    allowed = {"tier", "is_admin", "name", "email"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    db.admin_update_user(user_id, **updates)
    return jsonify({"status": "updated"})


@app.route("/api/admin/jobs")
@admin_required
def api_admin_jobs():
    return jsonify(db.admin_get_job_stats())


@app.route("/api/admin/growth")
@admin_required
def api_admin_growth():
    return jsonify(db.admin_get_growth_metrics())


@app.route("/api/admin/health")
@admin_required
def api_admin_health():
    return jsonify(db.admin_get_system_health())


@app.route("/api/admin/config")
@admin_required
def api_admin_config():
    import config as cfg
    api_keys = {}
    for key in ["ANTHROPIC_API_KEY", "PEXELS_API_KEY", "GOOGLE_API_KEY",
                "HIGGSFIELD_MCP_TOKEN", "STRIPE_SECRET_KEY",
                "YOUTUBE_CLIENT_ID", "TIKTOK_CLIENT_KEY",
                "INSTAGRAM_ACCESS_TOKEN"]:
        val = getattr(cfg, key, "")
        api_keys[key] = "configured" if val else "missing"
    return jsonify({
        "tiers": cfg.TIERS,
        "api_keys": api_keys,
        "app_base_url": cfg.APP_BASE_URL,
    })


# ── Agent Team Operations ─────────────────────────────────────────────────────────────────

@app.route("/api/admin/system-status")
@admin_required
def api_admin_system_status():
    return jsonify(agent_dispatch.get_system_status())


@app.route("/api/admin/agents", methods=["GET"])
@admin_required
def api_admin_agents():
    agents = db.get_agents()
    stats = db.get_agent_stats()
    for a in agents:
        if a.get("config"):
            try:
                a["config"] = json.loads(a["config"])
            except (json.JSONDecodeError, TypeError):
                a["config"] = {}
    return jsonify({"agents": agents, "stats": stats})


@app.route("/api/admin/agents/<agent_id>", methods=["GET"])
@admin_required
def api_admin_agent_detail(agent_id):
    agent = db.get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    if agent.get("config"):
        try:
            agent["config"] = json.loads(agent["config"])
        except (json.JSONDecodeError, TypeError):
            agent["config"] = {}
    logs = db.get_agent_logs(agent_id=agent_id, limit=30)
    return jsonify({"agent": agent, "logs": logs})


@app.route("/api/admin/agents/<agent_id>/status", methods=["PATCH"])
@admin_required
def api_admin_agent_status(agent_id):
    data = request.get_json(force=True)
    new_status = data.get("status")
    if new_status not in ("online", "offline", "standby", "maintenance"):
        return jsonify({"error": "Invalid status"}), 400
    db.update_agent(agent_id, status=new_status)
    db.add_agent_log(agent_id, "status_change", f"Status changed to {new_status}")
    return jsonify({"ok": True})


@app.route("/api/admin/agents/<agent_id>/dispatch", methods=["POST"])
@admin_required
def api_admin_agent_dispatch(agent_id):
    agent = db.get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    data = request.get_json(force=True)
    task = data.get("task", "")
    db.add_agent_log(agent_id, "task_dispatched", f"Manual task: {task[:200]}", {"task": task})
    tasks_done = (agent.get("tasks_completed") or 0) + 1
    db.update_agent(agent_id, tasks_completed=tasks_done)
    return jsonify({"ok": True, "message": f"Task dispatched to {agent['codename']}"})


@app.route("/api/admin/agents/logs", methods=["GET"])
@admin_required
def api_admin_agent_logs():
    limit = min(int(request.args.get("limit", 50)), 200)
    logs = db.get_agent_logs(limit=limit)
    return jsonify({"logs": logs})


# ── Media Library ────────────────────────────────────────────────────────────────────────────

@app.route("/media")
@login_required
def media_library_page():
    return render_template("media.html")


@app.route("/api/media", methods=["GET"])
@login_required
def api_list_media():
    media_type = request.args.get("type")
    category = request.args.get("category")
    search = request.args.get("search")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    items = db.get_media_library(
        current_user.id, media_type=media_type, category=category,
        search=search, limit=limit, offset=offset
    )
    stats = db.get_media_stats(current_user.id)
    return jsonify({"media": items, "stats": stats})


@app.route("/api/media/upload", methods=["POST"])
@login_required
def api_upload_media():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    original_name = file.filename
    ext = Path(original_name).suffix.lower()
    if ext not in db._all_allowed_extensions():
        return jsonify({"error": f"File type {ext} not supported"}), 400

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > db.MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 500 MB)"}), 400

    safe_name = secure_filename(original_name)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / unique_name
    file.save(str(dest))

    category = request.form.get("category", "uncategorized")
    description = request.form.get("description", "")
    tags_raw = request.form.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    result = db.add_media(
        user_id=current_user.id,
        filename=unique_name,
        original_name=original_name,
        file_path=str(dest),
        file_size=file_size,
        mime_type=file.content_type or "",
        category=category,
        tags=tags,
        description=description,
    )
    agent_dispatch.dispatch_async("media_upload", {
        "summary": original_name[:80],
        "user_id": current_user.id,
        "category": category,
    })
    return jsonify({"status": "uploaded", **result}), 201


@app.route("/api/media/upload/bulk", methods=["POST"])
@login_required
def api_upload_media_bulk():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    category = request.form.get("category", "uncategorized")
    results = []
    errors = []

    for file in files:
        if not file.filename:
            continue
        original_name = file.filename
        ext = Path(original_name).suffix.lower()
        if ext not in db._all_allowed_extensions():
            errors.append(f"{original_name}: unsupported type {ext}")
            continue

        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if file_size > db.MAX_FILE_SIZE:
            errors.append(f"{original_name}: too large")
            continue

        safe_name = secure_filename(original_name)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        user_dir = UPLOAD_DIR / str(current_user.id)
        user_dir.mkdir(parents=True, exist_ok=True)
        dest = user_dir / unique_name
        file.save(str(dest))

        result = db.add_media(
            user_id=current_user.id,
            filename=unique_name,
            original_name=original_name,
            file_path=str(dest),
            file_size=file_size,
            mime_type=file.content_type or "",
            category=category,
        )
        results.append(result)

    return jsonify({"uploaded": results, "errors": errors,
                     "total_uploaded": len(results)}), 201


@app.route("/api/media/<media_id>", methods=["GET"])
@login_required
def api_get_media(media_id):
    item = db.get_media(media_id, user_id=current_user.id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@app.route("/api/media/<media_id>", methods=["PUT", "PATCH"])
@login_required
def api_update_media(media_id):
    data = request.get_json(silent=True) or {}
    allowed_fields = {"category", "tags", "description"}
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400
    db.update_media(media_id, current_user.id, **updates)
    return jsonify({"status": "updated"})


@app.route("/api/media/<media_id>", methods=["DELETE"])
@login_required
def api_delete_media(media_id):
    file_path = db.delete_media(media_id, current_user.id)
    if file_path is None:
        return jsonify({"error": "Not found"}), 404
    try:
        Path(file_path).unlink(missing_ok=True)
    except OSError:
        pass
    return jsonify({"status": "deleted"})


@app.route("/api/media/picker")
@login_required
def api_media_picker():
    """Return media items for the in-app picker, grouped by type."""
    media_type = request.args.get("type")
    category = request.args.get("category")
    search = request.args.get("search")
    items = db.get_media_library(
        current_user.id, media_type=media_type, category=category,
        search=search, limit=100
    )
    grouped = {}
    for item in items:
        t = item["media_type"]
        if t not in grouped:
            grouped[t] = []
        grouped[t].append({
            "id": item["id"],
            "name": item["original_name"],
            "category": item["category"],
            "size": item["file_size"],
            "tags": item["tags"],
            "url": f"/api/media/{item['id']}/download",
        })
    return jsonify({"media": grouped, "total": len(items)})


@app.route("/api/media/<media_id>/download")
@login_required
def api_download_media(media_id):
    item = db.get_media(media_id, user_id=current_user.id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return send_file(item["file_path"], download_name=item["original_name"])


# ── Startup ───────────────────────────────────────────────────────────────────────────────────

db.init_db()
db.seed_agents()
start_background_threads()

if __name__ == "__main__":
    print("\n  Social Optimize Machine - Command Center")
    print("  Open → http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
