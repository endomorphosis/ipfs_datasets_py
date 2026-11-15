# LegalIR sampled-source connection to primary sections

Date: 2026-10-15. This continues the [US Code improvement
plan](legal_ir_uscode_corpus_improvement_plan_20261015.md), [source
preparation](legal_ir_cache_source_qualification_20261015.md) and [primary graph
recovery](legal_ir_primary_graph_recovery_20261015.md). It closes one source
transport gap before reviewed LegalIR training and graph composition.

## Implemented connection

The existing `logic/autoformal/legal_span_section_bridge.py` now has an additive
sampled-source profile. Its original cache-based profile expects Git source
revisions. The new profile accepts complete official-source sampling review
bundles with their real edition, acquisition, source-version and occurrence
identities, then uses the existing guarded `PrimarySectionIndex` for exact
literal section nominations. It does not fabricate Git revisions for HTML.

The adapter replays the complete source bundle, binds an independently committed
selection of exact original units and retains every matching primary section
with its source-package and release observations. Canonical-byte replay detects
changed or resealed output, including Boolean/integer substitutions. Bounds
refuse oversized inputs, selections and outputs instead of truncating them.
Selected output size is checked before index lookup. The original bridge's
contract and source-mapping policy remain unchanged.

See the [API and replay guide](../guides/legal_sampling_section_bridge_20261015.md).
These are review nominations. A literal section identifier alone cannot establish
source correspondence, governing applicability or legal meaning.

## Actual qualification

The retained officer-definition/two-use component uses official 2024 Title 10
HTML. All three complete bundles were replayed, including their unselected
subjects. The six selected subjects were already recorded in the original
component, rather than selected from the result of this qualification.

| Official section | Complete review subjects | Selected units | Exact primary section candidates |
| --- | ---: | --- | ---: |
| §101 | 560 | 48, 49, 50, 51: scope, officer definition and adjacent context | 1 |
| §7213 | 26 | 9: operative paragraph | 1 |
| §7214 | 41 | 9: operative paragraph | 1 |
| Total | 627 | 6 units | 3 distinct section nominations |

The index was rebuilt from all **297,825 primary records**: 119,134 nodes and
178,691 edges. Its complete receipt matched the previously retained independent
receipt. The candidate's 716,898,677 bytes were checked by the existing owner
on entry and exit against SHA-256
`46986513582973996e4d69ecf0669ed7331e6cca07ca793f3b1c1ea2dcdec8f1`.
The index receipt seal remained
`82b8099255a93c5a22135229d9bcab8a7a8dd25f09074ca744155734a1d931e1`.
This phase reused the previously qualified primary companion; it did not
reconstruct the original 74 primary shards again.

Every section had one source-package observation and one recognized release
observation, with no primary lookup issues. Every bridge still explicitly
reported unverified edition correspondence and unreviewed governing applicability.
Official edition **2024** and primary release **`us/pl/119/102`** remain separate
identities. Different namespaces do not establish either equivalence or a change
in statutory text. No source-package checksum was substituted for an HTML hash.

All six selected subjects retain six missing context requirements each:
definition, authority, antecedent, shared qualifier, temporal origin and
referenced provision. These are **36 open subject-level context slots**, not
36 independently discovered legal defects. Whole-population counts and pins
remain in each bridge; the original complete bundles remain required external
dependencies. There are zero actual reviews, typed meaning targets, admitted
components or semantic graph assertions. Training and evaluation masks are zero.

## Tests, failed attempt and resources

**119 distinct tests passed** across the new sampled-source bridge and existing
bridge/index suites. They exercise real fixture owners, incomplete and ambiguous
lookups, source/version identity, retained populations, withheld fragments,
tampering, canonical type distinctions and bounds. This qualifies the offline
interfaces; ordinary application startup and supervisor deployment were not run.

The first attempt passed those tests, then failed during full-index insertion
with SQLite `disk I/O error`. Its harness imposed a 1 GiB per-file ceiling below
the existing index owner's 1.5 GiB maximum. The separately retained retry aligned
that ceiling to **1,536 MiB**, retained identical implementation, test, source,
metadata and selection content, and ran only the integration phase. It passed
without an acceptance-rule or scheduler-policy change. Both attempts and the
original driver remain retained; the first failure is not relabeled as success.

| Child phase | Result | Measured wall seconds |
| --- | --- | ---: |
| Run 01: tests | 119 passed | 18.399 |
| Run 01: integration | retained file-limit failure | 13.622 |
| Run 02: integration and replay | passed | 30.272 |
| Sum, including failure | three nonoverlapping phases | 62.292 |

The successful integration's internal index-build timer was 17.009 seconds,
already included in its phase time. Its sampled peak temporary storage was
1,322,213,376 bytes and sampled child RSS was 137,964 KiB; process-lifetime
`ru_maxrss` was 144,084 KiB. The index scratch directory was empty afterward.
These measurements are not model throughput, exclusive hardware occupancy or
amortized training costs.

Both attempts used the existing scheduler's one-CPU, 8 GiB memory reservation
and one-child validation lease. The 600-second wall limit, 450 CPU-second hard
limit and 2 GiB sampled scratch bound stayed unchanged. Sampled RSS limits are
not a kernel memory quota. Both leases were released and policy
`f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661`
remained unchanged. The runtime used captured files from dirty base checkout
`74f5d98c8ffff3c284cffddf430091b5fc4c6f8c`, with exact loaded-module origins,
using minimal namespaces to avoid application package initialization.

The local evidence directory is
`lift_coding/artifacts/legal-ir-sampled-primary-bridge-20261015-01/`.
Its README provides exact commands, source pins, both attempts, replay outputs
and the independent source review. The combined retained-receipt checker passed
183 checks and invoked a further 125 integration-receipt checks. These are
artifact checks, not additional tests or independent semantic validation.

A separate receipt-only provenance supplement passed 133 checks over 17 pinned
files. It verifies all six original component roles and their exact guide,
occurrence, context and source-version joins. These checks are additional
post-run evidence, not assertions retroactively attributed to the runtime driver.

## Next contract gap

The existing sampling-review recorder authorizes evidence only from a subject's
own page. A §7213 or §7214 review therefore still cannot cite the separately
pinned §101 definition/scope bundle through that API. The next bounded extension
is versioned cross-bundle evidence attachment in the existing review owner:
replay complete supporting bundles and bind explicit target/supporting subjects
and roles while preserving all populations, open context and zero training masks.
This operation has not been implemented by the section bridge.

Independent source correspondence, meaning decisions, authenticated review
custody and training admission remain separate. Complete §7213 assignment,
transfer and approval semantics, and §7214 numerical cap, purpose and pronouns,
also exceed the current section-local unary norm compiler. The existing V2
definition-alias adapter does not resolve that grammar gap. No training,
inference, solver, Lean build, signing, publication or backlog-state promotion
was performed in this phase.
