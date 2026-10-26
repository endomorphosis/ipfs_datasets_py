"""Block until the box-wide Wayback breaker is closed. When a probe is due, triggers it via slot('wayback')
(one prober box-wide, at most every 30 min; losers just keep waiting). Exit 0 when closed."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import logging, sys, time
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ratelimit as rl
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
while True:
    b = rl.breaker_status()
    if b.get("state") != "open":
        logging.info("wayback breaker closed (%s), spacing %.0fs", b.get("closed_by"), b.get("spacing_now", 2))
        sys.exit(0)
    if rl.wayback_available():                     # probe due
        try:
            with rl.slot("wayback", lane="national") as r:
                r.ok(None)                         # the probe inside the gate already succeeded
        except rl.SlotBusy as e:
            logging.info("still down: %s", e)
        continue
    time.sleep(min(300, max(10, b.get("next_probe_in", 60))))
