"""Sample archived d1-law pages per host and report robots meta flags (uses ArchiveFetcher only)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive.core import ArchiveFetcher, Capture, ArchiveError
from robots_meta import robots_meta_flags
W = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_archive_work/_meta/")
fx = ArchiveFetcher()
out = []
sample = json.load(open(W + "d1_sample.json"))
extra = []
try:  # en5: whatever the listing has (no doc pages matched), sample a few html captures
    caps = fx.wb_captures("en5-jg.d1-law.com/", "prefix", collapse="urlkey", max_rows=1500000)
    html = [c for c in caps if (c.mime or "").startswith("text/html") and c.status == 200]
    print("en5 captures", len(caps), "html", len(html), flush=True)
    extra = html[:: max(1, len(html) // 6)][:6]
except ArchiveError as e:
    print("en5 listing failed", e)
for c in [Capture(**r["caps"][0]) for r in sample] + extra:
    try:
        d = fx.fetch_capture(c)
        fl = robots_meta_flags(d.body, content_type=d.content_type)
        out.append({"url": c.original_url, "ts": c.timestamp, "flags": fl, "len": len(d.body)})
    except ArchiveError as e:
        out.append({"url": c.original_url, "ts": c.timestamp, "error": str(e)[:120]})
    print(out[-1], flush=True)
json.dump(out, open(W + "d1_sample_result.json", "w"), indent=1)
