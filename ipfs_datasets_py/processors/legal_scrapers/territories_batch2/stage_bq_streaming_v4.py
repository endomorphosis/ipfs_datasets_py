#!/usr/bin/env python3
"""Two-pass ultra-low-RSS BQ/BES staging -> BQ/upload_ready_v3/.
Pass1: projected columns to collect BES law IDs.
Pass2: batch_size=4 laws / 32 articles with aggressive gc.
Leaves upload_ready/ and incomplete upload_ready_v2/ untouched.
"""
from __future__ import annotations
import collections, gc, json, pathlib, re, sys, time

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
guard("bq_v4_start")

import pyarrow as pa
import pyarrow.parquet as pq

SRC = pathlib.Path("/workspace/legal-corpora/nl_extract/hub_verify_58982353b51d/data")
READY = ROOT / "BQ" / "upload_ready_v3"
DATA = READY / "data"
DATA.mkdir(parents=True, exist_ok=True)
if (DATA / "laws.parquet").exists():
    raise SystemExit("UPLOAD_READY_V3_ALREADY_EXISTS")

PAT = re.compile(
    r"\bBES\b|Bonaire|Sint Eustatius|\bSaba\b|Caribisch(?:e)?\s+Nederland",
    re.I,
)

print(f"PASS1_START rss={peak_rss_mb():.1f} mem={mem_available_gib():.3f}", flush=True)
ids = set()
reasons = {}
types = collections.Counter()
lf = pq.ParquetFile(str(SRC / "laws.parquet"), pre_buffer=False, buffer_size=0)
for bi, batch in enumerate(
    lf.iter_batches(batch_size=64, columns=["id", "title", "metadata_json"], use_threads=False)
):
    guard(f"bq_id_{bi}")
    cols = {n: batch.column(n).to_pylist() for n in batch.schema.names}
    for i in range(batch.num_rows):
        md_raw = cols["metadata_json"][i] or "{}"
        try:
            md = json.loads(md_raw)
        except Exception:
            md = {}
        if isinstance(md, dict) and "metadata" in md:
            md = md.get("metadata") or {}
        typ = str((md or {}).get("bwb_type") or "")
        is_type = "bes" in typ.lower()
        title = cols["title"][i] or ""
        is_title = bool(PAT.search(title))
        if not (is_type or is_title):
            continue
        lid = cols["id"][i]
        if lid in ids:
            continue
        ids.add(lid)
        reasons[lid] = {
            "bwb_type": typ,
            "explicit_title_match": is_title,
            "official_type_BES": is_type,
        }
        types[typ or "(empty)"] += 1
    del batch, cols
    if bi % 20 == 0:
        gc.collect()
        print(f"PASS1 {bi} ids={len(ids)} rss={peak_rss_mb():.1f}", flush=True)

print(f"PASS1_DONE ids={len(ids)} rss={peak_rss_mb():.1f}", flush=True)
if not ids:
    raise SystemExit("NO_BES_IDS")

# Persist ID list for resume/debug (exclusive)
write_json_x(READY / "bes_law_ids.json", {"count": len(ids), "ids": sorted(ids)})

law_writer = None
law_count = 0
min_text = None
skipped_short = 0
schema_names = None

lf2 = pq.ParquetFile(str(SRC / "laws.parquet"), pre_buffer=False, buffer_size=0)
for bi, batch in enumerate(lf2.iter_batches(batch_size=4, use_threads=False)):
    guard(f"bq_laws_{bi}")
    rows = []
    for row in batch.to_pylist():
        if row["id"] not in ids:
            continue
        text = (row.get("text") or "").strip()
        if len(text) < 50:
            skipped_short += 1
            continue
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
            schema_names = table.schema.names
        law_writer.write_table(table)
        law_count += len(rows)
        del table, rows
        gc.collect()
        if law_count % 25 == 0 or peak_rss_mb() > 200:
            print(f"LAWS {law_count} rss={peak_rss_mb():.1f}", flush=True)
    del batch
    if bi % 50 == 0:
        gc.collect()

if law_writer:
    law_writer.close()
if law_count <= 0:
    raise SystemExit("NO_LAWS_NO_PACKAGE")
print(f"LAWS_DONE {law_count} min_text={min_text} rss={peak_rss_mb():.1f}", flush=True)

article_writer = None
article_count = 0
art_min = None
af = pq.ParquetFile(str(SRC / "articles.parquet"), pre_buffer=False, buffer_size=0)
for bi, batch in enumerate(af.iter_batches(batch_size=32, use_threads=False)):
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
        del table
        if bi % 10 == 0:
            print(f"ARTS {article_count} rss={peak_rss_mb():.1f}", flush=True)
    del rows, batch
    if bi % 5 == 0:
        gc.collect()

if article_writer:
    article_writer.close()

# Optional SRU probe
sru_info = {"attempted": False, "note": "optional; offline BWB extraction authoritative"}
try:
    from batch2_common_v3 import Polite

    client = Polite(["zoekservice.overheid.nl"], min_delay=2.5)
    query = (
        "https://zoekservice.overheid.nl/sru/Search"
        "?version=1.2&operation=searchRetrieve&x-connection=BWB"
        "&query=overheidbwb.geldigheidsgebied==BES&maximumRecords=1&startRecord=1"
    )
    sru_info["attempted"] = True
    try:
        body, meta = client.get(query)
        sru_info["response"] = {
            k: meta[k]
            for k in ("status", "requested_url", "content_type", "challenge", "observed_local")
        }
        if meta["status"] == 200 and not meta.get("challenge"):
            m = re.search(rb"<numberOfRecords>(\d+)</numberOfRecords>", body)
            if m:
                sru_info["numberOfRecords"] = int(m.group(1))
    except ValueError as e:
        sru_info["error"] = str(e)
except Exception as e:  # noqa: BLE001
    sru_info["error"] = f"sru_probe_skipped:{e}"

write_json_x(READY / "selection_provenance.json", reasons)
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
        "completeness": "All matching laws/articles in local preserved BWB snapshot",
        "target_hf_repo": "endomorphosis/ipfs_bonairesinteustatiusandsaba_laws",
        "sru_probe": sru_info,
        "streaming_method": "two-pass iter_batches; laws batch_size=4; articles batch_size=32",
        "peak_rss_mb": peak_rss_mb(),
        "mem_available_end_gib": mem_available_gib(),
        "push": "NOT_PUSHED",
        "datasets_streaming_validation": "Pending central verifier",
    },
)
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

All matching nonempty laws (text >= 50 chars) and structured articles from the
locally preserved official Dutch BWB corpus (snapshot 58982353b51d). Selection:
official BWB type containing BES, or explicit BES/Bonaire/Sint Eustatius/Saba/
Caribisch Nederland title. Jurisdiction BQ, parent_country NL. License CC0-1.0.
No Hugging Face upload (CoS HOLD). Official texts prevail; not legal advice.
""",
)
for src in [
    pathlib.Path(__file__),
    ROOT / "batch2_common_v3.py",
]:
    copy_sanitized_script(src, READY / "scrapers_and_normalizers" / src.name)
bwb = pathlib.Path(
    "/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_bwb.py"
)
if bwb.exists():
    copy_sanitized_script(bwb, READY / "scrapers_and_normalizers" / "collect_bwb.py")

print(
    "BQ_V3_READY",
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
