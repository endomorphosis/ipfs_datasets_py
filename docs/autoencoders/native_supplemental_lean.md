# Supplemental native IR interpretations in Lean

The shared autoencoder projection code can lower closed fragments of four
additional native models: `AuthorizationIR`, `ConcurrencyIR`, `ProtocolIR`, and
`RefinementIR`. These routes interpret explicitly supplied native declarations.
They do not infer those declarations from a checkpoint prediction or prove that
the declarations describe the source software correctly.

Use the [distributed projection context workflow](distributed_384_projection_context.md)
to bind a supplemental model to an unchanged prediction and its exact source.
The context entry has the shape `{"kind": "authorization", "document": native_document}`
inside `inputs.supplemental_inputs`. Other supported kinds are `concurrency`,
`protocol`, and `refinement`.

The richer [explicit interpretation routes](explicit_native_interpretations.md)
add typed state updates, symbolic refinement and static protocol frames while
preserving the original native models. The fragments below describe operation
without that additional evidence.

| Kind | Native family/profile | Applicable domain routes | Shared emitter |
| --- | --- | --- | --- |
| `authorization` | `authorization` / `datalog` | Intent, Security, Legal, UI/UX | `native_authorization_lean.emit_authorization` |
| `concurrency` | `concurrency` / `rely_guarantee` | Security | `native_concurrency_lean.emit_concurrency` |
| `protocol` | `cryptographic_protocol` / `dolev_yao` | Security | `native_protocol_lean.emit_protocol` |
| `refinement` | `refinement` / `simulation` | Security | `native_refinement_lean.emit_refinement` |

The modules live in `ipfs_datasets_py.logic.formalization.autoencoder`. Their
low-level API is `emit_*(native_document) -> (lean_source, details)`. A successful
call prepares declarations; it does not run Lake or issue execution evidence.
Unknown or unsupported semantics raise `UnsupportedNativeLean` or fail native
validation. The caller must retain that failure instead of deleting the field
or substituting a simpler model with the same claimed identity.

## Authorization: ground extensional policies

The supported policy fragment has ground facts and ground Datalog or SecPAL
rules whose body predicates do not occur in any rule head. Atoms have at most
three arguments. Positive body literals, closed-world negative body literals,
and explicit string equality, inequality, and membership guards have executable
Lean definitions. At least one fact, rule, or query is required; a principal and
trust-root declaration alone does not count as policy coverage.

Rules retain stratum and identifier ordering. SecPAL issuers must be declared
trust roots. The four precedence modes preserve `allow`, `deny`, `conflict`, and
`unknown`. Evaluation follows `ReferenceAuthorizationEvaluator`, including its
query-directed head alignment and scan of materialized predicates belonging to
allow/deny rules. Fact issuers remain provenance; they do not independently
assert an allow decision. This is a documented reference-evaluator fragment,
not a general implementation of SecPAL inference.

Variables, intensional body dependencies requiring a fixed point, role
materialization, delegation, speaks-for closure, query context/guards, opaque
guard statements, and custom/comparison/scope/temporal guard kinds are blocked.
Explicit universe-size constraints are also blocked. Derivation and fact
budgets must be large enough that the supported reference computation cannot
exhaust them. Native validation checks predicate signatures, references, and
sort consistency before lowering.

## Concurrency: labelled constant-guard steps

The supported fragment distinguishes component actors from environment actors
and preserves thread/process identifiers. Every guard must be the literal
`true` or `false`; every effect must be `skip`, with no declared reads or writes.
A transition preserves an arbitrary value-valued store. No integer sort,
program counter, initial-state condition, or extra stutter transition is
invented for the source.

Atomic regions contain exactly one step with exact, disjoint, bidirectional
membership. Weak, strong, and unconditional fairness have infinite-trace
definitions; the statement must equal the fairness kind. A fairness selector
names one step or one component's step set. Internal interference and
rely/guarantee relations support only literal Boolean conditions, retaining
their actor scopes and linked interference declarations. Their shared-variable
lists must be empty. Finite schedule definitions preserve their step caps,
explicit selections, and enabled-step checks; finite schedules do not establish
infinite-trace fairness.

Typed state mutations, opaque guard/effect prose, shared-state contracts,
channels, sessions, linearizability, locked or multi-step atomic regions,
ambiguous mixed selections, and additional semantic attributes are blocked.
The producer/consumer fixture with buffer arithmetic and session declarations
therefore remains unsupported. An independently authored `skip` example has a
different native identity and does not repair that richer fixture.

## Protocol: ground symbolic terms and conditional trace queries

The supported fragment has ground sorted terms, explicitly oriented rewrite
facts, free constructors, and one unambiguous typed symmetric
encryption/decryption pair. Adversary knowledge reflects declared capabilities,
initial and conditional knowledge, public and compromised keys, channel
visibility, and observed messages. Injection, replay, and drop steps have
explicit preconditions. Perfect symbolic decryption is not a computational
cryptography result.

Secrecy, reachability, authentication, and correspondence claims become query
definitions over an explicit interpretation of permitted finite traces and
complete trust statements. Correspondence requires one antecedent and one
consequent event with matching parameter declarations; injective correspondence
uses distinct earlier occurrence matches. A message send denotes emission, not
delivery. The IR supplies no role processes, so the emitter does not synthesize
or verify them. At least one supported query is required.

Observational equivalence, additional algebra families, free destructors without
semantics, session-variable substitution, compromised-role local state,
conditional channel guarantees, and ambiguous encryption signatures are
blocked. Declared fresh names remain a ground single-instance interpretation;
replicated-session freshness requires another lowering. Arbitrary trust prose
is an explicit premise parameter bound to the complete statement, not a newly
proved fact.

## Refinement: bounded matching of finite labelled graphs

The supported fragment has explicitly named finite states with literal Boolean
predicates and labelled nonstutter edges. Each system must have a satisfiable
initial state. Related-state couples and their direction are preserved. In this
repository's native contract, forward simulation is abstract-leading and
backward simulation is concrete-leading. Each leading edge must have one
matching trailing edge with the same action label and a related successor pair.

Explicit schedule and matching bounds constrain the generated check. Native
simulation obligations become Boolean checks and propositions, with no theorem
asserting that they hold. Every obligation must identify its exact relation,
system pair, and bound. Terminal markers are retained; the native model does
not prohibit an explicitly declared outgoing edge from a terminal state.

Opaque state predicates, coupled-data predicates, stuttering simulation,
concurrency-document links, extra semantic attributes, state-count budgets,
unbounded refinement claims, and other obligation kinds are blocked. Canonical
statement strings are required: `simulation`, `related`, and `bounded simulation`
in their respective fields. The richer authored refinement fixture remains
blocked until those declarations receive a typed interpretation.

## Replay, compilation, and coverage

The candidate gate schema is `distributed-384-candidate-native-lake/v3`. It
reuses the frozen v5 native gate and native model owners, adding routes only for
the audited Security source/program join and recognized supplemental models.
The native supplemental envelope must contain exactly `bridge`,
`native_document`, and `typed_expression`; the enclosing native owner regenerates
the bridge and expression identities during report replay.

Before and after compilation, the gate validates exact source bytes, the
unchanged candidate, typed inputs, native model round trips, report identity,
and producer file hashes. Source references present in the declarations must
resolve against the supplied source binding. Supplemental models that lack
internal source fields still have an explicit outer typed evidence binding.
Security requires its exact CodeUnit/body join and declared polarity. The gate
does not accept an unrelated native model as a replacement prediction.

Existing unsupported views remain in the report, with their prior diagnostics.
A supported extra view cannot hide a blocked view in the same family. The
original richer examples still expose three frontiers: producer/consumer
concurrency, protocol observational equivalence, and refinement with opaque
predicates. Removing unsupported constructs would create a new declaration and
new identity, not demonstrate coverage of the original one.

Lake compiles the generated definitions. Required additional syntax checks,
including SANY for a TLA+ view elsewhere in the report, must pass independently.
Only a live issued execution handle can be verified against freshly replayed
inputs; archived JSON receipts retain historical evidence only.

All four emitters report `capability_floor_eligible: false`. Coverage is limited
to the declared fragment. Compilation does not establish source fidelity,
program correctness, a real authorization grant, protocol security, or
unbounded refinement. Conditional queries and obligation definitions are not
proofs of their premises or conclusions. Admission and promotion remain false.

## Resource limits and unchanged training artifacts

The emitters impose finite collection/depth limits and total payload caps:
authorization and concurrency accept at most 256 KiB, protocol at most 128 KiB,
and refinement at most 512 KiB at their payload checks. These caps are upper
bounds, not guaranteed accepted sizes.

The shared Lean string renderer also limits every string to **16,384
characters**, rejects unsupported control characters, and performs quoting.
This matters for serialized provenance as well as labels. Protocol and
refinement currently retain the whole compact native document in one Lean
string, so that serialization must also fit the 16,384-character limit even
when the broader payload byte cap would allow it. Authorization retains
individual serialized records and concurrency retains individual identifiers
and labels; each such string has the same limit. The combined generated module
also has the candidate gate's 4 MiB cap. Oversized declarations fail explicitly;
they are not truncated into apparent coverage.

These additions do not rewrite prior numerical training recipes, DuckDB round
journals, checkpoint snapshots, weights, or published default checkpoint pins.
They add preparation and execution evidence. A successful build never promotes
a checkpoint or inserts caller-authored declarations into learned model output.
Use reviewed source/native-target pairs and a separate training run to measure
whether richer targets improve reconstruction on holdouts.
