"""Zoek de beste instelling van de regel, parameter voor parameter.
De maat is die van RollingTest: het gewogen aandeel gewonnen periodes, dan het gewogen verschil.
De zoekactie ziet de laatste HOLDOUT_WINDOWS periodes niet; die dienen alleen als controle."""

from functioning.constants import (
    HOLDOUT_WINDOWS,
    SEARCH_FIELDS,
    SEARCH_HIGH_PCT,
    SEARCH_JUMPS,
    SEARCH_LOW_PCT,
    SEARCH_MAX_ROUNDS,
    SEARCH_PATIENCE,
    SEARCH_STEP_PCT,
    WF_TEST_DAYS,
)
from functioning.imports import dataclass, replace
from functioning.market import StockData
from functioning.rule import HOLD, Rule
from functioning.testing import RollingTest, compound, portfolio_return, window_bounds

# ------------------------------------------------------------ one candidate


def is_valid(rule: Rule) -> bool:
    """Een stop-loss boven het dieptepunt zou nooit meer verkopen."""
    return rule.stop_pct < rule.floor_pct


def score_of(test: RollingTest, rule: Rule) -> tuple[float, float]:
    """Hoger is beter. Een ongeldige regel of een regel zonder uitkomst scoort als de slechtste."""
    stability = test.stability_of(rule) if is_valid(rule) else None
    return stability.sort_key() if stability else (-1.0, float("-inf"))


# --------------------------------------------------------------- one field


def jump(test: RollingTest, start: Rule, field: str) -> Rule:
    """Probeer grove waarden en geef de beste, of `start` als geen enkele beter is."""
    best, best_score = start, score_of(test, start)
    for value in SEARCH_JUMPS:
        candidate = replace(start, **{field: value})
        if (score := score_of(test, candidate)) > best_score:
            best, best_score = candidate, score
    return best


def walk(test: RollingTest, start: Rule, field: str, step: float) -> Rule:
    """Loop in één richting. Stop na SEARCH_PATIENCE stappen zonder verbetering of aan de rand."""
    best, best_score = start, score_of(test, start)
    value, misses = getattr(start, field), 0
    while misses < SEARCH_PATIENCE:
        value = round(value + step, 2)
        if not SEARCH_LOW_PCT <= value <= SEARCH_HIGH_PCT:
            break
        candidate = replace(start, **{field: value})
        if (score := score_of(test, candidate)) > best_score:
            best, best_score, misses = candidate, score, 0
        else:
            misses += 1
    return best


def improve_field(test: RollingTest, rule: Rule, field: str) -> Rule:
    """Eerst een sprong, dan omhoog en omlaag lopen vanaf de beste plek."""
    rule = jump(test, rule, field)
    for step in (SEARCH_STEP_PCT, -SEARCH_STEP_PCT):
        rule = walk(test, rule, field, step)
    return rule


# ----------------------------------------------------------------- all fields


def optimise(test: RollingTest, start: Rule) -> Rule:
    """Loop langs alle velden tot een hele ronde niets verbetert."""
    rule = start
    for _ in range(SEARCH_MAX_ROUNDS):
        before = rule
        for field in SEARCH_FIELDS:
            rule = improve_field(test, rule, field)
        if rule == before:
            break
    return rule


def optimise_from(test: RollingTest, starts: list[Rule]) -> Rule:
    """Meerdere startpunten tegen een lokaal dal: de beste uitkomst wint."""
    results = [optimise(test, start) for start in starts]
    return max(results, key=lambda rule: score_of(test, rule))


# ---------------------------------------------------------------- hold-out


def without_last_windows(stocks: list[StockData], count: int = HOLDOUT_WINDOWS) -> list[StockData]:
    """De aandelen zonder de laatste `count` periodes: daarop mag de zoekactie leren."""
    cut = count * WF_TEST_DAYS
    return [StockData(s.ticker, s.closes[:-cut], s.position_eur) for s in stocks if len(s.closes) > cut]


@dataclass(frozen=True)
class Holdout:
    wins: int
    windows: int
    rule_pct: float
    hold_pct: float


def holdout_result(stocks: list[StockData], rule: Rule, count: int = HOLDOUT_WINDOWS) -> Holdout:
    """Regel tegen vasthouden op de laatste `count` periodes, samengesteld."""
    bounds = window_bounds(max(len(s.closes) for s in stocks))[-count:]
    rule_pcts = [portfolio_return(stocks, rule, start, end)[0] for start, end in bounds]
    hold_pcts = [portfolio_return(stocks, HOLD, start, end)[0] for start, end in bounds]
    return Holdout(sum(r > h for r, h in zip(rule_pcts, hold_pcts)), len(bounds), compound(rule_pcts), compound(hold_pcts))
