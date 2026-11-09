# Autoencoder inference and training handbook

**Current LegalIR handoff:** [autoformalization guide](../../ipfs_datasets_py/logic/autoformal/README.md) and [current state](../../ipfs_datasets_py/logic/autoformal/docs/HANDOFF.md). Source, review, graph, Lean and LegalIR model guides are maintained beside the autoformal module; this document retains its existing model guidance and dated research history.

Use this handbook to choose a supported execution path, prepare its inputs,
run or resume it, and interpret the evidence. Its core API baseline is dataset
commit `3666ebad19422b8345ebe5432a1c02f26d2eba4c` (2026-09-29), with the
[UI DOM/IDL training additions](ui_datasets_and_bindings.md) dated 2026-09-30.
Examples and defaults
belong to their named backend; they are not interchangeable across backends.

## Choose a task

| I need to… | Start here |
| --- | --- |
| Improve US Code autoformalization and reuse prior artifact work across 8D/384D/768D/4096D | [Canonical home](../../ipfs_datasets_py/logic/autoformal/README.md), [current handoff](../../ipfs_datasets_py/logic/autoformal/docs/HANDOFF.md), [Canonical source→span→graph→Lean execution plan](../autoformalization/legal_ir_text_to_lean4_execution_plan_20261018.md), [submodule landing snapshot](evidence/legal-ir-text-to-lean4-plan-20261018T221630Z/reuse-landing-map.csv) |
| Replay selected normative Legal384/768 states on their original or separately bound retained native caches | [Original cached replay](../../ipfs_datasets_py/logic/autoformal/docs/guides/normative_legal_ir_runtime.md), [retained native caches](../../ipfs_datasets_py/logic/autoformal/docs/guides/normative_cached_legal_ir_runtime.md) |
| Replay both retained and balanced normative wording banks in one private trainer | [Dual-bank training adapter](dual_bank_wording_training_adapter.md) |
| Reconcile other agents' branches, findings and decoder progress | [Shared progress and formalization priorities](progress_integration.md) |
| Select a version across Legal, Security, Intent and UI/UX | [Versioned runtime interface](versioned_runtime_interface.md) |
| Inspect required logic families, decoder losses and Lake coverage | [Logic output requirements and inventory](logic_output_requirements.md) |
| Validate Legal conditions/exceptions or request/token UI confirmations before training | [Legal/UI qualifier coverage and v7/v5 entry points](legal_ui_qualifier_coverage.md) |
| Check Intent preconditions, updates and effects against a finite state model | [Guarded Intent projections and training](native_guarded_intent_training.md) |
| Obtain formal ASTs or reconstruct native expressions from model scores | [Formal logic decoders](formal_logic_decoders.md) |
| Train native categorical decoders and check actual outputs with Lake | [Native formula training](native_formula_training.md) |
| Train a source-only learned formula decoder | [Learned legal formula training](learned_legal_formula_training.md) |
| Load the source-span decoder through the shared runtime with its exact checkpoint and latent controls | [Source span LegalIR runtime](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_span_runtime.md) |
| Authorize every declared input against a frozen split manifest before consuming a batch | [LegalIR split membership](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_ir_split_membership.md) |
| Bind a complete zero-latent source-span batch to target eligibility, exposure declarations and split policy before an explicit consumer runs | [Source-span consumer input binding](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_span_consumer_binding.md) |
| Construct or resume a zero-latent source-span checkpoint after both bound input batches and checkpoint identity pass preflight | [Bound source-span training](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_span_bound_training.md) |
| Inventory selected paired cache manifests and preserve verified payloads as source-bound or unresolved candidates | [Manifest inventory](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_paired_manifest_inventory_v1.md), [payload intake](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_paired_payload_intake_v1.md) |
| Replay legacy paired source candidates into source-only review requests and signature subjects | [Legacy source review](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_review.md) |
| Validate signed legacy-source answers and retain unresolved or differing declarations | [Typed legacy source responses](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_responses.md) |
| Bind and authenticate a separate common adjudication declaration while source decisions remain pending | [Legacy source adjudication](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_adjudication.md) |
| Bind the complete declared review population and exclude source reviewers across requests and banks | [Legacy source-review cohorts](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_cohort.md) |
| Separately authorize nine candidate answer references after application-time source and adjudicator checks | [Legacy source application](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_application.md) |
| Replay declared answer-snapshot revisions and refuse current use across visible forks | [Legacy source history](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_history.md) |
| Authenticate exact candidate stored-source tuples while keeping legal applicability and governing adoption separate | [Legacy source bindings](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_legacy_source_bindings.md) |
| Prepare complete official statutory source units and open context | [Whole-source sampling](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_sampling.md) |
| Record source findings and meaning proposals against the complete source population | [Sampled-source review intake](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_sampling_review.md) |
| Bind typed role, scope and coverage proposals for an exact norm candidate to signed response-body evidence | [Typed norm interpretation responses](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_norm_content_responses_v1.md) |
| Prepare complete unsigned norm and definition-use proposals over retained evidence | [Unsigned norm content declarations](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_norm_content_declaration_v1.md) |
| Bind retained declarations to current norm generations with explicit obligation correspondence | [Norm declaration generation binding](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_norm_content_declaration_binding_v1.md) |
| Authenticate separate common choices over complete typed norm answers while decisions remain pending | [Norm content adjudication](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_norm_content_adjudication_v1.md) |
| Authenticate exact nominated-use definition applicability statements while governing use remains pending | [Norm definition applicability](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_norm_definition_applicability_v1.md) |
| Prepare conditional unary-definition instances at exact original bound-variable occurrences | [Bound-variable definition instances](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_bound_variable_definition_v1.md) |
| Bind authenticated exact-use applicability custody to an unverified conditional instance | [Applicability-to-instance binding](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_norm_definition_application_binding_v1.md) |
| Compile explicit V2 definition declarations into candidate graphs | [V2 source definitions](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_definition_v2.md) |
| Bind explicit V2 definition candidates to exact source-review subjects | [Sampled-source definition binding](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_sampling_definition_binding_v2.md) |
| Compile exact sampled-source V2 definitions and retain separate native receipts | [V2 definition native builds](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_source_sampling_definition_lake_v2.md) |
| Prepare and authenticate exact V2 definition review evidence | [V2 definition context and review](../../ipfs_datasets_py/logic/autoformal/docs/guides/corpus_definition_review_v2.md) |
| Connect explicit V2 definitions through an assumed alias and separate combined review | [Active definition-use integration](../../ipfs_datasets_py/logic/autoformal/docs/guides/definition_use_v2_integration.md) |
| Compile six-module V2 use components and check conditional Lean theorems | [Conditional definition-use native builds](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_native_v2.md) |
| Check concrete serialized native AST values against their Lean denotation and existing emitted formula | [Native AST preservation](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_native_ast_preservation.md) |
| Check all four V2 corpus fragments against their original declarations under the corpus interpretation | [V2 corpus preservation](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_preservation_v2.md) |
| Replay complete retained V2 preservation packets against current source and review inputs | [Retained corpus packets](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_preservation_packet_v2.md) |
| Persist and retrieve retained corpus observations with exact keys and no proof authority | [Observational corpus index](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_preservation_index_v2.md) |
| Bind retained theorem headers, explicit premises and import artifacts to typed engineering candidates | [Typed theorem lineage](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_preservation_theorem_lineage_v2.md) |
| Prepare and observe exact original/alias kernel types in a clean V2 corpus build | [Native theorem-type elaboration](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_preservation_elaboration_v2.md) |
| Replay retained types into closed kernel claims and planned typed theorem requests | [Closed kernel claims and planned requests](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_corpus_definition_use_preservation_kernel_claims_v2.md) |
| Preserve and train the old 8D linguistic/IR feature decoder | [Legacy linguistic training](../../ipfs_datasets_py/logic/autoformal/docs/guides/legacy_linguistic_training.md) |
| Reproduce the September 17 teacher and prepare screened distillation targets | [Historical teacher fidelity, fixes and performance](../../ipfs_datasets_py/logic/autoformal/docs/guides/legacy_teacher_fidelity.md) |
| Transfer screened teacher evidence into separately embedded 384D formula training | [Teacher-to-student preparation and smoke](../../ipfs_datasets_py/logic/autoformal/docs/guides/teacher_student_transfer.md) |
| Detect actor shortcuts and compare balanced formula training data | [Actor composition and free-running evaluation](actor_composition_evaluation.md) |
| Improve 8D feature updates and compare 384D reconstruction profiles | [Separate reconstruction-training paths](../../ipfs_datasets_py/logic/autoformal/docs/guides/reconstruction_training.md) |
| Keep 8D and 384D running while developing 768D multilingual GTE | [Parallel logic IR paths and transfer plan](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_multilingual_migration_plan.md) |
| Dispatch independent 8D, 384D and 768D workers together | [Parallel lane execution](../../ipfs_datasets_py/logic/autoformal/docs/guides/parallel_lineage_execution.md) |
| Run pinned local 8D and 384D models in private CPU workers | [Parallel model inference workers](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_parallel_model_workers.md) |
| Prepare source-only 768D tasks and inspect pinned multilingual assets | [Multilingual embedding preparation](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_multilingual_preparation.md) |
| Reuse existing model assets and vectors before generating missing embeddings | [Existing assets and embedding cache reuse](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_embedding_reuse.md) |
| Prepare 768→384 pairs and verify frozen-teacher adapter gradients | [Affine bridge preparation](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_affine_bridge_preparation.md) |
| Initialize the 768D decoder from learned 8D and 384D heads before fitting | [Decoder reuse and distillation sequence](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_decoder_reuse.md) |
| Verify inherited decoder knowledge and export original-input teacher distributions | [Decoder knowledge transfer and replay](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_decoder_knowledge_transfer.md) |
| Join original decoder targets to cached native inputs and check reference gradients | [Native decoder inputs and reference objective](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_decoder_native_inputs.md) |
| Fit only the new input connections with both learned decoder bodies frozen | [Bounded decoder interface training](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_decoder_interface_training.md) |
| Continue reference training from the authenticated fitted input boundary | [Aligned-start interface training](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_aligned_interface_training.md) |
| Compare original donors and saved 768D generations without reference prefixes | [Source-only decoder evaluation](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_decoder_source_evaluation.md) |
| Prepare or fit the new input connection from same-source vector pairs | [Train-only affine alignment](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_affine_alignment.md) |
| Load a completed fit into the inherited 768D student without changing donors | [Aligned decoder handoff and private reload](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_aligned_decoder.md) |
| Inventory pinned checkpoints and audit transfer corpus partitions | [GTE migration preparation tools and first audit](../../ipfs_datasets_py/logic/autoformal/docs/guides/gte_migration_preparation.md) |
| Train the current latent projection and formula decoder together | [Joint formula training](modal_joint_formula_training.md) |
| Recover historical 8D training optimizations | [Legacy speed history and selective ports](legacy_speed_history.md) |
| Try native UI/UX learning from real compiler output | [Runnable native quickstart](native_feature_quickstart.md) |
| Train UI DOM/IDL bindings, resume, and choose HF datasets | [UI training, datasets and bindings](ui_datasets_and_bindings.md) |
| Implement React action, handler, state and typed-call capture | [React capture specification and implementation plan](react_capture_spec.md) |
| Train or resume the legal autoencoder, including feature mode | [Legal training](legal_training.md) |
| Compare legacy and current legal architectures and quality evidence | [Legal architecture comparison](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_architecture_comparison.md) |
| Score a checkpoint without training, or understand qualification | [Inference and qualification](inference_and_qualification.md) |
| Add UI/UX, Security, Intent, or another IR | [Modality adapters and validation](modalities.md) |
| Know which files, vectors, manifests, and checkpoints are required | [Artifacts and inputs](artifacts_and_inputs.md) |
| Coordinate workers, weights, Quack, DuckLake, and Hugging Face | [Control plane and synchronization](control_plane_and_sync.md) |
| Diagnose stalled epochs, source drift, storage admission, or rejected candidates | [Operations and troubleshooting](operations_and_troubleshooting.md) |
| Find the exact callable or script for a task | [API and command map](api_map.md) |

See [legal autoencoder lineages](../../ipfs_datasets_py/logic/autoformal/docs/guides/legal_autoencoder_lineages.md) to preserve the full legacy teacher separately from current students.

## Choose an execution path first

| Path | Input and representation | Output | Current scope |
| --- | --- | --- | --- |
| Legal qualified training | Legal `SampleRecord` rows, supported modal checkpoint, legal targets and disjoint validation | Candidate plus qualification evidence | Existing legal runners; success depends on all required gates |
| Legal feature pretraining | Verified local semantic embedding rows, provenance manifest, legal target supervision | Selected feature checkpoint; qualification flags false | Existing legal feature-mode parallel and exchange infrastructure |
| Legal inference | Immutable legal checkpoint and inference input/validation rows | Scores and evidence; no optimizer update | Separate execution route and state directory |
| Learned legal formula reconstruction | Authored source/rule pairs for `source_conditioned_formula_v1` | Source-only generated canonical rules, resumable Adam checkpoint | Bounded single-rule deontic vocabulary; no semantic qualification or fleet integration |
| Native categorical formula training | Fixed-shape native envelopes, immutable training/tuning vocabulary | Learned native records, decoder CE, exact Adam resume and actual-output Lake checks | Separate `native_formula_v1`; local bounded diagnostics, incomplete semantic coverage |
| Native IR structural training | UI/UX, Security, or Intent compiler envelopes, training-only basis, fixed tuning panel | Numerical state, Adam moments, isolated DuckDB candidate | Bounded local API; nonlegal fleet/HF/Arrow state integration remains separate |
| Native IR feature inference | Same native contract, basis, saved state, compatible targets | Latent vectors and reconstructed feature blocks | Read-only numerical inference; explicit formal readout also requires a version-bound structural head |

The registry and contracts are reusable. The legal worker frontend, target
cache, checkpoint codec, and Hub exchange do not become modality-neutral by
changing a domain string. Check [format compatibility](artifacts_and_inputs.md).

## Environment and source preflight

Run examples from the canonical dataset checkout in a fresh Python process:

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD"
export PYTHONDONTWRITEBYTECODE=1
```

This workspace has another editable package installation in HACC. An imported
package stays in `sys.modules`; changing `PYTHONPATH` inside that process is
insufficient. Restart with the pinned path. Do not edit HACC or
`hallucinate_app` to synchronize them with this checkout.

Run this preflight before loading models:

```python
from importlib.util import find_spec
from pathlib import Path
import ipfs_datasets_py
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree

expected = Path("/home/barberb/lift_coding/external/ipfs_datasets").resolve()
assert expected in Path(ipfs_datasets_py.__file__).resolve().parents
print(require_workspace_logic_tree())
for name in ("torch", "duckdb", "pyarrow", "huggingface_hub"):
    print(name, "available" if find_spec(name) else "not installed")
```

The guard checks compiler, decompiler, and parser location. It is not a complete
frozen dependency manifest. Distributed jobs also need their
[source snapshot and producer bindings](operations_and_troubleshooting.md).

| Dependency | Needed for |
| --- | --- |
| Python supported by this checkout (current packaging: 3.12+) | All examples |
| `torch` | Native structural numerical backend; optional numerical paths elsewhere |
| `duckdb` | Registry and owner control process |
| `pyarrow` | Explicit Arrow input, target, or weight paths; not native JSON quickstart |
| `huggingface_hub` and suitable credentials | Configured Hub transfers; not local quickstarts |
| Lean/Lake and source-locked legal project | Legal Lean admission through qualification |
| Verified already-local embedding model and production evidence | Semantic legal feature runs; mock vectors are not a substitute |

The handbook does not install dependencies, fetch weights, alter the context
window, or configure a service automatically. Temperature stays zero. The native
quickstart uses compiler structures and no pretrained model.

## Common lifecycle

```mermaid
flowchart LR
    S[Bound source inputs] --> A[Modality-specific target preparation]
    A --> T[Private training candidate]
    C[Contract and immutable parent] --> T
    T --> E[Repeated tuning and selection]
    E --> R[Owner-controlled registration]
    R --> I[Separate feature inference]
    R --> Q[Independent modality qualification]
    Q --> P[Policy-controlled promotion]
```

This describes responsibilities, not a universal launcher. The legal
distributed path has owner/worker transport. The native API currently implements
local preparation, training, registration, and inference; its full qualification
and remote transport remain separate work.

## Reading success correctly

- `ready_for_training` means the required target structure exists.
- `improved` means the specified selection objective improved under that path's
  regression constraints. Read per-projection metrics and attempted versus
  selected epochs too.
- Resume preserves the parent, representation, runtime, optimizer, and validation
  bindings required by its backend.
- A tuning score repeatedly used for selection is not a held-out canary.
- Feature inference may inspect an unqualified model; it grants no proof,
  deployment, or execution authority.
- Legal admission requires the actual source-locked `lake build <Lib>` path.
  Compiler output, roundtrip text, loss, targets, NCA cells, and database rows
  do not count. No Constitution span becomes formalized through feature work.

See [qualification](inference_and_qualification.md) for statuses and
[operations](operations_and_troubleshooting.md) for performance telemetry.

## Maintaining the handbook

Prefer these task guides over dated reports for commands. Reports remain
evidence for their measured run and commit. The
[modality report](../implementation/reports/AUTOENCODER_MODALITY_REUSE_20260929.md)
records the initial 189-test validation and three-domain structural smoke.

When APIs change, update the guide, argument table, and runnable example. Check
links and Python/shell syntax, and execute only relevant bounded examples.
Documentation validation must not become an unattended corpus run, checkpoint
overwrite, Hub upload, or model download.
