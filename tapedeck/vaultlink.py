"""Read-only bridge to an external vault cockpit file (markdown).

This module is a strictly read-only consumer: the only filesystem access is
``Path(path).read_text()`` in ``load_cockpit`` — nothing here ever writes to
or otherwise touches the vault. Any failure (missing file, drifted format)
degrades to ``None`` / empty fields with a stderr warning so the dashboard
run always survives.
"""

import re
import sys
from datetime import date
from pathlib import Path

_DATE = r"(\d{4}-\d{2}-\d{2})"
_TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}$")


def load_cockpit(path):
    """Read + parse a cockpit markdown file. Returns None (and warns) on any failure."""
    try:
        return parse_cockpit(Path(path).read_text())
    except Exception as exc:
        print(f"warning: cockpit not readable ({exc}) — panel omitted", file=sys.stderr)
        return None


def parse_cockpit(text):
    """Tolerant, pure parser for the cockpit markdown. Each section is parsed
    independently — one drifted section empties its own fields, never the rest."""
    out = {"regenerated": None, "regime": None, "freeze": None, "triad_refreshed": None,
           "freeze_note": None, "sleeves": [], "triad": [], "open_decisions": []}
    preamble, sections = _split_sections(text.splitlines())
    for parse in (lambda: _parse_preamble(preamble, out),
                  lambda: _parse_book(sections.get("book", []), out),
                  lambda: _parse_regime(sections.get("regime", []), out),
                  lambda: _parse_decisions(sections.get("decisions", []), out)):
        try:
            parse()
        except Exception:
            pass
    return out


def cockpit_freshness(cockpit, today):
    """Age the cockpit's date stamps against `today` (a datetime.date)."""
    if not cockpit:
        return None

    def age(iso):
        try:
            return (today - date.fromisoformat(iso)).days if iso else None
        except ValueError:
            return None

    return {"regenerated": cockpit.get("regenerated"),
            "age_days": age(cockpit.get("regenerated")),
            "triad_refreshed": cockpit.get("triad_refreshed"),
            "triad_age_days": age(cockpit.get("triad_refreshed"))}


# ---------- internals ----------

def _split_sections(lines):
    """Split into preamble + `## ` sections classified by heading keywords
    (substring match, so circled digits / emoji / suffixes don't matter)."""
    preamble, sections, current = [], {}, None
    for ln in lines:
        m = re.match(r"##(?!#)\s*(.+)", ln)
        if m:
            head = m.group(1).lower()
            if "book" in head:
                current = "book"
            elif "regime" in head or "freeze" in head:
                current = "regime"
            elif "decision" in head:
                current = "decisions"
            else:
                current = "other"
            sections.setdefault(current, [])
        elif current is None:
            preamble.append(ln)
        else:
            sections[current].append(ln)
    return preamble, sections


def _parse_preamble(lines, out):
    m = re.search(r"Regenerated:\s*" + _DATE, "\n".join(lines))
    if m:
        out["regenerated"] = m.group(1)
    for ln in lines:
        if ln.lstrip().startswith(">") and "REGIME" in ln:
            s = ln.replace("**", "")
            for key, pattern in (("regime", r"REGIME\s+(.+?)\s*·"),
                                 ("freeze", r"FREEZE\s+([A-Z][A-Z-]*)"),
                                 ("triad_refreshed", r"triad[^·]*?" + _DATE)):
                m = re.search(pattern, s)
                if m:
                    out[key] = m.group(1).strip()
            break


def _parse_table(lines):
    """First markdown table in lines -> list of {lowercased header: cell} dicts.
    Bold markers stripped, separator rows skipped, rows with a mismatched
    cell count skipped."""
    headers, rows = None, []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            if headers and rows:
                break
            continue
        cells = [c.strip().replace("**", "") for c in s.strip("|").split("|")]
        if cells and all(re.fullmatch(r"[-: ]+", c) for c in cells):
            continue
        if headers is None:
            headers = [c.lower() for c in cells]
        elif len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _col(row, prefix):
    for key, val in row.items():
        if key.startswith(prefix):
            return val
    return None


def _parse_book(lines, out):
    for row in _parse_table(lines):
        tickers = [t.strip() for t in re.split(r"[,/]", _col(row, "ticker") or "")]
        conf = re.search(r"\d+", _col(row, "conf") or "")
        out["sleeves"].append({
            "position": _col(row, "position"),
            "tickers": [t for t in tickers if _TICKER.match(t)],
            "size": _col(row, "size"),
            "fill_status": _col(row, "fill"),
            "conf": int(conf.group()) if conf else None,
        })


def _parse_regime(lines, out):
    for row in _parse_table(lines):
        out["triad"].append({"leg": _col(row, "leg"), "reading": _col(row, "reading"),
                             "trigger": _col(row, "trigger"), "status": _col(row, "status")})
    for ln in lines:
        s = ln.replace("**", "").strip()
        if s.startswith("Freeze:"):
            out["freeze_note"] = s[len("Freeze:"):].strip()
            break


def _parse_decisions(lines, out):
    for ln in lines:
        m = re.match(r"#(\d+)\s+`\[([A-Z]+)\]`", ln.strip())
        if not m or m.group(2) != "OPEN":
            continue
        title = re.search(r"\*\*(.+?)\*\*", ln)
        out["open_decisions"].append({"id": int(m.group(1)),
                                      "title": title.group(1) if title else ""})
