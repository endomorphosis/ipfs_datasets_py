# PREP — ID Jawa Tengah JDIH — Perda + Pergub

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `id_jateng_jdih`  |  Script: `/workspace/scripts/id_jateng_collect.py`  |  Root: `/workspace/legal-corpora/id_jateng_jdih`
Slot: **slot-filler**  |  Expected count: 2101

## Source URL(s)
- https://jdih.jatengprov.go.id/

## Licence
UU No. 28/2014 Pasal 42 — no copyright in peraturan perundang-undangan.

## Robots / terms constraints (from evidence)
User-agent: * Disallow: (allow all). Evidence: subnational_evidence_20261006/id/robots_c2_id_jateng.txt. Batch C2 READY. JDIHN national network TLS-blocked — do not use.

## Expected count
Perda 739 + Pergub 1,362 (=2,101). Chart also shows Kepgub 2,528 — OUT OF SCOPE for this tranche (Perda+Pergub only). Complements id_bpk IN_PROGRESS.

## Rate / RSS plan
Floor delay_s=2.0 (match id_bpk politeness).
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `2.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler.

## Resume strategy
document id cursor in state.json. STOP_IDJT / PAUSE_IDJT.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- **Perda + Pergub only** (no Kepgub).

## Open questions
- Listing API/HTML path for Perda vs Pergub filters.
- PDF OCR need rate.

## Evidence paths
- /workspace/country-law-triage/subnational_batch_c2_20261006.md
- /workspace/country-law-triage/subnational_evidence_20261006/id/

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
