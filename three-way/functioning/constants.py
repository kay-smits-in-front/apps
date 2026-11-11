"""All constants. No logic."""

from pathlib import Path

ACTION_LABELS = {"buy": "KOPEN", "hold": "HOUDEN", "sell": "VERKOPEN"}

# Files
DATA_DIR = Path(__file__).resolve().parent.parent / "data"  # the data folder of three-way
HOLDINGS_FILE = DATA_DIR / "holdings.json"
CHECKS_FILE = DATA_DIR / "checks.json"
STATUS_FILE = DATA_DIR / "status.json"
LEDGER_FILE = DATA_DIR / "ledger.json"
PRICES_FILE = DATA_DIR / "prices.json"
RULE_FILE = DATA_DIR / "rule.json"

# Follow-up of the calls
PAPER_TRADING = True          # True: het advies zet de acties als (fictief) uitgevoerd in data/ledger.json
# Transaction costs (DEGIRO, 3.95 euro per buy or sell, for every stock)
TRANSACTION_COST_EUR = 3.95
COST_COVER_FACTOR = 2.0       # expected move must be this many times the round trip cost

# The rule (one of the facets of the forest). Uses data/rule.json if present, else these settings.
LIVE_LOOKBACK_DAYS = 2        # trading days a rise or fall is measured over
LIVE_UP_PCT = 5.0             # sell (take profit) after a rise of this much
LIVE_DOWN_PCT = 10.0          # buy back (when in cash) after a fall of this much
LIVE_STOP_PCT = 8.0           # sell (stop loss) after a fall of this much ...
LIVE_FLOOR_PCT = 20.0         # ... but not after a fall of this much: that is the bottom
LIVE_REGIME_PCT = 40.0        # a change of this much over two months is an extreme trend
LIVE_TURN_PCT = 3.0           # in an extreme trend: act only after a week's move of this much
LIVE_REVIEW_DAYS = 2          # the rule is checked every 2 trading days

# Winners: a stock that rose this much over the trailing year is only held
WINNER_LOOKBACK_DAYS = 250
WINNER_RETURN_PCT = 100.0

# Rule history
STRATEGY_HISTORY_DAYS = 1825  # five years of daily prices (shorter if the stock is younger)
WEEK_DAYS = 5                 # trading days in a week
REGIME_DAYS = 42              # trading days (two months) over which an extreme trend is measured
LONG_DAYS = 126               # trading days (half a year), for a trend that builds up slowly
LONG_FACTOR = 1.5             # over half a year the trend must be this many times the two-month limit
FORTNIGHT_DAYS = 10           # trading days; a rise this fast is a sudden rise
FAST_SHARE = 0.5              # a fortnight's rise of this share of the extreme limit is sudden

# Day-trader view
DAYTRADE_VOLUME_DAYS = 20     # normal volume = average of this many days before
DAYTRADE_SPIKE_X = 2.0        # a day with this many times the normal volume is a spike
DAYTRADE_GAP_PCT = 3.0        # open this far from the previous close is a gap
DAYTRADE_RANGE_PCT = 8.0      # high minus low of this much of the close is a wide day
DAYTRADE_ATR_DAYS = 14
DAYTRADE_RSI_DAYS = 14

# Who is in the stock (Yahoo ownership data)
PLAYERS_FILE = DATA_DIR / "players.json"
PLAYERS_MAX_AGE_DAYS = 7      # ownership data changes slowly: refresh once a week
PLAYERS_TOP_HOLDERS = 3
PLAYERS_INSIDER_DAYS = 180    # insider buys and sales over this many days
SHORT_HIGH_PCT = 15.0         # short interest of this share of the float is high
INSTITUTIONS_HIGH_PCT = 70.0
CONSENSUS_BUY_MAX = 2.2       # Yahoo recommendation mean: 1 = strong buy ... 5 = strong sell
CONSENSUS_SELL_MIN = 3.5

# Why now
TREND_MA_DAYS = 20            # rolling average window of the trend factor, trading days
WHY_TREND_PCT = 3.0           # close this far from its rolling average is a clear trend
WHY_CUMULATIVE_PCT = 30.0     # close this far from the average of all closes is dear or cheap
WHY_RSI_LOW = 30
WHY_RSI_HIGH = 70
WHY_SCORE_PCT = 1.0           # news or intuition of this size (-5..+5) counts as a lean

# Advies (advice.py): elk onderdeel een score van -5 tot +5, samen gewogen tot 100%
ADVICE_FILE = DATA_DIR / "advice.json"
ADVICE_LOG_FILE = DATA_DIR / "advice_log.json"   # elke run volledig, om achteraf te beoordelen
WATCHLIST_FILE = DATA_DIR / "watchlist.json"     # aandelen die je interessant vindt, kandidaten om naar te wisselen
ADVICE_WEIGHTS = {            # toets nov 2026: de forest alleen deed het beter dan elk mengsel van modellen
    "forest": 0.55,
    "nieuws": 0.25,
    "intuitie": 0.20,
}
FORECAST_HORIZON_DAYS = 3     # twee en een halve dag, naar boven afgerond op handelsdagen
FORECAST_FULL_SCALE = 0.3     # kans stijging min kans daling van zoveel geeft score +5
FORECAST_TOP_FACETS = 2       # zoveel facetten toont het advies als zwaarste
ROTATION_LONG_DAYS = 252      # rotatie: stijging over een jaar ...
ROTATION_SKIP_DAYS = 21       # ... zonder de laatste maand (die keert vaak om)
ROTATION_VOL_DAYS = 126       # beweeglijkheid over een half jaar
ADVICE_PARTS = tuple(ADVICE_WEIGHTS)
assert abs(sum(ADVICE_WEIGHTS.values()) - 1.0) < 1e-9, "de gewichten van het advies moeten samen 100% zijn"
ADVICE_SELL_AT = 1.5          # belegd en de score is dit negatief of lager: verkopen
ADVICE_BUY_AT = 1.5           # in cash en de score is dit positief of hoger: terugkopen
ADVICE_MOVE_PCT = 3.0         # de beweging waar het AI-advies op mikt, voor de kostencontrole
ADVICE_HORIZON_TEXT = "komende 2,5 dag"
ADVICE_MAX_PRICE_AGE_DAYS = 4  # oudere koersen (meer dan een weekend) geven een waarschuwing
REVIEW_HORIZON_DAYS = 3       # een advies wordt na zoveel handelsdagen beoordeeld
REVIEW_NEUTRAL = 0.3          # een onderdeel met een score dichter bij 0 dan dit heeft geen mening
