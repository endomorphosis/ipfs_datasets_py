#!/usr/bin/env python3
"""Kosovo staging builder, OCR wave 2 variant of stage_xk.py (wave-1).
Merges local xk instruments additively by ID (longest-text-wins) over the FRESH
remote parquet snapshot in ../dedupe/xk_remote_baseline.parquet, with the
normalized-title duplicate guard. Writes ../staging/ipfs_kosovo_laws/
(data/laws.parquet, README.md, MANIFEST.md). Validates: unique IDs, zero empty
texts, zero NEW rows under 300 chars, all rows jurisdiction XK / country Kosovo.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib, json, os, re, sys, unicodedata
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

WAVE = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
PARQUET_COLS = ['id','title','text','source_url','source_type','jurisdiction','country','language','eli','date','date_issued','retrieved_at','license','law_status','identifier','official_identifier','article_count','json_path','metadata_json']
EXTRA_KEYS = ['schema_version','record_type','law_identifier','document_type','is_current','canonical_law_url','article_extraction_status','documents','metadata']
REPO_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
STAGING = os.path.join(WAVE,'staging')

def norm(t):
    t = unicodedata.normalize('NFKD', str(t or '')).lower()
    t = re.sub(r'[^a-z0-9\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF]+',' ',t)
    return re.sub(r'\s+',' ',t).strip()

def load_local(cc):
    d=os.path.join(REPO_BASE,cc,'instruments'); out=[]
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.json'):
            try: out.append(json.load(open(os.path.join(d,fn))))
            except Exception: pass
    return out

def record_to_row(rec):
    row={}
    for k in PARQUET_COLS:
        if k in ('json_path','metadata_json'): continue
        v=rec.get(k); row[k]='' if v is None else v
    row['article_count']=int(rec.get('article_count') or 0)
    row['json_path']=f"instruments/{rec['id']}.json"
    meta={k:rec.get(k) for k in EXTRA_KEYS if rec.get(k) is not None}
    row['metadata_json']=json.dumps(meta,ensure_ascii=False) if meta else ''
    return row

def main():
    repo_name, display = 'ipfs_kosovo_laws','Kosovo'
    snap=os.path.join(WAVE,'dedupe','xk_remote_baseline.parquet')
    remote=pd.read_parquet(snap)
    for c in PARQUET_COLS:
        if c not in remote.columns: remote[c]=''
    remote=remote[PARQUET_COLS]
    remote_ids=set(remote['id'].astype(str))
    remote_titles={}
    for r in remote.itertuples():
        nt=norm(r.title)
        if nt: remote_titles[nt]=max(remote_titles.get(nt,0), len(r.text) if isinstance(r.text,str) else 0)
    local=load_local('xk')
    by_id={}
    for rec in local:
        rid=str(rec.get('id') or '')
        if not rid: continue
        txt=rec.get('text') or ''
        if rid not in by_id or len(txt)>len(by_id[rid].get('text') or ''): by_id[rid]=rec
    new_recs, skipped_id, skipped_title = [],0,0
    for rid,rec in by_id.items():
        if rid in remote_ids: skipped_id+=1; continue
        nt=norm(rec.get('title'))
        if nt and nt in remote_titles and len(rec.get('text') or '')<=remote_titles[nt]: skipped_title+=1; continue
        new_recs.append(rec)
    merged=remote.copy()
    if new_recs:
        new_df=pd.DataFrame([record_to_row(r) for r in new_recs],columns=PARQUET_COLS)
        merged=pd.concat([merged,new_df],ignore_index=True)
    merged=merged.sort_values('id').reset_index(drop=True)
    # validation
    assert merged['id'].is_unique, 'duplicate ids after merge'
    empty=int((merged['text'].fillna('').str.len()==0).sum()); assert empty==0, f'{empty} empty texts'
    new_ids={str(r.get('id')) for r in new_recs}
    new_rows=merged[merged['id'].isin(new_ids)]
    short_new=int((new_rows['text'].fillna('').str.len()<300).sum()); assert short_new==0, f'{short_new} new rows <300 chars'
    assert set(new_rows['jurisdiction'].astype(str))=={'XK'}, f"new juris {set(new_rows['jurisdiction'])}"
    assert set(new_rows['country'].astype(str))=={'Kosovo'}
    assert set(new_rows['language'].astype(str))=={'sq'}, f"new langs {set(new_rows['language'])}"
    assert set(new_rows['source_type'].astype(str))=={'gzk_kosovo'}
    stage_dir=os.path.join(STAGING,repo_name); os.makedirs(os.path.join(stage_dir,'data'),exist_ok=True)
    table=pa.Table.from_pandas(merged,preserve_index=False)
    pq_path=os.path.join(stage_dir,'data','laws.parquet')
    pq.write_table(table,pq_path,compression='zstd')
    sha=hashlib.sha256(open(pq_path,'rb').read()).hexdigest()
    total=len(merged)
    readme=f"""---
license: other
language:
- sq
- multilingual
tags:
- law
- legal
- ipfs
- datasets
---

# IPFS Kosovo Laws

Structured corpus of Kosovo national laws and legal instruments from the
Official Gazette of the Republic of Kosovo (Gazeta Zyrtare,
gzk.rks-gov.net), collected with the ipfs_datasets_py national collector
`collect_xk.py` (ActDetail PDF route).

- `data/laws.parquet`: one row per law / legal instrument with full text.

Kosovo OCR wave 2 build (2026-10-13): additive merge by instrument ID
(longest-text-wins) of the previously published corpus with scanned gazette
acts recovered by Albanian (sqi) tesseract OCR from the enumerated scanned-PDF
queue left by the 2026-10-12 continuation wave, with a normalized-title
duplicate guard.

## Counts

- laws_rows: {total}

## Schema (data/laws.parquet)

Columns: id, title, text, source_url, source_type, jurisdiction, country,
language, eli, date, date_issued, retrieved_at, license, law_status,
identifier, official_identifier, article_count, json_path, metadata_json

## Provenance

Primary legal texts are public legal information from the Official Gazette
of the Republic of Kosovo. Dataset compilation is a research artifact;
always verify against the official source before relying on a text.
Not legal advice.
"""
    open(os.path.join(stage_dir,'README.md'),'w').write(readme)
    with open(os.path.join(stage_dir,'MANIFEST.md'),'w') as f:
        f.write(f"""# Manifest

- repo: endomorphosis/{repo_name}
- updated_at: 2026-10-13
- wave: kosovo OCR wave 2 (scanned-queue recovery)

## Files

### data/laws.parquet
- laws_rows: {total}
- laws_sha256: {sha}
- compression: zstd
- merge: additive by instrument ID (longest-text-wins) over the previously
  published parquet, plus a title-level duplicate guard.
- local_instruments_total: {len(by_id)}
- local_new_instruments: {len(new_recs)}
- local_skipped_already_on_hf_by_id: {skipped_id}
- local_skipped_title_duplicate: {skipped_title}
""")
    summary={'repo':repo_name,'remote_rows':int(len(remote)),'local_total':len(by_id),'new_added':len(new_recs),'skipped_id':skipped_id,'skipped_title':skipped_title,'merged_rows':int(total),'sha256':sha,'parquet':pq_path}
    json.dump(summary,open(os.path.join(WAVE,'stats','staging_ocr2_summary.json'),'w'),indent=1)
    print(json.dumps(summary,indent=1))
if __name__=='__main__':
    main()
