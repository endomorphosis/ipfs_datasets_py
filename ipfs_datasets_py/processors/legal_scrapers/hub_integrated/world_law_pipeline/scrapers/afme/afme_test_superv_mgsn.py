#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""Focused tests for afme_superv_mgsn (no real long sleeps)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, sys, time
os.environ["AFME_SUPERV_BACKOFF_INIT_S"] = "1200"
os.environ["AFME_SUPERV_BACKOFF_CAP_S"] = str(6 * 3600)
os.environ["AFME_SUPERV_POLL_S"] = "1"
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/out"))

# Import after env
import afme_superv_mgsn as S

passed = 0
def ok(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL {name}: {detail}"); sys.exit(1)
    print(f"OK   {name}"); passed += 1

# Force knobs
S.BACKOFF_INIT = 1200.0
S.BACKOFF_CAP = 6 * 3600.0

# 1) schedule_deferred exponential growth, capped
t = {"backoff_s": S.BACKOFF_INIT, "status": "pending"}
t0 = time.time()
S.schedule_deferred(t, "test1")
ok("defer_status", t["status"] == "deferred")
ok("defer_wait_init", abs((t["next_retry_at"] - t0) - S.BACKOFF_INIT) < 2.0, t["next_retry_at"] - t0)
ok("defer_backoff_doubled", t["backoff_s"] == S.BACKOFF_INIT * 2, t["backoff_s"])
S.schedule_deferred(t, "test2")
ok("defer_wait_2x", abs((t["next_retry_at"] - time.time()) - S.BACKOFF_INIT * 2) < 3.0, t)
# grow until cap
for _ in range(20):
    S.schedule_deferred(t, "x")
ok("defer_capped", t["backoff_s"] == S.BACKOFF_CAP, t["backoff_s"])

# 2) schedule_ok reset
S.schedule_ok(t, "complete", complete=True)
ok("ok_complete", t["status"] == "complete" and t["backoff_s"] == S.BACKOFF_INIT)
S.schedule_ok(t, "idle", complete=False)
ok("ok_pending", t["status"] == "pending")

# 3) pick_due prefers due targets, skips complete
st = S.load_state()
st["targets"]["MG"]["status"] = "complete"
st["targets"]["MG"]["next_retry_at"] = 0
st["targets"]["SN"]["status"] = "deferred"
st["targets"]["SN"]["next_retry_at"] = time.time() + 9999
ok("pick_none_when_future", S.pick_due(st, time.time()) is None)
st["targets"]["SN"]["next_retry_at"] = time.time() - 1
ok("pick_sn", S.pick_due(st, time.time()) == "SN")

# 4) all_complete
st["targets"]["SN"]["status"] = "complete"
ok("all_complete", S.all_complete(st))

# 5) targets are MG+SN only
ok("targets", S.TARGETS == ("MG", "SN"))

# 6) init backoff in 15–30 min range
ok("init_range", 900 <= S.BACKOFF_INIT <= 1800, S.BACKOFF_INIT)
ok("cap_6h", S.BACKOFF_CAP == 6 * 3600)

# 7) empty/json retry still works in mg module
os.environ["AFME_MG_POST_MAX_TRIES"] = "3"
os.environ["AFME_MG_POST_BACKOFF_BASE"] = "0.01"
os.environ["AFME_MG_POST_BACKOFF_CAP"] = "0.05"
import importlib
import afme_mg_cnlegis as M
importlib.reload(M)
M.POST_MAX_TRIES = 3
M.POST_BACKOFF_BASE = 0.01
M.POST_BACKOFF_CAP = 0.05
from afme_live import Live
import requests
sleeps = []
import time as _t
_orig = _t.sleep
_t.sleep = lambda s: sleeps.append(s)
class FakeResp:
    def __init__(self, status=200, content=b""):
        self.status_code = status; self.content = content; self.headers = {}
        self.text = content.decode(errors="replace")
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError(str(self.status_code))
    def json(self):
        import json as J; return J.loads(self.content)
class FakeSession:
    def __init__(self, plan):
        self.plan = list(plan); self.calls = 0
        self.headers = {}; self.trust_env = False; self.proxies = {}
    def post(self, *a, **k):
        self.calls += 1
        item = self.plan.pop(0)
        if isinstance(item, Exception): raise item
        return item
live = Live(0.0)
live.s = FakeSession([FakeResp(200, b""), FakeResp(200, b'{"aaData":[]}')])
sleeps.clear()
r = M.post(live, M.BASE + "x", {}, expect_json=True)
ok("empty_body_retry", r.content == b'{"aaData":[]}' and live.s.calls == 2, live.s.calls)
_t.sleep = _orig

print(f"ALL {passed} checks passed")
