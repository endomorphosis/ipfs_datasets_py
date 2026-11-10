#!/usr/bin/env python3
"""Stream BQ/BES laws+articles from local NL BWB snapshot via iter_batches.
Writes NEW package BQ/upload_ready_v2/ — leaves incomplete BQ/upload_ready/ untouched.
Peak RSS target < 90 MB; MemAvailable stop floor 3.2 GiB.
"""
from __future__ import annotations
import collections, json, pathlib, re, resource, sys, time

sys.path.insert(0, "/workspace/staging/territories_batch2_20261105")
from batch2_common_v3 import (  # noqa: E402
    ROOT,
    copy_sanitized_script,
    guard,
    install_guard,
    mem_available_gib,
    peak_rss_mb,
    write_json_x,
    write_text_x,
)

install_guard()
guard("bq_start")

import pyarrow as pa
import pyarrow.parquet as pq

SRC = pathlib.Path("/workspace/legal-corpora/nl_extract/hub_verify_58982353b51d/data")
READY = ROOT / "BQ" / "upload_ready_v2"
DATA = READY / "data"
DATA.mkdir(parents=True, exist_ok=True)
if (DATA / "laws.parquet").exists():
    raise SystemExit("UPLOAD_READY_V2_ALREADY_EXISTS")

PAT = re.compile(
    r"\bBES\b|Bonaire|Sint Eustatius|\bSaba\b|Caribisch(?:e)?\s+Nederland",
    re.I,
)
ids = set()
reasons = {}
types = collections.Counter()
law_writer = None
law_count = 0
min_text = None
skipped_short = 0

lf = pq.ParquetFile(str(SRC / "laws.parquet"), pre_buffer=False, buffer_size=0)
for bi, batch in enumerate(lf.iter_batches(batch_size=32, use_threads=False)):
    guard(f"bq_laws_{bi}")
    rows = []
    for row in batch.to_pylist():
        md = json.loads(row.get("metadata_json") or "{}")
        if isinstance(md, dict) and "metadata" in md:
            md = md.get("metadata") or {}
        typ = str((md or {}).get("bwb_type") or "")
        is_type = "bes" in typ.lower()
        title = row.get("title") or ""
        is_title = bool(PAT.search(title))
        if not (is_type or is_title):
            continue
        text = (row.get("text") or "").strip()
        if len(text) < 50:
            skipped_short += 1
            continue
        lid = row["id"]
        if lid in ids:
            continue
        ids.add(lid)
        reasons[lid] = {
            "bwb_type": typ,
            "explicit_title_match": is_title,
            "official_type_BES": is_type,
        }
        types[typ or "(empty)"] += 1
        out = dict(row)
        out.update(
            {
                "jurisdiction": "BQ",
                "country": "BQ",
                "jurisdiction_code": "BQ",
                "parent_country": "NL",
                "source_snapshot_hf_commit": "58982353b51d",
                "territory_selection": "official BWB type -BES or explicit territory title",
                "source_snapshot_note": "Previously preserved national BWB corpus; not refreshed to current date",
            }
        )
        rows.append(out)
        min_text = len(text) if min_text is None else min(min_text, len(text))
    if rows:
        table = pa.Table.from_pylist(rows)
        if law_writer is None:
            law_writer = pq.ParquetWriter(
                str(DATA / "laws.parquet"), table.schema, compression="zstd"
            )
        law_writer.write_table(table)
        law_count += len(rows)
        print(f"BQ_LAWS_PROGRESS {law_count} rss={peak_rss_mb():.1f}", flush=True)

if law_writer:
    law_writer.close()
if law_count <= 0:
    raise SystemExit("NO_LAWS_NO_PACKAGE")

article_writer = None
article_count = 0
art_min = None
af = pq.ParquetFile(str(SRC / "articles.parquet"), pre_buffer=False, buffer_size=0)
for bi, batch in enumerate(af.iter_batches(batch_size=64, use_threads=False)):
    guard(f"bq_arts_{bi}")
    rows = []
    for row in batch.to_pylist():
        if row.get("law_id") not in ids:
            continue
        text = (row.get("text") or "").strip()
        if len(text) < 1:
            continue
        out = dict(row)
        out.update(jurisdiction_code="BQ", parent_country="NL")
        rows.append(out)
        art_min = len(text) if art_min is None else min(art_min, len(text))
    if rows:
        table = pa.Table.from_pylist(rows)
        if article_writer is None:
            article_writer = pq.ParquetWriter(
                str(DATA / "articles.parquet"), table.schema, compression="zstd"
            )
        article_writer.write_table(table)
        article_count += len(rows)
        if bi % 5 == 0:
            print(f"BQ_ARTS_PROGRESS {article_count} rss={peak_rss_mb():.1f}", flush=True)

if article_writer:
    article_writer.close()

# Optional lightweight SRU probe (1 page). zoekservice.overheid.nl may disallow; record result.
sru_info = {"attempted": False, "note": "optional; offline BWB extraction is authoritative for this package"}
try:
    from batch2_common_v3 import Polite

    # Official KOOP SRU host — check robots first via Polite.setup
    client = Polite(["zoekservice.overheid.nl"], min_delay=2.5)
    # setup will fetch robots; if Disallow:/, Polite.get will ROBOTS_HOLD on query
    query = (
        "https://zoekservice.overheid.nl/sru/Search"
        "?version=1.2&operation=searchRetrieve&x-connection=BWB"
        "&query=overheidbwb.geldigheidsgebied==BES&maximumRecords=1&startRecord=1"
    )
    sru_info["attempted"] = True
    try:
        body, meta = client.get(query)
        sru_info["response"] = {
            k: meta[k] for k in ("status", "requested_url", "content_type", "challenge", "observed_local")
        }
        if meta["status"] == 200 and not meta.get("challenge"):
            import re as _re

            m = _re.search(rb"<numberOfRecords>(\d+)</numberOfRecords>", body)
            if m:
                sru_info["numberOfRecords"] = int(m.group(1))
    except ValueError as e:
        sru_info["error"] = str(e)
except Exception as e:  # noqa: BLE001
    sru_info["error"] = f"sru_probe_skipped:{e}"

write_json_x(
    READY / "validation.json",
    {
        "laws_rows": law_count,
        "articles_rows": article_count,
        "articles_file_created": article_count > 0,
        "unique_law_ids": len(ids),
        "min_law_text_chars": min_text,
        "min_article_text_chars": art_min,
        "skipped_short_laws_lt50": skipped_short,
        "selection_types": dict(types),
        "source_files": [str(SRC / "laws.parquet"), str(SRC / "articles.parquet")],
        "source_snapshot_hf_commit": "58982353b51d",
        "source_license": "CC0-1.0 as preserved in official KOOP BWB provenance metadata",
        "completeness": "All matching laws/articles in local preserved BWB snapshot; NOT every currently applicable law or latest BES law",
        "target_hf_repo": "endomorphosis/ipfs_bonairesinteustatiusandsaba_laws",
        "sru_probe": sru_info,
        "streaming_method": "ParquetFile(pre_buffer=False,buffer_size=0).iter_batches(batch_size=32/64,use_threads=False)",
        "peak_rss_mb": peak_rss_mb(),
        "mem_available_end_gib": mem_available_gib(),
        "push": "NOT_PUSHED",
        "datasets_streaming_validation": "Pending central verifier",
    },
)
write_json_x(READY / "selection_provenance.json", reasons)
write_json_x(
    READY / "manifest_upload_ready.json",
    {
        "dataset": "endomorphosis/ipfs_bonairesinteustatiusandsaba_laws",
        "jurisdiction_code": "BQ",
        "parent_country": "NL",
        "package_path": str(READY),
        "laws_rows": law_count,
        "articles_rows": article_count,
        "created_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "push": "HOLD_PENDING_BENJAMIN_GO",
    },
)
write_text_x(
    READY / "README.md",
    """---
license: cc0-1.0
language: nl
configs:
- config_name: laws
  data_files: data/laws.parquet
- config_name: articles
  data_files: data/articles.parquet
---
# Caribbean Netherlands (BQ): official BWB BES snapshot subset

All matching nonempty laws (text >= 50 chars) and their existing structured articles
from the locally preserved official Dutch BWB corpus at national snapshot 58982353b51d.
Selection uses the official BWB regulation type containing BES, or explicit
BES/Bonaire/Sint Eustatius/Saba/Caribisch Nederland in the title.

Jurisdiction fields set to BQ with parent_country NL. Existing article text/identifiers
are preserved rather than inferred. Source is CC0-1.0 KOOP BWB provenance.

Complete for this selection within the preserved snapshot, not a certification of all
currently applicable BES laws. National general laws applicable to BES without explicit
title/type indicators may be omitted. No Hugging Face upload performed (CoS HOLD).
Official texts prevail; not legal advice.
""",
)

for src in [
    pathlib.Path(__file__),
    ROOT / "batch2_common_v3.py",
]:
    copy_sanitized_script(src, READY / "scrapers_and_normalizers" / src.name)

# also copy collect_bwb if present
bwb = pathlib.Path(
    "/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_bwb.py"
)
if bwb.exists():
    copy_sanitized_script(bwb, READY / "scrapers_and_normalizers" / "collect_bwb.py")

print(
    "BQ_V2_READY",
    law_count,
    article_count,
    "min_text",
    min_text,
    "peak_rss_mb",
    peak_rss_mb(),
    "mem_gib",
    f"{mem_available_gib():.3f}",
    flush=True,
)
