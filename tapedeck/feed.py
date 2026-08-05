"""Machine-readable feed shaping (--json stdout + output/tapedeck-latest.json).

Pure dict transforms — no IO, no network. The feed is the stable contract
external consumers (e.g. a morning-brief pipeline) read; new keys are added,
existing keys never repurposed.
"""


def slim_rows(rows):
    keep = ("ticker", "name", "group", "price", "pct_1d", "pct_ytd", "pct_off_high",
            "rs_1m", "rs_rank", "pe", "ps", "market_cap", "earnings_date", "gap_pct",
            "tv_symbol")
    out = []
    for r in rows:
        slim = {k: r.get(k) for k in keep}
        slim["sma_above"] = {w: s["above"] for w, s in (r.get("sma") or {}).items()}
        # field -> the reference symbol it was taken from. A consumer comparing
        # rows needs to know that SMSN's market cap describes 005930.KS while
        # its price describes the perp; absent or {} means everything is native.
        if r.get("borrowed"):
            slim["borrowed"] = r["borrowed"]
        if r.get("position"):
            slim["position"] = r["position"]
        out.append(slim)
    return out


def slim_cockpit(cockpit, fresh):
    """Cockpit parse dict + freshness ages merged into one block; None-safe."""
    if not cockpit:
        return None
    out = dict(cockpit)
    out["age_days"] = (fresh or {}).get("age_days")
    out["triad_age_days"] = (fresh or {}).get("triad_age_days")
    return out


def build_feed(rendered_lists, today=None, data_date=None):
    return {"date": today.isoformat() if today else None,
            "data_date": data_date,
            "lists": [{
                "name": wl["name"], "title": wl["title"], "benchmark": wl["benchmark"],
                "rows": slim_rows(wl["rows"]), "summary": wl.get("summary"),
                "alerts": wl.get("alerts"), "diff": wl.get("diff"),
                "baskets": wl.get("baskets") or [],
                "cockpit": slim_cockpit(wl.get("cockpit"), wl.get("cockpit_fresh")),
            } for wl in rendered_lists]}
