"""Auth Blueprint — register, login, logout."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import database as db

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw    = request.form.get("password", "")
        pw2   = request.form.get("password2", "")

        if not email or not pw:
            flash("Email and password are required.", "error")
            return render_template("auth/register.html")

        if pw != pw2:
            flash("Passwords do not match.", "error")
            return render_template("auth/register.html")

        if len(pw) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth/register.html")

        if db.get_user_by_email(email):
            flash("An account with that email already exists.", "error")
            return render_template("auth/register.html")

        pw_hash = generate_password_hash(pw)
        user_id = db.create_user(email=email, password_hash=pw_hash, name=name or email.split("@")[0])
        user_data = db.get_user_by_id(user_id)
        user = _UserObj(user_data)
        login_user(user, remember=True)
        return redirect(url_for("dashboard"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw    = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user_data = db.get_user_by_email(email)
        if not user_data or not check_password_hash(user_data["password_hash"], pw):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html")

        user = _UserObj(user_data)
        login_user(user, remember=remember)
        next_page = request.args.get("next") or url_for("dashboard")
        return redirect(next_page)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))


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
    def credits_used(self): return self._d.get("credits_used") or 0
    @property
    def stripe_customer_id(self): return self._d.get("stripe_customer_id")
    @property
    def stripe_subscription_id(self): return self._d.get("stripe_subscription_id")
    @property
    def is_admin(self): return bool(self._d.get("is_admin"))

    def refresh(self):
        self._d = db.get_user_by_id(self._d["id"])
        return self


def make_user(user_data: dict) -> _UserObj:
    return _UserObj(user_data)
