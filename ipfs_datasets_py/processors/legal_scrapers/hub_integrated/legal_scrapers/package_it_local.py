#!/usr/bin/env python3
"""Package Italy instruments -> staging_it (no HF upload)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
ROOT = Path(str(_CORPORA) + "/it/instruments")
STAGING = Path(str(_SCRAPERS) + "/staging_it")
SCRAPERS = Path(str(_SCRAPERS) + "/scrapers")
PT = timezone(timedelta(hours=-7))
MIN_TEXT = 80
LAW_COLS = ["id","title","text","source_url","source_type","jurisdiction","country","language","eli","date","date_issued","retrieved_at","license","law_status","identifier","official_identifier","article_count","json_path","metadata_json"]
ART_COLS = ["law_id","id","title","text","source_url","document_number","article_number","record_type","metadata_json"]
def main():
    laws, arts = [], []
    shells = total = 0
    for p in sorted(ROOT.glob("*.json")):
        total += 1
        try: rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception: continue
        text = str(rec.get("text") or "")
        if len(text.strip()) < MIN_TEXT:
            shells += 1; continue
        docs = rec.get("documents") or []
        meta = rec.get("metadata") or {}
        laws.append({"id": rec.get("id"), "title": rec.get("title"), "text": text, "source_url": rec.get("source_url"), "source_type": rec.get("source_type"), "jurisdiction": rec.get("jurisdiction") or "IT", "country": rec.get("country") or "Italy", "language": rec.get("language") or "it", "eli": rec.get("eli"), "date": rec.get("date"), "date_issued": rec.get("date"), "retrieved_at": rec.get("retrieved_at"), "license": rec.get("license"), "law_status": rec.get("law_status"), "identifier": rec.get("identifier"), "official_identifier": rec.get("official_identifier"), "article_count": rec.get("article_count") or len(docs), "json_path": f"instruments/{p.name}", "metadata_json": json.dumps(meta, ensure_ascii=False)})
        for d in docs:
            at = str(d.get("text") or "")
            if len(at.strip()) < 20: continue
            arts.append({"law_id": rec.get("id"), "id": d.get("id"), "title": d.get("title"), "text": at, "source_url": d.get("source_url") or rec.get("source_url"), "document_number": d.get("document_number"), "article_number": d.get("article_number"), "record_type": d.get("record_type") or "article", "metadata_json": json.dumps(d.get("metadata") or {}, ensure_ascii=False)})
    STAGING.mkdir(parents=True, exist_ok=True)
    (STAGING/"data").mkdir(exist_ok=True)
    (STAGING/"scrapers").mkdir(exist_ok=True)
    ldf = pd.DataFrame(laws, columns=LAW_COLS); adf = pd.DataFrame(arts, columns=ART_COLS)
    lpath = STAGING/"data"/"laws.parquet"; apath = STAGING/"data"/"articles.parquet"
    ldf.to_parquet(lpath, index=False); adf.to_parquet(apath, index=False)
    today = datetime.now(PT).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    size = "1K<n<10K" if len(ldf)<10000 else "10K<n<100K"
    readme = f"""---
pretty_name: Laws of Italy
license: other
license_name: italy-normattiva-opendata
language:
- it
task_categories:
- text-retrieval
tags:
- legal
- law
- italy
- official-texts
size_categories:
- {size}
configs:
- config_name: laws
  data_files: data/laws.parquet
  default: true
- config_name: articles
  data_files: data/articles.parquet
---

# Laws of Italy

Research snapshot of official legislation collected from **Normattiva OpenData**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | {today} |
| Coverage | catalog-backed incomplete (deepened bodies/articles) |
| Source | Normattiva OpenData BFF (`dettaglio-atto` + `idArticolo` walk) |
| Collector | `scrapers/collect_it.py` + `scrapers/deepen_it_idarticolo.py` |
| Laws / instruments | {len(ldf)} |
| Articles | {len(adf)} |
| Language | it |
| Jurisdiction | Italy |
| License | `italy-normattiva-opendata` |

## Contents

- `data/laws.parquet` — one row per instrument.
- `data/articles.parquet` — one row per article/section.
- `scrapers/collect_it.py` — catalog + body collector.
- `scrapers/deepen_it_idarticolo.py` — official `idArticolo` article walk.
- `scrapers/common.py` — shared helpers.

## License / reuse

Official government / gazette texts; reuse per source portal terms. Research packaging only.

## Notes

Rebuilt {today} from `~/.ipfs_datasets/legal_corpora/it/` with text>={MIN_TEXT} (dropped {shells}/{total} shells).
Articles from Normattiva `dettaglio-atto` `idArticolo` walks and honest Art. splits.
Prior HF tip historically ~42 articles (shell catalog) or ~1265 packaged; this deepen prioritizes bodies/articleization.
Official Normattiva text prevails. Not legal advice.
"""
    (STAGING/"README.md").write_text(readme, encoding="utf-8")
    manifest = f"""# MANIFEST\n\n- generated_at: {now}\n- laws: {len(ldf)}\n- articles: {len(adf)}\n- shells_dropped: {shells}\n- local_json_total: {total}\n- min_text: {MIN_TEXT}\n- files:\n  - data/laws.parquet: {lpath.stat().st_size} bytes\n  - data/articles.parquet: {apath.stat().st_size} bytes\n  - README.md: {(STAGING/'README.md').stat().st_size} bytes\n"""
    (STAGING/"MANIFEST.md").write_text(manifest, encoding="utf-8")
    for name in ["collect_it.py", "deepen_it_idarticolo.py", "common.py", "archive_fallbacks.py"]:
        src = SCRAPERS/name
        if src.exists(): (STAGING/"scrapers"/name).write_bytes(src.read_bytes())
    print(f"packaged laws={len(ldf)} arts={len(adf)} shells_dropped={shells} total_json={total} -> {STAGING}")
if __name__ == "__main__":
    main()
