# Minnesota retained-frontier audit v1

Audit date: 2026-08-26

Scope: read-only reconciliation of the retained Minnesota acquisition evidence
under `full-acquisition-evidence-v4/MN` against the current official Revisor
root, TOC-part, chapter, and section parsers. No network acquisition was
launched and no retained evidence or acquisition artifact was changed.

## Exact source frontier

The retained official root lists 105 unique TOC parts. Those parts list 1,133
unique chapters in source order. The chapter catalogs list 54,435 unique leaf
locators:

- 54,383 detail-page leaves requiring a section response;
- 52 source-bound chapter-73 terminal leaves whose exact catalog bytes type
  them as renumbered and therefore must not be fetched as detail pages.

The exact parser-input frontier after completion is 55,622 inputs: one root,
105 TOC parts, 1,133 chapter catalogs, and 54,383 required detail pages.

## Retained and residual inputs

The evidence contains 39,070 physical fetch receipts representing 38,923
unique endpoint/content identities. Of the physical receipts, 39,022 are
direct and 48 use Wayback; after endpoint deduplication, 38,875 are direct and
48 use Wayback. The 147 extra receipts repeat identical endpoint bytes and do
not conflict in URL or content identity.

Exactly 38,872 retained inputs belong to the required parser-input frontier:
one root, 105 TOC parts, 1,133 chapters, and 37,633 detail pages. The remaining
51 unique retained inputs are older detail fetches for 51 of the 52 leaves now
typed by the sealed chapter-73 catalog. They are reusable evidence but are
redundant parser inputs and must not be admitted or reacquired. Section 73.55
is the one catalog-terminal leaf with no redundant retained detail response.

The exact residual is therefore 16,750 detail URLs. It is the source-ordered
difference between the 54,383 required detail locators and the 37,633 retained
detail locators. Its first retained-order member is
`https://www.revisor.mn.gov/statutes/cite/336.1-301`; its last is
`https://www.revisor.mn.gov/statutes/cite/648.51`.

## Current retained classification

All 37,633 required retained detail objects match their recorded SHA-256
digests. The current parser classifies 21,857 as operative and 15,776 as typed
terminal pages, with no duplicate operative identity and no unclassified
retained input. Terminal counts are:

| Disposition | Count |
| --- | ---: |
| expired | 192 |
| expired+repealed | 3 |
| inoperative | 4 |
| local_or_special | 41 |
| never_effective | 5 |
| obsolete | 43 |
| obsolete+renumbered | 1 |
| omitted | 8 |
| renumbered | 2,207 |
| renumbered+repealed | 58 |
| repealed | 13,143 |
| repealed+temporary | 1 |
| repealed+unnecessary | 1 |
| superseded | 25 |
| temporary | 4 |
| transferred | 3 |
| unconstitutional | 5 |
| unnecessary | 32 |

The sole parser anomaly was the retained official response at
`/statutes/cite/296.01-1`, whose exact `.sr` element displays the historical
citation `296.01`. The parser now accepts that mismatch only for the exact URL,
60,883-byte body, SHA-256
`04a01e0bb5ce4817e0ca76ab1e9a67bfa80920ed4155adbbd9fcbbfc7dbb6893`,
and display citation. Any byte, URL, or markup drift fails closed.

Including the 52 catalog terminals, the retained source-leaf closure currently
accounts for 37,685 of 54,435 leaves: 21,857 operative and 15,828 terminal.
The 16,750 residual responses remain the publication blocker because their
operative/terminal dispositions cannot be inferred before acquisition.

## Reuse and next acquisition policy

The exact path replays retained parser inputs before network work, submits each
known same-domain frontier in deterministic source order through the plural
fetch API, and submits the complete cross-chapter detail union as one wave.
The configured parse/checkpoint slice remains bounded independently. Initial
archive recovery uses one Wayback prefix inventory and Common Crawl grouped,
coalesced WARC range reuse. Bounded retries contain only unresolved rows and do
not repeat grouped archive inventory or fall back to per-page archive loops.

