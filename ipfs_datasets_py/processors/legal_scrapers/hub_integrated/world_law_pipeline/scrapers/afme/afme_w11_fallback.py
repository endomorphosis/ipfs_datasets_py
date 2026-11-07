"""afme_w11_fallback.py <CC> : after the live w11 full run, add live-failed places (no rows and robots/home/connect failure) to the arch cfg (and rebuild its 20-place test cfg)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,sys,os
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline")); from schema import place_key
cc=sys.argv[1]; lc=cc.lower(); D=f"{_WORLD}/out/afme"
live=json.load(open(f"{D}/{lc}_live_w11_cfg.json")); arch=json.load(open(f"{D}/{lc}_arch_w11_cfg.json"))
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
json.dump(arch,open(f"{D}/{lc}_arch_w11_cfg.json","w"),ensure_ascii=False,indent=0)
json.dump(dict(arch,places=arch["places"][:20],batch=arch["batch"]+"t"),open(f"{D}/{lc}_arch_w11_test_cfg.json","w"),ensure_ascii=False)
print(cc,"fallback added",add,"arch places",len(arch["places"]))
