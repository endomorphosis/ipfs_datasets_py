# world_caselaw — AMEA (Latin America & Caribbean, Africa, Middle East)

Schema: /workspace/world_caselaw/schema (v1.0). Rows: /workspace/world_caselaw/data/<cc>/amea-<source>_partNNNN.jsonl
HF: endomorphosis/world_caselaw, same paths. All AMEA files are prefixed `amea-` (never touches other agents' files).

## Sources
| source prefix | cc | route | policy tags | status |
|---|---|---|---|---|
| amea-sierralii | sl | live Peachjam: /judgments/<COURT>/?page=N -> /akn/... doc pages; PDF text via /source.pdf (pdftotext). 5 s delay, 1 conn | robots-allowed;ai-train=no;search=yes;ai-input=no | background |
| amea-zimlii-wb | zw | Wayback CDX prefix zimlii.org/akn/ (live site behind Cloudflare challenge) -> id_ snapshots | ...;ai-train=no;...;archive-used | background |
| amea-br-stj | br | STJ CKAN open data (CC-BY): metadadosYYYYMMDD.json + textosYYYYMMDD.zip, 2008-present | open-license;robots-allowed | background |

Skipped by instruction: ULII, TanzLII (opt out of AI training). Excluded: CAP / CourtListener / US.
Blocked live (Cloudflare challenge, no bypass): ZambiaLII, MalawiLII, NamibLII, LesothoLII, GhaLII, EswatiniLII, lawlibrary.org.za, SAFLII -> use Wayback (`--wayback`).
Other blocks: SCJN (Incapsula 403), Israel supremedecisions (WAF block page), Turkey AYM (HTTP 500 to bots), Yargıtay/Danıştay (search API errors without browser session), CariLII (500/no response).

## Run
    cd /workspace/world_caselaw/amea
    nohup python3 scrapers/caselaw/peachjam.py --site sierralii.gov.sl --cc sl --src amea-sierralii --delay 5 --shard-rows 200 > logs/sierralii.log 2>&1 &
    nohup python3 scrapers/caselaw/peachjam.py --site zimlii.org --cc zw --src amea-zimlii-wb --wayback --delay 4 --shard-rows 200 > logs/zimlii_wb.log 2>&1 &
    nohup python3 scrapers/caselaw/br_stj.py > logs/br_stj.log 2>&1 &
Same command for other Peachjam LIIs (e.g. --site malawilii.org --cc mw --src amea-malawilii-wb --wayback).
Resumable: state/<src>_done.txt (AKN URIs / STJ dates) written only after a shard is atomically renamed. PIDs in state/*.pid.
Scrapers pause when free disk < 20 GB.
court_id: from /workspace/world_courts/data/<cc>/<cc>_courthouses.jsonl (court_body rows; name/keyword match). Unmatched -> missing_courts.jsonl.

## Upload (idempotent, hourly-safe)
    /workspace/world_caselaw/amea/upload.sh
Uploads only data/*/amea-*_part*.jsonl whose sha256 isn't in state/upload_manifest.json; flock prevents overlap; log logs/upload.log.
Cron: `0 * * * * /workspace/world_caselaw/amea/upload.sh`

## Disk / pruning
upload.sh sets AMEA_PRUNE=1: after a successful commit, local amea-br-stj shards are deleted (STJ full history is tens of GB). Part numbers persist in state/<src>_part.txt so pruned names are never reused.
An hourly loop is running (no crontab on box): `nohup bash -c 'while true; do upload.sh; sleep 3600; done' &` — PID in state/upload_loop.pid.

## Wave 2 (2026-10-29)
- Jobs: sierralii (live, then NigeriaLII auto-starts after it), run_wayback_queue.sh (ZimLII→MalawiLII→NamibLII→ZambiaLII, Peachjam via Wayback),
  run_wayback_generic_queue.sh (SAFLII→TR Anayasa Mahkemesi BB→Israel supremedecisions downloads→AR CSJN; scrapers/caselaw/wayback_generic.py),
  co_cc.py (Colombia Corte Constitucional: datos.gov.co v2k4-2t8s metadata + relatoria HTML), br_stj.py.
- CDX listings are cached in state/cdx_*.tsv; when CDX returns 503 the scraper waits 10 min and retries (up to 4 h).
- SierraLII: many judgments are scanned PDFs with no text layer -> text null (x_text_status=no-text-on-source); OCR pass is a TODO.
