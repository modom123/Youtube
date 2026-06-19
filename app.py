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
import vobject
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for,
    send_file, Response, stream_with_context, session
)
from werkzeug.utils import secure_filename
import database as db
import config

app = Flask(__name__)
app.secret_key = os.urandom(24)

ALLOWED_EXTENSIONS = {"csv", "vcf", "vcard", "txt"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── SSE job progress stream ───────────────────────────────────────────────────

_job_events: dict[int, list[str]] = {}
_job_lock = threading.Lock()


def push_event(job_id: int, data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with _job_lock:
        if job_id not in _job_events:
            _job_events[job_id] = []
        _job_events[job_id].append(payload)


def _run_job_thread(job_id: int, params: dict):
    """Run the Social Optimize pipeline in a background thread."""
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

        # Monkey-patch logger to emit SSE events
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

        db.update_job(
            job_id,
            status="done",
            progress=100,
            current_step="Complete!",
            title=manifest.get("title"),
            duration=manifest.get("duration", 0),
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
            "title": manifest.get("title"),
            "video_path": manifest.get("files", {}).get("video"),
        })

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        db.update_job(job_id, status="error", error_msg=str(e), current_step="Failed")
        push_event(job_id, {"progress": 0, "step": f"Error: {e}", "status": "error", "traceback": tb})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    stats = db.get_stats()
    recent_jobs = db.get_jobs(limit=5)
    accounts = db.get_accounts()
    return render_template("index.html", stats=stats, recent_jobs=recent_jobs, accounts=accounts)


@app.route("/create")
def create_page():
    accounts = db.get_accounts()
    connected = {a["platform"] for a in accounts if a["is_active"]}
    return render_template("create.html", connected_platforms=connected,
                           voices=config.AVAILABLE_VOICES)


@app.route("/api/create", methods=["POST"])
def api_create():
    data = request.json
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    platforms = data.get("platforms", [])
    skip_research = data.get("skip_research", False)
    job_id = db.create_job(
        topic=topic,
        format=data.get("format", "short"),
        platforms=platforms,
        audience=data.get("audience", "general public"),
        voice=data.get("voice") or config.DEFAULT_VOICE,
        style=data.get("style", "fire"),
        privacy=data.get("privacy", "private"),
        skip_research=skip_research,
    )

    params = {
        "topic": topic,
        "format": data.get("format", "short"),
        "platforms": platforms,
        "audience": data.get("audience", "general public"),
        "voice": data.get("voice") or config.DEFAULT_VOICE,
        "thumbnail_style": data.get("style", "fire"),
        "privacy": data.get("privacy", "private"),
        "custom_instructions": data.get("instructions"),
        "dry_run": data.get("dry_run", False),
        "cleanup": data.get("cleanup", False),
        "skip_research": skip_research,
        "ai_video_provider": data.get("ai_video_provider", "none"),
        "higgsfield_model": data.get("higgsfield_model", "kling3_0"),
    }

    t = threading.Thread(target=_run_job_thread, args=(job_id, params), daemon=True)
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<int:job_id>/stream")
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

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/job/<int:job_id>")
def api_get_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


@app.route("/jobs")
def jobs_page():
    jobs = db.get_jobs(limit=100)
    return render_template("jobs.html", jobs=jobs)


@app.route("/jobs/<int:job_id>")
def job_detail(job_id):
    job = db.get_job(job_id)
    if not job:
        return redirect("/jobs")
    return render_template("job_detail.html", job=job)


@app.route("/api/jobs/<int:job_id>/research")
def get_research(job_id):
    job = db.get_job(job_id)
    if not job or not job.get("research_path"):
        # Try manifest
        if job and job.get("manifest_path"):
            try:
                import json as _json
                with open(job["manifest_path"]) as f:
                    m = _json.load(f)
                rpath = m.get("files", {}).get("research")
                if rpath:
                    with open(rpath) as f:
                        return jsonify(_json.load(f))
            except Exception:
                pass
        return jsonify({"error": "Research not available"}), 404
    try:
        import json as _json
        with open(job["research_path"]) as f:
            return jsonify(_json.load(f))
    except Exception:
        return jsonify({"error": "Could not load research file"}), 404


@app.route("/api/jobs/<int:job_id>/download")
def download_video(job_id):
    job = db.get_job(job_id)
    if not job or not job.get("video_path"):
        return jsonify({"error": "Video not found"}), 404
    path = Path(job["video_path"])
    if not path.exists():
        return jsonify({"error": "File missing"}), 404
    return send_file(str(path), as_attachment=True, download_name=f"som_{job_id}.mp4")


@app.route("/api/jobs/<int:job_id>/thumbnail")
def get_thumbnail(job_id):
    job = db.get_job(job_id)
    if not job or not job.get("thumbnail_path"):
        return "", 404
    path = Path(job["thumbnail_path"])
    if not path.exists():
        return "", 404
    return send_file(str(path), mimetype="image/jpeg")


# ── Social Accounts ───────────────────────────────────────────────────────────

@app.route("/accounts")
def accounts_page():
    accounts = db.get_accounts()
    return render_template("accounts.html", accounts=accounts)


@app.route("/api/accounts", methods=["GET"])
def api_accounts():
    return jsonify(db.get_accounts())


@app.route("/api/accounts/connect", methods=["POST"])
def api_connect_account():
    """Manual account connection (token-based)."""
    data = request.json
    platform = data.get("platform", "").lower()
    username = (data.get("username") or "").strip()
    if not platform or not username:
        return jsonify({"error": "platform and username required"}), 400

    acc_id = db.upsert_account(
        platform=platform,
        username=username,
        display_name=data.get("display_name", username),
        avatar_url=data.get("avatar_url"),
        access_token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        account_id=data.get("account_id"),
        followers=int(data.get("followers", 0)),
    )
    return jsonify({"id": acc_id, "status": "connected"})


@app.route("/api/accounts/<int:acc_id>", methods=["DELETE"])
def api_delete_account(acc_id):
    db.delete_account(acc_id)
    return jsonify({"status": "deleted"})


# ── OAuth Placeholders (wire to real OAuth flows with your credentials) ──────

@app.route("/oauth/youtube/start")
def oauth_youtube_start():
    """Redirect user to Google OAuth for YouTube."""
    if not config.YOUTUBE_CLIENT_ID:
        return jsonify({"error": "YouTube credentials not configured in .env"}), 400
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {"web": {
            "client_id": config.YOUTUBE_CLIENT_ID,
            "client_secret": config.YOUTUBE_CLIENT_SECRET,
            "redirect_uris": ["http://localhost:5000/oauth/youtube/callback"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }},
        scopes=config.YOUTUBE_SCOPES + ["https://www.googleapis.com/auth/youtube.readonly"],
        redirect_uri="http://localhost:5000/oauth/youtube/callback",
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
            "redirect_uris": ["http://localhost:5000/oauth/youtube/callback"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }},
        scopes=config.YOUTUBE_SCOPES + ["https://www.googleapis.com/auth/youtube.readonly"],
        redirect_uri="http://localhost:5000/oauth/youtube/callback",
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
    redirect_uri = "http://localhost:5000/oauth/tiktok/callback"
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
    redirect_uri = "http://localhost:5000/oauth/tiktok/callback"
    token_resp = req.post("https://open.tiktokapis.com/v2/oauth/token/", data={
        "client_key": config.TIKTOK_CLIENT_KEY,
        "client_secret": config.TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
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
        platform="tiktok",
        username=user.get("display_name", "TikTok User"),
        display_name=user.get("display_name"),
        avatar_url=user.get("avatar_url"),
        access_token=access_token,
        account_id=open_id,
        followers=user.get("follower_count", 0),
    )
    return redirect("/accounts?connected=tiktok")


@app.route("/oauth/instagram/start")
def oauth_instagram_start():
    if not config.INSTAGRAM_ACCESS_TOKEN:
        return jsonify({"error": "Instagram credentials not configured in .env"}), 400
    # Instagram uses long-lived tokens — direct token entry via UI
    return redirect("/accounts?modal=instagram")


# ── Contacts ─────────────────────────────────────────────────────────────────

@app.route("/contacts")
def contacts_page():
    platform_filter = request.args.get("platform")
    search = request.args.get("q")
    contacts = db.get_contacts(platform=platform_filter, search=search, limit=200)
    total = db.count_contacts()
    platforms = ["youtube", "tiktok", "instagram", "phone", "other"]
    return render_template("contacts.html", contacts=contacts, total=total,
                           platforms=platforms, active_platform=platform_filter, search=search)


@app.route("/api/contacts", methods=["GET"])
def api_contacts():
    contacts = db.get_contacts(
        platform=request.args.get("platform"),
        search=request.args.get("q"),
        limit=int(request.args.get("limit", 100)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify(contacts)


@app.route("/api/contacts/import/csv", methods=["POST"])
def import_contacts_csv():
    """Import contacts from a CSV file. Expected columns: name, handle, email, phone, platform."""
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
        # Normalize common column name variants
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
            "platform": platform,
            "avatar_url": "",
            "followers": 0,
            "tags": "[]",
        })

    count = db.insert_contacts_bulk(contacts)
    return jsonify({"imported": count})


@app.route("/api/contacts/import/vcf", methods=["POST"])
def import_contacts_vcf():
    """Import contacts from a vCard (.vcf) file (phone exports)."""
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
                contacts.append({
                    "name": name,
                    "handle": "",
                    "email": email,
                    "phone": phone,
                    "platform": "phone",
                    "avatar_url": "",
                    "followers": 0,
                    "tags": "[]",
                })
    except Exception as e:
        return jsonify({"error": f"Failed to parse vCard: {e}"}), 400

    count = db.insert_contacts_bulk(contacts)
    return jsonify({"imported": count})


@app.route("/api/contacts/import/manual", methods=["POST"])
def import_contacts_manual():
    data = request.json
    contacts = data.get("contacts", [])
    cleaned = []
    for c in contacts:
        if not c.get("name"):
            continue
        cleaned.append({
            "name": c.get("name", "").strip(),
            "handle": c.get("handle", "").strip(),
            "email": c.get("email", "").strip(),
            "phone": c.get("phone", "").strip(),
            "platform": c.get("platform", "other"),
            "avatar_url": c.get("avatar_url", ""),
            "followers": int(c.get("followers", 0)),
            "tags": json.dumps(c.get("tags", [])),
        })
    count = db.insert_contacts_bulk(cleaned)
    return jsonify({"imported": count})


@app.route("/api/contacts/clear", methods=["POST"])
def clear_contacts():
    platform = request.json.get("platform") if request.json else None
    db.delete_contacts(platform=platform)
    return jsonify({"status": "cleared"})


# ── Settings / API keys ───────────────────────────────────────────────────────

@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/api/research/preview", methods=["POST"])
def api_research_preview():
    """Quick research preview — called live as user types a topic."""
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
        "higgsville":  bool(config.HIGGSFIELD_API_KEY),
        "youtube":     bool(config.YOUTUBE_CLIENT_ID),
        "tiktok":      bool(config.TIKTOK_CLIENT_KEY),
        "instagram":   bool(config.INSTAGRAM_ACCESS_TOKEN),
    })


# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    print("\n  Social Optimize Machine - Command Center")
    print("  Open → http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
