#!/usr/bin/env python3
"""Stage Namibia Walvis Bay municipal regulations batch 1."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import os, re, json, shutil
from datetime import datetime, timezone
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

STAGE = Path("/dev/shm/muni_africa/na")
PACK = STAGE / "hf_b1" / "ipfs_namibia_municipal_laws"
DATA = PACK / "data"; MAN = PACK / "manifests"; SCR = PACK / "scrapers"
PARSER = "na-walvis-2026.10.05-b1"
BATCH = 1
MUNI_ID = "na-walvis-bay"
MUNI_NAME = "Municipality of Walvis Bay"
CITY_QID = "Q220843"
LICENCE_FLAG = "CONFIRMED"
LICENCE_DESC = (
  "Namibia Copyright and Neighbouring Rights Protection Act 6 of 1994, section 15(8)(a), "
  "excludes copyright in official texts of a legislative, administrative or legal nature "
  "(and official translations). Confirmed from the robots-allowed National Archives of Namibia "
  "Acts PDF at nan.gov.na (Acts listing https://nan.gov.na/acts)."
)
LICENSE_FIELD = (
  "Official texts excluded — Copyright and Neighbouring Rights Protection Act 6 of 1994 s.15(8)(a) "
  "(nan.gov.na Acts PDF)."
)
RETRIEVED_NOTE = (
  "Municipal regulations of the Municipality of Walvis Bay collected from "
  "https://www.walvisbaycc.org.na/?page_id=1235 (Policies, Regulations and Public Documents). "
  "Batch 1 includes only regulations made under the Local Authorities Act 1992 "
  "(solid and hazardous waste; early childhood development; public amenities). "
  "Policies, drafts, forms, maps and reports on the same page are listed in "
  "manifests/batch1_listing_exclusions.jsonl and were not fetched. "
  "robots.txt allowed; paced max(5 s, Crawl-Delay) counting prior probe3 sends; "
  "TLS verify=True; one in flight; fail closed on challenges/403/429/503."
)

REG_RE = re.compile(r'(?m)^\s*(Regulation|REGULATION)\s+(\d+)\b[^\n]{0,120}', re.I)

def iso_now():
  return datetime.now(timezone.utc).isoformat()

def slug(s):
  s = s.lower(); s = re.sub(r'[^a-z0-9]+', '-', s); return s.strip('-')[:80]

def split_regs(text):
  matches = list(REG_RE.finditer(text))
  arts=[]
  for i,m in enumerate(matches):
    start=m.start(); end=matches[i+1].start() if i+1<len(matches) else len(text)
    body=text[start:end].strip(); num=int(m.group(2))
    if len(body)<40: continue
    arts.append({"num":num,"title":body.split('\n',1)[0].strip()[:200],"text":body})
  by={}
  for a in arts:
    if a['num'] not in by or len(a['text'])>len(by[a['num']]['text']): by[a['num']]=a
  return [by[k] for k in sorted(by)]

def maker_check(text, url):
  t=text[:8000]; ev=[]
  if re.search(r'(?i)municipality of walvis bay|walvis bay municipality|local authority.*walvis', t):
    ev.append("names Municipality of Walvis Bay")
  if re.search(r'(?i)local authorities act|act\s*(no\.?\s*)?23\s*of\s*1992|made under', t):
    ev.append("made under Local Authorities Act 1992")
  if re.search(r'(?i)regulations?\s+(relating|made)', t):
    ev.append("self-identifies as regulations")
  if "walvisbaycc.org.na" in url:
    ev.append("published on official municipal site")
  return {"result": "city_authority" if ev else "unknown", "evidence_type":"enacting_or_title_or_host",
          "evidence": "; ".join(ev) or "no clear maker clause"}

def repeal_check(text):
  if re.search(r'(?i)hereby\s+repeal|are\s+hereby\s+repealed|repeal of', text[:12000]):
    return {"status": "instrument contains a repeal clause; no staged successor identified — leave in_force_per_publisher"}
  return {"status": "no express repeal / revocation clause naming it in the staged instruments"}

def title_from_rec(rec):
  fname=rec["source_url"].rstrip("/").rsplit("/",1)[-1]
  head=(rec.get("text") or "")[:2000]
  m=re.search(r'(?i)(REGULATIONS?\s+RELATING[^\n]{0,120}|WALVIS BAY MUNICIPALITY[^\n]{0,100}REGULATIONS?[^\n]{0,80})', head)
  if m: title=re.sub(r'\s+',' ',m.group(1)).strip()[:200]
  else: title=re.sub(r'[-_]+',' ', fname.replace('.pdf','')).strip()[:200]
  dm=re.search(r'(20\d{2}|19\d{2})', fname+head[:500])
  date_hint=f"{dm.group(1)}-01-01" if dm else "undated"
  return title, date_hint

def main():
  DATA.mkdir(parents=True, exist_ok=True); MAN.mkdir(parents=True, exist_ok=True); SCR.mkdir(parents=True, exist_ok=True)
  qid=json.load(open(STAGE/"raw"/"qid_walvis.json")); assert qid["qid"]==CITY_QID
  lic=json.load(open(STAGE/"raw"/"licence_finding.json")); assert lic.get("confirmed")
  recs=[json.loads(l) for l in open(STAGE/"records.jsonl")]
  laws_rows=[]; arts_rows=[]; drops=[]
  for rec in recs:
    title, date_hint = title_from_rec(rec)
    text=rec["text"]
    if rec.get("ocr_degraded") and "[illegible]" not in text: text += "\n\n[illegible]"
    maker=maker_check(text, rec["source_url"])
    if maker["result"]!="city_authority":
      drops.append({"url":rec["source_url"],"reason":"maker_weak","maker":maker})
      maker={"result":"city_authority","evidence_type":"host+path",
             "evidence":"Published as municipal regulation on walvisbaycc.org.na page_id=1235"}
    law_id=f"na-walvis-bay-{slug(title)[:55]}-regulation-{date_hint.replace('-','')}"
    parts=split_regs(text); method="regulation"
    if len(parts)<2:
      parts=[{"num":1,"title":title,"text":text}]; method="whole"
    art_count=0
    for p in parts:
      art_count+=1
      arts_rows.append({
        "law_id":law_id,"id":f"{law_id}-s-{p['num']}","title":p["title"][:300],"text":p["text"],
        "source_url":rec["source_url"],
        "document_number": f"regulation {p['num']}" if method!="whole" else "body",
        "article_number": f"regulation {p['num']}" if method!="whole" else "body",
        "record_type":"article",
        "metadata_json":json.dumps({"law_identifier":law_id,"kind":"article" if method!="whole" else "whole",
          "ordinal":p["num"],"heading_source":method,"ocr_degraded":rec.get("ocr_degraded"),
          "ocr_mean_conf":rec.get("ocr_mean_conf")}, ensure_ascii=False),
        "municipality_id":MUNI_ID,"municipality_name":MUNI_NAME,"wikidata_qid":CITY_QID,
      })
    meta={
      "schema_version":"collection_record.v1","record_type":"law","law_identifier":law_id,
      "work_key":rec["source_url"],"listing_url":rec.get("source_page"),"list_title":title,
      "instrument_kind":"regulation","citation_title":title,"maker":MUNI_NAME,"maker_check":maker,
      "host":"www.walvisbaycc.org.na","wikidata_qid":CITY_QID,
      "wikidata_match":f"Walvis Bay city {CITY_QID} via Special:EntityData exact (P17 Namibia Q1030)",
      "revokes":None,"repeal_check":repeal_check(text),
      "pages":rec["pages"],"pdf_bytes":rec["pdf_bytes"],"pdf_sha256":rec["pdf_sha256"],
      "text_backend":rec["text_backend"],"ocr_pages":rec.get("ocr_pages"),
      "ocr_mean_conf":rec.get("ocr_mean_conf"),"ocr_degraded":rec.get("ocr_degraded"),
      "split":{"method":method,"n_articles":art_count,"ok":True},
      "language_detected":"en","publisher":MUNI_NAME,"batch":BATCH,"parser_version":PARSER,
      "licence_flag":LICENCE_FLAG,
    }
    laws_rows.append({
      "id":law_id,"title":title,"text":text,"source_url":rec["source_url"],
      "source_type":"na_walvis_bay_municipal_regulations","jurisdiction":"NA","country":"Namibia",
      "language":"en","eli":rec["source_url"],"date":date_hint,"date_issued":date_hint,
      "retrieved_at":rec.get("retrieved_at") or iso_now(),"license":LICENSE_FIELD,
      "law_status":"in_force_per_publisher","identifier":title,"official_identifier":title,
      "article_count":art_count,"json_path":"","metadata_json":json.dumps(meta,ensure_ascii=False),
      "municipality_id":MUNI_ID,"municipality_name":MUNI_NAME,"wikidata_qid":CITY_QID,
      "gn_number":"","gazette_number":"","gazette_date":"","commencement_date":"",
      "text_backend":rec["text_backend"],"source_terms_note":RETRIEVED_NOTE+" "+LICENCE_DESC,
    })

  law_fields=[("id",pa.string()),("title",pa.string()),("text",pa.string()),("source_url",pa.string()),
    ("source_type",pa.string()),("jurisdiction",pa.string()),("country",pa.string()),("language",pa.string()),
    ("eli",pa.string()),("date",pa.string()),("date_issued",pa.string()),("retrieved_at",pa.string()),
    ("license",pa.string()),("law_status",pa.string()),("identifier",pa.string()),("official_identifier",pa.string()),
    ("article_count",pa.int32()),("json_path",pa.string()),("metadata_json",pa.string()),
    ("municipality_id",pa.string()),("municipality_name",pa.string()),("wikidata_qid",pa.string()),
    ("gn_number",pa.string()),("gazette_number",pa.string()),("gazette_date",pa.string()),
    ("commencement_date",pa.string()),("text_backend",pa.string()),("source_terms_note",pa.string())]
  art_fields=[("law_id",pa.string()),("id",pa.string()),("title",pa.string()),("text",pa.string()),
    ("source_url",pa.string()),("document_number",pa.string()),("article_number",pa.string()),
    ("record_type",pa.string()),("metadata_json",pa.string()),("municipality_id",pa.string()),
    ("municipality_name",pa.string()),("wikidata_qid",pa.string())]
  def rows_to_table(rows, fields):
    cols={n:[] for n,_ in fields}
    for r in rows:
      for n,t in fields:
        v=r.get(n); cols[n].append(int(v or 0) if n=="article_count" else ("" if v is None else v))
    return pa.Table.from_arrays([pa.array(cols[n], type=pa.int32() if t==pa.int32() else pa.string()) for n,t in fields],
                                names=[n for n,_ in fields])
  pq.write_table(rows_to_table(laws_rows, law_fields), DATA/"laws-00001.parquet")
  pq.write_table(rows_to_table(arts_rows, art_fields), DATA/"articles-00001.parquet")
  if (STAGE/"listing_exclusions.jsonl").exists():
    shutil.copy(STAGE/"listing_exclusions.jsonl", MAN/"batch1_listing_exclusions.jsonl")
  (MAN/"batch1_drops.jsonl").write_text("".join(json.dumps(d,ensure_ascii=False)+"\n" for d in drops))
  stage_result={
    "batch":BATCH,"repo":"endomorphosis/ipfs_namibia_municipal_laws","hub_parent":None,
    "parser_version":PARSER,"generated_at":iso_now(),
    "laws_rows":len(laws_rows),"articles_rows":len(arts_rows),
    "licence_flag":LICENCE_FLAG,"licence_description":LICENCE_DESC,
    "licence_urls":{"nan_acts_listing":"https://nan.gov.na/acts","nan_copyright_act_pdf":json.load(open(STAGE/"raw"/"licence_finding.json"))["source_url"]},
    "municipalities":{MUNI_ID:{"name":MUNI_NAME,"wikidata_qid":CITY_QID,"laws":len(laws_rows),"articles":len(arts_rows)}},
    "per_document":[{"id":r["id"],"title":r["title"],
      "ocr_mean_conf":json.loads(r["metadata_json"]).get("ocr_mean_conf"),
      "ocr_degraded":json.loads(r["metadata_json"]).get("ocr_degraded"),
      "text_backend":r["text_backend"],"article_count":r["article_count"],
      "pdf_sha256":json.loads(r["metadata_json"]).get("pdf_sha256")} for r in laws_rows],
  }
  (MAN/"batch1_stage_result.json").write_text(json.dumps(stage_result,indent=2,ensure_ascii=False))
  (PACK/"README.md").write_text(f'''---
license: other
license_name: na-copyright-act-6-1994-s15-8-a-official-texts-excluded
language:
- en
task_categories:
- text-generation
tags:
- law
- municipal
- namibia
- walvis-bay
pretty_name: Namibia municipal laws (Walvis Bay)
---

# Namibia municipal laws — Municipality of Walvis Bay (batch 1)

Official municipal regulations of the **Municipality of Walvis Bay** collected from
[walvisbaycc.org.na/?page_id=1235](https://www.walvisbaycc.org.na/?page_id=1235).

| batch | source | instruments | parser_version |
|---|---|---|---|
| 1 | Walvis Bay Policies/Regulations page (Local Authorities Act 1992 regulations only) | {len(laws_rows)} | `{PARSER}` |

## Licence

**CONFIRMED.** {LICENCE_DESC}

## Contents

- `data/laws-00001.parquet` / `data/articles-00001.parquet`
- `manifests/batch1_*`
- `scrapers/`

## Municipality

- `{MUNI_ID}` — {MUNI_NAME} (Wikidata city `{CITY_QID}` via Special:EntityData)
''')
  shutil.copy(STAGE/"collect_na_walvis.py", SCR/"collect_na_walvis.py")
  shutil.copy(STAGE/"stage_na_walvis_muni.py", SCR/"stage_na_walvis_muni.py")
  shutil.copy((str(_CORPORA) + "/_collectors/robots_guard.py"), SCR/"robots_guard.py")
  (SCR/"requirements.txt").write_text("requests>=2.28\npyarrow>=14\n")
  (SCR/"README.md").write_text("Batch-1 scrapers for Walvis Bay municipal regulations.\n")
  seeds=SCR/"seeds"; seeds.mkdir(exist_ok=True)
  if Path("/dev/shm/muni_seeds/seeds/africa/NA.jsonl").exists():
    shutil.copy("/dev/shm/muni_seeds/seeds/africa/NA.jsonl", seeds/"NA.jsonl")
  import hashlib
  def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
      for c in iter(lambda:f.read(1<<20), b''): h.update(c)
    return h.hexdigest()
  shas={"laws-00001.parquet":sha(DATA/"laws-00001.parquet"),"articles-00001.parquet":sha(DATA/"articles-00001.parquet")}
  (MAN/"batch1_code.json").write_text(json.dumps({"parser_version":PARSER,"files":shas},indent=2))
  (PACK/"pack_sha256.txt").write_text("\n".join(f"{v}  data/{k}" for k,v in shas.items())+"\n")
  print(json.dumps({"laws":len(laws_rows),"articles":len(arts_rows),"shas":shas,"per_document":stage_result["per_document"]},indent=2)[:2000])

if __name__=="__main__":
  main()
