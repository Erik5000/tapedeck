"""One confidence number per panel, 0 to 100. Pure.

Confidence is separate from the reading (oil-tracker brief §8): it says how
much of the panel stands on fresh, full, liquid data — not what the data says.
"""

STATUS_SCORE = {"ok": 1.0, "stale": 0.5, "warming": 0.5, "no_data": 0.0}


def item_score(item):
    """A leg or a crowding row. A thin venue market counts half."""
    score = STATUS_SCORE.get(item.get("status"), 0.0)
    return score * 0.5 if item.get("thin") else score


def panel_confidence(items):
    items = list(items)
    if not items:
        return None
    return int(round(100 * sum(item_score(i) for i in items) / len(items)))
