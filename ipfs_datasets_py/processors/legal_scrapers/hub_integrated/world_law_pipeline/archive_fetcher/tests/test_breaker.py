"""Wayback circuit breaker simulation. Uses a temp RATE_DIR; never touches the network or the live state.
Run: venv/bin/python -m pytest -q archive/tests/test_breaker.py   (or python archive/tests/test_breaker.py)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import multiprocessing as mp, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ratelimit as rl


def setup(tmp=None):
    rl.RATE_DIR = Path(tmp or tempfile.mkdtemp(prefix="rltest_"))
    rl.FAMILIES["wayback"] = 0.01; rl.BREAKER_SLOW_SPACING = 0.02   # fast simulation
    return rl.RATE_DIR


def fail_once(kind, lane):
    with rl.slot("wayback", lane=lane) as r:
        r.fail(kind)
    st = rl._read_state("wayback"); st["backoff_until"] = 0; rl._write_state("wayback", st)  # skip the soft pause


def _child_fail(d, kind, lane):
    setup(d); fail_once(kind, lane)


def test_opens_after_3_across_lanes_and_processes():
    d = setup()
    for i, (k, lane) in enumerate([("ssl", "eu"), ("neterr", "national"), (429, "web")]):
        p = mp.get_context("fork").Process(target=_child_fail, args=(str(d), k, lane)); p.start(); p.join()
        assert p.exitcode == 0
    b = rl.breaker_status()
    assert b["state"] == "open" and b["consec_fails"] == 3, b
    assert not rl.wayback_available()
    t0 = time.time()
    try:
        with rl.slot("wayback", lane="x"):
            assert False, "must not get a slot"
    except rl.SlotBusy as e:                          # old callers catching SlotBusy keep working
        assert isinstance(e, rl.WaybackDown)
    assert time.time() - t0 < 1
    assert rl.slot.__name__ and rl.status()["wayback_breaker"]["state"] == "open"


def test_success_resets_count_and_404_is_not_failure():
    setup()
    fail_once("timeout", "a"); fail_once("timeout", "a")
    with rl.slot("wayback") as r: r.ok(404)
    fail_once("timeout", "a"); fail_once("timeout", "a")
    assert rl.breaker_status()["state"] == "closed"


def test_single_prober_every_30min_and_half_rate():
    setup()
    for _ in range(3): fail_once("ssl", "a")
    calls = []
    rl._probe = lambda fam: (calls.append(fam), (False, "SSLError"))[1]
    for _ in range(5):                                # not due yet: no probe at all
        try:
            with rl.slot("wayback"): pass
        except rl.WaybackDown: pass
    assert calls == []
    with rl._brk_locked() as b: b["last_probe"] = time.time() - 1801
    assert rl.wayback_available()                     # probe due -> caller may try
    for _ in range(5):
        try:
            with rl.slot("wayback"): pass
        except rl.WaybackDown: pass
    assert len(calls) == 1, calls                     # exactly one probe, then next window
    assert rl.breaker_status()["state"] == "open"
    with rl._brk_locked() as b: b["last_probe"] = time.time() - 1801
    rl._probe = lambda fam: (calls.append(fam), (True, 200))[1]
    with rl.slot("wayback") as r: r.ok(200)
    b = rl.breaker_status()
    assert b["state"] == "closed" and len(calls) == 2 and b["spacing"] == rl.BREAKER_SLOW_SPACING, b
    assert rl._spacing("wayback") == rl.BREAKER_SLOW_SPACING


def test_heal_back_to_base():
    setup()
    with rl._brk_locked() as b:
        b.update(state="closed", spacing=4.0, healthy_since=time.time() - 3700)
    rl.FAMILIES["wayback"] = 2.0
    assert rl._spacing("wayback") == 3.0
    with rl._brk_locked() as b: b["healthy_since"] = time.time() - 7300
    assert rl._spacing("wayback") == 2.0
    with rl._brk_locked() as b: b["healthy_since"] = time.time() - 100
    assert rl._spacing("wayback") == 4.0


def test_concurrent_probe_claim():
    d = setup()
    with rl._brk_locked() as b: b.update(state="open", last_probe=time.time() - 1801, opened_at=time.time())
    def child(q):
        setup(str(d))
        rl._probe = lambda fam: (time.sleep(0.5), (False, "SSLError"))[1]
        try:
            with rl.slot("wayback"): pass
        except rl.WaybackDown as e: q.put(str(e))
    ctx = mp.get_context("fork"); q = ctx.Queue()
    ps = [ctx.Process(target=child, args=(q,)) for _ in range(6)]
    [p.start() for p in ps]; [p.join() for p in ps]
    msgs = [q.get() for _ in range(6)]
    assert sum("probe failed" in m for m in msgs) == 1, msgs
    assert rl.breaker_status()["probes"] == 1


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
