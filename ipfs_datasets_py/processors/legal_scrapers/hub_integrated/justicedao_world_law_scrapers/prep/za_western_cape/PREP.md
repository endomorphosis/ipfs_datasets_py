# PREP — ZA Western Cape — Provincial Parliament Acts

Generated: 2026-10-06T14:04:02-0700 (offline). Status: PREP — not launched.
Slug: `za_western_cape`  |  Script: `/workspace/scripts/za_wc_collect.py`  |  Root: `/workspace/legal-corpora/za_western_cape`
Slot: **slot-filler**  |  Expected count: 133

## Source URL(s)
- https://www.wcpp.gov.za/?q=legislation

## Licence
Copyright Act 1978 s.12(8)(a) — no copyright in official legislative texts. Website Terms of Use: no reuse-restriction keywords found.

## Robots / terms constraints (from evidence)
Crawl-delay 10 (Drupal *); Disallow /search/ and Drupal internals; legislation path allowed. barkrowler/serpstatbot Disallow /. Evidence: subnational_counts_za_wc + subnational_evidence_20261006/za/.

## Expected count
133 Acts (filter field_type_of_document_value=2). Bills 189 out of scope for this tranche.

## Rate / RSS plan
Floor delay_s=10.0. Skip /search/.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `10.0` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler (small).

## Resume strategy
Drupal page cursor 0..13. STOP_ZAWC / PAUSE_ZAWC.

## CoS decisions (2026-10-06 ~2:05 PM PT)
- **Acts only**, delay **10s** — clear.

## Open questions
- Act PDF vs HTML body.
- Do not use Gazettes.Africa (robots-blocked + ai-train=no).

## Evidence paths
- /workspace/country-law-triage/subnational_counts_za_wc_20261006.md
- /workspace/country-law-triage/subnational_batch_a2_20261006.md

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
