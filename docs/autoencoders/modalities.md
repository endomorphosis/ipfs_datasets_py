# Modality adapters, projection contracts, and API reference

[Handbook](README.md) · [Runnable quickstart](native_feature_quickstart.md)

The native feature APIs prepare targets from existing UI/UX, Security, and
Intent compilers, train a small structural autoencoder, and register its
candidate in the existing DuckDB registry. They share numerical kernels and
version contracts while keeping each domain's input types, logic projections,
and validation evidence separate. Start with the executable
[native feature quickstart](native_feature_quickstart.md).

These models learn the structure of native compiler outputs. Their vectors are
not pretrained semantic text embeddings, decoded formulas, or proof results.
`ready_for_training=true` means that an envelope has nonempty targets and
passing required target checks. It does not mean the original source was
interpreted correctly. Training, inference, and registration keep
`qualified`, `admitted`, `formalized`, and `promotion_performed` false.

| Layer | Existing API | Responsibility |
| --- | --- | --- |
| Domain input and targets | `logic.formalization.autoencoder.domain_targets` and `.ui_targets` | Call existing domain compilers and retain their native expressions, source bindings, missing semantics, and validation observations. |
| Modality identity | `optimizers.logic_theorem_optimizer.autoencoder_modality_contracts` | Separate domain, schema, representation, basis, projection, implementation, optimizer, and validator identities. |
| Local numerical backend | `optimizers.logic_theorem_optimizer.autoencoder_projection_features` | Fit a bounded structural vocabulary; train, resume, and read a model using the existing CPU reconstruction kernel. |
| Local version storage | `duckdb_control.autoencoder_registry.AutoencoderRegistry` | One owner, short database transactions, artifact integrity, isolated variants, and exact version ancestry. |

A canonical family, a profile, a property, and a view role are different
fields. `frame_logic`, `temporal`, `program`, and `deontic` are families.
Intent safety and liveness are properties of temporal routes. A verification
condition is a view role; it is not an additional semantic family. Native
profile names remain native labels rather than automatically becoming
canonical catalog profiles. TDFOL and DCEC declarations include their explicit
composition identities.

`ProjectionSpec` records both canonical taxonomy fields and
`native_profile_id` / `native_view_role`. The native backend checks its exact
supported projection specification. It rejects a manually attached canonical
profile or validator policy that this backend does not implement. Catalog
membership alone does not prove that a family parser or provider ran. The
existing legal five-bridge list is not applied to these modalities.

| Domain | Required native inputs | Actual projections | Qualification still missing |
| --- | --- | --- | --- |
| UI/UX | `RoundTripDocument` or `FormalizationInputs`, built from native component, behavior, action-binding, and event models. `ExperienceModel` and `UIModalityContract` can add accessibility/modality inputs. A plain dictionary, text, image, HTML page, or full `UIIRDocument` is not accepted directly by this target API. | Only populated views: `ui_ux_ir:flogic` → `frame_logic`; `ui_ux_ir:event_calculus` → `event_calculus`; `ui_ux_ir:tdfol` → `tdfol`; `ui_ux_ir:dcec` → `dcec`. Expressions are native records, not family-parser ASTs. | Shared source-gate adapter implementation, family syntax checks, full semantic preservation, and independently checked device/interaction behavior. |
| Security | A native `security_ir.cvefixes.schemas.CodeUnit`, exact UTF-8 source bytes, and explicit `CodeLogicEvidence(document, source_ref)` objects. A `SourceRef` must bind the typed declaration to the exact code body. | Program/contract → `program`; transition → `transition_system`; supported temporal formulas → `temporal`; heap/separation → `separation_logic`; hyperproperties → `hyperproperty`. Projection IDs retain native payload schemas. | Correct source-to-model interpretation, relevant model checking/proofs, and sufficient domain modeling such as heap or information-flow policy. |
| Intent | An `IntentIRDocument` accepted by `validate_intent_ir`; grounded native statements/actions/control flow, not an arbitrary request string. | Native routes for first-order facts, intentions, deontic norms, program action/Hoare structures, and temporal workflows/properties. Emitted verification-condition rows retain their view-role identity. | Correct interpretation of user intent, independently checked effects/proofs, and execution or tool authorization. |

Security accepts these existing typed evidence owners:
`ProgramIR`, `ProgramContract`, `StateTransitionIR`, `TemporalFormula`,
`HeapModel`, `SeparationLogicIR`, and `HyperpropertyIR`. For a program-only
corpus, request `requested_kinds=("program",)` explicitly. Requesting a kind
without its typed evidence produces an unsupported target gap. Source code,
CWE labels, classifier scores, and a source hash cannot fill that gap.
Missing code bytes cause quarantine without usable targets. A source join
checks identity; it does not prove that a supplied program model represents
the source correctly.

UI target preparation uses the working native compiler/decompiler through
`roundtrip_ui_ir`. It separately records that
`UIUXFormalizationAdapter@2.formalize()` reports
`ui_ux.adapter_not_implemented`. Source absence blocks preparation; source
presence does not complete that shared adapter. Native roundtrip layers can
pass, fail, or remain unevaluated. Their checks cover bounded reconstruction
properties, not mutual entailment of all logic fragments. Pixel equality and
source-code equality remain excluded. Optional device projection results
apply to the supplied, document-ID-bound `ProjectionProblem` only.

Intent preparation distinguishes actual modal operators when splitting
intention and deontic routes. It preserves unknown/opaque formulas as gaps and
can require specific native view IDs. Family-free role rows can remain in a
target envelope, but the numerical backend cannot select them as if they were
logic families. Select actual family projections explicitly; excluded
projection IDs are recorded in the fitted feature space.

The following functions are public local building blocks. Module prefixes are
shown above; the quickstart supplies complete imports and native inputs.

| API | Arguments and returned value |
| --- | --- |
| `prepare_ui_targets(document, *, roundtrip_policy=None, projection_problem=None, device_profile=None, projection_policy=None)` | Returns a `DomainTargetEnvelope`. `document` must be a native `RoundTripDocument` or `FormalizationInputs`. A projection problem and device profile must be supplied together; their document ID must match. `projection_policy` requires that pair. Invalid native models fail target readiness; qualification gaps remain separate. |
| `prepare_intent_targets(document, *, required_view_ids=())` | Returns an envelope from the native Intent compiler/decompiler. Required view IDs must be unique and registered; absent requested views block feature readiness. |
| `prepare_security_targets(*, code_unit, source_bytes, typed_inputs=(), requested_kinds=None)` | Returns source-bound native Security targets. `source_bytes` is bytes or `None`; `None` cannot establish a usable source binding. `typed_inputs` contains `CodeLogicEvidence` objects. Choose requested kinds for which reviewed typed inputs exist. |
| `DomainTargetEnvelope.from_dict(value)` / `.to_dict()` | Validates the closed envelope schema and makes immutable canonical bytes / a detached JSON-compatible copy. `.digest`, `.domain_id`, and `.source_digest` expose identities. Loading an envelope validates its structure and declared readiness; it does not independently rerun its producer. |
| `build_feature_space(domain, projection_ids, training_targets)` | Fits a dictionary on training targets only. Returns a JSON-compatible feature-space object. Projection IDs must be explicit and unique; every selected projection must be populated in every row and retain the same native descriptor. |
| `build_native_feature_contract(space, *, ir_schema, adapter_sha256, latent_width=4)` | Returns a `ModalityContract` for this backend and fitted basis. `ir_schema` names the domain input contract. `adapter_sha256` is a lowercase SHA-256 supplied by the caller for the actual adapter; do not use a placeholder digest. Backend/kernel and target-codec implementation identities are also bound. |
| `ModalityContract.from_dict(value)` / `.to_dict()` | Reconstructs / serializes the contract with catalog bindings. A changed catalog or incompatible declaration fails validation. `.sha256` and `.variant_id` are stable identities for that exact contract. |
| `train_projection_features(contract, space, training_targets, tuning_targets, *, base_state=None, epochs=3, latent_width=4, learning_rate=0.02, max_seconds=60.0, seed=1729)` | Returns `{"state": selected_state, "report": training_report}`. `base_state=None` initializes locally; an exact compatible state resumes its Adam moments. Tuning selects feature candidates and is not a held-out canary. |
| `infer_projection_features(contract, space, state, targets)` | Validates the contract/state and returns latent vectors, reconstructed projection-feature vectors, source identities, and vocabulary coverage. Executes no training and generates no decoded formulas. It does not mutate the supplied state. |
| `register_feature_candidate(registry, contract, space, result, directory, *, parent_version_id=None)` | Stages the complete candidate into a fresh directory, then registers a version through an already-owned `AutoencoderRegistry`. Returns version/artifact/variant identities. Resumed results require the exact registered numerical parent; a matching variant alone is insufficient. It does not publish, select a distributed generation, or promote an inference head. |

`ModalityAdapterRegistry.register(contract, adapter, capabilities=...)` provides
explicit trusted-local dispatch. Registration checks that requested callable
capabilities exist and binds the entry to the exact contract. It does not
import code named by dataset metadata, validate the implementation's entire
source closure, or turn a declared `publish`/`qualify` capability into an
implemented transport or qualification policy.

The backend bounds and behavior are deliberately small and explicit:

| Item | Current bound or policy |
| --- | --- |
| Target envelope | At most 32 MiB in the envelope codec; this backend accepts at most 4 MiB per target. |
| Batch | Between 1 and 1,024 targets; duplicate source digests within a batch are rejected. |
| Feature basis | Between 1 and 4,096 columns; canonical, unique columns grouped by projection. |
| Expression traversal | Maximum depth 32. Ordered list/argument positions remain significant. |
| Contract | At most 32 KiB; at most 64 projections and 64 validator requirements, with required entries. |
| Per-call epochs | Integer from 1 through 32. |
| Latent width | Integer from 1 through 64, identical to the contract and resumed architecture. |
| Learning rate | Finite numeric value in `(0, 0.1]`; identical on resume. |
| Deadline | Finite seconds in `(0, 300]`; cooperative checks between native operations. Exhaustion before a baseline can be prepared raises an error; exhaustion later returns the last checked state where possible. This is not process preemption. |
| Seed | Integer from 0 through `2**31 - 1`; recorded for local initialization. |
| Optimizer | Adam with beta values `(0.9, 0.999)`, epsilon `1e-8`, gradient clipping at norm `1.0`; saved moments and step counts are validated. |
| Candidate artifact | At most 32 MiB for the complete JSON artifact staged by this backend. |
| Runtime | CPU kernels and in-process tensors. These functions do not reserve campaign resources or enforce a kernel memory quota themselves. |

Input features use `log1p` counts and per-projection L2 normalization. The
objective averages each projection's reconstruction loss, cosine penalty with
weight 0.1, and the existing kernel's auxiliary norm penalty; L2 regularization
is zero. Selection requires aggregate improvement and no selected projection's
reconstruction or cosine regression beyond the implemented tolerance. A
zero-norm decoded projection cannot masquerade as perfect cosine. Later
attempted epochs may be rejected even when their aggregate objective improves;
the returned state and Adam moments belong to the last selected candidate.

Training and tuning source identities must be disjoint, including the sources
used to fit the vocabulary. Resume requires the same tuning envelopes in the
same order, not merely the same row count: their canonical digest is bound in
the numerical state. Keep the feature basis, projection set, contract,
architecture, optimizer settings, and compatible implementation bytes fixed.
New training rows can be encoded against that frozen basis. A vocabulary
expansion requires a new variant or an explicit migration; silently adding
columns breaks checkpoint identity and ancestry.

Unknown atoms in tuning, later training, or inference are counted in
`coverage` / `train_coverage` / `tuning_coverage`. They are not added to the
vocabulary and do not contribute reconstructed features. A selected projection
with zero known coverage fails. There is currently no additional minimum
coverage threshold or unknown-atom loss penalty. Inspect those counts before
interpreting a loss reduction: it describes known structural atoms, not the
complete meaning of an input with unseen content.

Persistence uses JSON-compatible contracts, feature spaces, target envelopes,
and numerical states. Registry artifacts include their digests and should be
verified before loading. An adapter-module hash is useful identity evidence,
but is narrower than a frozen manifest of every compiler dependency and its
runtime. Production campaigns still need the existing provenance/resource
infrastructure and independently checked domain inputs.

The local database catalogs candidate artifacts and ancestry; it does not read
or rewrite scalar SQL weights during each epoch. Keep a single database owner.
The native backend is not connected to the distributed legal worker, Quack
dispatch, Arrow weight codec, sparse update protocol, or Hugging Face exchange.
Its JSON numerical state must not be passed to the legal checkpoint/replay
format. The [implementation report](../implementation/reports/AUTOENCODER_MODALITY_REUSE_20260929.md)
records the local smoke and the ordered integration work still needed. No
Lake admission, legal qualification, Constitution formalization, or nonlegal
deployment qualification follows from these local APIs.
