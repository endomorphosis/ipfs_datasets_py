# PREP — IS B-deild T1 — Stjórnartíðindi municipal samþykktir

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `is_bdeild`  |  Script: `/workspace/scripts/is_bdeild_collect.py`  |  Root: `/workspace/legal-corpora/is_bdeild`
Slot: **slot-filler**  |  Expected count: 1682

## Source URL(s)
- https://api.stjornartidindi.is/api/v1/adverts-lean (Official Journal API)
- https://api.stjornartidindi.is/api/v1/adverts/{id} (document.html)
- https://api.stjornartidindi.is/swagger-json
- RSS: https://api.stjornartidindi.is/api/v1/rss/b-deild

## Licence
Höfundalög 73/1972 9. gr. — official texts not protected (fetched from althingi.is).

## Robots / terms constraints (from evidence)
api.stjornartidindi.is and island.is robots.txt = 404 (no rules). Evidence: municipal_evidence_20261006/is/.

## Expected count
CoS queue target 1,682 (= SAMÞYKKT-family types 1,588 + Reykjavíkurborg 94 from evidence counts.json). Combined municipal involvedParty query returned 403; per-municipality counting deferred. B-deild total 35,125.

## Rate / RSS plan
Floor delay_s=1.0. Prefer API filters department=b-deild + type/category/involvedParty. Avoid hammering combined municipal OR that 403'd.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
state.json cursor over advert id / page; shards index/laws_shards/. STOP_IS / PAUSE_IS.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- At GO: confirm 1,588+94 membership with a polite read-only probe.
- If 403 persists: **no bypass** — report and HOLD.

## Open questions
- Older adverts may be legacy PDF — OCR plan?
- Rate limits undocumented — watch for 429.

## Evidence paths
- /workspace/country-law-triage/municipal_followup_20261006.md (IS READY)
- /workspace/country-law-triage/municipal_evidence_20261006/is/
- /workspace/country-law-triage/municipal_evidence_20261004/is/

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
