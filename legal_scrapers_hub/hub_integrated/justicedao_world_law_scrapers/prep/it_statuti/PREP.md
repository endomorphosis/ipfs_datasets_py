# PREP — IT municipal T1 — Ministero dell'Interno Raccolta Ufficiale degli Statuti

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `it_statuti`  |  Script: `/workspace/scripts/it_statuti_collect.py`  |  Root: `/workspace/legal-corpora/it_statuti`
Slot: **slot-filler**  |  Expected count: 8284

## Source URL(s)
- https://dait.interno.gov.it/territorio-e-autonomie-locali/statuti

## Licence
L. 633/1941 art. 5 (atti ufficiali) — statute cited from knowledge in batch B; text not re-fetched.

## Robots / terms constraints (from evidence)
OK: Drupal defaults (core/profiles assets). Evidence: subnational_evidence_20261006/it/robots_b_it_statuti.txt. Batch B READY.

## Expected count
8,284 statuti (7,908 Comuni + 95 Province + 15 Città metropolitane + 193 Unioni). STATUTES ONLY — not regolamenti.

## Rate / RSS plan
Floor delay_s=1.5. HTML + attached files.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.5` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
entity list cursor in state.json. STOP_ITSTAT / PAUSE_ITSTAT.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- **Statutes only** (not regolamenti).
- OCR attachments **only when text is empty** (CZ-style child OCR discipline).

## Open questions
- Confirm per-comune listing pagination.

## Evidence paths
- /workspace/country-law-triage/subnational_batch_b_20261006.md
- /workspace/country-law-triage/subnational_evidence_20261006/it/landing_b_it_statuti.html

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
