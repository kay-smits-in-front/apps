"""De cijfers achter het overzicht: per aandeel de waarde als je had vastgehouden en met de uitgevoerde adviezen,
wat elke verkoop opleverde, de daghandelcijfers en waarom nu. Per aandeel en voor de portefeuille, in euro."""

from functioning.constants import STATS_DAYS, STATS_MONTHS, TRANSACTION_COST_EUR
from functioning.daytrade import daytrade_panel
from functioning.imports import dataclass, date, timedelta
from functioning.market import Holdings
from functioning.monitor import PERIODS, change_pct, monitor_rows
from functioning.prices import PriceCache, Series
from functioning.storage import Ledger, RuleStore, Trade
from functioning.whynow import why_now


@dataclass(frozen=True)
class Move:
    index: int      # position in the series
    action: str     # "buy" or "sell"
    price: float    # close in the listing currency


# ------------------------------------------------------------- values


def value_curve(
    closes: list[float], moves: list[Move], first: int, last: int, shares0: float, fx: float
) -> tuple[list[float], int, int]:
    """Value in euro per day from `first` to `last`, costs included, plus the number
    of sales and buys that were really carried out (each one costs TRANSACTION_COST_EUR)."""
    by_index = {m.index: m for m in moves}
    shares, cash, values, sells, buys = shares0, 0.0, [], 0, 0
    for i in range(first, last + 1):
        move = by_index.get(i)
        if move and move.action == "sell" and shares > 0:
            cash, shares, sells = shares * move.price * fx - TRANSACTION_COST_EUR, 0.0, sells + 1
        elif move and move.action == "buy" and cash > TRANSACTION_COST_EUR:
            shares, cash, buys = (cash - TRANSACTION_COST_EUR) / (move.price * fx), 0.0, buys + 1
        values.append(shares * closes[i] * fx + cash)
    return values, sells, buys


def sale_effects(closes: list[float], moves: list[Move], shares0: float, fx: float, last: int) -> list[dict]:
    """For every sale: what it gained or lost against keeping the shares until the
    buy-back (or the end), in euro, costs included."""
    effects = []
    for k, move in enumerate(moves):
        if move.action != "sell":
            continue
        later = next((m for m in moves[k + 1:] if m.action == "buy"), None)
        back_price = later.price if later else closes[last]
        costs = TRANSACTION_COST_EUR * (2 if later else 1)
        effects.append({"index": move.index, "euro": round(shares0 * (move.price - back_price) * fx - costs, 2)})
    return effects


# ------------------------------------------------------------ alignment


def window_start(days: list[date], today: date, window_days: int) -> int:
    limit = today - timedelta(days=window_days)
    return next(i for i, d in enumerate(days) if d >= limit)


def executed_moves(trades: list[Trade], ticker: str, days: list[date], first: int) -> list[Move]:
    index = {d: i for i, d in enumerate(days)}
    return [
        Move(index[t.day], t.action, t.price)
        for t in sorted(trades, key=lambda t: t.day)
        if t.ticker == ticker and t.day in index and index[t.day] >= first
    ]


class StockPanel:
    """Alle lijnen en verkopen van één aandeel over de periode."""

    def __init__(self, series: Series, quantity: float, trades: list[Trade], today: date, window_days: int,
                 rule, news: float | None, intuition: float | None):
        self.series, self.rule, self.news, self.intuition = series, rule, news, intuition
        self.first = window_start(series.days, today, window_days)
        self.last = len(series.closes) - 1
        self.shares0 = quantity
        self.trades = trades

    def build(self) -> dict:
        s = self.series
        done = executed_moves(self.trades, s.ticker, s.days, self.first)
        hold, _, _ = value_curve(s.closes, [], self.first, self.last, self.shares0, s.fx)
        executed, sells, buys = value_curve(s.closes, done, self.first, self.last, self.shares0, s.fx)
        invested = not done or done[-1].action != "sell"
        return {
            "ticker": s.ticker,
            "daytrade": daytrade_panel(s, self.first),
            "why": why_now(s, self.rule, invested, self.news, self.intuition),
            "days": [d.isoformat() for d in s.days[self.first:]],
            "hold": hold, "executed": executed,
            "costs": round((sells + buys) * TRANSACTION_COST_EUR, 2),
            "effects": [e | {"day": s.days[e["index"]].isoformat()}
                        for e in sale_effects(s.closes, done, self.shares0, s.fx, self.last)],
        }


# ------------------------------------------------------------ portfolio

LINES = ("hold", "executed")


def forward_fill(axis: list[str], days: list[str], values: list[float]) -> list[float]:
    """Values on the common day axis. Before the first day the first value, after a
    missing day the last known value."""
    known = dict(zip(days, values))
    filled, last = [], values[0]
    for day in axis:
        last = known.get(day, last)
        filled.append(round(last, 2))
    return filled


def combine(panels: list[dict]) -> dict:
    """Alle aandelen op één dag-as, plus het totaal van de portefeuille per lijn."""
    axis = sorted({d for p in panels for d in p["days"]})
    for panel in panels:
        for line in LINES:
            panel[line] = forward_fill(axis, panel["days"], panel[line])
        panel["days"] = axis
    totals = {line: [round(sum(p[line][i] for p in panels), 2) for i in range(len(axis))] for line in LINES}
    return {"days": axis, "stocks": panels, "total": totals}


def overview_data(window_days: int, news: float | None = None, intuition: float | None = None,
                  cache: PriceCache | None = None, holdings: Holdings | None = None, ledger: Ledger | None = None,
                  today: date | None = None, watchlist: list[str] = (), views: dict[str, dict] | None = None) -> dict:
    """Alles wat het overzicht tekent, voor één periode: de monitor (portefeuille en watchlist) en de portefeuille."""
    today = today or date.today()
    quantities = (holdings or Holdings()).quantities()
    tickers = list(quantities) + [t for t in watchlist if t not in quantities]
    series, failed = (cache or PriceCache()).series(tickers, today)
    trades = (ledger or Ledger()).load()
    rule, _ = RuleStore().load()
    views = views or {}
    panels = [StockPanel(s, quantities[s.ticker], trades, today, window_days, rule,
                         own_score(views.get(s.ticker), "news", news), own_score(views.get(s.ticker), "intuition", intuition)).build()
              for s in series if s.ticker in quantities]
    found = {"monitor": monitor_rows(series, quantities), "failed": failed,
             "stats": portfolio_stats([s for s in series if s.ticker in quantities], quantities)}
    if not panels:
        return {"days": [], "stocks": [], "total": {line: [] for line in LINES}} | found
    return combine(panels) | found


def own_score(view: dict | None, key: str, general: float | None) -> float | None:
    """Jouw score voor dit aandeel als je die invulde, anders de algemene score."""
    value = (view or {}).get(key)
    return general if value is None else value


# ------------------------------------------------- cijfers van de portefeuille


def holding_values(series: list[Series], quantities: dict[str, float]) -> tuple[list[str], list[float]]:
    """De waarde in euro per dag van wat je nu hebt, over de laatste STATS_DAYS dagen, op één dag-as."""
    recent = [(s, [d.isoformat() for d in s.days[-STATS_DAYS:]], s.closes[-STATS_DAYS:]) for s in series]
    axis = sorted({d for _, days, _ in recent for d in days})[-STATS_DAYS:]
    # shortcut: een aandeel dat later begon telt daarvoor mee tegen zijn eerste koers; apart behandelen als dat stoort
    lines = [forward_fill(axis, days, [c * quantities[s.ticker] * s.fx for c in closes]) for s, days, closes in recent]
    return axis, [round(sum(line[i] for line in lines), 2) for i in range(len(axis))]


def monthly_returns(axis: list[str], values: list[float]) -> list[dict]:
    """Rendement in % per kalendermaand: laatste waarde van de maand tegen de laatste van de maand ervoor."""
    last_of = {day[:7]: value for day, value in zip(axis, values)}
    months = list(last_of)
    found = [{"month": m, "pct": round((last_of[m] / last_of[before] - 1) * 100, 1)} for before, m in zip(months, months[1:])]
    return found[-STATS_MONTHS:]


def quarter_average(months: list[dict]) -> float | None:
    """Gemiddeld rendement per blok van drie maanden (samengesteld), over de volle blokken."""
    blocks = [months[i:i + 3] for i in range(len(months) % 3, len(months), 3)]
    results = [((1 + b[0]["pct"] / 100) * (1 + b[1]["pct"] / 100) * (1 + b[2]["pct"] / 100) - 1) * 100 for b in blocks]
    return round(sum(results) / len(results), 1) if results else None


def portfolio_stats(series: list[Series], quantities: dict[str, float]) -> dict | None:
    """Hoe je huidige portefeuille het deed: per periode, per maand, en gemiddeld per maand en per kwartaal."""
    if not series:
        return None
    axis, values = holding_values(series, quantities)
    months = monthly_returns(axis, values)
    pcts = [m["pct"] for m in months]
    return {
        "value": values[-1], "day": axis[-1],
        "periods": {"d1": change_pct(values, 1)} | {name: change_pct(values, days) for name, days in PERIODS.items()},
        "from_top_pct": round((values[-1] / max(values) - 1) * 100, 1),
        "months": months,
        "month_average": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "quarter_average": quarter_average(months),
        "positive_months": sum(p > 0 for p in pcts),
        "best": max(months, key=lambda m: m["pct"], default=None), "worst": min(months, key=lambda m: m["pct"], default=None),
    }
