import os
from datetime import datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import EmailField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length

load_dotenv()

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "local-development-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///apps.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_DEBUG", "0") != "1"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Log eerst in om deze pagina te bekijken."
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "kaysmits@icloud.com").strip().lower()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class LoginForm(FlaskForm):
    email = EmailField("E-mailadres", validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField("Wachtwoord", validators=[DataRequired(), Length(min=12, max=128)])
    submit = SubmitField("Inloggen")


class SignupForm(FlaskForm):
    email = EmailField("E-mailadres", validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField("Kies een wachtwoord (minimaal 12 tekens)", validators=[DataRequired(), Length(min=12, max=128)])
    submit = SubmitField("Toegang aanvragen")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin or current_user.email.lower() != ADMIN_EMAIL:
            flash("Deze pagina is alleen beschikbaar voor de beheerder.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        if user and check_password_hash(user.password_hash, form.password.data):
            if not user.approved:
                flash("Je account is nog niet goedgekeurd.", "error")
            else:
                login_user(user)
                return redirect(url_for("dashboard"))
        else:
            flash("Inloggen mislukt. Controleer je gegevens.", "error")
    return render_template("login.html", form=form)


@app.route("/request-access", methods=["GET", "POST"])
def request_access():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing = db.session.scalar(select(User).where(User.email == email))
        if existing:
            flash("Deze aanvraag kan niet worden verwerkt. Neem contact op met de beheerder.", "error")
        else:
            user = User(
                email=email,
                password_hash=generate_password_hash(form.password.data),
                approved=False,
                is_admin=False,
            )
            db.session.add(user)
            try:
                db.session.commit()
                flash("Aanvraag ontvangen. Je krijgt pas toegang na goedkeuring door de beheerder.", "success")
                return redirect(url_for("login"))
            except IntegrityError:
                db.session.rollback()
                flash("Deze aanvraag kan niet worden verwerkt.", "error")
    return render_template("request_access.html", form=form)


@app.route("/dashboard")
@login_required
def dashboard():
    if not current_user.approved:
        logout_user()
        flash("Je account heeft nog geen toegang.", "error")
        return redirect(url_for("login"))
    apps = [
        {
            "name": "Three Way",
            "description": "Beleggingsanalyse en portefeuille-inzichten.",
            "status": "Koppeling volgt",
            "icon": "↗",
            "url": None,
        }
    ]
    return render_template("dashboard.html", apps=apps)


@app.route("/admin/users")
@admin_required
def admin_users():
    users = db.session.scalars(select(User).order_by(User.created_at.desc())).all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/approve", methods=["POST"])
@admin_required
def approve_user(user_id):
    user = db.session.get_or_404(User, user_id)
    if user.email.lower() == ADMIN_EMAIL:
        flash("Het beheerdersaccount wordt niet via deze pagina aangepast.", "error")
    else:
        user.approved = True
        db.session.commit()
        flash(f"Toegang goedgekeurd voor {user.email}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/revoke", methods=["POST"])
@admin_required
def revoke_user(user_id):
    user = db.session.get_or_404(User, user_id)
    if user.email.lower() == ADMIN_EMAIL:
        flash("Beheerdersrechten kunnen hier niet worden ingetrokken.", "error")
    else:
        user.approved = False
        db.session.commit()
        flash(f"Toegang ingetrokken voor {user.email}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Je bent uitgelogd.", "success")
    return redirect(url_for("login"))


def initialise_database():
    with app.app_context():
        db.create_all()
        # Intentionally do not auto-create an admin from a public signup form.
        # Bootstrap the admin account manually using the documented CLI step.


if __name__ == "__main__":
    initialise_database()
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
