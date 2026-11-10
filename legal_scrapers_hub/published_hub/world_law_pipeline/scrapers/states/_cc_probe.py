import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ArchiveFetcher
fx = ArchiveFetcher(cc_crawls=3, lane="states")
crawls = fx.cc_crawls()
print("crawls", crawls)
for url in sys.argv[1:]:
    for cr in crawls[:2]:
        try:
            caps = fx._cc_query(cr, url, "prefix", limit_pages=1)
            st = collections.Counter(c.status for c in caps)
            print(url, cr, len(caps), dict(st), [c.original_url for c in caps[:3]])
        except Exception as e:
            print(url, cr, "ERR", e)
