#!/usr/bin/env python3
"""Local-only ZW package (no Hugging Face upload). Mirrors world_package.package."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, shutil, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd

ROOT = Path(str(_CORPORA))
SCRAPERS = Path(str(_SCRAPERS) + "/scrapers")
PT = timezone(timedelta(hours=-7))
META_ZW = ("endomorphosis/ipfs_zimbabwe_laws", "Zimbabwe", "en", "Parliament of Zimbabwe (parlzim.gov.zw)", "scrapers/collect_zw.py", "zw-parliament-acts")

LAW_COLS = [
    "id", "title", "text", "source_url", "source_type", "jurisdiction", "country",
    "language", "eli", "date", "date_issued", "retrieved_at", "license", "law_status",
    "identifier", "official_identifier", "article_count", "json_path", "metadata_json",
]
ART_COLS = [
    "law_id", "id", "title", "text", "source_url", "document_number",
    "article_number", "record_type", "metadata_json",
]

def instruments_to_frames(cc: str):
    instr = ROOT / cc / "instruments"
    laws, arts = [], []
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 80:
            continue
        meta = rec.get("metadata") or {}
        laws.append({
            "id": rec.get("id"), "title": rec.get("title"), "text": text,
            "source_url": rec.get("source_url"), "source_type": rec.get("source_type"),
            "jurisdiction": rec.get("jurisdiction"), "country": rec.get("country"),
            "language": rec.get("language"), "eli": rec.get("eli"),
            "date": rec.get("date"), "date_issued": rec.get("date"),
            "retrieved_at": rec.get("retrieved_at"), "license": rec.get("license"),
            "law_status": rec.get("law_status"), "identifier": rec.get("identifier"),
            "official_identifier": rec.get("official_identifier"),
            "article_count": rec.get("article_count") or len(rec.get("documents") or []),
            "json_path": f"instruments/{p.name}",
            "metadata_json": json.dumps(meta, ensure_ascii=False),
        })
        for d in rec.get("documents") or []:
            arts.append({
                "law_id": rec.get("id"), "id": d.get("id"), "title": d.get("title"),
                "text": d.get("text") or "",
                "source_url": d.get("source_url") or rec.get("source_url"),
                "document_number": d.get("document_number"),
                "article_number": d.get("article_number"),
                "record_type": d.get("record_type") or "article",
                "metadata_json": json.dumps(d.get("metadata") or {}, ensure_ascii=False),
            })
    return pd.DataFrame(laws, columns=LAW_COLS), pd.DataFrame(arts, columns=ART_COLS)

def write_readme(out: Path, n_laws: int, n_arts: int, notes: str) -> None:
    repo, country, lang, source, collector, lic = META_ZW
    size = ("n<1K" if n_laws < 1000 else "1K<n<10K" if n_laws < 10000 else "10K<n<100K" if n_laws < 100000 else "100K<n<1M")
    today = datetime.now(PT).strftime("%Y-%m-%d")
    body = f"""---
pretty_name: Laws of {country}
license: other
license_name: {lic}
language:
- {lang}
task_categories:
- text-retrieval
tags:
- legal
- law
- zimbabwe
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

# Laws of {country}

Research snapshot of official legislation collected from **{source}**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | {today} |
| Coverage | catalog-backed incomplete |
| Source | {source} |
| Collector | `{collector}` |
| Laws / instruments | {n_laws} |
| Articles | {n_arts} |
| Language | {lang} |
| Jurisdiction | {country} |
| License | `{lic}` |

## Contents

- `data/laws.parquet` — one row per instrument (id, title, full text, dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article number, title, text, source URL).
- `{collector}` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.
- `scrapers/world_lib.py` — shared fetch (live official URL, Wayback fallback).
- `scrapers/archive_fallbacks.py` — Wayback / Common Crawl CDX helpers.

## License / reuse

Official government / gazette texts; reuse per public-sector terms of the
source portal. This packaging, metadata, and collector script are provided
for research.

This dataset is **not** an official consolidation and is **not legal advice**.
The official source prevails.

## Notes

{notes}
"""
    out.write_text(body, encoding="utf-8")

def write_manifest(out: Path, n_laws: int, n_arts: int, files: dict) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = ["# MANIFEST", "", f"- generated_at: {now}", f"- laws: {n_laws}", f"- articles: {n_arts}", "- files:"]
    for k, v in files.items():
        lines.append(f"  - {k}: {v} bytes")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

def main():
    notes = sys.argv[1] if len(sys.argv) > 1 else (
        "Parliament of Zimbabwe official Act PDFs (parlzim.gov.zw). "
        "Live acts-list often 404; Wayback of same official URLs. Skipped ZimLII/Veritas. Not legal advice."
    )
    staging = Path(str(_SCRAPERS) + "/staging_zw")
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "data").mkdir(exist_ok=True)
    (staging / "scrapers").mkdir(exist_ok=True)
    ldf, adf = instruments_to_frames("zw")
    if len(ldf) == 0:
        raise SystemExit("zw: no laws with text>=80 to package")
    lpath = staging / "data" / "laws.parquet"
    apath = staging / "data" / "articles.parquet"
    ldf.to_parquet(lpath, index=False)
    adf.to_parquet(apath, index=False)
    for name in ["collect_zw.py", "common.py", "archive_fallbacks.py", "world_lib.py"]:
        src = SCRAPERS / name
        if src.exists():
            shutil.copy2(src, staging / "scrapers" / name)
    # README last + freeze: avoid mid-pack race uploading stub/empty YAML
    readme = staging / "README.md"
    if readme.exists():
        readme.chmod(0o644)
    write_readme(readme, len(ldf), len(adf), notes)
    readme.chmod(0o444)  # freeze until next intentional pack / CoS upload done
    body = readme.read_text(encoding="utf-8")
    if not body.startswith("---") or "## Snapshot" not in body:
        raise SystemExit("zw README missing YAML+Snapshot — refusing stub card")
    files = {
        "data/laws.parquet": lpath.stat().st_size,
        "data/articles.parquet": apath.stat().st_size,
        "README.md": readme.stat().st_size,
    }
    write_manifest(staging / "MANIFEST.md", len(ldf), len(adf), files)
    print(f"packaged zw: laws={len(ldf)} arts={len(adf)} -> {staging} (README frozen)")

if __name__ == "__main__":
    main()
