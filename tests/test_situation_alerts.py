import pytest

from tapedeck.situation import alerts


def leg(leg_id, **kw):
    base = {"id": leg_id, "z": None, "chg20": None}
    base.update(kw)
    return base


def crowd(market, funding_z=None, oi_chg=None, oi_days=20, side=None, status=None):
    if status is None:
        status = "ok" if funding_z is not None and oi_chg is not None else "warming"
    return {"market": market, "funding_z": funding_z, "oi_chg_20d": oi_chg, "oi_days": oi_days,
            "oi_need": 20, "funding_days": 90, "funding_need": 60, "side": side,
            "status": status}


def by_id(legs, crowding=()):
    return {a["id"]: a for a in alerts.build_alerts(legs, list(crowding))}


# ---------- bonds ignore oil ----------

def test_bonds_ignore_oil_fires():
    a = by_id([leg("brent", z=1.5), leg("be_gap", z=-1.2)])["bonds_ignore_oil"]
    assert a["state"] == "fired" and "Brent z +1.5" in a["detail"]


def test_bonds_ignore_oil_quiet_when_breakevens_follow():
    assert by_id([leg("brent", z=1.5), leg("be_gap", z=-0.5)])["bonds_ignore_oil"]["state"] == "quiet"


def test_bonds_ignore_oil_disabled_without_the_gap():
    a = by_id([leg("brent", z=1.5), leg("be_gap")])["bonds_ignore_oil"]
    assert a["state"] == "disabled" and "gap" in a["detail"]


# ---------- inflation scare without oil ----------

def test_inflation_scare_without_oil_fires_when_brent_is_flat():
    legs = [leg("be10", chg_z=1.4), leg("brent", z=0.1, chg20=0.0)]
    assert by_id(legs)["inflation_no_oil"]["state"] == "fired"


def test_inflation_scare_quiet_when_oil_is_up():
    legs = [leg("be10", chg_z=1.4), leg("brent", z=0.1, chg20=3.0)]
    assert by_id(legs)["inflation_no_oil"]["state"] == "quiet"


def test_inflation_scare_disabled_without_brent():
    assert by_id([leg("be10", chg_z=1.4)])["inflation_no_oil"]["state"] == "disabled"


# ---------- leveraged oil rally ----------

def test_leveraged_oil_rally_fires_and_carries_its_note():
    a = by_id([leg("brent", z=1.5)], [crowd("xyz:BRENTOIL", 1.2, 15.0)])["leveraged_oil_rally"]
    assert a["state"] == "fired" and a["note"] == alerts.LEVERAGE_NOTE


def test_leveraged_oil_rally_quiet_when_oi_falls():
    a = by_id([leg("brent", z=1.5)], [crowd("xyz:BRENTOIL", 1.2, -5.0)])["leveraged_oil_rally"]
    assert a["state"] == "quiet"


def test_leveraged_oil_rally_disabled_while_oi_history_grows():
    a = by_id([leg("brent", z=1.5)],
              [crowd("xyz:BRENTOIL", 1.2, None, oi_days=3)])["leveraged_oil_rally"]
    assert a["state"] == "disabled" and a["detail"] == "needs OI history (3/20 days)"


def test_leveraged_oil_rally_never_fires_on_funding_alone():
    a = by_id([leg("brent", z=3.0)], [crowd("xyz:BRENTOIL", 5.0, None)])["leveraged_oil_rally"]
    assert a["state"] == "disabled"


# ---------- crowded duration ----------

def test_crowded_duration_fires_with_the_side():
    a = by_id([], [crowd("para:10Y", 2.5, 12.0, side="short duration crowded"),
                   crowd("mkts:USBOND", 0.2, 1.0)])["crowded_duration"]
    assert a["state"] == "fired"
    assert "para:10Y" in a["detail"] and "short duration crowded" in a["detail"]
    assert "USBOND" not in a["detail"]


def test_crowded_duration_reads_negative_funding_too():
    a = by_id([], [crowd("mkts:USBOND", -2.5, 12.0, side="short duration crowded")])
    assert a["crowded_duration"]["state"] == "fired"


def test_crowded_duration_quiet():
    a = by_id([], [crowd("para:10Y", 1.0, 12.0)])["crowded_duration"]
    assert a["state"] == "quiet"


def test_crowded_duration_disabled_without_oi_history():
    a = by_id([], [crowd("para:10Y", 2.5, None, oi_days=5)])["crowded_duration"]
    assert a["state"] == "disabled" and a["detail"] == "needs OI history (5/20 days)"


def test_crowded_duration_disabled_without_venue_data():
    assert by_id([], [])["crowded_duration"]["detail"] == "no venue data"


# ---------- order ----------

def test_fired_alerts_come_first():
    out = alerts.build_alerts([leg("brent", z=1.5), leg("be_gap", z=-1.2)], [])
    states = [a["state"] for a in out]
    assert states == sorted(states, key=lambda s: {"fired": 0, "quiet": 1, "disabled": 2}[s])
    assert out[0]["id"] == "bonds_ignore_oil" and len(out) == 4
