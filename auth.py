"""Auth Blueprint — register, login, logout, password reset."""
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import database as db
import config
import mobile_auth

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


PAID_PLANS = {"starter", "creator", "pro", "agency"}


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    is_json = request.is_json

    if current_user.is_authenticated:
        if is_json:
            return jsonify({"token": mobile_auth.issue_token(current_user.id),
                            "user": user_to_dict(current_user)})
        plan = request.args.get("plan", "").strip()
        if plan in PAID_PLANS:
            return redirect(url_for("billing.checkout", tier_name=plan))
        return redirect(url_for("dashboard"))

    plan = request.args.get("plan", "").strip()

    if request.method == "POST":
        if is_json:
            data = request.get_json(silent=True) or {}
            name  = (data.get("name") or "").strip()
            email = (data.get("email") or "").strip().lower()
            pw    = data.get("password", "")
            pw2   = pw  # mobile app has no separate confirm-password field
            plan  = (data.get("plan") or plan).strip()
        else:
            name  = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            pw    = request.form.get("password", "")
            pw2   = request.form.get("password2", "")
            plan  = request.form.get("plan", plan).strip()

        def _fail(msg, status=400):
            if is_json:
                return jsonify({"error": msg}), status
            flash(msg, "error")
            return render_template("auth/register.html", plan=plan)

        if not email or not pw:
            return _fail("Email and password are required.")

        if pw != pw2:
            return _fail("Passwords do not match.")

        if len(pw) < 8:
            return _fail("Password must be at least 8 characters.")

        if db.get_user_by_email(email):
            return _fail("An account with that email already exists.", 409)

        pw_hash = generate_password_hash(pw)
        user_id = db.create_user(email=email, password_hash=pw_hash, name=name or email.split("@")[0])
        ref_code = request.cookies.get("ref", "")
        if ref_code:
            db.update_user(user_id, referred_by=ref_code)
        user_data = db.get_user_by_id(user_id)
        user = _UserObj(user_data)
        login_user(user, remember=True)

        if is_json:
            return jsonify({"token": mobile_auth.issue_token(user.id), "user": user_to_dict(user)})

        if plan in PAID_PLANS:
            return redirect(url_for("billing.checkout", tier_name=plan))
        return redirect(url_for("dashboard"))

    return render_template("auth/register.html", plan=plan)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    is_json = request.is_json

    if current_user.is_authenticated:
        if is_json:
            return jsonify({"token": mobile_auth.issue_token(current_user.id),
                            "user": user_to_dict(current_user)})
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        if is_json:
            data = request.get_json(silent=True) or {}
            email = (data.get("email") or "").strip().lower()
            pw    = data.get("password", "")
            remember = True
        else:
            email = request.form.get("email", "").strip().lower()
            pw    = request.form.get("password", "")
            remember = bool(request.form.get("remember"))

        user_data = db.get_user_by_email(email)
        if not user_data or not check_password_hash(user_data["password_hash"], pw):
            if is_json:
                return jsonify({"error": "Invalid email or password"}), 401
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html")

        user = _UserObj(user_data)
        login_user(user, remember=remember)

        if is_json:
            return jsonify({"token": mobile_auth.issue_token(user.id), "user": user_to_dict(user)})

        next_page = request.args.get("next") or url_for("dashboard")
        return redirect(next_page)

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("landing"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = db.get_user_by_email(email)
        # Always show success message to prevent email enumeration
        if user:
            token = secrets.token_urlsafe(32)
            expires = (datetime.utcnow() + timedelta(hours=2)).isoformat()
            db.create_password_reset_token(user["id"], token, expires)
            _send_reset_email(email, token)
        flash("If that email has an account, a reset link has been sent.", "info")
        return redirect(url_for("auth.forgot_password"))
    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    record = db.get_password_reset_token(token)
    if not record:
        flash("This reset link is invalid or has already been used.", "error")
        return redirect(url_for("auth.forgot_password"))
    if datetime.utcnow().isoformat() > record["expires_at"]:
        flash("This reset link has expired. Please request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if len(pw) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth/reset_password.html", token=token)
        if pw != pw2:
            flash("Passwords do not match.", "error")
            return render_template("auth/reset_password.html", token=token)
        db.update_user(record["user_id"], password_hash=generate_password_hash(pw))
        db.consume_password_reset_token(token)
        flash("Password updated. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", token=token)


def _send_reset_email(email: str, token: str):
    host = config.SMTP_HOST
    if not host or not config.SMTP_USER:
        return
    reset_url = f"{config.APP_BASE_URL}/auth/reset-password/{token}"
    html = f"""<html><body style="font-family:sans-serif;background:#111;color:#eee;padding:32px;">
    <div style="max-width:520px;margin:0 auto;">
      <h2 style="color:#d4a017;">Reset Your Password</h2>
      <p style="color:#ccc;">Click the button below to set a new password. This link expires in 2 hours.</p>
      <a href="{reset_url}" style="display:inline-block;margin-top:16px;padding:12px 28px;background:#d4a017;color:#000;font-weight:700;text-decoration:none;border-radius:10px;">
        Reset Password
      </a>
      <p style="color:#666;font-size:12px;margin-top:24px;">If you didn't request this, ignore this email.</p>
    </div></body></html>"""
    text = f"Reset your password:\n{reset_url}\n\nExpires in 2 hours."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Reset your Social Optimize password"
        msg["From"] = config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(host, config.SMTP_PORT) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(config.SMTP_USER, config.SMTP_PASS)
            srv.sendmail(config.SMTP_FROM, email, msg.as_string())
    except Exception:
        pass


# ── Flask-Login User class ────────────────────────────────────────────────────

class _UserObj:
    """Thin wrapper so database dicts work with Flask-Login."""
    def __init__(self, data: dict):
        self._d = data

    # Flask-Login interface
    @property
    def is_authenticated(self): return True
    @property
    def is_active(self): return True
    @property
    def is_anonymous(self): return False
    def get_id(self): return str(self._d["id"])

    # Convenience
    @property
    def id(self): return self._d["id"]
    @property
    def email(self): return self._d["email"]
    @property
    def name(self): return self._d.get("name") or self._d["email"].split("@")[0]
    @property
    def subscription_tier(self): return self._d.get("subscription_tier") or "free"
    @property
    def subscription_status(self): return self._d.get("subscription_status") or "active"
    @property
    def videos_used(self): return self._d.get("videos_used") or 0
    @property
    def videos_used_this_month(self): return self._d.get("videos_used") or 0
    @property
    def credits_used(self): return self._d.get("credits_used") or 0
    @property
    def stripe_customer_id(self): return self._d.get("stripe_customer_id")
    @property
    def stripe_subscription_id(self): return self._d.get("stripe_subscription_id")
    @property
    def is_admin(self): return bool(self._d.get("is_admin"))
    @property
    def assistant_enabled(self): return self._d.get("assistant_enabled") != 0
    @property
    def default_voice(self): return self._d.get("default_voice") or "en-US-Journey-D"

    def refresh(self):
        self._d = db.get_user_by_id(self._d["id"])
        return self


def make_user(user_data: dict) -> _UserObj:
    return _UserObj(user_data)


def user_to_dict(user: "_UserObj") -> dict:
    """JSON-serializable view of a user, shared by the mobile JSON auth
    endpoints and /api/profile so the shape stays consistent everywhere."""
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "subscription_tier": user.subscription_tier,
        "videos_used": user.videos_used,
        "credits_used": user.credits_used,
    }


# ── Bootstrap: first-admin setup (only works when 0 users exist) ─────────────

@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    """Create the first admin account when the database is empty.
    Disabled once any user exists."""
    user_count = db.count_users()
    if user_count > 0:
        flash("Setup is disabled — accounts already exist.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw    = request.form.get("password", "")
        pw2   = request.form.get("password2", "")
        name  = request.form.get("name", "").strip()

        if not email or not pw:
            flash("Email and password are required.", "error")
            return render_template("auth/setup.html")
        if pw != pw2:
            flash("Passwords do not match.", "error")
            return render_template("auth/setup.html")
        if len(pw) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth/setup.html")

        pw_hash = generate_password_hash(pw)
        user_id = db.create_user(email=email, password_hash=pw_hash, name=name or email.split("@")[0])
        db.update_user(user_id, is_admin=1, subscription_tier="agency", subscription_status="active")
        user_data = db.get_user_by_id(user_id)
        user = _UserObj(user_data)
        login_user(user, remember=True)
        flash("Admin account created. Welcome!", "success")
        return redirect(url_for("dashboard"))

    return render_template("auth/setup.html")


# ── Invite links — admin generates, tester clicks to auto-register ────────────

_invite_store: dict[str, dict] = {}  # token → {tier, expires}


@auth_bp.route("/invite/<token>", methods=["GET"])
def accept_invite(token):
    """Pre-approved invite link. Redirects to register with tier pre-set."""
    invite = _invite_store.get(token)
    if not invite or datetime.utcnow().isoformat() > invite["expires"]:
        flash("This invite link has expired or is invalid.", "error")
        return redirect(url_for("auth.register"))
    tier = invite.get("tier", "free")
    return redirect(url_for("auth.register") + f"?plan={tier}")
