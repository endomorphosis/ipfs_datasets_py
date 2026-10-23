# PREP — FR municipal T1 — 28 SCDL délibérations datasets (Licence Ouverte / ODbL)

Generated: 2026-10-06T14:04:02-0700 (offline). Updated: 2026-10-06 ~2:11 PM PT — 28-id allow-list frozen & wired. Status: **READY** (not launched; waiting CoS GO).
Slug: `fr_scdl_deliberations`  |  Script: `/workspace/scripts/fr_scdl_collect.py`  |  Root: `/workspace/legal-corpora/fr_scdl_deliberations`
Slot: **slot-filler**  |  Expected count: 28

## Source URL(s)
- https://www.data.gouv.fr/api/1/datasets/?schema=scdl/deliberations
- https://schema.data.gouv.fr/scdl/deliberations/latest.html

## Licence
Per dataset: use ONLY open licences — batch B: **21 lov2 + 6 fr-lo + 1 ODbL (=28)**. SKIP 18 notspecified. Portal CGU: Licence Ouverte for editor content; datasets governed by their own licences.

## Robots / terms constraints (from evidence)
data.gouv.fr: Disallow /admin and /datasets/search?*; API path allowed. Evidence: subnational_evidence_20261006/fr/.

## Expected count
46 SCDL délibérations datasets total; **28 open-licensed** (metadata + DELIB_URL PDF links). Partial vs ~35k communes.

## Frozen 28-id allow-list (2026-10-06 ~2:11 PM PT)
- **Path (corpus JSON):** `/workspace/legal-corpora/fr_scdl_deliberations/ref/fr_scdl_28_allowlist_20261006.json`
- **Path (corpus MD):** `/workspace/legal-corpora/fr_scdl_deliberations/ref/fr_scdl_28_allowlist_20261006.md`
- **Source triage copies:** `/workspace/country-law-triage/fr_scdl_28_allowlist_20261006.{json,md}`
- **Count:** **28** dataset ids (exact)
- **Licence split:** lov2=21, fr-lo=6, odc-odbl=1 (18 notspecified excluded)
- **Wiring:** `fr_scdl_collect.py` loads via `load_allowlist()`; ONLY those 28 ids may be collected; **hard-fail** if asked to collect outside the list (`assert_ids_allowed`). `guard_dryrun` + `selftest` assert 28 ids + licence split offline (no network).
- **Status:** **READY** (was BLOCKED; allow-list arrived). Still no launch until CoS GO.

## Rate / RSS plan
Floor delay_s=1.0 via udata API; then polite PDF fetches per DELIB_URL hosts (per-host floors TBD at launch from robots).
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
dataset id + resource row cursor; per-host politeness state. STOP_FRSCDL / PAUSE_FRSCDL.

## CoS decisions (2026-10-06 ~2:05 PM PT; updated ~2:11 PM PT)
- Frozen 28-id allow-list from verifier wired (~2:11 PM PT). Do **not** invent ids.
- Status: **READY** (no longer BLOCKED). Collect only after Watchdog slot-OK + CoS GO.

## Open questions
- Per-destination-host robots for PDF URLs (resolve at GO).
- None blocking prep/allow-list.

## Evidence paths
- /workspace/country-law-triage/subnational_batch_b_20261006.md
- /workspace/country-law-triage/subnational_evidence_20261006/fr/
- /workspace/legal-corpora/fr_scdl_deliberations/ref/fr_scdl_28_allowlist_20261006.json
- /workspace/legal-corpora/fr_scdl_deliberations/ref/fr_scdl_28_allowlist_20261006.md

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
