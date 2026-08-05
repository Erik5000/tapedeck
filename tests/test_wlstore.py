"""Watchlist read/write behind the in-app editor.

The three properties that matter: nothing escapes the watchlists directory,
nothing unloadable reaches disk, and nothing is overwritten without a copy.
"""

import pytest
import yaml

from tapedeck import config, wlstore
from tapedeck.wlstore import WatchlistError


@pytest.fixture
def wl(tmp_path):
    d = tmp_path / "watchlists"
    d.mkdir()
    return d


def write(wl, name, text):
    (wl / f"{name}.yaml").write_text(text)


BOOK = "title: My Book\nbenchmark: QQQ\nholdings:\n  - {ticker: NVDA, group: semis}\n"


# ---------- path safety ----------
#
# The moment the server is listening, `name` is attacker-controlled input.

@pytest.mark.parametrize("name", [
    "../evil", "../../etc/passwd", "a/b", "/abs", "", "..", "sub/../../out",
    "Book", "my_book", "with space", "dot.dot", "-",
])
def test_bad_names_are_rejected_everywhere(wl, name):
    if name == "-":
        pytest.skip("'-' is a legal slug, covered by the happy path")
    for call in (lambda: wlstore.read(wl, name),
                 lambda: wlstore.save(wl, name, {"holdings": [{"ticker": "X"}]}),
                 lambda: wlstore.delete(wl, name)):
        with pytest.raises(WatchlistError):
            call()


def test_traversal_cannot_write_outside_the_directory(wl, tmp_path):
    outside = tmp_path / "secrets.yaml"
    outside.write_text("do not touch\n")
    with pytest.raises(WatchlistError):
        wlstore.save(wl, "../secrets", {"holdings": [{"ticker": "X"}]})
    assert outside.read_text() == "do not touch\n"


# ---------- listing and reading ----------

def test_list_names_skips_underscore_prefixed(wl):
    write(wl, "book", BOOK)
    write(wl, "_template", BOOK)
    assert wlstore.list_names(wl) == ["book"]


def test_list_names_on_a_missing_directory(tmp_path):
    assert wlstore.list_names(tmp_path / "nope") == []


def test_summaries_carry_title_count_and_source(wl):
    write(wl, "book", BOOK)
    write(wl, "venue", "source: hyperliquid\nholdings:\n  - {ticker: GOLD}\n"
                       "  - {ticker: NVDA}\n")
    by = {s["name"]: s for s in wlstore.summaries(wl)}
    assert by["book"]["title"] == "My Book"
    assert by["book"]["count"] == 1
    assert by["venue"]["count"] == 2
    assert by["venue"]["source"] == "hyperliquid"
    assert by["book"]["error"] is None


def test_summaries_surface_a_broken_list_instead_of_hiding_it(wl):
    """A file that won't load breaks every list on the next run, since
    load_watchlists has no per-file isolation. Hiding it from the editor is
    the one place the user could have fixed it."""
    write(wl, "good", BOOK)
    write(wl, "broken", "holdings: [{name: no ticker here}]\n")
    by = {s["name"]: s for s in wlstore.summaries(wl)}
    assert by["broken"]["error"]
    assert "ticker" in by["broken"]["error"]
    assert by["good"]["error"] is None


def test_read_returns_the_editable_model(wl):
    write(wl, "book", BOOK)
    model = wlstore.read(wl, "book")
    assert model["name"] == "book"
    assert model["title"] == "My Book"
    assert model["benchmark"] == "QQQ"
    assert model["holdings"] == [
        {"ticker": "NVDA", "name": None, "group": "semis", "equity": None,
         "shares": None, "cost_basis": None, "tv_symbol": None}]


def test_read_missing_list(wl):
    with pytest.raises(WatchlistError, match="no watchlist"):
        wlstore.read(wl, "ghost")


def test_read_flags_a_commented_file(wl):
    write(wl, "plain", BOOK)
    write(wl, "documented", "# why this list exists\n" + BOOK)
    assert wlstore.read(wl, "plain")["has_comments"] is False
    assert wlstore.read(wl, "documented")["has_comments"] is True


# ---------- yaml emission ----------

def test_to_yaml_round_trips_through_the_real_loader(wl):
    model = {"title": "Venue", "source": "hyperliquid", "benchmark": "SP500",
             "vwap_alert_pct": 1.5,
             "holdings": [{"ticker": "NVDA", "group": "semis", "equity": "NVDA"},
                          {"ticker": "GOLD", "name": "Gold (troy oz)"}]}
    path = wlstore.save(wl, "venue", model)
    cfg = config.load_config(path)
    assert cfg["source"] == "hyperliquid"
    assert cfg["vwap_alert_pct"] == 1.5
    assert [h["ticker"] for h in cfg["holdings"]] == ["NVDA", "GOLD"]
    assert cfg["holdings"][0]["equity"] == "NVDA"


@pytest.mark.parametrize("name", [
    "Alphabet, Inc.",          # a comma would end the flow-mapping entry
    "Gold: bullion",           # a colon would make it a nested mapping
    "Ends in a period Inc.",   # must not lose the trailing dot
    "Brace } close",
    "#not a comment",
    "S&P 500",
])
def test_awkward_names_survive_the_flow_mapping(wl, name):
    """Holdings are written in flow style. Quoting has to be decided knowing
    that, which is why the mapping is dumped whole rather than field by field."""
    wlstore.save(wl, "x", {"holdings": [{"ticker": "T", "name": name}]})
    assert config.load_config(wl / "x.yaml")["holdings"][0]["name"] == name


def test_yaml_boolean_tickers_stay_strings(wl):
    """Unquoted, `NO` is a yaml boolean and the ticker would load as False."""
    wlstore.save(wl, "x", {"holdings": [{"ticker": "NO"}, {"ticker": "ON"}]})
    assert [h["ticker"] for h in config.load_config(wl / "x.yaml")["holdings"]] == ["NO", "ON"]


def test_omitted_keys_do_not_appear(wl):
    path = wlstore.save(wl, "x", {"title": "T", "cockpit": None, "vwap": "",
                                  "holdings": [{"ticker": "NVDA", "group": None}]})
    raw = yaml.safe_load(path.read_text())
    assert "cockpit" not in raw and "vwap" not in raw
    assert "group" not in raw["holdings"][0]


def test_empty_holdings_rejected(wl):
    with pytest.raises(WatchlistError, match="at least one holding"):
        wlstore.save(wl, "x", {"title": "T", "holdings": []})


def test_holding_without_ticker_rejected(wl):
    with pytest.raises(WatchlistError, match="ticker"):
        wlstore.save(wl, "x", {"holdings": [{"name": "no ticker"}]})


def test_non_object_model_rejected(wl):
    with pytest.raises(WatchlistError):
        wlstore.to_yaml(["not", "a", "dict"])


# ---------- the save gate ----------

def test_save_refuses_a_file_that_would_not_load(wl):
    """One unloadable list takes down every list on the next run, so the editor
    must not be able to write one — verified against config.load_config itself,
    not a reimplementation of its rules."""
    write(wl, "x", BOOK)
    before = (wl / "x.yaml").read_text()
    with pytest.raises(WatchlistError, match="would not load"):
        wlstore.save(wl, "x", {"holdings": [{"ticker": "NVDA"}, {"ticker": "nvda"}]})
    assert (wl / "x.yaml").read_text() == before      # untouched on rejection


def test_save_rejects_a_negative_vwap_band(wl):
    with pytest.raises(WatchlistError, match="would not load"):
        wlstore.save(wl, "x", {"vwap_alert_pct": -1, "holdings": [{"ticker": "N"}]})


# ---------- backups ----------

def test_save_backs_up_the_previous_version_byte_for_byte(wl, tmp_path):
    original = "# hand-written, with commentary\n" + BOOK
    write(wl, "book", original)
    backups = tmp_path / "backups"
    wlstore.save(wl, "book", {"title": "New", "holdings": [{"ticker": "AMD"}]},
                 backup_dir=backups)
    copies = list(backups.glob("book-*.yaml"))
    assert len(copies) == 1
    # The comment loss is the accepted tradeoff; the backup is what makes it
    # recoverable rather than final.
    assert copies[0].read_text() == original
    assert "commentary" not in (wl / "book.yaml").read_text()


def test_creating_a_new_list_needs_no_backup(wl, tmp_path):
    backups = tmp_path / "backups"
    wlstore.save(wl, "fresh", {"holdings": [{"ticker": "NVDA"}]}, backup_dir=backups)
    assert not backups.exists() or not list(backups.glob("*.yaml"))


def test_delete_backs_up_first(wl, tmp_path):
    write(wl, "book", BOOK)
    backups = tmp_path / "backups"
    wlstore.delete(wl, "book", backup_dir=backups)
    assert not (wl / "book.yaml").exists()
    assert list(backups.glob("book-*.yaml"))[0].read_text() == BOOK


def test_delete_missing_list(wl):
    with pytest.raises(WatchlistError, match="no watchlist"):
        wlstore.delete(wl, "ghost")


# ---------- create ----------

def test_create_scaffolds_a_loadable_list(wl):
    name = wlstore.create(wl, "My Semis")
    assert name == "my-semis"
    assert wlstore.read(wl, name)["title"] == "My Semis"


def test_create_refuses_an_existing_name(wl):
    wlstore.create(wl, "semis")
    with pytest.raises(WatchlistError, match="exists"):
        wlstore.create(wl, "semis")


def test_create_rejects_traversal(wl):
    with pytest.raises(WatchlistError):
        wlstore.create(wl, "../evil")
