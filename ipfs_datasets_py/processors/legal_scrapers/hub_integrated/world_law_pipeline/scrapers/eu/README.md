# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
# EU lane scrapers

## `cvdr.py` — Netherlands CVDR (lokaleregelgeving.overheid.nl)

All decentralised regulations of Dutch gemeenten, provincies, waterschappen, gemeenschappelijke
regelingen, Caribbean public bodies (Bonaire/Saba/St Eustatius) and the kingdom parts (Curaçao, Sint Maarten).

**Endpoints (verified 2026-10-10)**
- Discovery: KOOP SRU 2.0 `https://zoekservice.overheid.nl/sru/Search?x-connection=cvdr&operation=searchRetrieve&version=2.0`
  with `query=overheidrg.datumGeldendOp=<date>` (versions in force on that date), `maximumRecords=1000`,
  `startRecord` paging. All records: 343,750; in force on 2026-10-10: **103,823** (all retrieved, unique = declared).
- Full text: `https://repository.officiele-overheidspublicaties.nl/cvdr/CVDR<n>/<v>/xml/CVDR<n>_<v>.xml`
  (`publicatieurl_xml` from SRU). No robots.txt on that host.
- Note: `zoekservice.overheid.nl/robots.txt` is `Disallow: /`. We use it anyway because it's the official reuse API:
  KOOP documents it for developers (Handleiding SRU 2.0, overheid.nl "Informatie hergebruiken"),
  and the SRU explain says "Database is freely available". The data is CC0. Discovery is only ~105 requests;
  everything else comes from the repository host.

**Politeness:** single thread, ≥0.65 s between requests (~1.5 req/s), exponential backoff (honours Retry-After),
UA `world-municipal-law-research/1.0 (...)`.

**Scope:** only current (in-force) versions, pass 1. **TODO, later pass:** historical versions (`overheidrg.datumGeldendOp` dropped,
~240k more versions). Use a new `--valid-on` or a separate query, with new batch names.

**Output** (follows `/workspace/world_law/pipeline/SCHEMA.md` v1.0.0)
- `staging/eu/<CC>/<place_key>.cvdr<YYYYMMDD>_bNNNN.jsonl`: one place per file. Files are written as a dot-tmp, then fsync,
  `schema.validate_file`, and `os.rename`, and are never rewritten. CC is `NL`, plus `CW`/`SX` for Curaçao and Sint Maarten (`iso:CW`/`iso:SX`, admin_level `country`).
- `staging/eu/_unmatched/cvdr_unmatched_<YYYYMMDD>_bNNNN.jsonl`: same record shape with `place_id: null`
  (waterschappen, regional cooperation bodies, Nederlandse Antillen, municipalities missing from the candidate CSV).
- `staging/eu/_raw/cvdr/CVDR<n>/<id>.xml.gz`: raw XML (also `raw_xml_url`).
- `staging/eu/_state/`: `catalog_<date>.jsonl` (SRU metadata), `discover_<date>.json`, `done_<date>.txt`,
  `batchno_<date>.txt`, `failed_<date>.jsonl`. `staging/eu/_logs/cvdr.log`. `staging/eu/_invalid/`: rows failing schema validation.
- Records carry the SCHEMA fields (`doc_id`=`CVDR<n>_<v>`, `number`=`CVDR<n>`, `doc_type=regulation`, `consolidated=true`,
  `in_force=true`, `content_format=xml`, `text`, `adopted_date`=dcterms:issued, `effective_date`=inwerkingtredingDatum),
  plus rich extras: `issuing_body_name/scheme/code/qid`, `level`, `place_match`, `withdrawn_date`, `cvdr_work_id`,
  `cvdr_version`, `raw_xml_url/path`, and the full `sru_meta` dict.

**Place mapping** (`PlaceMap`): the CVDR creator name is matched to Wikidata NL bodies (`data/wd_nl_bodies.csv`: nl/en labels, aliases, CBS P382),
and from there to the candidate CSV qid, which gives `wd:Q…`. `platform_place_id` / `issuing_body_code` = `GM<CBS>`.
- Merged-away municipalities: `data/nl_mergers_manual.csv`, then Wikidata P1366/P1365, map them to the successor (`place_match=former_municipality->successor`).
- Provinces: `iso:NL-XX` (SCHEMA §3), with `qid` = the candidate's province QID.
- Bonaire/Saba/St Eustatius: matched by name to the candidate rows.
- Known unmatched municipalities: Smallingerland, Opsterland, Weststellingwerf, Ooststellingwerf and Dantumadiel are missing from
  `global_municipalities_candidate.csv`. Maasdonk was split between Oss and 's-Hertogenbosch, so it's ambiguous.

**Run / resume**
```
cd /workspace/world_law/pipeline/scrapers/eu
nohup python3 cvdr.py discover >> /workspace/world_law/staging/eu/_logs/discover.nohup.out 2>&1 &   # done; idempotent
nohup python3 cvdr.py fetch    >> /workspace/world_law/staging/eu/_logs/fetch.nohup.out 2>&1 &      # resumes from _state/done_*.txt
python3 cvdr.py status
python3 cvdr.py fetch --test 40   # random sample into staging/eu/_test/
```
Resume is safe after a kill. Only the in-memory partial batch (≤1000 docs) is redone, and its XML is already cached in `_raw`.
Reuses `text_of()` from `ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_bwb.py`, which is the same KOOP XML family.

## `pl_dzienniki.py` — Poland, 16 voivodeship official journals (Dzienniki Urzędowe Województw)

**Endpoints (ABC PRO e-Dziennik ELI API, identical on every host, no key; verified 2026-10-10)**
- `https://<host>/api/eli/acts` returns the publisher and its years.
- `/api/eli/acts/POL_WOJ_<XX>/<year>` returns the full yearly list. Called without `limit`, it's complete (checked: `len(items) == totalCount`).
- `/api/eli/acts/POL_WOJ_<XX>/<year>/<pos>/text.pdf` is the official PDF, our text source (`pdftotext -layout`, with the journal header and footer stripped).
  `text.html` is only a fallback because it's usually just page 1 (flagged `text_source=html_first_page_only`).
- robots.txt on every reachable host: `Disallow: /login` only. Acts are official documents, so no copyright applies (art. 4 of the Polish Copyright Act).
- Hosts: DS edzienniki.duw.pl · KP edzienniki.bydgoszcz.uw.gov.pl · LB edziennik.lublin.uw.gov.pl · LS dzienniki.luw.pl ·
  LD dziennik.lodzkie.eu · MP edziennik.malopolska.uw.gov.pl · MZ edziennik.mazowieckie.pl · OP duwo.opole.uw.gov.pl ·
  PK edziennik.rzeszow.uw.gov.pl · PL edziennik.bialystok.uw.gov.pl · PM edziennik.gdansk.uw.gov.pl · SL dzienniki.slask.eu ·
  SK edziennik.kielce.uw.gov.pl · WM edzienniki.olsztyn.uw.gov.pl · WP edziennik.poznan.uw.gov.pl · ZP e-dziennik.szczecin.uw.gov.pl
- **Blocked from the box (2026-10-10): KP, LB, WP.** The TLS handshake gets EOF and port 80 times out, an IP or network-level block.
  The run re-probes these hosts every hour (48 tries) and logs `UNREACHABLE/BLOCKED`.
- MP, LS and LD serve an incomplete TLS chain. We add the Certum intermediates (fetched over https from repository.certum.pl, the AIA URL)
  to `_state/pl_certs/ca_bundle_plus.pem` and keep **full** verification on.
- Opole (WAF) and Mazowieckie (Akamai) accept our honest project UA with ordinary `Accept`/`Accept-Language` headers. We don't use browser impersonation.

**Pass 1 scope (this run):**
- **Issuers:** gmina and powiat organs (rada, wójt, burmistrz, prezydent, starosta, zarząd powiatu), plus sejmik/zarząd województwa and wojewoda.
- **Types:** Uchwała, Zarządzenie, Rozporządzenie, plus Obwieszczenie when it publishes a consolidated text (`consolidated=true`).
- **Status:** `obowiązujący` only.
- **Excluded for now:** budget and financial resolutions (budżet, WPF, sprawozdania, kredyty…).
- **Order:** newest years first.
- Everything else stays in `_state/pl/catalog_<XX>.jsonl` for later passes (repealed acts, budgets, porozumienia, rozstrzygnięcia nadzorcze, WSA rulings).

**Place mapping:**
- The issuer comes from the title (`… Rady Gminy w Imielnie z dnia …`). The toponym is matched, with tolerance for Polish inflection
  (word-prefix matching plus a few irregular forms), against Wikidata P1653 TERYT names within the journal's voivodeship
  (`data/wd_pl_teryt.csv`; 10-digit NTS-style codes are normalised to 7-digit TERYT).
- The TERYT is then matched to a candidate CSV row, falling back to the same 6-digit gmina code (city item vs. gmina item).
- Voivodeship organs map to `iso:PL-XX`.
- Powiats are kept but mostly end up in `_unmatched/` because the candidate CSV has only 27 powiats. Their TERYT, level and qid are recorded.
- Ambiguous same-name gminas within a voivodeship (e.g. 3× Czarna in PK, 2× Słupia in SK) stay unmatched, with the reason in `place_match`.

**Output:**
- `staging/eu/PL/<place_key>.pldz_<XX>_bNNNNN.jsonl` (`doc_type=gazette_act`, `consolidated=false`, `doc_id` = ELI `POL_WOJ_XX/yyyy/pos`).
- `_unmatched/pl_<XX>_unmatched_bNNNNN.jsonl`.
- PDFs aren't stored because of volume; `pdf_url` and `pdf_sha256` are kept.
- Scanned PDFs without a text layer go to `_state/pl/failed_<XX>.jsonl`. OCR is a later pass.

**Run / resume:**
```
cd /workspace/world_law/pipeline/scrapers/eu
# ONE low-memory process (2026-10-10 22:33 PT; replaces the 3 `pl_dzienniki.py all` workers):
MALLOC_ARENA_MAX=2 setsid nohup python3 -u pl_run.py --workers 6 >> /workspace/world_law/staging/eu/_logs/pl_run.nohup.out 2>&1 < /dev/null &
# stop gracefully with `kill -TERM <pid>` (finishes current docs, flushes all buffers). Never run pl_run.py twice.
# 6 worker threads round-robin over the 13 reachable hosts; a host is used by one worker at a time and Host.get keeps
# >= 0.7 s (or robots Crawl-delay) between its requests. Queue on disk: _state/pl/queue_<WOJ>.jsonl (built once by
# streaming the catalog), done-set in _state/pl/pl_done.sqlite (imports done_<WOJ>.txt, which are still appended).
# PDFs stream to a temp file -> pdftotext subprocess. Per-host flush at 100 docs / 8 MB / 15 min. RSS target < 500 MB.
# Catalog refresh (KP/LB/WP re-probe etc.) still uses: python3 pl_dzienniki.py catalog --woj ...
python3 pl_dzienniki.py status
python3 pl_dzienniki.py fetch --woj SK --test 5     # sample into staging/eu/_test_pl/
```
Each host is its own thread with ≥0.7 s between requests on that host. Re-running skips finished years and docs (`_state/pl/done_<XX>.txt`).
Log: `staging/eu/_logs/pl_dzienniki.log`.

## robots.txt (RFC 9309)

All EU-lane fetchers gate requests through `common/rfc9309.py`. It's vendored from `scrapers/asia_latam/common/rfc9309.py`, with two additions:
- **BOM fix:** a UTF-8 BOM is stripped, because the Polish hosts send one, and it would otherwise hide the first `User-agent` line.
- **`RobotsCache`:** follows RFC 9309. 2xx → parse; 4xx → allow all; 5xx/unreachable → disallow all and re-check later. `Crawl-delay` is honoured.
- Accepted exception: the CVDR SRU listing on `zoekservice.overheid.nl` (`Disallow: /`), the official KOOP reuse API (CC0). It was used for discovery only.
- Audit: `python3 tools/robots_audit.py` writes `staging/eu/_logs/robots_audit.json`.
- 2026-10-10 16:41 PT re-audit: 0 disallowed content URLs; nothing quarantined (`staging/eu/_quarantine_robots/` not needed). Checked:
  - 8,138 CVDR repository XMLs (that host has no robots.txt);
  - 26,006 PL act PDF/HTML URLs;
  - 279 PL list URLs (PL hosts allow everything except `/login`). The 3 flagged are KP/LB/WP, whose robots.txt is
    unreachable (TLS failure => RFC 9309 "disallow all"); nothing was ever fetched from them.
- Mapping tables were built with `query.wikidata.org/sparql` (4 queries), but its robots.txt says `Disallow: /sparql`. Flagged.
  Don't make further SPARQL calls; the tables are cached in `data/`. Use Wikidata dumps or another allowed route for future crosswalks.

## Archive harvests for network-blocked sources (`archive_jobs.py`)

Approved by Benjamin on 2026-10-10: public web archives (Common Crawl first, then Wayback Machine; never archive.today)
for hosts that are **network-blocked/unreachable from the box**, never to get around a robots.txt Disallow.
Uses ONLY the shared fetcher `/workspace/world_law/pipeline/archive/` (`ArchiveFetcher`, box-wide limiter,
`StagedWriter`, `provenance_fields`); no private Wayback/CC client. Interpreter: `/workspace/world_law/pipeline/venv/bin/python`.

Robots: the live robots.txt of these hosts is unreachable, so the newest **archived** robots.txt is fetched through
the same fetcher and every original URL is checked with `common/rfc9309.py` before it is fetched from the archive.
- RIS (`www.ris.bka.gv.at`, Wayback 2026-05-01): `Disallow: /Dokument.wxe`, `/GeltendeFassung*`, `/eli/*?`, `/showdata/`,
  `crawl-delay: 5`. We take **only** `/Dokumente/Gemeinderecht/<Nr>/<Nr>.{pdf,html,rtf}` (allowed). `Dokument.wxe` pages are never used.
- PL KP/LB/WP: no archived robots.txt exists; the 13 reachable hosts of the same ABC PRO platform all serve
  `Disallow: /login` only, so `/login*` is excluded and that default is assumed (logged in `discover.json`).

Live retries before falling back (2026-10-10 18:2x PT): `data.bka.gv.at` / `www.ris.bka.gv.at` and the KP/LB/WP hosts
fail in the TLS handshake (`unexpected eof`, also with TLS 1.2; port 80 times out), i.e. a network block, not a certificate
problem, so a CA bundle cannot help.

| target | archived URL pattern | state | output |
|---|---|---|---|
| `at` RIS Gemeinderecht | `/Dokumente/Gemeinderecht/GEMRE_<Land>_<GKZ>_…/…{.pdf>.html>.rtf}` | `_state/archive/at/` | `AT/<place_key>.atgr_archive_bNNNNN_<UTC>p0001.jsonl` |
| `pl` KP/LB/WP journals | `/WDU_<X>/<y>/<pos>/akt.pdf` > `…/Oryginal/akt.pdf` > `GetActPdf.ashx?year=&book=0&position=` | `_state/archive/pl/` | `PL/<place_key>.pldz_KPLBWP_archive_bNNNNN_<UTC>p0001.jsonl` |

- Every record carries `archive_source`, `archive_crawl_id`, `archive_timestamp`, `archive_url`, `original_url`
  (= `source_url`), `content_complete`, `possibly_stale` + `extra_metadata.archive`; `StagedWriter` also writes the
  sidecar `staging/eu/_archive_provenance/<CC>/<file>`. Unmatched → `_unmatched/{at,pl}_archive_unmatched_bNNNNN.jsonl`.
- AT mapping: GKZ (5 digits in the Dokumentnummer) → Statistik Austria Gemeindeliste 2026 (`data/at_gkz_2026.csv`, from
  `statistik.at/verzeichnis/reglisten/gemliste_knz.pdf`) → unique name match in the candidate CSV. Wikidata P964 was not
  used because `query.wikidata.org/sparql` and `wikidata.org/w/api.php` are robots-disallowed. Wien (GKZ 9xxxx) → `iso:AT-9`
  (city = Land). Unknown (pre-2015 Styrian) or ambiguous GKZ names stay unmatched with `gkz`, `level=municipality`.
- AT records: `doc_type=ordinance`, title = heading block of the document, `adopted_date` from "vom <d>. <Monat> <yyyy>".
- PL records: the archived journals have no ELI list JSON, so title/issuer come from the PDF's first lines and the same
  pass-1 rules as `pl_dzienniki.py` (type, gmina/powiat/voivodeship organ, no budget acts); `status`/`in_force` unknown;
  `doc_id = POL_WOJ_<KP|LB|WP>/<year>/<pos>` (same form as the live ELI ids).
- Resumable: `done.txt` per target; archive errors (`ArchiveError giving up`) are not marked done and are retried.
```bash
cd /workspace/world_law/pipeline/scrapers/eu; PY=/workspace/world_law/pipeline/venv/bin/python
ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup $PY -u archive_jobs.py all at --no-cc >> /workspace/world_law/staging/eu/_logs/archive_at.nohup.out 2>&1 < /dev/null &
ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup $PY -u archive_jobs.py all pl --no-cc >> /workspace/world_law/staging/eu/_logs/archive_pl.nohup.out 2>&1 < /dev/null &
# batches: 50 docs or 15 min; SIGTERM flushes then exits; fetched bodies are in archive/_cache so a restart replays them without network
$PY archive_jobs.py status
```
Max 2 archive workers for this lane (the limiter serialises Wayback box-wide; more workers only queue).


## Batch naming (uploader contract, 2026-10-10 22:xx PT)
Every NEW staged file carries a UTC timestamp; for the same `doc_id` the newer timestamp wins:
- CVDR: `NL/<place_key>.cvdr_<YYYYMMDDTHHMMSSZ>p0001.jsonl`, `_unmatched/cvdr_unmatched_<UTC>p0001.jsonl`
- Poland: `PL/<place_key>.pldz_<WOJ>_<UTC>p0001.jsonl`, `_unmatched/pl_<WOJ>_unmatched_<UTC>p0001.jsonl`
- Archive: `<CC>/<place_key>.{atgr,pldz_KPLBWP}_archive_bNNNNN_<UTC>p0001.jsonl`
- ES BOE AC: `ES/iso_ES-XX.esboe_ac_<UTC>p0001.jsonl`, `_unmatched/esboe_ac_unmatched_<UTC>p0001.jsonl`
- Re-map: `<CC>/<place_key>.<src>remap_<UTC>p<NNNN>.jsonl` (`tools/remap_unmatched.py`)
Older `_bNNNN` files are left as they are.


## `es_boe_ac.py` — Spain BOE legislación consolidada autonómica

Autonomous-community (ámbito Autonómico) consolidada norms from the BOE open-data API.
**Not** provincial BOP gazettes (`asia_latam/es/es_bop.py`).

**Endpoints (verified 2026-10-11)**
- List: `GET https://www.boe.es/datosabiertos/api/legislacion-consolidada`
  with `query={"query":{"query_string":{"query":"ambito@codigo:2"}}}`, `limit=500`, `offset` paging,
  `Accept: application/json`. Catalog size **3620** (2026-10-11).
- Full text: `…/legislacion-consolidada/id/{BOE-A-…}/texto` (`Accept: application/xml`).
- Docs: https://www.boe.es/datosabiertos/documentos/APIconsolidada.pdf · schemas `legislacion-consolidada-*`.
- robots.txt: search result URLs (`/buscar/legislacion.php?` etc.) and some xml/pdf mirrors are Disallow;
  `/datosabiertos/api/…` and `/buscar/act.php?id=…` are allowed. Gated via `common/rfc9309.py`.

**Place mapping:** ELI `/eli/es-xx/` → `iso:ES-XX` (SCHEMA §3 adm1), else departamento name → ISO 3166-2.
`common/xwalk.py` loads ES `es_ine` (municipal) from `place_codes.parquet` for other ES work; AC law does not use INE codes.
Never invent place_ids. Unmatched CCAA (if any) → `_unmatched/esboe_ac_unmatched_<UTC>p0001.jsonl`.

**Output**
- `staging/eu/ES/iso_ES-XX.esboe_ac_<YYYYMMDDTHHMMSSZ>p0001.jsonl` (atomic `.tmp` → `validate_file` → rename)
- `_raw/es_boe_ac/<id>.xml.gz`, `_state/es_boe_ac/{catalog.jsonl,discover.json,done.txt,batchno.txt,failed.jsonl}`
- `source_platform=es_boe_ac`, `doc_type` statute|regulation, `consolidated=true`, `content_format=xml`, `language=es`

**Run / resume**
```bash
cd /workspace/world_law/pipeline/scrapers/eu
# discover once (idempotent rewrite of catalog):
python3 es_boe_ac.py discover
# ONE low-memory live fetch (resumes from _state/es_boe_ac/done.txt):
MALLOC_ARENA_MAX=2 setsid nohup python3 -u es_boe_ac.py fetch \
  >> /workspace/world_law/staging/eu/_logs/es_boe_ac.nohup.out 2>&1 < /dev/null &
python3 es_boe_ac.py status
python3 es_boe_ac.py fetch --test 5   # sample into staging/eu/_test_es/
```
Politeness: ≥0.75 s between requests, UA `world-municipal-law-research/1.0`, flush every 80 docs / 12 MB.
RSS target < 500 MB (`MALLOC_ARENA_MAX=2`). Do not run two fetch processes.

## Place-code crosswalk
EU scrapers prefer `/workspace/world_law/pipeline/codes/place_codes.parquet` (fallback CSV) via `common/xwalk.py` (lazy per
country, ambiguous codes dropped): PL `pl_teryt_terc`/`pl_nts` (TERYT, also tried with type digit 3/1/2), NL `nl_cbs_gemeente`,
AT `at_gkz`, ES `es_ine`. AC BOE uses SCHEMA `iso:ES-XX` for adm1 (not INE). Own tables (wd_pl_teryt.csv, wd_nl_*.csv, at_gkz_2026.csv + names) are the fallback.
`tools/remap_unmatched.py` re-maps `_unmatched/` (streaming, idempotent via `_state/remap_done.txt`). First run
2026-10-10: 11,865 unmatched docs checked, 0 newly matched (PL: 10,191 are powiat acts whose TERYT resolves but the
powiats are not in the candidate CSV / crosswalk; 777 ambiguous + 749 unparsed issuers; NL: 174 Frisian municipalities
not in the candidate CSV).
CVDR (`cvdr.py fetch`) now streams a creator-sorted disk queue `_state/queue_<date>.jsonl` and flushes at 1,000 docs or 16 MB.

## Live scrapers on `common/live.py` (2026-10-11)
Shared plumbing: `PoliteSession` (RFC 9309 robots per request incl. Crawl-delay, ≥1 s/host, exponential backoff),
`Done` (sqlite done-set), `Stager` (UTC-named per-place files `<CC>/<place_key>.<src>_<UTC>p<NNNN>.jsonl`,
tmp → fsync → `schema.validate_file` → rename; invalid rows → `_invalid/`, unmatched → `_unmatched/<src>_unmatched_<UTC>p0001.jsonl`).
All are single-threaded, one process each, `MALLOC_ARENA_MAX=2`, setsid+nohup, ~45–110 MB RSS. Each command below is
also the resume command (catalog and fetch both checkpoint; finished ids live in `_state/<cc>/done.sqlite`).
`--test N` writes to `staging/eu/_test_<cc>/` with a separate done db.

### `ee_rt.py` — Estonia, Riigi Teataja RT IV (local-government acts), source tag `eert`
List API `https://www.riigiteataja.ee/api/oigusakt_otsing/1/otsi?kov=true&kehtiv=2026-10-11` (45,973 rows; rows with
`kehtivKehtetus=true` are repealed stubs → marked done `repealed_stub`), XML `public-api/api/v1/akt/<globaalID>/xml`
(huge_tree parser; embedded base64 blobs dropped). Places: issuer → candidate "X Rural Municipality"; the 15 current
cities and pre-2017 municipalities are not in the candidate CSV → `_unmatched`.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u ee_rt.py all >> /workspace/world_law/staging/eu/_logs/ee_rt.nohup.out 2>&1 < /dev/null &
python3 ee_rt.py status
```
Logs `_logs/ee_rt.log`; state `_state/ee/` (catalog.jsonl, done.sqlite, failed.jsonl).

### `lv_likumi.py` — Latvia, likumi.lv pašvaldību domes saistošie noteikumi, source tag `lvlik`
43 councils from `/ta/veids`; per council the listing page gives `izd_id/veids_id`, rows from
`/ajax/ties_akti_pec_veida.php` (the listing's own JSON; in force + not yet in force), text from `/ta/id/<id>` (div.doc-body,
current consolidated text). Never uses `/search.php`, `/doc.php`, `/rss/`, `/*/redakcijas-datums/` (robots). Places: fixed
slug → candidate table (7 state cities + 35 novadi); Varakļāni novads not in candidate CSV → unmatched.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u lv_likumi.py all >> /workspace/world_law/staging/eu/_logs/lv_likumi.nohup.out 2>&1 < /dev/null &
python3 lv_likumi.py status
```

### `si_ul.py` — Slovenia, Uradni list RS section OBČINE (1991 – 28.2.2026), source tag `siul`
Issue index `/glasilo-uradni-list-rs/celotno-kazalo/<YYYY><issue>` (5 consecutive misses or HTTP 500 = end of year),
act text `/glasilo-uradni-list-rs/vsebina/<SOP>/<slug>` (div#divSection). Terms exempt gazette content; the crawl ban covers
only the razglasni del (not touched). Places: gazette municipality header → candidate base name (212/212 current
municipalities matched). Issues after 28.2.2026 live on PISRS, whose API needs a permit → not used.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u si_ul.py all >> /workspace/world_law/staging/eu/_logs/si_ul.nohup.out 2>&1 < /dev/null &
python3 si_ul.py status
```

### Lithuania (e-TAR) — blocked, nothing built
`www.e-tar.lt` answers 403 Cloudflare challenge to every request incl. robots.txt; the official open data
(`get.data.gov.lt/datasets/gov/lrsk/teises_aktai/...`) answers a WAF "Web Page Blocked" page for the box IP. Logged in
`_logs/blocked_sources.jsonl`. Archive target added: see "Lithuania e-TAR via Wayback" below.

### Lithuania e-TAR via Wayback (`archive_q2.py lt`, tag `ltetar`, added 2026-10-12)
- Live e-TAR stays network-blocked (Cloudflare 403, robots.txt included), so it is never crawled live. Discovery is a Wayback CDX prefix over `www.e-tar.lt/rs/legalact/` and `e-tar.lt/rs/legalact/`. Text comes from the archived `/rs/legalact/<id>/` HTML (the portal iframe), with DOCX, ODT and PDF format captures as fallback.
- Only municipal council decisions are kept: the text must start with "<STEM> SAVIVALDYBĖS TARYBA SPRENDIMAS". Everything else is marked done `not_municipal_council`. `doc_type` is decision. Places: genitive stem goes through `LT_GEN` to the 53 candidate municipalities. The 7 city municipalities (Vilniaus/Kauno/Klaipėdos/Šiaulių/Panevėžio/Alytaus/Palangos miesto) aren't in the candidate CSV, so they go to `_unmatched` as `city_municipality_not_in_candidate` until place_additions covers them.
- Queued after `czfirst` (cz, then at/pl resume, then be). A waiter shell polls pid 1907758 every 10 min, then runs the command below. If the waiter is gone and czfirst has finished, run it by hand (check `ps` first):
```
cd /workspace/world_law/pipeline/scrapers/eu && ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup /workspace/world_law/pipeline/venv/bin/python -u archive_q2.py all lt >> /workspace/world_law/staging/eu/_logs/archive_lt.nohup.out 2>&1 < /dev/null &
```

### `be_lokaalbeslist.py` — Flanders, Lokaal Beslist harvester SPARQL, source tag `belb`
`orgs` (centrale-vindplaats: bestuursorgaan → bestuurseenheid, `_state/be_lb/orgs.json`, 32,006 organen), `catalog`
(4 harvesters, besluiten whose title contains reglement/verordening and that carry prov:value; 175,414 rows), `fetch`
(VALUES batches of 40, ≥3 s between queries). Place: passed_by → eenheid (Gemeente/OCMW) → candidate, else publication
host → candidate. Fine type in `regulation_kind` (traffic/police/tax/regulation); `doc_type` = regulation.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u be_lokaalbeslist.py all >> /workspace/world_law/staging/eu/_logs/be_lokaalbeslist.nohup.out 2>&1 < /dev/null &
```

### `uk_ukla.py` — UK Local Acts (legislation.gov.uk Atom feed + CLML), source tag `ukla`, Crawl-delay 5 honoured
Only council/corporation acts are fetched; company/harbour/railway acts → done `non_municipal`; pre-1991 acts carry
no digitised text → done `no_digitised_text`. `doc_type` = statute (`act_kind` "UK Local Act").
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u uk_ukla.py all >> /workspace/world_law/staging/eu/_logs/uk_ukla.nohup.out 2>&1 < /dev/null &
```

### `it_statuti.py` — Italy, Ministero dell'Interno raccolta statuti comunali/provinciali, source tag `itstat`
List `/territorio-e-autonomie-locali/statuti?page=0..414`, detail page → PDF (`/documenti/statuti/...`, ≤40 MB,
streamed to a temp file → pdftotext). Places: unique comune name → candidate; ambiguous names and province statutes → unmatched.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u it_statuti.py all >> /workspace/world_law/staging/eu/_logs/it_statuti.nohup.out 2>&1 < /dev/null &
```

### `chain_after.sh <pid> <script.py> <log>`
Waits until a catalog process exits, then runs `<script.py> all` (used for si_ul and it_statuti: catalog → fetch).

### `archive_q2.py` — second-wave archive targets (Wayback only, lane eu, shared limiter), queued after at/pl
* `cz` sbirkapp.gov.cz (network_blocked): 13,259 archived detail ids, 2,483 with an archived `/text` file (PDF/ODT/DOCX)
  → `CZ/<pk>.czspp_archive_<UTC>p0001.jsonl`. Publisher name → candidate (unique names only).
* `be` www.ejustice.just.fgov.be/eli/ (robots_disallowed live): 5,287 archived acts; only regional (Flemish/Walloon/
  Brussels) acts are kept, tagged `source_policy=archived_robots_disallowed`; never crawled live.
* `hu` or.njt.hu: NOT built — archived ELI pages hold title/metadata only (text is loaded by JavaScript) and NJT
  reserves all rights on its texts ("minden jogot fenntart"): needs a decision.
```
cd /workspace/world_law/pipeline/scrapers/eu && ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup /workspace/world_law/pipeline/venv/bin/python -u archive_q2.py queue >> /workspace/world_law/staging/eu/_logs/archive_q2_queue.nohup.out 2>&1 < /dev/null &
/workspace/world_law/pipeline/venv/bin/python archive_q2.py status
```
(`queue` polls every 10 min until no `archive_jobs.py all|fetch at|pl` process is alive, then runs cz, then be.)

### Portugal (DRE) — researched, not built
diariodarepublica.pt is a JavaScript single-page app (no server-rendered act pages, robots.txt redirects to the app);
the only static official sources are the daily RSS per Série II part (`files.diariodarepublica.pt/rss/serie2&parte=h-html.xml`,
municipalities = Parte H, today only) and whole-issue PDFs (`files.diariodarepublica.pt/gratuitos/2s/YYYY/MM/2S<nnn>A0000S00.pdf`).
A backfill would need issue-PDF splitting by act; the app's internal API was not used.

## Crosswalk expansion remap (2026-10-11, place_additions.csv)
- `common/xwalk.py` has `ADDITIONS` (codes/place_additions.csv: 314 PL powiats=county, 21 NL water boards with nl_tooi ws-codes, 5 Frisian municipalities).
- `pl_dzienniki.PlaceMap.cand_for_teryt`: crosswalk pids missing from the candidate CSV now take name, admin_level (county) and iso from ADDITIONS (`_via=crosswalk+additions`).
- `cvdr.PlaceMap`: CBS→crosswalk→additions for the Frisian municipalities. There is a new `Waterschap` branch: the creator name → additions (nl_tooi), admin_level=water_board, and issuing_body_code / platform_place_id=wsNNNN. Merged boards map to their successor (Vallei & Eem / Veluwe → Vallei en Veluwe; Velt en Vecht → Vechtstromen).
- `cvdr.py fetch` now stops gracefully on SIGTERM: it flushes the buffer, then exits. Resume with the same command.
- Re-map unmatched records (idempotent, streaming, ~150 MB). It writes new `<pk>.<src>remap_<UTC>pNNNN.jsonl` batches, and consumed doc_ids are listed in `_state/remap_done.txt`. Re-run it after pl_run/cvdr flush new unmatched records:
  `cd tools && MALLOC_ARENA_MAX=2 python3 -u remap_unmatched.py [--dry-run] [--only pl_DS,cvdr] > ../../../../staging/eu/_logs/remap_unmatched_$(date -u +%Y%m%dT%H%M%SZ).log 2>&1`

## Successors, denylist, raw hygiene (2026-10-11 09:xx PT)
- `common/xwalk.py`: `SUCCESSORS.lookup(cc, name=, code=, qid=)` reads codes/place_successors.csv. A dissolved name or code maps to its single successor (`mapped_via=successor`; former_name/former_code/dissolved_date are kept, along with the original issuer). Splits with more than one successor return `ambiguous` and stay unmatched. `DENY` / `denied()` lists Piringen, Amelscheid, Sint-Lambrechts-Herk, Mündi and École Vervloesem, which are never mapped.
- `ee_rt.py`: candidate (denylist applied) → current towns from place_additions.csv → successor. `be_lokaalbeslist.py`: candidate (+ieper→Ypres, denylist) → successor; also falls back to the gelinkt-notuleren path and to 3-token hosts.
- `common/live.py`: `Stager.graceful(done)` (used by ee_rt and be_lokaalbeslist). On SIGTERM the next add() flushes the buffer and the done-marks, then exits. Resume with the same command.
- `tools/remap_unmatched.py` now also covers EE and BE, and writes mid-group when more than 64 MB is buffered.
- `tools/raw_hygiene.py [--apply]` deletes `_raw/cvdr` and `_raw/es_boe_ac` files only for docs in HF-confirmed batches (state/confirmed_batches/eu.jsonl). Each batch's doc set is verified against the uploader's doc_ids_sha256. Unverified docs, and docs in unconfirmed files, are kept. It's safe to re-run.

## Flanders harvester health breaker (2026-10-11 17:xx PT)
- Root cause of the 09:05–17:00 PT stall: harvesters h1 and h2 (`lokaalbeslist-harvester-{1,2}.s.redhost.be`) time out server-side, even on a trivial `ASK {?s ?p ?o}` and on their JSON:API `/datasets`, with our process stopped. h0 and h3 answer in under 1 s. The old code sent 25-URI VALUES POSTs (600 s timeout, 6 retries) and never skipped a dead harvester.
- Fix: `VALUES_BATCH=10`, `POST_READ_TIMEOUT=180`, `POST_TRIES=3`, backoff `min(30*2^a, 600)` s. Before each harvester there is a 60 s ASK probe. On a probe failure, or 2 consecutive batch failures, that harvester is parked for 1→3→6→12 h (`_state/be_lb/harvester_health.json`) and a `temporarily_down` row goes to `_logs/blocked_sources.jsonl`. When every remaining harvester is parked, the process sleeps until the earliest wake.
- Sanctioned bulk alternative: delta-producer dump `BesluitenCacheGraphDump` (`/datasets?filter[subject]=…&filter[:has-no:next-version]=yes`, then `/datasets/<id>/distributions`). It is reachable only on the healthy harvesters (h3 ≈ 1.27 GB gz). h1/h2 dumps are unreachable too, so SPARQL is kept.
- Resume command unchanged (see above). Check: `grep -E "flush|parked" ../../../staging/eu/_logs/be_lokaalbeslist.log | tail`.

## `pt_dre.py` — Portugal Diário da República, 2.ª série Parte H (autarquias locais), source tag `ptdre`
- Static official sources only: whole-issue PDFs `https://files.diariodarepublica.pt/gratuitos/2s/<YYYY>/<MM>/2S<NNN>A0000S<SS>.pdf` (`S00` = main issue, `S01`+ = supplements; a missing file is a 301 to `/dr/error`), plus the RSS `rss/serie2&parte=h-html.xml` (latest day only). The JS app and its internal API are not used. No robots.txt exists (it redirects to the app's error page, so nothing is disallowed). Access is free with no login. Pacing: 2 s between requests, with a HEAD probe before each download.
- Coverage: whole-issue 2.ª série PDFs exist back to at least 1980. Parte H (autarquias) starts in 2007; before that, municipal acts sit in appendices (apêndices), which this scraper does not parse. Scope is 2007 → present, newest year first.
- Parsing: `pdftotext -layout`; acts are split at the closing 9-digit DR id. The issuer is the MUNICÍPIO/FREGUESIA heading; the title is the last "Tipo n.º X/AAAA" line before "Sumário:" (modern layout) or the first after the heading (old layout). Running headers and footers are stripped. Only local-authority regulatory acts are kept (Regulamento/Postura, or regulation/consultation/ARU/PDM keywords minus HR/procurement/disciplinary). `doc_id=pt_dre:<DR id>`, `content_format=pdf_text`.
- Crosswalk: concelhos via `data/wd_pt_municipios.csv` (Wikidata + DICO, P6324). Same-name concelhos (Lagoa, Calheta) are resolved by the "(Açores)/(Madeira)/(Algarve)" qualifier and the DICO prefix. Freguesias via `data/wd_pt_freguesias.csv` (DICOFRE) go to `_unmatched/` with `freguesia_qid`, `dicofre` and `parent_place_id`, because freguesias are not in the candidate list.
- State: `_state/pt/progress.json` (per year: next issue `n`, month `m`, misses, complete) plus done marks `issue:YYYY/NNN/SS`. Restarts are safe: SIGTERM flushes gracefully. PDFs go to `_state/pt/tmp` and are deleted after parsing. Peak RSS is about 50–60 MB.
- Test: `python3 pt_dre.py test 2026/10/196` (prints parsed acts, writes nothing). Status: `python3 pt_dre.py status`.
- Resume:
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u pt_dre.py all >> /workspace/world_law/staging/eu/_logs/pt_dre.nohup.out 2>&1 < /dev/null &
```

## 2026-10-12 15:xx PT — CZ, Bornem, Opole 403 breaker, UK/RO council sites, HU
### Czechia (sbirkapp.gov.cz): still network-blocked, so the archive pass runs first
- Re-check 22:00Z: DNS resolves, but the TLS handshake gets reset (curl 35 "unexpected eof") on `/` and `/robots.txt`. On 2026-10-11 it was a TCP connect timeout. Other .gov.cz hosts (data.gov.cz) work, so this is a host-level block of the box's egress. The same pattern hits legislatie.just.ro and njt.hu.
- No official SPP open data: NKOD (data.gov.cz SPARQL) only lists e-Sbírka datasets, which are national law, not SPP. The e-Sbírka REST API needs MV registration via a datová schránka (not used).
- `archive_q2.py czfirst` runs the CZ Wayback pass now. It then resumes `archive_jobs.py all at|pl --no-cc` (stopped gracefully from their checkpoints at 15:01 PT) and waits for them, then runs be. The old `queue` process was stopped.
```
cd /workspace/world_law/pipeline/scrapers/eu && ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup /workspace/world_law/pipeline/venv/bin/python -u archive_q2.py czfirst >> /workspace/world_law/staging/eu/_logs/archive_q2_queue.nohup.out 2>&1 < /dev/null &
```
  If czfirst dies after cz has finished, resume at/pl with the two `archive_jobs.py all at|pl --no-cc` commands above, then run `archive_q2.py all be`.

### Bornem (NIS 12007) and BE name matching
- Root cause: the candidate CSV names Bornem in Cyrillic ("Борнем", wd:Q724025), as it does Zottegem ("Зотегем") and Bouillon ("וילון"). `fold()` turns those names into an empty key. `Places` now also keys non-Latin candidate names by their official-site domain label (bornem.be → bornem).
- The host fallback now tries 1–5 tokens (heist-op-den-berg) and goes through `by_name`, so 2025 merger successors apply (raadpleeg-<x>.onlinesmartcities.be, csecho.be).
- Remap (`tools/remap_unmatched.py --only belb`): 1,424 of 1,576 matched, including 182 Bornem rows (`BE/wd_Q724025.belbremap_*`). 152 rows remain unmatched (oost-vlaanderen province 141, 11 others).

### Poland: per-host 403 breaker (`pl_dzienniki.Host`, used by `pl_run.py`)
- 3 consecutive 401/403 responses park the host for 2 → 4 → 6 → 6 h (`_state/pl/host_health.json`), log `temporarily_blocked_403` to `blocked_sources.jsonl`, and `pl_run` skips parked hosts. A 403 is retried at most once per URL. A 200 clears the record.
- If 403s persist for more than 6 h since `first_403`, it writes `_state/pl/archive_request_<WOJ>.json` as the trigger for an archive pass. OP's `first_403` was seeded at 18:46Z (11:46 PT).

### `council_docs.py` — targeted official council websites (`gb`: byelaws, tag `ukbyelaw`; `ro`: Monitorul Oficial Local / HCL, tag `romol`)
- Per site: robots.txt (RFC 9309) + Crawl-delay, at least 1.5 s per host, https only (port 80 is closed on the box). Sources: the homepage, the site's own sitemap(s) and nav hints. It follows links matching the profile words (depth ≤ 2, ≤ 60 pages, same site) and fetches PDF/DOCX/HTML byelaw or HCL documents. No search forms, logins or third-party portals.
- Places: candidate rows with a `source_url` (GB: principal councils first, then parish/town/community; 2,634 sites. RO: 2,436 primării). Done keys: `site:<place_id>` and `doc:<sha1(url)>`, in `_state/council_<cc>/done.sqlite`.
- Test: `python3 council_docs.py gb test wd:Q774015` (Leeds: 12 byelaw docs). Status: `python3 council_docs.py gb status`.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u council_docs.py gb run --workers 8 >> /workspace/world_law/staging/eu/_logs/council_gb.nohup.out 2>&1 < /dev/null &
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u council_docs.py ro run --workers 6 >> /workspace/world_law/staging/eu/_logs/council_ro.nohup.out 2>&1 < /dev/null &
```
- RO caveats: many HCL PDFs are scanned with no text layer and there is no OCR on the box, so these are marked `no_text` and not staged. Many communes host MOL on third-party portals, which are not followed.

### Hungary: blocked
- njt.hu and or.njt.hu: TLS reset from the box. The archived pages carry metadata only, and NJT reserves all rights. No official open export of helyi rendeletek was found, so nothing is built.

## 2026-10-13 10:00 PT — Wayback breaker (ratelimit v4): defer, don't fail; one EU archive runner
- **Patch (`archive_jobs.py`, `archive_q2.py`):** `AJ.lookup_caps()` does Common Crawl plus Wayback CDX per exact URL. `AJ.fbest()` wraps `fetch_best`. `AJ.ITEM_DEF` counts the Wayback lookups and captures the breaker skipped for the current item. When an item ends as `no_good_capture` (doc None) and `ITEM_DEF`/`fx.last_wb_deferred` is set, or `ArchiveTransient` is raised, it becomes `deferred_wayback`: not written to done.txt or failed.jsonl, audited in `_state/archive/<t>/deferred_wayback.tsv`.
  - CZ: a text found while the metadata page is Wayback-deferred is also deferred, because the publisher is needed for place mapping.
  - Stored Wayback-only candidate captures (at/pl) get CC exact captures of the same URLs added while the breaker is open (`cc_extra`).
  - `--no-cc` is no longer used: CC is on everywhere (`CC_CRAWLS=3`) and is the breaker's fallback. The CC index is flaky, though (502/504), so the fetcher's own CC breaker often skips it.
- **Requeued:** CZ `SPPCBYDSHCEUAV34` was marked done at 08:40 PT without its metadata page (Wayback down, v3 code), so it was removed from done.txt (backup `/tmp/cz_done.txt.bak`; log in `cz/requeued.tsv`). No other items were wrongly marked done or failed during the outage: at/pl/be were not running, and the 3 CZ errors were never marked done.
- **One runner:** `archive_q2.py run`, order `lt, cz, at, pl (KP/LB/WP), be, op`.
  - LT discovery needs a Wayback prefix listing, so it waits for the breaker.
  - Deferred items are skipped while the breaker stays open. All targets re-run from checkpoint once `wayback_available()` is true, plus a CC-only retry every 3 h.
  - It waits up to 30 min between rounds (wakes early on close) and exits when nothing is remaining or deferred. Status: `_state/archive/runner.json`.
  - `czfirst`, `queue` and the old waiter are retired; never run them together with `run`.
```
cd /workspace/world_law/pipeline/scrapers/eu && ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup /workspace/world_law/pipeline/venv/bin/python -u archive_q2.py run >> /workspace/world_law/staging/eu/_logs/archive_runner.nohup.out 2>&1 < /dev/null &
```
  (`--order cz,at` etc. to restrict; SIGTERM flushes and exits at the next item.)
- **Opole archive target (`op`):** `AJ.op_candidates()` rebuilds `_state/archive/pl/candidates_OP.jsonl` before each OP pass, from the live pass-1 queue (`_state/pl/queue_OP.jsonl`) minus live done (`done_OP.txt` plus `pl_done.sqlite`): 1,941 acts at 10:00 PT. Each candidate is the `api/eli/acts/<eli>/text.pdf` URL, with captures looked up per item (CC plus Wayback). `pl_record` is unchanged (`pdf_capture_kind=api/eli/text.pdf`, doc_id = ELI, the same as the live `pldz`). PL prefix discovery stays KP/LB/WP (`PL_DISCOVER`).

## 2026-10-13 11:00 PT — be_lokaalbeslist: wall-clock sleep, 2 h cap; archive path checked
- PID 1912472 had parked at 20:24 PT with a 12 h `time.sleep`. The box suspended, and `time.sleep` doesn't count suspended time, so it overslept its 08:24 PT wake by 2.5 h or more. It ignored SIGTERM while sleeping (old code), so I killed it with KILL; nothing was buffered.
- Patch: `DOWN_STEPS_H=[1,2]` with `MAX_PARK_S=2h`. Old parks over 2 h in `harvester_health.json` are clamped on load. `wall_sleep()` sleeps in chunks of 60 s or less against a wall-clock deadline, logs `heartbeat: sleeping (...)` every 30 min, and exits cleanly on SIGTERM. Resume command unchanged.
- Hand probe at 10:55 PT (`ASK {?s ?p ?o}`, 60 s): h0 200 in 0.72 s, h1 timeout at 60 s, h2 timeout at 60 s, h3 200 in 0.56 s. h0 and h3 are already fully harvested. 86,365 h1/h2 decisions are pending.
- Archive path (Common Crawl via the shared ArchiveFetcher; Wayback is down, breaker open): 14 CC index calls succeeded and returned 0 captures. Exact besluit URIs (data.gent.be, lblod.waregem.be, lblod.stekene.be): 0 of 3; an earlier 8-URI try was skipped by CC backoff. Host prefixes `lblod.stekene.be/` and `data.antwerpen.be/` over 3 crawls: 0. Coverage is useless, so no `be_lb` archive target was added.

## 2026-10-14 04:xx PT — `council_docs.py ro run --list-notext` (URL list of no_text docs for the OCR bot)
- What it does: re-runs the same per-site discovery as before (rfc9309 robots, same UA, ≥1.5 s per host) but never downloads documents.
  - Each discovered doc URL's key `doc:<sha1(url)[:20]>` is checked against done.sqlite rows with why='no_text' (opened read-only).
  - Output: `_state/council_ro/notext_urls.jsonl` (append-only; `{place_id, place_name, source_url, title, doc_key, site}`; each key at most once). Done sites go to `_state/council_ro/notext_sites.txt`.
  - Sites whose previous pass logged `docs=0` or `home_failed` (in `_logs/council_ro.log`) are skipped: 1,594 of 2,435. That leaves 841 sites.
- It never writes done.sqlite or staged RO files. Run with 4 workers: 6 workers peaked at about 430 MB RSS (large sitemaps). The final log line reports `listed N of M no_text keys; unmatched K`.
```
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u council_docs.py ro run --list-notext --workers 4 >> /workspace/world_law/staging/eu/_logs/council_ro_notext.nohup.out 2>&1 < /dev/null &
```

## 2026-10-17 status: PL pass 1 finished
- `pl_run.py` exited on its own at 09:30 PT on 2026-10-17 (all 13 reachable host queues exhausted). Done 798,622 of 805,599 pass-1 acts; the ~7k not done are mostly scanned PDFs without a text layer (plus some timeouts), listed in `_state/pl/failed_<XX>.jsonl` for a later OCR pass. 24,633 PL docs are in `_unmatched/` (15,917 powiat, 8,716 gmina, mostly ambiguous same-name gminas); a remap dry-run matched none. Do not restart `pl_run.py`. KP/LB/WP stay with the archive runner.

## 2026-10-17 15:xx PT — PL rematch, failed-row backfill, NL gemeenteblad, GR Diavgeia

### PL unmatched rematch (`tools/remap_unmatched.py` + `pl_dzienniki.PlaceMap.resolve_ext`)
- 15,222 of the 24,633 PL unmatched powiat docs were already remapped on 2026-10-11 (`pldzremap`, 277 batches, 15,210 rows confirmed on the Hub) and are in `_state/remap_done.txt`; they are skipped.
- `codes/proposed/PL_powiaty.csv` (built by `tools/build_pl_powiaty.py` from the cached GUS BDL level-5 list, `codes/place_additions.csv` and `data/wd_pl_teryt.csv`): 380 current powiats (314 land + 66 city) + 2 historical, all with a place_id. A city county maps to the city gmina candidate (the rada miasta acts as the rada powiatu). `PlaceMap.cand_for_teryt()` now uses it for 4-digit TERYT.
- `codes/proposed/PL_gmina_fill.csv`: gminas missing from `wd_pl_teryt.csv`/the candidate CSV (Żory, Rumia, Stargard, the rural gmina Zielona Góra → city successor, plus Wąbrzeźno town, Branice, Marianowo and Ostrowice without a candidate).
- `resolve_ext()` order: plain `resolve()` → organ fixes (Białegostoku, Dobrym Mieście, Ujeździe, Głogów Młp., n. Odrą, Uzdrowiskowej, Rumi) → ambiguous same-name gminas by (1) the longest full name, (2) the gmina type from the organ (Rada Gminy/Wójt → rural; Rada Miejska/Miasta/Burmistrz → urban or urban-rural), (3) a "(pow. X)" qualifier or a "powiat X" mention in the title or text, (4) villages from pl.wikipedia (`tools/pl_gmina_villages.py`, cache `_state/pl/wiki_villages.json`, 15 page fetches; at least 2 exclusive village hits, every same-name gmina must have a list, common nouns dropped), (5) the signer (≥3 cue-resolved docs, ≥90 % agreement, same candidate set). Unresolved gminas use nominative names from the title or text. Unresolved powiats use the seat → gmina → powiat, then a fuzzy adjective.
- Applied 2026-10-17 14:52 PT: 7,207 of 9,411 matched (695 powiat, 6,512 gmina), 126 files `PL/<pk>.pldz{,arch}remap_<UTC>p<NNNN>.jsonl`, all validated, ids appended to `_state/remap_done.txt`. Log: `_logs/remap_pl_20261017.log`. Rerun (idempotent): `python3 tools/remap_unmatched.py --only pl_DS,pl_LD,pl_LS,pl_MP,pl_MZ,pl_OP,pl_PK,pl_PL,pl_PM,pl_SK,pl_SL,pl_WM,pl_ZP,pl_archive [--dry-run]`.

### PL failed rows → OCR hand-off (`tools/pl_failed_backfill.py`, offline, no PDF downloads)
- Rewrites `_state/pl/failed_<XX>.jsonl` atomically; the original is kept as `.jsonl.pre_backfill`. Each row gets act_id, host, pdf_url/source_url (`https://<host>/api/eli/acts/<eli>/text.pdf`), html_url, title, type, date, issuer, level, place_id/place_match, reason, reason_class and now_done.
- `_state/pl/ocr_queue_pl.jsonl` has one row per act that is still not done; the summary is in `ocr_queue_pl.summary.json`. Rerun: `python3 tools/pl_failed_backfill.py`.

### `nl_gmb.py` — Netherlands Gemeenteblad (regulatory types only), source tag `nlgmb`
- Discovery uses KOOP SRU `https://repository.overheid.nl/sru`. Its robots.txt is `Disallow: /`; we use it on the same documented-reuse basis as the CVDR SRU, about 1 request per 1,000 records, and fetch nothing else from that host. Full text comes from `https://zoek.officielebekendmakingen.nl/<gmb-id>.xml` (robots allows it), 1 req/s.
- Types: AVV (verordening), Verordeningen, beleidsregel(s), delegatie-/mandaatbesluit, gemeenschappelijke regeling. That is 2013 to today, about 173.5k publications. Pass 2 (not started) is "(ander/overige) besluit van algemene strekking" (about 187k). Places come from `cvdr.PlaceMap` (creator + scheme).
- State is in `_state/nl_gmb/` (`catalog.jsonl`, `catalog.state.json` per month, `done.sqlite`, `failed.jsonl`). The test batch of 15 went to `_test_nl/`.
- Resume (SIGTERM-safe): `cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u nl_gmb.py all >> /workspace/world_law/staging/eu/_logs/nl_gmb.nohup.out 2>&1 < /dev/null &`

### `gr_diavgeia.py` — Greece, Diavgeia OpenData API, municipal regulatory decisions, source tag `grdiav`
- Uses `/opendata/organizations?category=MUNICIPALITY` (336), `/opendata/search?subject={κανονισμ,κανονιστικ}` in half-year windows from 2010-10 (the server caps a window at about 6 months), and `/opendata/decisions/<ADA>/document` (PDF → pdftotext). robots.txt only disallows `/decision/view`, `/doc/*`, `/luminapi/api/decisions/*` and `/f/all/ada/*`, none of which are fetched.
- Kept: municipal orgs, types Α.2 and 2.4.7.1, minus the NOISE regex. Places: `common/gr_names.py` (Greek genitive label → transliteration → English candidate names, one org per place) matches 312 of 336 orgs. The rest go to `_unmatched` with the Diavgeia org uid and label.
- PDFs without a text layer go to `_state/gr/failed.jsonl` (reason no_text_layer, with pdf_url) for OCR.
- Resume: `cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u gr_diavgeia.py all >> /workspace/world_law/staging/eu/_logs/gr_diavgeia.nohup.out 2>&1 < /dev/null &`

### Ops
- `_logs/archive_runner.nohup.out` had reached 2.3 GB (Common Crawl index retry spam printed by the shared archive module). On 2026-10-17 at 14:54 PT the last 30 MB were saved to `archive_runner.nohup.tail_20261017.gz`, then the file was truncated in place (the runner writes it O_APPEND, so this is safe). It grows about 150 MB/h while the CC index is failing, so truncate it again the same way if needed.

## 2026-10-17 15:4x PT — GR code-first place mapping, PL reviewed gmina fill
- `common/gr_names.assign(gp, orgs, codes, extra_rows)`: an org whose Diavgeia uid is in `codes/place_codes.csv`
  (`gr_diavgeia_org`, 25 orgs incl. former Corfu/Kefalonia/Lesbos/Samos) gets that place, whatever any fuzzy score says;
  name matching runs only for orgs without a code and never against a code-owned place (fixes Chaidari 6313 -> Hydra
  0.97; Chaidari = wd:Q25161986, Hydra 6303 = wd:Q16642582). Now 336/336 orgs mapped (25 code, 311 name). Code-mapped
  rows carry `place_match=diavgeia_org->code(gr_diavgeia_org)->place`.
- `gr_diavgeia.py fetch` also honours SIGTERM between docs when consecutive docs fail (before, only `add()` checked it,
  so a run of failing docs ignored SIGTERM). Old ADA documents redirect to `http://static.old.diavgeia.gov.gr/doc/…`
  (port 80, unreachable from the box; https also times out): each such doc costs ~4 min of retries and lands in
  `_state/gr/failed.jsonl` (not done, retried next run).
- `tools/remap_unmatched.py` has a GR rule (`--only grdiav`, same assign()). 
- `pl_dzienniki.PlaceMap.fill_row` reads `codes/proposed/PL_gmina_fill_reviewed.csv`: accepted rows map (Branice, Marianowo,
  Wąbrzeźno town, Ostrowice = former place, Stargard); rejected rows resolve through `REJECT_FIX` (Żory -> wd:Q393171 via
  2479011, Rumia -> 2215021, rural Zielona Góra 0809102 -> successor wd:Q104720 with former_code). `tools/restage_fill_rejects.py`
  re-placed the docs that had used rejected rows (writes `.full` only when the batch is the place's complete set).

### PL issue-PDF re-fetch for ELI-406 acts (`tools/pl_issue_refetch.py`, source tag `pldziss`) — 2026-10-17
Pre-~2012 (and some later) e-Dziennik acts have no per-act PDF behind the ELI API (`/api/eli/acts/<ELI>/text.pdf` -> HTTP 406,
`text.html` -> 404). The PDF is the whole journal issue: `https://<host>/GetActPdf.ashx?year=<Y>&book=<volume>&position=<pos>`.
The job fetches each issue once (polite PoliteSession, robots), splits act segments by "Poz." headers, stages text acts,
marks scanned/garbled/missing in `_state/pl/issue_refetch_done.sqlite` (resumable). Place mapping = pl_dzienniki.PlaceMap
(TERYT via place_codes crosswalk + PL_gmina_fill_reviewed.csv).
  cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u tools/pl_issue_refetch.py \
      >> /workspace/world_law/staging/eu/_logs/pl_issue_refetch.nohup.out 2>&1 &      # resume = same command
  python3 tools/pl_issue_refetch.py --retry-why split_failed     # re-try one done reason
  python3 tools/pl_ocr_queue_fix.py                               # then rewrite _state/pl/ocr_queue_pl.jsonl (atomic, pdf_url_old kept)
  python3 tools/restage_fill_rejects.py --dry-run && python3 tools/restage_fill_rejects.py

## 2026-10-18 CEE (SK / CZ / AT live council sites + archive pass `cee`; HU; RS skipped)
- Probes (01:00 PT): slov-lex.sk reachable, robots `Disallow:` (empty) — but it holds national law/opatrenia only; VZN of
  obce are NOT on Slov-Lex yet (MS SR + MV SR announced the extension Aug 2025). njt.hu / or.njt.hu, sbirkapp.gov.cz,
  e-sbirka.cz, www.ris.bka.gv.at: TLS reset from the box (curl 35/56) = network_blocked; archive only.
- `council_docs.py` new profiles (own municipal sites, live, RFC 9309 robots + Crawl-delay, >= 1.5 s/host, https):
  `sk` VZN (tag `skvzn`), `cz` obecně závazné vyhlášky / nařízení obce (`czozv`), `at` Verordnungen (`atgvo`).
  Listing pages only count when URL/<title>/<h1> name the act type; PDFs found there without an act cue in link, URL or
  first 3,000 chars are `not_act` (not staged). Charset from <meta> when the header has none. Unusable sites
  (TLS reset / name mismatch / robots disallow) are `site_home_failed` -> archive target `cee`.
```
cd /workspace/world_law/pipeline/scrapers/eu && L=/workspace/world_law/staging/eu/_logs && MALLOC_ARENA_MAX=2 setsid nohup bash -c "python3 -u council_docs.py sk run --workers 10 >> $L/council_sk.nohup.out 2>&1; python3 -u council_docs.py at run --workers 8 >> $L/council_at.nohup.out 2>&1" > /dev/null 2>&1 < /dev/null &
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 setsid nohup python3 -u council_docs.py cz run --workers 12 >> /workspace/world_law/staging/eu/_logs/council_cz.nohup.out 2>&1 < /dev/null &
python3 council_docs.py sk status      # resume = same commands (done.sqlite per profile; SIGTERM flushes)
```
- `tools/restage_cee_titles.py`: fixed titles of the first sk/cz run (latin-1 mojibake, "Stiahnuť" link text) as
  `<pk>.skvznfix_/czozvfix_<UTC>` batches; non-act rows listed in `_state/council_<sk|cz>/not_act_staged.jsonl` (Normalizer: drop by doc_id).
- `cee_archive.py` = target `cee` of `archive_q2.py run` (last in RUN_ORDER): per blocked site one Wayback CDX prefix
  listing with an act-type URL regex, PDFs/DOCX only, <= 80 docs/site, ArchiveFetcher (ARCHIVE_LANE=eu). Live robots
  disallow -> `source_policy=archived_robots_disallowed`; network-blocked -> newest archived robots.txt honoured
  (`extra_metadata.archive.live_access`). Candidates rebuilt each pass from council_<cc>/done.sqlite + logs; stays
  pending while the live runs are alive. `python3 cee_archive.py build|test N|status`.
- RS: skipped (Western Balkans incl. RS assigned to World Law Scraper Africa & Middle East).

## 2026-10-18 02:02 PT — GR Diavgeia finished (watchdog note)
- `gr_diavgeia.py all` exited on its own: fetch finished, done 31,293 of 31,854 catalog rows; 31,178 matched/staged, 29 skipped, 336/336 orgs mapped, 3 unmatched rows (1 `_unmatched` file).
- 198 docs deferred in `_state/gr/deferred_oldhost.jsonl` (old ADA docs redirect to `static.old.diavgeia.gov.gr`, unreachable from the box); 32 no_text_layer PDFs in `_state/gr/failed.jsonl` for OCR. Don't restart; a rerun would only retry the unreachable host.

## 2026-10-18 03:xx PT — CEE pass 2 (SK / HU / CZ / AT); notes in `staging/eu/_state/cee_notes.md`
- **SK**: still no central VZN source. Slov-Lex holds no obec VZN (the MS SR/MV SR extension announced in Aug 2025 isn't live).
  e-obce.sk (robots `Allow: /`) is a directory, and its per-obec `docs.html` pages are empty. vzn.sk is a parked domain. So SK = live
  `council_docs.py sk` on the municipalities' own sites, plus the `cee` archive target for the sites it can't reach.
- **Runner queue file**: `archive_q2.py run` now re-reads `_state/archive/runner_queue.txt` every round (one target per
  line, must be in RUN_ORDER), so new targets no longer need a restart. One graceful restart was done to load this code and `cee`:
  `tools/runner_restart.sh <old pid>` sends SIGTERM, waits up to 45 min for the exit, refuses to start if any archive_q2 runner is
  still alive, and then starts exactly one `archive_q2.py run`. Log: `_logs/runner_restart.log`.
  RUN_ORDER = `lt, cz, at, pl, be, op, cee`.
- **HU (`hu_njt.py`, target `hu`, tag `hunjt`)**: BUILT but NOT QUEUED. It is not in RUN_ORDER or runner_queue.txt, pending
  Benjamin's decision on NJT's "minden jogot fenntart" footer. Archived `or.njt.hu/eli/v01/<issuer>/r/<yyyy>/<no>` pages DO carry
  the full consolidated text (verified on 735782/r/2023/5 @ 2025-08-07: 27 §§, ~17k chars). Discovery is a paged Wayback CDX
  (`pageSize=1`, resumable per page in `_state/archive/hu/cdx_pages/`). Places: issuer heading → toponym → unique HU candidate.
  Budapest districts, minority self-governments, and ambiguous names go to `_unmatched`.
  Test only: `archive_q2.py discover hu --limit 3 && archive_q2.py fetch hu --test 8` → `staging/eu/_test_hu/`.
- **Live council RSS guard**: `tools/council_rss_guard.sh` checks every 60 s. When a `council_docs.py sk|cz|at run` goes over 460 MB
  it sends SIGTERM (Stager.graceful flushes) and relaunches the same command. sk keeps its sk→at chain.
  Log: `_logs/council_rss_guard.log`.
- **AT**: `at` candidates cover 86 GKZ (KA 79, NI 2, ST 2, OB/SA/WI 1). Per-Land Wayback prefixes `GEMRE_<L>_` found:
  ST 207 docs / 2 GKZ (already covered), TI 0, VO 0. No new archive targets were added. The 2,057 uncovered AT places are
  left to the live `council_docs.py at` run (own websites).

### 2026-10-18 box move (~10:40–11:03 PT)
- The box was moved to a fresh instance around 10:40 PT; every process died and files were restored by ~11:03 PT. `pipeline/venv` did not survive, so it was recreated with `python3 -m venv --system-site-packages venv` (system python already has requests, bs4, lxml; pdftotext is present). `hf-venv` is also gone (uploader's lane, not touched here).
- Finished before the move: `council_docs.py cz` at 10:11 PT (6,058 sites, 30,459 items done, 8,660 matched docs staged, 18,881 skipped) and `council_docs.py sk` at 10:36 PT (2,706 sites, 28,753 done, 17,166 matched, 8,680 skipped). Don't restart either.
- Restarted 11:11 PT with the resume commands above: nl_gmb (PID 28059), ONE `archive_q2.py run` (PID 28060), `council_docs.py at run --workers 8` (PID 28061, standalone since sk is done), council RSS guard (PID 28062). All done.sqlite files passed `pragma quick_check`.

## 2026-10-18 11:30 PT — EU Wayback policy (coordinator: stop tripping the box-wide breaker)
- **Cause (audit `pipeline/archive/_ratelimit/wayback.log`):** after the box move the single runner (PID 28060, the only EU
  Wayback client, 1 thread) opened the box-wide breaker at 11:14 PT. The shared `ArchiveFetcher._get` retried the SAME CDX URL
  after a 429 (10 s, then 23 s); 3 consecutive 429s = breaker open for every lane. No Retry-After came with those 429s.
- **`common/eu_wayback.py` → `EUArchiveFetcher`** (subclass of the shared `ArchiveFetcher`; `AJ.new_fx()` everywhere: archive_jobs
  at/pl/op, archive_q2 lt/cz/be/hu, cee_archive, hu_njt CLI). Every Wayback call (CDX, id_ snapshots, hu_njt raw CDX pages, archived
  robots.txt) still goes through `ratelimit.slot("wayback")` with lane `eu`. EU-only additions, other lanes unchanged:
  - ONE EU Wayback request in flight across all EU processes (flock `_state/archive/eu_wayback.lock`, SIGTERM-aware);
  - exactly 1 attempt inside the shared slot; NO retry after 429/5xx (item → `deferred_wayback`, retried on a later pass); at most
    1 retry after a timeout/network error;
  - Retry-After honoured exactly, delta-seconds AND HTTP-date, on 429/503/5xx: no EU Wayback request before it expires. The shared
    ratelimit parses digits only, applies ±15 % jitter (can wait less than asked) and caps at 180 s; that is NOT changed
    (box-wide code). No Retry-After → EU cool-down 60 s doubling per consecutive EU hard failure, cap 900 s;
  - EU min interval 5 s between Wayback requests (`EU_WB_MIN_INTERVAL`) on top of the shared spacing. State/audit:
    `_state/archive/eu_wayback_gate.json` (also in `runner.json` as `eu_wayback_gate`, with `wayback_workers: 1`).
- **One runner, one thread:** `archive_q2.py run` takes `_state/archive/runner.lock` (flock) and refuses to start a second one;
  all targets (lt, cz, at, pl, be, op, cee) run sequentially in that one thread. `tools/runner_restart.sh` now logs the real
  python PID (the 03:22 / 11:30 entries logged the `cd && …` subshell, PID − 3).
- **cee = Common Crawl first:** when the CC index is up (shared limiter: < 3 consecutive cc_index failures, backoff ≤ 30 s), one
  CC prefix listing per site (newest `CC_CRAWLS`=3 crawls, ≤ `CEE_CC_MAX_PAGES`=10 index pages each, act-type regex applied
  locally). Wayback CDX prefix listing only as fallback (CC down / a crawl query failed / CC found no act document). A CC capture
  that yields no PDF/DOCX falls back to the newest 3 Wayback captures of that exact URL. Per-site log shows `src=cc|wayback(...)`.
- **`council_docs.py` (at, and every profile)** never used Wayback (no archive imports; no archive.org URL in any council log).
  Now enforced: archive.org URLs, and redirects to them (page and robots.txt sessions), are refused with
  `ArchiveHostRefused` (a PermissionError, handled like a robots disallow). Archived copies come only from target `cee`.
- gr_diavgeia / nl_gmb / other live scrapers: no Wayback use (checked).
- Restart 11:30 PT: runner 28060 → **72839** (via `tools/runner_restart.sh`), `council_docs.py at` 28061 → **73084**
  (SIGTERM flushed 14 docs; relaunched with the resume command above). nl_gmb 28059 and guard 28062 unchanged.
- Backups: `staging/eu/_state/archive/bak_20261018_wbeu/`.

## 2026-10-18 12:0x PT — shared ArchiveDeferred adopted; EU wrapper simplified
- The Normalizer's shared fetcher (`pipeline/archive/core.py` + `deferral.py`, live ~12:00 PT) now does what the 11:30 EU wrapper
  did: no in-process retry on 429/5xx → `archive.ArchiveDeferred` (subclass of `ArchiveTransient`, `.not_before`), box-wide
  per-host cool-down (Retry-After seconds/date, else 60 s doubling to 900 s; calls during it raise at once), ≥ 5 s lane spacing,
  deferrals not counted by the breaker. So `common/eu_wayback.py` no longer has its own cool-down, Retry-After parser, 5 s
  interval or gate file. Those would have doubled the shared cool-down. `_state/archive/eu_wayback_gate.json` is a stale leftover (kept, not deleted).
- Kept, EU-only: the `eu_wayback.lock` flock (ONE EU Wayback request in flight across all EU processes) and ONE attempt per Wayback
  call (`max_retries=1`; the shared code still retries timeouts). `EUArchiveFetcher.wb_paused()` = max(last
  `ArchiveDeferred.not_before` seen, shared cool-down of web.archive.org). The shared fetcher's own `fetch_best`, `fetch_newest`
  and `cc_captures` swallow ArchiveError, so the loops check this after each item instead of relying on the exception.
- Item loops (`archive_jobs.fetch` at/pl/op, `archive_q2.fetch` lt/cz/be/hu, `cee_archive.fetch`): on a Wayback deferral the item
  is deferred (not done, not failed). Buffers are flushed, and the target returns `paused_until`. The remaining items stay
  pending. The runner skips that target until `paused_until`, and skips every target while the shared web.archive.org
  cool-down lasts. It continues with the other targets, and when nothing is due it idles (no requests) until a target is due or
  the breaker closes. No sleep-retry loops.
- `AJ.robots_for`: an ArchiveTransient/Deferred (or `fetch_newest` → None with `last_wb_deferred`) now raises instead of caching
  "no archived robots.txt" (which would have skipped a disallow). cee defers that site; hu defers the pass.
- cee `_doc`: a CC capture that failed transiently while Wayback is cooling down → site deferred, not marked `no_good_capture`.
- Offline test (no network, all state in /tmp): `python _state/archive/tests/test_defer_20261018.py` (from staging/eu) → 15/15 PASS.
- Backups: `staging/eu/_state/archive/bak_20261018_defer/`.

## 2026-10-18 12:17 PT — shared ArchiveFetcher v3 (raised deferrals, flagged listings)
- `fetch_best`/`fetch_newest` raise `ArchiveDeferred` when throttled; `None` = genuine miss. `AJ.fbest()` lets it propagate and
  also raises the item's own lookup deferrals (`Looked.deferrals`: truncated CC `CaptureList` / deferred Wayback CDX) instead of a false miss.
- Item loops (q2 fetch, AJ fetch, cee): `AJ.defer_info(e)` -> (not_before, involves_wayback). Every deferred item gets
  `deferred_nb[key] = not_before`; the runner skips it until then (no sleep-retry). Only a Wayback deferral pauses the whole target
  (`paused_until`); CC-only deferrals requeue just the item. The post-item `fx.wb_paused()` check is gone.
- Listings: at/pl discovery raise on `cc.truncated` (nothing written). cee `list_docs`: the CC listing counts only if complete
  (no deferral/failed crawl/page cap > CEE_CC_MAX_PAGES); otherwise the Wayback listing is merged in; a deferred Wayback listing defers the site.
  hu discover.json has `"complete"` (pages_done == pages_total). lt/cz/be discovery use `wb_captures` (raises; no partial file).
- `_doc` (cee): CC data deferral -> Wayback copy of the same URL; none -> CC deferral re-raised.
- Offline test: `_state/archive/tests/test_defer_v3_20261018.py` (30 checks; supersedes test_defer_20261018.py, which targets the v2 shim).
- Backups: `_state/archive/bak_20261018_defer2/`. Resume: `setsid nohup bash tools/runner_restart.sh <oldpid>`.
- Restarted 12:17:53 PT: runner PID 143859 (old 116545 exited on SIGTERM).

## 2026-10-18 13:38 PT — `council_docs.py at` FINISHED
- Exited on its own 13:38:23 PT after site 1932/1932: run total `{'matched': 1398, 'skipped': 3643}` (6,405 keys in
  `_state/council_at/done.sqlite`). No `_unmatched` rows (sites come from candidate rows). Don't restart.
- Council RSS guard exited by itself at 14:07 PT (no council runs for 30 min), as designed. Not needed any more.
- Still live (watchdog 14:47 PT): nl_gmb 28059 (done 69,436), ONE archive runner 143859 (breaker closed, lt fetch 816/30,393 done).

## 2026-10-18 ~14:5x PT — shared fetcher round 3 ("Completeness signals")
- `AJ.fbest` uses `fetch_best_ex` (strict kwargs) and per-call `FetchInfo`; `robots_for` uses `fetch_newest_ex(raise_deferred=True)`.
  No `fx.last_*` reads remain. None = every source answered and the item's own lookups were complete; otherwise one merged
  ArchiveDeferred (timeout / busy / breaker_open / throttle) is raised and the item is requeued for not_before (as for throttles).
- Docs with `doc.incomplete` (another source failed) are ACCEPTED (a fuller copy needs a full re-lookup; not cheap here); counted
  in `AJ.INCOMPLETE` -> runner.json `accepted_incomplete_docs` by reason.
- Low-level calls (wb_captures, cee `_cc_query`, hu `_cdx` raw `_get`) raise raw typed errors; `AJ.as_deferral` normalises them
  with the shared `_as_deferral` (permanent 400/403/404/410 -> None = final gap). Discovery listings use `AJ._wb_list`.
  cee `_cc_list` runs inside `fx._call_scope()` (one breaker failure per family per site listing).
- Listings: retryable gap = `.deferral` set -> requeue/raise; permanent-only gaps (`complete_except_permanent`) are final and logged.
- `unknown_error` deferrals (no module cap): after `EU_UNKNOWN_ERROR_CAP` (6) per key (`<target>/unknown_defer.json`) the item is
  done-with-gaps (`failed*.jsonl` why=unknown_error_cap). Timeouts/breaker/throttle are never capped.
- Offline test: `_state/archive/tests/test_defer_r3_20261018.py` (28 checks). Backups: `_state/archive/bak_20261018_defer3/`.
- Restarted 14:54:25 PT for round 3: runner PID 275561 (old 143859 exited on SIGTERM; see `_logs/runner_restart.log`).
- Watchdog 16:46 PT: nl_gmb 28059 (done 75,992), ONE archive runner 275561 (breaker closed, opens 50; lt 848/30,361 with CC cooldown deferrals). Disk 73G free. Newest 40 staged files valid (57 rows, 0 bad); 0 new unmatched since 14:47.
