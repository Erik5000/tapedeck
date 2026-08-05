"""Currency conversion for values that arrive in a listing's local currency.

Market cap is the one field that needs this. Samsung's comes back as
1,615,375 (billion KRW) and Kioxia's as 29,715 (billion JPY) — rendered raw in
a $-prefixed column those read as "$1615375B", which is not a small error.
Ratios (P/E, P/S) are currency-free and need none of this.

Rates come from Yahoo under the `<CCY>=X` convention, which quotes units of
that currency per USD: JPY=X ≈ 158 means 158 JPY to the dollar. Conversion is
therefore a division. There is no fallback rate and no guess — an unavailable
rate returns None, and the cell reads n/a rather than a wrong number.
"""

USD = "USD"

# Yahoo quotes a few currencies in minor units. GBp/ZAc/ILA are the pence,
# cent and agora forms of GBP/ZAR/ILS — a market cap in GBp is 100x the GBP
# figure, so the currency has to be normalised before the rate is applied.
_MINOR_UNITS = {"GBP": ("GBP", 100.0), "GBX": ("GBP", 100.0),
                "ZAC": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def normalize(currency):
    """('GBp', 100.0) -> ('GBP', 100.0): the major currency and its divisor."""
    if not currency:
        return None, 1.0
    raw = str(currency).strip()
    if not raw:
        return None, 1.0
    # Case matters here and only here: Yahoo writes pence as "GBp" and pounds
    # as "GBP", so upper-casing first would silently multiply by 100.
    if raw in ("GBp", "GBX", "ZAc", "ILA"):
        major, divisor = _MINOR_UNITS[raw.upper()]
        return major, divisor
    return raw.upper(), 1.0


def rate_symbol(currency):
    """The Yahoo ticker carrying <currency> per USD, or None for USD itself."""
    major, _ = normalize(currency)
    if not major or major == USD:
        return None
    return f"{major}=X"


def symbols_for(currencies):
    """Every rate ticker needed for a set of currencies, deduped."""
    out = []
    for currency in currencies:
        symbol = rate_symbol(currency)
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def to_usd(value, currency, rates):
    """Convert `value` from `currency` to USD. None if it can't be done.

    `rates` maps a rate ticker ('JPY=X') to units-per-USD.
    """
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    major, divisor = normalize(currency)
    if not major:
        return None                       # unknown currency: refuse to guess
    amount /= divisor
    if major == USD:
        return amount
    rate = rates.get(f"{major}=X")
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return amount / rate
