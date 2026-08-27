# Arkansas current-variant evidence audit (v1)

This is an evidence-only audit. It does not admit, normalize, index, or publish
a statute body. The retained delegated inventory remains the source of
all candidate locator identities, including source defects. The Arkansas
General Assembly change tables and public acts are used only to determine
whether a candidate can be selected without guessing.

## Fixed inputs and result

- Delegated inventory:
  `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/arkansas-delegated-inventory-v6/arkansas-lexis-toc.json`
- Inventory SHA-256:
  `af92fd2d12405dfe5246ab50563dc9031180b82c8d0fa0e5336e9580f2085475`
- Inventory observation: `2026-08-25T04:32:58.722528+00:00`
- Source inventory: 38,317 statute locators, 38,183 unique citations, 132
  concurrent-citation groups.
- Source-label reconciliation before enactment evidence: 94 selected, one with
  no current locator, and 37 unresolved.
- The original enactment-and-TOC-identity overlay selected 29 of those 37 and
  left 8 unresolved. The canonical JSON digest of that pre-GovInfo 37-row
  overlay, sorted by citation and with sorted candidate node IDs, is
  `f4e80b14676a96df921bf6abfec0ee8325133c58e02fd57759486004d6622572`.
- The source-bound GovInfo addendum below closes `16-56-106`, bringing the
  currently retained result to 30 selected and 7 unresolved. Its exact
  resolution-object digest is
  `1ca66ddfc19ac6dcaf4762a4386c0a3f085cf6b14dc2d4c0f4f526b31e9e573d`.
- A subsequent exact-source audit established a deterministic Act 283
  resolution for `11-10-803` and `26-51-905`: select the two `until` locators
  and preserve the two `if` locators as
  `future_contingent_not_yet_effective`. The canonical 863-byte
  selection/exclusion plan has SHA-256
  `ad29f34cc60ba5b095f46ca7bbffb3164a89ba39b05ec67d017c315bdfb03938`.
  The resolver rejects any missing or changed Act, CRC, DWS, locator, request,
  transport, or parser-input receipt.
- The existing authorizing ledger contains Act 283 but not the exact CRC and
  DWS parser-input receipts. Therefore the retained result remains 30 selected
  and 7 unresolved; after those two exact inputs are retained and replayed, the
  reproducible result is expected to be 32 selected and 5 unresolved. No
  materialization was started.
- The corpus is still inadmissible. No unresolved candidate body has been
  admitted and no row has been emitted.

The overlay selects only an exact retained node ID. It does not synthesize a
new locator, use content-item recency, or infer that the second locator is the
newer one. An identical-heading pair remains unresolved unless another exact
source feature binds one candidate to the enacted text.

### Executable retained preflight

The 29-row enactment/TOC overlay is now an executable, atomic replay rather
than a report-only decision table. It accepts only the exact delegated
inventory SHA-256 above, an exact canonical locator-selection plan with
SHA-256
`d2fc5ad212cb87810121667c439cd56ba6d51d8db1e986af4f9b8b897d4c4b55`,
and all 52 exact retained official inputs named by the plan (15 title change
tables and 37 public acts). Each input is rebound through its retained
`ArkansasCurrentVariantResolution` parser envelope, complete GET identity,
HTTP status, jurisdiction, body digest and size, parser-input receipt, and
verified transport receipt. A missing input, extra input, changed body,
changed inventory, changed candidate set, or changed selected locator rejects
the whole overlay before any decision is admitted.

The same retained-only full-corpus preflight invokes the independent H.R. 5330
and Act 283 resolvers before reconciliation. H.R. 5330 resolves from the
already-retained Act 1032 and GovInfo BILLSTATUS inputs with zero network
requests. Act 283 is invoked but remains fail-closed because the CRC Exhibit E1
and current DWS form are not in the authorizing ledger. On the exact retained
65-receipt ledger, the executable replay changes the all-duplicate baseline
from `94 selected + 1 no-current + 37 unresolved` to
`124 selected + 1 no-current + 7 unresolved`; restricted to the original
37-conflict cohort, that is exactly `30 selected + 7 unresolved`. The sorted
full decision digest is
`edb8578ae9029280f6bd134d89fd81722a2291e6e1a63158bf4dfbe8002b9450`.
The ledger remains 65 receipts and 65 objects before and after replay, proving
that this path neither fetches nor writes evidence.

The integration is activated only when `ARKANSAS_LEXIS_INVENTORY_PATH` names
the exact retained inventory and `ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT`
names the retained proof-ledger root. Full-corpus mode runs this preflight
before any live delegated probe or secondary recovery. Because the seven
citations listed below remain unresolved, it still raises the delegated-corpus
blocker and does not materialize, normalize, index, or publish any body.

Three retained-TOC identity forms supply that binding, but only within the
fixed inventory fingerprint above:

1. A detached legacy branch contains only the duplicate section, while the
   alternative same-titled branch contains the official editorial note and
   complete canonical sibling sequence. The independently Act-proven
   § 26-57-1507 repeal is a positive control for this exact layout.
2. A legacy duplicate is out of citation order and the alternative occupies
   the one canonical numeric position among its immediate siblings.
3. An unlabeled pair is ordinally aligned with independently resolved pairs in
   the same exact parent and enactment set. This is used only for § 4-2A-101,
   whose neighboring § 4-2A-102 and § 4-2A-107 pairs explicitly label the
   pre/post-September 1, 2026 order, and § 21-5-406, aligned with the exact
   Act 205 collision at § 21-5-1101 and the independently repealed § 21-5-421
   pair in the same subchapter.

None of these forms is a global “last node wins” rule. Missing notes, a
non-singleton detached branch, non-unique numeric placement, reversed ordinal
anchors, a different parent, or a different enactment set remains unresolved.

## Citation-by-citation decision table

`Tn` refers to the retained official 2025 code-section change table for title
`n`. `Ay-n` refers to the retained official public Act `n` from year `y`; exact
URLs and digests are below.

| Citation | Retained candidate node IDs | Decision | Exact official evidence |
|---|---|---|---|
| 10-2-133 | `AAKAADAABABI`, `AAKAADAABABJ` | Select repealed node `AAKAADAABABJ`. | `T10` records Act 2 as RP; `A2025-2` expressly repeals § 10-2-133. |
| 11-10-803 | `AALAAKAAJAAE`, `AALAAKAAJAAF` | **Source-bound selection ready:** select until node `AALAAKAAJAAE`; preserve `AALAAKAAJAAF` as `future_contingent_not_yet_effective`. Existing ledger remains unresolved until the two new official inputs are retained. | `A2021-283` § 3 defines the trigger; the exact CRC Exhibit E1 records DWS's official statement that the contingency had not been met, and the exact current DWS form still allows federal withholding only. All three input bodies are digest-pinned together. |
| 14-40-208 | `AAOAADAAFAADAAJ`, `AAOAADAAFAADAAK` | Select repealed node `AAOAADAAFAADAAK`. | `T14` records Act 314 as RP; `A2025-314` expressly repeals § 14-40-208. |
| 14-58-202 | `AAOAADAAXAABAAB`, `AAOAADAAZAADAAD` | Select canonical-branch node `AAOAADAAZAADAAD`. | `T14` and `A2025-24` prove the current emergency-clause amendment. `AAOAADAAXAAB` is an exact detached singleton branch; `AAOAADAAZAAD` contains the official note and the canonical 14-58-201—203 sequence. |
| 15-43-205 | `AAPAAEAAEAADAAE`, `AAPAAEAAEAADAAF` | Select repealed node `AAPAAEAAEAADAAF`. | `T15` records Act 26 as RP; `A2025-26` expressly repeals § 15-43-205. |
| 16-56-106 | `AAQAAFAADAACAAH`, `AAQAAFAADAACAAI` | Select the until-contingency node `AAQAAFAADAACAAH` / `681V-8950-R03K-G0T5-00008-00`. | `A2021-1032` § 2 required H.R. 5330 to become law by January 1, 2026. Exact official GovInfo BILLSTATUS bytes identify H.R. 5330 of the 116th Congress, contain no law node, and report the latest action as placement on Union Calendar No. 537 on December 15, 2020. The 116th Congress ended January 3, 2021, before the trigger deadline. |
| 16-90-123 | `AAQAAGAAMAACAAY`, `AAQAAGAAMAACAAZ` | Select substantive node `AAQAAGAAMAACAAZ`. | `T16` records Act 1003 as NS; `A2025-1003` enacts the section with the retained substantive heading. |
| 17-37-202 | `AARAACABCAADAAD`, `AARAACABCAADAAE` | Select repealed node `AARAACABCAADAAD`. | `T17` records Act 292 as RP; `A2025-292` expressly repeals § 17-37-202. |
| 19-42-201 | `AATAAEAADAACAAC`, `AATAAEAADAACAAD` | **Unresolved identity.** | `A2025-419` recodifies Title 19 and prints the full section, but the two retained headings are identical and neither locator is body-bound to that recodification. |
| 19-43-222 | `AATAAEAAEAACAAU`, `AATAAEAAEAACAAY` | Select canonical-position node `AATAAEAAEAACAAY`. | `A2025-419` recodifies and prints the section. The first duplicate is retained out of order between 19-43-218 and 19-43-219; this candidate alone occupies the exact position after 19-43-221 and before 19-43-223. |
| 21-5-1101 | `AAVAAFAALAAB`, `AAVAAFAAOAAC` | Select canonical-branch node `AAVAAFAAOAAC`. | `T21` and `A2025-205` prove the emergency-clause amendment. `AAVAAFAAL` is a detached singleton branch; `AAVAAFAAO` contains the official subchapter note and canonical locator. |
| 21-5-406 | `AAVAAFAAFAAH`, `AAVAAFAAFAAI` | Select aligned Act-205 node `AAVAAFAAFAAI`. | `T21`, `A2025-205`, and `A2025-234` prove current amendments. The same exact Act 205 set independently binds the second § 21-5-1101 locator; the same parent independently binds the second § 21-5-421 locator to Act 2's repeal. The § 21-5-406 pair has that exact ordinal alignment. |
| 21-5-421 | `AAVAAFAAFAAP`, `AAVAAFAAFAAY` | Select repealed node `AAVAAFAAFAAY`. | `T21` records Act 2 as RP; `A2025-2` expressly repeals § 21-5-421. |
| 23-3-201 | `AAXAABAAEAADAAC`, `AAXAABAAEAADAAE` | Select definitions node `AAXAABAAEAADAAC`. | `T23` and `A2025-373` add subsection (e) definitions; only this candidate's exact heading includes “Definitions”. `A2025-705` is a later same-session amendment and does not remove them. |
| 23-4-909 | `AAXAABAAFAAJAAK`, `AAXAABAAFAAJAAL` | **Unresolved identity.** | `T23` and `A2025-373` prove a current emergency-clause amendment, but the retained headings are identical and neither locator is act-bound. |
| 24-6-202 | `AAYAAGAADAAC`, `AAYAAGAADAAE` | Select canonical-position node `AAYAAGAADAAE`. | `T24` and `A2025-112` prove the current emergency-clause amendment. The first duplicate is out of order before 24-6-201; this candidate alone occupies the exact position after 24-6-201 and before 24-6-203. |
| 25-43-505 | `AAZABSAADAAB`, `AAZABSAAIAAG` | Select canonical-branch node `AAZABSAAIAAG`. | `T25` and `A2025-10` prove the current emergency-clause amendment. `AAZABSAAD` is a detached singleton branch; `AAZABSAAI` contains the official note and canonical 25-43-501—505 sequence. |
| 26-3-306 | `ABAAABAADAADAAH`, `ABAAABAADAADAAI`, `ABAAABAADAADAAJ` | Select 2026 assessment-year node `ABAAABAADAADAAJ`. | `T26` maps Acts 407, 876, and 880; `A2025-880` expressly applies its exact § 26-3-306 amendment to assessment years beginning on or after January 1, 2026, matching this node's exact source label. |
| 26-5-101 | `ABAAABAAFAAC`, `ABAAABAAFAAD`, `ABAAABAAFAAE` | Select 2026 tax-year node `ABAAABAAFAAE`. | `T26` maps Act 719; `A2025-719` amends § 26-5-101 and expressly applies the act to tax years beginning on and after January 1, 2026, matching this node's exact source label. |
| 26-51-2702 | `ABAAAFAACABCAAD`, `ABAAAFAACABCAAE` | Select 2026 tax-year node `ABAAAFAACABCAAE`; preserve its literal “Januay”/impossible-end-date label as a source defect. | `T26` maps Acts 701 and 709; both official acts amend the exact section and § 7 in each says tax years beginning on or after January 1, 2026. The acts repair the boundary, not the retained source string. |
| 26-51-905 | `ABAAAFAACAAKAAG`, `ABAAAFAACAAKAAH` | **Source-bound selection ready:** select until node `ABAAAFAACAAKAAG`; preserve `ABAAAFAACAAKAAH` as `future_contingent_not_yet_effective`. Existing ledger remains unresolved until the two new official inputs are retained. | The same indivisible Act 283 + CRC nonoccurrence + current DWS form proof bundle resolves both citations together; it cannot partially select only one. |
| 26-51-908 | `ABAAAFAACAAKAAK`, `ABAAAFAACAAKAAL` | Select 2026 tax-year node `ABAAAFAACAAKAAL`; preserve the old candidate's malformed “Effective until tax years beginning before” label. | `T26` maps Act 616; `A2025-616` § 3(a) makes its exact § 26-51-908 amendment effective for tax years beginning on or after January 1, 2026. |
| 26-57-1507 | `ABAAAFAAIAAPAAB`, `ABAAAFAAIAASAAI` | Select repealed node `ABAAAFAAIAASAAI`. | `T26` records Act 380 as RP; `A2025-380` expressly repeals § 26-57-1507. |
| 27-14-802 | `ABBAACAACAAJAAD`, `ABBAACAACAAJAAE` | **Unresolved contingency.** | `T27` maps Act 926; `A2025-926` § 12 requires an implementation certification filed with named state entities. No exact certification receipt is retained. |
| 27-14-803 | `ABBAACAACAAJAAF`, `ABBAACAACAAJAAG` | **Unresolved contingency.** | Same `A2025-926` § 12 trigger and missing certification as § 27-14-802. |
| 4-2A-101 | `AAEAABAAEAACAAC`, `AAEAABAAEAACAAD` | Select pre-effective node `AAEAABAAEAACAAC`. | `A2025-997` takes effect September 1, 2026, after the inventory observation. In the same exact parent, § 4-2A-102 explicitly orders pre-effective then post-effective and § 4-2A-107 orders unmarked pre-effective then explicitly post-effective. The § 4-2A-101 pair has that exact two-position alignment; no URN-age inference is used. |
| 5-64-308 | `AAFAAHAAFAAEAAG`, `AAFAAHAAFAAEAAH` | **Unresolved contingency.** | `A2019-447` § 2 requires the later of January 1, 2021 or an Arkansas Attorney General certification about a federal prescribing requirement. No exact certification receipt is retained. |
| 6-15-2102 | `AAGAACAAGAAWAAD`, `AAGAACAAGAAWAAE` | Select substantive definition node `AAGAACAAGAAWAAE`. | `T6` records Acts 340 and 341 as NS; both `A2025-340` and `A2025-341` add § 6-15-2102 with the exact “Definition” heading. |
| 6-18-722 | `AAGAACAAJAAIAAB`, `AAGAACAAJAAKAAX` | Select canonical-branch node `AAGAACAAJAAKAAX`. | `T6` and `A2025-123` prove the current emergency-clause amendment. `AAGAACAAJAAI` is a detached singleton branch; `AAGAACAAJAAK` contains the official note and canonical 6-18-701—723 sequence. |
| 6-51-1101 | `AAGAAEAACAAMAAB`, `AAGAAEAACAAMAAE` | Select repealed node `AAGAAEAACAAMAAE`. | `T6` records Act 25 as RP; `A2025-25` expressly repeals §§ 6-51-1101—6-51-1104. `A2025-419` § 373 expressly preserves other 2025 session acts over its technical recodification. |
| 6-51-1102 | `AAGAAEAACAAMAAD`, `AAGAAEAACAAMAAG` | Select repealed node `AAGAAEAACAAMAAG`. | Exact range repeal and construction rule in `A2025-25` and `A2025-419`, as above. |
| 6-51-1103 | `AAGAAEAACAAMAAF`, `AAGAAEAACAAMAAI` | Select repealed node `AAGAAEAACAAMAAI`. | Exact range repeal and construction rule in `A2025-25` and `A2025-419`, as above; the title table's Act 419 technical row does not override Act 25. |
| 6-51-1104 | `AAGAAEAACAAMAAH`, `AAGAAEAACAAMAAJ` | Select repealed node `AAGAAEAACAAMAAJ`. | Exact range repeal and construction rule in `A2025-25` and `A2025-419`, as above. |
| 7-9-103 | `AAHAAJAACAAD`, `AAHAAJAACAAF` | Select canonical-position node `AAHAAJAACAAF`. | `T7` maps Acts 153, 218, 273, 274, 453, and 768. The first duplicate is out of order before 7-9-102; this candidate alone occupies the exact position after 7-9-102 and before 7-9-104. |
| 7-9-107 | `AAHAAJAACAAI`, `AAHAAJAACAAK` | Select canonical-position node `AAHAAJAACAAK`. | `T7` maps Acts 153, 154, 272, 602, and 768. The first duplicate is out of order before 7-9-106; this candidate alone occupies the exact position after 7-9-106 and before 7-9-108. |
| 7-9-109 | `AAHAAJAACAAL`, `AAHAAJAACAAN` | Select canonical-position node `AAHAAJAACAAN`. | `T7` maps Acts 240 and 274. The first duplicate is out of order before 7-9-108; this candidate alone occupies the exact position after 7-9-108 and before 7-9-110. |
| 8-6-609 | `AAIAAHAAGAAK`, `AAIAAHAAGAAL` | Select substantive host-fee node `AAIAAHAAGAAL`. | `T8` records Act 815 as NS; `A2025-815` adds § 8-6-609 with the exact “Host fee — Definition” heading. |

## Preserved cross-title source-label anomaly

The locator inventory contains node `AACAACAAFAAFAAC` under Title 2, Chapter
19, Subchapter 5 with the literal source label
`2-19-501 — 5-19-503. [Repealed.]`. It has no `section_number` and remains
nonstatutory. The retained replay types it as
`nonstatutory_citation_collection_repealed_cross_title_source_label`. It is not
repaired to `2-19-503`, split into sections, or promoted to a statute locator.

`T2` records `2-19-5`, Act 290, RP Yes. `A2025-290` expressly repeals Arkansas
Code Title 2, Chapter 19, Subchapter 5 and prints sections 2-19-501 onward.
`A2019-378` and `A1991-968` retain official historical enactment evidence for
2-19-501—503. The exact observed defect is therefore terminally classified
without changing its bytes or citation endpoints.

## Official change-table receipts

Each URL has the form
`https://www.arkleg.state.ar.us/Acts/CodeSection?section={title}&ddBienniumSession=2025%2F2025R`.

| Ref | Title | SHA-256 |
|---|---:|---|
| T2 | 2 | `11288fe674fd5e66f3f6c9bdd3bdb0c649ad0a9c68c319e7a7a3a02f9d2dd8d6` |
| T4 | 4 | `3734e6e17491c739440a4ef240268cc2e95e2786008a69616efdc67214364362` |
| T5 | 5 | `a8eb9018107dbd44c3182980dbbd292d50423442eb567e30483f8e4786d60ea7` |
| T6 | 6 | `876dd4925c3be77dede5045f069ecbba3aaf24ed1c563dbb02603410ec7b3ae6` |
| T7 | 7 | `4a9e204a69f3727f9a90131d3054e2397611234af0e35d64500191da0e44bc7d` |
| T8 | 8 | `7235110d3e78a97d0fc1f890f625d401c3e755488aadf5e01149102a624a5492` |
| T10 | 10 | `9d62bb92ef67ecfae4c32cff748b7392524c7744973d2777bfb7b1d15ac3cd34` |
| T11 | 11 | `25e6230203ee7d6de936217e1ed4c06e1cbbebc945dfe3eca9950f70b82999f1` |
| T14 | 14 | `a5bbf1c2ea62508426340b257f236c70934db03c9a357062dcf40e2c3f766b0c` |
| T15 | 15 | `7bf3d7c7e62b873d1d83e9ada4e85c36aa0e5056394f3113393dff6da64301be` |
| T16 | 16 | `f763d3c8c433b512385e3452bdd34314ce6cd9ddb28451bf6c2debea457afeef` |
| T17 | 17 | `817773045b55e7e52c4e7ebeffb8f33cbc9f2933ad366bda077ef2e886d5d878` |
| T19 | 19 | `a8f44cf1457651b77afd8e343b7d08628b72259c7c6f581f08047fd112df0851` |
| T21 | 21 | `2f563a00ae36ff5fc99a517bbe8d73a0d9537e1871a7a8f500f9e9f51cfd6fac` |
| T23 | 23 | `5178070bc931f9766f31c96ec9c54b48445e1ebb114a7cc5c85d9d0d4f9b0ec4` |
| T24 | 24 | `deeb88176796d0d861faed984af5960ae5a8b9fdadbecbaed7a2e65582b3b636` |
| T25 | 25 | `3b77bbaf3e8ad5109d99abde24e3bf522c4c16b0f1cbb7d88a54c2f6cf0028b6` |
| T26 | 26 | `c1b6f4c055e466c8972ab035656c0c1a9de13a0cc8967e9b3c2f6bc3eb30539e` |
| T27 | 27 | `d887609de1a96a662854acc0e69a638b33e039bdff7687be754f7efa4089f433` |

## Official public-act receipts

Except for the explicitly listed historical URLs, a 2025 act URL has the form
`https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&file={act}.pdf&ddBienniumSession=2025%2F2025R`.

| Ref | SHA-256 |
|---|---|
| A2025-2 | `cf952d55b9bf8e42ecb8847d90712e67ff4f28ab6611b6622983c66865d74b64` |
| A2025-10 | `a096adb1a7afebc78a1967e9acffb2e09ea9871b265c27993bd4575c6399d9b4` |
| A2025-24 | `c9ced0141731b9fd9687bbee9096dd6bd43f19f7b1b7396b0d97e2b8178af561` |
| A2025-25 | `932037076cdef651430de1c143768dc84b844a271e0e5281aeb8a0cceb6af46b` |
| A2025-26 | `55dc3931693d4c31b95839f9ab9d461a0d708fa14457ed46b2c3ac6efb5839bd` |
| A2025-112 | `3a52db5e564750b823245f64c210f2dde63ffc72fc32fb5c7e4713fca7dffae9` |
| A2025-123 | `426534a83c1856ebd499712673dd02e156461dd489923238da9402ea7f9e499d` |
| A2025-153 | `d27d4d824d9708e4b9371dde1dfd469a1beed588a4f5e29c625e3f73755ce88d` |
| A2025-154 | `e2e0663e40d9451732e27c294a645a27d994130226e791526e5ac991382a53ba` |
| A2025-205 | `1500bfedf9a5bf840a287d5c55472f0f02eb3ca5b4c234c7175b974e8e18844d` |
| A2025-218 | `367265f73721d2fb7eaaa6c7a6e5a1103400f17d40b8901f9eb7156fadb82f9a` |
| A2025-234 | `46b0ba130ec09ae034c1aa9c916838398b0df909019b7dbfd271b5d059ce7937` |
| A2025-240 | `ce39519f8aa03694e5ab91a20d8822f8e1e4f0826d2e554c5ebc203eaebbf466` |
| A2025-272 | `a6852cc03cc97eb535b978b2f9f01853e14072493d9842b5b0320a89b63a8c39` |
| A2025-273 | `30804a307943aec85e2a426176eb8c1bb26d0d1f8031b1e1cdbc7a736f81ac41` |
| A2025-274 | `385e15e7659e0f036007d606667228698887e143feb1e40d3648043892d40f52` |
| A2025-290 | `151fedf6739057a264658597a992359f983da846de5b1f39be972b0291bd06c8` |
| A2025-292 | `187144f083af9f3443eb88351a0243f4288cd999c1162e912c24b99c2b38b44b` |
| A2025-314 | `7c292116b8ccae5540ef24aa299c392def293f2fc8611da77a887b7d4081c8e7` |
| A2025-340 | `2c4e66bb6d7313d1c499268b747a443e5b998c18929f916c2f8864af883f02bc` |
| A2025-341 | `772a439513416b6376340ba971b7bfa02fea966c2546ae3310be40a0fe7a7211` |
| A2025-373 | `fa0ad2a4dd3cef14da56065a2cd128caa29cacb4db3eb7544b4a67eecf4341c4` |
| A2025-380 | `350b5f828c71626101f6af2e2da0176eca4d986b6204347f74328bb11db1c32d` |
| A2025-407 | `a5361fc616adac1c32f88a449c0b8a6df27ed6124deedad62367c57f406d1569` |
| A2025-419 | `5507bef690ecffd984e16d83478224912d3e03103cd6a52c3c9fed7c35b149dd` |
| A2025-453 | `48bbe38662a26db3bd58feb76c75f957e80dcf1a372447bdcb25c5374ae8c510` |
| A2025-602 | `94ae5498873c964a5c1316f53108cdbe11ab299600cda2b1dbbacc25dda44ba7` |
| A2025-616 | `2acabbe4ec7431296c9b9d7bbed4c8febfea234d4d93f687235634e7fdc03244` |
| A2025-701 | `d2e294dbdcd7df5ce1bffb782f81f395d4f08692a885e5de3028a7883914d8e3` |
| A2025-705 | `bef9c4cd2df82e99f7a0f9b0aa4af5cf05ec0ae7916c57c1c2d2fea0b303683a` |
| A2025-709 | `9366f85bcaafc789ca1157005407c95097d6ab277d34bef7654a59df9ff590df` |
| A2025-719 | `eb2300aff5629bd57ca0beee2544344b47154e9555944b5c165a404547e79e6f` |
| A2025-768 | `69854ad9f678f824a7307ef7272d2388c7a9f9c3c86c6b03f5d36852217ddb33` |
| A2025-815 | `fde8b8fa796751d92c7e5544225c14eee4b2e1cc8ba0a69e92625222fad6c55b` |
| A2025-876 | `05f0a17aebe0a0f20b268e7e1ac81019b241f08bd0a8fe7ea1c651f00b0c7f4e` |
| A2025-880 | `ddbb49666ec85a5550421ac0b10f06dc374c961aeca183aac69b7edd0344170c` |
| A2025-926 | `613ef75651a4e3c5adbb66da1859ad105e6eac1336604a443251a61aa2561353` |
| A2025-997 | `cfc81fbc42576c7c30941f2c4727bd19247f8910b71afb44af80cbc963362915` |
| A2025-1003 | `4e99e09e1f25e616ac873248facb417d875b45bf31c9b41faa5a7526b602ac45` |

The retained older-act URLs are exact rather than inferred from the 2025
pattern:

| Ref | Official URL | SHA-256 |
|---|---|---|
| A2021-283 | `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2021R%2FPublic%2F&file=283.pdf&ddBienniumSession=2021%2F2021R` | `3df754fb7c243c620289f2f05a0381a11f2e787a94b6e1998746ee870320b5a0` |
| A2021-1032 | `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2021R%2FPublic%2F&file=1032.pdf&ddBienniumSession=2021%2F2021R` | `59534f794b626bf9d162fec606eb343c9c5f922a3340a34efd1d2ddfbbfae019` |
| A2019-447 | `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2019R%2FPublic%2F&file=447.pdf&ddBienniumSession=2019%2F2019R` | `ec6647135cba62e622f3a274e0ef4915837799e3b7e822cf373682763bac80de` |
| A2019-378 | `https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FACTS%2F2019R%2FPublic%2FACT378.pdf` | `89acf721dc98778b0bc9483d4b86119d175ac81c81ce2c23b3023b5628033f61` |
| A1991-968 | `https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FACTS%2F1991%2FPublic%2F968.pdf` | `c325b1fe92feb9ab6f90615c675642b1cd27c61ca09697fdc506309bbd19f86b` |

## Official GovInfo contingency receipt

- Official URL:
  `https://www.govinfo.gov/bulkdata/BILLSTATUS/116/hr/BILLSTATUS-116hr5330.xml`
- Body SHA-256:
  `ff17b359294dd8923472fa3a6fea1f5640776e4b715b6bfc075dce3b2779d122`
- Body CID:
  `bafkreih7c6zvskkn3cjdi4x2hjx6uh2wib3w4s3rlnv7yb25zy5so6orei`
- Byte size: `12630`
- Direct HTTP parser-input receipt SHA-256:
  `de2bc47a51c22193cbc2a7cf0fc91ea4d14d7be4003b31aa426391a470b90013`
- Canonical transport-receipt SHA-256:
  `690bb79a4a59965f98fe5737b6bc546233071325384042da2168da753f6fc1af`
- The same resolution capability replays the already retained exact Act 1032
  PDF (`59534f794b626bf9d162fec606eb343c9c5f922a3340a34efd1d2ddfbbfae019`,
  308537 bytes) under parser-input receipt
  `6845feaea71d8b7cfcbae7a3e28b8ae66f65ba5b7e15e4c336b49fcfaa2fdef2`
  and canonical transport-receipt digest
  `4262d9aa5ff35e749c001c420ee173746fe22c64b21cbb1d9d3b8c660111d0e2`.
- Exact request identity: `GET` plus the official URL above, with no request
  headers added to the sanitized identity.
- Acquisition used the shared direct-first multi-fetch seam: one direct
  request succeeded, zero Common Crawl inventory queries, zero WARC requests,
  and zero residual fallback requests. Exact replay then used zero network
  requests.

The validator pins both official bodies and separately checks the Act 1032
PDF/request/receipt identity, GovInfo XML root/schema, bill
number/type/congress/origin, update date, latest-action ledger parity, absence
of a direct law collection, and the Congress-end/trigger chronology.
GPO's [BILLSTATUS XML user guide](https://github.com/usgpo/bill-status/blob/main/BILLSTATUS-XML_User_User-Guide.md#laws)
states that the `laws` element is empty unless a measure has been enacted and
assigned a public-law number.
The U.S. Senate's official [dates of sessions table](https://www.senate.gov/legislative/DatesofSessionsofCongress.htm)
records the 116th Congress's second session as ending on January 3, 2021,
before Act 1032's January 1, 2026 trigger deadline.
Digest, URL, node ID, URN, heading, XML, request identity, transport receipt,
or retained parser-input drift fails closed.

## Shared delegated-page batch contract

The fixed inventory contains exactly 16 distinct delegated document-page URLs
for the eight originally unresolved citation pairs. Their node IDs, citations,
URN paths, seven retained title-response digests, and the whole inventory
digest replay without drift. The Arkansas adapter passes that aligned frontier
to the existing state-law plural fetch seam with:

- domain `advance.lexis.com`;
- one Common Crawl URL prefix, `/documentpage/`;
- direct-first concurrency, followed by one shared Common Crawl inventory for
  misses;
- grouping and range coalescing by immutable WARC object in the existing
  `state_archival_fetch` / `web_archiving` implementation; and
- a separate exact citation-body validation for every returned URL before a
  row or diagnostic can be emitted.

No Arkansas WARC, CDX, range, or archive client was added. Restart replay uses
the existing complete sanitized GET identity, so retained pages do not trigger
another live request, Common Crawl lookup, or WARC slice.

## Evidence-store integrity

The append-only evidence root is
`/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/arkansas-current-resolution-evidence-v1/AR`.
At this audit it contains 65 typed fetch receipts and 65 content-addressed
objects for 65 unique official URLs. Every receipt's declared SHA-256 equals
the retained object's bytes and filename. There are zero missing objects, zero
symlinks, and 130 distinct inodes across the 130 files. All transports used by
the cited receipts are recorded as direct; no secondary body was treated as
official.

## Exact identity-body and secondary-edition checks

A four-locator plural probe covered the following exact retained URNs in one
ordered `advance.lexis.com` `/documentpage/` wave:

- `6J02-Y1M0-R03N-11YK-00008-00` and
  `6JJX-0JB0-R03P-11YC-00008-00` for `19-42-201`;
- `4WVJ-BCY0-R03N-60BF-00008-00` and
  `6FHK-F8H0-R03M-P2W8-00008-00` for `23-4-909`.

The Arkansas adapter exposes this exact four-node identity frontier separately
from the original sixteen-node audit frontier, then hands it once to the
shared `web_archiving` plural seam. That seam performs at most one same-domain
Common Crawl inventory query, groups all hits by immutable WARC object, and
coalesces ranges; no per-page CDX, WARC-object, or WARC-range loop is allowed.
The bounded audit's single inventory lookup timed out, no exact WARC pointer
was admitted, and direct/Wayback/archive payloads either missed or failed the
citation-and-body validator. The fresh probe root
`arkansas-variant-body-identity-evidence-v1/AR` therefore remains empty: zero
receipts, zero objects, and zero candidate-body bindings. It does not change
either identity decision.

The retained TOC supplies no substitute identity rule. For `19-42-201`, one
candidate's content-item prefix is shared with the surrounding Act 419
recodification sequence while the other content item is distinct. For
`23-4-909`, one candidate continues the old `23-4-901`--`23-4-909` content-item
series and the other is appended after it. Those shapes suggest source update
history, but they do not prove the body behind either locator. In particular,
Act 373 also amended §§ 23-4-901, 23-4-902, 23-4-903, 23-4-905, 23-4-907, and
23-4-908 without parallel duplicate locators, so there is no same-Act ordinal
anchor that uniquely labels the § 23-4-909 pair. Content-item prefix, apparent
age, and append order therefore remain explicit negative evidence, not a
selection rule.

Justia was checked only as an explicitly secondary edition cross-check. Search
discovery exposed Arkansas Code editions 2024, 2023, and 2020 for the relevant
Title 23 hierarchy, but no exact 2025 edition for either unresolved citation;
direct unauthenticated requests to the hypothesized 2025 and current section
paths returned HTTP 403. No Justia bytes were retained, and no 2024 text is
substituted for or represented as the 2025 official/delegated corpus.

Two earlier official-evidence recovery workers were later found blocked in the
legacy archive fallback. After exact PID, parent, and command-line verification,
only their Python subprocesses received `SIGINT`; both workers and shells then
exited without escalation. At that termination boundary the official evidence
root remained exactly 64 fetch receipts plus 64 objects, with no later file
timestamp or evidence delta; the separately identified GovInfo receipt above
was subsequently appended as receipt/object 65.

## Remaining exact blocker

The current retained result still reports seven unresolved citations. The new
Act 283 algebra closes two of them only after the exact CRC and DWS responses
are prospectively retained in the authorizing ledger. The five substantive
blockers after that replay are two identical/unqualified locator-identity pairs
and three contingency citations. The identity pairs require an exact
body-to-act comparison or equivalent official source identity; locator order
and content-item age are insufficient. Sections `27-14-802` and `27-14-803`
require the exact Act 926 implementation certification, and `5-64-308`
requires the exact Arkansas Attorney General certification. Until those five
boundaries close, no 38,000-body acquisition or corpus admission is authorized
by this audit.

## Post-audit official trigger and identity hunt (2026-08-25)

This appendix records a bounded follow-up on the seven citations in the
currently retained result. It launched no full crawler, admitted no statute
body, and did not enlarge either evidence store. It did produce the later
Act 283 resolver and focused tests described above. The hashes below identify
the exact observed response body or, where separately labeled, the
already-retained acquisition receipt.

Nothing here treats enacted Arkansas law as copyrighted or source-
inadmissible. The blocker is solely the absence of exact proof of a named
legal trigger or an exact body-to-URN identity binding. Publisher access
controls were not bypassed.

### Candidate identity and fail-closed decision

The exact delegated document URL for each URN below is the literal prefix

`https://advance.lexis.com/documentpage/?pdmfid=1000516&config=00JAA2ZjZiM2VhNS0wNTVlLTQ3NzUtYjQzYy0yYWZmODJiODRmMDYKAFBvZENhdGFsb2fXiYCnsel0plIgqpYkw9PK&pddocfullpath=%2Fshared%2Fdocument%2Fstatutes-legislation%2Furn%3AcontentItem%3A`

followed by that URN. This is the retained inventory mapping, not a recency or
locator-order inference.

| Citation | Exact candidate node / URN identities | Bounded official finding | Fail-closed disposition |
|---|---|---|---|
| 11-10-803 | Until: `AALAAKAAJAAE` / `4WVD-J370-R03N-P1NN-00008-00`; if: `AALAAKAAJAAF` / `62N9-CKR0-R03N-V4W1-00008-00` | Act 283 defines a conjunctive implementation trigger. CRC Exhibit E1 records DWS's official statement that the contingency had not been met. The later exact official DWS form still authorizes federal withholding only, which is incompatible with operation of the triggered state-withholding text. The resolver requires all three pinned official PDFs and their exact receipts together. | **Select the until candidate after strict retention/replay; preserve the if candidate as `future_contingent_not_yet_effective`.** Existing ledger remains unresolved because CRC and DWS parser-input receipts are absent. |
| 26-51-905 | Until: `ABAAAFAACAAKAAG` / `4WVP-0VS0-R03J-S4T1-00008-00`; if: `ABAAAFAACAAKAAH` / `62N9-G2T0-R03N-J4W2-00008-00` | Same indivisible Act 283 + CRC nonoccurrence + later current DWS operational proof. The function returns both section resolutions atomically and cannot admit one without the other. | **Select the until candidate after strict retention/replay; preserve the if candidate as `future_contingent_not_yet_effective`.** Existing ledger remains unresolved for the same receipt gap. |
| 27-14-802 | Until: `ABBAACAACAAJAAD` / `4WVS-4PV0-R03K-72V1-00008-00`; if: `ABBAACAACAAJAAE` / `6G0S-8470-R03N-60JG-00008-00` | Act 926 requires the Office of Motor Vehicle's implementation certification. The official RFP says the existing process was manual and contemplated implementation, pilot, acceptance, and 30 consecutive compliant days; the live bid remained “2BA - Bid Approved (Ready for Vendor Awarding)” on August 25, 2026. Neither item is the statutory certification, nor proves that no other exact filing exists. | **Unresolved. Select neither candidate; admit no row.** |
| 27-14-803 | Until: `ABBAACAACAAJAAF` / `4WVS-4PV0-R03K-72V2-00008-00`; if: `ABBAACAACAAJAAG` / `6G0S-8FX0-R03N-60JH-00008-00` | Same Act 926 certification and evidence boundary as 27-14-802. The latest located DFA monthly rules report does not assert implementation or certification. | **Unresolved. Select neither candidate; admit no row.** |
| 5-64-308 | Until: `AAFAAHAAFAAEAAG` / `4WPT-00W0-R03K-10WH-00008-00`; on trigger: `AAFAAHAAFAAEAAH` / `5VST-6VD0-R03M-70WR-00008-00` | Act 447 requires an Arkansas Attorney General certification. CRC Exhibit E1 records only that staff contacted the Attorney General; the Board of Pharmacy/ADH notice repeats the condition but is not the certification. The current official AG sitemaps disclosed no matching item. Federal EPCS implementation cannot substitute for the Arkansas certification named by the act. | **Unresolved. Select neither candidate; admit no row.** |
| 19-42-201 | `AATAAEAADAACAAC` / `6J02-Y1M0-R03N-11YK-00008-00`; `AATAAEAADAACAAD` / `6JJX-0JB0-R03P-11YC-00008-00` | Act 419 supplies the enacted section but does not identify either delegated URN. A single four-page same-domain browser context returned Lexis Human Verification for all four identity-gap URLs, and the bounded project archive fallbacks admitted no validated archived body. | **Unresolved. Select neither candidate; admit no row.** |
| 23-4-909 | `AAXAABAAFAAJAAK` / `4WVJ-BCY0-R03N-60BF-00008-00`; `AAXAABAAFAAJAAL` / `6FHK-F8H0-R03M-P2W8-00008-00` | Act 373 supplies the enacted amendment but does not identify either delegated URN. The same batched direct/archive body test produced no validated body-to-URN binding. | **Unresolved. Select neither candidate; admit no row.** |

### Deterministic Act 283 selection/preservation algebra

For each of the two exact citation pairs, let `U` be the source-labeled
until-contingency locator and `F` the source-labeled if-contingency locator.
The resolver returns both decisions atomically only when:

1. the exact Act 283, CRC Exhibit E1, and current DWS form bytes, URLs, sizes,
   GET identities, parser-input receipts, and transport receipts all verify;
2. the DWS form observation is not older than the fixed delegated inventory;
3. both citations contain exactly their pinned `U` and `F` node, URN, and
   literal title identities; and
4. the CRC nonoccurrence statement and later DWS federal-only operation remain
   bound to their pinned official bodies.

Then `current(citation) = U`, while `F` remains in evidence and the candidate
frontier with disposition `future_contingent_not_yet_effective`. If any
premise is absent or changed, `current(citation)` is undefined and both
candidates remain unresolved. No rule consults tuple order, entry sequence,
URN prefix/age, first/last position, or another citation's resolution. A later
exact occurrence record can therefore supersede this as-of decision without
losing the official future variant.

### Exact official observations

- **Acts 283, 926, and 447.** The exact official bodies and already-retained
  receipt SHA-256 values are:

  - `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2021R%2FPublic%2F&file=283.pdf&ddBienniumSession=2021%2F2021R` — body
    `3df754fb7c243c620289f2f05a0381a11f2e787a94b6e1998746ee870320b5a0`,
    receipt
    `b90bc97fbb9722a12d724a57fda63d9c95d212fe952a15b97ae2b8fb77331faa`,
    retrieved `2026-08-25T05:02:49.049000Z`.
  - `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&file=926.pdf&ddBienniumSession=2025%2F2025R` — body
    `613ef75651a4e3c5adbb66da1859ad105e6eac1336604a443251a61aa2561353`,
    receipt
    `a1270aa2b2da3e4d26959f48b3d19c37a8c44c48b2f3274673d5729c0a01e55e`,
    retrieved `2026-08-25T05:02:59.179000Z`.
  - `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2019R%2FPublic%2F&file=447.pdf&ddBienniumSession=2019%2F2019R` — body
    `ec6647135cba62e622f3a274e0ef4915837799e3b7e822cf373682763bac80de`,
    receipt
    `88d362698c8b92ff13e9fc10d2557b5d606710c0fed8d2115eb3df233b529a7b`,
    retrieved `2026-08-25T05:02:49.417000Z`.

- **Act 283 status.** CRC Exhibit E1 is
  `https://webftp.blr.arkansas.gov/Home/FTPDocument?path=Assembly%2FMeeting+Attachments%2F630%2F26263%2FExhibit+E1.pdf`,
  body SHA-256
  `09fb6ff50d24402023c3446823629d6830864997fb87bc30ae3348ecb31473b1`
  (150,593 bytes; four pages; PDF created and modified
  `2023-11-03T18:29:49Z`; observed `2026-08-25T08:59:12.523442+00:00`).
  Its exact status sentence is: “According to the Division of Workforce
  Services, this contingency has not been met.” The CRC minutes approving
  publication of current and contingent versions are
  `https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FAssembly%2FMeeting+Attachments%2F630%2F26632%2FExhibit+B+-+Minutes+of+November+14%2C+2023%2C+Meeting.pdf`,
  body SHA-256
  `56e2f3f6879ac58c31562487132f3be76be5f4edd5a0cd2481ae84729f840a65`
  (219,373 bytes; observed `2026-08-25T08:59:26.934697+00:00`).

- **Current DWS operation.** The 2026 UI handbook is
  `https://dws.arkansas.gov/wp-content/uploads/UI-Handbook-2026-Final.pdf`,
  body SHA-256
  `f4d3210c8a1a74e2fcd66b36b6c1bc669146f0e2abdaf430f4a9a50946211fb9`
  (454,956 bytes; 17 pages; created and modified
  `2026-01-14T16:45:42Z`; observed `2026-08-25T08:58:23.973226+00:00`).
  The official withholding form is
  `https://dws.arkansas.gov/wp-content/uploads/DWS-ARK-501_6_Notice_to_UI_Withholding_LPS_4.pdf`,
  body SHA-256
  `00eca78717a0ce162e2d2d778348c2a25fc2f19c6e5da7c84e769ae349d5a40a`
  (141,982 bytes; created and modified `2022-06-20T16:45:20Z`; observed
  `2026-08-25T08:58:24.194870+00:00`). It says DWS “can make a deduction
  for federal income tax only.” The current FAQ's stable official API body is
  `https://dws.arkansas.gov/wp-json/wp/v2/pages/3198`, SHA-256
  `d27b57172805ba319f0c4de3d6552db554b2456335015583e21c6eaf5094aee1`
  (23,083 bytes; page modified `2026-02-05T17:04:50Z`; observed
  `2026-08-25`); the human page
  `https://dws.arkansas.gov/workforce-services/unemployment/faq/` had body
  SHA-256
  `1877374de23ab2fbe7c5b1e7a0331093ad80201b37fdcd5d22523b456e87c60e`
  (258,759 bytes; observed `2026-08-25`).

- **Act 283 retention and restart boundary.** The authorizing ledger already
  retains Act 283 as receipt
  `b90bc97fbb9722a12d724a57fda63d9c95d212fe952a15b97ae2b8fb77331faa`.
  It does not retain the CRC Exhibit E1 or DWS form responses. A restart must
  retain those two exact GET responses prospectively, including a live direct
  DWS observation, then replay all three inputs together. Changed bytes, stale
  or non-live DWS observation, altered request,
  missing HTTP 200/content identity, invalid transport, or incomplete locator
  pairs fail closed. This small evidence step is required, but a fresh strict
  Arkansas materialization must wait for the other five blockers. No response
  was copied from the audit temporary directory into the production ledger.

- **Act 926 implementation trail.** RFP `S000000464` is
  `https://arbuy.arkansas.gov/bso/external/bidDetail.sda?docId=S000000464&downloadFileNbr=14731&mode=download&external=true&parentUrl=close`,
  body SHA-256
  `08784fb336942d28130a9113c79255a2daa93991108c61d255dd156653aff040`
  (383,272 bytes; 25 pages; created and modified
  `2025-09-23T12:42:30Z`; observed `2026-08-25T09:01:16.417313+00:00`).
  It describes the then-current dealer process as manual and schedules EVR,
  ELT, pilot, and acceptance stages. The Anticipation to Award is
  `https://arbuy.arkansas.gov/bso/external/bid/tabulation/summary.sda?docId=S000000464&downloadFileNbr=16617&mode=download&fromQuote=false&docSubType=T`,
  body SHA-256
  `56b445d1da62f3128d204286795cf5871e703331bab65c4ad5fca2aa218e8ba2`
  (99,616 bytes; one page; created and modified
  `2026-02-19T15:51:09Z`; observed `2026-08-25T09:01:16.760526+00:00`).
  The source itself prints “Date of ATA Posting: February 19, 2025”; that
  apparent source inconsistency is preserved, not repaired. The live summary,
  `https://arbuy.arkansas.gov/bso/external/bid/tabulation/summary.sda?docId=S000000464&fromQuote=false&docSubType=T`,
  had body SHA-256
  `514e97428f7f965b540c53a23d9359d587fbb9084c73ead502208144ef951028`
  (53,564 dynamic bytes; observed `2026-08-25T08:57:54.319327+00:00`)
  and status “2BA - Bid Approved (Ready for Vendor Awarding).”

- **DFA rule report.** The latest located monthly report is
  `https://arkleg.state.ar.us/Home/FTPDocument?path=%2FAssembly%2FMeeting+Attachments%2F040%2F27958%2FH.10+Department+of+Finance+and+Administration_08.01.26.pdf`,
  body SHA-256
  `34953866ba559c7e76a09c9ee186c03a3cd15f22af1b7220288841f20637cc73`
  (257,968 bytes; three pages; created `2026-07-31T21:05:39Z`; observed
  `2026-08-25T08:57:39.211455+00:00`). It does not claim that the Act 926
  system was implemented or that the section 12 certification was filed.

- **Act 447 status.** The official Board of Pharmacy/ADH EPCS delay notice is
  `https://healthy.arkansas.gov/wp-content/uploads/EPCS-Review-for-DELAY.pdf`,
  body SHA-256
  `f36e4c1cbd08e6088eb7e43657a4b9a4dcf734c74e8f4c3b5919fad690899c1b`
  (89,344 bytes; three pages; created and modified
  `2020-12-18T19:55:03Z`; observed `2026-08-25T09:02:20.621783+00:00`).
  It quotes the certification condition but is not that certification. On
  `2026-08-25`, the current official AG sitemap index and its page and news
  children contained no matching certification URL:
  `https://arkansasag.gov/sitemap_index.xml` —
  `e6645b4ecb80ebaacca3d5224528cc0b58eac72253d64e7d21c3faaf1d6b1602`;
  `https://arkansasag.gov/page-sitemap.xml` —
  `00c7dc162a6c8e695c3f424621f770df2564489d796887966e67f6bd3a8ee33a`;
  `https://arkansasag.gov/news-release-sitemap.xml` —
  `74bff94fd5a1de499068d1495b011dfc4e9a71e799239f68f74e011ef0d89397`.
  Sitemap absence is search evidence, not proof that the legal event did not
  occur.

- **Identity acts.** Act 419 is
  `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&file=419.pdf&ddBienniumSession=2025%2F2025R`, body SHA-256
  `5507bef690ecffd984e16d83478224912d3e03103cd6a52c3c9fed7c35b149dd`,
  retained receipt
  `b17373e0774a2dce1dac3b9a21cdd5538480b85325dd05f26c0d542cdb8022c6`
  (retrieved `2026-08-25T05:03:01.559000Z`). Act 373 is
  `https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&file=373.pdf&ddBienniumSession=2025%2F2025R`, body SHA-256
  `fa0ad2a4dd3cef14da56065a2cd128caa29cacb4db3eb7544b4a67eecf4341c4`,
  retained receipt
  `7bf39ff6d23152ed8c512ed2e2cd975cc2dccf1657667e83aaa034cb9810a555`
  (retrieved `2026-08-25T05:02:56.388000Z`). Neither act contains a
  delegated URN or otherwise binds one candidate URL.

### Archive and access boundary

The four identity URLs were requested together in one browser context so
same-domain work was not reduplicated; all four reached the same Lexis Human
Verification boundary. The existing shared direct/Wayback/Common Crawl path
was then used only as a bounded fallback. Wayback transport was unavailable;
the Common Crawl helper failed closed because its optional `cdx-toolkit`
dependency was absent, and direct Common Crawl inventory attempts
timed out or disconnected. No challenge was bypassed, no archive body or WARC
pointer passed citation/body validation, and no bytes were admitted. These are
acquisition failures, not evidence selecting either identity candidate.

## Restart preflight and exact residual algebra (2026-08-26)

The retained evidence was rechecked without network access. The authorizing
resolution store remains
`/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/arkansas-current-resolution-evidence-v1/AR`:
65 fetch receipts, 65 content-addressed objects, 65 unique exact URLs, 65
unique body hashes, 29,049,526 retained body bytes, and 130 distinct inodes.
All 65 inputs use the `ArkansasCurrentVariantResolution` parser identity and a
direct transport receipt; every body path, digest, byte count, URL, sanitized
GET, response status, and receipt identity verifies. A canonical audit digest
over the sorted URL/receipt/file-hash/body-hash/size/transport/time tuples is
`e240812dac0d791f92905cd6702c8d2c27e32dc7ac01813cdd2748d73faa3b1a`.

The exact authorizing gaps are:

1. two known Act 283 proof URLs: CRC Exhibit E1 (`09fb6f…`, 150,593 bytes)
   and the current DWS form (`00eca7…`, 141,982 bytes);
2. four known delegated body URLs, one for each exact retained URN in the two
   unresolved identity pairs; and
3. two proof records whose exact locators are not yet source-sealed: one Act
   926 implementation certification, shared by `27-14-802` and `27-14-803`,
   and one Act 447 Arkansas Attorney General certification for `5-64-308`.

Consequently, the currently enumerable exact-URL residual is `2 + 4 = 6`, but
the minimum nonduplicative proof-input residual is `2 + 4 + 1 + 1 = 8`.
The six known URLs do not form the complete proof frontier: the two
certification identities cannot be guessed from their legal descriptions. One
Act 926 certification can close both affected citations atomically, so
counting two separate copies would duplicate work. The Act 283 replay changes
the ledger result from `30 selected + 7 unresolved` to
`32 selected + 5 unresolved`; it does not authorize materialization while the
other five citation boundaries remain.

Global retained-store checks found neither missing Act 283 body hash or URL.
The four-URN root
`arkansas-variant-body-identity-evidence-v1/AR` remains empty, as does
`full-acquisition-evidence-v4/AR`. The older
`full-acquisition-evidence/AR/frontiers/official-catalog-observations/first/89a801dad8e84600e889c06416a7372e3d09e9830729a96e1c7c663c43464df9/AR`
projection has no `receipt.json` despite naming one in checkpoint
`6c44e3293f1eed503b845526b5f92e0f9e04d753bed4ccd0a859af1b2eb4dba0`;
it is not parser-authorizing reuse and cannot reduce a future body residual.
Already-authorizing Acts 283, 926, 447, 419, 373, and 1032 and the GovInfo H.R.
5330 record must be replayed, not fetched again.

The Arkansas delegated body seam now submits the exact frontier once through
the shared plural residual helper, enables one Common Crawl prefix inventory
and plural Wayback prefix inventory, groups/coalesces WARC ranges, disables
legacy per-page Wayback/archive.is after the grouped inventory, and retries
only exact misses without repeating grouped archive discovery. The current
source files are `arkansas.py` SHA-256
`9667a4bf2109fcc4c1f37ed98e69d2fd398b6a74ff9c425fa815259c3eac7bdb`
and `arkansas_lexis.py` SHA-256
`eb7335fdee764c495ffeeb26d9c1465c6bde3860eba3fa5f913ab136a4140929`.
The latter is now an explicit frontier dependency, producing source bundle
`ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas.ArkansasScraper@sha256:a7d971e83edbf525e4e3f96f2bcd8a32fa26b799550d030a782fd3bb00bf11ec`.

## Final bounded certification and identity hunt (2026-08-26)

A final read-only official/live-and-archive hunt found no source-sealable Act
926 implementation certification and no source-sealable Act 447 Attorney
General certification. This is a bounded negative search result, not proof
that either legal event never occurred: a nonpublic filing or letter may
exist. The three trigger-controlled citations therefore remain fail-closed,
with neither candidate selected.

For Act 926, the search rechecked the statutory filing chain in sections 9--12
of the retained official act, the current Arkleg full-document index, Code
Revision Commission meeting attachments through April 9, 2026, the DFA rule
packet and June/August 2026 rule reports, and procurement `S000000464`. The
fresh 2026 rule packet merely republishes Act 926 after the odometer rule, the
monthly reports establish rulemaking status rather than systems
implementation, and the procurement summary still printed `2BA - Bid
Approved (Ready for Vendor Awarding)` on August 26. None is the written Office
of Motor Vehicle certification filed with the DFA Secretary, BLR Director,
and Code Revision Commission that section 12 requires. These sources must not
be used to infer either occurrence or nonoccurrence.

For Act 447, CRC Exhibit E1 still says only that staff contacted the Attorney
General. The official Board/ADH EPCS notice, including exact Wayback capture
`20240929063945` with CDX digest
`BAMTOGPWQQKNEWPAX5POHECNY7VARYNF`, restates the condition but is not the
certification. The current official Board lawbook dated May 12, 2025 still
prints both the `effective until contingent` and `effective on contingent`
versions of section `5-64-308`. Official AG page/news/media and opinion-index
searches, the Arkleg document index, the archived AG letters page, and the
bounded 2019--2023 AG-domain PDF inventory exposed no exact certification.
Dual publication is evidence that the publisher still treats the status as
unresolved; it is not proof that the trigger did or did not occur.

The fixed delegated inventory
`arkansas-delegated-inventory-v6/arkansas-lexis-toc.json` (SHA-256
`af92fd2d12405dfe5246ab50563dc9031180b82c8d0fa0e5336e9580f2085475`)
independently verifies the exact node/URN identities for both candidates of
`19-42-201` and `23-4-909`. No delegated body was requested during this final
hunt. Identity verification narrows acquisition to the four already-known
URLs but does not bind either body to Act 419 or Act 373, so both pairs remain
unresolved.

Future work should not repeat these bounded searches unless a new official
locator, filing index, meeting attachment, or changed delegated body becomes
available. The remaining boundary is source proof of the named legal events
and body identities; it is unrelated to copyright in enacted public law.
