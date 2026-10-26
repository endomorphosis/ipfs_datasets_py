"""commit_repo BLOCKED guard: a new places.parquet that would shrink the Hub's (beyond tolerance), or a sharp drop in
local metadata places vs the Hub's rows of the repo, is never committed; run_loop exits 3 with a BLOCKED message
(synthetic data in /tmp; mocked Hub API; no network).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_places_guard.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import contextlib, io, json, shutil, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import run_loop as RL  # noqa: E402
from test_hold_policy import base, w  # noqa: E402

ARGS = SimpleNamespace(allow_places_shrink=False, places_drop_frac=0.01)


def guard(hub, n_rows, n_meta, args=ARGS):
    RL._HUB_PLACES["fn"] = hub
    try:
        return RL.places_guard(object(), "test/muni", Path("/tmp"), n_rows, n_meta, args)
    finally:
        RL._HUB_PLACES.clear()


def test_guard_tolerance_and_thresholds():
    hub = lambda api, repo, scratch: (1000, 900)  # noqa: E731
    assert guard(hub, 1000, 900) is None
    assert guard(hub, 991, 900) is None                      # within max(10, 1%) = 10 rows
    b = guard(hub, 989, 900)
    assert b and b.startswith("BLOCKED test/muni") and "989 rows vs 1000" in b, b
    assert guard(hub, 1200, 900) is None                     # growth is fine
    b = guard(hub, 1000, 850)                                # metadata places 850 < 900 * 0.95
    assert b and "local metadata places" in b, b
    assert guard(hub, 1000, 856) is None
    assert guard(lambda *a: (50, 50), 41, 41) is None        # small repo: absolute tolerance of 10 rows
    assert guard(lambda *a: (50, 50), 39, 39)


def test_guard_new_repo_override_and_lookup_failure():
    assert guard(lambda *a: None, 1, 1) is None              # no places.parquet on the Hub yet
    assert guard(lambda *a: (55379, 43408), 5, 3,
                 SimpleNamespace(allow_places_shrink=True, places_drop_frac=0.01)) is None

    def boom(*a):
        raise ConnectionError("hub down")
    b = guard(boom, 100, 100)
    assert b and b.startswith("BLOCKED") and "cannot read the Hub places.parquet" in b, b


class Api:
    def __init__(self):
        self.commits = []

    def list_repo_files(self, repo, repo_type=None):
        return []

    def list_repo_tree(self, *a, **k):
        return []

    def get_paths_info(self, *a, **k):
        return []

    def list_repo_commits(self, repo, repo_type=None):
        return []

    def create_commit(self, **kw):
        self.commits.append(kw["commit_message"])
        return SimpleNamespace(oid=f"c{len(self.commits)}", commit_url=f"u/c{len(self.commits)}")


def _run(tmp, api, hub_counts):
    import huggingface_hub
    orig = huggingface_hub.HfApi
    huggingface_hub.HfApi = lambda *a, **k: api
    RL._HUB_PLACES["fn"] = lambda a, repo, scratch: hub_counts.get(repo)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = RL.main(["--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
                          "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "q"),
                          "--held", str(tmp / "h"), "--overrides", str(tmp / "none.json"), "--once", "--no-prune",
                          "--no-us-pointers", "--repo", "test/muni", "--national-repo", "test/nat"])
    finally:
        huggingface_hub.HfApi = orig
        RL._HUB_PLACES.clear()
        if RL._LOCK["f"]:
            RL._LOCK["f"].close()
        RL._LOCK["f"] = None
    return rc, out.getvalue()


def test_run_once_blocked_commits_nothing_and_exits_3():
    tmp = Path(tempfile.mkdtemp(prefix="wl_guard_"))
    try:
        f = tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl"
        w(f, [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
        api = Api()
        rc, out = _run(tmp, api, {"test/muni": (55379, 43408)})  # out/ lost its metadata: 1 place vs 55k
        assert rc == 3, (rc, out)
        assert "BLOCKED test/muni" in out and "nothing committed" in out, out
        assert api.commits == [] and f.exists()
        assert not (tmp / "state" / "ledger.jsonl").exists() or not (tmp / "state" / "ledger.jsonl").read_text()
        summ = json.loads((tmp / "state" / "runs.jsonl").read_text().splitlines()[-1])
        assert summ["blocked"] and summ["blocked"][0].startswith("BLOCKED test/muni"), summ
        # same data, Hub not larger: the commit goes through and the staged file is ledgered
        rc, out = _run(tmp, api, {"test/muni": (1, 1)})
        assert rc == 0 and len(api.commits) == 1 and not f.exists(), (rc, out, api.commits)
        summ = json.loads((tmp / "state" / "runs.jsonl").read_text().splitlines()[-1])
        assert not summ["blocked"] and summ["commit_ids"] == ["c1"], summ
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PLACES-GUARD TESTS PASSED")
