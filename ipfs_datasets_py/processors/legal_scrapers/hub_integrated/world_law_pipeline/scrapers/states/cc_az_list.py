"""2026-10-28 (Benjamin): AZ ARS URL discovery from Common Crawl (index.commoncrawl.org via the shared archive module,
lane=states; box-wide ratelimit + cooldowns). Wayback CDX checkpoint (data/cdx_parts) is kept untouched.
Resumable: one finished file per crawl in data/cc_az_parts/<crawl>.jsonl; deferred crawls are retried next run.
Output: data/archive/az_ars_cc.jsonl (newest 200 html capture per section URL, with WARC pointer).
usage: cc_az_list.py [NCRAWLS]   (0 = all crawls). Exit 75 = some crawls still deferred."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, time, re
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
os.environ.setdefault("ARCHIVE_LANE", "states")
from archive import ArchiveFetcher, ArchiveTransient
from common import check_guards as _cg  # noqa: E402
D = (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/states/data")
PARTS = f"{D}/cc_az_parts"; OUT = f"{D}/archive/az_ars_cc.jsonl"
RX = re.compile(r"azleg\.gov(?::\d+)?/ars/(\d+[A-Z]?)/([0-9A-Z-]+)\.htm$", re.I)
os.makedirs(PARTS, exist_ok=True)
n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
fx = ArchiveFetcher(lane="states", cc_crawls=n, use_wayback=False, cc_max_wait=900)
crawls = fx.cc_crawls(); pending = 0
deadline = time.time() + float(os.environ.get("CC_AZ_MAX_SECS", "21600"))
queue = [c for c in crawls if not os.path.exists(f"{PARTS}/{c}.jsonl")]
tries = {}
while queue and time.time() < deadline:
    c = queue.pop(0); fn = f"{PARTS}/{c}.jsonl"
    try:
        caps = fx.cc_captures("www.azleg.gov/ars/", "prefix", crawls=[c], filters=["statuscode:200"], on_error="raise")
    except ArchiveTransient as e:
        tries[c] = tries.get(c, 0) + 1
        print(time.strftime("%FT%T"), "deferred", c, tries[c], repr(e)[:160], flush=True)
        if tries[c] < 8: queue.append(c)
        time.sleep(max(30, min(900, getattr(e, "not_before", 0) - time.time()))); continue
    except Exception as e:
        if getattr(e, "permanent", False):
            open(fn, "w").close(); print("permanent-empty", c, e, flush=True); continue
        tries[c] = tries.get(c, 0) + 1; print(time.strftime("%FT%T"), "fail", c, repr(e)[:160], flush=True)
        if tries[c] < 8: queue.append(c)
        time.sleep(60); continue
    _cg()
    with open(fn + ".tmp", "w") as f:
        for cap in caps:
            if RX.search(cap.original_url.split("?")[0]):
                f.write(json.dumps(cap.to_dict()) + "\n")
    os.replace(fn + ".tmp", fn)
    print(time.strftime("%FT%T"), c, len(caps), "caps", flush=True)
pending = sum(1 for c in crawls if not os.path.exists(f"{PARTS}/{c}.jsonl"))
best = {}
for c in crawls:
    fn = f"{PARTS}/{c}.jsonl"
    if not os.path.exists(fn):
        continue
    for line in open(fn):
        d = json.loads(line); m = RX.search(d["original_url"].split("?")[0])
        if "html" not in (d.get("mime") or "html"):
            continue
        k = f"{m.group(1).upper()}/{m.group(2).upper()}"
        if k not in best or d["timestamp"] > best[k]["timestamp"]:
            best[k] = d
with open(OUT + ".tmp", "w") as f:
    for k in sorted(best):
        f.write(json.dumps({"key": k, **best[k]}) + "\n")
os.replace(OUT + ".tmp", OUT)
print("unique section urls", len(best), "pending crawls", pending, flush=True)
sys.exit(75 if pending else 0)
