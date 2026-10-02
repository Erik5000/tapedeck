"""Suite-wide guard: no test reaches the network.

Every CLI run builds the Situation tab, which fetches from FRED and the venue.
The CLI tests stub the watchlist fetches but not these, so without this guard
they would make real calls. A test that exercises the fetch code replaces
these stubs with its own (a later monkeypatch.setattr wins).
"""

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    from tapedeck import hlfetch
    from tapedeck.situation import sources

    def blocked(*args, **kwargs):
        raise RuntimeError("network blocked in tests")

    monkeypatch.setattr(hlfetch, "_post", blocked)
    monkeypatch.setattr(sources, "_get", blocked)
