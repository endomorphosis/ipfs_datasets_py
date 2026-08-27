# State-laws candidate conflict audit: CT, HI, IA, and ME (v1)

Date: 2026-08-26 UTC  
Branch: `feature/legal-corpora-reindex`  
Status: **CT resolved by a digest-pinned assembler manifest; exact-51 map remains blocked**

## Scope and decision rule

This read-only audit covers every distinct assembler-eligible canonical
artifact/normalized-receipt pair for the four conflicted jurisdictions in
`legal-corpora-reindex-20260824`. A candidate is not preferred merely because
its file is newer or larger, or because it has more rows. Selection requires a
source-derived full frontier, retained parser-input provenance, zero-network
replay, exact canonical identity parity, and source-software identity consistent
with the strict parser contract that would certify the corpus now.

All ten normalized receipts use
`state-laws-sparse-graphrag-release-schema-v2` and
`state-laws-legacy-v2-adapter-v1`. Their corresponding raw completion receipts
have verified official authority, `mode=full`, `edition=2026`,
`legal_as_of=2026-07-01T00:00:00Z`, and
`public_law_no_state_copyright` statutory-text admission. Each raw receipt's
SHA-256 equals its content-addressed filename. Each candidate also reports:

- `state-laws-multifetch-frontier-aggregate-v1` aggregate closure;
- `state-laws-multifetch-acquisition-v1` parser-input coverage with zero
  uncovered units;
- equal first/replay frontier digests and `replay.closed=true`;
- canonical-key parity with no stale keys; and
- a non-synthetic, official multi-fetch request/response ledger.

Those shared gates make the pairs assembler-eligible. They do not by themselves
resolve semantic parser repairs between distinct candidates.

## Complete candidate identity matrix

The `receipt SHA-256` column is the digest of the serialized normalized receipt
file. `Raw receipt SHA-256` is its `legacy_receipt_sha256` completion receipt.

| State / generation | Observation (UTC) | Rows | Canonical artifact SHA-256 | Normalized receipt SHA-256 | Raw receipt SHA-256 | Source-software SHA-256 |
|---|---|---:|---|---|---|---|
| CT v11 | 2026-08-24 20:05:53 | 28,187 | `e52bfadbb42b91839fa7c098a56c0b80ac1bcf983e6899c8bc8b541025636051` | `dce50990c0db6d674e8ce7a82fda148990d2ce9f9c4355b27d769504b713d349` | `f61acd197012286e35200707b859b75fdc72ab7988d405c595c284c168d0f626` | `3ed7874c8f6569d40555cb6edc16f1ad523654a5c24b6f9295c77e75bd1be13c` |
| CT v12 row-binding | 2026-08-24 20:42:54 | 28,187 | `6293dcfc4284b91899dca0bc3a8cf1a10f7423617bed85d3a3b3d79ca85628eb` | `c2bbe2475257648b16d6b5516848642b1d8cb64992bdc06325638f9a535a7ace` | `650a7131fb0f794141b2b8c24b6c9c3d952f3c0018480ebd7c4cccca91b907aa` | `3ed7874c8f6569d40555cb6edc16f1ad523654a5c24b6f9295c77e75bd1be13c` |
| HI standalone v7 | 2026-08-24 22:33:53 | 21,616 | `81209663d1821ceb5f877a63002b6c26c6bf05a7d2df0d71064d87e413a13138` | `9f32ad006b96ee76de1261b78e8fdd171a4e21b0cad27cd5bf0af24c75fa603c` | `de1b6a7ad28b9b6377aeb4830942eae8cd2ebbf98a03d19360c2918549eda1f9` | `deed0a78091789af98169c86fbed90b308ea02d85bee2c328cabc64d1504d527` |
| HI v8 | 2026-08-24 23:27:50 | 21,948 | `53d7fad503dc9d74cb7d8418fb3d5948b6ef6e6d16796e3a2dcdbbb256ec505b` | `ba7f01fc014f7fa83102f896bef3c952c7af2602df0aeb6b68353ce485341df0` | `2ebe82fe577215a7677c088b4276344868e79d4bb9aa676e226aed9515df5b30` | `b3c6aa78273f3379bb0d7c4b5faaa1e2de90faad1c87c7dd87e45ee93d2ad6a7` |
| HI v9 exact inventory | 2026-08-25 00:15:49 | 22,600 | `6b80ff35f7ade393de70df2a2a0467ad8d1ca9b631817886c3f05bca474f63ae` | `2278d278629800ff9b9c274685e6bf1e8263037c7081a0cb515b8fdc8a32ca90` | `6bdd051593efe58d2166145ff5fa6e4d046a5cc5f39fbca918d4fb74407f7550` | `22cc6883e754d821e3e0bf691763c2381dba8f7ced2482febb8caff2e500dd5c` |
| IA v5 | 2026-08-24 19:21:17 | 28,216 | `5b8a0e83f99424ac9248262ac810d0257ec3f2838a2836c5b1f320a31155b60d` | `258c2873898a3760a08898c5d38bd4475d3982b1c60cc0e84935b43be14302ac` | `2f053ecb878795b3c0ffd8319a5b46961b1cffd1b01fd4c69ad1594f18561d75` | `2b0c54a47f5dda60a459f72f546d63f7e9d36d8aa3f31b8a5020f9d65da9932c` |
| IA v6 content-addressed | 2026-08-24 20:16:45 | 28,216 | `5b8a0e83f99424ac9248262ac810d0257ec3f2838a2836c5b1f320a31155b60d` | `ee274e73d69fe3cf0d3afba4126406d95b12a4f439f7486b54a02792dbd29a78` | `709177cc160599fb0ae596a4a4512f0db00d2fee8b7c64f85a6cb33f9878e7c9` | `95e0eb1cff512546540bdbd4bc99e8fc0f0114b0962b067977cfe040a139da8b` |
| ME shard-c v6 | 2026-08-24 21:44:19 | 20,287 | `ba88e09bb3aa23c44ec1391a28590c4c80fc8efb7b1566b00200adb571084fd7` | `237a755e6878a89d8ad2133a4fc4f2258febd3a7622f5af1cb72bed16cbff772` | `4f48fdf2332b6f5ab79617c1812986d3c06bdfb1257324f9427a42732584b381` | `4b81d57fe50469747b3d004e9489759c80849116d42937787ff5dd20f389d3cd` |
| ME v7 | 2026-08-25 07:19:32 | 20,310 | `e8286cd62a99bfe4e2695ce95ea454747aa5bbf66973c33f72c937aa49d0d2d5` | `1e8ec7cf8aa7bd2139bb7abbba87536b9876cdb43d3ec732643e71023a016734` | `7a7d70d8600ddbf4f0256d20a968ec2964d0a6ac97b87aa93418ca848cad3010` | `4b81d57fe50469747b3d004e9489759c80849116d42937787ff5dd20f389d3cd` |
| ME v9 | 2026-08-25 08:22:36 | 32,786 | `643c84741c7da790b9b78889fd37611cc9bf4872712ec2e1756429e7f8a190ad` | `f91335ca6604bee5b6c8a8b3ad1351bbf776161471ea502ef97f7733f29350d6` | `0307422d8a08c93bc1c9c1f6317c46887612c790063494135dc0d24d3a4fe2a6` | `ca3809e63cc00654d96fa4bd2597939b5767d7e942ed4ccb945aedf11e6dd262` |

## Source and closure provenance

| State | Official root / release point | Catalog units | Retained parser inputs | Evidence-supported result |
|---|---|---:|---:|---|
| CT | `https://www.cga.ct.gov/current/pub/titles.htm` / `3ae72a8966688cdb0badc03e06ca91d43bfe4065a7573e3096bc821e55bc4c5d` | 83 base units plus 59 supplement units; Titles 2a and 2b typed reserved | 1,642 | v12 is the supported candidate |
| HI | `https://www.capitol.hawaii.gov/hrscurrent/` / `a135463226c598784e16fc7e47384b67215b58446e36951de8a2d67d8919deb5` | 38 title units | 24,393 | v9 is the supported candidate |
| IA | `https://www.legis.iowa.gov/law/statutory` / `29720216be7e14360867f5d1b4baf4ca79debaf63bddf3a6006f57450db60207` | 16 title units | 3,795 | v6 is the supported receipt for the shared artifact |
| ME | `https://legislature.maine.gov/statutes/` / `04b82d21df091d11c96d72abee15c7f591bb1467299b22194684d911638dda45` | 64 title units | 48,749 unique current-frontier inputs; the retained ledger has 48,786 observations because 27 endpoints have 37 digest-identical duplicates | strict repair implemented; retained-only replay pending, so no current candidate yet |

### Connecticut

Both CT receipts bind the same exact current source-software identity and the
same retained request/response ledgers. The distinction is canonical row
provenance: v11 has zero rows with serialized `structuredData`; v12 has all
28,187 rows bound to an exact `content_sha256` and transport receipt. The v12
receipt is the later row-binding replay, not a row-count preference. If all four
conflicts later close, the supported CT digest pair is:

- artifact: `6293dcfc4284b91899dca0bc3a8cf1a10f7423617bed85d3a3b3d79ca85628eb`
- normalized receipt: `c2bbe2475257648b16d6b5516848642b1d8cb64992bdc06325638f9a535a7ace`

A fresh streaming comparison makes the selection basis exact rather than
temporal. Removing only v12's `structuredData` member from each row produces
28,187/28,187 dictionaries identical to v11 in the same order. Both projections
have SHA-256
`baa6291add7722aa78c569770813382efd55b7482f6db3da3dee7d27c6eed50b`.
The v12 artifact has 28,187 unique `@id` values and 28,187 unique source URLs.
Every row has exactly the two row-binding fields `content_sha256` and
`transport_receipt`; all 28,187 digest pairs agree internally, all receipt URLs
equal the defragmented row source URL, and every pair is present in the retained
transport ledger. There are zero missing bindings, malformed digests, URL
mismatches, or ledger misses.

The common retained acquisition contains 1,642 unique request receipts, 1,642
unique official URLs, and 1,642 unique response bodies. Every receipt filename
equals its embedded acquisition-receipt SHA-256; every retained object verifies
against its filename, envelope, transport receipt, and response content digest.
The v11 and v12 request ledgers are byte-identical at
`3b167b3a9e7e5418f593cf0ddf2679909136e1d92e96c8e87924209b6db1121a`;
their response ledgers are byte-identical at
`fcdf471db68f58f39d78c6f018e29350bf0d8c51b4cfff217ec8cccdb55864ec`.
The current registered CT bundle remains
`ConnecticutScraper@sha256:3ed7874c8f6569d40555cb6edc16f1ad523654a5c24b6f9295c77e75bd1be13c`,
which is exactly the source identity on both receipts. Thus v11 is retained as
historical evidence for the same substantive parse, while only v12 satisfies
the current row-provenance representation.

The machine-consumed
`state_laws_exact51_candidate_selection_v1.json` now pins only that v12 pair
under schema `state-laws-production-input-map-candidate-selection/v1`; its file
SHA-256 is
`b27413a0301e6de42d1e3449070eaeea7d7afbd9faf70c7161cf5fb1bd35530f`.
The assembler still independently requires the current registered source
bundle and replays the shared adapter checks, so this control is neither a
historical-source bypass nor a generic preference rule.

A guarded current-bundle union preflight over the retained production root
loaded that exact manifest and observed two eligible CT pairs but exactly one
digest match. It selected the v12 path and receipt above at 28,187 rows under
the registered `3ed7874c…` bundle. CT disappeared from
`conflict_jurisdictions`; both candidate-selection mismatch lists were empty,
as were the invalid-receipt, invalid-artifact, source-software-mismatch,
symlink, special-file, and unexpected-jurisdiction blockers. The incomplete
scan selected 24 jurisdictions and still reported 27 missing, so
`exact_51_ready=false` and no production input map was written.

### Hawaii

The current Hawaii closure binds both `hawaii.py` and `hawaii_section.py`,
requires exactly 22,600 operative sections, and requires operative inventory
SHA-256
`493351e0c442c5918e149af2cd16f5e1799267eb140605b8f62912bae5e61abe`.
The v9 source-software identity is the exact current source-bundle identity.
Independent recomputation from the v9 artifact's 22,600 unique source URLs and
canonical statute identities produces that exact inventory digest. v7 and v8
do not satisfy the exact count or inventory. The supported HI digest pair is:

- artifact: `6b80ff35f7ade393de70df2a2a0467ad8d1ca9b631817886c3f05bca474f63ae`
- normalized receipt: `2278d278629800ff9b9c274685e6bf1e8263037c7081a0cb515b8fdc8a32ca90`

### Iowa

Both IA receipts bind the exact same 28,216-row artifact and identical retained
request/response ledgers. v6 is not preferred by timestamp: it adds the exact
edition/legal-as-of/source-path acquisition metadata absent from v5 and binds
the sibling Iowa XML parser into the source-software bundle. Its source identity
is the exact current bundle identity. The supported IA digest pair is:

- artifact: `5b8a0e83f99424ac9248262ac810d0257ec3f2838a2836c5b1f320a31155b60d`
- normalized receipt: `ee274e73d69fe3cf0d3afba4126406d95b12a4f439f7486b54a02792dbd29a78`

### Maine repair pending retained replay

ME v9 is neither selectable because it is newest nor because it has the most
rows. Its receipt source identity predates the current bundle, which now binds
`maine.py`, `maine_section.py`, the shared strict retained-replay helper, and
exact source-bound terminal classification. The bundle digest must be computed
immediately before the replay because the shared helper is still under active
strict-lifecycle development.

This is observable semantic drift, not a theoretical version mismatch. The v9
artifact admits the following six rows as operative:

- Title 14 § 556-2 and Title 34-A § 4102;
- Title 22 §§ 1553-A-2 and 1716-2;
- Title 36 § 4365-F-2; and
- Title 29-A § 2354-E.

Replaying their already-retained official HTML through the current parser types
the first two as `repealed`, the next three as `repealed_effective_dated`, and
the last as `never_effective`; all six return no operative statute. Because the
receipt declares a legal-as-of date of July 1, 2026, selecting v9 would preserve
known nonoperative rows. v6 and v7 predate still more parser repairs and cannot
substitute for it.

The repaired lifecycle derives exactly 48,749 unique inputs: one root, 64 title
indexes, 2,910 chapter indexes, and 45,774 section leaves. It requires a second
uncapped traversal using retained inputs only, zero network requests, equality
of first/replay frontier digests, ordered canonical parity, typed exclusion of
the six rows above, and row-level content/transport evidence. The 48,786 ledger
observations must remain unchanged; their 37 extras are duplicate observations
for 27 endpoints with identical request, response, status, and content digests.

ME must therefore be replayed from that retained frontier with the final current
source bundle, producing a new canonical artifact, completion receipt, and
normalized receipt. No reacquisition is required unless retained replay exposes
a missing input or frontier residual.

## Fail-closed outcome

Three choices are evidence-supported. The assembler's current-source-software
gate now rejects obsolete candidates before selection, making HI v9 and IA v6
automatically unique. Both CT candidates bind the same current source bundle,
so CT is the sole conflict that needs explicit curation; the checked-in
digest-pinned manifest now supplies exactly that v12 selection without deleting
or rewriting v11. Every existing ME candidate is rejected as stale; ME is now a
missing jurisdiction until its current-bundle retained replay seals a replacement
pair.

The checked-in manifest is an exact-51 production selection control whose
`states` object intentionally contains only CT; unlisted jurisdictions retain
the assembler's unique-current-candidate rule. It does not authorize writing an
incomplete production input map. Missing jurisdictions must still close, and a
later distinct current-bundle candidate would still fail closed unless separately
audited and digest-pinned. This report authorizes no indexing, upload, or
publication.
