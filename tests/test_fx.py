"""Currency conversion for market caps quoted in a listing's own currency.

Samsung's comes back as 1,615,375 (billion KRW) and Kioxia's as 29,715 (billion
JPY). Rendered raw in a $-prefixed column those read as "$1615375B".
"""

import pytest

from tapedeck import fx

RATES = {"JPY=X": 158.0, "KRW=X": 1425.0, "CNY=X": 6.8, "GBP=X": 0.74}


# ---------- rate tickers ----------

def test_usd_needs_no_rate():
    assert fx.rate_symbol("USD") is None
    assert fx.rate_symbol(None) is None
    assert fx.rate_symbol("") is None


def test_rate_symbol_follows_yahoos_convention():
    assert fx.rate_symbol("JPY") == "JPY=X"
    assert fx.rate_symbol("krw") == "KRW=X"


def test_symbols_for_dedupes_and_skips_usd():
    assert fx.symbols_for(["JPY", "USD", "JPY", None, "KRW"]) == ["JPY=X", "KRW=X"]


# ---------- conversion ----------

def test_converts_a_local_currency_cap_to_usd():
    """Samsung: 1.615e15 KRW at 1425 KRW/USD is about $1.13T, not $1.6 quadrillion."""
    usd = fx.to_usd(1_615_375e9, "KRW", RATES)
    assert usd == pytest.approx(1.615375e15 / 1425.0)
    assert 1.0e12 < usd < 1.3e12


def test_usd_values_pass_through_untouched():
    assert fx.to_usd(4.7e12, "USD", RATES) == pytest.approx(4.7e12)


def test_minor_units_are_normalised_before_the_rate():
    """Yahoo quotes some London listings in pence. Treating GBp as GBP would
    overstate the cap by 100x — and the case is the only thing distinguishing
    them, so this must not upper-case first."""
    assert fx.to_usd(100.0, "GBp", RATES) == pytest.approx(1.0 / 0.74)
    assert fx.to_usd(100.0, "GBP", RATES) == pytest.approx(100.0 / 0.74)


# ---------- refusing to guess ----------

def test_missing_rate_returns_none_rather_than_the_raw_number():
    """n/a beats a number that is off by three orders of magnitude."""
    assert fx.to_usd(1e12, "KRW", {}) is None


def test_unknown_currency_returns_none():
    assert fx.to_usd(1e12, None, RATES) is None
    assert fx.to_usd(1e12, "", RATES) is None


def test_nonsense_inputs_return_none():
    assert fx.to_usd(None, "JPY", RATES) is None
    assert fx.to_usd("not a number", "JPY", RATES) is None
    assert fx.to_usd(1e12, "JPY", {"JPY=X": "n/a"}) is None
    assert fx.to_usd(1e12, "JPY", {"JPY=X": 0}) is None      # would divide by zero
    assert fx.to_usd(1e12, "JPY", {"JPY=X": -5}) is None
