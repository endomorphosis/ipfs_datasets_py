#!/usr/bin/env python3
"""Svalbard & Jan Mayen (SJ) and Bouvet Island (BV) from Lovdata-derived HF corpus.

api.lovdata.no and lovdata.no both publish robots.txt `User-agent: * Disallow: /`,
so this pass does NOT call those hosts. It filters already-published
`endomorphosis/ipfs_norway_laws` (itself built from Lovdata publicData / NLOD)
for dependency-specific instruments, and bundles a robots-aware scraper stub
for future NLOD mirror use when robots allow.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave2b_common import (  # noqa: E402
    LAW_COLS,
    RAW,
    ROOT,
    require_mem,
    utcnow,
    verify_load_dataset,
    write_json,
    write_parquet,
)

SJ_RE = re.compile(r"Svalbard|Jan[\s\-]?Mayen|Svalbardloven|Jan Mayen-loven", re.I)
BV_RE = re.compile(r"Bouvet|Bouvetøya|Bilandsloven|biland", re.I)
LICENSE = (
    "Official Norwegian legislative texts (Lovdata / Norsk Lovtidend). "
    "Underlying public gjeldende-lover dataset under NLOD 2.0. "
    "Filtered from endomorphosis/ipfs_norway_laws without new lovdata.no / "
    "api.lovdata.no fetches (robots User-agent:* Disallow:/). Not legal advice."
)


def load_norway_hits() -> tuple[list[dict], list[dict]]:
    require_mem()
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq

    path = hf_hub_download(
        repo_id="endomorphosis/ipfs_norway_laws",
        filename="data/laws.parquet",
        repo_type="dataset",
        local_dir=str(RAW / "hf_no"),
        local_dir_use_symlinks=False,
    )
    pf = pq.ParquetFile(path)
    names = pf.schema_arrow.names
    want = [c for c in (
        "id", "title", "text", "source_url", "identifier", "official_identifier",
        "eli", "date", "date_issued", "license", "law_status", "language",
        "metadata_json", "article_count", "source_type",
    ) if c in names]
    table = pf.read(columns=want)
    sj, bv = [], []
    for i in range(table.num_rows):
        row = {c: table.column(c)[i].as_py() for c in want}
        title = str(row.get("title") or "")
        text_head = str(row.get("text") or "")[:500]
        blob = title + "\n" + text_head
        if SJ_RE.search(blob):
            sj.append(row)
        if BV_RE.search(blob):
            bv.append(row)
    write_json(RAW / "no_dependency_hf_hits.json", {"sj": len(sj), "bv": len(bv)})
    return sj, bv


def stage(code: str, country: str, repo: str, rows: list[dict]) -> dict:
    out = ROOT / code / "upload_ready"
    data = out / "data"
    scrapers = out / "scrapers_and_normalizers"
    scrapers.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for name in ("collect_no_dependencies_from_hf.py", "wave2b_common.py"):
        src = Path(__file__).resolve().parent / name
        (scrapers / name).write_bytes(src.read_bytes())
    laws = []
    for row in rows:
        text = str(row.get("text") or "")
        if len(text) < 50:
            continue
        oid = str(row.get("official_identifier") or row.get("identifier") or row.get("id"))
        laws.append(
            {
                "id": f"{code.lower()}-{oid}".replace("/", "-").lower(),
                "title": row.get("title"),
                "text": text,
                "source_url": row.get("source_url"),
                "source_type": "lovdata_via_hf_norway_filter",
                "jurisdiction": code,
                "country": country,
                "language": row.get("language") or "no",
                "eli": row.get("eli"),
                "date": row.get("date"),
                "date_issued": row.get("date_issued"),
                "retrieved_at": utcnow(),
                "license": LICENSE,
                "law_status": row.get("law_status"),
                "identifier": oid,
                "official_identifier": oid,
                "article_count": row.get("article_count") or 0,
                "json_path": None,
                "metadata_json": json.dumps(
                    {"hf_source_id": row.get("id"), "robots_note": "no live lovdata fetch"},
                    ensure_ascii=False,
                ),
            }
        )
    validation = {
        "jurisdiction": code,
        "target_hf_repo": repo,
        "candidate_rows": len(rows),
        "laws": 0,
        "articles": 0,
        "lovdata_network": False,
        "lovdata_skip_reason": "robots.txt User-agent:* Disallow:/ on api.lovdata.no and lovdata.no",
        "push": "NOT_PUSHED",
    }
    if laws:
        n = write_parquet(data / "laws.parquet", laws, LAW_COLS)
        validation["laws"] = n
        validation["load_dataset_verify"] = verify_load_dataset(out)
        (out / "README.md").write_text(
            f"""# {country} laws (Norwegian dependency filter)

Filtered from `endomorphosis/ipfs_norway_laws` (NLOD-derived). No new requests to
lovdata.no / api.lovdata.no (robots Disallow:/).

Laws: {n}
Retrieved: {utcnow()}
Push: NOT_PUSHED
""",
            encoding="utf-8",
        )
    else:
        (out / "README.md").write_text(
            f"# {country} — code-only\n\nNo text>=50 dependency matches in live Norway HF corpus.\n",
            encoding="utf-8",
        )
    write_json(out / "validation.json", validation)
    return validation


def main() -> int:
    sj, bv = load_norway_hits()
    s1 = stage("SJ", "Svalbard and Jan Mayen", "endomorphosis/ipfs_svalbardandjanmayen_laws", sj)
    s2 = stage("BV", "Bouvet Island", "endomorphosis/ipfs_bouvetisland_laws", bv)
    print(json.dumps({"SJ": s1.get("laws"), "BV": s2.get("laws")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
