# New York residual closure v1

Date: 2026-08-28
Board: `legal-corpora-reindex-v1`
Task: `LCR-103`
Track: `exact51-residual-wave-d`
Status: **three newly source-proved decisions implemented; not sealed; not publication-authorized**

This report supersedes the stale 214-row narrative with the corrected
New York audit and the bounded research completed on 2026-08-28. The
authoritative starting point is the corrected 212-row inventory. One
official Agriculture and Markets report is now directly recoverable, and
two official Assembly bill records prove two more terminal dispositions.
Those three decisions project the residual from 212 to 209. A fresh
evidence generation and host zero-network replay have not been run, so the
209 figure is a source- and unit-test-backed projection, not a sealed
current-bundle claim.

## Exact identity

| Field | Value |
|---|---|
| jurisdiction | NY |
| official domain | www.nysenate.gov |
| official_pdf_domain | legislation.nysenate.gov |
| official_assembly_domain | assembly.ny.gov |
| official entry | `https://www.nysenate.gov/legislation/laws` |
| official_consolidated_url | `https://www.nysenate.gov/legislation/laws/CONSOLIDATED` |
| corrected_evidence_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-ny-corrected-evidence-cgGxfD` |
| corrected_inventory | `NY/inventories/903f27eb0b34c54e3a167ff811e2eb327fa50eb28d14796077c5aec43c09d5f6.json` |
| corrected_blocker | `NY/blockers/65a124fdb40824bcccd8310e65c3214bf030c10e53d626f95ddf6fd7663bec9c.json` |
| corrected_seed | 99-input corrected seed: 95 catalog/PDF inputs plus four substantive Senate inputs |
| corrected_audited_identity | 37441 = 36477 operative + 752 terminal + 212 unresolved |
| corrected_audited_closed_laws | 70 |
| corrected_audited_event_rows | 183 |
| corrected_audited_senate_version_rows | 29 |
| corrected_unresolved_projection_sha256 | `482b7e60020ad20e2ce6bdd49ef1f9870f9d94269d00f1345c4d1c912b1604b1` |
| agm28_lifecycle_report_url | `https://agriculture.ny.gov/system/files/documents/2023/02/urbanruralconsumeraccessreport.pdf` |
| agm28_lifecycle_report_sha256 | `6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d` |
| agm28_direct_status | HTTP 200; exact digest matched |
| signed_bill_proof_count | 2 |
| signed_bill_wave_name | `signed-assembly-bill-records-1-2` |
| signed_bill_url_projection_sha256 | `ef7e526c284aa62b725b457639b71707627482ac9b35ea76ff8bf74ad48a8a31` |
| projected_identity_after_bounded_direct_wave | 37441 = 36477 operative + 755 terminal + 209 unresolved |
| projected_closed_laws | 72 |
| remaining_event_rows | 182 |
| remaining_senate_version_rows | 27 |
| remaining_unresolved_rows | 209 |
| remaining_senate_wave_url_count | 28 |
| remaining_senate_wave_name | `source-derived-supplemental-sections-1-28` |
| remaining_senate_wave_sha256 | `b03131cd20eb808d159427e548a732a078fc7b3f94291a2c5fff8a4cd206dde0` |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| host_retained_replay_network_requests | 0 required |

The corrected audited identity is exact:

```text
37,441 = 36,477 operative + 752 terminal + 212 unresolved
212 = 183 official event-condition decisions + 29 Senate/version decisions
```

The bounded direct proofs implemented in this worktree produce this
projection:

```text
+1 AGM event proof:             terminal +1, unresolved -1, closed laws +1
+2 signed Assembly bill proofs: terminal +2, unresolved -2, closed laws +1

37,441 = 36,477 operative + 755 terminal + 209 unresolved
209 = 182 official event-condition decisions + 27 Senate/version decisions
72 of 94 laws projected closed
```

Education Law §666 is resolved terminal, but Education remains open because
§669-c and §2023-b*2 remain unresolved. CPL §150.30 was Criminal Procedure's
only residual, so that law newly closes. The AGM report newly closes
Agriculture and Markets.

## Newly recoverable/proved official inputs

### AGM §28

The exact official report now returns HTTP 200 from:

```text
https://agriculture.ny.gov/system/files/documents/2023/02/urbanruralconsumeraccessreport.pdf
```

The body is 1,781,639 bytes and its SHA-256 is exactly
`6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d`.
The existing seven-conjunct fixed resolver proves delivery of the named
report and types AGM §28 terminal. This replaces the corrected inventory's
archive-provider blocker with one direct acquisition; no parser inference is
involved.

### CPL §150.30

Exact official Assembly bill record:

```text
https://assembly.ny.gov/leg/?Actions=Y&Summary=Y&Text=Y&bn=A02009&term=2019
```

The record identifies A02009C, records `04/12/2019 SIGNED CHAP.59`, and in
Part JJJ contains both `Section 150.30 of the criminal procedure law is
REPEALED.` and the Part's January 1, 2020 effective clause. The resolver
binds that exact URL, selector, signed action, same-Part repeal/effective
conjunction, legal-as-of check, retained raw-body digest, and stable semantic
projection SHA-256
`83609b2646f17478c3b6cbfbfa21400eeb4ba10cacb778afa2659cccc0358be7`.

Disposition: `repealed`, effective 2020-01-01.

### Education Law §666

Exact official Assembly bill record:

```text
https://assembly.ny.gov/leg/?Actions=Y&Summary=Y&Text=Y&bn=A03006&term=2025
```

The record identifies A03006C, records `05/09/2025 SIGNED CHAP.56`, and in
Part D contains both `Section 666 of the education law is REPEALED.` and the
same Part's immediate effective clause applying to academic years 2025-2026
and thereafter. Its stable semantic projection SHA-256 is
`3a212979e4428f98acfad78f033949c7abb2b09f8ffe0ac7c24c46dec6d94a02`.

Disposition: `repealed`, effective 2025-05-09.

Assembly response markup contains request-varying bytes. The ledger still
retains and replays the exact raw body and raw SHA-256. Resolver admission is
additionally pinned to the stable source-bearing projection, so harmless
markup variance does not silently change the legal conjunction and any
signed-action, chapter, target clause, effective clause, selector, URL, or
date drift fails closed.

## Exact remaining Senate/version residual

After the two signed-bill dispositions, 27 Senate/version decisions remain:

```text
EDN 669-c
EDN 2023-b*2
ELD 221
ELN 3-408
ELN 7-108
ELN 8-310
ELN 9-104
ELN 9-128
ELN 11-304
ELN 17-140
ELN 17-158
EXC 236
GBS 495-d
GMU 371-a*2
ISC 3114
MHY 7.48
PBA 2799-aaaa
SOS 364-j-1
SOS 369-ii
TAX 602
TAX 622
TAX 636
TAX 1262-l*2
VAT 235*2
VAT 235*3
VAT 1180-i*5
VAT 1180-i*6
```

They split into two missing-lifecycle-note rows and 25 TOC/body rows. Their
current evidence statuses are exact: seven direct-missing/archive-blocked,
18 retained soft-not-found responses rejected as proof, and two VAT §235
variants for which one retained substantive current page does not expose the
required historical variants. Current-page absence is not proof.

The production acquisition path replays/fetches 28 source-derived URLs. It
includes EPT §3-6.5, GMU §902, and PAR §27.09 because their three retained
pages are inputs to existing resolvers; after those resolvers run, the 27
decisions above remain over 25 unique URLs. Four of the 28 URL inputs already
exist in the corrected 99-input seed (the three resolver pages plus VAT
§235), leaving 24 URL acquisitions/recoveries in that wave.

The ordered URL list is:

```text
https://www.nysenate.gov/legislation/laws/EPT/3-6.5
https://www.nysenate.gov/legislation/laws/GBS/495-d
https://www.nysenate.gov/legislation/laws/GMU/902
https://www.nysenate.gov/legislation/laws/PBA/2799-aaaa
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

The production pin is
`sha256("\n".join(urls).encode("utf-8"))` =
`b03131cd20eb808d159427e548a732a078fc7b3f94291a2c5fff8a4cd206dde0`.
Proof manifests continue to use
`json.dumps(..., ensure_ascii=False, separators=(",", ":"), sort_keys=True)`;
that manifest digest is not a substitute for the ordered URL identity.

The seven exact direct-miss rows that still require one bounded grouped
archive/provider retry are:

```text
https://www.nysenate.gov/legislation/laws/EDN/669-c
https://www.nysenate.gov/legislation/laws/ELN/9-104
https://www.nysenate.gov/legislation/laws/ELN/9-128
https://www.nysenate.gov/legislation/laws/PBA/2799-aaaa
https://www.nysenate.gov/legislation/laws/SOS/364-j-1
https://www.nysenate.gov/legislation/laws/TAX/622
https://www.nysenate.gov/legislation/laws/TAX/1262-l
```

The remaining version rows need distinct official OpenLeg historical-version
or signed session-law records when the current section page cannot expose the
required body. Soft 404/not-found shells are never terminal evidence.

## Exact remaining event families

After AGM §28, 182 event-conditioned decisions remain in 22 families:

| Family | Rows | Required official proof |
|---|---:|---|
| DFS 2025 Part Y rules | 16 | DFS/State Register adoption record and event date |
| DFS superintendent notification | 1 | Named notification and issuance/receipt date |
| matching New Jersey enactment | 7 | Enacted NJ text with identical effect and effective date |
| COR session-law expirations | 1 | 1994 ch.60 §42, 1972 ch.339 §10, and 1986 ch.554 §3 expiration proof |
| ENV 2025 concurrent resolution | 4 | Resolution, certified voter result, and implementation chain |
| DEC move to Albany | 1 | DEC/OGS move record and date |
| State BOE compact notification | 2 | Commissioner notification and event date |
| DCJS/DOS §837-aa rules | 1 | Adoption and State Register publication record |
| GMU agency termination | 107 | DOS nonfiling and DED dissolved/ceased records for 101 named agencies |
| DOT roadway completion | 1 | Project completion/noncompletion record and date |
| Insurance §5516-e schedule | 1 | DFS submission/non-submission record and date |
| MHY reimbursement approval | 1 | Approval/certification under 2026 ch.60 §8 |
| MHY 2022 ch.481 regulations | 15 | Adoption plus State Register publication records |
| MAC liability discharge | 15 | Full discharge record and date sufficient for the one-year condition |
| PEN 2022 ch.205 condition | 1 | Session-law condition plus occurrence/nonoccurrence record |
| Franchise Board appointments | 1 | Official roster and appointment dates proving majority status |
| IRS ruling for RPT §304 | 1 | Exact IRS ruling and applicability/date |
| IRS ruling for RPT §926-a | 1 | Distinct exact IRS ruling and applicability/date |
| LIRR election/Comptroller receipt | 2 | Election plus Comptroller receipt and date |
| RSS 2011 ch.525 condition | 1 | Session-law condition plus occurrence/nonoccurrence record |
| DOH contract plus 16 years | 1 | Executed contract and execution date |
| DED notice to LBDC | 1 | Notice/receipt under 2019 ch.683 §6(2)(b) |

### Derived ENV locator bundle

Official research produced a finite candidate bundle for the four ENV rows:

```text
https://www.nysenate.gov/legislation/bills/2025/A7454
https://www.nysenate.gov/legislation/bills/2025/S5227
https://www.nysenate.gov/legislation/bills/2025/S8047
https://elections.ny.gov/2025-statewide-ballot-proposal
https://results.elections.ny.gov/contest/5860
https://results.elections.ny.gov/document/482
https://www.nysenate.gov/legislation/laws/CNS/A14S1
```

A7454/S5227 identify the concurrent resolution, S8047 is the signed Chapter
488 implementation measure, and the Board of Elections pages identify State
Proposal 1 and its certification document. These are exact official locators,
but no bytes from the certified-results document were retained in the
corrected ledger and no selector-specific ENV resolver was added. The four
ENV rows therefore remain unresolved. This bundle is the next bounded event
acquisition/review wave, not a disposition claim.

For the other 21 event families, the retained law PDFs identify the governing
authority and citation but not an exact request URL. The blocker is locator
derivation, not permission to infer that an event did or did not occur.

## Remaining acquisition waves and gate

Run only these bounded steps in a fresh absent evidence generation:

1. Seed the exact 99-input corrected ledger without copying objects or
   overwriting an earlier generation. Replay `consolidated-catalog` and the
   `full-law-pdfs-` waves from those retained inputs.
2. Acquire AGM §28 directly as `agm-28-lifecycle-selector`; exact digest must
   remain `6abaab50…`.
3. Acquire the two Assembly HTML records together as
   `signed-assembly-bill-records-1-2`; bind them as
   `official_signed_bill_record` and reparse before the Senate wave.
4. Replay/fetch the exact 28 Senate URLs together as
   `source-derived-supplemental-sections-1-28`, with one-domain Common Crawl
   inventory, grouped/coalesced WARC reuse, Wayback prefix inventory, and
   residual-only retries. No per-page archive loop or `_build_official_senate_section`.
5. Separately acquire the finite ENV official locator bundle, then implement a
   fixed resolver only if exact retained bytes prove every required conjunct.
6. Derive and review finite exact locators for the other event families;
   retain unknown for every missing or incomplete proof.
7. Only after every law closes, run host `--retained-replay-only` with zero
   network and `--no-incremental-state-publish`. Require 94/94 laws,
   `37,441 = operative + terminal`, and first/replay frontier equality before
   materialization.

Forbidden throughout: Hub mutation, `--publish-to-hf`, Docker-copying the
evidence root, static disposition lists, data-driven resolver registration,
public.law/Justia sole admission, current-page-absence inference, and any
conversion of an unresolved row into current law without exact official
proof.

This worktree did not launch a full corpus job, mutate a remote service, seal
a bundle, or authorize publication.
