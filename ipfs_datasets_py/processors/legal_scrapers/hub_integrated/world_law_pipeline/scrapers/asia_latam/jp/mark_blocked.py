#!/usr/bin/env python3
"""Mark blocked seeds in state and write staging/asia_latam/_blocked_jp.csv
(d1-law.com robots_unreachable, g-reiki.net / h-chosonkai unreachable, robots.txt disallows)."""
import csv, json, os, sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).parent))
from jp_reiki import blocked_reason, load_state, save_state, now_utc, STAGE, classify
seeds = json.load(open(Path(__file__).parent / "seeds_places.json"))
rows = []
for s in seeds:
    st = load_state(s["seed_id"])
    url = st.get("detected_url") or s["url"]
    why = blocked_reason(url) or blocked_reason(s["url"])
    if why:
        if st.get("status") != "blocked":
            st.update(status="blocked", reason=why, blocked_host=urlparse(url).netloc, blocked_at=now_utc())
            save_state(s["seed_id"], st)
        rows.append([s["seed_id"], s["pref"], s["name"], s.get("jis_code"), s.get("place_id"), url, urlparse(url).netloc,
                     st.get("vendor") or classify(s["url"]), why, st.get("n_docs", 0)])
    elif st.get("status") == "skipped" and "robots.txt disallow" in (st.get("reason") or ""):
        rows.append([s["seed_id"], s["pref"], s["name"], s.get("jis_code"), s.get("place_id"), url, urlparse(url).netloc,
                     st.get("vendor") or classify(s["url"]), "robots_disallow", st.get("n_docs", 0)])
out = STAGE / "_blocked_jp.csv"
tmp = out.with_name(out.name + ".tmp")
with open(tmp, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["seed_id", "pref", "name", "jis_code", "place_id", "url", "host", "vendor", "reason", "docs_staged_before_block"])
    w.writerows(rows)
    fh.flush(); os.fsync(fh.fileno())
os.replace(tmp, out)
from collections import Counter
print(out, Counter(r[8] for r in rows), "staged-before-block docs:", sum(r[9] for r in rows))
