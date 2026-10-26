"""README / dataset card of endomorphosis/world_law_scanned_pdfs (generated from manifest.parquet)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def _stats(manifest: Optional[Path]):
    if manifest is None or not Path(manifest).exists():
        return 0, 0, {}, 0, {}
    import pyarrow.parquet as pq
    t = pq.read_table(str(manifest), columns=["country_code", "bytes", "law_repo", "source_policy"])
    cc, pol = {}, {}
    for c in t.column("country_code").to_pylist():
        cc[c] = cc.get(c, 0) + 1
    for p in t.column("source_policy").to_pylist():
        for tok in (p or "none").split(";"):
            pol[tok] = pol.get(tok, 0) + 1
    pub = sum(1 for x in t.column("law_repo").to_pylist() if x)
    return t.num_rows, sum(t.column("bytes").to_pylist()), cc, pub, pol


def card(manifest: Optional[Path] = None) -> str:
    n, nbytes, cc, pub, pol = _stats(manifest)
    cc_rows = "\n".join(f"| {c} | {k:,} |" for c, k in sorted(cc.items())) or "| – | 0 |"
    pol_rows = "\n".join(f"| `{p}` | {k:,} |" for p, k in sorted(pol.items(), key=lambda kv: -kv[1])) or "| – | 0 |"
    return f"""---
license: other
license_name: mixed-public-sector-sources
license_link: LICENSE.md
pretty_name: World law — raw scanned PDFs (awaiting OCR)
tags:
- legal
- law
- pdf
- ocr
- scanned-documents
configs:
- config_name: manifest
  data_files: manifest.parquet
---

# World law — raw image-only scanned PDFs (awaiting OCR)

Raw, **image-only** (no text layer) scanned PDFs of laws, ordinances, regulations and gazettes collected by the
world law pipeline. They are published as-is so they can be OCRed later; there is **no text in this dataset**.
The text corpora are [endomorphosis/world_municipal_law](https://huggingface.co/datasets/endomorphosis/world_municipal_law)
(municipal / local places) and [endomorphosis/world_national_law](https://huggingface.co/datasets/endomorphosis/world_national_law)
(`iso:*` places: country, first-level subdivision, supranational).

**Contents:** {n:,} PDFs, {nbytes / 1e9:.2f} GB; {pub:,} of them have a matching row in a law dataset
(`law_repo` not null). The rest are documents whose text row isn't published yet (e.g. metadata only, or still
waiting for OCR).

## Layout

Two layouts coexist. PDFs uploaded before 2026-10-18 are **loose files** under `pdfs/` (kept unchanged forever, so
their `pdf_ref`s stay valid). Newer batches are packed into **per-country tar shards** under `shards/`, because the
Hub recommends < 100k files per repo (this repo passed that with the loose layout). `manifest.parquet` covers both.

### Tar shards (new uploads)

```
shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar      one country per shard, ~768 MB (max ~1 GB), uncompressed tar
   └── <place_key>/<sha256>.pdf             members, ordered by place_key then sha256
```

* `<seq>` is a 6-digit counter per country, increasing across batches; `<YYYY>/<MM>` is the upload month.
* Members are stored **uncompressed**, so every PDF is one contiguous byte range of its shard: the manifest gives
  `offset` (start of the PDF bytes) and `size`; fetch it with an HTTP `Range: bytes=offset-(offset+size-1)` request
  (no need to download the shard). Whole shards also work with `tar`, `tarfile` or WebDataset-style streaming.
* A PDF already published (loose or in an earlier shard) is never stored again: new rows point at the existing copy.

### Loose files (uploads before 2026-10-18)

```
pdfs/<CC>/<place_key>/<sha256>.pdf          most countries
pdfs/<CC>/<b>/<place_key>/<sha256>.pdf      FR, IT, DE (many places): b = first 2 hex chars of sha256(place_key)
pdfs/<CC>/[<b>/]<place_key>/<s>/<sha256>.pdf  only for a place with > 9,000 PDFs: s = sha256[:2]
manifest.parquet                            one row per document
```

* `<CC>`: ISO 3166-1 alpha-2 (`EU` for supranational). `<place_key>`: the law datasets' place key (`place_id` with
  `:` → `_`, e.g. `wd_Q90`, `iso_FR`, `iso_US-CA`; US municipalities use the bare GNIS number).
* File name = sha256 of the file bytes, so files are content-addressed and verifiable. The same PDF used by two
  documents of one place is stored once (both manifest rows point to it).
* The bucket rule is the same as in the law datasets (`schema.place_bucket`), keeping every folder under the
  Hub's 10,000-entries limit.

## manifest.parquet

| column | type | meaning |
|---|---|---|
| `doc_id` | string | document id (as in the law datasets' `doc_id`) |
| `place_id` | string | `wd:Q…`, `iso:CC[-SUB]`, `gnis:N` |
| `place_key` | string | path component (see above) |
| `country_code` | string | ISO 3166-1 alpha-2 |
| `source_url` | string | where the PDF was fetched from |
| `sha256` | string | sha256 of the PDF (= file name) |
| `bytes` | int64 | file size |
| `fetched_at` | string | ISO 8601 UTC fetch time |
| `source_policy` | string | crawl-policy tags, lower-case, `;`-joined (incl. `content_signal…` tags) |
| `lane` | string | collection lane of the OCR bot (e.g. archive / live) |
| `law_repo` | string | `endomorphosis/world_municipal_law` or `endomorphosis/world_national_law`, null if the doc isn't published |
| `law_path` | string | data parquet (or shard glob) of the place in `law_repo`, null if not published |
| `pdf_path` | string | file in this repo holding the PDF: the loose `.pdf`, or the shard `.tar` |
| `pdf_ref` | string | loose: `endomorphosis/world_law_scanned_pdfs:<pdf_path>`; shard: `endomorphosis/world_law_scanned_pdfs:<shard_path>#member=<member>&offset=<offset>&size=<size>&sha256=<sha256>` (= the law datasets' `pdf_ref` column) |
| `batch`, `uploaded_at` | string | upload bookkeeping |
| `shard_path` | string | shard `.tar` (null for loose files) |
| `member` | string | member name inside the shard, `<place_key>/<sha256>.pdf` (null for loose files) |
| `offset` | int64 | byte offset of the PDF's data inside the shard (null for loose files) |
| `size` | int64 | PDF length in bytes inside the shard (= `bytes`; null for loose files) |

By country:

| country | PDFs |
|---|---|
{cc_rows}

By `source_policy` tag:

| tag | PDFs |
|---|---|
{pol_rows}

## Joining with the law datasets

Law rows (schema v1.2.0+) carry a nullable `pdf_ref` column equal to this manifest's `pdf_ref`; join on it, or on
`(place_id, doc_id)`. Files written before v1.2.0 have no `pdf_ref` column (treat as null).

```python
import sys; sys.path.insert(0, "world_law_pipeline")   # endomorphosis/world_law_pipeline
import world_law_loader as wll
m = wll.load_scanned_pdf_manifest(countries=["PH"])          # pyarrow Table
local_pdf = wll.fetch_pdf(m.slice(0, 1).to_pylist()[0])      # loose or shard (HTTP Range) + sha256 check
data = wll.fetch_pdf_bytes(m.slice(0, 1).to_pylist()[0]["pdf_ref"])   # bytes instead of a path
law = wll.load(countries=["PH"], include_national=True)
scanned = law.filter(law["pdf_ref"].is_valid())              # law rows whose source is a scanned PDF
```

Or with plain `huggingface_hub`:

```python
from huggingface_hub import hf_hub_download
import pyarrow.parquet as pq
m = pq.read_table(hf_hub_download("endomorphosis/world_law_scanned_pdfs", "manifest.parquet", repo_type="dataset"))
row = m.to_pylist()[0]
if row["shard_path"] is None:                                   # loose file
    pdf = open(hf_hub_download("endomorphosis/world_law_scanned_pdfs", row["pdf_path"], repo_type="dataset"), "rb").read()
else:                                                           # one member of a tar shard: a single Range request
    import requests
    from huggingface_hub import hf_hub_url
    url = hf_hub_url("endomorphosis/world_law_scanned_pdfs", row["shard_path"], repo_type="dataset")
    a = row["offset"]
    pdf = requests.get(url, headers={{"Range": f"bytes={{a}}-{{a + row['size'] - 1}}"}}).content
import hashlib; assert hashlib.sha256(pdf).hexdigest() == row["sha256"]
```

## License and source caveats

* The documents are official legal texts (statutes, ordinances, gazettes, court/agency decisions) from government
  and public-sector sources. Many jurisdictions place such texts in the public domain or under an open government
  licence, **but not all do**, and scanned editions (e.g. official gazettes, commercial compilations) can carry
  their own terms. No licence is granted beyond what each source permits: check the `source_url` publisher's
  terms before redistribution or commercial use.
* `source_policy` is kept verbatim (lower-case) from collection: e.g. `noarchive_meta`, `archived_robots_disallowed`,
  `robots_404_allow_rfc9309`, and `content_signal…` tags (the publisher's Content-Signals preference such as
  `ai-train=no`). **Honour these tags**; filter rows by them if your use (e.g. model training) is restricted.
* Live fetches made against an unreachable or disallowing robots.txt (`robots_unreachable`, `robots_disallowed`)
  are **held back and not published here**, same rule as the law datasets.
* Scans are as published by the source: quality, completeness and page order aren't verified; some PDFs may be
  partial or historic (non-consolidated) editions. Nothing here is legal advice.

Takedown or corrections: open a discussion on this repository.
"""
