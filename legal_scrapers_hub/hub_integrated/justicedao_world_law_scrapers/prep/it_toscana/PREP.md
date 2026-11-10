# PREP — IT Toscana — Raccolta Normativa regional acts

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `it_toscana`  |  Script: `/workspace/scripts/it_toscana_collect.py`  |  Root: `/workspace/legal-corpora/it_toscana`
Slot: **slot-filler**  |  Expected count: 4361

## Source URL(s)
- https://raccoltanormativa.consiglio.regione.toscana.it/

## Licence
Free use with attribution ("I documenti… liberamente utilizzabili a condizione che ne sia citata la fonte") + L. 633/1941 art. 5.

## Robots / terms constraints (from evidence)
robots.txt 404 (no rules). Evidence: subnational_evidence_20261006/it/. Batch A READY. Do NOT use Normattiva MFR (/mfr/ricerca/ disallowed; dati.normattiva.it WAF).

## Expected count
4,361 atti (MFR per-region label).

## Rate / RSS plan
Floor delay_s=1.5. HTML only.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.5` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
listing page/cursor in state.json. STOP_ITTOS / PAUSE_ITTOS.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- At GO: discover pagination under robots; **stop and report** if blocked.

## Open questions
- Attribution string for hub card.

## Evidence paths
- /workspace/country-law-triage/subnational_batch_a_20261006.md
- /workspace/country-law-triage/subnational_evidence_20261006/it/landing_it_toscana.html
- /workspace/country-law-triage/subnational_evidence_20261006/it/terms0_it_toscana.html

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
