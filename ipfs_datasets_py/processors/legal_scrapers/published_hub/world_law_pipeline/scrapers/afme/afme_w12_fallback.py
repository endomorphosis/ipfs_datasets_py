"""afme_w12_fallback.py <CC> : after the live w12 full run, add live-failed places (no rows and robots/home/connect failure) to the arch cfg (and rebuild its 20-place test cfg)."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,sys,os
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import place_key
cc=sys.argv[1]; lc=cc.lower(); D=f"/workspace/world_law/out/afme"
live=json.load(open(f"{D}/{lc}_live_w12_cfg.json")); arch=json.load(open(f"{D}/{lc}_arch_w12_cfg.json"))
dn=f"{D}/{cc}/_au_done.tsv"; st={}
if os.path.exists(dn):
    for l in open(dn):
        k,_,j=l.rstrip("\n").partition("\t")
        try: st[k]=json.loads(j)
        except Exception: pass
have={p["place_id"] for p in arch["places"]}; add=0
from urllib.parse import urlparse
for p in live["places"]:
    s=st.get(place_key(p["place_id"],None,cc))
    if not s or s.get("rows") or p["place_id"] in have: continue
    pol=str(s.get("policy") or ""); err=str(s.get("err") or "")
    if pol.startswith(("robots_unreachable","robots_html")) or err.startswith("home") or "Error" in err or err.startswith("Conn"):
        q={"place_id":p["place_id"],"name":p["name"],"admin_level":p.get("admin_level","municipality"),"host":urlparse(p["site"]).netloc.lower().removeprefix("www."),"live_status":(pol+" "+err).strip()[:120]}
        arch["places"].append(q); add+=1
json.dump(arch,open(f"{D}/{lc}_arch_w12_cfg.json","w"),ensure_ascii=False,indent=0)
json.dump(dict(arch,places=arch["places"][:20],batch=arch["batch"]+"t"),open(f"{D}/{lc}_arch_w12_test_cfg.json","w"),ensure_ascii=False)
print(cc,"fallback added",add,"arch places",len(arch["places"]))
