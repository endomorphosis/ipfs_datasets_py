#!/usr/bin/env python3
"""Local-only packager (no huggingface_hub). Mirrors world_package.package()."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, shutil, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(str(_CORPORA))
SCRAPERS = Path(str(_SCRAPERS) + "/scrapers")
PT = timezone(timedelta(hours=-7))

META = {
    "na": ("endomorphosis/ipfs_namibia_laws", "Namibia", "en", "Parliament of Namibia / Laws of Namibia (parliament.na, laws.parliament.na)", "scrapers/collect_na.py", "na-parliament-laws"),
    "md": ("endomorphosis/ipfs_moldova_laws", "Moldova", "ro", "legis.md / Parlament (old1.parlament.md) / justice.gov.md", "scrapers/collect_md.py", "md-legis-parlament"),
    "ge": ("endomorphosis/ipfs_georgia_laws", "Georgia", "ka", "matsne.gov.ge + parliament.ge kan CDX PDFs", "scrapers/collect_ge.py", "ge-matsne-parliament"),
    "cm": ("endomorphosis/ipfs_cameroon_laws", "Cameroon", "fr", "Présidence / Primature Cameroun (prc.cm / spm.gov.cm)", "scrapers/collect_cm.py", "cm-prc-spm"),
    "mz": ("endomorphosis/ipfs_mozambique_laws", "Mozambique", "pt", "Boletim da República / MIREME / Parlamento", "scrapers/collect_mz.py", "mz-boletim-mireme"),
    "ao": ("endomorphosis/ipfs_angola_laws", "Angola", "pt", "Diario da Republica / GUE / Portal do Governo", "scrapers/collect_ao.py", "ao-diario-republica"),
    "sv": ("endomorphosis/ipfs_elsalvador_laws", "El Salvador", "es", "Diario Oficial de El Salvador", "scrapers/collect_sv.py", "sv-diario-oficial"),
    "tn": ("endomorphosis/ipfs_tunisia_laws", "Tunisia", "fr", "Journal Officiel (IORT/JORT; iort.gov.tn / ocr.jort.tn)", "scrapers/collect_tn.py", "tn-jort"),
    "az": ("endomorphosis/ipfs_azerbaijan_laws", "Azerbaijan", "az", "e-qanun.az downloadDetailPdf", "scrapers/collect_az.py", "az-eqanun"),
    "zw": ("endomorphosis/ipfs_zimbabwe_laws", "Zimbabwe", "en", "Parliament of Zimbabwe (parlzim.gov.zw)", "scrapers/collect_zw.py", "zw-parliament-acts"),    "iq": ("endomorphosis/ipfs_iraq_laws", "Iraq", "ar", "Ministry of Justice moj.gov.iq", "scrapers/collect_iq.py", "iq-moj"),
    "ir": ("endomorphosis/ipfs_iran_laws", "Iran", "fa", "DOTIC dotic.ir", "scrapers/collect_ir.py", "ir-dotic"),
    "la": ("endomorphosis/ipfs_laos_laws", "Laos", "lo", "Lao Official Gazette", "scrapers/collect_la.py", "la-official-gazette"),
    "dz": ("endomorphosis/ipfs_algeria_laws", "Algeria", "fr", "JORADP Journal Officiel", "scrapers/collect_dz.py", "dz-joradp"),
    "lk": ("endomorphosis/ipfs_srilanka_laws", "Sri Lanka", "en", "documents.gov.lk / parliament.lk", "scrapers/collect_lk.py", "lk-documents-gov"),
    "bo": ("endomorphosis/ipfs_bolivia_laws", "Bolivia", "es", "Gaceta Oficial de Bolivia", "scrapers/collect_bo.py", "bo-gaceta-oficial"),
    "gh": ("endomorphosis/ipfs_ghana_laws", "Ghana", "en", "Parliament of Ghana / Judicial Service (parliament.gh, judicial.gov.gh)", "scrapers/collect_gh.py", "ghana-official"),
    "do": ("endomorphosis/ipfs_dominicanrepublic_laws", "Dominican Republic", "es", "Consultoria Juridica / consultoria.gov.do", "scrapers/collect_do.py", "do-consultoria"),
    "al": ("endomorphosis/ipfs_albania_laws", "Albania", "sq", "QPZ/QBZ Fletorja Zyrtare PDFs", "scrapers/collect_al.py", "al-qbz-fletore"),
    "et": ("endomorphosis/ipfs_ethiopia_laws", "Ethiopia", "am", "Federal Negarit Gazette", "scrapers/collect_et.py", "et-negarit"),
    "rs": ("endomorphosis/ipfs_serbia_laws", "Serbia", "sr", "PIS + parlament.gov.rs zakoni PDFs", "scrapers/collect_rs.py", "rs-pis-parlament"),

    "ba": ("endomorphosis/ipfs_bosnia_laws", "Bosnia and Herzegovina", "bs", "Sluzbeni list BiH PdfDownload", "scrapers/collect_ba.py", "ba-sluzbeni-list"),
    "cu": ("endomorphosis/ipfs_cuba_laws", "Cuba", "es", "Gaceta Oficial de Cuba", "scrapers/collect_cu.py", "cu-gaceta-oficial"),
    "gt": ("endomorphosis/ipfs_guatemala_laws", "Guatemala", "es", "Congreso de la Republica", "scrapers/collect_gt.py", "gt-congreso"),
    "kh": ("endomorphosis/ipfs_cambodia_laws", "Cambodia", "km", "Ministry of Justice Cambodia", "scrapers/collect_kh.py", "kh-moj"),
    "ni": ("endomorphosis/ipfs_nicaragua_laws", "Nicaragua", "es", "Asamblea Nacional Nicaragua", "scrapers/collect_ni.py", "ni-asamblea"),
    "fj": ("endomorphosis/ipfs_fiji_laws", "Fiji", "en", "laws.gov.fj LawsAsMade", "scrapers/collect_fj.py", "fj-laws"),
    "me": ("endomorphosis/ipfs_montenegro_laws", "Montenegro", "sr", "Sluzbeni list Crne Gore", "scrapers/collect_me.py", "me-sluzbeni-list"),
    "bn": ("endomorphosis/ipfs_brunei_laws", "Brunei", "en", "AGC Laws of Brunei", "scrapers/collect_bn.py", "bn-agc-laws"),
    "mw": ("endomorphosis/ipfs_malawi_laws", "Malawi", "en", "MalawiLII / Parliament of Malawi", "scrapers/collect_mw.py", "mw-malawilii"),
    "zm": ("endomorphosis/ipfs_zambia_laws", "Zambia", "en", "Parliament of Zambia / ZambiaLII", "scrapers/collect_zm.py", "zm-parliament"),
    "mg": ("endomorphosis/ipfs_madagascar_laws", "Madagascar", "fr", "Official Madagascar government publications", "scrapers/collect_mg.py", "mg-official"),
    "pa": ("endomorphosis/ipfs_panama_laws", "Panama", "es", "Gaceta Oficial de Panama", "scrapers/collect_pa.py", "pa-gaceta-oficial"),
    "af": ("endomorphosis/ipfs_afghanistan_laws", "Afghanistan", "fa", "Afghanistan MoJ Official Gazette / laws.moj.gov.af", "scrapers/collect_af.py", "af-moj-gazette"),
    "ss": ("endomorphosis/ipfs_southsudan_laws", "South Sudan", "en", "South Sudan MoJCA laws (mojca.gov.ss)", "scrapers/collect_ss.py", "ss-mojca-laws"),
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


def instruments_to_frames(cc: str):
    instr = ROOT / cc / "instruments"
    laws, arts = [], []
    if not instr.exists():
        return pd.DataFrame(columns=LAW_COLS), pd.DataFrame(columns=ART_COLS)
    min_txt = int(os.environ.get("MIN_PACKAGE_TEXT", "80"))
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < min_txt:
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



def _parquet_counts(staging: Path) -> tuple[int, int]:
    import pyarrow.parquet as pq
    lpath = staging / "data" / "laws.parquet"
    apath = staging / "data" / "articles.parquet"
    n_laws = pq.read_table(lpath, columns=["id"]).num_rows
    n_arts = pq.read_table(apath, columns=["id"]).num_rows
    return n_laws, n_arts


def sync_snapshot_from_parquet(cc: str, staging: Path | None = None) -> tuple[int, int]:
    """Rewrite README Snapshot L/A and MANIFEST counts from parquet row counts.

    Call AFTER any Hub arts merge that mutates articles.parquet, otherwise
    README Articles stays at the pre-merge (local-instrument) count.
    """
    staging = staging or Path(f"{_SCRAPERS}/staging_{cc}")
    n_laws, n_arts = _parquet_counts(staging)
    readme = staging / "README.md"
    man = staging / "MANIFEST.md"
    for fp in (readme, man):
        if fp.exists():
            try:
                fp.chmod(0o644)
            except Exception:
                pass
    if not readme.exists():
        raise SystemExit(f"{cc}: missing README.md — cannot sync from parquet")
    body = readme.read_text(encoding="utf-8")
    body2, n1 = re.subn(
        r"(\|\s*Laws\s*/\s*instruments\s*\|\s*)\d+(\s*\|)",
        rf"\g<1>{n_laws}\2",
        body,
        count=1,
    )
    body2, n2 = re.subn(
        r"(\|\s*Articles\s*\|\s*)\d+(\s*\|)",
        rf"\g<1>{n_arts}\2",
        body2,
        count=1,
    )
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"{cc} README Snapshot L/A replace failed (laws={n1} arts={n2})")
    readme.write_text(body2, encoding="utf-8")
    if man.exists():
        mtx = man.read_text(encoding="utf-8")
        mtx = re.sub(r"(- laws: )\d+", rf"\g<1>{n_laws}", mtx, count=1)
        mtx = re.sub(r"(- articles: )\d+", rf"\g<1>{n_arts}", mtx, count=1)
        man.write_text(mtx, encoding="utf-8")
    chk = readme.read_text(encoding="utf-8")
    got_l = re.search(r"\|\s*Laws\s*/\s*instruments\s*\|\s*(\d+)\s*\|", chk, re.I)
    got_a = re.search(r"\|\s*Articles\s*\|\s*(\d+)\s*\|", chk, re.I)
    if not got_l or not got_a or int(got_l.group(1)) != n_laws or int(got_a.group(1)) != n_arts:
        raise SystemExit(f"{cc} README still stale vs parquet L={n_laws} A={n_arts}")
    for fp in (readme, man):
        if fp.exists():
            try:
                fp.chmod(0o444)
            except Exception:
                pass
    print(f"sync_readme {cc}: README+MANIFEST L={n_laws} A={n_arts} from parquet")
    return n_laws, n_arts


def package(cc: str, staging: Path, notes: str) -> tuple[int, int]:
    if cc not in META:
        raise SystemExit(f"unknown cc: {cc}")
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "data").mkdir(exist_ok=True)
    (staging / "scrapers").mkdir(exist_ok=True)
    ldf, adf = instruments_to_frames(cc)
    if len(ldf) == 0:
        raise SystemExit(f"{cc}: no laws with text>=80 to package")
    lpath = staging / "data" / "laws.parquet"
    apath = staging / "data" / "articles.parquet"
    for fp in (lpath, apath, staging / "MANIFEST.md", staging / "README.md"):
        if fp.exists():
            try:
                fp.chmod(0o644)
            except Exception:
                pass
    (os.environ.get("LP_NO_UNLINK") == "1" or lpath.unlink(missing_ok=True)); ldf.to_parquet(lpath, index=False, compression="zstd")
    (os.environ.get("LP_NO_UNLINK") == "1" or apath.unlink(missing_ok=True)); adf.to_parquet(apath, index=False, compression="zstd")
    readme = staging / "README.md"
    if readme.exists():
        try:
            readme.chmod(0o644)
        except Exception:
            pass
    write_readme(cc, readme, len(ldf), len(adf), notes)
    body = readme.read_text(encoding="utf-8")
    if not body.startswith("---") or "## Snapshot" not in body:
        raise SystemExit(f"{cc} README missing YAML+Snapshot — refusing stub card")
    readme.chmod(0o444)  # freeze full Snapshot card for CoS upload
    collector = Path(META[cc][4]).name
    for name in [collector, "common.py", "archive_fallbacks.py", "world_lib.py", "pdf_extract_lib.py"]:
        src = SCRAPERS / name
        if src.exists():
            shutil.copy2(src, staging / "scrapers" / name)
    files = {
        "data/laws.parquet": lpath.stat().st_size,
        "data/articles.parquet": apath.stat().st_size,
        "README.md": (staging / "README.md").stat().st_size,
    }
    write_manifest(staging / "MANIFEST.md", len(ldf), len(adf), files)
    for fp in (lpath, apath, staging / "MANIFEST.md", staging / "README.md"):
        if fp.exists():
            try:
                fp.chmod(0o444)
            except Exception:
                pass
    # gap summary
    total_instr = len(list((ROOT / cc / "instruments").glob("*.json"))) if (ROOT / cc / "instruments").exists() else 0
    skipped = total_instr - len(ldf)
    sources = sorted({s for s in ldf["source_type"].dropna().astype(str).unique()})
    print(f"packaged {cc}: laws={len(ldf)} arts={len(adf)} -> {staging}")
    print(f"  instruments_on_disk={total_instr} packaged={len(ldf)} skipped_short_text={skipped}")
    print(f"  source_types={sources}")
    print(f"  source_label={META[cc][3]}")
    n_laws, n_arts = sync_snapshot_from_parquet(cc, staging)
    if (n_laws, n_arts) != (len(ldf), len(adf)):
        print(f"  parquet_after_write L={n_laws} A={n_arts} (frames were {len(ldf)}/{len(adf)})")
    return n_laws, n_arts


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("package", "sync_readme"):
        print("usage: local_package.py package <cc> [notes]")
        print("       local_package.py sync_readme <cc>   # rewrite README L/A from parquet")
        sys.exit(2)
    cc = sys.argv[2]
    staging = Path(f"{_SCRAPERS}/staging_{cc}")
    if sys.argv[1] == "sync_readme":
        sync_snapshot_from_parquet(cc, staging)
    else:
        notes = sys.argv[3] if len(sys.argv) > 3 else "Partial official scrape. Not legal advice."
        package(cc, staging, notes)
