The autoencoder infrastructure now has a local path for preparing native UI/UX,
Security, and Intent targets, fitting structural features, training and resuming
a separate numerical model, reading its features without training, and storing
an isolated candidate in the existing DuckDB registry. This is a foundation for
reusing the distributed infrastructure. It does not make the existing legal
worker fleet a nonlegal training service.

The change keeps domain semantics with their existing owners. Scheduling,
resource limits, content addressing, version ancestry, checkpoint transport,
and numerical kernels can be shared. Source normalization, actual compiler
views, supported logic fragments, preservation requirements, and qualification
projections remain specific to each modality.

All new training, inference, and registration outputs remain
`qualified=false`, `admitted=false`, `formalized=false`, and
`promotion_performed=false`. Native target envelopes also keep the first three
flags false. Feature readiness means usable structural training targets exist;
it does not mean their interpretation, proof obligations, or deployment
behavior has been verified. These adapters do not execute Lake. Legal admission
still requires the existing `lake build <Lib>` path, and no Constitution span
becomes formalized through this work.

The implementation is in the pinned `external/ipfs_datasets` source tree:

| Surface | Implemented responsibility |
| --- | --- |
| `optimizers/logic_theorem_optimizer/autoencoder_modality_contracts.py` | Immutable modality, representation, projection, validator, implementation, and version identities; explicit local adapter registration. |
| `logic/formalization/autoencoder/domain_targets.py` | Immutable target envelopes plus adapters to the existing Intent compiler/decompiler and source-bound Security code projections. |
| `logic/formalization/autoencoder/ui_targets.py` | Existing UI compiler outputs, bounded roundtrip observations, and optional device projection evidence. |
| `optimizers/logic_theorem_optimizer/autoencoder_projection_features.py` | Structural feature space, CPU training through the existing reconstruction kernel, Adam resume, read-only inference, and candidate registration. |
| Existing domain compilers, `security_ir/code_logic_projection.py`, and `duckdb_control/autoencoder_registry.py` | Retain ownership of native semantics, exact source joins, durable versions, and the single-writer database boundary. |

The contract records the IR schema, source language, input representation,
feature basis, target codec, numerical state codec, optimizer implementation,
objective, selected projections, validator policy, and adapter identity. Its
digest determines an isolated model variant. Equal vector dimensions are not
sufficient for reusing a checkpoint. Changing a modality, projection schema,
feature basis, objective, implementation, or architecture creates an
incompatible identity instead of silently reinterpreting existing weights.

The taxonomy distinguishes a canonical logic family from a native profile,
property, and view role. For example, Intent safety and liveness are properties
under temporal logic, and a verification condition is a view role rather than
a new family. Native profile names are preserved without claiming they are
reviewed global logic profiles. TDFOL and DCEC retain explicit composition
identities. A named family or registered route establishes vocabulary, not that
a prover, parser, or qualified execution path ran.

| Domain | Actual target preparation | Validation retained and important limits |
| --- | --- | --- |
| UI/UX IR | `prepare_ui_targets` calls the native layered roundtrip, which invokes the existing compiler/decompiler. Actual populated views produce frame-logic component facts, event-calculus behavior formulas, TDFOL action norms, and DCEC interaction records. | Records schema failures, source-gate disposition, compiler coverage, evaluated/skipped roundtrip layers, and optional device projection results. Structural reconstruction and bounded traces are not mutual entailment or a proof. Missing views are not fabricated. |
| Security IR | `prepare_security_targets` reuses `project_code_logic` and its exact replay validator. Program and contract inputs map to program logic; state transitions to transition systems; supported temporal inputs to temporal logic; heap/separation inputs to separation logic; hyperproperty inputs to hyperproperty logic. | Requires exact code-body binding and explicitly supplied typed evidence for requested targets. A CWE label, classifier score, code snippet, or missing heap/policy declaration cannot manufacture the required IR. Source semantics, model checking, and backend proofs remain unverified. |
| Intent IR | `prepare_intent_targets` uses the existing Intent compiler and decompiler review, then preserves native route identities. Actual emitted routes distinguish first-order facts, intention/agency, deontic norms, program/action contracts, temporal workflows, and temporal properties. | Reviews protected fields and preserves unsupported/opaque formulas and missing requested views. Verification-condition roles remain represented in the envelope but cannot substitute for a canonical family in this numerical backend. Structural fidelity to an Intent declaration grants no tool authorization. |

The UI source gate needs particular care. The package and its native compiler
exist, but `UIUXFormalizationAdapter@2.formalize()` still reports
`ui_ux.adapter_not_implemented`. The new target adapter records that gap
separately from successful native compilation. It does not rewrite the gate,
claim that source presence means adapter completion, or upgrade UI leaf
dataclasses to parser-checked family ASTs. An absent source package blocks
target preparation. Optional device projection evidence is scoped to the
supplied, document-bound problem; it does not prove that the entire UI is
accessible or deployable on that device. Pixel and source-code equality remain
excluded claims.

The current numerical representation is a vocabulary of native compiler
structure. Each selected projection has its own namespace and normalized
feature block. Ordered argument positions remain significant. The vocabulary
is fitted on training sources, and tuning/inference report known and unknown
atoms. The model reconstructs these structural features and produces latent
vectors; it does not decode executable formulas or generate formalized text.
It does not use pretrained semantic text embeddings, and it downloads no
weights. A low loss on known structural atoms must not be reported as semantic
equivalence of the complete input, particularly when vocabulary coverage is
low.

Training reuses the CPU reconstruction and gradient kernels from
`modal_autoencoder_cuda.py`; importing that implementation does not select a
CUDA backend. The backend has its own feature-space and numerical-state
schemas. It averages projection objectives and reports reconstruction,
cosine, and the kernel's auxiliary norm penalty separately. Candidate selection
requires aggregate improvement without hiding a required projection's
reconstruction or cosine regression. Zero-norm reconstructions cannot count
as perfect cosine. The result is a checked feature candidate, not evidence of
a global loss minimum.

The example below assumes `training_documents` and `tuning_documents` contain
native `RoundTripDocument` or `FormalizationInputs` instances prepared by the
application. They must have disjoint source identities. It intentionally
selects only the populated structural component view; a multi-view campaign
must explicitly choose its additional projections and supply each required
view in every row. Repeated tuning is not a held-out canary.

```python
from hashlib import sha256
from pathlib import Path

from ipfs_datasets_py.logic.formalization.autoencoder import ui_targets
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_projection_features import (
    build_feature_space,
    build_native_feature_contract,
    infer_projection_features,
    register_feature_candidate,
    train_projection_features,
)
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry

training = [ui_targets.prepare_ui_targets(doc) for doc in training_documents]
tuning = [ui_targets.prepare_ui_targets(doc) for doc in tuning_documents]
space = build_feature_space("ui_ux_ir", ("ui_ux_ir:flogic",), training)
adapter_digest = sha256(Path(ui_targets.__file__).read_bytes()).hexdigest()
contract = build_native_feature_contract(
    space, ir_schema="ui-ux-ir/v1", adapter_sha256=adapter_digest, latent_width=4,
)
result = train_projection_features(
    contract, space, training, tuning,
    epochs=3, latent_width=4, learning_rate=0.02, max_seconds=60,
)
features = infer_projection_features(contract, space, result["state"], tuning)
assert features["training_executed"] is False
assert features["decoded_formulas_generated"] is False

# Execute registration in the existing owner process. These are fresh local
# example paths, not a second connection to a live campaign database.
with AutoencoderRegistry("example-control.duckdb", "example-artifacts") as registry:
    registered = register_feature_candidate(
        registry, contract, space, result, "example-candidate-001",
    )
```

Use an explicit pinned `PYTHONPATH` or the existing source capsule when running
this code. A bare package import can resolve to the unrelated editable HACC
installation. The example adapter digest identifies that module's bytes; it
does not attest the complete compiler dependency closure. A distributed
campaign must bind the verified frozen producer/runtime manifest as well.

Incremental training keeps the fitted basis and selected projection identities
fixed. New training rows may be encoded in that basis, with unknown atoms
reported. Resume supplies `base_state=result["state"]`, the same contract,
feature space, tuning targets, architecture, and optimizer settings. The saved
state includes Adam moments, consistent step counts, and the selected epoch
count. The immutable tuning digest prevents changing the selection set while
calling it the same resumed run. Reports distinguish attempted work from the
selected state's progress and bind the actual parent state. Registering a
resumed candidate requires the exact registered parent version whose numerical
state matches that binding.

Vocabulary expansion is a separate version change. It needs an explicit
migration or a new variant; it must not happen implicitly during inference,
resume, or synchronization. Source-disjoint tuning also must not silently reuse
the original vocabulary-fitting sources. Deadline checks include preparation
and occur between native numerical operations. They are cooperative checks,
not a hard process preemption guarantee; the campaign resource supervisor
remains responsible for an external process deadline.

Target envelopes are canonical and content addressed. Their identity includes
the actual native expressions, source digest, projection descriptors,
validation observations, and qualification gaps. This creates a reusable
boundary for later shared target storage. It does not install a new distributed
cache today, and the legal target cache must not accept these envelopes by
renaming fields. A future cache key must include the domain/schema, exact
source and typed-evidence binding, frozen producer identity, requested
projection set, policies, and envelope digest. Distinct Security modeling
declarations for the same code bytes cannot share a cache entry merely because
their code-body hash matches.

The current registry integration stores a versioned artifact containing the
contract, feature space, numerical state, and training report. DuckDB catalogs
that artifact and its ancestry; the numerical arrays are not repeatedly read
and written as SQL rows during an epoch. One owner still serializes short
transactions, and workers should use the existing Quack interface when a
remote adapter is added. This change does not create a new DuckLake catalog or
rename DuckLake to “quacklake.” It does not change existing legal checkpoint,
sparse-update, or Hub manifest formats.

The implementation order for broader reuse is concrete:

1. **Finish per-domain corpus and validation profiles.** Build representative,
   source-bound training, repeated-tuning, and independent canary corpora for
   each selected projection set. Include negative examples for wrong argument
   order, missing effects, weakened norms, accessibility loss, invalid source
   joins, and unsupported fragments. UI needs graph/trace/accessibility/device
   checks; Security needs the relevant program, temporal, heap, and flow
   policies; Intent needs protected-field and intended-effect preservation.
   This has the highest domain-specific cost and avoids spending distributed
   compute on targets that have the wrong meaning. Keep legal's five bridge
   names and Lake gate confined to their existing legal path.

2. **Move target preparation behind the shared, immutable cache boundary.**
   Produce domain envelopes once from a verified frozen source/runtime,
   publish their manifest, and give workers read-only target shards. Reuse
   resource reservation, hashing, stale-source rejection, and storage
   accounting from the existing campaign infrastructure. Measure cold target
   preparation and warm reuse separately, with counts of actual emitted
   projections. This can remove repeated compiler work, but introduces cache
   storage and invalidation costs. Do not add a new distributed cache until
   profiling confirms repeat preparation is material.

3. **Add an explicit remote modality worker adapter.** Dispatch through an
   allowlisted local adapter registered for the full contract digest. Require
   prepare/train/evaluate/state-codec capabilities independently; a declaration
   of capability does not implement it. Reuse the single DuckDB owner, Quack
   requests, leases, worker resource scheduling, immutable job bindings,
   generation compare-and-swap, and stale-parent retry. The owner must replay
   the candidate and recompute that modality's selection metrics. Domain,
   basis, tuning, and producer mismatches must reject before training or
   publication. Test owner restart, expired leases, duplicate delivery, and
   source drift before using two physical hosts. This is orchestration work,
   not permission to substitute legal target preparation inside a generic
   worker.

4. **Profile the local numerical and serialization costs, then add an Arrow
   state codec if justified.** The present bounded backend keeps numerical
   tensors in process and serializes a complete candidate in its own JSON
   format. It is not yet an Arrow weight implementation. An Arrow codec needs
   explicit tensor names, dimensions, dtypes, projection/basis identity,
   endianness, Adam moments, and immutable parent digests. Read-only memory
   mapping can reduce loading and copies; tensor conversion and mutable
   training still need measured ownership/lifetime rules. Workers should
   produce bounded updates locally and submit a manifest to the owner, with
   short database commits. The opportunity cost is codec/migration complexity;
   implement it after measurements show checkpoint copying or serialization
   dominates this backend. Never switch to a CUDA-resident path based only on
   available hardware.

5. **Define nonlegal sparse-update and Hugging Face transport schemas.**
   Bind each patch to the exact modality contract, state codec, parent full
   state, parameter layout, optimizer state, and resulting full-state digest.
   Reuse existing upload/download integrity, idempotency, resumability, and
   anchor-compaction mechanisms through an explicit transport adapter.
   Independent workers' Adam updates must not be averaged or replayed onto a
   different parent without a defined aggregation algorithm. The established
   conservative path is selected-generation compare-and-swap with stale work
   retrained from the current parent. Sparse patches may exceed a full anchor;
   choose publication format using measured bytes and replay cost. A proposed
   Hub v2 modality manifest must coexist with legal's current formats and use
   separate namespaces. These nonlegal remote exchanges are not implemented
   or validated by the local API.

6. **Qualify inference separately from feature training.** Attach independently
   produced, modality-specific parser/typechecker, structural preservation,
   bounded-model, or proof receipts to the exact selected state and source
   artifacts. Keep unavailable checks explicit. Establish an owner-controlled
   inference promotion policy only after those checks exist. Low reconstruction
   loss, a database row, a generated syntax string, or a successful feature
   upload cannot replace them. For legal Lean admission, Lake remains the
   authority. For other modalities, their reviewed qualification profiles must
   specify the relevant evidence rather than inheriting a legal gate that
   says nothing about their semantics.

The immediate value is a common contract and a working local learning boundary
that can be profiled and tested before modifying the operating legal fleet.
The larger costs are source-grounded corpus construction, modality validation,
and versioned remote state transport. Reusing the existing database ownership,
resource controls, and replay infrastructure can reduce those integration
costs; it cannot remove the need for domain-specific semantic evidence.

The owned local native smoke passed for all three modalities. Its
[result receipt](evidence/autoencoder-modality-reuse-20260929/native-smoke.json)
records actual target preparation, training, Adam resume, inference without
training, and registration of isolated candidates in the local registry. Each
modality used four small authored structural fixtures: two training rows and
two repeated-tuning rows. Each attempted three epochs followed by one resumed
epoch, with latent width 4, learning rate 0.02, seed 1729, and a 60-second
cooperative deadline per training call. No legal bridges or external provers
ran in this smoke.

| Native modality | Selected projection count / feature width | Initial tuning objective | Final selected tuning objective | Selected cumulative epochs | Target preparation for four rows |
| --- | --- | --- | --- | --- | --- |
| Intent | 6 / 174 | 0.196044 | 0.112094 | 1 | 0.105242 s |
| Security | 1 / 52 | 0.120698 | 0.027951 | 4 | 0.019378 s |
| UI/UX | 4 / 36 | 0.246532 | 0.040538 | 4 | 0.049731 s |

Intent retained its first selected epoch. Later aggregate losses were lower,
but a projection's reconstruction regressed, so those proposals and the
resumed proposal were not selected. Security and UI/UX improved again during
resume. The Security numerical smoke exercised only `program.program_ir/v1`;
it does not demonstrate numerical learning for every supported Security
projection. UI/UX exercised its four actual views. Intent exercised facts,
action/Hoare, intentions, norms, safety, and workflow-temporal routes.

These objectives measure known-vocabulary structural fixture reconstruction.
The receipt reports unknown tuning atoms where present. The rows are not
independent semantic canaries, and the results do not show source-meaning
preservation, calibrated semantic embeddings, a global optimum, or compiler
qualification. Initial training calls took 1.212185 s, 0.008438 s, and
0.012404 s for Intent, Security, and UI/UX respectively; resume calls took
0.020785 s, 0.008984 s, and 0.010915 s. These sequential calls share one process
and warmed imports, so they are not comparable cold-start performance
baselines or a parallel scaling measurement.

The [resource receipt](evidence/autoencoder-modality-reuse-20260929/resources.json)
records a released reservation, no cleanup error, no storage overrun, and no
live child at final accounting. The run reserved 32,000,000 bytes, one CPU
slot, one child slot, and 4,096 MB of memory. Retained attempt artifacts totaled
4,850,088 bytes. Enforcement was cooperative admission and polled usage, not a
kernel quota.

The result receipt SHA-256 is
`c5220f2d1997d2ef688bedb4b6307fc2bc9e8c7ede9424ca3558c6e45c3c24bb`;
the resource receipt SHA-256 is
`77cf216955ebee3b86c36b0483db566351226eae2b15cf4ba15b835b4d0814e7`.
Six explicitly listed implementation/test files had identical before/after
hashes. Publication also compares selected dependency bytes. In particular,
`security_ir/code_logic_projection.py` and its focused test existed in the
workspace but were absent from `origin/main`; the reviewed dependency bytes
are included with this change. Other untracked Security work is excluded.
These checks are narrower than a complete frozen producer/runtime capsule
and do not establish validation of the full published runtime.

The final combined regression run passed **189 tests in 8.74 seconds**, as
recorded in
[test receipt](evidence/autoencoder-modality-reuse-20260929/tests.log).
It covers the new modality contracts, native targets and feature backend,
relevant existing domain tests, and the existing DuckDB registry checks.

This smoke used one physical host, did not test parallel execution, and did
not publish weights or database artifacts or transfer them through Hugging
Face. It downloaded no pretrained weights and executed no Lake build. The
nonlegal distributed worker, Arrow state codec, sparse update transport, and
Hugging Face integration described above remain follow-on work.
