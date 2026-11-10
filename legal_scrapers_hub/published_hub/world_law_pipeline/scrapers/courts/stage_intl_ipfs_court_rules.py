"""Stage (LOCAL ONLY, no upload) national court-rule rows for justicedao/ipfs_court_rules, mirroring the STATE-XX schema.org Legislation JSON-LD + parquet_cid shape
as COUNTRY-XX files under rules/out/upstream_intl/. Dedupe: identifier/@id/ipfs_cid vs all remote parquet shards (read-only listing) and vs previously staged rows.
Never overwrites a staged file: new rows go to COUNTRY-XX.add-<sha8>.* if COUNTRY-XX exists."""
import json, sys, os, glob, hashlib, io
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from rules_common import dagjson_cid
import pandas as pd
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/rules/out/upstream_intl"; J = f"{OUT}/country_court_rules_jsonld"; P = f"{OUT}/country_court_rules_parquet_cid"
os.makedirs(J, exist_ok=True); os.makedirs(P, exist_ok=True)
CCS = sys.argv[1].split(",")
NAMES = {"TH": "Thailand", "NP": "Nepal", "PE": "Peru", "BO": "Bolivia", "PH": "Philippines", "IN": "India", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "CO": "Colombia", "CL": "Chile",
         "ID": "Indonesia", "PK": "Pakistan", "BD": "Bangladesh", "VN": "Vietnam", "EC": "Ecuador", "GT": "Guatemala", "VE": "Venezuela", "UY": "Uruguay", "HN": "Honduras", "SV": "El Salvador", "PA": "Panama", "DO": "Dominican Republic", "PY": "Paraguay", "CR": "Costa Rica", "NI": "Nicaragua", "VN": "Vietnam"}
remote_ids, remote_cids = set(), set()
for f in glob.glob(f"{ROOT}/data/ref/hf_dl/state_court_rules_parquet_cid/*.parquet") + glob.glob(f"{P}/*.parquet"):
    if "_embeddings" in f: continue
    d = pd.read_parquet(f, columns=["ipfs_cid", "identifier"]); remote_ids |= set(d.identifier); remote_cids |= set(d.ipfs_cid)
rep = {}
for cc in CCS:
    rows = [json.loads(l) for l in open(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_rules.jsonl")]
    recs, jl = [], []
    for r in rows:
        if not r.get("text"): continue
        ident = f"{cc}-{r['rule_id'].replace(':', '-')}"
        o = {"@context": {"@vocab": "https://schema.org/", "country": f"urn:iso3166:{cc.lower()}", "countryCode": "country:code", "sectionNumber": "country:sectionNumber", "sourceUrl": "country:sourceUrl"},
             "@type": "Legislation", "@id": f"urn:country:{cc.lower()}:court-rule:{ident}", "identifier": ident, "name": r.get("title") or r["rule_number"],
             "isPartOf": {"@type": "CreativeWork", "name": r["rule_set"], "identifier": f"{cc}-{r['rule_set_id']}"}, "legislationType": "court_rule", "countryCode": cc,
             "countryName": NAMES.get(cc, cc), "titleName": r["rule_set"], "sectionNumber": r["rule_number"], "sectionName": r.get("title"), "dateModified": r.get("effective_date"),
             "sourceUrl": r["source_url"], "inLanguage": r.get("language"), "text": r["text"], "license": r.get("license"), "source_kind": "world_courts:" + (r.get("site_policy") or ""),
             "world_courts_rule_id": r["rule_id"], "source_sha256": r.get("source_sha256"), "ipfs_cid": None}
        cid = dagjson_cid({k: v for k, v in o.items() if k != "ipfs_cid"}); o["ipfs_cid"] = cid
        if ident in remote_ids or cid in remote_cids: continue
        remote_ids.add(ident); remote_cids.add(cid); jl.append(json.dumps(o, ensure_ascii=False) + "\n")
        recs.append({"ipfs_cid": cid, "state_code": cc, "source_id": o["@id"], "identifier": ident, "name": o["name"], "legislation_type": "court_rule",
                     "legislation_jurisdiction": cc, "source_url": o["sourceUrl"], "text": o["text"], "jsonld": json.dumps(o, ensure_ascii=False)})
    rep[cc] = {"rows": len(rows), "staged_new": len(recs)}
    if not recs: continue
    base = f"COUNTRY-{cc}"
    if os.path.exists(f"{P}/{base}.parquet"): base += ".add-" + hashlib.sha256("".join(sorted(x["ipfs_cid"] for x in recs)).encode()).hexdigest()[:8]
    assert not os.path.exists(f"{P}/{base}.parquet")
    pd.DataFrame(recs).to_parquet(f"{P}/{base}.parquet", index=False); open(f"{J}/{base}.jsonld", "w").writelines(jl)
json.dump(rep, open(f"{OUT}/stage_report.json", "w"), indent=1); print(json.dumps(rep))
