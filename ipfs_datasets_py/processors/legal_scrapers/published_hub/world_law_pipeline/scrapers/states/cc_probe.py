"""Probe Common Crawl availability for archive-only sources (CC index only, newest N crawls, lane=states).
Writes data/cc_probe/<name>.txt (timestamp crawl status mime url) and a summary line per prefix."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, time, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
os.environ.setdefault("ARCHIVE_LANE", "states")
from archive import ArchiveFetcher

PREFIXES = {
    "bc": "www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/",
    "ab": "kings-printer.alberta.ca/documents/",
    "nsw": "legislation.nsw.gov.au/view/html/inforce/current/",
    "sa": "www.legislation.sa.gov.au/lz",
    "qc": "www.legisquebec.gouv.qc.ca/en/document/",
    "yt": "laws.yukon.ca/cms/images/LEGISLATION/",
    "vic_meta": "www.legislation.vic.gov.au/in-force/",
    "vic_content": "content.legislation.vic.gov.au/sites/default/files/",
}
OUT = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/cc_probe")
os.makedirs(OUT, exist_ok=True)
ncrawls = int(os.environ.get("CC_PROBE_CRAWLS", "3"))
fx = ArchiveFetcher(lane="states", cc_crawls=ncrawls, use_wayback=False, cc_max_wait=900)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deferq import DeferQueue, ArchiveTransient, not_before_for, listing_state  # noqa: E402
dq = DeferQueue(f"{OUT}/_deferred.tsv")   # ArchiveDeferred/transient: requeue >= not_before, move on (persisted)


def todo():
    for name in (sys.argv[1:] or PREFIXES):
        if not os.path.exists(f"{OUT}/{name}.txt") and not dq.held(name, name):
            yield name
    yield from dq.drain(log=lambda m: print(m, flush=True))


for name in todo():
    fn = f"{OUT}/{name}.txt"
    if os.path.exists(fn):
        continue
    t0 = time.time()
    try:
        caps = fx.cc_captures(PREFIXES[name], "prefix", filters=["statuscode:200"], on_error="raise", on_deferred="raise")
    except ArchiveTransient as e:
        nb = not_before_for(e, ["cc_index"]); dq.defer(name, nb, f"{type(e).__name__}:{e}", name)
        print(name, "DEFERRED until", time.strftime("%T", time.localtime(nb)), repr(e)[:160], flush=True); continue
    except Exception as e:
        print(name, "ERROR", repr(e)[:200], flush=True); continue
    st, nb = listing_state(caps)
    if st == "retry":                              # retryable .truncated gap: requeue, don't write a partial list
        dq.defer(name, nb, f"truncated:{caps.truncated_reason}", name)
        print(name, "TRUNCATED, requeued until", time.strftime("%T", time.localtime(nb)), flush=True); continue
    if name in dq:
        dq.clear(name)
    with open(fn + ".tmp", "w") as f:
        for c in caps:
            f.write(f"{c.timestamp} {c.crawl_id} {c.status} {c.mime} {c.original_url}\n")
    os.rename(fn + ".tmp", fn)
    urls = {c.original_url.split("?")[0] for c in caps}
    print(name, "captures", len(caps), "urls", len(urls), "crawls", dict(collections.Counter(c.crawl_id for c in caps)),
          f"{time.time()-t0:.0f}s", flush=True)
