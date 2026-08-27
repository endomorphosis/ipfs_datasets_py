# New York exact residual-input plan (v1)

Date: 2026-08-26 UTC  
Status: read-only retained-evidence audit; **not authorization to materialize,
index, upload, or publish**

## Retained source algebra

The exact retained v20 input set is one official catalog plus 94 official
full-law PDFs. Current source-bound parsing produces:

```text
37,827 body occurrences + 33 source terminals
  = 37,441 candidate rows + 292 typed terminals + 127 source exclusions

37,441 candidate rows
  = 36,475 operative + 751 typed terminals + 215 unresolved
```

Sixty-eight of the 94 laws close. The exact unresolved projection is:

```text
215 = 183 event-conditioned lifecycle rows
    +   4 bodies missing source-bound lifecycle notes
    +  28 unaligned TOC bodies
```

Its SHA-256 is
`4e8865cc8dbfe4706e0fbe931e31df60a4e4f7e20e88ee9f628507c354b22dc3`.
One event proof is already reusable: the exact official AGM §28 report retained
in v21, body SHA `6abaab50…`. It closes one of the 183 event rows without a new
request, leaving 214 genuinely unresolved rows.

## First acquisition: one 30-URL Senate wave

The four missing-note bodies already exist in their retained PDFs, but their
lifecycle status is not source-bound. The 28 body residuals collapse to 26
unique official section URLs. Deduplicate the union and submit exactly this one
30-URL `www.nysenate.gov` HTML wave through
`_fetch_new_york_frontier_batch`:

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

Twenty-one of the 28 body rows have no exact body header in the retained PDFs.
The other seven are missing extra variants across five identities:

- `EDN 2023-b*2`
- `GMU 371-a*2`
- `TAX 1262-l*2`
- `VAT 235*2` and `VAT 235*3`
- `VAT 1180-i*5` and `VAT 1180-i*6`

If the current section page does not expose every required variant, acquire
only the unresolved variants from a distinct official OpenLeg/version or
session-law document. A historical response for an otherwise identical
unversioned request must use a capture-qualified request identity so differing
bytes cannot make the retained ledger ambiguous.

## External lifecycle proof families

The 183 event-conditioned rows group into the following governing-event
families. Every selector requires affirmative official event or non-event
evidence and an event date; absence from a current page is not proof.

- AGM report delivery: 1 row, already retained and reusable.
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
- Agency-specific termination under GMU §§856/882: 107 rows representing 101
  unique agencies. Use Department of State nonfiling lists and Department of
  Economic Development dissolved/ceased-agency lists; where those are not
  cumulative, obtain historical or agency-specific affirmative evidence.
- DOT roadway-completion record: HAY §342-f.
- Schedule submission under Insurance Law §5516-e: ISC §9111-a.
- Reimbursement-rate approval/certification named by 2026 Ch. 60 §8:
  MHY §36.08.
- Regulation adoption/publication under 2022 Ch. 481 §1: MHY §§82.01–82.15.
- Municipal Assistance Corporation liability discharge/termination:
  PBA §§3030–3041.
- Event specified by 2022 Ch. 205 §5: PEN §265.38.
- Appointment of a majority of the State Franchise Oversight Board: PML §207.
- Two separate IRS rulings: RPT §304 and RPT §926-a; do not merge them.
- One LIRR election plus Comptroller receipt: RSS §389 and WKC §30.
- Condition in 2011 Ch. 525 §7: RSS §1204-a.
- Department of Health contract execution plus 16 years: SOS §365-h.
- DED notice to LBDC under 2019 Ch. 683 §6(2)(b): TAX §24-b.

## Nonduplication and transport contract

None of the 30 Senate section URLs exists in the audited 437,240 retained
state-law fetch receipts or the 112,890-entry legal page cache. Each of the 15
affected retained law PDFs has exactly one current official version and no
retained alternate official PDF. The 30-URL wave is therefore a real residual,
not duplicate acquisition.

Build the eventual aggregate evidence ledger as a fixity-verified union of
v20's 95 parser inputs and only the required v21 AGM report receipt/object, then
append genuinely new inputs. For every supplemental domain and media/request
contract:

1. deduplicate exact request identities before submission;
2. issue one source-ordered plural wave;
3. perform at most one Common Crawl inventory for the domain;
4. group and coalesce byte ranges by WARC file;
5. perform plural Wayback-prefix discovery;
6. retry only unresolved identities; and
7. finish with a complete ledger-only replay making zero network requests.

Do not use the legacy per-page `_build_official_senate_section` path. Do not
materialize until all 94 laws close, the exact `37,441 = operative + terminal`
algebra has zero residuals, and the zero-network replay reproduces the source
frontier and ordered canonical keys.
