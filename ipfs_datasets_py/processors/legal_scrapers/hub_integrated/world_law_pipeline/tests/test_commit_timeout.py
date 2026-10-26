"""Commit watchdog: a hanging create_commit is abandoned, the Hub history is checked, retried once, and on the
second timeout the repo's staged files stay in staging (synthetic data in /tmp; mocked Hub API)."""
import json, os, shutil, sys, tempfile, threading, time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import run_loop as RL  # noqa: E402

RELEASE = threading.Event()


class HangApi:
    """create_commit hangs (until RELEASE); optionally a commit 'lands' after the first hang."""
    def __init__(self, land_after_first=False):
        self.calls, self.landed, self.land_after_first = 0, [], land_after_first

    def list_repo_files(self, repo, repo_type=None):
        return []

    def list_repo_tree(self, *a, **k):
        return []

    def create_commit(self, **kw):
        self.calls += 1
        if self.land_after_first and self.calls == 1:
            self.landed.append(kw["commit_message"])
        RELEASE.wait(30)
        raise RuntimeError("released")

    def list_repo_commits(self, repo, repo_type=None):
        return [SimpleNamespace(title=m, commit_id=f"c{i}") for i, m in enumerate(self.landed)]

    def get_paths_info(self, *a, **k):
        return []

    def hf_hub_download(self, *a, **k):  # places guard: no places.parquet on the mock Hub yet
        from huggingface_hub.utils import EntryNotFoundError
        raise EntryNotFoundError("mock: no places.parquet")


def test_guarded_commit_retry_then_fail():
    api = HangApi()
    t0 = time.time()
    try:
        RL.guarded_commit(api, 0.3, time.time() + 60, "t 1/1", repo_id="r", repo_type="dataset", operations=[],
                          commit_message="msg A")
        raise AssertionError("expected CommitTimeout")
    except RL.CommitTimeout:
        pass
    assert api.calls == 2 and time.time() - t0 < 5


def test_guarded_commit_landed_no_retry():
    api = HangApi(land_after_first=True)
    c = RL.guarded_commit(api, 0.3, time.time() + 60, "t 1/1", repo_id="r", repo_type="dataset", operations=[],
                          commit_message="msg B")
    assert api.calls == 1 and c.oid == "c0"


def test_guarded_commit_no_retry_after_deadline():
    api = HangApi()
    try:
        RL.guarded_commit(api, 0.2, time.time() - 1, "t 1/1", repo_id="r", repo_type="dataset", operations=[],
                          commit_message="msg C")
    except RL.CommitTimeout:
        pass
    assert api.calls == 1


def test_run_once_timeout_leaves_staging():
    tmp = Path(tempfile.mkdtemp(prefix="wl_hang_"))
    import huggingface_hub
    orig = huggingface_hub.HfApi
    api = HangApi()
    huggingface_hub.HfApi = lambda *a, **k: api
    try:
        sys.path.insert(0, str(HERE / "tests"))
        from test_hold_policy import base, w
        f = tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl"
        w(f, [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
        rc = RL.main(["--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
                      "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "q"), "--held", str(tmp / "h"),
                      "--overrides", str(tmp / "none.json"), "--once", "--no-prune", "--commit-timeout", "0.3",
                      "--repo", "test/muni", "--national-repo", "test/nat"])
        assert rc == 0
        assert f.exists(), "staged file must stay for the next run"
        assert not (tmp / "processed").exists() or not any((tmp / "processed").rglob("*.jsonl"))
        assert not (tmp / "state" / "ledger.jsonl").exists() or (tmp / "state" / "ledger.jsonl").read_text() == ""
        summ = json.loads((tmp / "state" / "runs.jsonl").read_text().splitlines()[-1])
        assert summ.get("commit_timeout") == 1 and summ.get("upload_failed") == 1, summ
        assert api.calls == 2
        info = json.loads((tmp / "state" / "run_loop.lock").read_text())
        assert info["pid"] == os.getpid() and info["started_at"] and info["heartbeat_at"]
    finally:
        huggingface_hub.HfApi = orig
        RL._LOCK["f"] = None
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_deadline_stops_before_commit():
    tmp = Path(tempfile.mkdtemp(prefix="wl_dl_"))
    import huggingface_hub
    orig = huggingface_hub.HfApi
    api = HangApi()
    huggingface_hub.HfApi = lambda *a, **k: api
    try:
        sys.path.insert(0, str(HERE / "tests"))
        from test_hold_policy import base, w
        f = tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl"
        w(f, [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
        rc = RL.main(["--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
                      "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "q"), "--held", str(tmp / "h"),
                      "--overrides", str(tmp / "none.json"), "--once", "--no-prune", "--run-deadline", "0",
                      "--repo", "test/muni", "--national-repo", "test/nat"])
        assert rc == 0 and f.exists() and api.calls == 0
        summ = json.loads((tmp / "state" / "runs.jsonl").read_text().splitlines()[-1])
        assert summ.get("deadline_stop") == 1, summ
    finally:
        huggingface_hub.HfApi = orig
        RL._LOCK["f"] = None
        shutil.rmtree(tmp, ignore_errors=True)


def test_stale_lock_reported_not_killed():
    tmp = Path(tempfile.mkdtemp(prefix="wl_lock_"))
    try:
        lp = tmp / "run_loop.lock"
        lp.write_text(json.dumps({"pid": os.getpid(), "started_at": "2020-01-01T00:00:00Z",
                                  "heartbeat_at": "2020-01-01T00:00:00Z", "phase": "commit"}))
        rep = RL.lock_holder_report(lp, tmp)
        assert rep["stale"] and rep["pid_alive"] and (tmp / "stale_lock_alert.json").exists()
        import fcntl
        holder = open(lp, "a+")
        fcntl.flock(holder, fcntl.LOCK_EX)
        rc = RL.main(["--state", str(tmp), "--once", "--dry-run", "--no-hub-listing", "--staging", str(tmp / "s"),
                      "--repo", "test/muni", "--national-repo", "test/nat"])
        assert rc == 2 and json.loads(lp.read_text())["pid"] == os.getpid()  # holder's info not truncated
        holder.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    RELEASE.set()
    print("ALL COMMIT-TIMEOUT TESTS PASSED")
    sys.stdout.flush()
    os._exit(0)  # abandoned daemon commit threads may still hold stdout's lock at interpreter shutdown
