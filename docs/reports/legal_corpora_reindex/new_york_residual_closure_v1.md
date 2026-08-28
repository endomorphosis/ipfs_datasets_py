# New York residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-103`  
Goal: `LCR-G153`  
Track: `exact51-residual-wave-d`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-103 by recording the exact remaining New York
residual: seed the 96-input v20-plus-AGM union, then acquire one 30-URL
`www.nysenate.gov` HTML wave and keep every unresolved decision unresolved
until reviewed source-bound resolvers see official proof bytes. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, the legacy
`_build_official_senate_section` path, public.law/Justia sole admission,
and converting unresolved decisions into current law are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | NY |
| official domain | www.nysenate.gov |
| official_pdf_domain | legislation.nysenate.gov |
| agm28_domain | agriculture.ny.gov |
| official entry | `https://www.nysenate.gov/legislation/laws` |
| official_consolidated_url | `https://www.nysenate.gov/legislation/laws/CONSOLIDATED` |
| agm28_lifecycle_report_url | `https://agriculture.ny.gov/system/files/documents/2023/02/urbanruralconsumeraccessreport.pdf` |
| agm28_lifecycle_report_sha256 | `6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d` |
| agm28_selector_key | AGM:28 |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official full-law PDF plus reviewed supplemental proof resolvers |
| same_target_parser_for_live_and_replay | true |
| seed | 96-input v20-plus-AGM union; 95 v20 direct plus one v21 AGM Wayback |
| seed_v20_direct_inputs | 95 |
| seed_v21_agm_wayback_inputs | 1 |
| seed_selected_input_count | 96 |
| seed_selected_projection_sha256 | `46dce4a3aecf32f3fe21dd743da8f958b1bec8bbc84f5ec680e49f2c13807f76` |
| seed_copied_file_count | 0 |
| convert_unresolved_decisions_into_current_law | forbidden |
| dynamic_resolver_registration | forbidden |
| public_law_justia_fallback_in_strict | forbidden |
| legacy_per_page_senate_section_path | forbidden |
| invent_later_senate_section_urls | forbidden |
| unbounded_locator_hunt | forbidden |
| static_residual_list | forbidden |
| v20_catalog_plus_pdf_inputs | 95 |
| v20_verified_bytes | 75151982 |
| catalog_law_count | 94 |
| catalog_ordered_code_sha256 | `792d08fe5168ff6b429d13076fa843a8e5987c4b670339e1a2c6ca70420d590c` |
| source_sections | 37441 |
| operative_sections | 36475 |
| terminal_sections_before_agm | 751 |
| terminal_sections_after_agm | 752 |
| unresolved_before_agm | 215 |
| unresolved_after_agm | 214 |
| closed_laws_before_agm | 68 |
| closed_laws_after_agm | 69 |
| event_conditioned_rows_before_agm | 183 |
| event_conditioned_rows_after_agm | 182 |
| missing_lifecycle_note_rows | 4 |
| toc_body_rows | 28 |
| supplemental_residual_rows | 32 |
| extra_toc_variant_identities | 7 |
| enumerable_url_residual_count | 30 |
| unresolved_decision_count | 214 |
| residual_count | 30 |
| residual_kind | exact 30-URL www.nysenate.gov wave plus 214 unresolved proof decisions |
| residual_first_url | `https://www.nysenate.gov/legislation/laws/EPT/3-6.5` |
| residual_wave_name | `source-derived-supplemental-sections-1-30` |
| agm28_wave_name | `agm-28-lifecycle-selector` |
| catalog_wave_name | `consolidated-catalog` |
| pdf_wave_name_prefix | `full-law-pdfs-` |
| catalog_acquisition_wave_count | 1 |
| agm28_acquisition_wave_count | 0 remaining; already retained |
| supplemental_acquisition_wave_count | 1 |
| implemented_event_resolvers | 1 |
| unimplemented_event_resolvers | 182 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256("\n".join(urls))` |
| residual_ordered_sha256 | `30fb7bd969c80f3747b3ff0eae6685f11e61bdd82193b4abf35864a2c32a1ec2` |
| residual_ordered_sha256_prefix | `30fb7bd969c8` |
| unresolved_projection_sha256_before_agm | `4e8865cc8dbfe4706e0fbe931e31df60a4e4f7e20e88ee9f628507c354b22dc3` |
| unresolved_projection_sha256_after_agm_prefix | `d6b209ac65ab` |
| diagnostic_hashes_authorizing | false |
| source_bundle | `f68d2672e24092c93810dd0f168a098a855d7879bea746faa63f676ef3ccdd75` |
| source_bundle_prefix | `f68d2672e240` |

The 30-URL residual SHA-256 is the production pin
`STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256`. Recompute it only as
`sha256("\n".join(urls).encode("utf-8"))` over the source-ordered unique
Senate section URLs derived from the 32 v20 residual rows. Proof
manifests and unimplemented-resolver outcomes use
`json.dumps(..., ensure_ascii=False, separators=(",", ":"), sort_keys=True)`
and are not a substitute for that 30-URL identity. Guessing later Senate
locators, emitting a 37,441-row dump, or encoding diagnostic notes as
operative/terminal decisions fails closed.

## Outcome

New York is **not** assembler-eligible. The exact retained v20 source set
is one official catalog plus 94 official full-law PDFs: 95 unique direct
inputs over 75,151,982 verified bytes. The only reusable v21 proof is the
AGM §28 official report (`6abaab50…`); its seven conjuncts pass and the
fixed source-bound resolver moves exactly one AGM residual to one typed
terminal without changing 722 operative AGM rows. Candidate algebra is
therefore:

```text
37,441 = 36,475 operative + 752 typed terminals + 214 unresolved
```

Sixty-nine of 94 laws close. The 214 unresolved decisions split as 182
event-conditioned rows, four missing lifecycle notes, and 28 TOC/body
rows. Those 32 body/note rows deduplicate in source order to one exact
30-URL `www.nysenate.gov` wave. Host zero-network replay has not sealed
a current-bundle pair, normalized receipt, or JSON-LD/Parquet pair for
this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is: seed a fresh NY evidence
generation from the exact 96-input v20-plus-AGM union, acquire only the
ordered 30-URL Senate wave plus any separately source-proved event or
version inputs, implement reviewed fixed resolvers for those retained
proofs, require all 94 laws and `37,441 = operative + terminal` to close
with zero unresolved decisions, then host `--retained-replay-only` of
every parser input with zero network before materialization.

## Source algebra

Current source-bound parsing of the retained v20 PDFs produces:

```text
37,827 body occurrences + 33 source terminals
  = 37,441 candidate rows + 292 typed terminals + 127 source exclusions

37,441 candidate rows
  = 36,475 operative + 751 typed terminals + 215 unresolved
```

The 215-row unresolved projection SHA-256 is
`4e8865cc8dbfe4706e0fbe931e31df60a4e4f7e20e88ee9f628507c354b22dc3`.
One event proof is already reusable: AGM §28, body SHA
`6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d`.
It closes one of the 183 event rows without a new request:

```text
215 = 183 event-conditioned + 4 missing lifecycle notes + 28 TOC/body
214 = 182 event-conditioned + 4 missing lifecycle notes + 28 TOC/body
 32 body/note rows = 4 missing notes + 28 TOC/body
 30 unique Senate URLs = 32 rows minus 2 extra VAT variant identities
     that share a URL with another residual row
```

After AGM §28, 69/94 laws close and the unresolved-row SHA prefix is
`d6b209ac65ab`. Absence from a current Senate page is not proof.

## Exact remaining URL

The exact next URL is the first source-ordered member of the 30-URL
Senate wave:

```text
https://www.nysenate.gov/legislation/laws/EPT/3-6.5
```

The complete enumerable URL residual, in production source order, is:

```text
https://www.nysenate.gov/legislation/laws/EPT/3-6.5
https://www.nysenate.gov/legislation/laws/GBS/495-d
https://www.nysenate.gov/legislation/laws/GMU/902
https://www.nysenate.gov/legislation/laws/PBA/2799-aaaa
https://www.nysenate.gov/legislation/laws/CPL/150.30
https://www.nysenate.gov/legislation/laws/EDN/666
https://www.nysenate.gov/legislation/laws/EDN/669-c
https://www.nysenate.gov/legislation/laws/EDN/2023-b
https://www.nysenate.gov/legislation/laws/ELD/221
https://www.nysenate.gov/legislation/laws/ELN/3-408
https://www.nysenate.gov/legislation/laws/ELN/7-108
https://www.nysenate.gov/legislation/laws/ELN/8-310
https://www.nysenate.gov/legislation/laws/ELN/9-104
https://www.nysenate.gov/legislation/laws/ELN/9-128
https://www.nysenate.gov/legislation/laws/ELN/11-304
https://www.nysenate.gov/legislation/laws/ELN/17-140
https://www.nysenate.gov/legislation/laws/ELN/17-158
https://www.nysenate.gov/legislation/laws/EXC/236
https://www.nysenate.gov/legislation/laws/GMU/371-a
https://www.nysenate.gov/legislation/laws/ISC/3114
https://www.nysenate.gov/legislation/laws/MHY/7.48
https://www.nysenate.gov/legislation/laws/PAR/27.09
https://www.nysenate.gov/legislation/laws/SOS/364-j-1
https://www.nysenate.gov/legislation/laws/SOS/369-ii
https://www.nysenate.gov/legislation/laws/TAX/602
https://www.nysenate.gov/legislation/laws/TAX/622
https://www.nysenate.gov/legislation/laws/TAX/636
https://www.nysenate.gov/legislation/laws/TAX/1262-l
https://www.nysenate.gov/legislation/laws/VAT/235
https://www.nysenate.gov/legislation/laws/VAT/1180-i
```

Those 30 URLs are the fail-closed pin
`STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS`. Production derives them from
`STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS` and raises if membership,
order, host, or newline SHA drifts. None of the 30 identities exists in
the audited 437,240 retained state-law fetch receipts or the
112,890-entry legal page cache. The wave is therefore a real residual,
not duplicate acquisition.

Twenty-one of the 28 TOC/body rows have no exact body header in the
retained PDFs. The other seven extra variants across five identities
still share those same five URLs:

- `EDN 2023-b*2`
- `GMU 371-a*2`
- `TAX 1262-l*2`
- `VAT 235*2` and `VAT 235*3`
- `VAT 1180-i*5` and `VAT 1180-i*6`

If a current section page does not expose every required variant, acquire
only the unresolved variants from a distinct official OpenLeg/version or
session-law document. A historical response for an otherwise identical
unversioned request must use a capture-qualified request identity so
differing bytes cannot make the retained ledger ambiguous. Do not invent
a later `/legislation/laws/ZZZ/` locator.

## Exact remaining proof residual

The 30-URL wave binds official Senate HTML as
`official_senate_section` proof inputs. The fixed supplemental-proof
registry admits only byte-bound official inputs, exposes no
`register_resolver` API, and leaves every missing or unimplemented
selector `unknown` with `decision_action=None`. Retaining a Senate page
does not close a law. The remaining proof residual is therefore all 214
unresolved decisions until reviewed source-specific resolvers exist.

AGM §28 is the only implemented event resolver. Its seven conjuncts are:

1. exact official source URL
2. exact retained report SHA-256 `6abaab50…`
3. valid PDF with extracted pages
4. identifies the exact 2022 report
5. states delivery to the governor and the legislature
6. states that submission of this report concludes the requirement
7. authoritative dated department XMP on or before `legal_as_of`

The remaining 182 event-conditioned rows group into the following
governing-event families. Every selector requires affirmative official
event or non-event evidence and an event date.

- DFS rule promulgation under 2025 Ch. 58 Part Y §13: 16 BNK rows.
- Superintendent of Financial Services notification: BNK §103.
- Matching New Jersey enactment: COM §§220–225 and PBA §2985-a.
- Expiration of three cited session-law provisions: COR §851.
- Concurrent resolution referenced by 2025 Ch. 488 §2: ENV §§9-2301–9-2304.
- DEC move to Albany: ENV §3-0105.
- State Board of Elections compact-threshold notification: ELN §§12-400,
  12-402.
- DCJS/Department of State rule promulgation under Executive Law §837-aa:
  GBS §396-eeee.
- Agency-specific termination under GMU §§856/882: 107 rows representing
  101 unique agencies. Use Department of State nonfiling lists and
  Department of Economic Development dissolved/ceased-agency lists;
  where those are not cumulative, obtain historical or agency-specific
  affirmative evidence. Do not invent one URL per agency.
- DOT roadway-completion record: HAY §342-f.
- Schedule submission under Insurance Law §5516-e: ISC §9111-a.
- Reimbursement-rate approval/certification named by 2026 Ch. 60 §8:
  MHY §36.08.
- Regulation adoption/publication under 2022 Ch. 481 §1: MHY §§82.01–82.15.
- Municipal Assistance Corporation liability discharge/termination:
  PBA §§3030–3041.
- Event specified by 2022 Ch. 205 §5: PEN §265.38.
- Appointment of a majority of the State Franchise Oversight Board:
  PML §207.
- Two separate IRS rulings: RPT §304 and RPT §926-a; do not merge them.
- One LIRR election plus Comptroller receipt: RSS §389 and WKC §30.
- Condition in 2011 Ch. 525 §7: RSS §1204-a.
- Department of Health contract execution plus 16 years: SOS §365-h.
- DED notice to LBDC under 2019 Ch. 683 §6(2)(b): TAX §24-b.

Do not convert those families into current law. Do not hunt unbounded
locators. Do not encode diagnostic notes as decisions.

## Seed, then one 30-URL wave

Required acquisition shape:

1. Seed a fresh absent NY evidence root from the exact 96-input
   v20-plus-AGM union via `seed_retained_evidence_union`: all 95 v20
   direct catalog/PDF inputs plus only the one v21 AGM Wayback proof,
   excluding the other seven v21 observations. Selected-projection SHA
   must remain
   `46dce4a3aecf32f3fe21dd743da8f958b1bec8bbc84f5ec680e49f2c13807f76`.
   Hardlink objects (`copied_file_count=0`). Never overwrite a prior
   ledger. Direct-only reuse applies to the 95 v20 inputs;
   `--allowed-source-transport wayback` is admitted only for the exact
   AGM report URL.
2. Replay the retained catalog, 94 PDFs, and AGM selector through
   `_replay_new_york_retained_input` / `_fetch_new_york_frontier_batch`
   without a new catalog or PDF residual. The AGM selector request
   identity is `Accept: application/pdf,*/*;q=0.8`.
3. Submit the 30 Senate URLs as one same-host plural HTML wave named
   `source-derived-supplemental-sections-1-30` through
   `_fetch_new_york_frontier_batch`. One `www.nysenate.gov` Common Crawl
   inventory with URL term `/legislation/laws/`, grouped/coalesced WARC
   reuse, Wayback prefix inventory, residual-only retries without
   archive reinventory, `prefer_direct=True`, and no per-page archive
   loop. Do not use `_build_official_senate_section`.
4. Bind acquired pages as `official_senate_section` proof inputs and
   reparse. Unimplemented resolvers must remain `unknown`. Implement
   reviewed selector-specific resolvers only for retained official proof
   bytes.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require all 94 laws closed, `37,441 = operative + terminal`,
   first/replay frontier equality, and `public_law_no_state_copyright`
   before treating the pair as assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later Senate
  section targets;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- per-page archive loops, `archive.is`, and the legacy per-page
  `_build_official_senate_section` path;
- public.law or Justia sole-admission fallback in strict full-corpus
  mode;
- converting unresolved decisions, missing proofs, or historical archive
  bodies into current law;
- dynamic resolver registration or data that asserts its own status;
- repeating a Common Crawl domain inventory inside one acquisition
  attempt;
- resuming a fenced staging root as current.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | New York binding |
|---|---|
| Source-derived frontier | Official consolidated catalog, 94 full-law PDFs, AGM §28 proof, then the 30-URL Senate residual |
| Fresh evidence generation | `seed_retained_evidence_union` of 95 v20 direct plus one AGM Wayback; never overwrite |
| Direct-only reuse | `--allowed-source-transport direct` for v20; Wayback only for the exact AGM report |
| One residual wave | `source-derived-supplemental-sections-1-30` |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave and reviewed resolvers
close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states NY \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-ny-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-ny-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would
not flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is:

```text
https://www.nysenate.gov/legislation/laws/EPT/3-6.5
```

The exact remaining proof residual is the 214 unresolved decisions: the
30-URL Senate wave as bound HTML proof inputs plus 182 event-conditioned
selectors that stay `unknown` until official proof bytes and reviewed
resolvers exist. The 30-URL ordered newline SHA remains
`30fb7bd969c80f3747b3ff0eae6685f11e61bdd82193b4abf35864a2c32a1ec2`.
