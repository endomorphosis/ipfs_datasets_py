#!/usr/bin/env python3
"""Idempotent hourly publisher for endomorphosis/world_courts (+ scrapers to endomorphosis/world_law_pipeline).
- builds parquet from data/*.jsonl into publish/ (deterministic), hashes everything
- uploads only when hashes changed since last successful push (state in publish/.upload_state.json)
- fcntl lock prevents overlapping runs; never deletes remote files except those it manages under data/ prefix
Usage: HF_TOKEN=... python upload_world_courts.py [--dry-run]"""
import os,sys,json,hashlib,fcntl,glob,shutil
import pandas as pd
from huggingface_hub import HfApi,CommitOperationAdd
ROOT="/workspace/world_courts";PUB=ROOT+"/publish";STATE=PUB+"/.upload_state.json"
DS="endomorphosis/world_courts";PIPE="endomorphosis/world_law_pipeline"
def sha(p): return hashlib.sha256(open(p,"rb").read()).hexdigest()
def flat_court(r):
    a=r.get("address") or {};g=r.get("geo") or {}
    return {"court_id":r["court_id"],"name":r.get("name"),"official_name":r.get("official_name"),"level":r.get("level"),"court_system":r.get("court_system"),
      "country_code":r["country_code"],"subdivision":r.get("subdivision"),"record_type":r.get("record_type","courthouse"),"license":r.get("license"),"geo_source":r.get("geo_source"),"upstream":r.get("upstream"),"subdivision_method":r.get("subdivision_method"),"hours":r.get("hours"),"email":r.get("email"),"jurisdiction":r.get("jurisdiction"),"county_fips":r.get("county_fips"),"parent_court_id":r.get("parent_court_id"),
      "street":a.get("street"),"city":a.get("city"),"postcode":a.get("postcode"),"lat":g.get("lat"),"lon":g.get("lon"),"phone":r.get("phone"),"website":r.get("website"),
      "wikidata":r.get("wikidata"),"place_ids":list(r.get("place_ids") or []),"place_match_method":r.get("place_match_method"),
      "source_url":r.get("source_url"),"source_kind":r.get("source_kind"),"site_policy":r.get("site_policy"),"sources_json":json.dumps(r.get("sources") or [],sort_keys=True),
      "needs_review":bool(r.get("needs_review",False)),"retrieved_at":r.get("retrieved_at")}
EU_CC="at be bg hr cy cz dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se eu".split()
def flat_court_eu(r):
    o=flat_court(r)
    for k in ("court_family","tier","level_basis","cdb_id","ecli_code","name_local","upstream_court_id","accepted_languages"):
        v=r.get(k);o[k]=json.dumps(v) if isinstance(v,(list,dict)) else v
    o["geoname_ids"]=list(r.get("geoname_ids") or []);o["upstream_json"]=json.dumps(r.get("upstream"),sort_keys=True) if r.get("upstream") else None
    return o
ROW_CC="nz in jp br mx za kr tw ph ar co cl ng ke sg my il pk bd th vn id tr eg sa ae pe ve ec gh et ma ru dz ua kz ir cn iq tz ug sn ci cm jo tn lb lk np mm".split()
import os as _os
_EX = "/workspace/world_courts/data/row/upload_cc.txt"
if _os.path.exists(_EX): ROW_CC += [c for c in open(_EX).read().split() if c not in ROW_CC]
def flat_court_row(r):
    o=flat_court(r)
    for k in ("name_local","record_note","facility_kind","geonames_city","geonames_admin1","geonames_admin2","admin_qid","operational_status"):
        v=r.get(k);o[k]=json.dumps(v) if isinstance(v,(list,dict)) else v
    o["geoname_ids"]=[str(x) for x in (r.get("geoname_ids") or [])];o["upstream_json"]=json.dumps(r.get("upstream"),sort_keys=True) if isinstance(r.get("upstream"),(dict,list)) else None
    return o
def build():
    os.makedirs(PUB+"/data",exist_ok=True);out={}
    def wr(name,rows):
        p=f"{PUB}/data/{name}.parquet"
        if not rows:
            if not os.path.exists(p): return
            old=pd.read_parquet(p); rows_df=old.iloc[0:0]  # previously published, now empty (e.g. filtered): publish empty table, never delete
            rows_df.to_parquet(p,index=False);out[f"data/{name}.parquet"]=p;return
        p=f"{PUB}/data/{name}.parquet";os.makedirs(os.path.dirname(p),exist_ok=True);pd.DataFrame(rows).to_parquet(p,index=False);out[f"data/{name}.parquet"]=p
    c=[flat_court(json.loads(l)) for l in open(ROOT+"/data/us/us_courthouses.jsonl")]
    c.sort(key=lambda r:r["court_id"]);wr("courthouses/us",c)
    for name,pat in (("judges/us",ROOT+"/data/us/us_judges.jsonl"),("forms/us",ROOT+"/data/us/us_forms.jsonl"),("rules/us",ROOT+"/data/us/us_rules.jsonl")):
        if os.path.exists(pat):
            rows=[json.loads(l) for l in open(pat)]
            rows=[{k:(json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in rows]
            for r in rows: r.setdefault("needs_review",name.startswith("judges"))
            wr(name,rows)
    rr=[json.loads(l) for f in sorted(glob.glob(ROOT+"/rules/out/us_rules_??.jsonl")) for l in open(f)]
    rr.sort(key=lambda r:r["rule_id"]);wr("rules/us",rr)
    xx=[json.loads(l) for f in sorted(glob.glob(ROOT+"/rules/out/us_rules_crosswalk_??.jsonl")) for l in open(f)]
    xx.sort(key=lambda r:(r["rule_set_id"],r["court_id"]));wr("rules_court_crosswalk/us",xx)
    # ---- phase 5: GB / CA / AU (same schema; record_type=court_body rows give the court hierarchy that parent_court_id points to)
    def jl(pat):
        return [json.loads(l) for f in sorted(glob.glob(pat)) for l in open(f)]
    def js(rows):
        return [{k:(json.dumps(v,sort_keys=True,default=str) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in rows]
    for cc in ("gb","ca","au"):
        ch=[flat_court(r) for r in jl(f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl")]
        ch.sort(key=lambda r:r["court_id"]);wr(f"courthouses/{cc}",ch)
        jd=js(jl(f"{ROOT}/data/{cc}/{cc}_judges.jsonl"));jd.sort(key=lambda r:r["judge_id"]);wr(f"judges/{cc}",jd)
        fm=js(jl(f"{ROOT}/data/{cc}/{cc}_forms*.jsonl"));fm.sort(key=lambda r:r["form_id"]);wr(f"forms/{cc}",fm)
        ru=js(jl(f"{ROOT}/data/{cc}/{cc}_rules.jsonl"));ru.sort(key=lambda r:r["rule_id"]);wr(f"rules/{cc}",ru)
        xw=js(jl(f"{ROOT}/data/{cc}/{cc}_rules_crosswalk.jsonl"));xw.sort(key=lambda r:(r["rule_set_id"],r["court_id"]));wr(f"rules_court_crosswalk/{cc}",xw)
    # ---- phase 6: EU member states + EU level (court_family/tier/cdb_id/ecli_code/geoname_ids extra columns)
    for cc in EU_CC:
        if os.path.exists(f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl"):
            ch=[flat_court_eu(r) for r in jl(f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl")]
            ch.sort(key=lambda r:r["court_id"]);wr(f"courthouses/{cc}",ch)
        jd=js(jl(f"{ROOT}/data/{cc}/{cc}_judges.jsonl"));jd.sort(key=lambda r:r["judge_id"]);wr(f"judges/{cc}",jd)
        fm=js(jl(f"{ROOT}/data/{cc}/{cc}_forms*.jsonl"));fm.sort(key=lambda r:r["form_id"]);wr(f"forms/{cc}",fm)
        ru=js(jl(f"{ROOT}/data/{cc}/{cc}_rules.jsonl"));ru.sort(key=lambda r:r["rule_id"]);wr(f"rules/{cc}",ru)
        xw=js(jl(f"{ROOT}/data/{cc}/{cc}_rules_crosswalk.jsonl"));xw.sort(key=lambda r:(r["rule_set_id"],r["court_id"]));wr(f"rules_court_crosswalk/{cc}",xw)
    # ---- phase 7: rest of the world (NZ IN JP BR MX ZA ...): extra columns name_local/record_note/facility_kind/geonames_*/admin_qid
    for cc in ROW_CC:
        if os.path.exists(f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl"):
            ch=[flat_court_row(r) for r in jl(f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl")]
            ch.sort(key=lambda r:r["court_id"]);wr(f"courthouses/{cc}",ch)
        jd=js(jl(f"{ROOT}/data/{cc}/{cc}_judges.jsonl"));jd.sort(key=lambda r:r["judge_id"]);wr(f"judges/{cc}",jd)
        fm=js(jl(f"{ROOT}/data/{cc}/{cc}_forms*.jsonl"));fm.sort(key=lambda r:r["form_id"]);wr(f"forms/{cc}",fm)
        ru=js(jl(f"{ROOT}/data/{cc}/{cc}_rules.jsonl"));ru.sort(key=lambda r:r["rule_id"]);wr(f"rules/{cc}",ru)
        xw=js(jl(f"{ROOT}/data/{cc}/{cc}_rules_crosswalk.jsonl"));xw.sort(key=lambda r:(r["rule_set_id"],r["court_id"]));wr(f"rules_court_crosswalk/{cc}",xw)
    lk=js(jl(f"{ROOT}/data/eu/eu_laws_dataset_links.jsonl"))
    if lk: wr("laws_dataset_links/eu",lk)
    out["README.md"]=ROOT+"/publish/README.md";out["EU_COUNTS.md"]=ROOT+"/publish/EU_COUNTS.md";out["WORLD_COUNTS.md"]=ROOT+"/publish/WORLD_COUNTS.md"
    for s in ("world_courts_schema.json","RULES_LINKAGE_PLAN.md"): out["schema/"+s]=ROOT+"/schema/"+s
    return out
def pipe_files():
    base=ROOT+"/scrapers/courts/"
    fs=[p for ext in ("py","json","md") for p in glob.glob(base+"**/*."+ext,recursive=True) if "__pycache__" not in p]
    return {"scrapers/courts/"+os.path.relpath(p,base):p for p in sorted(fs)}
def push(api,repo,rtype,files,state,key,dry):
    h={k:sha(v) for k,v in files.items()};old=state.get(key,{})
    ch=[k for k in files if old.get(k)!=h[k]]
    if not ch: print(key,"unchanged");return
    print(key,"changed:",ch)
    if dry: return
    api.create_repo(repo,repo_type=rtype,exist_ok=True,private=False)
    api.create_commit(repo,repo_type=rtype,operations=[CommitOperationAdd(path_in_repo=k,path_or_fileobj=files[k]) for k in ch],commit_message=f"world_courts update: {len(ch)} files")
    state[key]=h;json.dump(state,open(STATE,"w"),indent=1)
def main():
    dry="--dry-run" in sys.argv
    os.makedirs(PUB,exist_ok=True);lk=open(PUB+"/.lock","w")
    try: fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError: print("another run active");return
    state=json.load(open(STATE)) if os.path.exists(STATE) else {}
    api=HfApi(token=os.environ["HF_TOKEN"])
    push(api,DS,"dataset",build(),state,"world_courts",dry)
    rtype="model" if api.repo_exists(PIPE) else "dataset"
    push(api,PIPE,rtype,pipe_files(),state,"world_law_pipeline",dry)
if __name__=="__main__": main()
