#!/usr/bin/env python3
"""Package instruments -> parquet + README and upload ipfs_<slug>_laws datasets."""
from __future__ import annotations
import json, shutil, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi

ROOT = Path("/workspace/legal-corpora")
SCRAPERS = Path("/workspace/legal_scrapers/scrapers")
PT = timezone(timedelta(hours=-7))

META = {
    "am": ("endomorphosis/ipfs_armenia_laws", "Armenia", "hy", "ARLIS (arlis.am)", "scrapers/collect_am.py", "am-arlis"),
    "al": ("endomorphosis/ipfs_albania_laws", "Albania", "sq", "QBZ Fletorja Zyrtare", "scrapers/collect_al.py", "al-qbz-fletore"),
    "ba": ("endomorphosis/ipfs_bosnia_laws", "Bosnia and Herzegovina", "bs", "Sluzbeni list BiH", "scrapers/collect_ba.py", "ba-sluzbeni-list"),
    "mk": ("endomorphosis/ipfs_northmacedonia_laws", "North Macedonia", "mk", "Sluzben vesnik", "scrapers/collect_mk.py", "mk-slvesnik"),
    "me": ("endomorphosis/ipfs_montenegro_laws", "Montenegro", "sr", "Sluzbeni list Crne Gore", "scrapers/collect_me.py", "me-sluzbeni-list"),
    "md": ("endomorphosis/ipfs_moldova_laws", "Moldova", "ro", "legis.md State Register", "scrapers/collect_md.py", "md-legis"),
    "ge": ("endomorphosis/ipfs_georgia_laws", "Georgia", "ka", "matsne.gov.ge Legislative Herald", "scrapers/collect_ge.py", "ge-matsne"),
    "ec": ("endomorphosis/ipfs_ecuador_laws", "Ecuador", "es", "gob.ec / Registro Oficial", "scrapers/collect_ec.py", "ec-registro-oficial"),
    "bo": ("endomorphosis/ipfs_bolivia_laws", "Bolivia", "es", "Gaceta Oficial de Bolivia", "scrapers/collect_bo.py", "bo-gaceta-oficial"),
    "py": ("endomorphosis/ipfs_paraguay_laws", "Paraguay", "es", "BACN leyes paraguayas", "scrapers/collect_py.py", "py-bacn"),
    "pa": ("endomorphosis/ipfs_panama_laws", "Panama", "es", "Gaceta Oficial de Panama", "scrapers/collect_pa.py", "pa-gaceta-oficial"),
    "dz": ("endomorphosis/ipfs_algeria_laws", "Algeria", "fr", "JORADP Journal Officiel", "scrapers/collect_dz.py", "dz-joradp"),
    "tn": ("endomorphosis/ipfs_tunisia_laws", "Tunisia", "ar", "IORT Journal Officiel", "scrapers/collect_tn.py", "tn-iort"),
    "et": ("endomorphosis/ipfs_ethiopia_laws", "Ethiopia", "am", "Federal Negarit Gazette", "scrapers/collect_et.py", "et-negarit"),
    "tz": ("endomorphosis/ipfs_tanzania_laws", "Tanzania", "en", "Parliament / OAG MIS", "scrapers/collect_tz.py", "tz-bunge"),
    "rs": ("endomorphosis/ipfs_serbia_laws", "Serbia", "sr", "PIS / Sluzbeni glasnik ELI", "scrapers/collect_rs.py", "rs-pis-slglasnik"),
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
    return Path("/home/box/.cache/huggingface/token").read_text().strip()


def instruments_to_frames(cc: str):
    instr = ROOT / cc / "instruments"
    laws, arts = [], []
    if not instr.exists():
        return pd.DataFrame(columns=LAW_COLS), pd.DataFrame(columns=ART_COLS)
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
    return pd.DataFrame(laws, columns=LAW_COLS), pd.DataFrame(arts, columns=ART_COLS)


def write_readme(cc: str, out: Path, n_laws: int, n_arts: int, notes: str) -> None:
    repo, country, lang, source, collector, lic = META[cc]
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
- {country.lower().replace(' ', '-')}
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


def package(cc: str, staging: Path, notes: str) -> tuple[int, int]:
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "data").mkdir(exist_ok=True)
    (staging / "scrapers").mkdir(exist_ok=True)
    ldf, adf = instruments_to_frames(cc)
    if len(ldf) == 0:
        raise SystemExit(f"{cc}: no laws with text>=80 to package")
    lpath = staging / "data" / "laws.parquet"
    apath = staging / "data" / "articles.parquet"
    ldf.to_parquet(lpath, index=False)
    adf.to_parquet(apath, index=False)
    write_readme(cc, staging / "README.md", len(ldf), len(adf), notes)
    collector = Path(META[cc][4]).name
    for name in [collector, "common.py", "archive_fallbacks.py", "world_lib.py"]:
        src = SCRAPERS / name
        if src.exists():
            shutil.copy2(src, staging / "scrapers" / name)
    files = {
        "data/laws.parquet": lpath.stat().st_size,
        "data/articles.parquet": apath.stat().st_size,
        "README.md": (staging / "README.md").stat().st_size,
    }
    write_manifest(staging / "MANIFEST.md", len(ldf), len(adf), files)
    return len(ldf), len(adf)


def upload(cc: str, staging: Path) -> str:
    repo = META[cc][0]
    api = HfApi(token=token())
    api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        folder_path=str(staging),
        repo_id=repo,
        repo_type="dataset",
        commit_message=f"Add/update {cc} official laws snapshot",
        allow_patterns=["data/*.parquet", "README.md", "MANIFEST.md", "scrapers/*"],
    )
    return f"https://huggingface.co/datasets/{repo}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "package":
        cc = sys.argv[2]
        notes = sys.argv[3] if len(sys.argv) > 3 else "Partial official scrape. Not legal advice."
        staging = Path(f"/workspace/legal_scrapers/staging_{cc}")
        n_l, n_a = package(cc, staging, notes)
        print(f"packaged {cc}: laws={n_l} arts={n_a} -> {staging}")
    elif cmd == "upload":
        cc = sys.argv[2]
        staging = Path(f"/workspace/legal_scrapers/staging_{cc}")
        url = upload(cc, staging)
        print("uploaded", url)
    elif cmd == "package-upload":
        cc = sys.argv[2]
        notes = sys.argv[3] if len(sys.argv) > 3 else "Partial official scrape. Not legal advice."
        staging = Path(f"/workspace/legal_scrapers/staging_{cc}")
        n_l, n_a = package(cc, staging, notes)
        url = upload(cc, staging)
        print(f"{cc}: laws={n_l} arts={n_a} {url}")
    else:
        print("usage: package|upload|package-upload <cc> [notes]")
