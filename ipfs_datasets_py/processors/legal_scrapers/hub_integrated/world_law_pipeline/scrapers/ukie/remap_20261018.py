#!/usr/bin/env python3
"""One-off re-map after the Normalizer's 2026-10-17 place decisions (canonical places, Greater London, no
'upcoming' LGR areas). Restages acts under current places; London-wide acts -> wd:Q23306."""
import json, sys
sys.argv = [sys.argv[0]]
import legislation_uk as L
R = L.Run()
FIX = {"ukla/2003/1": ["wd:Q23306"],                          # London Development Agency Act 2003
       "ukla/2013/6": ["wd:Q21695028", "wd:Q175945"],         # Humber Bridge Act 2013: East Riding + North Lincolnshire
       "ukla/2002/5": ["wd:Q213361"],                         # Milford Haven Port Authority Act 2002: Pembrokeshire
       "ukla/1994/15": ["wd:Q21885994", "wd:Q21272736"],      # Greater Nottingham LRT Act 1994: Nottingham + Notts CC
       "ukla/2006/2": ["wd:Q21683242"]}                       # Leicester City Council Act 2006
try:
    for k, pids in FIX.items():
        R.restage(k, pids, "normalizer_remap_20261017")
    # unmatched London-wide / duplicate-place items -> re-evaluate with the new rules
    rows = R.st.c.execute("SELECT key, info FROM items WHERE status='unmatched'").fetchall()
    for key, info in rows:
        title = json.loads(info)["title"]
        R.st.c.execute("DELETE FROM items WHERE key=?", (key,))
        R.st.c.commit()
        R.handle("ukla" if key.startswith("ukla/") else "lsi", {"id": f"{L.BASE}/id/{key}", "title": title, "xml": []})
finally:
    files = R.flush()
    print(json.dumps({"files": [f.rsplit('/', 1)[1] for f in files], **R.n}))
    R.st.summary()
