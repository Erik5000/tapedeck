import pytest

from bloom import config


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
