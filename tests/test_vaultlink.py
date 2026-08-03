from datetime import date

from tapedeck import vaultlink

# Trimmed replica of a real cockpit file: preamble + blockquote state line,
# book table (bolded status, comma + slash tickers, parenthesised status),
# regime table + Freeze line, decision queue with OPEN/DONE/DECIDED mix.
COCKPIT_MD = """\
# 🎛️ FMFB Kapital — Cockpit

*Regenerated: 2026-07-28 · weekly (Sun 21:00) + on demand ("refresh the cockpit").*
*Act by telling Claude `do #N`. Full audit: [[decisions-log]].*

> **REGIME** higher-for-longer, low-stress · **FREEZE** PARTIAL-LIFT · triad manually refreshed 2026-07-28 (all legs quiet) · ⚠️ still not auto-wired (#3)
> **NEEDS YOU THIS WEEK:** 2 open decisions.

## ① The Book — proposed v1, 0 real fills

| Position | Tickers | Size | Fill status | Conf |
|---|---|---|---|---|
| Interconnect leaders | CRDO, CIEN, FN | 1.25R | **STARTER-OK** | 62 |
| Teradyne (cyclical + robotics) | TER | 0.5R | FROZEN (gated) | 54 |
| Hedge sleeve — trend + real assets | DBMF/KMLM/GLD/DBC/TIP | ~25% | UNFUNDED | 68 |

Gross long ~45% · dry powder ~40%.

## ② Regime & Freeze

| Leg | Reading | Trigger | Status |
|---|---|---|---|
| 10Y breakeven | 2.21% (falling, 2026-07-27) | >2% **and rising** = inflation live | quiet |
| Yield curve (2s10s) | +34bp (steepened, 2026-07-27) | inversion = recession lead | quiet |

**Freeze:** PARTIAL-LIFT — only the two `STARTER-OK` legs may fill; everything else frozen.

## ③ Decision Queue ← the cockpit

#1 `[DONE]` `[your call]` **Feed source material** — closed out long ago.
#3 `[OPEN]` `[your call]` **Wire the regime triad live** (FRED T10YIE / T10Y2Y / ISM) — the single gate.
#5 `[OPEN]` `[your call]` **Monthly thesis review** — theses dated 2026-06-18/19.
#8 `[DECIDED]` `[approve]` **Implement the trend overlay** — spec written.

<!-- cockpit:last-id=9 -->
"""


def test_parse_preamble_state():
    c = vaultlink.parse_cockpit(COCKPIT_MD)
    assert c["regenerated"] == "2026-07-28"
    assert c["regime"] == "higher-for-longer, low-stress"
    assert c["freeze"] == "PARTIAL-LIFT"
    assert c["triad_refreshed"] == "2026-07-28"


def test_parse_book_sleeves():
    sleeves = vaultlink.parse_cockpit(COCKPIT_MD)["sleeves"]
    assert len(sleeves) == 3
    first = sleeves[0]
    assert first["position"] == "Interconnect leaders"
    assert first["tickers"] == ["CRDO", "CIEN", "FN"]
    assert first["size"] == "1.25R"
    assert first["fill_status"] == "STARTER-OK"  # bold stripped
    assert first["conf"] == 62
    assert sleeves[1]["fill_status"] == "FROZEN (gated)"  # parenthesis survives
    assert sleeves[2]["tickers"] == ["DBMF", "KMLM", "GLD", "DBC", "TIP"]  # slash row


def test_parse_triad_and_freeze_note():
    c = vaultlink.parse_cockpit(COCKPIT_MD)
    assert len(c["triad"]) == 2
    assert c["triad"][0]["leg"] == "10Y breakeven"
    assert c["triad"][0]["status"] == "quiet"
    assert c["triad"][1]["reading"].startswith("+34bp")
    assert c["freeze_note"].startswith("PARTIAL-LIFT")


def test_parse_open_decisions_only():
    c = vaultlink.parse_cockpit(COCKPIT_MD)
    assert [(d["id"], d["title"]) for d in c["open_decisions"]] == [
        (3, "Wire the regime triad live"), (5, "Monthly thesis review")]


def test_missing_section_degrades_alone():
    trimmed = COCKPIT_MD.replace("## ② Regime & Freeze", "## ② Something Else")
    c = vaultlink.parse_cockpit(trimmed)
    assert c["triad"] == []
    assert c["freeze_note"] is None
    assert len(c["sleeves"]) == 3  # book section still parsed
    assert c["open_decisions"]  # decisions still parsed


def test_mangled_table_row_skipped():
    mangled = COCKPIT_MD.replace(
        "| Teradyne (cyclical + robotics) | TER | 0.5R | FROZEN (gated) | 54 |",
        "| broken row without enough cells |")
    sleeves = vaultlink.parse_cockpit(mangled)["sleeves"]
    assert [s["position"] for s in sleeves] == [
        "Interconnect leaders", "Hedge sleeve — trend + real assets"]


def test_no_blockquote_gives_nones():
    lines = [ln for ln in COCKPIT_MD.splitlines() if not ln.startswith(">")]
    c = vaultlink.parse_cockpit("\n".join(lines))
    assert c["regime"] is None
    assert c["freeze"] is None
    assert c["sleeves"]  # rest still parsed


def test_load_cockpit_missing_file_warns(tmp_path, capsys):
    assert vaultlink.load_cockpit(tmp_path / "nope.md") is None
    assert "warning" in capsys.readouterr().err.lower()


def test_load_cockpit_reads_file(tmp_path):
    p = tmp_path / "COCKPIT.md"
    p.write_text(COCKPIT_MD)
    assert vaultlink.load_cockpit(p)["freeze"] == "PARTIAL-LIFT"


def test_cockpit_freshness_age_math():
    c = vaultlink.parse_cockpit(COCKPIT_MD)
    fresh = vaultlink.cockpit_freshness(c, date(2026, 7, 31))
    assert fresh["age_days"] == 3
    assert fresh["triad_age_days"] == 3
    assert fresh["regenerated"] == "2026-07-28"


def test_cockpit_freshness_none_safe():
    assert vaultlink.cockpit_freshness(None, date(2026, 7, 31)) is None
    fresh = vaultlink.cockpit_freshness({"regenerated": None}, date(2026, 7, 31))
    assert fresh["age_days"] is None
