"""Het logboek van het advies: elke run volledig bewaard, zodat het achteraf beoordeeld kan worden.

Per dag een regel met de ingevoerde scores, de gewichten en per aandeel: koers, positie, score per onderdeel,
totaalscore en actie. Opnieuw draaien op dezelfde dag vervangt die dag. Het bestand blijft lokaal (gitignored)."""

from functioning.constants import ADVICE_LOG_FILE, ADVICE_WEIGHTS
from functioning.imports import date, json
from functioning.storage import write_json


def entry_of(day: date, rows, news: float, intuition: float, top: list[str]) -> dict:
    """Eén run als gewone gegevens. `rows` zijn de AdviceRow's van het advies."""
    return {
        "day": day.isoformat(), "news": news, "intuition": intuition, "weights": dict(ADVICE_WEIGHTS),
        "top_facets": top,
        "rows": [{"ticker": r.ticker, "price": r.price, "position_eur": round(r.position_eur, 2), "invested": r.invested,
                  "parts": r.parts, "score": round(r.score, 3), "action": r.decision.action.value,
                  "reason": r.decision.reason} for r in rows],
    }


class AdviceLog:
    def __init__(self, path=ADVICE_LOG_FILE):
        self.path = path

    def load(self) -> list[dict]:
        """Alle runs, oudste eerst."""
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def add(self, entry: dict) -> None:
        """Bewaar een run. Een run van dezelfde dag wordt vervangen."""
        others = [e for e in self.load() if e["day"] != entry["day"]]
        write_json(self.path, sorted(others + [entry], key=lambda e: e["day"]))
