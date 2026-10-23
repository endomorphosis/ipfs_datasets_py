# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
# ukie lane — UK + Ireland local law (byelaws, PSPOs, local acts, local SIs, IE bye-laws)

Bot/lane name `ukie` (staging dir `staging/ukie/`, archive limiter lane `ukie`). Interpreter:
`/workspace/world_law/pipeline/venv/bin/python`. Never uploads; run_loop.py picks up `staging/ukie/<CC>/*.jsonl`.

| file | what |
|---|---|
| `common/util.py` | PoliteSession (RFC 9309 robots + Crawl-delay, >= 2 s/host, no retry on 401/403/429/WAF page), `State` (sqlite), `guard()` (disk >= 35 GB free, RSS < 900 MB) |
| `common/rfc9309.py` | copy of `scrapers/eu/common/rfc9309.py` |
| `places.py` | GB/IE places from the candidate CSV -> state db; phases: 1 GB principal councils (446), 2 GB parish/town/community (11,633), 3 IE local authorities (32 rows = 31 LAs + duplicate Dublin). `codes` -> `_state/place_codes_gaps.csv` |
| `wd_codes.py` | one SPARQL query -> `_state/proposed_place_codes.csv` (ONS GSS, P836) + `_state/places_without_official_code.csv` (for the Normalizer) |
| `councils.py` | council sites: byelaws + PSPOs, live first, archive (shared `pipeline/archive`, Wayback/CC) when robots/403/WAF blocks; image-only PDFs -> `_state/needs_ocr/notext_urls.jsonl` |
| `legislation_uk.py` | legislation.gov.uk: `ukla` local acts (Atom feed + CLML via ipfs_datasets_py `collect_legislation_gov_uk.parse_clml`), `lsi` local SIs by title query; Crawl-delay 5 |

## doc_id (never change)
* council docs: `ukbyelaw:<sha1(url)[:20]>` (same as `scrapers/eu/council_docs.py`, so URLs the EU lane already published
  merge), `ukpspo:<sha1(url)[:20]>`; HTML pages hash `"html:"+url`. Prefix comes from URL+link text only;
  `local_instrument_kind` (byelaw|pspo) is from the content.
* `uk_ukla:<year>/<n>` (same as `scrapers/eu/uk_ukla.py`), `uk_uksi:<y>/<n>`, `uk_ssi:`, `uk_wsi:`.

## Batches
`<pk>.ukie-live<UTC>pNNNN`, `<pk>.ukie-archive<UTC>pNNNN`, `<pk>.ukie-leg<UTC>pNNNN`; `--full` re-crawls write
`<pk>.full.ukie-<UTC>p0001` (ONE file; replaces every doc of the place — only for places whose docs all come from
councils.py). `--refresh` re-stages same doc_ids in a normal batch (metadata fixes).

## State (`staging/ukie/_state/`, resumable; re-running a command skips done places/items)
* `ukie_state.sqlite`: `places(place_id, cc, phase, status todo|done|partial|blocked|error, mode live|archive, docs, ocr,
  note JSON)`, `docs(place_id, doc_id, url, status staged|needs_ocr|skipped:*|deferred:*)`, `items(key, source, status)`.
* `progress.json` (summary per phase), `unmatched_legislation.jsonl`, `needs_ocr/notext_urls.jsonl`,
  `proposed_doc_overrides_*.json` (for the Normalizer), `test_batch_places.txt`.

## Commands
```
cd /workspace/world_law/pipeline/scrapers/ukie; PY=/workspace/world_law/pipeline/venv/bin/python
$PY places.py init
ARCHIVE_LANE=ukie MALLOC_ARENA_MAX=2 $PY -u councils.py run --places wd:Q1,wd:Q2 [--archive-docs 10] [--no-archive]
$PY -u legislation_uk.py ukla --pages 1-1010     # resumable via items table
$PY -u legislation_uk.py lsi --queries "Permit%20Scheme,Parking%20Contraventions" --types uksi --max 500
$PY councils.py status
```

## 2026-10-18 jobs (see `_state/watchdog_jobs.json`)
`run_isb.sh` (isb_local.py, Irish Statute Book local SIs), `run_ie_councils.sh` (phase 3 councils, live then archive queue),
`run_phase2_scale.sh 1|2` (phase-2 councils with a discovered site, `_state/phase2_scale_w{1,2}.txt`, council sites first),
`run_discover_dns.sh` (phase-2 domain guessing). Phase-2 docs must mention bye-law(s) (skip `phase2_not_byelaw`).
Run scripts fall back to /usr/bin/python3 if the venv is missing. `irish_statute_book.py.superseded_by_isb_local` is unused.
