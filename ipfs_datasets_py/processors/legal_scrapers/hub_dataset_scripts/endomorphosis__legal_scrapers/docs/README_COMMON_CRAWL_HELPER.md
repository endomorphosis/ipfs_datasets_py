# common_crawl_helper.py — ranged Common Crawl harvest for official-gazette domains

Path: `$IPFS_DATASETS_LEGAL_COLLECTORS_ROOT/common_crawl_helper.py`
Interpreter: `$IPFS_DATASETS_FRESH_VENV/bin/python` (has ipfs_datasets_py + pyarrow + bs4). Run from a cwd
that is NOT `$IPFS_DATASETS_LEGAL_WORKSPACE` (the repo dir `$IPFS_DATASETS_PY` would shadow the installed package).

## Flow (ranged reads only; no live requests to target sites; no dumps)
1. `cluster.idx` (~100 MB per collection on `data.commoncrawl.org`) is **binary-searched with HTTP Range reads**
   (~15 reads of ~4–64 KB) to find the cdx shard block(s) for a domain's SURT prefix.
2. Only those `cdx-NNNNN.gz` members (offset/length from cluster.idx, ~100–300 KB) are Range-read and gunzipped;
   lines are filtered by domain / status / mime / url regex -> pointer dicts.
3. WARC members are fetched with `ipfs_datasets_py ... CommonCrawlSearchEngine.fetch_warc_record_ranges_sliced`
   (coalesced bounded ranges, exact member split) and parsed (WARC+HTTP headers stripped, chunked/gzip decoded).
   Engine-version skew is handled (the bundled ccindex api in `ipfs_datasets_py_fresh` lacks `stats_out`; helper
   calls `engine.api.fetch_warc_record_ranges_sliced` directly in that case). Falls back to plain Range GET if the engine is missing.
4. `extract_text(body, mime)` -> text (pdftotext for PDF, bs4 for HTML); `clean_text()` NFKC-normalises Arabic PDF glyphs.

Built-in `resource_guard()` pauses when MemAvailable < 3.5 GiB or free disk < 20 GiB (env `CC_MIN_MEM_GIB`, `CC_MIN_DISK_GIB`).
`CC_REQ_DELAY` (default 0.15 s) spaces requests.

## Usage
```python
import sys; sys.path.insert(0, "$IPFS_DATASETS_LEGAL_COLLECTORS_ROOT")
import common_crawl_helper as cc

cols = cc.recent_collections(6)                 # or cc.spread_collections(8) for history-wide coverage
ptrs = cc.find_pointers("joradp.dz", cols, status="200", mime_regex="pdf|html",
                        url_regex=r"jo-arabe|jo-francais", max_records=500)
recs = cc.fetch_records(ptrs[:50])              # adds body, http_status, http_headers; 'error' on failure
text = cc.clean_text(cc.extract_text(recs[0]["body"], recs[0]["mime"]))
cc.save_pointers(ptrs, "$IPFS_DATASETS_LEGAL_COLLECTORS_ROOT/cc_pointers/dz_joradp.parquet")
```
CLI:
```
cd /tmp && $IPFS_DATASETS_FRESH_VENV/bin/python $IPFS_DATASETS_LEGAL_COLLECTORS_ROOT/common_crawl_helper.py \
   pointers joradp.dz --collections 6 --max 200 --out /tmp/dz.parquet
... fetch /tmp/dz.parquet --limit 20 --outdir /tmp/dz_raw
```
Pointer keys: url, timestamp, collection, filename, offset, length, status, mime, digest, languages.
Tip: `path_prefix="/FTP/jo-arabe"` narrows within a domain; `include_subdomains=False` limits to the apex host.

## Tested
`joradp.dz` (Algerian Journal Officiel): 141 pointers across 2 collections in ~3 s, 4 PDFs fetched by ranged WARC read
(~350 KB each) and text-extracted (Arabic gazette issues 2006–2009).
