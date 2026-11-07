"""Union HF-published ES doc_ids into es_bop done-lists; move backward cursors past the oldest published day (idempotent)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,re,glob,os,shutil,time
from datetime import date,timedelta
ST=(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/asia_latam/_state/es_bop")
PFX=[("acoruna","BOPC-"),("caceres","BOPCC-"),("alava","BOTHA-"),("bizkaia","BOB-"),("barcelona","BOPB-"),("girona","BOPG-"),
     ("tarragona","BOPT-"),("toledo","BOPTO-"),("alicante","BOPA-"),("avila","AV-"),("bocm","BOCM-"),("borm","BORM-"),("cadiz","CA-"),
     ("castellon","CS-"),("cordoba","CO-"),("gipuzkoa","BOG-"),("granada","BOP-GRA-"),("guadalajara","GU-"),("huesca","BOPH-"),
     ("leon","BOP-LE-"),("lugo","LU-"),("ourense","OU-"),("soria","SO-")]
PFX.sort(key=lambda x:-len(x[1]))
pub={}
for l in open(os.path.dirname(__file__)+"/es_docids.jsonl"):
    r=json.loads(l); d=r.get("doc_id") or ""
    for g,p in PFX:
        if d.startswith(p):
            pub.setdefault(g,[]).append((d,(r.get("published_date") or "")[:10])); break
ts=time.strftime("%Y%m%dT%H%M%S")
for g,lst in sorted(pub.items()):
    f=f"{ST}/{g}.json"; s=json.load(open(f)) if os.path.exists(f) else {"gazette":g,"done":{}}
    if os.path.exists(f) and not os.path.exists(f+".bak_pre_hfsync"): shutil.copy(f,f+".bak_pre_hfsync")
    done=s.setdefault("done",{}); before=len(done)
    for d,_ in lst: done[d]=1
    dates=sorted(x for _,x in lst if re.match(r"\d{4}-\d\d-\d\d$",x))
    old=s.get("cursor"); new=old
    if dates:
        tgt=(date.fromisoformat(dates[0])-timedelta(days=1)).isoformat()
        if not old or tgt<old: new=tgt
    s["cursor"]=new; s["hf_sync"]={"at":ts,"published":len(lst),"oldest_pub":dates[0] if dates else None,"newest_pub":dates[-1] if dates else None}
    if s.get("status")=="done_through_today": s["status"]="resumed_after_restore"
    json.dump(s,open(f,"w"))
    print(f"{g:12s} hf={len(lst):6d} done {before}->{len(done)} cursor {old} -> {new} pub[{dates[0] if dates else '-'}..{dates[-1] if dates else '-'}]")
