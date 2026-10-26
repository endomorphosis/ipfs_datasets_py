# JP 例規集 (local-government rule DB) scraper — asia_latam lane

* `parse_seeds.py`  – parses uub.jp/opm/ml_reikishu.html (1,763 bodies; cached `ml_reikishu.html`) -> `seeds_raw.json`
* `build_places.py` – name+prefecture -> Wikidata P429 (JIS 全国地方公共団体コード, `wd_p429.csv`) -> place_id from
  global_municipalities_candidate.csv; prefectures -> `iso:JP-NN` (adm1). Output `seeds_places.json` (1,716 wd + 47 iso, 0 unmatched).
* `jp_reiki.py`     – crawler. Vendors: gyosei (Reiki-Base static), d1w (D1-Law static), d1ops (D1-Law opensearch), joureikun;
  unknown seed URLs are auto-detected. Polite: 1 req/s per host, ≤2 concurrent bodies per host, robots.txt checked per host,
  UA `JusticeDAO-WorldLaw/1.0 (+github…)`. Resumable per seed (`staging/asia_latam/_state/jp/<seed>.json`).
  Output: SCHEMA.md v1 jsonl, `staging/asia_latam/JP/<place_key>.<seed>-<vendor>-pNNNN-<ts>.jsonl` (250 docs/batch,
  dot-tmp -> fsync -> validate_file -> rename). Unmatched -> `staging/asia_latam/_unmatched/JP/`, bad rows -> `_quarantine/JP/`.
* `run_full.sh`     – full detached run (re-run to resume). `status.py` – summary -> `_status_jp.json`, `_unmatched_jp.csv`.

Not covered yet: g-reiki.net (Gyosei hosted, TLS dropped from box egress), houmu.h-chosonkai.gr.jp (timeouts),
legal-square.com (Gyosei JSF app, session-based), joureikun own-hosts without urllist.txt, a few stale seed URLs.
