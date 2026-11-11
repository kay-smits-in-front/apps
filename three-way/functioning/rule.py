"""The rule for one stock, and the decision made from it.

Rule (all changes in percent):
Invested stock, normal trend:
    rise of up_pct or more              -> SELL (take profit)
    fall between stop_pct and floor_pct -> SELL (stop loss)
    fall of floor_pct or more           -> hold (that is the bottom)
Stock in cash, normal trend:
    fall of down_pct or more            -> BUY (buy back)
Extreme trend (regime_pct or more over two months, or 1.5 times that over half a year):
    up, invested: hold until the week turns down by turn_pct, then SELL
    up, in cash, sudden rise (most of it in two weeks): wait for the first fall, then BUY
    up, in cash, gradual rise: BUY
    down, invested: it slipped through every stop loss, so hold
    down, in cash: wait until the week rises by turn_pct, then BUY
Winners (stocks that doubled over the past year) are only held.

Decision: the rule gives the signal. Checks (costs, track record, news and intuition)
can turn it into HOLD.
"""

from functioning.constants import (
    COST_COVER_FACTOR,
    FAST_SHARE,
    FORTNIGHT_DAYS,
    LIVE_DOWN_PCT,
    LIVE_FLOOR_PCT,
    LIVE_LOOKBACK_DAYS,
    LIVE_REGIME_PCT,
    LIVE_REVIEW_DAYS,
    LIVE_STOP_PCT,
    LIVE_TURN_PCT,
    LIVE_UP_PCT,
    LONG_DAYS,
    LONG_FACTOR,
    REGIME_DAYS,
    TRANSACTION_COST_EUR,
    WEEK_DAYS,
    WINNER_LOOKBACK_DAYS,
    WINNER_RETURN_PCT,
)
from functioning.imports import StrEnum, dataclass


class Signal(StrEnum):
    SELL = "sell"
    BUY = "buy"
    NONE = "none"


class Action(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Outcome:
    signal: Signal
    zone: str  # short reason, shown in the overview


# ------------------------------------------------------------- helpers


def change_pct(closes: list[float], index: int, days: int) -> float:
    """Percent change over the `days` trading days up to and including `index`."""
    return (closes[index] / closes[index - days] - 1) * 100


def worth_trading(value_eur: float, move_pct: float) -> bool:
    """A move must cover the round trip costs several times, or we keep holding."""
    round_trip = 2 * TRANSACTION_COST_EUR
    return value_eur * move_pct / 100 >= COST_COVER_FACTOR * round_trip


def is_winner_at(closes: list[float], index: int) -> bool:
    """True if the stock rose WINNER_RETURN_PCT over the year before `index`."""
    if index < WINNER_LOOKBACK_DAYS:
        return False
    return change_pct(closes, index, WINNER_LOOKBACK_DAYS) >= WINNER_RETURN_PCT


# ---------------------------------------------------------------- rule


@dataclass(frozen=True)
class Rule:
    """One setting of the rule. The methods are the rule itself."""

    lookback_days: int
    up_pct: float
    down_pct: float
    stop_pct: float
    floor_pct: float
    regime_pct: float
    turn_pct: float
    review_days: int

    def describe(self) -> str:
        return (
            f"{self.lookback_days}d: verkoop +{self.up_pct:.0f}%, stop-loss -{self.stop_pct:.0f}%, "
            f"dieptepunt -{self.floor_pct:.0f}%, terugkoop -{self.down_pct:.0f}%, "
            f"extreem {self.regime_pct:.0f}%, keer {self.turn_pct:.0f}%, elke {self.review_days} dgn"
        )

    def normal_zone(self, invested: bool, short: float) -> Outcome:
        """Normal trend. Take profit and stop loss when invested, buy back when in cash."""
        if invested:
            if short >= self.up_pct:
                return Outcome(Signal.SELL, "stijging: winst nemen")
            if short <= -self.floor_pct:
                return Outcome(Signal.NONE, "dieptepunt: niet verkopen")
            if short <= -self.stop_pct:
                return Outcome(Signal.SELL, "daling: stop-loss")
            return Outcome(Signal.NONE, "geen signaal")
        if short <= -self.down_pct:
            return Outcome(Signal.BUY, "daling: terugkopen")
        return Outcome(Signal.NONE, "in cash: wachten op daling")

    def extreme_trend(self, closes: list[float], index: int) -> int:
        """+1 for an extreme rise, -1 for an extreme fall, 0 for a normal trend.
        Measured over two months, and over half a year with a higher limit."""
        two_months = change_pct(closes, index, REGIME_DAYS)
        half_year = change_pct(closes, index, LONG_DAYS) if index >= LONG_DAYS else 0.0
        long_limit = self.regime_pct * LONG_FACTOR
        if two_months >= self.regime_pct or half_year >= long_limit:
            return 1
        if two_months <= -self.regime_pct or half_year <= -long_limit:
            return -1
        return 0

    def is_sudden(self, closes: list[float], index: int) -> bool:
        """True if a big part of an extreme rise happened in the last two weeks."""
        return change_pct(closes, index, FORTNIGHT_DAYS) >= self.regime_pct * FAST_SHARE

    def positive_trend(self, closes: list[float], index: int, invested: bool) -> Outcome:
        """Extreme rise. Held: let it run until the week turns. In cash: wait for the
        first fall if the rise was sudden, buy if it was gradual."""
        week = change_pct(closes, index, WEEK_DAYS)
        if invested:
            if week <= -self.turn_pct:
                return Outcome(Signal.SELL, "extreem positief, trend draait: verkopen")
            return Outcome(Signal.NONE, "extreem positief: vasthouden")
        if not self.is_sudden(closes, index):
            return Outcome(Signal.BUY, "extreem positief, geleidelijk: kopen")
        if week <= -self.turn_pct:
            return Outcome(Signal.BUY, "extreem snelle stijging, eerste daling: kopen")
        return Outcome(Signal.NONE, "extreem snelle stijging: wachten op daling")

    def negative_trend(self, closes: list[float], index: int, invested: bool) -> Outcome:
        """Extreme fall. Held: it slipped through every stop loss, so hold. In cash: buy
        back only after a recovery."""
        if invested:
            return Outcome(Signal.NONE, "extreem negatief, door stop-loss geglipt: vasthouden")
        if change_pct(closes, index, WEEK_DAYS) >= self.turn_pct:
            return Outcome(Signal.BUY, "extreem negatief, herstel: terugkopen")
        return Outcome(Signal.NONE, "extreem negatief: afwachten")

    def trend_outcome(self, closes: list[float], index: int, invested: bool) -> Outcome:
        """What the rule says at `index`, without the winner check."""
        trend = self.extreme_trend(closes, index)
        if trend > 0:
            return self.positive_trend(closes, index, invested)
        if trend < 0:
            return self.negative_trend(closes, index, invested)
        return self.normal_zone(invested, change_pct(closes, index, self.lookback_days))

    def trade_move(self, closes: list[float], index: int) -> float:
        """The size of the move behind a signal, in percent."""
        short = change_pct(closes, index, self.lookback_days)
        week = change_pct(closes, index, WEEK_DAYS)
        return max(abs(short), abs(week))

LIVE = Rule(
    LIVE_LOOKBACK_DAYS,
    LIVE_UP_PCT,
    LIVE_DOWN_PCT,
    LIVE_STOP_PCT,
    LIVE_FLOOR_PCT,
    LIVE_REGIME_PCT,
    LIVE_TURN_PCT,
    LIVE_REVIEW_DAYS,
)


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


