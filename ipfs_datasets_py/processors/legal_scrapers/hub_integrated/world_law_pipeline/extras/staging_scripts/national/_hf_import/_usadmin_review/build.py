# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import pickle,json,os,sys,collections,datetime
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from schema import validate_record, validate_file, place_key
rows=pickle.load(open('rows.pkl','rb')); drops=pickle.load(open('drops.pkl','rb'))
TS='20261014T233000Z'
base=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national/_hf_import')
by={r['doc_id']:r for r in rows}
# quarantine list
q=[]
for pid,did,(cat,why) in drops:
    r=by[did]
    q.append({"country_code":"US","place_key":place_key(pid),"doc_id":did,"reason":f"us_admin_cleanup:{cat}: {why}",
              "category":cat,"source_url":r['source_url'],"title":(r['title_native'] or '')[:200],
              "hf_legislation_type":r['em'].get('legislation_type'),"hf_pass":"parsed" if 'parsed' in r['em']['hf_path'] else "release"})
q.sort(key=lambda x:(x['place_key'],x['category'],x['doc_id']))
out={"generated_at":datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),"source_dataset":"justicedao/ipfs_state_admin_rules",
     "note":"Merge entries into state/doc_overrides.json['quarantine'] (fields country_code/place_key/doc_id/reason; extra fields informational). All rows already published to endomorphosis/world_national_law.",
     "counts":dict(collections.Counter(x['category'] for x in q)),"total":len(q),"quarantine":q}
p=f'{base}/us_admin_quarantine.json'; t=p+'.tmp'
json.dump(out,open(t,'w'),indent=1,ensure_ascii=False); os.rename(t,p)
# versions
dset={d for _,d,_ in drops}
first={(r['place_id'],r['em']['hf_source_id']):r for r in rows if 'parsed' not in r['em']['hf_path'] and r['em'].get('hf_source_id')}
pairs=[(r,first[(r['place_id'],r['em']['hf_source_id'])]) for r in rows if 'parsed' in r['em']['hf_path'] and (r['place_id'],r['em'].get('hf_source_id')) in first]
DROP={'cid','doc_order','html','html_title','extra_metadata','em','gnis'}
def rec(r,vm):
    o={k:v for k,v in r.items() if k not in DROP and v is not None}
    for k,v in r['em'].items():
        if v is not None and k not in o: o[k]=v
    sc=r['place_id'][-2:]
    o.update({"place_name":sc,"iso_3166_2":f"US-{sc}","state_code":sc,"admin_level":"adm1","platform":o['source_platform']})
    o['extra_metadata']=vm; return o
LBL={'release':'release:canonical_merged_daemon_cycle_0999_20260325_234135_cleaned','parsed':'parsed:US_ADMINISTRATIVE_RULES/parsed/parquet'}
per=collections.defaultdict(list)
for v,f in pairs:
    g=f['em']['hf_source_id']
    per[v['place_id']].append(rec(f,{"version_group":g,"version_label":LBL['release'],"version_index":1,"has_versions":[v['doc_id']],"is_latest_version":False}))
    per[v['place_id']].append(rec(v,{"version_group":g,"version_label":LBL['parsed'],"version_index":2,"version_of":f['doc_id'],"is_latest_version":True}))
od=f'{base}/us_admin_versions_pending'; os.makedirs(od,exist_ok=True)
tot=0;errs=0
for pid,rs in sorted(per.items()):
    for x in rs:
        e=validate_record(x); 
        if e: errs+=1; print(pid,x['doc_id'],e)
    fn=f'{od}/{place_key(pid)}.hf-versions{TS}.jsonl'; t=fn+'.tmp'
    with open(t,'w',encoding='utf-8') as fh:
        for x in rs: fh.write(json.dumps(x,ensure_ascii=False)+'\n')
        fh.flush(); os.fsync(fh.fileno())
    os.rename(t,fn); r=validate_file(fn); tot+=len(rs); print(os.path.basename(fn),len(rs),str(r)[:200])
print('total',tot,'errs',errs,'quarantine',len(q),out['counts'])
