#!/usr/bin/env python3
"""Block until the box-wide Wayback breaker is closed (archive/README.md, ratelimit v4). When a probe is due, triggers
it via slot('wayback') (one prober box-wide, at most every 30 min). Exit 0 when closed, 3 if a stop file appears.
  wb_wait.py [stopfile ...]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import logging, os, sys, time
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ratelimit as rl
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s wb_wait %(message)s")
stops = sys.argv[1:]
last = 0
while True:
    if any(os.path.exists(f) for f in stops):
        logging.info("stop file -> exit"); sys.exit(3)
    b = rl.breaker_status()
    if b.get("state") != "open":
        logging.info("wayback breaker closed (%s)", b.get("closed_by")); sys.exit(0)
    if rl.wayback_available():
        try:
            with rl.slot("wayback", lane=os.environ.get("ARCHIVE_LANE", "asia_latam")) as r:
                r.ok(None)
        except rl.SlotBusy as e:
            logging.info("still down: %s", e)
        continue
    if time.time() - last > 900:
        logging.info("breaker open; next probe in %ss", b.get("next_probe_in")); last = time.time()
    time.sleep(30)
