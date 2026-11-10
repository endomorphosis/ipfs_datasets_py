# PREP — PT Azores — JO-RAA DLR + DRR

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `pt_azores`  |  Script: `/workspace/scripts/pt_azores_collect.py`  |  Root: `/workspace/legal-corpora/pt_azores`
Slot: **slot-filler**  |  Expected count: 754

## Source URL(s)
- https://jo.azores.gov.pt/
- https://jo.azores.gov.pt/api/public/search/ato

## Licence
CDADC art. 7 — textos de leis e regulamentos não protegidos (cited in batch A).

## Robots / terms constraints (from evidence)
OK — robots.txt is only "User-agent: *" (no Disallow). Evidence: subnational_counts_br_pt + subnational_evidence_20261006/pt/.

## Expected count
Decreto Legislativo Regional 339 + Decreto Regulamentar Regional 415 (=754).

## Rate / RSS plan
Floor delay_s=1.0 via public search API (pageSize≤200).
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
API page + humanId cursor. STOP_PTAZ / PAUSE_PTAZ.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- **Clear** — CoS confirmed; no further prep blockers.

## Open questions
- Full-text field vs PDF attachment.
- Madeira JORAM still NEEDS_PERMISSION — out of scope.

## Evidence paths
- /workspace/country-law-triage/subnational_counts_br_pt_20261006.md
- /workspace/country-law-triage/subnational_batch_a_20261006.md
- /workspace/country-law-triage/subnational_evidence_20261006/pt/

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
