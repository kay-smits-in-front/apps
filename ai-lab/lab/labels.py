"""What the model has to recognise. Label 1: the price is clearly lower `horizon` days later,
by more than the move that covers the costs."""


def falls_after(closes: list[float], i: int, horizon: int, min_drop_pct: float) -> int | None:
    """1 if the close `horizon` days later is at least `min_drop_pct` lower, else 0.
    None when the future is not known yet (the row can not be used)."""
    if i + horizon >= len(closes):
        return None
    return int(closes[i + horizon] / closes[i] - 1 <= -min_drop_pct / 100)
