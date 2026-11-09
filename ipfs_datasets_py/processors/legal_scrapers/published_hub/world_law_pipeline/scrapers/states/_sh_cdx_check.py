import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, ".")
os.environ.setdefault("ARCHIVE_LANE", "states")
import de_sh_wb
t = de_sh_wb.__dict__.get("TARGET") or None
from archive.core import ArchiveFetcher
fx = ArchiveFetcher(use_cc=False, lane="states")
H = de_sh_wb.HOST
for url, kw in [(f"{H}/jportal/portal/page/bsshoprod.psml?aiz=true&max=true", dict(collapse="urlkey")),
                (f"{H}/jportal/portal/page/bsshoprod.psml", dict(collapse="urlkey", filters=["original:.*quelle=jlink.*"]))]:
    import time
    for att in range(120):
        try:
            caps = fx.wb_captures(url, "prefix", page_size=5000, **kw); break
        except Exception as e:
            nb = getattr(e, "not_before", None) or time.time() + 120
            print("wait", type(e).__name__, int(nb - time.time()), flush=True); time.sleep(max(10, nb - time.time()))
    try:
        qs = collections.Counter("max=true" in c.original_url for c in caps)
        print(url[-60:], kw, len(caps), dict(qs), getattr(caps, "truncated", None), getattr(caps, "deferral", None))
        print("  e.g.", [c.original_url.split("query=")[-1][:40] for c in caps[:8]])
    except Exception as e:
        print("ERR", type(e).__name__, str(e)[:300])
