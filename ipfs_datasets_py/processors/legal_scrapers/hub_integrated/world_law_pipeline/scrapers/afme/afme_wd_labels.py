"""Fetch labels+aliases (+P131) for a country's candidate QIDs via Wikidata wbgetentities (50/batch, 1 s). usage: afme_wd_labels.py CC en,ar"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,sys,time,urllib.request,urllib.parse,os
CC=sys.argv[1]; langs=sys.argv[2]; out=f"/workspace/world_law/out/afme/_labels/{CC}.jsonl"
done={json.loads(l)["qid"] for l in open(out)} if os.path.exists(out) else set()
q=sorted({r["qid"] for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]==CC and r["qid"] and r["qid"] not in done})
UA="world-municipal-law-research/1.0 (afme lane)"
with open(out,"a") as f:
    for i in range(0,len(q),50):
        u="https://www.wikidata.org/w/api.php?"+urllib.parse.urlencode({"action":"wbgetentities","ids":"|".join(q[i:i+50]),"props":"labels|aliases","languages":langs,"format":"json"})
        for t in range(4):
            try: ents=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=60).read())["entities"]; break
            except Exception: time.sleep(10*(t+1))
        else: continue
        time.sleep(1)
        for k,e in ents.items():
            f.write(json.dumps({"qid":k,"labels":{l:v["value"] for l,v in e.get("labels",{}).items()},"aliases":{l:[a["value"] for a in v] for l,v in e.get("aliases",{}).items()}},ensure_ascii=False)+"\n")
print(CC,"done",len(q))
