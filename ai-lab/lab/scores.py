"""Alle factoren op dezelfde schaal als het dashboard: -5 tot +5.
Positief: reden om te houden of te kopen. Negatief: reden om te verkopen."""

SCORE_MAX = 5.0


def to_score(value: float, full_scale: float) -> float:
    """`full_scale` is de waarde die precies +5 geeft. Een negatieve `full_scale`
    draait het teken om. Waarden daarbuiten worden afgekapt."""
    return max(-SCORE_MAX, min(SCORE_MAX, value / full_scale * SCORE_MAX))


def trend_score(dist_ma20: float) -> float:
    """Boven het gemiddelde van 20 dagen is positief. +10% geeft +5."""
    return to_score(dist_ma20, 0.10)


def cumulative_score(dist_all: float) -> float:
    """Duur is negatief, goedkoop is positief. 30% onder het gemiddelde van alle koersen geeft +5."""
    return to_score(dist_all, -0.30)


def rsi_score(rsi: float) -> float:
    """Oververkocht is positief, overgekocht is negatief. RSI 30 geeft +5, RSI 70 geeft -5."""
    return to_score(rsi - 50, -20)


def volume_score(volume_ratio: float, day_change: float) -> float:
    """Een volumepiek telt mee in de richting van de dag. 3x normaal geeft ±5, normaal volume geeft 0."""
    spike = to_score(max(volume_ratio - 1, 0.0), 2.0)
    return spike if day_change >= 0 else -spike


def week_score(change_5: float) -> float:
    """Stijging over vijf dagen is positief. +10% geeft +5."""
    return to_score(change_5, 0.10)


def depth_score(drop_from_high: float) -> float:
    """Ver onder de top van de laatste 60 dagen is goedkoop, dus positief. -40% geeft +5."""
    return to_score(drop_from_high, -0.40)


def direction_score(p_fall: float, p_rise: float, full_scale: float) -> float:
    """Kans op stijging min kans op daling als score. Een verschil van `full_scale` geeft +5."""
    return to_score(p_rise - p_fall, full_scale)
