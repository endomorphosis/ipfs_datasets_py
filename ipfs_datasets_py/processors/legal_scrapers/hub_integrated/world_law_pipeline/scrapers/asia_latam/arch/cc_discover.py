#!/usr/bin/env python3
"""Background Common Crawl index listings (prefix/domain) for the lane's archive targets, so the jobs can fetch from
CC WARCs (data.commoncrawl.org, cheap) before Wayback. Results land in the shared CDX cache (resumable; a later
job run with --rediscover picks them up). Summary -> _archive_work/_cc_discover.json."""
import json, logging, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_common import WORK, ArchiveFetcher, setup, STOP  # noqa: E402

TARGETS = [a.split("|") for a in sys.argv[2:]] or [
    ["www1.g-reiki.net/", "prefix"], ["en3-jg.d1-law.com/", "prefix"], ["en5-jg.d1-law.com/", "prefix"],
    ["houmu.h-chosonkai.gr.jp/", "prefix"], ["peraturan.bpk.go.id/Details/", "prefix"],
    ["peraturan.bpk.go.id/Download/", "prefix"]]
setup("_cc_discover")
fx = ArchiveFetcher(cc_crawls=int(sys.argv[1]) if len(sys.argv) > 1 else 4)
out = {}
p = WORK / "_cc_discover.json"
if p.exists():
    out = json.loads(p.read_text())
for url, match in TARGETS:
    if STOP["flag"]:
        break
    t = time.time()
    caps = fx.cc_captures(url, match)
    trunc = bool(getattr(caps, "truncated", False))   # deferred mid-listing -> NOT complete (shared fetcher 2026-10-18)
    out[url] = {"captures": len(caps), "truncated": trunc,
                "not_before": getattr(getattr(caps, "deferral", None), "not_before", None), "crawls": sorted({c.crawl_id for c in caps}), "secs": round(time.time() - t),
                "fetcher": dict(fx.stats), "at": time.strftime("%Y-%m-%d %H:%M")}
    logging.info("%s %s", url, out[url])
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(out, indent=1)); os.replace(tmp, p)
    if trunc:
        logging.warning("%s listing truncated (deferred) -> stop; rerun after not_before", url)
        sys.exit(75)
