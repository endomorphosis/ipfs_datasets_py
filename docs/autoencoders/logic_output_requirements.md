# Logic outputs, training losses and mandatory Lake checks

Every autoencoder output schema must have an exact Lean4 representation checked
with `lake build <Lib>`. Each modality also needs its own logic projections,
parsers and semantics. A vector reconstruction score, JSON schema check,
compiler result, DuckDB row or declared `PROOF` enum cannot satisfy this policy.
Only an actual source-bound Lake build can provide Lean admission evidence,
and its scope must state exactly what was checked.

This inventory comes from the canonical `ipfs_datasets_py/logic` tree. It
separates available schema definitions and parsers from learned decoders,
executed validators and evidence of semantic correctness.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_logic_requirements import describe_logic_requirements

policy = runtimes.describe_runtime("security_ir", "native_v1")["qualification_requirements"]
code_policy = describe_logic_requirements("ui_ux_ir", contains_code=True)
```

`contains_code=False` is not a waiver for code-bearing artifacts. A production
verifier must derive applicability from the typed input/output adapter. This
declarative API accepts no external evidence or `passed` flag.

The [recorded inventory and three source-bound gate samples](../implementation/reports/evidence/legal-lineages-20260930/logic-output-requirements-inventory.json)
contains all 35 family descriptors, fourteen code routes, four domain policies
and ten runtime bindings. At that historical inventory revision all three authored spans compiled, but
distinct CEC and propositional exports were missing. The follow-up adds those
restricted syntax projections; complete semantic coverage still fails closed.
The [validation receipt](../implementation/reports/evidence/legal-lineages-20260930/logic-output-requirements-validation.json)
records 327 passing tests, including the installed `lake build Legal` numeric
pattern smoke. It does not claim that every schema has passed Lake.

## Eight-family schema capability floor

The following are eight separate requirements. A schema's qualification suite
must cover the floor; a particular input may use only its applicable logical
constructs. Do not manufacture eight supposedly equivalent translations of
every sentence, discard unsupported meaning, or count a simple predicate in a
richer grammar as evidence for that grammar's distinctive operators.

| Requirement | Canonical catalog binding | Required distinctions |
| --- | --- | --- |
| Propositional logic | `propositional` | Connectives and negation |
| First-order logic | `first_order` | Quantifiers, predicates, terms and binding |
| Deontic first-order logic | `deontic` with `first_order` | Obligation, permission, prohibition, guards and exceptions |
| Temporal first-order logic | `temporal`, composition `pure_temporal_fol_v1` | Temporal operators with first-order terms; no implicit deontic extension |
| Temporal deontic first-order logic | `tdfol`, composition `tdfol_composition_v1` | Temporal, deontic and first-order semantics together |
| Cognitive event calculus | Event-calculus and cognitive/modal structure | Event, fluent, time and cognitive operators; distinct CEC binding still needs an explicit reviewed composition |
| Deontic cognitive event calculus | `dcec`, composition `dcec_composition_v1` | Cognitive/event constructs plus deontic operators |
| Frame logic | `frame_logic` | Objects, slots, relations and frame structure |

The canonical registry has no standalone `cec` family. Existing aliases that
collapse CEC into DCEC do not satisfy two requirements. The new legal family
gate keeps them distinct. It now validates separate event/FOL and single-attitude propositional cognitive
fragments for CEC, plus propositional Boolean syntax. Mixed cognitive/event
nesting remains unsupported. The projections retain their original atom
bindings and explicitly disclose omitted modality and other semantics. All
eight syntax checks can pass while `family_coverage_gate` remains false.
Historical six-family diagnostics cannot pass the floor.

The existing canonical-rule exports are deliberately limited: FOL and TFOL
projections disclose omitted modality; temporal atoms are often predicates,
not interpreted temporal operators. DCEC currently validates a restricted
deontic first-order/event-atom fragment. The exporter records zero cognitive,
event-calculus and temporal operator counts where none were emitted. Preserve
those limitations in training targets and coverage reports.

Sources: [family gate](../../ipfs_datasets_py/logic/autoformal/family_qualification.py),
[canonical taxonomy](../../ipfs_datasets_py/logic/families/registry.py),
[compositions](../../ipfs_datasets_py/logic/families/profiles.py),
[DCEC operators](../../ipfs_datasets_py/logic/CEC/native/dcec_core.py).

## Code-bearing schemas add their native routes

The sealed software-verification registry supplies fourteen routes. These are
additional schema capabilities when inputs/outputs contain code, executable
contracts or state-transition models. Applicability comes from the trusted
typed source/schema adapter, never a worker's request to skip a gate.

| Typed owner | Family | Profile/view |
| --- | --- | --- |
| State | `transition_system` | `state_schema` |
| Transition | `transition_system` | `action_system` |
| Program | `program` | `program_ir` |
| Contract | `program` | `dynamic_hoare` |
| Verification conditions | `program` | `wp_vc`, verification-condition view |
| Temporal specification | `temporal` | `ltl` |
| Trace | `temporal` | `finite_trace` |
| Authorization | `authorization` | `datalog` |
| Protocol | `cryptographic_protocol` | `dolev_yao` |
| Hyperproperty | `hyperproperty` | `hyperltl` |
| Heap | `separation_logic` | `heap_model` |
| Separation | `separation_logic` | `separation` |
| Concurrency | `concurrency` | `rely_guarantee` |
| Refinement | `refinement` | `simulation` |

TLA+ belongs to state/transition and temporal modeling. Its parser/compiler and
TLC execution have separate identities and results; TLA+ is not a substitute
family name for all state logics. Similarly SMT-LIB is an encoding, while Z3
and cvc5 are backends. Preserve arithmetic/bit-vector theories, boundedness,
trace models, fairness and explicit translation losses in the semantic profile.

Security's current code projection selects seven of these owners: program,
contract, transition, temporal, heap, separation and hyperproperty. Supporting
those seven does not establish all fourteen or the eight-family floor.
UI's current views cover frame facts, event records, TDFOL and DCEC records.
Intent's native views cover facts, norms, intentions, actions and workflows.
Their common autoencoders still reconstruct compiler-prepared features.

Sources: [typed routes](../../ipfs_datasets_py/logic/software_verification/syntax_bridge.py),
[Security adapter](../../ipfs_datasets_py/logic/security_ir/code_logic_projection.py),
[TLA compiler](../../ipfs_datasets_py/logic/backends/tla/compiler.py),
[TLA runners](../../ipfs_datasets_py/logic/backends/tla/runners.py),
[native decoder limits](native_formal_decoders.md).

## Broader supported vocabulary and implementation levels

The canonical taxonomy contains 35 family IDs: `argumentation`, `authorization`,
`concurrency`, `cryptographic_protocol`, `datalog`, `dcec`, `defeasible_logic`,
`deontic`, `dependent_type`, `description_logic`, `doxastic`, `epistemic`,
`event_calculus`, `finite_field_constraint`, `first_order`, `frame_logic`,
`fuzzy_weighted`, `higher_order`, `horn_chc`, `hyperproperty`, `intention_agency`,
`modal`, `mu_calculus`, `nonmonotonic_logic`, `probabilistic`, `program`,
`propositional`, `refinement`, `relevance_paraconsistent`, `separation_logic`,
`session_process`, `situation_calculus`, `tdfol`, `temporal`, `transition_system`.

This is vocabulary coverage, not a claim that all are production-executable.
The parser catalogs bind exact notation/version/profile tuples. Implemented
profiles include LTL/LTLf/past-LTL/MTL/CTL/CTL*, Hoare/dynamic logic, resources,
HyperLTL, Datalog/Horn/SecPAL, symbolic protocols, and additional normative,
argumentation, ontology, agency and session/process syntax. Select their actual
catalog lifecycle and provider capability, not the presence of a directory.

Sources: [catalog composition](../../ipfs_datasets_py/logic/families/canonical_catalog.py),
[lifecycle](../../ipfs_datasets_py/logic/families/registry_v3.py),
[parser catalog](../../ipfs_datasets_py/logic/parsers/catalog.py),
[parser profiles](../../ipfs_datasets_py/logic/parsers/profile_catalog_v2.py),
[domain overlays](../../ipfs_datasets_py/logic/conformance/domain_family_bindings_v2.py).

## Lake schema checks and semantic admission

Record at least the exact schema version, decoded artifact and source identities,
Lean source files, renderer implementation, installed Lean toolchain, library,
command, exit status and build log. A verifier must regenerate and compare the
source, execute a clean bounded `lake build <Lib>`, and reject stale, partial or
caller-asserted success. Schema-only typechecking and proof of the source's
meaning are separate scopes. An empty schema, `True` theorem, fingerprint, or
uninterpreted opaque string cannot stand in for the decoded logic's semantics.

The current committed legal route runs `lake build Legal` for exact
source-locked numeric patterns. It does not cover a complete multi-family IR
schema. It rejects `within_duration` as a minimum-duration theorem and never
marks Constitution spans `roundtrip_ok`. The generic kernel adapter executes
`lean --json`; its result alone does not satisfy this campaign's Lake rule.

The working tree also contains an uncommitted Intent Lake projection. It checks
declaration syntax/types and explicitly omits action/workflow semantics. The follow-up now supplies a shared typed structural schema/instance renderer
for all four domains and binds actual learned runtime outputs to its Lake builds.
See [native formula training](native_formula_training.md). This closes structural
typecheck plumbing, not semantic coverage of every family or code route.

Some leaf objects use broader internal authority labels. For example the UI
TDFOL compiler defaults to `ResultAuthority.PROOF` while constructing string
records without executing a prover. The shared envelope already retains false
admission flags. Universal qualification must rely on verified execution
receipts and scope, never that enum or dataset metadata.

Sources: [legal Lake gate](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py),
[generic Lean backend](../../ipfs_datasets_py/logic/backends/kernel/lean.py),
[UI leaf](../../ipfs_datasets_py/logic/ui_ux_ir/formalize/tdfol.py).

## Decoder-aware optimization and completion criteria

Training requires a reversible, versioned modality codec and explicit target
provenance. Token/field reconstruction loss must update the actual source
encoder and output heads. Structure needs its own presence/length and binding
signals where required. Report losses per projection and semantically important
facet, rather than hiding a dropped exception or norm reversal in average loss.

Use actual generated outputs for evaluation: parse/type validity, exact
structure, argument/binder identity, negation, modality, guards, exceptions,
time, event/fluent and cognitive scope; for code also contracts, state changes,
resources and trace properties. Preserve every failed row in the denominator.
Perturbation and model-off tests must show output-dependent losses and selection.
Tuning data may select candidates; a separate held-out set measures generalization.

Lake and backend/model-checker results are nondifferentiable qualification or
selection evidence. Do not fabricate a gradient from a pass boolean. A surrogate
loss can guide training but cannot replace any required acceptance check.

Implementation order:

1. Version requirements and expose coverage gaps. Enforce eight separate legal
   syntax requirements and reject historical subset receipts for full qualification.
2. Add reviewed family/profile compositions and reversible domain codecs;
   implement missing CEC/propositional exports without weakening semantics.
3. Add typed Lean schema/artifact renderers for every required output route;
   reuse installed toolchain execution and source binding, with no Mathlib.
4. Connect modality output heads and loss components; keep old lineages and
   checkpoints separately loadable rather than relabeling their objectives.
5. Run family-specific negative/positive syntax, semantic, Lake and gradient
   tests; bind receipts to the candidate before qualified publication.

The requirements descriptor is a declaration. It does not add the missing
renderers, change feature-pretraining checkpoints, run Lake, or grant qualification.
Explicitly unqualified feature learning remains available while these gaps are
being repaired. No Constitution formalization claim follows from this work.
