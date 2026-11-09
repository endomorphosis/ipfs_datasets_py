# DE federal + Länder scrapers & normalizers (secret-free bundle)

Bundled for handoff with staged append package
`/workspace/staging/de_laender_append_20261105/`.

## Collectors (`scripts/`)

| Script | Role |
|---|---|
| `de_laender_collect.py` | Multi-Land collector (BY gesetze-bayern; TLS-gated Länder) |
| `de_laender_collect_bwstream.py` | **BW Gesetzblatt gazette stream** (Benjamin: gazette route only; no juris tokens) |
| `de_laender_collect_rss600.py` | RSS/mem-capped launcher helper for BW/BYVV |
| `de_laender_reprobe_0300.py` | Polite TLS/robots reprobe for HOLD Länder |
| `de_sub_collect.py` | Subnational Landesrecht (BB/HB/NW/SN portals) |
| `de_sub_launch_guarded.py` / `de_sub_supervise.py` | Launch + supervise guards |
| `de_collect.py` / `de_build.py` / `de_finalize.py` / `de_checks.py` | Federal/Landesrecht build pipeline |
| `de_stage_and_check.py` / `de_stage_noHB.py` | Hub staging + never-thin checks (HB held) |
| `de_hub_publish.py` | Publish helper (do **not** run without explicit GO) |
| `de_nw_bb_*` / `de_nw_delta_publish_memsafe.py` | NW/BB follow-up densify |

## Normalizer

| Script | Role |
|---|---|
| `normalize_de_bw_gazette.py` | Offline normalize `DE-BW.jsonl` → hub laws schema parquet |

## Hub scrapers snapshot

`hub_scrapers_snapshot/` — selected modules from prior `endomorphosis/ipfs_germany_laws` scrapers tree (`de_lib.py`, `collect_gii.py`, etc.).

## Hard rules

- ZERO deletions of corpora/caches
- TLS `verify=True` / `CERT_REQUIRED` always
- No captcha/WAF/login bypass; keyless official portals; `max(Crawl-delay, 2s)`
- BW: gazette route only (no juris token minting)
- Do not push to Hugging Face unless CoS quotes Benjamin GO

Mirror path in repo tree (local only, no git push this turn):
`ipfs_datasets_py/processors/legal_scrapers/europe/germany/`

## GVBl gazette wave (2026-11-05)

| Script | Role |
|---|---|
| `scripts/de_laender_gvbl_collect.py` | Resumable non-juris GVBl collector (NI Verkündungsplattform, Berlin SenJust GVBl, Hamburg luewu HmbGVBl) |
| `normalize_de_laender_gvbl.py` | Normalize GVBl JSONL → hub laws parquet |

State: `/workspace/legal-corpora/de_laender_gvbl_20261105/state.json`  
**DE-BE:** STOP on HTTP 429 — do not resume/retry.  
**DE-NI / DE-HH:** resumeable when MemAvailable ≥ 4.2 GiB.
