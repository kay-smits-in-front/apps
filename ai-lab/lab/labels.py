"""What the model has to recognise. Label 1: the price is clearly lower `horizon` days later,
by more than the move that covers the costs."""


def falls_after(closes: list[float], i: int, horizon: int, min_drop_pct: float) -> int | None:
    """1 if the close `horizon` days later is at least `min_drop_pct` lower, else 0.
    None when the future is not known yet (the row can not be used)."""
    if i + horizon >= len(closes):
        return None
    return int(closes[i + horizon] / closes[i] - 1 <= -min_drop_pct / 100)


def direction_after(closes: list[float], i: int, horizon: int, min_move_pct: float) -> int | None:
    """0 als de koers `horizon` dagen later minstens `min_move_pct` lager is, 2 als minstens
    zoveel hoger, anders 1 (geen beweging die de kosten dekt). None als de toekomst nog onbekend is."""
    if i + horizon >= len(closes):
        return None
    move = closes[i + horizon] / closes[i] - 1
    return 0 if move <= -min_move_pct / 100 else 2 if move >= min_move_pct / 100 else 1
