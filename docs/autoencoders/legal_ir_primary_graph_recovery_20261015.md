# LegalIR primary graph recovery and navigation export

Date: 2026-10-15. This continues the
[US Code improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
and [cache/source qualification](legal_ir_cache_source_qualification_20261015.md).
It strengthens the data layer needed before reviewed LegalIR training and a
unified Lean corpus. It measures structural transport, not decoder accuracy or
legal validity.

## Recovered cause evidence

The newer materialized entity cache has 238,452 node rows and 1,722,395 edge
rows; every edge lacks both endpoints. The retained primary snapshot contains
74 current manifest-selected shards plus 407 unselected historical shards.
Arithmetic over its retained footer inventory gives:

| Population | Manifest-selected current rows | Historical extra rows | All-prefix rows |
| --- | ---: | ---: | ---: |
| Nodes | 119,134 | 119,318 | 238,452 |
| Edges | 178,691 | 1,543,704 | 1,722,395 |

The historical publisher enumerated files by prefix. It also searched for
`node_cid`/`id` and `src`/`source`/`dst`/`target`, while current wrapped graph
records declare `entry_cid`, `source_entry_cid` and `target_entry_cid`. A retained
legacy edge witness already has blank endpoint fields. These are distinct
failure mechanisms: fixing wrapper extraction cannot recover values absent in
legacy source records.

The population match supports mixed-generation contamination, but the exact
later twelve-field `kg-logic-index.parquet` writer and execution binding remain
unrecovered. The historical writer emits a different ten-field file. No
occurrence-level equivalence or semantic duplication of the two populations is
claimed. The original malformed export remains intact.

## Additive implementation

The new `logic/autoformal/legal_primary_graph_navigation.py` reuses the existing
manifest, record decoder and complete reconstruction owners. It selects only
manifest-declared shards, retains actual IDs and pairs the existing twelve-field
navigation schema with full primary records and source provenance. No endpoint
is guessed from a label, citation or row position.

The new bundle contains `primary-records.jsonl`, `reconstruction.json`,
`navigation.parquet` and a manifest published last. The writer refuses incomplete
or conflicting selected populations. The validator independently replays the
original source and compares every navigation row to the complete companion;
rehashing changed outputs cannot replace source evidence. Finite resource bounds,
exclusive creation, descriptor checks and owned-file cleanup apply. See the
[API guide](../guides/legal_primary_graph_navigation_20261015.md).

All `in_formula`, `admitted` and `formalized` fields remain false. The companion
preserves parsed original properties and custody, including each edge's own ID.
Exact original JSON bytes remain in the required pinned source shards. The
navigation table alone is not a lossless exchange or an accepted semantic graph.

## Source and execution scope

Primary source repository: `justicedao/ipfs_uscode`, revision
`5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`, declared release point
`us/pl/119/102`. Exact selection:
`83c8fb05b4a0435486dff800297674a8433dd4af7dcfd50beae85a8490f2a330`.
The selected source contains 46,241,258 bytes across 74 verified files.

Runtime modules were captured from the existing dirty checkout at base commit
`74f5d98c8ffff3c284cffddf430091b5fc4c6f8c`, with the new additive adapter/tests.
Actual loaded origins and file hashes are retained. This is not relabeled as the
published planning snapshot `234dc97a2fedb864c99add7f0d8e37ba81c785cf`.
Minimal namespaces avoid application package startup; the qualification concerns
these offline owner APIs, not ordinary package startup or supervisor deployment.

All full scans and focused tests use the existing shared scheduler's validation
lease with one CPU, 8 GiB memory reservation and one child slot under unchanged
policy `f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661`.
Kernel CPU/per-file limits and sampled RSS/temp guards have different meanings;
sampled guards are not a kernel memory quota. CPU affinity and a prelaunch idle
sample do not guarantee exclusive hardware. No model, solver, training, native
Lean build, download, upload, service change or task-state mutation is involved.

The first primary replay reached its 300-second wall ceiling and remains a
failed attempt. Its retry used a separately recorded 600-second wall budget and
another allowed CPU, retaining the same inputs, owner code and acceptance
checks. The retry reconstructed all 716,898,677 candidate bytes exactly, including
SHA-256 `46986513582973996e4d69ecf0669ed7331e6cca07ca793f3b1c1ea2dcdec8f1`.
The retained report also matched exactly. All primary attempt phase times,
including the failure, total 541.133 seconds; that is a sum of measured phase
wall times, not CPU consumption or an overall parallel-campaign clock.

The first new test run had 34 passes and one incorrect expected dictionary: the
existing census retains zero-valued unresolved/ambiguous categories. Correcting
that assertion produced **35 passing focused cases** in 1.99 seconds without
changing the intake contract. The tests include real source reconstruction and
replay, exact IDs, unknown kinds, conflicting records, altered/resealed outputs,
resource bounds, atomic manifest publication and preservation of foreign files.

## Complete new-bundle results

The new export and its separate complete source replay both passed. The existing
v2 entity-index census then independently scanned the entire output table:

| Observation | Result |
| --- | ---: |
| Navigation rows | 297,825 |
| Node rows, all with declared IDs | 119,134 |
| Edge rows with unique declared endpoints | 178,691 |
| Missing / dangling / ambiguous endpoint edges | 0 / 0 / 0 |
| Duplicate node IDs / duplicate navigation rows | 0 / 0 |
| Rows with `in_formula`, `admitted` or `formalized` true | 0 |

Navigation Parquet: 59,090,677 bytes, SHA-256
`45c173bfe5a83a222eae6f0e15743635e0f7ad72c4a34b8f23d5a20033b5b930`.
Bundle manifest SHA-256:
`8cdec69ca63f511c194f3ea66d68e25a6c9ef1670006a58f7f4fa2725142ef5c`.
The paired primary candidate matches the original bytes and report exactly.

| Navigation phase | Parent-observed wall seconds | Peak sampled child RSS (KiB) |
| --- | ---: | ---: |
| Initial failed test attempt | 2.287 | 122,468 |
| Corrected focused tests | 2.305 | 120,972 |
| Full source reconstruction and export | 123.410 | 134,756 |
| Independent complete source replay and row comparison | 111.523 | 109,600 |
| Complete endpoint census | 11.169 | 93,696 |

All leases were released, policies stayed unchanged, and captured live source
hashes still matched after execution. The maximum sampled temporary allocation
for the navigation replay was 822,442,144 bytes and drained after the phase;
retained test fixtures are separate. Phase times include child startup and
monitoring. They are not hardware benchmarks or evidence of autoencoder speed.
The standard-library artifact checker passed **70 checks** over small pins,
receipts, sizes and arithmetic; it does not itself repeat graph-body validation.

The census records 26 historical ontology-hint disagreements because this
export deliberately leaves `CITES.in_formula=False`. Two node categories remain
unclassified. Both observations are retained rather than hidden or converted
into admission claims.

## Remaining semantic and provenance gates

- The 119,134-node/178,691-edge primary population is a separately qualified
  current generation. It is not a repaired replacement for all legacy rows.
- Its 13 unresolved citation nodes and 13 `CITES_UNRESOLVED` edges remain
  unresolved, even though their declared endpoints exist.
- Code and release-point kinds without a registered category stay unclassified;
  no default mapping manufactures legal meaning. Citation labels grant no
  formula or training authority.
- This release and the separately prepared official 2024 officer-definition
  review packet have distinct version identities. Text or section-ID equality
  cannot establish their governing edition correspondence.
- Actual definition/norm interpretation, occurrence-level scope binding,
  independent reviews, semantic graph assertions, training targets and compatible
  Lean lowering/builds remain open. Transport correctness does not train a model
  or establish legal meaning.

Continue the existing LIR backlog with the prepared source-review owners and
explicit edition/scope correspondence. Preserve the current source graph as a
navigation layer; introduce reviewed semantic assertions through the existing
typed graph owners. The backlog's statuses are not changed by this report.

## Evidence location

`lift_coding/artifacts/legal-ir-primary-graph-recovery-20261015-01/` contains the
lineage investigation, both primary attempts, captured source owners, independent
review, both navigation attempts, qualification driver and receipt checker.
The original cache/source qualification directory and original reconstruction
artifacts are retained unchanged. The root README records exact reproduction
commands and final new-bundle validation results.
