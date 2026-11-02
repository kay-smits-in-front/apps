import json
import os
import re
import threading
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
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
THREE_WAY_LOCK = threading.Lock()
AI_LAB_PATH = os.path.abspath(os.getenv("AI_LAB_PATH", os.path.join(os.path.dirname(__file__), "ai-lab")))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Position(db.Model):
    """A stock one user holds, with the group (rule) it follows."""
    __table_args__ = (db.UniqueConstraint("user_id", "ticker", name="one_position_per_ticker"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    ticker = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    cost_eur = db.Column(db.Float, nullable=False, default=0.0)
    group = db.Column(db.String(20), nullable=True)


class GroupSetting(db.Model):
    """The settings (JSON) one user chose for one group."""
    __table_args__ = (db.UniqueConstraint("user_id", "group", name="one_setting_per_group"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    group = db.Column(db.String(20), nullable=False)
    data = db.Column(db.Text, nullable=False)


class Seeded(db.Model):
    """Marks users whose holdings were already taken over from data/holdings.json."""
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)


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
    apps = [
        {"name": "Three Way", "description": "Beleggingsanalyse en portefeuille-inzichten.",
         "status": "Lokaal", "icon": "↗", "url": url_for("three_way_advice")},
        {"name": "SHIELD", "description": "Basisdashboard voor de DJI Tello: verkenning, mapping en AI-interactie.",
         "status": "Opzet", "icon": "⌁", "url": url_for("shield_dashboard")},
        {"name": "AI-LAB", "description": "Modellen vanaf nul bouwen en streng toetsen. Three Way is het eerste onderwerp.",
         "status": "Lokaal", "icon": "✦", "url": url_for("ai_lab")},
        {"name": "Thinkwave", "description": "Open de Thinkwave-ervaring vanuit je persoonlijke app-portaal.",
         "status": "PlayCanvas", "icon": "✳", "url": url_for("thinkwave")},
    ]
    return render_template("dashboard.html", apps=apps)


@app.route("/apps/shield")
@login_required
def shield_dashboard():
    approved_user()
    return render_template("shield_dashboard.html")


@app.route("/apps/shield/tests")
@login_required
def shield_tests():
    approved_user()
    return render_template("shield_tests.html")


@app.route("/apps/three-way")
@login_required
def three_way():
    return redirect(url_for("three_way_dashboard"))


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


def scenario_from_args(args, defaults, saved_plan=None):
    """The scenario of the request. Missing fields keep the default setting."""
    from functioning.dashboard import Scenario
    from functioning.rule import Rule
    values = dict(vars(defaults.rule))
    for field, (low, high, kind) in RULE_FIELDS.items():
        if args.get(field):
            values[field] = read_number(args[field], low, high, kind)
    news = read_score(args["news"]) if "news" in args else defaults.news
    intuition = read_score(args["intuition"]) if "intuition" in args else defaults.intuition
    return Scenario(Rule(**values), news, intuition, plan_from_args(args) or saved_plan)


def plan_from_args(args):
    """The plan per group, when the request asks for it (plan=<json>). Otherwise None."""
    import json
    from functioning.groups import plan_from_json
    raw = args.get("plan")
    if not raw:
        return None
    if len(raw) > 4000:
        raise ValueError("plan te groot")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("plan ongeldig")
    return plan_from_json(parsed)


def three_way_import():
    """Make the bundled Three Way code importable for the dashboard."""
    import sys
    if THREE_WAY_PATH not in sys.path:
        sys.path.insert(0, THREE_WAY_PATH)


MAX_POSITIONS = 60
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,14}$")


class UserHoldings:
    """The holdings of one user, in the shape the Three Way code expects."""

    def __init__(self, quantities):
        self._quantities = quantities

    def quantities(self):
        return dict(self._quantities)


def approved_user():
    if not current_user.approved:
        abort(403)
    return current_user


def import_holdings_file(user):
    """First visit of the admin: take over data/holdings.json, with the starting groups."""
    if not user.is_admin or db.session.get(Seeded, user.id):
        return
    db.session.add(Seeded(user_id=user.id))
    three_way_import()
    from functioning.constants import DEFAULT_GROUPS
    from functioning.market import Holdings
    for entry in Holdings().entries():
        db.session.add(Position(user_id=user.id, ticker=entry["ticker"], quantity=float(entry["quantity"]),
                                cost_eur=float(entry.get("cost_eur", 0)), group=DEFAULT_GROUPS.get(entry["ticker"])))
    db.session.commit()


def user_positions(user):
    import_holdings_file(user)
    return db.session.scalars(select(Position).where(Position.user_id == user.id).order_by(Position.ticker)).all()


def user_plan(user):
    """Groups of the user's stocks plus the settings the user saved (defaults otherwise)."""
    from functioning.groups import plan_from_json
    saved = {row.group: json.loads(row.data)
             for row in db.session.scalars(select(GroupSetting).where(GroupSetting.user_id == user.id))}
    groups = {p.ticker: p.group for p in user_positions(user) if p.group}
    return plan_from_json({"groups": groups, "settings": saved})


def position_json(position):
    return {"ticker": position.ticker, "quantity": position.quantity, "cost_eur": position.cost_eur, "group": position.group}


def verify_ticker(ticker):
    """True if Yahoo has prices for the ticker. Fetches (and caches) the history."""
    three_way_import()
    from functioning.prices import PriceCache
    series, _ = PriceCache().series([ticker])
    return bool(series)


def yahoo_search(query):
    import yfinance
    quotes = yfinance.Search(query, max_results=8).quotes
    return [{"symbol": q.get("symbol", ""), "name": q.get("longname") or q.get("shortname") or "",
             "exchange": q.get("exchDisp", ""), "type": q.get("quoteType", "")} for q in quotes if q.get("symbol")]


def read_position_payload(body):
    ticker = str(body.get("ticker", "")).strip().upper()
    if not TICKER_PATTERN.match(ticker):
        raise ValueError("Ongeldige ticker.")
    quantity = read_number(body.get("quantity"), 1e-9, 1e9, float)
    cost = read_number(body.get("cost_eur", 0) or 0, 0, 1e9, float)
    return ticker, quantity, cost


@app.route("/apps/three-way/dashboard")
@login_required
def three_way_dashboard():
    user = approved_user()
    if IS_PRODUCTION:
        return render_template("three_way_dashboard.html", defaults=None, disabled=True)
    three_way_import()
    from functioning.constants import GROUP_LABELS
    scenario = scenario_defaults(user)
    plan = user_plan(user)
    defaults = {**vars(scenario.rule), "news": scenario.news, "intuition": scenario.intuition,
                "plan": {"groups": plan.groups, "settings": plan.settings, "labels": GROUP_LABELS}}
    return render_template("three_way_dashboard.html", defaults=defaults, disabled=False)


def scenario_defaults(user):
    """Admin: the saved rule and latest scores. Others: the live start rule, no scores."""
    from functioning.dashboard import Scenario, default_scenario
    from functioning.rule import LIVE
    return default_scenario() if user.is_admin else Scenario(LIVE)


@app.route("/apps/three-way/dashboard/data")
@login_required
@limiter.limit("1200 per hour", override_defaults=True)
def three_way_dashboard_data():
    user = approved_user()
    if IS_PRODUCTION:
        return {"error": "Het dashboard is op Render uitgeschakeld totdat persistente opslag is ingericht."}, 503
    three_way_import()
    from functioning.dashboard import dashboard_data
    from functioning.storage import Ledger
    try:
        scenario = scenario_from_args(request.args, scenario_defaults(user), user_plan(user))
        window = int(read_number(request.args.get("days", "180"), 30, 1825, float))
    except (ValueError, TypeError, AttributeError):
        return {"error": "Ongeldige instelling."}, 400
    holdings = UserHoldings({p.ticker: p.quantity for p in user_positions(user)})
    ledger = Ledger() if user.is_admin else Ledger(Path(app.instance_path) / "no-trades.json")
    with THREE_WAY_LOCK:
        return dashboard_data(scenario, window, holdings=holdings, ledger=ledger)


@app.route("/apps/three-way/dashboard/research")
@login_required
@limiter.limit("1200 per hour", override_defaults=True)
def three_way_dashboard_research():
    user = approved_user()
    if IS_PRODUCTION:
        return {"error": "Het dashboard is op Render uitgeschakeld totdat persistente opslag is ingericht."}, 503
    three_way_import()
    from functioning.prices import PriceCache
    from functioning.research import research_data
    try:
        scenario = scenario_from_args(request.args, scenario_defaults(user), user_plan(user))
    except (ValueError, TypeError, AttributeError):
        return {"error": "Ongeldige instelling."}, 400
    quantities = {p.ticker: p.quantity for p in user_positions(user)}
    with THREE_WAY_LOCK:
        series, failed = PriceCache().series(list(quantities))
        return research_data(series, scenario, quantities) | {"failed": failed}


def latest_ai_run(experiment: str, folder: Path | None = None) -> dict | None:
    """The newest saved run of an AI-Lab experiment (plain JSON, no AI libraries needed here)."""
    import json
    files = sorted((folder or Path(AI_LAB_PATH) / "runs").glob(f"*-{experiment}.json"))
    return json.loads(files[-1].read_text()) if files else None


def ai_runs(folder: Path | None = None) -> list[dict]:
    """All saved AI-Lab runs, newest first, with the headline of each."""
    import json
    rows = []
    for path in sorted((folder or Path(AI_LAB_PATH) / "runs").glob("*.json"), reverse=True):
        run = json.loads(path.read_text())
        result = run.get("result", {})
        rows.append({"experiment": run.get("experiment", path.stem), "time": run.get("time", ""),
                     "headline": (f"model {result['rule_pct']:+.1f}% tegen vasthouden {result['hold_pct']:+.1f}%, "
                                  f"{result['wins']}/{result['total_periods']} perioden gewonnen")
                     if "rule_pct" in result else ""})
    return rows


@app.route("/apps/ai-lab")
@login_required
def ai_lab():
    user = approved_user()
    return render_template("ai_lab.html", runs=ai_runs() if user.is_admin else [], is_admin=user.is_admin)


@app.route("/apps/three-way/dashboard/ai")
@login_required
def three_way_dashboard_ai():
    user = approved_user()
    if not user.is_admin:
        return {"run": None}
    run = latest_ai_run("three_way_turns")
    if run:
        run["result"].pop("periods", None)
    return {"run": run}


def latest_advice(path: Path | None = None) -> dict | None:
    """De laatste uitkomst van advice.py (zie three-way), of None als die er nog niet is."""
    import json
    path = path or Path(THREE_WAY_PATH) / "data" / "advice.json"
    return json.loads(path.read_text()) if path.exists() else None


def advice_form_defaults():
    """Nieuws en intuïtie van de vorige check, als beginwaarde voor het formulier."""
    three_way_import()
    from datetime import date
    from functioning.storage import Checks
    previous = Checks.previous(Checks().load(), date.today())
    return {"news": previous.news if previous else 0, "intuition": previous.intuition if previous else 0}


@app.route("/apps/three-way/advice")
@login_required
def three_way_advice():
    user = approved_user()
    usable = user.is_admin and not IS_PRODUCTION
    return render_template("three_way_advice.html", is_admin=user.is_admin, production=IS_PRODUCTION,
                           defaults=advice_form_defaults() if usable else None)


def make_advice(user, news, intuition, mode):
    """Het advies voor de posities van de gebruiker, in het logboek gezet en bewaard. Gooit AdviceError."""
    three_way_import()
    from datetime import date
    from functioning.advice import advice_dict, compute_advice, record_advice, save_advice, stocks_in_cash
    from functioning.storage import RuleStore
    day = date.today()
    quantities = {p.ticker: p.quantity for p in user_positions(user)}
    with THREE_WAY_LOCK:
        result = compute_advice(quantities, news, intuition, day, stocks_in_cash(day), mode)
        record_advice(day, result.rows, news, intuition, RuleStore().load()[0])
        save_advice(day, result.rows, result.top, result.weights)
    return advice_dict(day, result.rows, result.top, result.weights) | {"stale": result.stale, "failed": result.failed}


@app.route("/apps/three-way/advice/run", methods=["POST"])
@login_required
@limiter.limit("30 per hour", override_defaults=True)
def three_way_advice_run():
    user = approved_user()
    if IS_PRODUCTION:
        return {"error": "Het advies is op Render uitgeschakeld totdat persistente opslag is ingericht."}, 503
    if not user.is_admin:
        abort(403)
    body = request.get_json(silent=True) or {}
    try:
        news = read_number(body.get("news", 0), -5, 5, float)
        intuition = read_number(body.get("intuition", 0), -5, 5, float)
    except (ValueError, TypeError):
        return {"error": "Nieuws en intuïtie moeten tussen -5 en +5 liggen."}, 400
    mode = "train" if body.get("retrain") is True else "score"
    three_way_import()
    from functioning.advice import AdviceError
    try:
        return make_advice(user, news, intuition, mode)
    except AdviceError as error:
        return {"error": str(error)}, 500


def model_overview(folder: Path | None = None) -> dict:
    """De laatste run (scores van vandaag) en de laatste run met toetsing (nauwkeurigheid), uit de opgeslagen JSON."""
    files = sorted((folder or Path(AI_LAB_PATH) / "runs").glob("*-three_way_advice.json"), reverse=True)
    latest, tested = None, None
    for path in files:
        run = json.loads(path.read_text())
        latest = latest or run
        if run["result"].get("evaluation"):
            tested = run
            break
    return {"latest": latest, "tested": tested}


@app.route("/apps/three-way/models")
@login_required
def three_way_models():
    user = approved_user()
    usable = user.is_admin and not IS_PRODUCTION
    return render_template("three_way_models.html", is_admin=user.is_admin, production=IS_PRODUCTION,
                           overview=model_overview() if usable else None)


@app.route("/apps/three-way/dashboard/advice")
@login_required
def three_way_dashboard_advice():
    user = approved_user()
    return {"advice": latest_advice() if user.is_admin and not IS_PRODUCTION else None}


@app.route("/apps/three-way/api/holdings", methods=["GET", "POST"])
@login_required
def api_holdings():
    user = approved_user()
    if request.method == "GET":
        return {"holdings": [position_json(p) for p in user_positions(user)]}
    try:
        ticker, quantity, cost = read_position_payload(request.get_json(silent=True) or {})
    except (ValueError, TypeError):
        return {"error": "Controleer ticker, aantal en kosten."}, 400
    position = db.session.scalar(select(Position).where(Position.user_id == user.id, Position.ticker == ticker))
    if position is None:
        if len(user_positions(user)) >= MAX_POSITIONS:
            return {"error": f"Maximaal {MAX_POSITIONS} aandelen."}, 400
        if not verify_ticker(ticker):
            return {"error": f"Geen koersdata gevonden voor {ticker} op Yahoo. Controleer de ticker."}, 400
        position = Position(user_id=user.id, ticker=ticker, quantity=quantity, cost_eur=cost)
        db.session.add(position)
    position.quantity, position.cost_eur = quantity, cost
    db.session.commit()
    return position_json(position)


@app.route("/apps/three-way/api/holdings/<ticker>", methods=["DELETE"])
@login_required
def api_holdings_delete(ticker):
    user = approved_user()
    position = db.session.scalar(select(Position).where(Position.user_id == user.id, Position.ticker == ticker.upper()))
    if position is None:
        abort(404)
    db.session.delete(position)
    db.session.commit()
    return {"deleted": position.ticker}


@app.route("/apps/three-way/api/plan", methods=["POST"])
@login_required
def api_plan():
    """Save the group of each stock and the settings of each group for this user."""
    user = approved_user()
    three_way_import()
    from functioning.groups import plan_from_json
    try:
        plan = plan_from_json(request.get_json(silent=True) or {})
    except (ValueError, TypeError, AttributeError):
        return {"error": "Ongeldige instellingen."}, 400
    for position in user_positions(user):
        position.group = plan.groups.get(position.ticker)
    db.session.execute(db.delete(GroupSetting).where(GroupSetting.user_id == user.id))
    for group, setting in plan.settings.items():
        db.session.add(GroupSetting(user_id=user.id, group=group, data=json.dumps(setting)))
    db.session.commit()
    return {"saved": True}


@app.route("/apps/three-way/api/players")
@login_required
@limiter.limit("60 per hour", override_defaults=True)
def api_players():
    """Ownership, short interest, consensus and insider activity per stock of this user."""
    user = approved_user()
    if IS_PRODUCTION:
        return {"error": "Uitgeschakeld op Render."}, 503
    three_way_import()
    from functioning.players import PlayersCache
    tickers = [p.ticker for p in user_positions(user)]
    with THREE_WAY_LOCK:
        return {"players": PlayersCache().rows(tickers)}


@app.route("/apps/three-way/api/search")
@login_required
@limiter.limit("120 per hour", override_defaults=True)
def api_search():
    approved_user()
    query = request.args.get("q", "").strip()
    if len(query) < 2 or len(query) > 40:
        return {"results": []}
    try:
        return {"results": yahoo_search(query)}
    except Exception:
        app.logger.warning("Yahoo-zoekopdracht mislukt.")
        return {"error": "Zoeken bij Yahoo is nu niet beschikbaar. Vul de ticker zelf in."}, 502


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
