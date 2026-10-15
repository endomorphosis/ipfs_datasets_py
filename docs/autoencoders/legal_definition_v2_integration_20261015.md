# LegalIR V2 definition integration

The existing V2 definition bridge now connects complete markup sampling to
unreviewed FOL/TDFOL definition candidates and the public corpus graph exporter.
This adopts the parallel contribution at
`4e4ea1afa0226c62fdd28e1678cd4046feb90218`; its seven files are preserved exactly
by the attributed import `0ee2872d085f57128b14f952fa1916734522e991`.
The [US Code improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
continues to govern reconstruction, training, graph composition and Lean work.

## What is integrated

The [V2 interface](legal_source_definition_v2.md) binds caller-declared unary
`means` definitions to the complete sampler report, original HTML and acquisition
descriptor. Exact ordered contributors, subspan occurrences, title/section scope
evidence, explicit applicability and open contexts survive into a separate
corpus companion. Boolean lowering is shared with the legacy compiler; its
request and source-validation profile stay distinct.

Public graph export validates the candidate and original inputs before writing
Parquet. `DEFINES` endpoints address existing graph node envelopes. The graph
bundle is insufficient on its own: retain the exact companion, request, report,
full sampler and original source evidence separately.

The shared helper changes producer pins and therefore regenerated report hashes
and downstream candidate CIDs.
Preserve earlier receipts under their original producer generation. Legacy
formula/AST behavior is covered by the affected suites; complete old report
bytes are not claimed identical.

## Qualification

The [raw qualification receipt](evidence/legal-ir-definition-v2-integration-20261015/qualification-v02/receipt.json)
and [independent recount](evidence/legal-ir-definition-v2-integration-20261015/independent_recount.json)
record **732 unique cases across 23 modules**, zero failures/errors/skips, plus
22 passing subtests. All 402 listed local source/test/driver inputs, HEAD and
index remained unchanged during the run. This inventory is not a complete
transitive import closure.

Coverage includes the imported bridge/adapter, affected legacy definition/norm
and review owners, source extraction/sampling, corpus transport, shared and
incremental build contracts, and representability integration. Four new cases
exercise the actual public V2 exporter, fresh-interpreter graph readback on
authored fixtures, separate companion custody and tamper refusal before writing.
Native build gates in these suites use explicit process stubs; they do not
qualify an installed Lean toolchain.

The first attempt stopped before execution because an existing set-based test
parameterization collected in different orders across workers. Its raw failure
and executed driver are retained. The passing run fixes `PYTHONHASHSEED=0` in
the runner without changing product or test behavior.

## Concurrent main reconciliation

Main advanced to `0b3ec5191` with the additive
[source-first sampling review intake](legal_source_sampling_review.md).
A normal merge preserves that contribution and both plan/review-guide updates.
The [combined check](evidence/legal-ir-definition-v2-integration-20261015/reconciliation-v01/receipt.json)
passes **135 cases across six modules**, with zero failures/errors/skips and
405 listed inputs unchanged. It exercises intake, sampler, V2 bridge/adapter,
public export and import controls together; the 732-case run remains separately
attributable to its original generation.

Of the older 402 listed inputs, only `corpus_source_bindings.py` differs, by
standard-library import ordering from main. All seven imported V2 files and all
explicit producer pins in the retained probe remain exact. The intake records
unsigned declarations over all subjects; it does not authenticate them or
substitute for the separate V2 meaning-review contract.

Main subsequently advanced to `a313093cf` with the separate paired-census
quality audit. Its three paths are preserved exactly in a further normal merge;
all 405 tested inputs remain unchanged. This integration does not supply a new
qualification of that audit.

## Retained source probe

The [probe receipt](evidence/legal-ir-definition-v2-integration-20261015/real-source-probe-v02/probe-receipt.json)
records a bounded engineering replay of the original 98,879-byte 2024 title 10
§101 HTML and its original acquisition descriptor. It regenerates the sampler
under the selected producer and verifies the historical record/unit-ref
population is unchanged: **560 blocks, 134 candidate paragraphs, 426 controls
and 3,360 original open context obligations**.

The declaration selects the original title-scope literal and “armed forces”
definition. Its entire post-`means` wording is one opaque unary atom. It does
not infer a six-way union, legal sorts, lexical completeness or governing
applicability. Legal as-of date remains explicitly unknown.

Each FOL/TDFOL candidate has **15 nodes and 26 edges**. Public Parquet export and
same-process disk readback preserve the exact graph; independently retained
companion/input bytes are replayed separately. Each selected component retains
36 open requirements over six physical occurrences. The complete sampler stays
external, including the 558 unselected original occurrences.

All review, source-meaning, context-closure, training and admission flags remain
false. No norm, ground entity, `USES_DEFINITION`, model fit, learned reconstruction
score or actual Lean execution is supplied by this probe. The
[launcher receipt](evidence/legal-ir-definition-v2-integration-20261015/real-source-probe-v02-launch/receipt.json)
binds the passing qualification and frozen inputs, private output/cache,
sanitized application environment and enforced 300-second limit.
The retained initial probe also passed; the second tightens launcher guards for
receipt custody and checkout-root agreement. Their raw results remain separate.

## Next connected component

The subsequent [V2 context and review integration](legal_definition_v2_review_integration_20261015.md)
now qualifies and adopts `8f33492f4a639aa0ee3218653c63e467cd01d3ea`. Its fresh
source/report/subject generation preserves earlier evidence above without
rewriting producer pins. Actual source/meaning reviews and the parallel complete
definition/use contribution remain next. Parent/alignment requests still
require their original identities and request evidence; equal text cannot
substitute for checked correspondence to the standalone sampler.

Obtain actual independent legal/formal decisions for one complete definition,
a source-backed norm/use and a second scope-valid use. Preserve source roles,
applicability, operator semantics, all arguments/qualifiers and disagreement.
Candidate `USES_DEFINITION` edges can be structural declarations with false
authority; statutory admission requires reviewed supported binding evidence.
Qualify scoped resolution, pinned deterministic lowering and actual native
Lean builds separately.

Keep the 8D, 384D and 768D models separate by IR family, schema/version and decoder
task. Reuse retained compatible embeddings and checkpoints with exact lineage.
This engineering path creates neither semantic training gold nor a promoted
teacher; improve the decoder against reviewed targets and matched evaluation.
The historical Hub graph export still requires its own complete lineage repair.
