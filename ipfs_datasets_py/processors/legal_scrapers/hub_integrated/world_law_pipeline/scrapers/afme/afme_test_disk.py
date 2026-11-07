#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""Focused tests for afme_common multi-source disk confirm (no network, no long sleeps)."""
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
os.environ["AFME_DISK_CONFIRM_SECS"] = "0.2"
os.environ["AFME_DISK_CONFIRM_SAMPLES"] = "3"
os.environ["AFME_DISK_RETRY_MAX_SECS"] = "0.4"
os.environ["AFME_DISK_RETRY_SLEEP_SECS"] = "0.1"
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/out"))
import afme_common as C

# Reload knobs from env (module may have already bound defaults at import)
C.DISK_CONFIRM_SECS = float(os.environ["AFME_DISK_CONFIRM_SECS"])
C.DISK_CONFIRM_SAMPLES = int(os.environ["AFME_DISK_CONFIRM_SAMPLES"])
C.DISK_RETRY_MAX_SECS = float(os.environ["AFME_DISK_RETRY_MAX_SECS"])
C.DISK_RETRY_SLEEP_SECS = float(os.environ["AFME_DISK_RETRY_SLEEP_SECS"])

passed = 0

def ok(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL {name}: {detail}"); sys.exit(1)
    print(f"OK   {name}"); passed += 1

# 1) live probe returns multi-source vals and is above floor right now
p = C.disk_probe()
ok("probe_has_min", p.get("min_gib") is not None, p)
ok("probe_multi_source", sum(1 for k in ("df_avail_gib","statvfs_avail_gib","shutil_free_gib") if p.get(k) is not None) >= 2, p)
ok("probe_above_floor_now", p["min_gib"] >= C.DISK_STOP_GIB, p)

# 2) disk_check passes immediately when healthy
free = C.disk_check()
ok("disk_check_healthy", free is not None and free >= C.DISK_STOP_GIB, free)

# 3) one-shot false low then recovery must NOT stop
seq = [
    {"path":"x","device":1,"df_avail_gib":7.0,"statvfs_avail_gib":7.1,"shutil_free_gib":7.2,"min_gib":7.0,"ok":False},
    {"path":"x","device":1,"df_avail_gib":22.0,"statvfs_avail_gib":22.1,"shutil_free_gib":22.2,"min_gib":22.0,"ok":True},
]
calls = {"n": 0}
real_probe = C.disk_probe
def fake_probe(path=C.ROOT):
    i = min(calls["n"], len(seq)-1); calls["n"] += 1
    return dict(seq[i])
C.disk_probe = fake_probe
try:
    v = C.disk_check()
    ok("false_low_recovered", v is not None and v >= C.DISK_STOP_GIB, v)
    ok("false_low_used_confirm", calls["n"] >= 2, calls["n"])
except C.DiskLow as e:
    print(f"FAIL false_low_recovered: raised {e}"); sys.exit(1)
finally:
    C.disk_probe = real_probe

# 4) persistent low across confirm + retry MUST stop
calls = {"n": 0}
low = {"path":"x","device":1,"df_avail_gib":7.5,"statvfs_avail_gib":7.6,"shutil_free_gib":7.4,"min_gib":7.4,"ok":False}
def always_low(path=C.ROOT):
    calls["n"] += 1
    return dict(low)
C.disk_probe = always_low
raised = False
t0 = time.time()
try:
    C.disk_check()
except C.DiskLow as e:
    raised = True
    ok("persistent_low_raises", True, str(e))
    ok("persistent_low_message", "persisted" in str(e) or "confirm" in str(e), str(e))
finally:
    C.disk_probe = real_probe
ok("persistent_low_did_raise", raised)
ok("persistent_low_took_confirm_retry", time.time()-t0 >= 0.2, time.time()-t0)
ok("persistent_low_multi_samples", calls["n"] >= 3, calls["n"])

# 5) floors unchanged
ok("floor_10", C.DISK_STOP_GIB == 10.0)
ok("warn_12", C.DISK_WARN_GIB == 12.0)

print(f"ALL {passed} checks passed")
