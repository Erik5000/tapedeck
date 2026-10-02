"""Panel B: oil against rates. Pure.

be_beta: how many bp the 5Y breakeven moves per 1% Brent move, over 60 bars.
be_gap: the 20-bar breakeven move that the beta did not predict. A negative
gap while Brent rallies means bonds do not price the oil move.
"""

import pandas as pd

from .legs import is_thin, make_leg
from .stats import clean

BETA_BARS = 60
GAP_BARS = 20


def compound(returns, bars=GAP_BARS):
    """Rolling ``bars``-bar compounded % return from daily % returns, or None."""
    r = clean(returns)
    if r is None:
        return None
    level = (1 + r / 100).cumprod()
    out = ((level / level.shift(bars) - 1) * 100).dropna()
    return out if len(out) else None


def be_beta_series(be5, brent_ret, bars=BETA_BARS):
    """Rolling OLS beta of daily Δbreakeven (bp) on daily Brent return (%)."""
    be, r = clean(be5), clean(brent_ret)
    if be is None or r is None:
        return None
    frame = pd.concat([be.diff() * 100, r], axis=1, join="inner").dropna()
    if len(frame) < bars:
        return None
    frame.columns = ["dbe", "ret"]
    beta = frame["dbe"].rolling(bars).cov(frame["ret"]) / frame["ret"].rolling(bars).var()
    return clean(beta)


def be_gap_series(be5, brent_ret, beta, bars=GAP_BARS):
    """20-bar Δbreakeven (bp) minus beta × 20-bar Brent return. Each day uses
    the beta of that day."""
    be, b, r20 = clean(be5), clean(beta), compound(brent_ret, bars)
    if be is None or b is None or r20 is None:
        return None
    frame = pd.concat([(be - be.shift(bars)) * 100, b, r20], axis=1, join="inner").dropna()
    if not len(frame):
        return None
    frame.columns = ["dbe20", "beta", "r20"]
    return clean(frame["dbe20"] - frame["beta"] * frame["r20"])


def build_oil_legs(prep, src, today):
    """Panel B legs, in display order. ``prep`` comes from series.prepare."""
    fred, ctx, closes = src.get("fred") or {}, src.get("ctx") or {}, src.get("closes") or {}
    brent = prep["brent"]
    brent_thin = is_thin(ctx.get("xyz:BRENTOIL"))

    def last(s):
        return None if s is None else float(s.iloc[-1])

    r20 = compound(brent["returns"])
    out = [make_leg("brent", "Brent", "oil", "$", "stronger oil rally", brent["level"], today,
                    src=brent["src"], chg20=last(r20), chg_unit="%", z_series=r20,
                    thin=brent_thin)]

    wti = prep["wti"]
    wti_r20 = compound(None if wti is None else wti.pct_change().dropna() * 100)
    out.append(make_leg("wti", "WTI", "oil", "$", "stronger oil rally", wti, today,
                        src="V" if wti is not None else None, chg20=last(wti_r20),
                        chg_unit="%", z_series=wti_r20, thin=is_thin(ctx.get("xyz:CL"))))

    b_v, w_v = clean(closes.get("xyz:BRENTOIL")), clean(closes.get("xyz:CL"))
    spread = None
    if b_v is not None and w_v is not None:
        spread = clean((b_v - w_v).dropna())
    out.append(make_leg("brent_wti", "Brent−WTI", "oil", "$", "wider Brent premium", spread,
                        today, src="V" if spread is not None else None, chg_mult=1.0,
                        chg_unit="$", thin=brent_thin or is_thin(ctx.get("xyz:CL"))))

    be5 = fred.get("T5YIE")
    beta = be_beta_series(be5, brent["returns"])
    out.append(make_leg("be_beta", "BE beta", "oil", "bp/1%", "more pass-through", beta, today,
                        src="V+F" if beta is not None else None, chg20=None, with_z=False,
                        thin=brent_thin))
    gap = be_gap_series(be5, brent["returns"], beta)
    out.append(make_leg("be_gap", "BE gap", "oil", "bp", "breakevens ahead of oil", gap, today,
                        src="V+F" if gap is not None else None, chg20=None, center=False,
                        thin=brent_thin))
    return out
