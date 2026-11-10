"""Small CC CDX probes for BG/CY — index only, no WARC."""
import json, time, sys
from pathlib import Path
sys.path.insert(0, "/workspace/legal_scrapers/scrapers")
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
Path("/workspace/legal_scrapers/logs/cc_probe_round4.json").write_text(json.dumps(out, indent=2))
print("wrote cc_probe_round4.json", flush=True)
