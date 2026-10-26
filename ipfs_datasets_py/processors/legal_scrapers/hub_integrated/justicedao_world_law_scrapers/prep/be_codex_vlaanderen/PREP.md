# PREP — BE Codex Vlaanderen — Open Data API

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `be_codex_vlaanderen`  |  Script: `/workspace/scripts/be_codex_collect.py`  |  Root: `/workspace/legal-corpora/be_codex_vlaanderen`
Slot: **slot-filler**  |  Expected count: None

## Source URL(s)
- https://codex.vlaanderen.be/
- https://codex.opendata.api.vlaanderen.be/docs (Open Data API)

## Licence
WER XI.172 §2 + operator open-data API. No restrictive terms located.

## Robots / terms constraints (from evidence)
codex.vlaanderen.be: only system paths disallowed; API host robots 404. Evidence: subnational_evidence_20261006/be/. Batch A READY.

## Expected count
unknown — API not queried beyond docs in gate.

## Rate / RSS plan
Floor delay_s=1.0. Prefer official Open Data API over HTML scrape.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
API page/cursor in state.json. STOP_BECODEX / PAUSE_BECODEX.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- At GO: **count first**, then collect.

## Open questions
- Scope: Flemish Region/Community consolidated only.

## Evidence paths
- /workspace/country-law-triage/subnational_batch_a_20261006.md (BE Codex READY)
- /workspace/country-law-triage/subnational_evidence_20261006/be/be_codexapi_docs.html

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
