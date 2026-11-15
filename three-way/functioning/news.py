"""Nieuwskoppen per aandeel van Yahoo. Alleen de koppen: jij beoordeelt zelf wat ze betekenen."""

from functioning.constants import NEWS_ITEMS
from functioning.imports import yf


def headline(item: dict) -> dict | None:
    """Eén kop uit het antwoord van Yahoo. Yahoo kent twee vormen: plat (oud) en onder 'content' (nieuw)."""
    content = item.get("content") or item
    title = content.get("title")
    if not title:
        return None
    provider = content.get("provider")
    link = (content.get("canonicalUrl") or {}).get("url") or content.get("link") or ""
    return {"title": title, "source": provider.get("displayName", "") if isinstance(provider, dict) else content.get("publisher", ""),
            "time": str(content.get("pubDate") or content.get("providerPublishTime") or ""),
            "url": link if link.startswith("https://") else ""}


def headlines(ticker: str, fetch=None) -> list[dict]:
    """De laatste koppen van een aandeel. `fetch(ticker)` geeft de ruwe lijst (voor de test)."""
    raw = (fetch or (lambda t: yf.Ticker(t).news))(ticker) or []
    # shortcut: geen cache, elke klik vraagt Yahoo opnieuw; cachen per dag zodra dat te traag of te vaak wordt
    return [h for h in (headline(item) for item in raw) if h][:NEWS_ITEMS]
