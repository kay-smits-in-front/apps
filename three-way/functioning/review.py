"""De beoordeling van het advies achteraf. Het systeem leert van zijn eigen uitkomsten.

Na het advies zit het systeem 'in' het aandeel (houden terwijl belegd, of terugkopen) of 'eruit' (verkopen,
of in cash blijven). Na REVIEW_HORIZON_DAYS handelsdagen telt de koersverandering van het aandeel:
- in het aandeel: winst is positief, verlies negatief
- eruit: verlies (vermeden) is positief, winst (gemist) negatief
Daarnaast kijkt het per onderdeel (model, nieuws, intuïtie) of de score de goede kant op wees, wat dat onderdeel
bijdroeg aan de totaalscore en wat de uitkomst was geweest als alleen dat onderdeel had beslist."""

from functioning.constants import REVIEW_HORIZON_DAYS, REVIEW_NEUTRAL, TRANSACTION_COST_EUR

# ------------------------------------------------------------- one stock


def outcome_pct(days: list[str], closes: list[float], run_day: str, start_price: float,
                horizon: int = REVIEW_HORIZON_DAYS) -> tuple[float, int] | None:
    """Koersverandering in % sinds de koers van de run, na `horizon` handelsdagen of tot nu toe,
    en hoeveel handelsdagen er verstreken zijn. None als er nog geen dag na de run is."""
    after = [i for i, day in enumerate(days) if day > run_day]
    if not after or start_price <= 0:
        return None
    elapsed = min(horizon, len(after))
    return (closes[after[elapsed - 1]] / start_price - 1) * 100, elapsed


def stays_in(action: str, invested: bool) -> bool:
    """Zit het systeem na dit advies in het aandeel?"""
    return action == "buy" or (action == "hold" and invested)


def result_pct(in_stock: bool, pct: float) -> float:
    """Uitkomst van het advies in %: meebewegen als je erin zit, tegenovergesteld als je eruit bent."""
    return pct if in_stock else -pct


def regret_pct(pct: float, result: float) -> float:
    """Hoeveel beter het achteraf had gekund: de beste keuze had altijd |koersverandering| opgeleverd."""
    return abs(pct) - result


def stance(score: float | None) -> int:
    """Wat een onderdeel vindt: +1 erin (omhoog), -1 eruit (omlaag), 0 geen mening."""
    if score is None or abs(score) < REVIEW_NEUTRAL:
        return 0
    return 1 if score > 0 else -1


def part_review(name: str, score: float | None, weight: float, pct: float) -> dict:
    """Eén onderdeel bij één aandeel: gelijk gehad, bijdrage aan de totaalscore, uitkomst als het alleen had beslist."""
    opinion = stance(score)
    right = None if opinion == 0 or pct == 0 else (opinion > 0) == (pct > 0)
    return {"name": name, "score": score, "contribution": None if score is None else round(weight * score, 3),
            "right": right, "alone_pct": None if opinion == 0 else result_pct(opinion > 0, pct)}


def review_row(row: dict, weights: dict | None, prices: dict, run_day: str, horizon: int) -> dict | None:
    """Eén aandeel van een run beoordeeld. None als er geen koersen na de run zijn."""
    entry = prices.get(row["ticker"])
    found = outcome_pct(entry["days"], entry["closes"], run_day, row["price"], horizon) if entry else None
    if found is None:
        return None
    pct, elapsed = found
    inside = stays_in(row["action"], row["invested"])
    result = result_pct(inside, pct)
    position = row.get("position_eur") or 0.0
    trade_cost = TRANSACTION_COST_EUR if row["action"] in ("buy", "sell") else 0.0
    parts = [part_review(name, score, (weights or {}).get(name, 0.0), pct) for name, score in (row.get("parts") or {}).items()]
    return {"ticker": row["ticker"], "action": row["action"], "invested": row["invested"], "pct": round(pct, 2),
            "elapsed": elapsed, "result_pct": round(result, 2), "regret_pct": round(regret_pct(pct, result), 2),
            "position_eur": position, "result_eur": round(position * result / 100 - trade_cost, 2) if position else None,
            "hold_eur": round(position * pct / 100, 2) if row["invested"] and position else None, "parts": parts}


# ------------------------------------------------------------------ runs


def review_run(entry: dict, prices: dict, horizon: int = REVIEW_HORIZON_DAYS) -> dict:
    """Een hele run beoordeeld, met totalen. `done` is pas waar als alle drie de dagen verstreken zijn."""
    rows = [r for r in (review_row(row, entry.get("weights"), prices, entry["day"], horizon) for row in entry["rows"]) if r]
    elapsed = min((r["elapsed"] for r in rows), default=0)
    eur = [r["result_eur"] for r in rows if r["result_eur"] is not None]
    held = [r["hold_eur"] for r in rows if r["hold_eur"] is not None]
    return {"day": entry["day"], "news": entry.get("news"), "intuition": entry.get("intuition"), "elapsed": elapsed,
            "horizon": horizon, "done": bool(rows) and elapsed >= horizon, "rows": rows,
            "missing": [row["ticker"] for row in entry["rows"] if row["ticker"] not in {r["ticker"] for r in rows}],
            "mean_result_pct": round(sum(r["result_pct"] for r in rows) / len(rows), 2) if rows else None,
            "mean_regret_pct": round(sum(r["regret_pct"] for r in rows) / len(rows), 2) if rows else None,
            "right_calls": sum(1 for r in rows if r["result_pct"] > 0), "result_eur": round(sum(eur), 2) if eur else None,
            "hold_eur": round(sum(held), 2) if held else None}


def part_scoreboard(reviews: list[dict]) -> list[dict]:
    """Per onderdeel over alle afgeronde runs: hoe vaak gelijk, en wat het alleen had opgeleverd."""
    names: dict[str, dict] = {}
    for review in (r for r in reviews if r["done"]):
        for row in review["rows"]:
            for part in row["parts"]:
                total = names.setdefault(part["name"], {"name": part["name"], "calls": 0, "right": 0, "alone": []})
                if part["right"] is not None:
                    total["calls"] += 1
                    total["right"] += int(part["right"])
                if part["alone_pct"] is not None:
                    total["alone"].append(part["alone_pct"])
    return [{"name": t["name"], "calls": t["calls"], "right": t["right"],
             "hit_rate": round(t["right"] / t["calls"], 3) if t["calls"] else None,
             "mean_alone_pct": round(sum(t["alone"]) / len(t["alone"]), 2) if t["alone"] else None} for t in names.values()]


# ---------------------------------------------------------- the old checks


def entries_from_checks(checks: list, cash_before) -> list[dict]:
    """Runs uit het oudere logboek (checks.json) als log-regels, voor de dagen dat het advies-log er nog niet was.
    Er zijn dan geen scores per onderdeel, alleen koers en actie. `cash_before(day)` geeft de aandelen in cash."""
    entries = []
    for check in checks:
        cash = cash_before(check.day)
        entries.append({"day": check.day.isoformat(), "news": check.news, "intuition": check.intuition, "weights": None,
                        "rows": [{"ticker": c.ticker, "price": c.price, "position_eur": 0.0, "invested": c.ticker not in cash,
                                  "parts": None, "score": None, "action": c.action, "reason": c.reason} for c in check.calls]})
    return entries


def merge_runs(log_entries: list[dict], check_entries: list[dict]) -> list[dict]:
    """Alle runs, oudste eerst. Voor een dag met beide gaat het advies-log voor (dat heeft meer gegevens)."""
    logged = {e["day"] for e in log_entries}
    return sorted(log_entries + [e for e in check_entries if e["day"] not in logged], key=lambda e: e["day"])


def review_all(entries: list[dict], prices: dict) -> list[dict]:
    """Alle runs beoordeeld, nieuwste eerst."""
    return [review_run(e, prices) for e in sorted(entries, key=lambda e: e["day"], reverse=True)]
