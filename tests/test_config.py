from pathlib import Path

import pytest

from tapedeck import config

ROOT = Path(__file__).resolve().parents[1]


def write_yaml(tmp_path, text):
    path = tmp_path / "portfolio.yaml"
    path.write_text(text)
    return path


def test_load_normalizes_holdings(tmp_path):
    path = write_yaml(tmp_path, """
holdings:
  - ticker: nvda
    name: NVIDIA
    shares: 10
    cost_basis: 118.5
  - ticker: IREN
""")
    cfg = config.load_config(path)
    assert cfg["benchmark"] == "SPY"
    nvda, iren = cfg["holdings"]
    assert nvda["ticker"] == "NVDA"
    assert nvda["shares"] == 10.0
    assert nvda["cost_basis"] == 118.5
    assert iren["name"] is None
    assert iren["shares"] is None
    assert iren["tv_symbol"] is None


def test_load_tv_symbol_passthrough(tmp_path):
    path = write_yaml(tmp_path, "holdings:\n  - ticker: SPY\n    tv_symbol: AMEX:SPY\n")
    assert config.load_config(path)["holdings"][0]["tv_symbol"] == "AMEX:SPY"


def test_load_watchlists_directory(tmp_path):
    (tmp_path / "ai-power.yaml").write_text("title: AI Power Trade\nholdings:\n  - ticker: NVDA\n")
    (tmp_path / "my-semis.yaml").write_text("benchmark: QQQ\nholdings:\n  - ticker: AMD\n")
    (tmp_path / "_template.yaml").write_text("holdings:\n  - ticker: SKIP\n")
    lists = config.load_watchlists(tmp_path)
    assert [w["name"] for w in lists] == ["ai-power", "my-semis"]
    assert lists[0]["title"] == "AI Power Trade"
    assert lists[1]["title"] == "My Semis"  # derived from filename
    assert lists[1]["benchmark"] == "QQQ"
    assert lists[0]["holdings"][0]["ticker"] == "NVDA"


def test_load_watchlists_respects_order_field(tmp_path):
    (tmp_path / "aaa.yaml").write_text("order: 2\nholdings:\n  - ticker: AMD\n")
    (tmp_path / "zzz.yaml").write_text("order: 1\nholdings:\n  - ticker: NVDA\n")
    (tmp_path / "mmm.yaml").write_text("holdings:\n  - ticker: MU\n")  # no order → last
    lists = config.load_watchlists(tmp_path)
    assert [w["name"] for w in lists] == ["zzz", "aaa", "mmm"]


def test_load_watchlists_empty_dir_rejected(tmp_path):
    import pytest as _pytest
    with _pytest.raises(ValueError, match="[Nn]o watchlists"):
        config.load_watchlists(tmp_path)


def test_new_watchlist_creates_loadable_template(tmp_path):
    path = config.new_watchlist(tmp_path, "My Semis")
    assert path.name == "my-semis.yaml"
    cfg = config.load_config(path)  # template must be valid straight away
    assert cfg["title"] == "My Semis"
    assert cfg["holdings"][0]["ticker"] == "NVDA"


def test_new_watchlist_refuses_existing(tmp_path):
    config.new_watchlist(tmp_path, "semis")
    with pytest.raises(ValueError, match="exists"):
        config.new_watchlist(tmp_path, "semis")


def test_new_watchlist_rejects_bad_name(tmp_path):
    with pytest.raises(ValueError, match="name"):
        config.new_watchlist(tmp_path, "../evil")


def test_seed_watchlists_copies_examples_once(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "starter.yaml").write_text("holdings:\n  - ticker: SPY\n")
    target = tmp_path / "watchlists"
    assert config.seed_watchlists(target, examples) == ["starter"]
    assert (target / "starter.yaml").exists()
    assert config.seed_watchlists(target, examples) == []  # already populated → no-op


def test_cockpit_and_anti_basket_default_none(tmp_path):
    path = write_yaml(tmp_path, "holdings:\n  - ticker: AMD\n")
    cfg = config.load_config(path)
    assert cfg["cockpit"] is None
    assert cfg["anti_basket"] is None


def test_cockpit_and_anti_basket_passthrough(tmp_path):
    path = write_yaml(tmp_path, """
cockpit: /some/vault dir/COCKPIT.md
anti_basket: situational-awareness
holdings:
  - ticker: AMD
""")
    cfg = config.load_config(path)
    assert cfg["cockpit"] == "/some/vault dir/COCKPIT.md"
    assert cfg["anti_basket"] == "situational-awareness"


def test_load_watchlists_passes_cockpit_keys(tmp_path):
    (tmp_path / "book.yaml").write_text(
        "cockpit: /some/vault dir/COCKPIT.md\nanti_basket: pulse\nholdings:\n  - ticker: AMD\n")
    (tmp_path / "pulse.yaml").write_text("holdings:\n  - ticker: NVDA\n")
    lists = {w["name"]: w for w in config.load_watchlists(tmp_path)}
    assert lists["book"]["cockpit"] == "/some/vault dir/COCKPIT.md"
    assert lists["book"]["anti_basket"] == "pulse"
    assert lists["pulse"]["cockpit"] is None
    assert lists["pulse"]["anti_basket"] is None


def test_load_custom_benchmark(tmp_path):
    path = write_yaml(tmp_path, "benchmark: qqq\nholdings:\n  - ticker: AMD\n")
    assert config.load_config(path)["benchmark"] == "QQQ"


def test_duplicate_ticker_rejected(tmp_path):
    path = write_yaml(tmp_path, "holdings:\n  - ticker: AMD\n  - ticker: amd\n")
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        config.load_config(path)


def test_missing_ticker_rejected(tmp_path):
    path = write_yaml(tmp_path, "holdings:\n  - name: no ticker here\n")
    with pytest.raises(ValueError, match="ticker"):
        config.load_config(path)


def test_empty_holdings_rejected(tmp_path):
    path = write_yaml(tmp_path, "holdings: []\n")
    with pytest.raises(ValueError, match="holdings"):
        config.load_config(path)


def test_vwap_keys_default_to_none_and_2pct(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("holdings:\n  - ticker: NVDA\n")
    cfg = config.load_config(p)
    assert cfg["vwap"] is None
    assert cfg["vwap_alert_pct"] == 2.0


def test_vwap_keys_parsed(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("vwap: /tmp/vwap-latest.json\nvwap_alert_pct: 1.5\n"
                 "holdings:\n  - ticker: NVDA\n")
    cfg = config.load_config(p)
    assert cfg["vwap"] == "/tmp/vwap-latest.json"
    assert cfg["vwap_alert_pct"] == 1.5


def test_vwap_keys_reach_watchlists(tmp_path):
    (tmp_path / "a.yaml").write_text("vwap: /tmp/v.json\nvwap_alert_pct: 3\n"
                                     "holdings:\n  - ticker: NVDA\n")
    wl = config.load_watchlists(tmp_path)[0]
    assert wl["vwap"] == "/tmp/v.json"
    assert wl["vwap_alert_pct"] == 3.0


def test_vwap_alert_pct_zero_is_preserved(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("vwap_alert_pct: 0\nholdings:\n  - ticker: NVDA\n")
    cfg = config.load_config(p)
    assert cfg["vwap_alert_pct"] == 0.0


def test_vwap_alert_pct_explicit_null_defaults_to_2pct(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("vwap_alert_pct:\nholdings:\n  - ticker: NVDA\n")
    cfg = config.load_config(p)
    assert cfg["vwap_alert_pct"] == 2.0


def test_vwap_alert_pct_negative_rejected(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("vwap_alert_pct: -3\nholdings:\n  - ticker: NVDA\n")
    with pytest.raises(ValueError, match="vwap_alert_pct"):
        config.load_config(p)


# ---------- source ----------

def write(tmp_path, text):
    return config.load_config(write_yaml(tmp_path, text))


def test_source_defaults_to_yahoo_with_bare_ticker_keys(tmp_path):
    """Every list that existed before trade.xyz support must load unchanged."""
    cfg = write(tmp_path, "holdings:\n  - ticker: NVDA\n")
    assert cfg["source"] == "yahoo"
    assert cfg["benchmark"] == "SPY"
    assert cfg["holdings"][0]["key"] == "NVDA"
    assert cfg["holdings"][0]["source"] == "yahoo"


def test_hyperliquid_source_namespaces_the_fetch_key(tmp_path):
    """The key is what keeps a Yahoo NVDA and a trade.xyz NVDA from colliding
    in the one shared hists dict."""
    cfg = write(tmp_path, "source: hyperliquid\nholdings:\n  - ticker: NVDA\n")
    assert cfg["source"] == "hyperliquid"
    assert cfg["holdings"][0]["ticker"] == "NVDA"     # display stays bare
    assert cfg["holdings"][0]["key"] == "xyz:NVDA"


def test_hyperliquid_defaults_benchmark_to_sp500(tmp_path):
    """SPY is not a market on the venue; SP500 is."""
    cfg = write(tmp_path, "source: hyperliquid\nholdings:\n  - ticker: NVDA\n")
    assert cfg["benchmark"] == "SP500"


def test_explicit_benchmark_still_wins_for_hyperliquid(tmp_path):
    cfg = write(tmp_path, "source: hyperliquid\nbenchmark: xyz100\nholdings:\n  - ticker: NVDA\n")
    assert cfg["benchmark"] == "XYZ100"


def test_dex_override_reaches_the_key(tmp_path):
    cfg = write(tmp_path, "source: hyperliquid\ndex: flx\nholdings:\n  - ticker: NVDA\n")
    assert cfg["dex"] == "flx"
    assert cfg["holdings"][0]["key"] == "flx:NVDA"


def test_source_is_case_insensitive(tmp_path):
    cfg = write(tmp_path, "source: HyperLiquid\nholdings:\n  - ticker: NVDA\n")
    assert cfg["source"] == "hyperliquid"


def test_unknown_source_is_rejected(tmp_path):
    """A typo must fail loudly at load, not silently fetch from Yahoo and
    render perp tickers as blank rows."""
    with pytest.raises(ValueError, match="unknown source"):
        write(tmp_path, "source: coinbase\nholdings:\n  - ticker: NVDA\n")


def test_source_propagates_through_load_watchlists(tmp_path):
    d = tmp_path / "wl"
    d.mkdir()
    (d / "book.yaml").write_text("source: hyperliquid\nholdings:\n  - ticker: GOLD\n")
    (d / "equities.yaml").write_text("holdings:\n  - ticker: NVDA\n")
    lists = {w["name"]: w for w in config.load_watchlists(d)}
    assert lists["book"]["source"] == "hyperliquid"
    assert lists["book"]["holdings"][0]["key"] == "xyz:GOLD"
    assert lists["equities"]["source"] == "yahoo"
    assert lists["equities"]["holdings"][0]["key"] == "NVDA"


def test_scaffold_template_still_loads(tmp_path):
    """The template gained a commented-out source: line — it must stay valid."""
    path = config.new_watchlist(tmp_path, "fresh list")
    cfg = config.load_config(path)
    assert cfg["source"] == "yahoo"


def test_equity_defaults_to_none_and_uppercases(tmp_path):
    cfg = write(tmp_path, "source: hyperliquid\nholdings:\n"
                          "  - ticker: GOLD\n"
                          "  - {ticker: SKHX, equity: 000660.ks}\n")
    holdings = {h["ticker"]: h for h in cfg["holdings"]}
    assert holdings["GOLD"]["equity"] is None      # bullion, not Barrick
    assert holdings["SKHX"]["equity"] == "000660.KS"


def test_generated_tradexyz_universe_declares_equity_only_where_it_applies(tmp_path):
    """Guards the catalog in scripts/sync_tradexyz.py: a commodity or FX market
    that picks up an `equity:` would import an unrelated company's fundamentals."""
    path = ROOT / "watchlists" / "tradexyz-universe.yaml"
    if not path.exists():
        pytest.skip("universe watchlist not generated in this checkout")
    holdings = {h["ticker"]: h for h in config.load_config(path)["holdings"]}
    for symbol in ("GOLD", "SILVER", "COPPER", "CL", "BRENTOIL", "NATGAS",
                   "EUR", "GBP", "JPY", "SP500", "XYZ100", "JP225", "KR200",
                   "SPCX", "CXMT", "ZHIPU", "SKHX", "SMSN"):
        assert holdings[symbol]["equity"] is None, symbol
    for symbol in ("NVDA", "MU", "AAPL", "SMH"):
        assert holdings[symbol]["equity"] == symbol, symbol
