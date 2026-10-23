#!/usr/bin/env python3
"""Find FI municipal rule-collection documents via Common Crawl index (ranged reads only, no WARC)."""
import sys, json, collections
import os; sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
import common_crawl_helper as cc
MUNIS = {  # Statistics Finland municipality code: (name, domain)
 "091":("Helsinki","hel.fi"),"049":("Espoo","espoo.fi"),"837":("Tampere","tampere.fi"),"092":("Vantaa","vantaa.fi"),
 "564":("Oulu","ouka.fi"),"853":("Turku","turku.fi"),"179":("Jyväskylä","jyvaskyla.fi"),"297":("Kuopio","kuopio.fi"),
 "398":("Lahti","lahti.fi"),"609":("Pori","pori.fi"),"286":("Kouvola","kouvola.fi"),"167":("Joensuu","joensuu.fi"),
 "405":("Lappeenranta","lappeenranta.fi"),"109":("Hämeenlinna","hameenlinna.fi"),"905":("Vaasa","vaasa.fi"),
 "743":("Seinäjoki","seinajoki.fi"),"698":("Rovaniemi","rovaniemi.fi"),"491":("Mikkeli","mikkeli.fi"),
 "285":("Kotka","kotka.fi"),"734":("Salo","salo.fi"),
}
RX = r"(?i)(hallintos(a|ä|%c3%a4)(a|ä|%c3%a4)nt|johtos(a|ä|%c3%a4)(a|ä|%c3%a4)nt|j(a|ä|%c3%a4)rjestyss(a|ä|%c3%a4)(a|ä|%c3%a4)nt|saanto|s(a|ä|%c3%a4)(a|ä|%c3%a4)nn(o|ö|%c3%b6)t|taksa|maksut.*\.pdf|rakennusj(a|ä|%c3%a4)rjestys|ymp(a|ä|%c3%a4)rist(o|ö|%c3%b6)nsuojelum(a|ä|%c3%a4)(a|ä|%c3%a4)r|j(a|ä|%c3%a4)tehuoltom(a|ä|%c3%a4)(a|ä|%c3%a4)r|taloussaanto|ohjes(a|ä|%c3%a4)(a|ä|%c3%a4)nt)"
COLS = ["CC-MAIN-2026-30","CC-MAIN-2026-21","CC-MAIN-2026-17","CC-MAIN-2026-08","CC-MAIN-2025-51"]
out = {}
for code,(name,dom) in MUNIS.items():
    try: p = cc.find_pointers(dom, COLS, status="200", mime_regex="pdf", url_regex=RX, max_records=400)
    except Exception as e: print(name, "ERR", repr(e)[:120], flush=True); continue
    seen = {}
    for x in p: seen.setdefault(x["url"].split("?")[0], x)
    out[code] = {"name":name,"domain":dom,"pointers":list(seen.values())}
    print(code, name, len(p), "unique", len(seen), flush=True)
json.dump(out, open(sys.argv[1] if len(sys.argv)>1 else "/tmp/fi_ptrs.json","w"), ensure_ascii=False)
