#!/usr/bin/env python3
"""Package /workspace/legal-corpora/{cc} into HF-style parquet hub and optionally upload."""
from __future__ import annotations
import argparse, json, re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pa_exit_guard as _EG  # exit guard (pa_exit_guard)

ROOT = Path("/workspace/legal-corpora")
OUT = Path("/workspace/hf-hubs")

LAW_COLS = [
    "id","title","text","source_url","source_type","jurisdiction","country","language",
    "eli","date","date_issued","retrieved_at","license","law_status","identifier",
    "official_identifier","article_count","json_path","metadata_json",
]
ART_COLS = [
    "law_id","id","title","text","source_url","document_number","article_number",
    "record_type","metadata_json",
]

SLUG = {
    "bg":"bulgaria","cy":"cyprus","it":"italy","ro":"romania","si":"slovenia",
}

def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def package(cc: str) -> Path:
    cc = cc.lower()
    src = ROOT / cc / "instruments"
    if not src.exists():
        raise SystemExit(f"missing instruments dir: {src}")
    laws, arts = [], []
    for p in sorted(src.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        docs = rec.get("documents") or []
        meta = {
            "schema_version": rec.get("schema_version"),
            "record_type": rec.get("record_type"),
            "law_identifier": rec.get("identifier") or rec.get("official_identifier"),
            "document_type": rec.get("document_type"),
            "collector": (rec.get("provenance") or {}).get("collector") if isinstance(rec.get("provenance"), dict) else rec.get("collector"),
            "metadata": rec.get("metadata") or rec.get("extra_meta") or {},
            "is_current": rec.get("is_current"),
        }
        # pull collector from nested places
        if not meta["collector"]:
            meta["collector"] = (rec.get("extra_meta") or {}).get("collector")
        laws.append({
            "id": rec.get("id"),
            "title": rec.get("title"),
            "text": rec.get("text") or "",
            "source_url": rec.get("source_url"),
            "source_type": rec.get("source_type"),
            "jurisdiction": rec.get("jurisdiction") or cc.upper(),
            "country": rec.get("country"),
            "language": rec.get("language"),
            "eli": rec.get("eli"),
            "date": rec.get("date"),
            "date_issued": rec.get("date_issued"),
            "retrieved_at": rec.get("retrieved_at"),
            "license": rec.get("license"),
            "law_status": rec.get("law_status"),
            "identifier": rec.get("identifier"),
            "official_identifier": rec.get("official_identifier") or rec.get("identifier"),
            "article_count": len(docs) if docs else int(rec.get("article_count") or 0),
            "json_path": str(p),
            "metadata_json": json.dumps(meta, ensure_ascii=False),
        })
        for i, doc in enumerate(docs):
            if not isinstance(doc, dict):
                continue
            num = doc.get("article_number") or doc.get("document_number") or doc.get("number") or str(i+1)
            aid = doc.get("id") or f"{rec.get('id')}-art-{i+1}"
            arts.append({
                "law_id": rec.get("id"),
                "id": aid,
                "title": doc.get("title") or str(num),
                "text": doc.get("text") or "",
                "source_url": doc.get("source_url") or rec.get("source_url"),
                "document_number": str(num),
                "article_number": str(num),
                "record_type": doc.get("record_type") or "article",
                "metadata_json": json.dumps({
                    "date_filed": doc.get("date"),
                    "law_identifier": rec.get("id"),
                    "metadata": doc.get("metadata") or {},
                }, ensure_ascii=False),
            })
    slug = SLUG.get(cc, cc)
    dest = OUT / f"ipfs_{slug}_laws"
    (dest / "data").mkdir(parents=True, exist_ok=True)
    (dest / "scrapers").mkdir(parents=True, exist_ok=True)
    laws_df = pd.DataFrame(laws, columns=LAW_COLS)
    arts_df = pd.DataFrame(arts, columns=ART_COLS)
    pq.write_table(pa.Table.from_pandas(laws_df, preserve_index=False), dest/"data"/"laws.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pandas(arts_df, preserve_index=False), dest/"data"/"articles.parquet", compression="zstd")
    # copy collector if present
    scraper = Path(f"/workspace/legal_scrapers/scrapers/collect_{cc}.py")
    if scraper.exists():
        (dest/"scrapers"/scraper.name).write_bytes(scraper.read_bytes())
    common = Path("/workspace/legal_scrapers/scrapers/common.py")
    if common.exists():
        (dest/"scrapers"/"common.py").write_bytes(common.read_bytes())
    summary = ROOT / cc / "SUMMARY.md"
    notes = summary.read_text(encoding="utf-8") if summary.exists() else ""
    n_laws, n_arts = len(laws_df), len(arts_df)
    size_cat = (
        "n<1K" if n_laws < 1000 else
        "1K<n<10K" if n_laws < 10000 else
        "10K<n<100K" if n_laws < 100000 else
        "100K<n<1M"
    )
    country = laws_df["country"].dropna().iloc[0] if n_laws else slug.title()
    lang = laws_df["language"].dropna().iloc[0] if n_laws else "und"
    source_type = laws_df["source_type"].dropna().iloc[0] if n_laws else cc
    license_text = laws_df["license"].dropna().iloc[0] if n_laws else "other"
    readme = f"""---
pretty_name: {country} Official Legislation Snapshot
license: other
license_name: {cc}-official-texts
language:
- {lang}
task_categories:
- text-retrieval
tags:
- legal
- law
- {slug}
- official-texts
size_categories:
- {size_cat}
configs:
- config_name: laws
  data_files: data/laws.parquet
  default: true
- config_name: articles
  data_files: data/articles.parquet
---

# {country} Official Legislation Snapshot

Research snapshot of official national legislation.

**Not legal advice.** The official gazette / authentic source prevails over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | {utcnow()[:10]} |
| Coverage | see MANIFEST.md / SUMMARY |
| Source type | `{source_type}` |
| Collector | `scrapers/collect_{cc}.py` |
| Laws / instruments | {n_laws:,} |
| Articles | {n_arts:,} |
| Language | {lang} |
| Jurisdiction | {country} |
| License | `{cc}-official-texts` |

## Contents

- `data/laws.parquet` — one row per instrument.
- `data/articles.parquet` — article/section rows for the same snapshot.
- `scrapers/collect_{cc}.py` — research collector used to build this snapshot.

## License / reuse

{license_text}

This dataset is **not legal advice**. The official source prevails.

## Known gaps / notes

```
{notes[:4000]}
```
"""
    (dest/"README.md").write_text(readme, encoding="utf-8")
    laws_bytes = (dest/"data"/"laws.parquet").stat().st_size
    arts_bytes = (dest/"data"/"articles.parquet").stat().st_size
    (dest/"MANIFEST.md").write_text(
        f"# ipfs_{slug}_laws manifest\n\n"
        f"generated_utc: {utcnow()}\n"
        f"cc: {cc}\n"
        f"laws_rows: {n_laws}\n"
        f"articles_rows: {n_arts}\n"
        f"laws_bytes: {laws_bytes}\n"
        f"articles_bytes: {arts_bytes}\n"
        f"compression: zstd\n"
        f"collector: scrapers/collect_{cc}.py\n",
        encoding="utf-8",
    )
    print(f"PACKAGED {dest} laws={n_laws} articles={n_arts}")
    del laws_df, arts_df; _EG.release()  # exit guard (pa_exit_guard): Tables were temporaries; drop DataFrames + gc
    return dest

def upload(dest: Path, repo_id: str, token: str):
    from huggingface_hub import HfApi, create_repo
    api = HfApi(token=token)
    create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, token=token)
    api.upload_folder(folder_path=str(dest), repo_id=repo_id, repo_type="dataset", token=token)
    print(f"UPLOADED https://huggingface.co/datasets/{repo_id}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cc")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--token")
    args = ap.parse_args()
    dest = package(args.cc)
    if args.upload:
        token = args.token or __import__("os").environ.get("HF_TOKEN") or __import__("os").environ.get("HUGGING_FACE_HUB_TOKEN")
        if not token:
            raise SystemExit("need --token or HF_TOKEN")
        slug = SLUG.get(args.cc.lower(), args.cc.lower())
        upload(dest, f"endomorphosis/ipfs_{slug}_laws", token)

if __name__ == "__main__":
    _EG.run_guarded(main)  # exit guard (pa_exit_guard)
