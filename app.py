import json
import os
import re
import threading
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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
THREE_WAY_LOCK = threading.Lock()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Position(db.Model):
    """A stock one user holds."""
    __table_args__ = (db.UniqueConstraint("user_id", "ticker", name="one_position_per_ticker"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    ticker = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    cost_eur = db.Column(db.Float, nullable=False, default=0.0)


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
        {"name": "Three Way", "description": "Advies per aandeel voor de komende dagen, en je portefeuille.",
         "status": "Lokaal", "icon": "↗", "url": url_for("three_way")},
        {"name": "SHIELD", "description": "Basisdashboard voor de DJI Tello: verkenning, mapping en AI-interactie.",
         "status": "Opzet", "icon": "⌁", "url": url_for("shield_dashboard")},
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


def read_number(raw, low, high, kind):
    value = kind(str(raw).replace(",", "."))
    if not low <= value <= high:
        raise ValueError("buiten bereik")
    return value


def three_way_import():
    """Make the bundled Three Way code importable."""
    import sys
    if THREE_WAY_PATH not in sys.path:
        sys.path.insert(0, THREE_WAY_PATH)


MAX_POSITIONS = 60
MAX_WATCHLIST = 40
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


def usable_by(user):
    """Three Way works only for the admin, and only locally (no persistent private storage on Render yet)."""
    return user.is_admin and not IS_PRODUCTION


def three_way_user():
    user = approved_user()
    if not usable_by(user):
        abort(403)
    three_way_import()
    return user


def import_holdings_file(user):
    """First visit of the admin: take over data/holdings.json."""
    if not user.is_admin or db.session.get(Seeded, user.id):
        return
    db.session.add(Seeded(user_id=user.id))
    three_way_import()
    from functioning.market import Holdings
    for entry in Holdings().entries():
        db.session.add(Position(user_id=user.id, ticker=entry["ticker"], quantity=float(entry["quantity"]),
                                cost_eur=float(entry.get("cost_eur", 0))))
    db.session.commit()


def user_positions(user):
    import_holdings_file(user)
    return db.session.scalars(select(Position).where(Position.user_id == user.id).order_by(Position.ticker)).all()


def user_quantities(user):
    return {p.ticker: p.quantity for p in user_positions(user)}


def position_json(position):
    return {"ticker": position.ticker, "quantity": position.quantity, "cost_eur": position.cost_eur}


def verify_ticker(ticker):
    """True if Yahoo has prices for the ticker. Fetches (and caches) the history."""
    from functioning.prices import PriceCache
    series, _ = PriceCache().series([ticker])
    return bool(series)


def yahoo_search(query):
    import yfinance
    quotes = yfinance.Search(query, max_results=8).quotes
    return [{"symbol": q.get("symbol", ""), "name": q.get("longname") or q.get("shortname") or "",
             "exchange": q.get("exchDisp", ""), "type": q.get("quoteType", "")} for q in quotes if q.get("symbol")]


def read_ticker(raw):
    ticker = str(raw or "").strip().upper()
    if not TICKER_PATTERN.match(ticker):
        raise ValueError("Ongeldige ticker.")
    return ticker


def read_position_payload(body):
    ticker = read_ticker(body.get("ticker"))
    quantity = read_number(body.get("quantity"), 1e-9, 1e9, float)
    cost = read_number(body.get("cost_eur", 0) or 0, 0, 1e9, float)
    return ticker, quantity, cost


def last_scores():
    """News and intuition of the latest check, as the start values of the form."""
    from datetime import date
    from functioning.storage import Checks
    previous = Checks.previous(Checks().load(), date.today() + timedelta(days=1))
    return {"news": previous.news if previous else 0, "intuition": previous.intuition if previous else 0}


def track_record(limit: int = 6) -> dict:
    """De beoordeling van het advies tot nu toe: de laatste runs en het scorebord per onderdeel."""
    from functioning.advice_log import AdviceLog
    from functioning.constants import ADVICE_WEIGHTS
    from functioning.prices import PriceCache
    from functioning.review import entries_from_checks, merge_runs, part_scoreboard, review_all
    from functioning.storage import Checks, Ledger
    trades = Ledger().load()
    entries = merge_runs(AdviceLog().load(), entries_from_checks(Checks().load(), lambda day: Ledger.cash_before(trades, day)))
    reviews = review_all(entries, PriceCache().load())
    board = sorted(part_scoreboard(reviews), key=lambda part: -ADVICE_WEIGHTS.get(part["name"], 0))
    return {"reviews": reviews[:limit], "scoreboard": board, "runs": len(reviews), "weights": ADVICE_WEIGHTS}


@app.route("/apps/three-way")
@login_required
def three_way():
    user = approved_user()
    if not usable_by(user):
        return render_template("three_way.html", usable=False, production=IS_PRODUCTION)
    import_holdings_file(user)  # before the page's parallel requests, which would each try to import it
    three_way_import()
    from functioning.constants import ADVICE_WEIGHTS
    return render_template("three_way.html", usable=True, defaults=last_scores(), weights=ADVICE_WEIGHTS,
                           track=track_record())


@app.route("/apps/three-way/overview")
@login_required
@limiter.limit("600 per hour", override_defaults=True)
def three_way_overview():
    user = three_way_user()
    from functioning.overview import overview_data
    try:
        window = int(read_number(request.args.get("days", "180"), 30, 1825, float))
    except (ValueError, TypeError):
        return {"error": "Ongeldige periode."}, 400
    from functioning.storage import Views, Watchlist
    scores = last_scores()
    with THREE_WAY_LOCK:
        return overview_data(window, scores["news"], scores["intuition"], holdings=UserHoldings(user_quantities(user)),
                             watchlist=Watchlist().load(), views=Views().load())


@app.route("/apps/three-way/advice")
@login_required
def three_way_advice():
    three_way_user()
    from functioning.constants import ADVICE_FILE
    return {"advice": json.loads(ADVICE_FILE.read_text()) if ADVICE_FILE.exists() else None}


@app.route("/apps/three-way/advice/run", methods=["POST"])
@login_required
@limiter.limit("30 per hour", override_defaults=True)
def three_way_advice_run():
    user = three_way_user()
    from datetime import date
    from functioning.advice import AdviceError, advice_dict, compute_advice, log_advice, record_advice, save_advice, stocks_in_cash
    from functioning.storage import RuleStore, Views, Watchlist
    body = request.get_json(silent=True) or {}
    try:
        news = read_number(body.get("news", 0), -5, 5, float)
        intuition = read_number(body.get("intuition", 0), -5, 5, float)
    except (ValueError, TypeError):
        return {"error": "Nieuws en intuïtie moeten tussen -5 en +5 liggen."}, 400
    day = date.today()
    try:
        with THREE_WAY_LOCK:
            result = compute_advice(user_quantities(user), news, intuition, day, stocks_in_cash(day), Watchlist().load(),
                                    Views().load())
            record_advice(day, result.rows, news, intuition, RuleStore().load()[0])
            save_advice(result)
            log_advice(day, result, news, intuition)
    except AdviceError as error:
        return {"error": str(error)}, 500
    return advice_dict(result)


@app.route("/apps/three-way/api/holdings", methods=["GET", "POST"])
@login_required
def api_holdings():
    user = three_way_user()
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
    user = three_way_user()
    position = db.session.scalar(select(Position).where(Position.user_id == user.id, Position.ticker == ticker.upper()))
    if position is None:
        abort(404)
    db.session.delete(position)
    db.session.commit()
    return {"deleted": position.ticker}


@app.route("/apps/three-way/api/watchlist", methods=["GET", "POST"])
@login_required
def api_watchlist():
    """Aandelen die je interessant vindt. Het advies scoort ze mee en toont de beste als kandidaat."""
    three_way_user()
    from functioning.storage import Watchlist
    if request.method == "GET":
        return {"watchlist": Watchlist().load()}
    raw = (request.get_json(silent=True) or {}).get("tickers", "")
    try:
        tickers = list(dict.fromkeys(read_ticker(t) for t in re.split(r"[\s,;]+", str(raw)) if t))
    except ValueError:
        return {"error": "Een van de tickers is ongeldig. Gebruik Yahoo-tickers, zoals ASML.AS."}, 400
    if len(tickers) > MAX_WATCHLIST:
        return {"error": f"Maximaal {MAX_WATCHLIST} aandelen op de watchlist."}, 400
    Watchlist().save(tickers)
    return {"watchlist": tickers}


def read_own_score(raw):
    """A score from -5 to +5, or None when left empty (then the general score counts)."""
    return None if raw in (None, "") else read_number(raw, -5, 5, float)


@app.route("/apps/three-way/api/views", methods=["GET", "POST"])
@login_required
def api_views():
    """Jouw eigen beeld per aandeel: nieuws, intuïtie en een notitie."""
    three_way_user()
    from functioning.storage import Views
    if request.method == "GET":
        return {"views": Views().load()}
    body = request.get_json(silent=True) or {}
    try:
        ticker = read_ticker(body.get("ticker"))
        news, intuition = read_own_score(body.get("news")), read_own_score(body.get("intuition"))
    except (ValueError, TypeError):
        return {"error": "Scores moeten tussen -5 en +5 liggen."}, 400
    return {"views": Views().set(ticker, news, intuition, str(body.get("note") or "").strip()[:500])}


@app.route("/apps/three-way/api/news/<ticker>")
@login_required
@limiter.limit("300 per hour", override_defaults=True)
def api_news(ticker):
    three_way_user()
    from functioning.news import headlines
    try:
        return {"news": headlines(read_ticker(ticker))}
    except ValueError:
        abort(404)
    except Exception:
        app.logger.warning("Yahoo-nieuws mislukt.")
        return {"error": "Nieuws van Yahoo is nu niet beschikbaar."}, 502


@app.route("/apps/three-way/api/players")
@login_required
@limiter.limit("60 per hour", override_defaults=True)
def api_players():
    """Ownership, short interest, consensus and insider activity per stock of this user and the watchlist."""
    user = three_way_user()
    from functioning.players import PlayersCache
    from functioning.storage import Watchlist
    with THREE_WAY_LOCK:
        return {"players": PlayersCache().rows(list(dict.fromkeys(list(user_quantities(user)) + Watchlist().load())))}


@app.route("/apps/three-way/api/search")
@login_required
@limiter.limit("120 per hour", override_defaults=True)
def api_search():
    three_way_user()
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
