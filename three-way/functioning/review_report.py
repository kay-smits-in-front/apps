"""De beoordeling als tekst voor de terminal."""

from functioning.constants import ACTION_LABELS

PART_NAMES = {"forest": "forest", "logistisch": "logistisch", "boosted": "boosted", "gam": "GAM",
              "nieuws": "nieuws", "intuitie": "intuïtie"}


def pct(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:+.{digits}f}%"


def eur(value: float | None) -> str:
    return "-" if value is None else f"{value:+,.0f}".replace(",", ".") + " euro"


def status_text(review: dict) -> str:
    if review["done"]:
        return f"afgerond na {review['horizon']} dagen"
    return f"lopend, {review['elapsed']} van {review['horizon']} dagen"


def names_where(row: dict, right: bool) -> str:
    return ", ".join(PART_NAMES.get(p["name"], p["name"]) for p in row["parts"] if p["right"] is right) or "-"


def best_part_alone(review: dict) -> tuple[str, float] | None:
    """Het onderdeel dat in deze run het meest had opgeleverd als het alleen had beslist."""
    totals: dict[str, list[float]] = {}
    for row in review["rows"]:
        for part in row["parts"]:
            if part["alone_pct"] is not None:
                totals.setdefault(part["name"], []).append(part["alone_pct"])
    if not totals:
        return None
    name, values = max(totals.items(), key=lambda item: sum(item[1]) / len(item[1]))
    return name, sum(values) / len(values)


def format_run(review: dict) -> str:
    header = f"=== Advies van {review['day']}: {status_text(review)} ==="
    if not review["rows"]:
        return f"{header}\n  Nog geen koersen na deze dag."
    lines = [header, f"{'Aandeel':<10}{'Advies':<10}{'Koers':>8}{'Uitkomst':>10}{'Spijt':>8}  {'Gelijk had':<34}Ongelijk"]
    for r in review["rows"]:
        lines.append(f"{r['ticker']:<10}{ACTION_LABELS[r['action']]:<10}{pct(r['pct']):>8}{pct(r['result_pct']):>10}"
                     f"{pct(r['regret_pct']):>8}  {names_where(r, True):<34}{names_where(r, False)}")
    best = review["mean_result_pct"] + review["mean_regret_pct"]
    lines.append(f"Gemiddelde uitkomst {pct(review['mean_result_pct'])}, achteraf had het {pct(best)} kunnen zijn "
                 f"(spijt {pct(review['mean_regret_pct'])}). {review['right_calls']} van {len(review['rows'])} adviezen goed.")
    if review["result_eur"] is not None:
        lines.append(f"In euro: advies {eur(review['result_eur'])}, vasthouden {eur(review['hold_eur'])}.")
    if best_part_alone(review):
        name, value = best_part_alone(review)
        lines.append(f"Had alleen {PART_NAMES.get(name, name)} beslist, dan was het {pct(value)} geweest.")
    if review["missing"]:
        lines.append(f"Geen koersen na de run voor: {', '.join(review['missing'])}.")
    return "\n".join(lines)


def format_scoreboard(board: list[dict], weights: dict[str, float]) -> str:
    """Per onderdeel over alle afgeronde runs. Pas betrouwbaar na veel runs."""
    if not board:
        return "Nog geen afgeronde run met scores per onderdeel."
    lines = [f"{'Onderdeel':<12}{'Gewicht':>8}{'Meningen':>10}{'Gelijk':>8}{'Gelijk %':>10}{'Alleen beslist':>16}"]
    for part in sorted(board, key=lambda p: -weights.get(p["name"], 0)):
        rate = "-" if part["hit_rate"] is None else f"{part['hit_rate']:.0%}"
        lines.append(f"{PART_NAMES.get(part['name'], part['name']):<12}{weights.get(part['name'], 0):>8.0%}"
                     f"{part['calls']:>10}{part['right']:>8}{rate:>10}{pct(part['mean_alone_pct']):>16}")
    return "\n".join(lines)
