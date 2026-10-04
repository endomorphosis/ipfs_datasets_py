# Initial alignment study and exposed development baseline

The alignment study prepares a source-bound inventory and measures two small
development diagnostics: the current deterministic Legal IR compiler (B0) and
retrieval over cached 384D source vectors (B1). It is the first implementation
increment of the [autoformalization improvement plan](../../../../implementation_plan/docs/49-autoformalization-joint-embeddings-improvement-plan-2026-10-03.md).
Its outputs remain unqualified evidence; they do not establish independent
source fidelity, useful proof coverage, or downstream retrieval-conditioned
generation quality.

The [study adapter](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_study.py)
uses the existing encoder, checkpoint, family, and compiler owners. The
[capability inventory](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_capabilities.py)
keeps declarations, PATH discovery, saved execution records, certificate
support, and current verification separate. The
[asset inventory](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_inventory.py)
records the available model and checkpoint evidence without loading weights.
Inventory status must be read within its stated inspection scope; it does not
establish that an uninspected model or checkpoint is absent.

## Run from the datasets repository root

The [configuration](../../configs/autoencoders/alignment_study_development_v1.json)
names the exposed development study, pinned cached inputs, training-only
retrieval, protected AF-002 protocol bytes, and a bounded resource policy.
Its input paths are relative to the enclosing workspace. In the standard
`lift_coding/external/ipfs_datasets` layout, the CLI finds that workspace
automatically; another layout requires `--workspace-root`.

Use a fresh output directory:

~~~bash
python scripts/ops/legal_ir/prepare_alignment_study.py \
  --config configs/autoencoders/alignment_study_development_v1.json \
  --baseline \
  --output-directory /tmp/alignment-development-run-01
~~~

Choose another path if the example destination already exists. The
[CLI](../../scripts/ops/legal_ir/prepare_alignment_study.py) refuses an existing
directory or symlink rather than replacing prior evidence. Omit `--baseline`
to prepare the inventory and study manifest without measuring B0/B1. An
optional `--expected-config-sha256` binds the operator-selected configuration
bytes before preparation.

The command publishes `manifest.json` with its canonical payload digest and
rechecks the persisted content. Each run uses a new evidence directory;
preserve the original manifest and create a new generation after changing
configuration, input, or implementation bytes. Exit 0 means preparation or
the diagnostic measurement completed. It does not mean quality or production
admission passed. The manifest retains `qualified=false`,
`production_admitted=false`, and the separate primary-evaluation outcomes.

No encoder or autoencoder model is loaded, no provider or prover is called,
no optimizer step runs, and no sealed final-test corpus is accessed. The
baseline uses cached vectors and the synchronous deterministic compiler.
Configured file/row bounds and a cooperative deadline limit the diagnostic;
the deadline is checked between cases and does not preempt an individual
compiler call.

## Corpus and measurement boundaries

The pinned Legal IR panel contains 360 training rows and 120 exposed
development rows. Its targets are **synthetic authored and unreviewed**.
They are useful for regression diagnostics, with separate provenance records,
but have no independent source/target adjudication attestation. Cached encoder
execution is also not authenticated by this study.

The baseline checks source and complete-target group separation before
retrieval. B0 builds its atom vocabulary from training targets only and
compiles each development source without using its target. Scoring reads the
authored reference afterward. The development references do not extend the
compiler vocabulary.

B1 ranks training **source** vectors against each development source vector
and retains five demonstrations. It does not encode formal targets, retrieve
the development counterpart, invoke a generator, or copy a retrieved target
as an autoformalization. Nearest-target copy and facet matches are separate
diagnostics computed after ranking. No complete development target appears
in the training pool, so exact nearest-target copying cannot succeed on this
panel and counterpart recall is not applicable.

## Observed development diagnostics

The initial measured panel gives the following results. Check the manifest of
the particular run for its implementation hashes, timings, row accounting,
and evidence generation.

| Diagnostic | Observed result | Interpretation |
| --- | --- | --- |
| B0 exact authored target | 80/120, or 66.7% | Agreement with synthetic references under the training-only vocabulary. |
| B0 remaining cases | 40 `empty_output` cases | Retained compiler failures; they remain in the completed-case denominator. |
| B1 nearest-target exact copy | 0/120 | Expected for the complete-target groups excluded from training. |
| B1 nearest actor match | 104/120 | Nearest examples often share the actor. |
| B1 nearest action match | 16/120 | Actor agreement frequently accompanies a different action. |
| B1 mean best top-five core-facet fraction | 0.75 | The best retrieved demonstration per query matches three of four core facets on average. |
| B1 mean best top-five seven-facet fraction | 6/7, or 85.7% | Shared empty qualifier facets inflate this average. |

The four core facets are modality, actor, action, and object. The seven-facet
diagnostic also includes conditions, exceptions, and temporal qualifiers.
Empty qualifier agreement supplies three matches without testing the richer
semantics those fields can express. The best-in-five scores use authored
references to assess the retrieved set; they do not represent an available
inference-time selector. These results locate a retrieval mismatch and a
compiler gap. They do not measure RAG generation success or independently
reviewed natural-document fidelity.

The manifest records primary outcomes separately:

| Primary outcome | Status | Needed evidence |
| --- | --- | --- |
| Independently adjudicated source fidelity | Unavailable; value remains null | Candidate-blind source/target review on independently grouped material. |
| Native-checker-accepted useful proof coverage | Unrun; value remains null | Faithful statements and actual scoped native proof/checker receipts. |

## Encoder and proof dependencies

The user-confirmed 768D producer is
[`Alibaba-NLP/gte-multilingual-base`](https://huggingface.co/Alibaba-NLP/gte-multilingual-base).
That producer identifies the multilingual **encoder**. It does not identify
a trained 768D autoencoder or source-decoder checkpoint. Those downstream
weights, compatible native vectors, lineage, and replay receipts require
their own inventory and admission. Preserve the independent 8D, 384D, and
768D paths described in the [autoencoder handbook](README.md) and
[parallel lane contract](parallel_lineage_execution.md).

The inspected local Leanstral GGUF metadata reports a **4096D** native hidden
width. Its metadata prefix is read within a byte limit without reading model
tensors. A cache manifest's declared full-model digest remains distinct from
a freshly verified full-model hash. The current runner is configured for chat;
the hidden-state embedding experiment has not run. Generation and embedding
experiments require separately admitted residency, pinned tokenizer/template
and backend identities, and actual numerical capability receipts. Catalog
proof support and saved historical receipts do not establish current proving
or embedding quality.

## Evidence to extend before qualification

The manifest binds the listed study/core source files and configured input
provenance. Its dependency scope is explicitly
`listed_study_and_core_source_files_only`, with
`complete_dependency_manifest=false`. It is not a complete transitive
dependency closure. An independent reproduction or qualification must extend
those bindings to the actual encoder, numerical, compiler, parser, and checker
dependencies used by its claimed scope.

The next study increments should obtain independently reviewed source facets,
test semantic hard negatives, compare raw and learned representations under
the same retrieval envelope, and then measure generation and bounded repair.
Keep exposed development separate from the protected AF-002 final test.
Changing alignment heads, model weights, or retrieval indexes creates a new
study/evidence generation with fresh validation of the applicable scope.
