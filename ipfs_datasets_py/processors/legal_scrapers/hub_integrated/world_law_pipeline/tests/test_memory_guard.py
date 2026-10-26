"""Memory guard (MemAvailable), per-commit bookkeeping (ledger + move right after each commit), idempotent re-run
after a kill between Hub commit and bookkeeping, small commit chunks when memory is low, and the streaming
ledger / confirmed_batches readers of prune. Mocked Hub + mocked /proc/meminfo; synthetic data in /tmp."""
import hashlib, io, json, os, shutil, sys, tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
sys.path.insert(0, str(HERE / "tools"))
import run_loop as RL  # noqa: E402
import prune_processed as PP  # noqa: E402
from test_hold_policy import base, w  # noqa: E402
from test_scoped_listing import HubMock  # noqa: E402
import schema as _S  # noqa: E402
_S.BUCKETED_COUNTRIES = frozenset()  # flat-layout tests; hash buckets: test_buckets.py


class Killed(BaseException):
    """Stands in for SIGKILL: not an Exception, so nothing in run_loop catches it."""


class KillingHub(HubMock):
    def __init__(self, kill_at):
        super().__init__({"test/muni": set(), "test/nat": set()})
        self.kill_at = kill_at

    def create_commit(self, **kw):
        if len(self.commits) + 1 == self.kill_at:
            self.commits.append(kw)  # it LANDED on the Hub, then the process died before bookkeeping
            raise Killed()
        return super().create_commit(**kw)


def _run(tmp, api, avail=8.0, extra=()):
    import huggingface_hub
    orig_api, orig_mem = huggingface_hub.HfApi, RL.mem_available_gb
    huggingface_hub.HfApi = lambda *a, **k: api
    RL.mem_available_gb = avail if callable(avail) else (lambda: avail)
    try:
        return RL.main(["--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
                        "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "q"), "--held",
                        str(tmp / "h"), "--overrides", str(tmp / "none.json"), "--once", "--no-prune",
                        "--min-age", "0", "--repo", "test/muni", "--national-repo", "test/nat",
                        "--mem-wait", "0", *extra])
    finally:
        huggingface_hub.HfApi, RL.mem_available_gb = orig_api, orig_mem
        if RL._LOCK["f"] is not None:
            RL._LOCK["f"].close()
        RL._LOCK["f"] = None


def _stage(tmp, n=3, ts="20261011T010000Z"):
    fs = []
    for i in range(n):
        f = tmp / f"staging/eu/FR/wd_Q9{i}.{ts}p0001.jsonl"
        w(f, [base(f"d{i}{ts}", place_id=f"wd:Q9{i}", country_code="FR", language="fr")])
        fs.append(f)
    return fs


def _ledger(tmp):
    p = tmp / "state" / "ledger.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def _adds(commit):
    return {o.path_in_repo: o.path_or_fileobj for o in commit["operations"] if type(o).__name__ == "CommitOperationAdd"}


def test_mem_guard_recovers_or_stops():
    st = RL.Counter()
    seq = iter([1.0, 1.2, 2.0])
    assert RL.mem_guard("x", 1.5, 30, st, avail_fn=lambda: next(seq), sleep_fn=lambda s: None)
    assert st["mem_low_waits"] == 1 and not st.get("mem_low_stop")
    st = RL.Counter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = RL.mem_guard("commit municipal 2/3", 1.5, 10, st, avail_fn=lambda: 0.9, sleep_fn=lambda s: None)
    assert not ok and st["mem_low_stop"] == 1 and "MEM_LOW MemAvailable=0.90GB" in buf.getvalue()
    assert st["mem_min_available_gb"] == 0.9
    assert RL.mem_available_gb() > 0  # real /proc/meminfo is readable


def test_bookkeeping_right_after_each_commit_and_rerun_after_kill():
    """Kill after commit 2 landed (before its bookkeeping): commit 1's place is already ledgered + moved; the
    re-run re-commits the rest (identical data parquet bytes), ledgers everything exactly once."""
    tmp = Path(tempfile.mkdtemp(prefix="wl_mem_"))
    try:
        fs = _stage(tmp, 3)
        # tiny chunks: 1 place per commit (forced via the low-memory chunking path)
        small = ["--mem-small-chunk-gb", "100", "--mem-small-chunk-ops", "4"]
        api = KillingHub(kill_at=2)
        try:
            with redirect_stdout(io.StringIO()):
                _run(tmp, api, extra=small)
            raise AssertionError("expected the simulated kill")
        except Killed:
            pass
        assert len(api.commits) == 2
        led = _ledger(tmp)
        assert [r["place_key"] for r in led] == ["wd_Q90"], led
        assert led[0]["commit_ids"] == ["c1"]
        assert not fs[0].exists() and fs[1].exists() and fs[2].exists()
        assert (tmp / "processed/eu/FR" / fs[0].name).exists()
        landed = _adds(api.commits[1])
        sha_landed = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in landed.items() if "/data/" in k}
        # re-run (the Q91 commit already landed on the Hub; the re-commit carries the same data bytes)
        api2 = HubMock({"test/muni": set(), "test/nat": set()})
        with redirect_stdout(io.StringIO()):
            assert _run(tmp, api2, extra=small) == 0
        led = _ledger(tmp)
        assert sorted(r["place_key"] for r in led) == ["wd_Q90", "wd_Q91", "wd_Q92"], "each file ledgered once"
        assert not any(f.exists() for f in fs)
        re_q91 = [c for c in api2.commits if any("wd_Q91_html" in p for p in _adds(c))]
        assert len(re_q91) == 1
        for k, v in _adds(re_q91[0]).items():
            if k in sha_landed:
                assert hashlib.sha256(Path(v).read_bytes()).hexdigest() == sha_landed[k], "re-commit is a no-op"
        assert not any("wd_Q90" in p for c in api2.commits for p in _adds(c) if "/data/" in p), "Q90 not rebuilt"
        # a third run finds nothing to do
        api3 = HubMock({"test/muni": set(), "test/nat": set()})
        with redirect_stdout(io.StringIO()):
            assert _run(tmp, api3) == 0
        assert api3.commits == [] and len(_ledger(tmp)) == 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rerun_after_kill_before_any_bookkeeping_is_idempotent():
    """The 2026-10-14 06:38 failure mode: all commits landed, no file moved, no ledger row. Next run: same data
    bytes re-committed (Hub dedupes), ledger written, files moved."""
    tmp = Path(tempfile.mkdtemp(prefix="wl_mem_"))
    try:
        fs = _stage(tmp, 2)
        api = HubMock({"test/muni": set(), "test/nat": set()})
        with redirect_stdout(io.StringIO()):
            assert _run(tmp, api) == 0
        first = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in _adds(api.commits[0]).items()
                 if "/data/" in k}
        # undo the bookkeeping as if killed right after the commit
        for f in fs:
            shutil.move(str(tmp / "processed/eu/FR" / f.name), str(f))
        (tmp / "state/ledger.jsonl").unlink()
        api2 = HubMock({"test/muni": {"world_law/data/FR/wd_Q90_html.parquet",
                                      "world_law/data/FR/wd_Q91_html.parquet"}, "test/nat": set()})
        with redirect_stdout(io.StringIO()):
            assert _run(tmp, api2) == 0
        again = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in _adds(api2.commits[0]).items()
                 if "/data/" in k}
        assert again == first
        assert not any(type(o).__name__ == "CommitOperationDelete" for o in api2.commits[0]["operations"])
        assert len(_ledger(tmp)) == 2 and not any(f.exists() for f in fs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mem_low_before_commit_stops_cleanly():
    tmp = Path(tempfile.mkdtemp(prefix="wl_mem_"))
    try:
        fs = _stage(tmp, 2)
        calls = {"n": 0}

        def avail():  # fine while building, low from the first commit on
            calls["n"] += 1
            return 8.0 if calls["n"] <= 2 else 0.5
        api = HubMock({"test/muni": set(), "test/nat": set()})
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert _run(tmp, api, avail=avail) == 0
        assert "MEM_LOW" in buf.getvalue()
        assert api.commits == [] and all(f.exists() for f in fs) and _ledger(tmp) == []
        summ = json.loads((tmp / "state/runs.jsonl").read_text().splitlines()[-1])
        assert summ["mem_low_stop"] == 1 and summ["mem_low_commits_skipped"] == 1
        assert summ["files_left_staged_uncommitted"] == 2
        # memory back: next run publishes and ledgers them
        with redirect_stdout(io.StringIO()):
            assert _run(tmp, HubMock({"test/muni": set(), "test/nat": set()})) == 0
        assert len(_ledger(tmp)) == 2 and not any(f.exists() for f in fs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mem_low_mid_build_commits_what_was_built():
    tmp = Path(tempfile.mkdtemp(prefix="wl_mem_"))
    try:
        fs = _stage(tmp, 3)
        calls = {"n": 0}

        def avail():  # 1st build ok, then low for the rest of the builds, then ok again for the commit
            calls["n"] += 1
            return 0.5 if calls["n"] in (2, 3) else 8.0
        api = HubMock({"test/muni": set(), "test/nat": set()})
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert _run(tmp, api, avail=avail) == 0
        assert "MEM_LOW" in buf.getvalue()
        assert len(api.commits) == 1
        assert [r["place_key"] for r in _ledger(tmp)] == ["wd_Q90"]
        assert not fs[0].exists() and fs[1].exists() and fs[2].exists()
        summ = json.loads((tmp / "state/runs.jsonl").read_text().splitlines()[-1])
        assert summ["places_deferred_mem"] == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_small_chunks_when_memory_low():
    tmp = Path(tempfile.mkdtemp(prefix="wl_mem_"))
    try:
        _stage(tmp, 3)
        api = HubMock({"test/muni": set(), "test/nat": set()})
        with redirect_stdout(io.StringIO()):
            _run(tmp, api, avail=1.8, extra=["--mem-small-chunk-ops", "5"])
        assert len(api.commits) == 3  # one place (2 ops) per commit + the 3 tail ops in the last
        assert all(len(c["operations"]) <= 5 for c in api.commits)
        api2 = HubMock({"test/muni": set(), "test/nat": set()})
        _stage(tmp, 3, ts="20261012T010000Z")
        with redirect_stdout(io.StringIO()):
            _run(tmp, api2, avail=8.0)
        assert len(api2.commits) == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_filtered_ledger_and_streaming_confirmed_merge():
    tmp = Path(tempfile.mkdtemp(prefix="wl_mem_"))
    try:
        lp = tmp / "ledger.jsonl"
        rows = [{"bot": "eu", "rel": f"eu/FR/k{i}.jsonl", "sha256": f"s{i}", "at": "2026-10-14T00:00:00Z",
                 "big": "x" * 100} for i in range(50)] + [{"bot": "eu", "rel": "eu/FR/é.jsonl", "sha256": "u",
                                                           "at": "2026-10-14T00:00:00Z"}]
        lp.write_text("".join(json.dumps(r) + "\n" for r in rows) + "garbage\n")
        assert RL.load_ledger(lp, rels={"eu/FR/k3.jsonl", "eu/FR/é.jsonl"}) == {("eu", "eu/FR/k3.jsonl", "s3"),
                                                                             ("eu", "eu/FR/é.jsonl", "u")}
        assert len(RL.load_ledger(lp)) == 51
        idx = PP.load_ledger_index(tmp, wanted={("eu", "eu/FR/k7.jsonl"), ("eu", "eu/FR/é.jsonl")})
        assert set(idx) == {("eu", "eu/FR/k7.jsonl"), ("eu", "eu/FR/é.jsonl")}
        assert "big" not in idx[("eu", "eu/FR/k7.jsonl")][0]
        assert len(PP.load_ledger_index(tmp)) == 51
        cp = tmp / "confirmed" / "eu.jsonl"
        recs = [{"rel": f"eu/FR/k{i}.jsonl", "sha256": f"s{i}", "rows": 1} for i in range(3)]
        assert PP.merge_confirmed(cp, recs[:2], apply=True) == (2, 2)
        assert PP.merge_confirmed(cp, recs, apply=False) == (3, 1) and len(cp.read_text().splitlines()) == 2
        assert PP.merge_confirmed(cp, recs + [{"rel": "eu/FR/é.jsonl", "sha256": "u"}], apply=True) == (4, 2)
        assert PP.merge_confirmed(cp, recs + [{"rel": "eu/FR/é.jsonl", "sha256": "u"}], apply=True) == (4, 0)
        got = [json.loads(l) for l in cp.read_text().splitlines()]
        assert len(got) == 4 and all("confirmed_at" in r for r in got)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL MEMORY-GUARD TESTS PASSED")
