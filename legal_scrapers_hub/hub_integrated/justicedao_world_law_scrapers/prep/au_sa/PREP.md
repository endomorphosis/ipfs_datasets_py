# PREP — AU-SA — legislation.sa.gov.au Acts + Regulations

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `au_sa`  |  Script: `/workspace/scripts/au_sa_collect.py`  |  Root: `/workspace/legal-corpora/au_sa`
Slot: **slot-filler**  |  Expected count: None

## Source URL(s)
- https://www.legislation.sa.gov.au/ (Acts + Regulations HTML/PDF)

## Licence
CC BY 4.0 (Copyright Notice ¶3-4; commercial OK; no Excluded Content per ¶11).

## Robots / terms constraints (from evidence)
Crawl-delay: 10; Disallow /search and Matrix admin paths. Evidence: subnational_evidence_20261006/au/. Batch A READY.

## Expected count
unknown — count A-Z first at launch (batch A).

## Rate / RSS plan
Floor delay_s=10.0 (robots Crawl-delay 10). Skip /search.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `10.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
A-Z letter + page cursor in state.json; shards index/. STOP_AUSA / PAUSE_AUSA.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- Delay floor **10s** confirmed OK (robots Crawl-delay 10).

## Open questions
- Exact Acts+Regs volume after A-Z count.
- Prefer HTML consolidated vs PDF?

## Evidence paths
- /workspace/country-law-triage/subnational_batch_a_20261006.md (AU SA READY)
- /workspace/country-law-triage/subnational_evidence_20261006/au/

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
