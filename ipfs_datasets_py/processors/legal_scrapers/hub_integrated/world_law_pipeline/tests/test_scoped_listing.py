"""Scoped Hub listing (replaces the full recursive listing): only data/<CC>/ + metadata/<CC>/ of the touched
countries are listed, stale shards are still deleted exactly, and a country whose listing fails after retries is
skipped with its staged files left in staging. Mocked Hub; synthetic data in /tmp."""
import json, shutil, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import run_loop as RL  # noqa: E402
import schema as _S  # noqa: E402
_S.BUCKETED_COUNTRIES = frozenset()  # flat-layout tests; hash buckets: test_buckets.py

RL.PREFIX_LISTING_BACKOFF_S = 0.0


class Err504(Exception):
    response = SimpleNamespace(status_code=504)


class NotFound(Exception):
    response = SimpleNamespace(status_code=404)


class HubMock:
    def __init__(self, files, fail_prefixes=(), fail_times=10**9):
        self.files, self.fail_prefixes, self.fail_times = dict(files), set(fail_prefixes), fail_times
        self.tree_calls, self.commits, self.fails = [], [], {}

    def list_repo_files(self, *a, **k):
        raise AssertionError("full recursive listing must not be used")

    def list_repo_tree(self, repo, path_in_repo=None, recursive=False, repo_type=None):
        self.tree_calls.append((repo, path_in_repo) if not recursive else (repo, path_in_repo, "recursive"))
        if path_in_repo in self.fail_prefixes and self.fails.get(path_in_repo, 0) < self.fail_times:
            self.fails[path_in_repo] = self.fails.get(path_in_repo, 0) + 1
            raise Err504("504 Gateway Timeout")
        pre = path_in_repo.rstrip("/") + "/"
        kids = {f[len(pre):].split("/")[0] for f in self.files.get(repo, set()) if f.startswith(pre)} \
            if isinstance(self.files, dict) else set()
        if not kids:
            raise NotFound("404 entry not found")
        if recursive:
            return iter([SimpleNamespace(path=f, type="file") for f in sorted(self.files[repo]) if f.startswith(pre)])
        out = []
        for k in sorted(kids):
            full = pre + k
            isdir = any(f.startswith(full + "/") for f in self.files[repo])
            out.append(SimpleNamespace(path=full, type="directory" if isdir else "file"))
        return iter(out)

    def create_commit(self, **kw):
        self.commits.append(kw)
        return SimpleNamespace(oid=f"c{len(self.commits)}", commit_url=f"https://x/commit/c{len(self.commits)}")

    def list_repo_commits(self, *a, **k):
        return []

    def get_paths_info(self, *a, **k):
        return []


def _run(tmp, api):
    import huggingface_hub
    orig = huggingface_hub.HfApi
    huggingface_hub.HfApi = lambda *a, **k: api
    try:
        return RL.main(["--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
                        "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "q"), "--held",
                        str(tmp / "h"), "--overrides", str(tmp / "none.json"), "--once", "--no-prune",
                        "--min-age", "0", "--repo", "test/muni", "--national-repo", "test/nat"])
    finally:
        huggingface_hub.HfApi = orig
        RL._LOCK["f"] = None


def test_list_prefix_retries_then_ok_and_404_is_empty():
    api = HubMock({"r": {"world_law/data/FR/a_html.parquet", "world_law/data/FR/b.s0001_html.parquet"}},
                  fail_prefixes={"world_law/data/FR"}, fail_times=2)
    got = RL.list_prefix(api, "r", "world_law/data/FR", attempts=4, backoff_s=0)
    assert got == {"world_law/data/FR/a_html.parquet", "world_law/data/FR/b.s0001_html.parquet"}
    assert RL.list_prefix(api, "r", "world_law/data/ZZ", backoff_s=0) == set()
    api2 = HubMock({"r": set()}, fail_prefixes={"world_law/data/FR"})
    try:
        RL.list_prefix(api2, "r", "world_law/data/FR", attempts=3, backoff_s=0)
        raise AssertionError("expected ListingFailed")
    except RL.ListingFailed:
        pass
    assert api2.fails["world_law/data/FR"] == 3


def test_scoped_listing_stale_deletes_and_failed_country_skipped():
    from test_hold_policy import base, w
    tmp = Path(tempfile.mkdtemp(prefix="wl_scoped_"))
    try:
        # run 1: FR place built and committed (hub empty)
        f1 = tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl"
        w(f1, [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
        api = HubMock({"test/muni": set(), "test/nat": set()})
        assert _run(tmp, api) == 0 and not f1.exists() and len(api.commits) == 1
        # run 2: hub has stale shards of wd_Q90 + another FR place + a NL place; DE listing returns 504 forever
        hub = {"world_law/data/FR/wd_Q90.s0001_html.parquet", "world_law/data/FR/wd_Q90.s0002_html.parquet",
               "world_law/data/FR/wd_Q900_html.parquet", "world_law/metadata/FR/wd_Q90.json",
               "world_law/data/FR/wd_Q91_html.parquet", "world_law/data/NL/wd_Q727_html.parquet",
               "world_law/data/DE/wd_Q64_html.parquet"}
        api = HubMock({"test/muni": hub, "test/nat": set()},
                      fail_prefixes={"world_law/data/DE", "world_law/metadata/DE"})
        f2 = tmp / "staging/eu/FR/wd_Q90.20261012T010000Zp0001.jsonl"
        w(f2, [base("m2", place_id="wd:Q90", country_code="FR", language="fr")])
        f3 = tmp / "staging/eu/DE/wd_Q64.20261012T010000Zp0001.jsonl"
        w(f3, [base("m3", place_id="wd:Q64", country_code="DE", language="de")])
        assert _run(tmp, api) == 0
        listed = {p for r, p in api.tree_calls if r == "test/muni"}
        assert "world_law/data/FR" in listed and "world_law/metadata/FR" in listed
        assert not any("/NL" in p for p in listed), "untouched countries must not be listed"
        assert "world_law" not in listed and "" not in listed
        assert len(api.commits) == 1
        ops = api.commits[0]["operations"]
        dels = {o.path_in_repo for o in ops if type(o).__name__ == "CommitOperationDelete"}
        adds = {o.path_in_repo for o in ops if type(o).__name__ == "CommitOperationAdd"}
        assert dels == {"world_law/data/FR/wd_Q90.s0001_html.parquet",
                        "world_law/data/FR/wd_Q90.s0002_html.parquet"}, dels
        assert "world_law/data/FR/wd_Q90_html.parquet" in adds
        assert not any("DE/" in a for a in adds | dels)
        assert not f2.exists() and f3.exists(), "failed-listing country stays staged"
        summ = json.loads((tmp / "state" / "runs.jsonl").read_text().splitlines()[-1])
        assert summ["places_skipped_listing_failed"] == 1 and summ["countries_skipped_listing_failed"] == 1
        led = [json.loads(l) for l in (tmp / "state" / "ledger.jsonl").read_text().splitlines()]
        assert not any(r["cc"] == "DE" for r in led)
        # card still lists every hub country (from the one-level country listing), incl. untouched NL
        readme = (tmp / "out" / "README.md").read_text()
        assert "NL" in readme
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stall_watchdog_progress_vs_stall():
    import time as _t

    def slow_pages():  # keeps making progress: never abandoned although total > stall_s
        for i in range(6):
            _t.sleep(0.1)
            yield SimpleNamespace(path=f"p/{i}", type="file")
    assert len(RL._iter_with_stall_watchdog(slow_pages, True, 0.3, 30, "t")) == 6

    def hang():
        yield SimpleNamespace(path="p/0", type="file")
        _t.sleep(5)
    t0 = _t.time()
    try:
        RL._iter_with_stall_watchdog(hang, True, 0.3, 30, "t")
        raise AssertionError("expected TimeoutError")
    except TimeoutError:
        pass
    assert _t.time() - t0 < 3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL SCOPED-LISTING TESTS PASSED")
