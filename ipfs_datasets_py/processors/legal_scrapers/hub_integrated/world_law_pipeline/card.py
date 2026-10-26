"""Dataset cards (README.md) for endomorphosis/world_municipal_law and endomorphosis/world_national_law:
one config per country (§4.2)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import schema as S

PHASE1_COUNTRIES = ["AT", "BE", "CL", "CZ", "ES", "GB", "HU", "IT", "JP", "NL", "PE", "PL", "PT"]


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "n/a"


def provenance_section(stats: Optional[Dict[str, Dict[str, Any]]]) -> str:
    """Archived share overall / per country + restricted-archive, content_complete=false, source_official=false counts.
    stats = {CC: {places, docs, archived, archived_restricted, content_incomplete, source_unofficial}}."""
    if not stats:
        return ""
    keys = ("places", "docs", "archived", "archived_restricted", "content_incomplete", "source_unofficial")
    tot = {k: sum(int(v.get(k) or 0) for v in stats.values()) for k in keys}
    lines = ["## Provenance", "",
             f"- Documents: {tot['docs']:,} in {tot['places']:,} places.",
             f"- From a web archive (Wayback / Common Crawl; `archive_source` set): {tot['archived']:,} "
             f"({_pct(tot['archived'], tot['docs'])}).",
             f"- Of those, archived copies of sites whose robots.txt disallows crawling or whose pages carry a "
             f"robots `noarchive`/`noindex` meta tag (`source_policy` = archived_robots_disallowed / noarchive_meta / "
             f"noindex_meta): {tot['archived_restricted']:,}.",
             f"- `content_complete = false` (metadata-only or partial text): {tot['content_incomplete']:,}.",
             f"- `source_official = false` (non-government mirror/aggregator): {tot['source_unofficial']:,}.",
             "- Rows whose live fetch was not permitted (robots.txt unreachable or disallowing) are not published.",
             "", "| country | places | docs | archived | archived share | archived (restricted sites) | content_complete=false | source_official=false |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for cc in sorted(stats):
        v = {k: int(stats[cc].get(k) or 0) for k in keys}
        lines.append(f"| {cc} | {v['places']:,} | {v['docs']:,} | {v['archived']:,} | {_pct(v['archived'], v['docs'])} | "
                     f"{v['archived_restricted']:,} | {v['content_incomplete']:,} | {v['source_unofficial']:,} |")
    return "\n".join(lines) + "\n"


SPLIT_NOTE_MUNICIPAL = """## Split: national law lives in `world_national_law`
Since 2026-10-11, national, subnational (first-level: state / Land / province / région) and supranational law,
i.e. every `iso:*` place (`iso_FR`, `iso_ES-CT`, `iso_EU`, …), is published in
[`endomorphosis/world_national_law`](https://huggingface.co/datasets/endomorphosis/world_national_law), which uses
the same schema and layout. This repo keeps municipal and other local law (municipalities, counties, water boards,
…). The `iso_*` files were copied there first, verified (sha256 and row counts), and then deleted here in a
separate commit; the repo history still has them.
"""

SPLIT_NOTE_NATIONAL = """## Relation to `world_municipal_law`
This repo holds national, first-level subnational (state / Land / province / région) and supranational law, i.e.
places whose `place_id` is `iso:{CC}`, `iso:{ISO 3166-2}` or `iso:EU` (`place_key` `iso_*`, `admin_level`
`country` / `adm1` / `supranational`). Municipal and other local law (municipalities, counties, water boards, …)
is in [`endomorphosis/world_municipal_law`](https://huggingface.co/datasets/endomorphosis/world_municipal_law),
with the same schema and layout. The data was split out of world_municipal_law on 2026-10-11 (copied, verified by
sha256 and row counts, then deleted there in a later commit); both repos are now updated by the same pipeline run.
"""


LOADER_SECTION = """
## Combined loader (world + US)

US municipal codes stay in [endomorphosis/american_municipal_law](https://huggingface.co/datasets/endomorphosis/american_municipal_law)
(not copied). `endomorphosis/world_municipal_law` `world_law/places.parquet` holds one **pointer row** per US GNIS
place (`place_id` `gnis:N`, `country_code` US, `has_local_data` false, `source_repo`, `source_paths`, `total_docs`).
[`world_law_loader.py`](https://huggingface.co/endomorphosis/world_law_pipeline/blob/main/world_law_loader.py)
reads both and maps the US 5-column files (cid, doc_id, doc_order, html_title, html) onto the 35-column schema
(other columns null):

```python
from huggingface_hub import hf_hub_download
import importlib.util
spec = importlib.util.spec_from_file_location("wll", hf_hub_download("endomorphosis/world_law_pipeline", "world_law_loader.py"))
wll = importlib.util.module_from_spec(spec); spec.loader.exec_module(wll)
wll.places(countries=["US", "FR"])                          # crosswalk (pandas)
t = wll.load(places=["gnis:1085809", "wd:Q10001"])              # pyarrow Table, 35 columns
t = wll.load(countries=["DE"], include_national=True, max_places=10)
```
"""


def build_card(countries: Iterable[str], stats: Optional[Dict[str, Dict[str, Any]]] = None,
               kind: str = "municipal") -> str:
    ccs = sorted({c.upper() for c in countries if c})
    national = kind == "national"
    # Quote every config_name: YAML 1.1 turns bare NO/ON/OFF/YES into bools
    # (Norway's ISO code NO broke the Hub dataset viewer with TypeError on bool name).
    cfg = ["configs:", '- config_name: "default"', "  default: true", "  data_files:",
           "  - split: train", "    path:",
           "    - world_law/data/*/*_html.parquet",      # flat countries: data/<CC>/<key>_html.parquet
           "    - world_law/data/*/*/*_html.parquet"]    # hash-bucketed countries: data/<CC>/<b>/<key>_html.parquet
    for cc in ccs:  # both layouts per country (a pattern with no match is skipped by `datasets`)
        cfg += [f'- config_name: "{cc}"', "  data_files:", "  - split: train", "    path:",
                f"    - world_law/data/{cc}/*_html.parquet", f"    - world_law/data/{cc}/*/*_html.parquet"]
    title = "World National Law" if national else "World Municipal Law"
    tags = (["- legal", "- national-law", "- legislation", "- subnational-law"] if national else
            ["- legal", "- municipal-law", "- local-government", "- ordinances"])
    yaml = "\n".join(["---", f"pretty_name: {title}", "license: other",
                      "language:", "- multilingual", "tags:", *tags, *cfg, "---"])
    intro = ("National, first-level subnational and supranational law worldwide (statutes, regulations, gazettes,\n"
             "codes), normalized to the same schema as world_municipal_law.\n\n" + SPLIT_NOTE_NATIONAL) if national else (
             "Local (municipal / county / water-board / regional) law worldwide, normalized to one schema. Companion to\n"
             "[`endomorphosis/american_municipal_law`](https://huggingface.co/datasets/endomorphosis/american_municipal_law),\n"
             "which stays unchanged.\n\n" + SPLIT_NOTE_MUNICIPAL)
    keyex = ("`iso_FR` = France national law, `iso_US-CA` = California state law, `iso_EU` = EU law" if national else
             "`wd_Q90` = Paris, `1008538` = a US place by GNIS, `KG-kg_cbd_<organ id>` = a Kyrgyz aiyl aimak council "
             "without a Wikidata item, place_id `KG-kg_cbd:<organ id>` keyed by its CBD (cbd.minjust.gov.kg) "
             "issuing-organ id; a QID found later is added as `qid`, the place_id stays")
    bucketed = ", ".join(sorted(S.BUCKETED_COUNTRIES)) if not national else "none in this repo"
    body = f"""
# {title}

{intro}
## Layout
- `world_law/data/{{CC}}/{{place_key}}_html.parquet`: one file per jurisdiction (ZSTD); large places are
  sharded as `{{place_key}}.s0001_html.parquet`, `.s0002_…` (≤20k rows / ~200 MB each)
- `world_law/metadata/{{CC}}/{{place_key}}.json`
- Countries with more than 5,000 places ({bucketed}) are hash-bucketed, because the Hub allows at most 10,000
  files per folder: `world_law/data/{{CC}}/{{b}}/{{place_key}}_html.parquet` and
  `world_law/metadata/{{CC}}/{{b}}/{{place_key}}.json`, where `b` = first 2 hex characters of
  `sha256(place_key)` (256 buckets). `places.parquet` always holds each place's exact `html_path`.
- `world_law/manifests/*.jsonl`: per-upload manifests with sha256
- `world_law/places.parquet`: crosswalk of place_id, Wikidata QID, GNIS and platform ids

`place_key` is the GNIS for US places, otherwise `place_id` with `:` replaced by `_`
({keyex}).

## Columns (`*_html.parquet`)
`cid, doc_id, doc_order, html_title, html` (same as american_municipal_law), then
`place_id, country_code, gnis, source_platform, source_url, doc_type, language, title_native,
number, adopted_date, published_date, effective_date, in_force, consolidated, content_format,
text, retrieved_at`, then optional provenance (v1.1.0): `archive_source, archive_crawl_id,
archive_timestamp, archive_url, original_url, content_complete, possibly_stale, source_policy,
source_official, source_org, license_note, extra_metadata` (JSON string of other source fields),
then (v1.2.0) `pdf_ref`: for documents whose source is an image-only scanned PDF, the PDF in
[endomorphosis/world_law_scanned_pdfs](https://huggingface.co/datasets/endomorphosis/world_law_scanned_pdfs)
as `endomorphosis/world_law_scanned_pdfs:pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf` (loose file) or, for PDFs
uploaded since 2026-10-18, `endomorphosis/world_law_scanned_pdfs:shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar#member=<place_key>/<sha256>.pdf&offset=<o>&size=<n>&sha256=<h>`
(one member of a per-country tar shard, fetchable with one HTTP Range request); null otherwise. Files
written before v1.2.0 have no `pdf_ref` column — treat it as null. `world_law_loader.fetch_pdf(row)` downloads
either form (`fetch_pdf_bytes` returns the bytes) and checks the sha256.
**Access:** `world_law_scanned_pdfs` is a private dataset, so resolving a `pdf_ref` needs a Hugging Face token
that is authorized for it (set `HF_TOKEN`, or pass `token=` to the loader). The text, metadata and every other
column in this dataset are public and need no token.

Related datasets: [world_municipal_law](https://huggingface.co/datasets/endomorphosis/world_municipal_law) (local
places) · [world_national_law](https://huggingface.co/datasets/endomorphosis/world_national_law) (`iso:*` places) ·
[world_law_scanned_pdfs](https://huggingface.co/datasets/endomorphosis/world_law_scanned_pdfs) (scanned source PDFs) ·
code: [world_law_pipeline](https://huggingface.co/endomorphosis/world_law_pipeline).
`content_complete=false` marks metadata-only / partial records.

`doc_type` ∈ code_section | ordinance | regulation | statute | gazette_act | decision.
`consolidated=false` marks as-published gazette acts.

`cid` = IPFS CIDv1 (raw, sha2-256, base32) of `{{place_key}}_{{doc_id}}.json`, which is identical
to american_municipal_law for US places.

{provenance_section(stats)}
## Configs
`default` covers every country; there is also one config per ISO 3166-1 country code
({", ".join(ccs) if ccs else "added as data lands"}). A country config can show as empty until its
first files are uploaded.

## Code
The scrapers, normalizer/uploader, schema and place-code crosswalk that build this dataset are published at
[`endomorphosis/world_law_pipeline`](https://huggingface.co/endomorphosis/world_law_pipeline).
Rows whose live fetch was not permitted (robots.txt unreachable or disallowing) are held back and not published.

## Licence
The texts come from official government sources under various open licences (CC0, CC-BY, OGL,
NLOD, public domain) and from codifier platforms, following the existing US practice. Each row's
`source_platform` and `source_url` identify its origin, so check the source's terms before reuse.
"""
    return yaml + "\n" + body.rstrip("\n") + "\n" + LOADER_SECTION
