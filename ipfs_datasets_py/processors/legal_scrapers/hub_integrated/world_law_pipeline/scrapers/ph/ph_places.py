"""Build PH place list: candidate CSV + before_wp2 CSV + url_discovery (live hits) + place_codes.parquet (0 PH rows)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import pandas as pd, json, sys
GM=(_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/')
EXCL_QID={'Q1461','Q1475','Q1467'}  # Manila, Quezon City, Cebu City (blocked)
EXCL_NAME={'manila','city of manila','quezon city','cebu city','city of cebu'}
c=pd.read_csv(GM+'global_municipalities_candidate.csv',low_memory=False); c=c[c.country_code=='PH']
b=pd.read_csv(GM+'wd/urls/global_municipalities_candidate.before_wp2.csv',low_memory=False); b=b[b.country_code=='PH']
u=pd.read_csv(GM+'url_discovery.csv',low_memory=False); u=u[u.country_code=='PH']
pc=pd.read_parquet((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/codes/place_codes.parquet')); pc=pc[pc.country_code=='PH']
rows={}
for df,src in ((c,'candidate'),(b,'before_wp2')):
    for r in df.itertuples():
        d=rows.setdefault(r.place_id,dict(place_id=r.place_id,place_name=r.place_name,qid=r.qid,admin_level=r.admin_level,iso_3166_2=r.iso_3166_2,urls=[]))
        if isinstance(r.source_url,str) and r.source_url.startswith('http') and r.source_url not in d['urls']: d['urls'].append(r.source_url)
for r in u.itertuples():
    if r.place_id in rows and str(r.check) in ('ok','live','alive') :
        url=r.final_url if isinstance(r.final_url,str) and r.final_url else r.url
        if url not in rows[r.place_id]['urls']: rows[r.place_id]['urls'].append(url)
for pid in set(pc.place_id)-set(rows): rows[pid]=dict(place_id=pid,urls=[])
stats=dict(candidate=len(c),before_wp2=len(b),url_discovery=len(u),place_codes=len(pc),merged=len(rows),
  with_url=sum(1 for d in rows.values() if d['urls']))
ex=[d for d in rows.values() if d.get('qid') in EXCL_QID or str(d.get('place_name','')).lower() in EXCL_NAME]
for d in ex: rows.pop(d['place_id'])
stats['excluded']=[d['place_name'] for d in ex]; stats['after_excl']=len(rows); stats['after_excl_with_url']=sum(1 for d in rows.values() if d['urls'])
with open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/ph/_state/places.jsonl'),'w') as f:
    for d in rows.values(): f.write(json.dumps(d,ensure_ascii=False,default=str)+'\n')
print(json.dumps(stats,indent=1))
