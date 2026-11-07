"""Re-queue robots_disallowed blockers in data/us/cos/*.blockers.jsonl (IGNORE_ROBOTS=1), sequential, append-only."""
import sys,json,glob,os,datetime,collections
sys.path.insert(0,"/workspace/world_courts/scrapers/courts")
import us_cos_ingest as I, us_fed_courts as F
D=I.D+"cos/";now=datetime.datetime.now(datetime.UTC).isoformat();seeds={}
for l in open(I.SEED):
    s=json.loads(l);seeds[s["url"]]=s
added=collections.Counter()
for bf in sorted(glob.glob(D+"*.blockers.jsonl")):
    st=os.path.basename(bf).split(".")[0];B=[json.loads(l) for l in open(bf)]
    todo=[b for b in B if b["reason"]=="robots_disallowed"]
    if not todo: continue
    rf=D+st+".jsonl";rows=[json.loads(l) for l in open(rf)] if os.path.exists(rf) else []
    keys={((r["address"]["street"] or "").lower(),r["address"]["postcode"]) for r in rows};keep=[b for b in B if b["reason"]!="robots_disallowed"]
    for b in todo:
        if st=="FED":
            body=next(x for x in F.bodies().values() if x["court_id"]==b["court_id"]);_,out,err=F.crawl(body);new=out
        else:
            s=seeds.get(b["url"]) or {"url":b["url"],"state":st,"county_or_place":b["county_or_place"],"gnis_id":None}
            _,out,err,pol=I.one(s);new=[{"court_id":None,"name":a["name"],"level":None,"court_system":"state","country_code":"US","subdivision":"US-"+st,"jurisdiction":None,"parent_court_id":None,
              "address":{"street":a["street"],"city":a["city"],"postcode":a["postcode"],"region":st,"country":"US"},"geo":None,"place_ids":[],"gnis_id":s.get("gnis_id"),"seed_county_or_place":s["county_or_place"],
              "source_url":s["url"],"source_kind":"official","site_policy":pol,"retrieved_at":now,"needs_review":True,"seed":"chief_of_staff_inbox"} for a in out]
        n=0
        for r in new:
            k=((r["address"]["street"] or "").lower(),r["address"]["postcode"])
            if k in keys: continue
            keys.add(k);rows.append(r);n+=1
        added[st]+=n
        if not new: keep.append({**b,"reason":err or "empty","requeued":"robots_ignored_per_owner_2026-11-01"})
        print(st,b["url"],"new",n,"err",err,flush=True)
    with open(rf,"w") as f:
        for r in rows: f.write(json.dumps(r)+"\n")
    with open(bf,"w") as f:
        for b in keep: f.write(json.dumps(b)+"\n")
print("ADDED",dict(added),flush=True)
