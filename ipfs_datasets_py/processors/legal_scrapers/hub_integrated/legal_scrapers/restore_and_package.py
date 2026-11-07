#!/usr/bin/env python3
"""Restore instruments from HF parquet; package instruments -> parquet; upload."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi

ROOT = Path(str(_CORPORA))
SCRAPERS = Path(str(_SCRAPERS) + "/scrapers")
PT = timezone(timedelta(hours=-7))

REPOS = {
    "it": ("endomorphosis/ipfs_italy_laws", "Italy", "it", "Normattiva OpenData", "scrapers/collect_it.py", "italy-normattiva-opendata"),
    "ro": ("endomorphosis/ipfs_romania_laws", "Romania", "ro", "legislatie.just.ro SOAP", "scrapers/collect_ro.py", "romania-legislatie-just"),
    "si": ("endomorphosis/ipfs_slovenia_laws", "Slovenia", "sl", "Uradni list RS", "scrapers/collect_si.py", "slovenia-uradni-list"),
    "bg": ("endomorphosis/ipfs_bulgaria_laws", "Bulgaria", "bg", "dv.parliament.bg (archive fallbacks)", "scrapers/collect_bg.py", "bulgaria-dv-parliament"),
    "cy": ("endomorphosis/ipfs_cyprus_laws", "Cyprus", "el", "GPO mof.gov.cy", "scrapers/collect_cy.py", "cyprus-gpo-gazette"),
}

LAW_COLS = [
    "id", "title", "text", "source_url", "source_type", "jurisdiction", "country",
    "language", "eli", "date", "date_issued", "retrieved_at", "license", "law_status",
    "identifier", "official_identifier", "article_count", "json_path", "metadata_json",
]
ART_COLS = [
    "law_id", "id", "title", "text", "source_url", "document_number",
    "article_number", "record_type", "metadata_json",
]


def token() -> str:
    return Path("/home/USER/.cache/huggingface/token").read_text().strip()


def restore(cc: str, parquet_dir: Path, *, min_text: int = 0) -> tuple[int, int]:
    laws = pd.read_parquet(parquet_dir / "data" / "laws.parquet")
    arts = pd.read_parquet(parquet_dir / "data" / "articles.parquet")
    instr = ROOT / cc / "instruments"
    instr.mkdir(parents=True, exist_ok=True)
    (ROOT / cc / "raw").mkdir(parents=True, exist_ok=True)
    (ROOT / cc / "logs").mkdir(parents=True, exist_ok=True)
    restored = skipped_short = 0
    arts_by_law: dict[str, list] = {}
    for _, a in arts.iterrows():
        lid = str(a.get("law_id") or "")
        arts_by_law.setdefault(lid, []).append({
            "id": a.get("id"),
            "title": a.get("title"),
            "text": a.get("text") or "",
            "date_filed": None,
            "document_number": a.get("document_number"),
            "source_url": a.get("source_url"),
            "record_type": a.get("record_type") or "article",
            "article_number": a.get("article_number"),
            "law_identifier": lid,
            "metadata": {},
        })
    for _, row in laws.iterrows():
        text = str(row.get("text") or "")
        if len(text) < min_text:
            skipped_short += 1
            continue
        rid = str(row["id"])
        meta = row.get("metadata_json")
        if isinstance(meta, str) and meta:
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {"raw_metadata_json": meta}
        elif not isinstance(meta, dict):
            meta = {}
        docs = arts_by_law.get(rid, [])
        rec = {
            "schema_version": "collection_record.v1",
            "record_type": "law",
            "id": rid,
            "title": row.get("title") or rid,
            "text": text,
            "source_url": row.get("source_url"),
            "source_type": row.get("source_type"),
            "date": row.get("date") if pd.notna(row.get("date")) else None,
            "jurisdiction": row.get("jurisdiction"),
            "country": row.get("country"),
            "language": row.get("language"),
            "eli": row.get("eli") if pd.notna(row.get("eli")) else None,
            "license": row.get("license"),
            "retrieved_at": row.get("retrieved_at"),
            "identifier": row.get("identifier"),
            "official_identifier": row.get("official_identifier"),
            "law_identifier": row.get("official_identifier") or row.get("identifier"),
            "document_type": "statute",
            "law_status": row.get("law_status") or "unknown",
            "is_current": None,
            "canonical_law_url": row.get("source_url"),
            "article_count": int(row.get("article_count") or len(docs) or 0),
            "article_extraction_status": "ok" if docs else "missing",
            "documents": docs,
            "metadata": meta or {"collector": "restored-from-parquet"},
        }
        dest = instr / f"{rid}.json"
        dest.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        restored += 1
    return restored, skipped_short


def instruments_to_frames(cc: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    instr = ROOT / cc / "instruments"
    laws, arts = [], []
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 80:
            continue  # honest bodies only (drop short abrogated / shells)
        meta = rec.get("metadata") or {}
        laws.append({
            "id": rec.get("id"),
            "title": rec.get("title"),
            "text": text,
            "source_url": rec.get("source_url"),
            "source_type": rec.get("source_type"),
            "jurisdiction": rec.get("jurisdiction"),
            "country": rec.get("country"),
            "language": rec.get("language"),
            "eli": rec.get("eli"),
            "date": rec.get("date"),
            "date_issued": rec.get("date"),
            "retrieved_at": rec.get("retrieved_at"),
            "license": rec.get("license"),
            "law_status": rec.get("law_status"),
            "identifier": rec.get("identifier"),
            "official_identifier": rec.get("official_identifier"),
            "article_count": rec.get("article_count") or len(rec.get("documents") or []),
            "json_path": f"instruments/{p.name}",
            "metadata_json": json.dumps(meta, ensure_ascii=False),
        })
        for d in rec.get("documents") or []:
            arts.append({
                "law_id": rec.get("id"),
                "id": d.get("id"),
                "title": d.get("title"),
                "text": d.get("text") or "",
                "source_url": d.get("source_url") or rec.get("source_url"),
                "document_number": d.get("document_number"),
                "article_number": d.get("article_number"),
                "record_type": d.get("record_type") or "article",
                "metadata_json": json.dumps(d.get("metadata") or {}, ensure_ascii=False),
            })
    ldf = pd.DataFrame(laws, columns=LAW_COLS) if laws else pd.DataFrame(columns=LAW_COLS)
    adf = pd.DataFrame(arts, columns=ART_COLS) if arts else pd.DataFrame(columns=ART_COLS)
    return ldf, adf


def write_readme(cc: str, out: Path, n_laws: int, n_arts: int, notes: str) -> None:
    repo, country, lang, source, collector, lic = REPOS[cc]
    pretty = f"Laws of {country}"
    size = (
        "n<1K" if n_laws < 1000 else
        "1K<n<10K" if n_laws < 10000 else
        "10K<n<100K" if n_laws < 100000 else
        "100K<n<1M"
    )
    today = datetime.now(PT).strftime("%Y-%m-%d")
    body = f"""---
pretty_name: {pretty}
license: other
license_name: {lic}
language:
- {lang}
task_categories:
- text-retrieval
tags:
- legal
- law
- {country.lower()}
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

# {pretty}

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

- `data/laws.parquet` — one row per instrument (id, title, full text, ELI,
  dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article
  number, title, text, source URL).
- `{collector}` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.

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
    lines = [
        f"# MANIFEST",
        f"",
        f"- generated_at: {now}",
        f"- laws: {n_laws}",
        f"- articles: {n_arts}",
        f"- files:",
    ]
    for k, v in files.items():
        lines.append(f"  - {k}: {v} bytes")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def package(cc: str, staging: Path, notes: str) -> tuple[int, int]:
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "data").mkdir(exist_ok=True)
    (staging / "scrapers").mkdir(exist_ok=True)
    ldf, adf = instruments_to_frames(cc)
    lpath = staging / "data" / "laws.parquet"
    apath = staging / "data" / "articles.parquet"
    ldf.to_parquet(lpath, index=False)
    adf.to_parquet(apath, index=False)
    write_readme(cc, staging / "README.md", len(ldf), len(adf), notes)
    # copy scrapers
    mapping = {
        "it": "collect_it.py", "ro": "collect_ro.py", "si": "collect_si.py",
        "bg": "collect_bg.py", "cy": "collect_cy.py",
    }
    for name in [mapping[cc], "common.py", "archive_fallbacks.py"]:
        src = SCRAPERS / name
        if src.exists():
            (staging / "scrapers" / name).write_bytes(src.read_bytes())
    files = {
        "data/laws.parquet": lpath.stat().st_size,
        "data/articles.parquet": apath.stat().st_size,
        "README.md": (staging / "README.md").stat().st_size,
    }
    write_manifest(staging / "MANIFEST.md", len(ldf), len(adf), files)
    return len(ldf), len(adf)


def upload(cc: str, staging: Path) -> str:
    repo = REPOS[cc][0]
    api = HfApi(token=token())
    api.upload_folder(
        folder_path=str(staging),
        repo_id=repo,
        repo_type="dataset",
        commit_message=f"Resume scrape checkpoint: update {cc} laws/articles",
        allow_patterns=["data/*.parquet", "README.md", "MANIFEST.md", "scrapers/*"],
    )
    return f"https://huggingface.co/datasets/{repo}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "restore":
        for cc in (sys.argv[2:] or list(REPOS)):
            pdir = Path(f"{_SCRAPERS}/data_{cc}")
            min_text = 200 if cc == "it" else 0
            r, s = restore(cc, pdir, min_text=min_text)
            print(f"{cc}: restored={r} skipped_short={s} instruments={len(list((ROOT/cc/'instruments').glob('*.json')))}")
    elif cmd == "package":
        cc = sys.argv[2]
        notes = sys.argv[3] if len(sys.argv) > 3 else "Partial resume run. Not legal advice."
        staging = Path(f"{_SCRAPERS}/staging_{cc}")
        n_l, n_a = package(cc, staging, notes)
        print(f"packaged {cc}: laws={n_l} arts={n_a} -> {staging}")
    elif cmd == "upload":
        cc = sys.argv[2]
        staging = Path(f"{_SCRAPERS}/staging_{cc}")
        url = upload(cc, staging)
        print("uploaded", url)
    elif cmd == "package-upload":
        cc = sys.argv[2]
        notes = sys.argv[3] if len(sys.argv) > 3 else "Partial resume run. Not legal advice."
        staging = Path(f"{_SCRAPERS}/staging_{cc}")
        n_l, n_a = package(cc, staging, notes)
        url = upload(cc, staging)
        print(f"{cc}: laws={n_l} arts={n_a} {url}")
    else:
        print("usage: restore|package|upload|package-upload")
