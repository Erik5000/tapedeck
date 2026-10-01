"""The four Situation alerts. Pure.

An alert whose inputs are missing or warming up is "disabled" and says why.
It never fires on part of its inputs. Fired alerts come first.
"""

Z_ON = 1.0                 # brent z, be10 change z
GAP_Z = -1.0               # be_gap z
FUNDING_Z = 1.0            # leveraged oil rally
CROWD_FUNDING_Z = 2.0      # crowded duration, either sign
OI_RISE_PCT = 10.0
DURATION_MARKETS = ("para:10Y", "mkts:USBOND")
LEVERAGE_NOTE = ("Reads perp leverage, not the futures curve: "
                 "the venue lists no contract months.")
_ORDER = {"fired": 0, "quiet": 1, "disabled": 2}


def _alert(alert_id, label, state, detail, note=None):
    return {"id": alert_id, "label": label, "state": state, "detail": detail, "note": note}


def _positioning_gap(row):
    """Why a crowding row cannot feed an alert yet, or None when it can."""
    if row is None or row["status"] == "no_data":
        return "no venue data"
    if row["oi_chg_20d"] is None:
        return f"needs OI history ({row['oi_days']}/{row['oi_need']} days)"
    if row["funding_z"] is None:
        return f"needs funding history ({row['funding_days']}/{row['funding_need']} days)"
    return None


def build_alerts(legs, crowding):
    by_leg = {leg["id"]: leg for leg in legs}
    by_market = {row["market"]: row for row in crowding}

    def get(leg_id, key):
        return (by_leg.get(leg_id) or {}).get(key)

    out = []
    brent_z, gap_z = get("brent", "z"), get("be_gap", "z")

    label = "Bonds ignore oil"
    if brent_z is None or gap_z is None:
        out.append(_alert("bonds_ignore_oil", label, "disabled",
                          "needs Brent z and breakeven gap z"))
    else:
        fired = brent_z > Z_ON and gap_z < GAP_Z
        out.append(_alert("bonds_ignore_oil", label, "fired" if fired else "quiet",
                          f"Brent z {brent_z:+.1f} · BE gap z {gap_z:+.1f}"))

    label = "Inflation scare without oil"
    be_chg_z, brent_chg = get("be10", "chg_z"), get("brent", "chg20")
    if be_chg_z is None or brent_chg is None:
        out.append(_alert("inflation_no_oil", label, "disabled",
                          "needs BE 10Y change z and Brent 20-day return"))
    else:
        fired = be_chg_z > Z_ON and brent_chg <= 0
        out.append(_alert("inflation_no_oil", label, "fired" if fired else "quiet",
                          f"BE 10Y Δ20d z {be_chg_z:+.1f} · Brent {brent_chg:+.1f}%/20d"))

    label = "Leveraged oil rally"
    row = by_market.get("xyz:BRENTOIL")
    why = _positioning_gap(row) or (None if brent_z is not None else "needs Brent z")
    if why:
        out.append(_alert("leveraged_oil_rally", label, "disabled", why, LEVERAGE_NOTE))
    else:
        fired = (brent_z > Z_ON and row["funding_z"] > FUNDING_Z
                 and row["oi_chg_20d"] > OI_RISE_PCT)
        out.append(_alert("leveraged_oil_rally", label, "fired" if fired else "quiet",
                          f"Brent z {brent_z:+.1f} · funding z {row['funding_z']:+.1f} · "
                          f"OI {row['oi_chg_20d']:+.0f}%/20d", LEVERAGE_NOTE))

    label = "Crowded duration"
    ready = [by_market[m] for m in DURATION_MARKETS
             if _positioning_gap(by_market.get(m)) is None]
    if not ready:
        out.append(_alert("crowded_duration", label, "disabled",
                          _positioning_gap(by_market.get(DURATION_MARKETS[0]))))
    else:
        hits = [r for r in ready
                if abs(r["funding_z"]) > CROWD_FUNDING_Z and r["oi_chg_20d"] > OI_RISE_PCT]
        shown = hits or ready
        detail = " · ".join(
            f"{r['market']} funding z {r['funding_z']:+.1f}, OI {r['oi_chg_20d']:+.0f}%"
            + (f", {r['side']}" if r in hits and r["side"] else "")
            for r in shown)
        out.append(_alert("crowded_duration", label, "fired" if hits else "quiet", detail))

    return sorted(out, key=lambda a: _ORDER[a["state"]])
