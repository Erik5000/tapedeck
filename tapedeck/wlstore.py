"""Read and write watchlist yaml on behalf of the in-app editor.

All filesystem reasoning lives here so the request handler stays a router.
Three rules the editor depends on:

  * **Nothing leaves the watchlists directory.** Names go through the same
    slug rule `--new` uses, and every resolved path is checked to sit inside
    the directory — a name is attacker-controlled input the moment the server
    is listening.
  * **Nothing is saved that the next run can't load.** Every write is parsed
    back through config.load_config first, so the editor cannot produce a file
    that breaks the whole dashboard (load_watchlists has no per-file isolation:
    one bad list kills every list).
  * **Nothing is overwritten without a copy.** yaml.safe_dump does not preserve
    comments, so saving a hand-annotated file through the UI loses them. The
    pre-write backup is what makes that recoverable rather than final.
"""

import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from . import config

NAME_RE = re.compile(r"[a-z0-9-]+")

# Written in this order so a saved file still reads top-down like a hand-written
# one. Keys absent from the editor's model are simply omitted.
_TOP_KEYS = ("title", "order", "source", "dex", "benchmark", "cockpit",
             "anti_basket", "vwap", "vwap_alert_pct")
_HOLDING_KEYS = ("ticker", "name", "group", "equity", "shares", "cost_basis",
                 "tv_symbol")


class WatchlistError(Exception):
    """Anything the caller should see as a 4xx rather than a 500."""


def _safe_path(directory, name):
    """<directory>/<name>.yaml, or raise if `name` tries to leave the directory."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise WatchlistError(f"invalid watchlist name {name!r} — use lowercase letters, digits and dashes")
    directory = Path(directory).resolve()
    path = (directory / f"{name}.yaml").resolve()
    # Belt and braces: the regex already forbids "/" and ".." , but a symlinked
    # watchlists dir would still be caught here.
    if path.parent != directory:
        raise WatchlistError(f"invalid watchlist name {name!r}")
    return path


def list_names(directory):
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml") if not p.name.startswith("_"))


def summaries(directory):
    """Name, title and holding count per list, for the editor's sidebar.

    A list that fails to load still appears, carrying its error — hiding a
    broken file would leave the user wondering where their watchlist went,
    when that same file is also breaking every other list on the next run.
    """
    out = []
    for name in list_names(directory):
        entry = {"name": name, "title": name.replace("-", " ").title(),
                 "count": 0, "error": None}
        try:
            cfg = config.load_config(_safe_path(directory, name))
            entry["title"] = cfg["title"] or entry["title"]
            entry["count"] = len(cfg["holdings"])
            entry["source"] = cfg["source"]
        except (WatchlistError, OSError, ValueError, yaml.YAMLError) as exc:
            entry["error"] = str(exc)
        out.append(entry)
    return out


def read(directory, name):
    """The editor's model for one list: every key it can edit, nothing else."""
    path = _safe_path(directory, name)
    if not path.exists():
        raise WatchlistError(f"no watchlist named {name!r}")
    cfg = config.load_config(path)
    holdings = [{k: h.get(k) for k in _HOLDING_KEYS} for h in cfg["holdings"]]
    model = {k: cfg.get(k) for k in _TOP_KEYS}
    model.update({"name": name, "holdings": holdings,
                  "has_comments": _has_comments(path)})
    return model


def _has_comments(path):
    """Whether saving would destroy hand-written commentary. The editor warns
    on this rather than silently flattening a documented file."""
    try:
        return any(line.lstrip().startswith("#") for line in path.read_text().splitlines())
    except OSError:
        return False


def create(directory, name, title=None):
    """Scaffold a new list. Reuses config.new_watchlist so the template, the
    slug rule and the already-exists check stay in one place."""
    try:
        path = config.new_watchlist(directory, name, title=title)
    except ValueError as exc:
        raise WatchlistError(str(exc))
    return path.stem


def delete(directory, name, backup_dir=None):
    path = _safe_path(directory, name)
    if not path.exists():
        raise WatchlistError(f"no watchlist named {name!r}")
    _backup(path, backup_dir)
    path.unlink()


def save(directory, name, model, backup_dir=None):
    """Write the editor's model, after proving it loads. Returns the path."""
    path = _safe_path(directory, name)
    text = to_yaml(model)
    _verify(text, name)
    if path.exists():
        _backup(path, backup_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _verify(text, name):
    """Parse the candidate before it touches disk.

    load_watchlists loops without a per-file try, so one unloadable list takes
    down every list on the next run. The editor must not be able to cause that.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write(text)
        tmp = Path(fh.name)
    try:
        config.load_config(tmp)
    except (ValueError, yaml.YAMLError) as exc:
        raise WatchlistError(f"would not load: {exc}")
    finally:
        tmp.unlink()


def _backup(path, backup_dir):
    if backup_dir is None:
        backup_dir = path.parent.parent / "output" / "watchlist-backups"
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{path.stem}-{stamp}.yaml"
    shutil.copy2(path, target)
    return target


def to_yaml(model):
    """The editor's model -> yaml text.

    Hand-rolled rather than one safe_dump of the whole document so the key
    order stays readable and holdings stay one-per-line in flow style, which
    is how every hand-written list in this repo looks.
    """
    if not isinstance(model, dict):
        raise WatchlistError("watchlist must be an object")
    holdings = model.get("holdings")
    if not isinstance(holdings, list) or not holdings:
        raise WatchlistError("a watchlist needs at least one holding")

    lines = []
    for key in _TOP_KEYS:
        value = model.get(key)
        if value is None or value == "":
            continue
        lines.append(_dump({key: value}, flow=False))
    lines.append("")
    lines.append("holdings:")
    for entry in holdings:
        if not isinstance(entry, dict):
            raise WatchlistError(f"holding must be an object, got {entry!r}")
        fields = {k: entry[k] for k in _HOLDING_KEYS
                  if entry.get(k) is not None and entry.get(k) != ""}
        if not fields.get("ticker"):
            raise WatchlistError(f"holding missing 'ticker': {entry!r}")
        lines.append("  - " + _dump(fields, flow=True))
    return "\n".join(lines) + "\n"


def _dump(mapping, flow):
    """One yaml mapping, with pyyaml deciding the quoting.

    Doing this per-mapping rather than per-scalar is what makes the flow style
    safe: a scalar dumped on its own has no idea it is about to be embedded in
    `{...}`, so a name like "Alphabet, Inc." would come back unquoted and the
    comma would end the entry. width is set high so nothing line-wraps.
    """
    text = yaml.safe_dump(mapping, default_flow_style=flow, sort_keys=False,
                          width=10 ** 6, allow_unicode=True)
    return text.strip()
