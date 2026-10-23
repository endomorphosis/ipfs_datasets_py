# PREP — BR ALESP — São Paulo state normas (open ZIP)

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `br_alesp`  |  Script: `/workspace/scripts/br_alesp_collect.py`  |  Root: `/workspace/legal-corpora/br_alesp`
Slot: **alone-required**  |  Expected count: 254063

## Source URL(s)
- https://www.al.sp.gov.br/repositorioDados/legislacao/legislacao_normas.zip
- https://www.al.sp.gov.br/ (dados abertos)

## Licence
Lei 9.610/1998 art. 8 IV (atos oficiais) — statute cited from knowledge; no portal terms located.

## Robots / terms constraints (from evidence)
OK: /repositorioDados/legislacao allowed (Disallow seo/web/StaticFile/contratos). Evidence: subnational_evidence_20261006/br/. Counts file confirms 254,063.

## Expected count
254,063 normas in open ZIP (10.2 MB compressed). By tipo: Lei 42,773; Decreto 178,802; … (see subnational_counts_br_pt_20261006).

## Rate / RSS plan
Download ZIP once then offline parse (no per-norma crawl). delay_s=2.0 only if supplementing via HTML. HUGE — alone-required; NEVER with NL-M.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `2.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
ALONE-REQUIRED. Cap context: launch only when NL-M and other collectors are stopped. Never pair with NL-M.

## Resume strategy
ZIP download progress + XML stream cursor; packed shards under index/. STOP_BRALESP / PAUSE_BRALESP.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- **Alone-required confirmed** (never with NL-M).
- At GO: take **ALL tipos** from the open ZIP (not Lei-only) — dump, not crawl.

## Open questions
- Shard sizing for 254k rows under RSS 300MB.

## Evidence paths
- /workspace/country-law-triage/subnational_counts_br_pt_20261006.md
- /workspace/country-law-triage/subnational_evidence_20261006/br/
- /workspace/country-law-triage/subnational_batch_a_20261006.md

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
