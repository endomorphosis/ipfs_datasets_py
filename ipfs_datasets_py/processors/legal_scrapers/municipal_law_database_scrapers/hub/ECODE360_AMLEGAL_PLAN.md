# eCode360 + American Legal scrape plan

## Schema target
Same as Municode → `parquet_writer.docs_to_html_rows` / citation parquet:
`Id`, `Title`, `TitleHtml`, `Content`, `DocOrderId` → html parquet
(`cid`, `doc_id`, `doc_order`, `html_title`, `html`) + citation parquet.

## eCode360 (835 URLs)
**Feasible via public HTML (no auth).** Prefer this over licensed `developer.ecode360.com`.

1. `GET https://ecode360.com/{custId}` (e.g. `DI3285`, `BU1237`)
2. Parse `data-toc-nodes` (HTML-escaped JSON) for full TOC tree
3. Fetch each chapter/leaf numeric guid: `GET https://ecode360.com/{guid}`
4. Parse `div.*_content.content` blocks + `data-full-title` / `data-position`
5. Emit one doc per guid (chapter/article/section)

**Politeness:** UA identifying bot + project; ≥0.6–1.0s between GETs; honor 429 / Cloudflare “Just a moment”; backoff.
**Avoid:** `/api/{custId}/…` (401), aggressive `/ajax/*` (Cloudflare).

**MVP:** `ecode360_draft.py` — Diamond MO (`DI3285`), 2 chapters → 11 docs. Wired from `ecode360.py`.

## American Legal (`codelibrary.amlegal.com`, 1237 URLs)
**Feasible via public JSON API (no auth discovered).**

```
GET /api/clients/{slug}/
GET /api/client-version/{slug}/latest/
GET /api/code-toc/{code_uuid}/
GET /api/section-toc/{section_id}/
GET /api/render-doc/{slug}/{version}/{code_slug}/{doc_id}/
GET /api/sec-info/{slug}/{version}/{code_slug}/{doc_id}/
```

1. Parse slug from `…/codes/{slug}/latest/overview`
2. Load version TOC → pick primary code (municipal code > zoning)
3. Recursively expand `section-toc` for `has_children`
4. `render-doc` each node; sanitize JSX (`className`→`class`, strip `AnnotationDrawer`/`CodeOptions`, `Link`→`a`)

**Politeness:** ≥0.4–0.7s; same UA/429 handling; optional concurrency=1.

**MVP:** `amlegal_draft.py` — Silverton OH, 15 nodes with HTML. Wired from `amlegal.py`.

## Legal / ToS (high level — not legal advice)
- eCode360 ToS: content for personal use; copyright asserted by General Code/municipalities; commercial exploitation restricted; informational only / not official.
- AmLegal: codes are municipal law published for public access; review amlegal.com terms before bulk commercial redistribution.
- Treat as public-law text with publisher copyright in compilation/markup; prefer attribution, rate limits, no login bypass, no HF upload until policy review.
- Common Crawl index (`endomorphosis/common_crawl_municipal_index`) is a polite fallback/mirror for historical snapshots when live hosts throttle.

## Batch integration next steps
1. Extend `run_batch.py` (or sibling) to dispatch `publisher` → ecode360/amlegal `scrape_jurisdiction`
2. Map CSV `source_url` + `gnis`/`place_name`/`state_code` into `write_jurisdiction`
3. Resume/skip-existing by gnis parquet presence
4. Cap per-host QPS; checkpoint TOC progress (amlegal node ids / ecode guids)
5. Tune history-note regexes for eCode `class="history"` / `hisdate` and amlegal ord patterns
6. Optional: WARC replay from common_crawl index when 429 persists
