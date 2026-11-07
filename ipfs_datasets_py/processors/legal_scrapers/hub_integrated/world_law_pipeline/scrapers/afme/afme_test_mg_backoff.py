#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""Focused tests: MG post() bounded exponential backoff for RemoteDisconnected/5xx."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, time
os.environ["AFME_MG_POST_MAX_TRIES"] = "4"
os.environ["AFME_MG_POST_BACKOFF_BASE"] = "0.05"
os.environ["AFME_MG_POST_BACKOFF_CAP"] = "0.2"
# Keep disk confirm short if disk_check is hit (not expected here)
os.environ.setdefault("AFME_DISK_CONFIRM_SECS", "0.2")
os.environ.setdefault("AFME_DISK_RETRY_MAX_SECS", "0.2")
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/out"))

import afme_mg_cnlegis as M
from afme_live import Live
import requests

# Force module knobs from env (import may have bound them)
M.POST_MAX_TRIES = 4
M.POST_BACKOFF_BASE = 0.05
M.POST_BACKOFF_CAP = 0.2

passed = 0
def ok(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL {name}: {detail}"); sys.exit(1)
    print(f"OK   {name}"); passed += 1

sleeps = []
real_sleep = time.sleep
def fake_sleep(s):
    sleeps.append(s)
    # do not actually sleep long
real_sleep  # keep ref
M.time.sleep = fake_sleep
# also patch module-level time used via `import time` in mg — it uses time.sleep directly
import time as _t
_orig = _t.sleep
_t.sleep = fake_sleep

class FakeResp:
    def __init__(self, status=200, content=b'{"aaData":[]}', headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.text = content.decode()
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)
    def json(self):
        import json; return json.loads(self.content)

class FakeSession:
    def __init__(self, plan):
        self.plan = list(plan); self.calls = 0
        self.headers = {}; self.trust_env = False; self.proxies = {}
    def post(self, url, data=None, timeout=None):
        self.calls += 1
        if not self.plan:
            return FakeResp()
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

live = Live(0.0)  # no polite delay for unit test speed
# 1) RemoteDisconnected then success
from http.client import RemoteDisconnected
from urllib3.exceptions import ProtocolError
live.s = FakeSession([
    requests.ConnectionError(ProtocolError("Connection aborted.", RemoteDisconnected("Remote end closed connection without response"))),
    FakeResp(200, b'{"ok":1}'),
])
sleeps.clear()
r = M.post(live, M.BASE + "x", {"a": 1})
ok("recovers_after_remotedisconnect", r.status_code == 200)
ok("retried_once", live.s.calls == 2, live.s.calls)
ok("slept_backoff", len(sleeps) >= 1 and sleeps[0] <= M.POST_BACKOFF_CAP, sleeps)

# 2) persistent ConnectionError -> TransientHostError after max tries
live.s = FakeSession([requests.ConnectionError("reset")] * 10)
sleeps.clear(); t0 = _orig and time.time()
raised = False
try:
    M.post(live, M.BASE + "x", {})
except M.TransientHostError as e:
    raised = True
    ok("persistent_raises", "neterr" in str(e), str(e))
ok("persistent_did_raise", raised)
ok("persistent_calls_bounded", live.s.calls == M.POST_MAX_TRIES, live.s.calls)
ok("backoff_capped", all(s <= M.POST_BACKOFF_CAP + 1e-9 for s in sleeps if s > 0.001), sleeps)
# exponential growth in retry sleeps (ignore polite-interval zeros)
retry_sleeps = [s for s in sleeps if s >= M.POST_BACKOFF_BASE - 1e-9]
ok("exponential_nondecreasing", retry_sleeps == sorted(retry_sleeps), retry_sleeps)

# 3) 503 then success
live.s = FakeSession([FakeResp(503), FakeResp(200, b'{}')])
sleeps.clear()
r = M.post(live, M.BASE + "x", {})
ok("recovers_after_5xx", r.status_code == 200 and live.s.calls == 2)

# 4) challenge never retried
live.s = FakeSession([FakeResp(403, b"Just a moment... cf-browser-verification",
                               {"Server": "cloudflare", "cf-mitigated": "challenge"})])
# is_challenge looks at body/headers — craft body that matches
live.s = FakeSession([FakeResp(200, b"<html>cf-browser-verification Just a moment...</html>",
                               {"cf-mitigated": "challenge"})])
chal = False
try:
    M.post(live, M.BASE + "x", {})
except SystemExit as e:
    chal = "skip_challenge" in str(e)
ok("challenge_no_retry", chal and live.s.calls == 1, live.s.calls)

# 5) _retryable_net classification
ok("classifies_conn", M._retryable_net(requests.ConnectionError("x")))
ok("classifies_timeout", M._retryable_net(requests.Timeout("x")))
ok("rejects_http", not M._retryable_net(requests.HTTPError("400")))

_t.sleep = _orig
print(f"ALL {passed} checks passed")
