"""IGNORE_ROBOTS=1 switch (2026-11-01): Disallow checks skipped, Crawl-delay kept as a politeness delay capped at 10 s."""
import os, sys, importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rfc9309
from rfc9309 import Robots, politeness_delay

TXT = "User-agent: *\nDisallow: /\nCrawl-delay: 60\n"


def _with(val, fn):
    old = os.environ.get("IGNORE_ROBOTS")
    if val is None:
        os.environ.pop("IGNORE_ROBOTS", None)
    else:
        os.environ["IGNORE_ROBOTS"] = val
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("IGNORE_ROBOTS", None)
        else:
            os.environ["IGNORE_ROBOTS"] = old


def test_ignore_robots_off_by_default():
    r = Robots(TXT)
    assert _with(None, lambda: r.can_fetch("JusticeDAO-WorldLaw/1.0", "https://a/x")) is False
    assert _with(None, lambda: Robots(disallow_all=True).can_fetch("x", "https://a/x")) is False
    assert _with(None, lambda: politeness_delay(60, 2.0)) == 60.0


def test_ignore_robots_on_allows_and_caps_delay():
    r = Robots(TXT)
    assert _with("1", lambda: r.can_fetch("JusticeDAO-WorldLaw/1.0", "https://a/x")) is True
    assert _with("1", lambda: Robots(disallow_all=True).can_fetch("x", "https://a/x")) is True
    assert r.crawl_delay("JusticeDAO-WorldLaw/1.0") == 60.0
    assert _with("1", lambda: politeness_delay(60, 2.0)) == 10.0      # >10 s treated as 10 s
    assert _with("1", lambda: politeness_delay(5, 2.0)) == 5.0        # honoured up to 10 s
    assert _with("1", lambda: politeness_delay(None, 2.0)) == 2.0
    assert _with("1", lambda: politeness_delay(0.1, 0.0)) == 1.0      # never below 1 s


class _Rob:
    def __init__(self, state):
        self.state = state


def test_ignore_robots_crawler_politeness_layer():
    for name in ("de_ortsrecht_crawler", "fr_actes_crawler"):
        m = importlib.import_module(name)
        pol = m.Politeness(lambda: None)
        pol.robots["h.example"] = ("ok", Robots(TXT))
        pol.robots["dead.example"] = ("disallow_all", "robots 503")
        assert _with(None, lambda: pol.allowed("https://h.example/satzung.pdf", None)) == (False, "robots_disallowed")
        assert _with(None, lambda: pol.allowed("https://dead.example/a", None))[0] is False
        assert _with("1", lambda: pol.allowed("https://h.example/satzung.pdf", None)) == (True, "")
        assert _with("1", lambda: pol.allowed("https://dead.example/a", None)) == (True, "")
        assert _with("1", lambda: pol.delay_for("h.example")) == 10.0
        assert _with(None, lambda: pol.delay_for("h.example")) == 60.0
