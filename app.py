import os
import subprocess
import threading
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from getpass import getpass

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect, FlaskForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import EmailField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length

load_dotenv()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
SECRET_KEY = os.getenv("SECRET_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///apps.db")
TRUSTED_HOSTS = [h.strip() for h in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://").strip()

if IS_PRODUCTION:
    missing = []
    if len(SECRET_KEY) < 32 or SECRET_KEY == "local-development-only-change-me":
        missing.append("SECRET_KEY (minimaal 32 willekeurige tekens)")
    if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        missing.append("DATABASE_URL (PostgreSQL)")
    if not os.getenv("TRUSTED_HOSTS", "").strip():
        missing.append("TRUSTED_HOSTS (domeinnamen)")
    if not ADMIN_EMAIL or ADMIN_EMAIL == "admin@example.com":
        missing.append("ADMIN_EMAIL (beheerderse-mailadres)")
    if not RATELIMIT_STORAGE_URI.startswith(("redis://", "rediss://")):
        missing.append("RATELIMIT_STORAGE_URI (Redis)")
    if not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY:
        missing.append("TURNSTILE_SITE_KEY en TURNSTILE_SECRET_KEY")
    if missing:
        raise RuntimeError("Onvolledige productieconfiguratie: " + ", ".join(missing))

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)
app.config.update(
    APP_ENV=APP_ENV,
    SECRET_KEY=SECRET_KEY or "local-development-only-change-me",
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SECURE=IS_PRODUCTION,
    MAX_CONTENT_LENGTH=1024 * 1024,
    TRUSTED_HOSTS=TRUSTED_HOSTS,
    WTF_CSRF_TIME_LIMIT=3600,
)
proxy_hops = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
if proxy_hops > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops, x_host=proxy_hops)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, storage_uri=RATELIMIT_STORAGE_URI,
                  default_limits=["200 per hour"], headers_enabled=False)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Log eerst in om deze pagina te bekijken."

# Three Way runs only from the bundled folder and is disabled on hosted production
# until an isolated, persistent worker is configured. This avoids running portfolio
# scripts in a short-lived web dyno or exposing personal data to a shared service.
THREE_WAY_PATH = os.path.abspath(os.getenv("THREE_WAY_PATH", os.path.join(os.path.dirname(__file__), "three-way")))
THREE_WAY_TIMEOUT = min(max(int(os.getenv("THREE_WAY_TIMEOUT", "180")), 10), 600)
THREE_WAY_LOCK = threading.Lock()
THREE_WAY_ACTIONS = {"main": "main.py", "backcasting": "backcasting.py", "walkforward": "walkforward.py"}


def run_three_way(action: str, news: str = "0", intuition: str = "0") -> tuple[int, str]:
    if action not in THREE_WAY_ACTIONS:
        raise ValueError("Onbekende Three Way-taak.")
    if IS_PRODUCTION:
        raise RuntimeError("Three Way-uitvoering is op Render uitgeschakeld totdat een geïsoleerde worker en persistente opslag zijn ingericht.")
    script = os.path.realpath(os.path.join(THREE_WAY_PATH, THREE_WAY_ACTIONS[action]))
    root = os.path.realpath(THREE_WAY_PATH)
    if os.path.commonpath([script, root]) != root or not os.path.isfile(script):
        raise RuntimeError("Three Way-bestanden niet gevonden. Controleer de map three-way.")
    holdings_file = os.path.join(root, "data", "holdings.json")
    if not os.path.isfile(holdings_file):
        raise RuntimeError("Portefeuille ontbreekt. Maak three-way/data/holdings.json aan op basis van holdings.json; dit bestand wordt niet in Git opgeslagen.")
    import json
    try:
        with open(holdings_file, encoding="utf-8") as handle:
            holdings_data = json.load(handle)
        if not holdings_data.get("holdings"):
            raise RuntimeError("Portefeuille is leeg. Vul three-way/data/holdings.json met je eigen aandelen voordat je een analyse start.")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError("Portefeuillebestand is ongeldig. Controleer three-way/data/holdings.json.") from exc
    if not THREE_WAY_LOCK.acquire(blocking=False):
        raise RuntimeError("Er draait al een Three Way-taak. Wacht tot deze klaar is.")
    try:
        input_text = f"{news}\n{intuition}\n" if action == "main" else ""
        completed = subprocess.run(
            [os.getenv("THREE_WAY_PYTHON", os.sys.executable), script],
            cwd=root,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=THREE_WAY_TIMEOUT,
            check=False,
            shell=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        output = completed.stdout[-24000:]
        return completed.returncode, output or "De taak gaf geen uitvoer."
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return 124, str(output)[-20000:] + "\n\nTaak afgebroken: time-out bereikt."
    finally:
        THREE_WAY_LOCK.release()


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
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin or current_user.email.lower() != ADMIN_EMAIL or not current_user.approved:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def verify_turnstile(token):
    if not TURNSTILE_SECRET_KEY or not TURNSTILE_SITE_KEY or not token:
        return False
    payload = urllib.parse.urlencode({
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
        "remoteip": request.remote_addr or "",
    }).encode()
    req = urllib.request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        import json
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read(8192).decode("utf-8"))
        return result.get("success") is True
    except Exception:
        app.logger.warning("Turnstile-verificatie niet beschikbaar.")
        return False


def send_admin_notification(email):
    host = os.getenv("MAIL_SERVER", "").strip()
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "")
    if not host or not username or not password:
        app.logger.warning("SMTP niet geconfigureerd; aanvraag staat klaar in Gebruikersbeheer.")
        return False
    message = EmailMessage()
    message["Subject"] = "Nieuwe toegangaanvraag voor kay.apps"
    message["From"] = os.getenv("MAIL_FROM", username)
    message["To"] = ADMIN_EMAIL
    message.set_content(
        "Er is een nieuwe toegangaanvraag voor kay.apps.\n\n"
        f"E-mailadres aanvrager: {email}\n\n"
        "Log in op het portaal en beoordeel de aanvraag via Gebruikersbeheer. "
        "Er is geen wachtwoord in deze melding opgenomen."
    )
    try:
        with smtplib.SMTP(host, int(os.getenv("MAIL_PORT", "587")), timeout=10) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)
        return True
    except Exception:
        app.logger.exception("E-mailmelding voor toegangaanvraag kon niet worden verzonden.")
        return False


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com https://playcanv.as; connect-src 'self' https://challenges.cloudflare.com",
    )
    if IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


@app.route("/")
def index():
    return redirect(url_for("dashboard" if current_user.is_authenticated else "login"))


@app.route("/healthz")
@limiter.exempt
def healthz():
    return {"status": "ok"}, 200


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
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
                login_user(user, remember=False, fresh=True)
                return redirect(url_for("dashboard"))
        else:
            flash("Inloggen mislukt. Controleer je gegevens.", "error")
    return render_template("login.html", form=form)


@app.route("/request-access", methods=["GET", "POST"])
@limiter.limit("3 per hour; 8 per day", methods=["POST"])
def request_access():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = SignupForm()
    if IS_PRODUCTION and (not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY):
        abort(503, description="Toegang aanvragen is tijdelijk niet beschikbaar.")
    if form.validate_on_submit():
        if request.form.get("website", "").strip():
            abort(400)
        if TURNSTILE_SITE_KEY and not verify_turnstile(request.form.get("cf-turnstile-response", "")):
            flash("Controle mislukt. Probeer het opnieuw.", "error")
            return render_template("request_access.html", form=form, turnstile_site_key=TURNSTILE_SITE_KEY), 400
        email = form.email.data.strip().lower()
        existing = db.session.scalar(select(User).where(User.email == email))
        if existing:
            flash("Als deze aanvraag verwerkt kan worden, ontvang je verdere informatie.", "success")
            return redirect(url_for("login"))
        user = User(email=email, password_hash=generate_password_hash(form.password.data),
                    approved=False, is_admin=False)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        else:
            send_admin_notification(email)
        flash("Aanvraag ontvangen. Je krijgt pas toegang na goedkeuring door de beheerder.", "success")
        return redirect(url_for("login"))
    return render_template("request_access.html", form=form, turnstile_site_key=TURNSTILE_SITE_KEY)


@app.route("/dashboard")
@login_required
def dashboard():
    if not current_user.approved:
        logout_user()
        flash("Je account heeft nog geen toegang.", "error")
        return redirect(url_for("login"))
    apps = [{"name": "Three Way", "description": "Beleggingsanalyse en portefeuille-inzichten.",
             "status": "Koppeling volgt", "icon": "↗", "url": None}]
    return render_template("dashboard.html", apps=apps)


@app.route("/apps/three-way", methods=["GET", "POST"])
@login_required
@limiter.limit("3 per hour", methods=["POST"])
def three_way():
    if not current_user.approved:
        abort(403)
    output = None
    exit_code = None
    selected_action = "backcasting"
    news = "0"
    intuition = "0"
    if request.method == "POST":
        selected_action = request.form.get("action", "")
        news = request.form.get("news", "0").strip().replace(",", ".")
        intuition = request.form.get("intuition", "0").strip().replace(",", ".")
        if selected_action not in THREE_WAY_ACTIONS:
            abort(400)
        if selected_action == "main":
            try:
                if not -5 <= float(news) <= 5 or not -5 <= float(intuition) <= 5:
                    raise ValueError
            except ValueError:
                flash("Nieuws en intuïtie moeten tussen -5 en +5 liggen.", "error")
                return render_template("three_way.html", output=None, exit_code=None, selected_action=selected_action, news=news, intuition=intuition)
            if request.form.get("confirm_main") != "yes":
                flash("Bevestig eerst dat main.py een check opslaat in de Three Way-data.", "error")
                return render_template("three_way.html", output=None, exit_code=None, selected_action=selected_action, news=news, intuition=intuition)
        try:
            exit_code, output = run_three_way(selected_action, news, intuition)
        except (RuntimeError, ValueError) as exc:
            output = str(exc)
            exit_code = 1
        app.logger.info("Three Way-taak %s eindigde met code %s", selected_action, exit_code)
    return render_template("three_way.html", output=output, exit_code=exit_code, selected_action=selected_action, news=news, intuition=intuition)


RULE_FIELDS = {
    "lookback_days": (1, 20, int), "up_pct": (0.5, 200, float), "down_pct": (0.5, 100, float),
    "stop_pct": (0.5, 100, float), "floor_pct": (0.5, 100, float), "regime_pct": (5, 300, float),
    "turn_pct": (0.5, 50, float), "review_days": (1, 20, int),
}


def read_number(raw, low, high, kind):
    value = kind(str(raw).replace(",", "."))
    if not low <= value <= high:
        raise ValueError("buiten bereik")
    return value


def read_score(raw):
    """A score from -5 to +5, or None when the factor is switched off."""
    if raw in (None, "", "off"):
        return None
    return read_number(raw, -5, 5, float)


def scenario_from_args(args, defaults):
    """The scenario of the request. Missing fields keep the default setting."""
    from functioning.dashboard import Scenario
    from functioning.rule import Rule
    values = dict(vars(defaults.rule))
    for field, (low, high, kind) in RULE_FIELDS.items():
        if args.get(field):
            values[field] = read_number(args[field], low, high, kind)
    news = read_score(args["news"]) if "news" in args else defaults.news
    intuition = read_score(args["intuition"]) if "intuition" in args else defaults.intuition
    return Scenario(Rule(**values), news, intuition)


def three_way_import():
    """Make the bundled Three Way code importable for the dashboard."""
    import sys
    if THREE_WAY_PATH not in sys.path:
        sys.path.insert(0, THREE_WAY_PATH)


@app.route("/apps/three-way/dashboard")
@login_required
def three_way_dashboard():
    if not current_user.approved:
        abort(403)
    defaults = None
    if not IS_PRODUCTION:
        three_way_import()
        from functioning.dashboard import default_scenario
        scenario = default_scenario()
        defaults = {**vars(scenario.rule), "news": scenario.news, "intuition": scenario.intuition}
    return render_template("three_way_dashboard.html", defaults=defaults, disabled=IS_PRODUCTION)


@app.route("/apps/three-way/dashboard/data")
@login_required
@limiter.limit("120 per hour")
def three_way_dashboard_data():
    if not current_user.approved:
        abort(403)
    if IS_PRODUCTION:
        return {"error": "Het dashboard is op Render uitgeschakeld totdat persistente opslag is ingericht."}, 503
    three_way_import()
    from functioning.dashboard import dashboard_data, default_scenario
    try:
        scenario = scenario_from_args(request.args, default_scenario())
        window = int(read_number(request.args.get("days", "180"), 30, 1825, float))
    except ValueError:
        return {"error": "Ongeldige instelling."}, 400
    with THREE_WAY_LOCK:
        return dashboard_data(scenario, window)


@app.route("/apps/thinkwave")
@login_required
def thinkwave():
    if not current_user.approved:
        abort(403)
    return render_template("thinkwave.html")


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
        abort(403)
    user.approved = True
    db.session.commit()
    flash(f"Toegang goedgekeurd voor {user.email}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/revoke", methods=["POST"])
@admin_required
def revoke_user(user_id):
    user = db.session.get_or_404(User, user_id)
    if user.email.lower() == ADMIN_EMAIL:
        abort(403)
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


@app.cli.command("create-admin")
def create_admin():
    email = ADMIN_EMAIL
    password = getpass(f"Nieuw wachtwoord voor beheerder {email} (minimaal 12 tekens): ")
    confirmation = getpass("Herhaal wachtwoord: ")
    if len(password) < 12 or password != confirmation:
        print("Wachtwoorden komen niet overeen of zijn korter dan 12 tekens.")
        return
    with app.app_context():
        db.create_all()
        user = db.session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
        user.password_hash = generate_password_hash(password)
        user.approved = True
        user.is_admin = True
        db.session.commit()
        print(f"Beheerdersaccount ingesteld voor {email}.")


def initialise_database():
    with app.app_context():
        db.create_all()


if __name__ == "__main__":
    initialise_database()
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
