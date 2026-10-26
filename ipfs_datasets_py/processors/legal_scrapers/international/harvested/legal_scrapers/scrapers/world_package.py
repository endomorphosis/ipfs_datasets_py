#!/usr/bin/env python3
"""Package instruments -> parquet + README and upload ipfs_<slug>_laws datasets."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, shutil, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi

ROOT = _CORPORA
SCRAPERS = _SCRAPERS
PT = timezone(timedelta(hours=-7))

META = {
    "am": ("endomorphosis/ipfs_armenia_laws", "Armenia", "hy", "ARLIS (arlis.am)", "scrapers/collect_am.py", "am-arlis"),
    "al": ("endomorphosis/ipfs_albania_laws", "Albania", "sq", "QPZ/QBZ Fletorja Zyrtare PDFs", "scrapers/collect_al.py", "al-qbz-fletore"),
    "ba": ("endomorphosis/ipfs_bosnia_laws", "Bosnia and Herzegovina", "bs", "Sluzbeni list BiH PdfDownload", "scrapers/collect_ba.py", "ba-sluzbeni-list"),
    "mk": ("endomorphosis/ipfs_northmacedonia_laws", "North Macedonia", "mk", "Sluzben vesnik", "scrapers/collect_mk.py", "mk-slvesnik"),
    "me": ("endomorphosis/ipfs_montenegro_laws", "Montenegro", "sr", "Sluzbeni list Crne Gore", "scrapers/collect_me.py", "me-sluzbeni-list"),
    "md": ("endomorphosis/ipfs_moldova_laws", "Moldova", "ro", "legis.md State Register", "scrapers/collect_md.py", "md-legis"),
    "ge": ("endomorphosis/ipfs_georgia_laws", "Georgia", "ka", "matsne.gov.ge PDF download", "scrapers/collect_ge.py", "ge-matsne-pdf"),
    "ec": ("endomorphosis/ipfs_ecuador_laws", "Ecuador", "es", "gob.ec / Registro Oficial", "scrapers/collect_ec.py", "ec-registro-oficial"),
    "bo": ("endomorphosis/ipfs_bolivia_laws", "Bolivia", "es", "Gaceta Oficial de Bolivia", "scrapers/collect_bo.py", "bo-gaceta-oficial"),
    "py": ("endomorphosis/ipfs_paraguay_laws", "Paraguay", "es", "BACN leyes paraguayas", "scrapers/collect_py.py", "py-bacn"),
    "pa": ("endomorphosis/ipfs_panama_laws", "Panama", "es", "Gaceta Oficial de Panama", "scrapers/collect_pa.py", "pa-gaceta-oficial"),
    "dz": ("endomorphosis/ipfs_algeria_laws", "Algeria", "fr", "JORADP Journal Officiel", "scrapers/collect_dz.py", "dz-joradp"),
    "tn": ("endomorphosis/ipfs_tunisia_laws", "Tunisia", "ar", "IORT Journal Officiel", "scrapers/collect_tn.py", "tn-iort"),
    "gh": ("endomorphosis/ipfs_ghana_laws", "Ghana", "en", "Parliament of Ghana / ir.parliament.gh", "scrapers/collect_gh.py", "ghana-official"),
    "et": ("endomorphosis/ipfs_ethiopia_laws", "Ethiopia", "am", "Federal Negarit Gazette", "scrapers/collect_et.py", "et-negarit"),
    "tz": ("endomorphosis/ipfs_tanzania_laws", "Tanzania", "en", "OAG MIS Acts PDFs", "scrapers/collect_tz.py", "tz-oagmis"),
    "rs": ("endomorphosis/ipfs_serbia_laws", "Serbia", "sr", "PIS + parlament.gov.rs zakoni PDFs", "scrapers/collect_rs.py", "rs-pis-parlament"),
    "is": ("endomorphosis/ipfs_iceland_laws", "Iceland", "is", "Althingi Lagasafn", "scrapers/collect_is.py", "is-althingi-lagasafn"),
    "xk": ("endomorphosis/ipfs_kosovo_laws", "Kosovo", "sq", "Gazeta Zyrtare GZK", "scrapers/collect_xk.py", "xk-gzk"),
    "uz": ("endomorphosis/ipfs_uzbekistan_laws", "Uzbekistan", "uz", "lex.uz National Database", "scrapers/collect_uz.py", "uz-lex"),
    "rw": ("endomorphosis/ipfs_rwanda_laws", "Rwanda", "en", "MINIJUST Official Gazette", "scrapers/collect_rw.py", "rw-minijust-og"),
    "by": ("endomorphosis/ipfs_belarus_laws", "Belarus", "ru", "pravo.by National Legal Portal", "scrapers/collect_by.py", "by-pravo"),
    "mn": ("endomorphosis/ipfs_mongolia_laws", "Mongolia", "mn", "legalinfo.mn", "scrapers/collect_mn.py", "mn-legalinfo"),
    "np": ("endomorphosis/ipfs_nepal_laws", "Nepal", "ne", "Nepal Law Commission", "scrapers/collect_np.py", "np-lawcommission"),
    "jm": ("endomorphosis/ipfs_jamaica_laws", "Jamaica", "en", "MOJ Jamaica / Parliament", "scrapers/collect_jm.py", "jm-moj"),
    "ug": ("endomorphosis/ipfs_uganda_laws", "Uganda", "en", "Parliament of Uganda", "scrapers/collect_ug.py", "ug-parliament"),
    "sn": ("endomorphosis/ipfs_senegal_laws", "Senegal", "fr", "Journal Officiel du Senegal", "scrapers/collect_sn.py", "sn-jo"),
    "cm": ("endomorphosis/ipfs_cameroon_laws", "Cameroon", "fr", "Présidence / Primature Cameroun (prc.cm / spm.gov.cm)", "scrapers/collect_cm.py", "cm-prc-spm"),
    "mz": ("endomorphosis/ipfs_mozambique_laws", "Mozambique", "pt", "Boletim da República / MIREME / Parlamento", "scrapers/collect_mz.py", "mz-boletim-mireme"),
    "ao": ("endomorphosis/ipfs_angola_laws", "Angola", "pt", "Diario da Republica / GUE / Portal do Governo", "scrapers/collect_ao.py", "ao-diario-republica"),
    "az": ("endomorphosis/ipfs_azerbaijan_laws", "Azerbaijan", "az", "e-qanun.az downloadDetailPdf", "scrapers/collect_az.py", "az-eqanun"),
    "do": ("endomorphosis/ipfs_dominicanrepublic_laws", "Dominican Republic", "es", "Consultoria Juridica / consultoria.gov.do", "scrapers/collect_do.py", "do-consultoria"),
    "fj": ("endomorphosis/ipfs_fiji_laws", "Fiji", "en", "laws.gov.fj LawsAsMade", "scrapers/collect_fj.py", "fj-laws"),
    "sv": ("endomorphosis/ipfs_elsalvador_laws", "El Salvador", "es", "Diario Oficial de El Salvador", "scrapers/collect_sv.py", "sv-diario-oficial"),
    "gt": ("endomorphosis/ipfs_guatemala_laws", "Guatemala", "es", "Congreso de la Republica (congreso.gob.gt)", "scrapers/collect_gt.py", "gt-congreso"),
    "kh": ("endomorphosis/ipfs_cambodia_laws", "Cambodia", "km", "Ministry of Justice Cambodia (moj.gov.kh)", "scrapers/collect_kh.py", "kh-moj"),
    "la": ("endomorphosis/ipfs_laos_laws", "Laos", "lo", "Lao Official Gazette", "scrapers/collect_la.py", "la-official-gazette"),
    "cu": ("endomorphosis/ipfs_cuba_laws", "Cuba", "es", "Gaceta Oficial de Cuba", "scrapers/collect_cu.py", "cu-gaceta-oficial"),
    "ni": ("endomorphosis/ipfs_nicaragua_laws", "Nicaragua", "es", "Asamblea Nacional legislacion.asamblea.gob.ni", "scrapers/collect_ni.py", "ni-asamblea"),
    "hn": ("endomorphosis/ipfs_honduras_laws", "Honduras", "es", "TSC / La Gaceta tsc.gob.hn/web/leyes", "scrapers/collect_hn.py", "hn-tsc-gaceta"),
    "ve": ("endomorphosis/ipfs_venezuela_laws", "Venezuela", "es", "Gaceta Oficial gacetaoficial.gob.ve", "scrapers/collect_ve.py", "ve-gaceta-oficial"),
    "tt": ("endomorphosis/ipfs_trinidad_laws", "Trinidad and Tobago", "en", "TT Parliament / laws.gov.tt", "scrapers/collect_tt.py", "tt-parliament-laws"),
    "bn": ("endomorphosis/ipfs_brunei_laws", "Brunei", "en", "AGC Laws of Brunei", "scrapers/collect_bn.py", "bn-agc-laws"),
    "pg": ("endomorphosis/ipfs_papuanewguinea_laws", "Papua New Guinea", "en", "PNG Parliament uploads/acts", "scrapers/collect_pg.py", "pg-parliament-acts"),
    "iq": ("endomorphosis/ipfs_iraq_laws", "Iraq", "ar", "Ministry of Justice moj.gov.iq", "scrapers/collect_iq.py", "iq-moj"),
    "ir": ("endomorphosis/ipfs_iran_laws", "Iran", "fa", "DOTIC dotic.ir", "scrapers/collect_ir.py", "ir-dotic"),
    "lk": ("endomorphosis/ipfs_srilanka_laws", "Sri Lanka", "en", "documents.gov.lk / parliament.lk", "scrapers/collect_lk.py", "lk-documents-gov"),
    "lb": ("endomorphosis/ipfs_lebanon_laws", "Lebanon", "ar", "JO pcm.gov.lb Official Gazette", "scrapers/collect_lb.py", "lb-jo-pcm"),
    "zw": ("endomorphosis/ipfs_zimbabwe_laws", "Zimbabwe", "en", "Parliament of Zimbabwe (parlzim.gov.zw)", "scrapers/collect_zw.py", "zw-parliament-acts"),
    "na": ("endomorphosis/ipfs_namibia_laws", "Namibia", "en", "Parliament of Namibia / laws.parliament.na / Bank of Namibia", "scrapers/collect_na.py", "na-parliament-bon"),
    "bw": ("endomorphosis/ipfs_botswana_laws", "Botswana", "en", "gov.bw / Parliament / BURS / statutory agencies", "scrapers/collect_bw.py", "bw-gov-parliament-burs"),
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
    return _HF_TOKEN_PATH.read_text().strip()


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
        min_txt = int(__import__("os").environ.get("MIN_PACKAGE_TEXT", "80"))
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
        staging = _SCRAPERS.parent / f"staging_{cc}"
        n_l, n_a = package(cc, staging, notes)
        print(f"packaged {cc}: laws={n_l} arts={n_a} -> {staging}")
    elif cmd == "upload":
        cc = sys.argv[2]
        staging = _SCRAPERS.parent / f"staging_{cc}"
        url = upload(cc, staging)
        print("uploaded", url)
    elif cmd == "package-upload":
        cc = sys.argv[2]
        notes = sys.argv[3] if len(sys.argv) > 3 else "Partial official scrape. Not legal advice."
        staging = _SCRAPERS.parent / f"staging_{cc}"
        n_l, n_a = package(cc, staging, notes)
        url = upload(cc, staging)
        print(f"{cc}: laws={n_l} arts={n_a} {url}")
    else:
        print("usage: package|upload|package-upload <cc> [notes]")
