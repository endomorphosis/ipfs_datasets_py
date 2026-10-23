"""Slow wrapper around the copied shared/collect_cl.py (repo file unchanged).
1 worker, >=3 s between leychile obtxml requests, stops (exit 3) after 20 consecutive empty/failed responses."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, time, threading, logging
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/shared"))
import collect_cl as C
C.WORKERS = 1
C.SLEEP = 3.0
MIN_GAP, MAX_EMPTY = 3.0, 20
_lock = threading.Lock(); _last = [0.0]; _empty = [0]
_orig = C.fetch_xml_bytes
def fetch_xml_bytes(url):
    with _lock:
        w = _last[0] + MIN_GAP - time.time()
        if w > 0: time.sleep(w)
        try:
            body, u, how = _orig(url)
        finally:
            _last[0] = time.time()
        if how == "fail" and not body:
            _empty[0] += 1
            if _empty[0] >= MAX_EMPTY:
                logging.getLogger().error("STOP: %d consecutive empty/failed obtxml responses (throttling) - exiting", _empty[0])
                logging.shutdown(); os._exit(3)
        else:
            _empty[0] = 0
        return body, u, how
C.fetch_xml_bytes = fetch_xml_bytes
if __name__ == "__main__":
    C.main()
