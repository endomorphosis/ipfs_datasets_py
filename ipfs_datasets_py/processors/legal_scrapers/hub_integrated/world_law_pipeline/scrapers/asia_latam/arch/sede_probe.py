"""One-off: Wayback URL patterns for a few sedelectronica.es hosts (lane asia_latam, shared fetcher)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, collections, re, json
os.environ.setdefault("ARCHIVE_LANE", "asia_latam")
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ArchiveFetcher
fx = ArchiveFetcher(lane="asia_latam", use_cc=False) if "use_cc" in ArchiveFetcher.__init__.__code__.co_varnames else ArchiveFetcher(lane="asia_latam")
out = {}
for h in ["calp.sedelectronica.es", "ciudadrodrigo.sedelectronica.es"]:
    caps = fx.wb_captures(h + "/", "prefix", collapse="urlkey", max_rows=50000)
    pat = collections.Counter(re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<UUID>", re.sub(r"https?://[^/]+", "", c.original_url).split("?")[0])[:70] for c in caps)
    out[h] = {"n": len(caps), "top": pat.most_common(25), "sample": [c.original_url for c in caps if "board" in c.original_url or "doc" in c.original_url][:15]}
    print(h, len(caps), flush=True)
json.dump(out, open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_archive_work/_meta/sede_probe.json"), "w"), indent=1)
print("done")
