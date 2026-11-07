"""Small CC CDX probes for BG/CY — index only, no WARC."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, time, sys
from pathlib import Path
sys.path.insert(0, str(_SCRAPERS) + "/scrapers")
import archive_fallbacks as af

queries = [
    ("dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=", 50),
    ("dv.parliament.bg/DVWeb/", 40),
    ("www.mof.gov.cy/mof/gpo/gazette.nsf", 40),
    ("mof.gov.cy/mof/gpo/gazette.nsf/*/$file/", 30),
]
results = []
for q, lim in queries:
    t0 = time.time()
    hits, err = [], None
    try:
        hits = af.search_common_crawl(q, limit=lim) or []
    except Exception as e:
        err = str(e)
        hits = []
    secs = round(time.time() - t0, 1)
    mimes = {}
    samples = []
    for h in hits:
        m = (h.get("mime") or h.get("mimetype") or "?")
        mimes[m] = mimes.get(m, 0) + 1
        if len(samples) < 3:
            samples.append({k: h.get(k) for k in ("url","original","mime","timestamp","filename","status") if h.get(k)})
    results.append({"query": q, "limit": lim, "hit_count": len(hits), "secs": secs, "mimes": mimes, "err": err, "samples": samples})
    print(f"q={q!r} limit={lim} hits={len(hits)} secs={secs} mimes={mimes} err={err}", flush=True)

out = {"round": 4, "queries": results}
Path(str(_SCRAPERS) + "/logs/cc_probe_round4.json").write_text(json.dumps(out, indent=2))
print("wrote cc_probe_round4.json", flush=True)
