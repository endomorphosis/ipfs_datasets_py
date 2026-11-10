# PREP — BE-FL Centrale Vindplaats — stale regulatory subset

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `be_fl_vindplaats`  |  Script: `/workspace/scripts/be_fl_vindplaats_collect.py`  |  Root: `/workspace/legal-corpora/be_fl_vindplaats`
Slot: **slot-filler**  |  Expected count: 1718

## Source URL(s)
- https://centrale-vindplaats.lblod.info/sparql
- https://publicatie.gelinkt-notuleren.vlaanderen.be/ (full text /raw)

## Licence
WER Art. XI.172 §2 — no copyright on official acts. No site licence statement; operator invites machine reuse.

## Robots / terms constraints (from evidence)
Both hosts: User-agent: * Disallow: (allow all). Evidence: municipal_evidence_20261004/be/ + 20261006/be/.

## Expected count
1,718 regulatory candidates (typed Reglementen/verordeningen ∪ title regex); 893 with inline full text. Date range 2021-07-15 → 2024-05-06 only (STALE).

## Rate / RSS plan
Floor delay_s=1.0 between SPARQL + publication fetches. Small tranche / schema test only — do NOT harvest lokaalbeslist-harvester shards (3.78M; NEEDS_PERMISSION).
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler (small).

## Resume strategy
SPARQL OFFSET/cursor in state.json; shards under index/. STOP_BEFL / PAUSE_BEFL.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- **Confirmed:** 2021-07 → 2024-05 Centrale Vindplaats stale snapshot only.
- **Never** the 3.78M lokaalbeslist-harvester.

## Open questions
- ABB/LBLOD bulk confirmation still required before current harvester.

## Evidence paths
- /workspace/country-law-triage/municipal_followup_20261006.md (BE-VL READY stale 1,718)
- /workspace/country-law-triage/municipal_evidence_20261006/be/

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
