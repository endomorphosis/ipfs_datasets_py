# Software Contract Soundness and Threat Model

Status: normative companion for
[`verdict-policy-v1.json`](verdict-policy-v1.json), policy version 1.0.0.

## Claim boundary

The analyzer makes bounded claims, not general claims of program correctness.
A successful proof means that one encoded obligation is valid within the
receipt's named semantic model, assumptions, selected scope, repository and
gitlink identities, contract and policy revisions, analyzer and toolchain
identities, and resource bounds. It says nothing about behavior omitted from
those bindings.

The JSON policy is the machine-readable authority. This document explains its
intent. A consumer must fail closed if the document and policy disagree, the
policy version is unsupported, or a required binding cannot be verified.
Narrow provable claims are preferable to broad claims that silently assume
away dynamic behavior.

## Conceptual interfaces

The policy names four conceptual interfaces. They are vocabulary contracts,
not runtime classes, but every receipt and completion decision must use them
consistently:

- `VerificationVerdict`: the exact terminal result for one obligation or scan
  result. The vocabulary is fixed by the policy `verdicts` array. Fail-closed
  verdicts never satisfy a completion criterion.
- `AssuranceLevel`: the claim-specific authority of an evidence kind. Levels
  are not totally ordered and are not a scalar trust score. Combining lower
  levels never creates a higher one.
- `CompletionEvidence`: an evidence kind drawn from `evidence_authority`,
  evaluated only against its allowlisted `may_satisfy` completion
  requirements. Evidence kinds are non-substitutable.
- `ProofAttestation`: a bound native or cryptographic verification artifact
  (`FORMAL_PROOF_RECEIPT` or `ZK_ATTESTATION`). Its authority is limited by
  `evidence_authority` and the matching `completion_requirements` entry. A
  simulated proof is not a `ProofAttestation`. A ZK envelope alone cannot
  satisfy `proof_required`.

## Supported semantic models

Version 1 permits only reviewed, version-bound models:

- static Python AST, symbol, import, call, contract, and effect facts whose
  targets can be resolved without executing source;
- static JavaScript and TypeScript facts under the same restriction;
- explicitly represented schema, dataset-operation, receipt, architecture,
  effect, exception, capability, and resource constraints;
- obligations translated to reviewed decidable theories or explicit finite
  temporal/resource bounds; and
- deterministic syntactic, dataflow, architecture, effect, and security rules
  over normalized IR.

Reflection, mutable dispatch and monkey-patching, runtime code generation,
unresolved dynamic imports, uncontracted native extensions, ambient network or
subprocess behavior, credentials, clocks, randomness, mutable external state,
and unmodeled metaprogramming are not silently approximated as safe.

When material behavior is outside every reviewed model, the result is
`UNSUPPORTED`. When behavior is represented but the bounded analyzer or solver
cannot decide it, the result is `UNKNOWN`. Non-execution, lack of observations,
or absence of findings can never produce `PROVED_WITHIN_MODEL`.

## Trusted computing base

The soundness boundary includes:

- Git-object and selected-root identity reading;
- canonical encoding, multihash, and CID code;
- parsers and normalized AST frontends;
- symbol, module, call, effect, exception, and dataflow resolution;
- reviewed contract and policy registries;
- obligation generation and model translation;
- solvers, deterministic rules, counterexample checkers, and proof
  reconstruction;
- coverage sharding and completeness validation;
- locked toolchains, sandboxing, and resource-budget enforcement; and
- receipt serialization, integrity, freshness, signature, native-proof, and
  cryptographic verification.

For a zero-knowledge claim, the cryptographic library, proving backend,
verification-key registry, public-input encoding, and reviewed circuit are
additional conditional trusted components. A detected identity, integrity,
configuration, or execution failure must become `STALE` or `ERROR`. A
compromised or incorrectly reviewed trusted component is outside the
guarantee; the policy never claims otherwise.

## Contract authority

Expected behavior is selected in this descending order:

1. reviewed policy or contract registry;
2. versioned public schema or protocol;
3. version-bound documented API contract;
4. declared type contract; and
5. implementation inference.

A lower authority cannot weaken a higher one. Conflicting authorities at the
same rank, an unbound authority revision, or an unresolved runtime authority
is a policy-input `ERROR`. Tests, traces, examples, GraphRAG results, and the
absence of findings are evidence, not contract authorities. A checked runtime
or symbolic witness can refute an authoritative contract, but it cannot
rewrite it.

## Scan completeness

A complete scan binds the repository trees and gitlinks, selected logical
roots, policy, analyzer, toolchain, shard plan, and coverage root. Every
selected tracked object is counted exactly once per logical root and has an
explicit analyzed, unsupported, excluded-by-policy, generated, vendored,
binary, archived, oversized, or missing disposition. All expected shards,
counts, and roots verify, and recursive mirrors are cycle-safe.

Any absent required repository, object, gitlink, shard, or disposition; a
count/root mismatch; an input that changes during analysis; or an unbound
snapshot produces `INCOMPLETE_SCAN`.

An unsupported object remains explicit and can therefore participate in a
complete inventory. That does not prove behavior depending on the object and
does not authorize a whole-scope safety claim. Similarly, zero findings means
only that the named rules emitted no findings over the successfully analyzed
scope. It is not proof, safety, scan completeness, or exhaustion evidence.

## Exact verdict vocabulary

Each obligation or scan result has exactly one of these terminal verdicts:

- `PROVED_WITHIN_MODEL`: a reviewed verifier established the encoded
  obligation under every named binding. The claim stops at that model.
- `VIOLATED_WITH_COUNTEREXAMPLE`: a deterministic checker accepted a concrete
  witness against the bound obligation. It does not claim that all violations
  were found.
- `UNKNOWN`: supported analysis was undecided or exhausted its declared
  budget. This is never a pass.
- `UNSUPPORTED`: material behavior lies outside reviewed semantics. It may be
  an inventory disposition, never a behavioral pass.
- `INCOMPLETE_SCAN`: required scope or disposition evidence is absent or
  unverifiable. Narrow findings can remain useful, but whole-scope absence and
  safety claims are forbidden.
- `STALE`: evidence does not bind current repositories, gitlinks, contracts,
  policy, analyzer, toolchain, or coverage roots.
- `ERROR`: analysis or verification did not complete safely and
  deterministically, including invalid policy inputs and integrity failures.

`UNKNOWN`, `UNSUPPORTED`, `INCOMPLETE_SCAN`, `STALE`, and `ERROR` always fail
closed. Only policy-allowlisted verdict, evidence-kind, assurance, and
condition combinations can satisfy a completion criterion.

## Evidence and completion authority

Evidence kinds are non-substitutable:

| Evidence | Maximum authority | May satisfy |
| --- | --- | --- |
| Formal proof receipt | Encoded obligation under bound model and assumptions | `proof_required` |
| Checked counterexample | Witnessed violation of one bound obligation | `violation_required` |
| Coverage receipt | Inventory and disposition completeness only | `coverage_required` |
| Test result | Exact exercised cases, assertions, revision, and environment | `test_required` |
| Type-check result | Selected type system and checked declarations | `type_check_required` |
| GraphRAG retrieval | Navigation and candidate discovery only | nothing |
| Simulated proof | Development diagnostics only | nothing |
| ZK attestation | Exact circuit statement and public-input integrity | `attestation_integrity_required` |
| Absence of findings | No emission by named rules over analyzed scope | nothing |

A proof-required criterion accepts only `PROVED_WITHIN_MODEL` backed by a
formal proof receipt with named model, bound assumptions and scope, complete
coverage for the claimed scope, current repository identity, bound policy,
analyzer and toolchain, and verified evidence integrity.

A `test_required`, `type_check_required`, or
`attestation_integrity_required` criterion can establish only that narrowly
named evidence condition. Completing one of those criteria neither satisfies
`proof_required` nor upgrades empirical or cryptographic-integrity evidence
into behavioral proof.

A test pass remains empirical even if repeated. A type-check pass does not
prove runtime behavior. GraphRAG ranking cannot create, suppress, prove, or
refute a fact. Multiple low-authority records do not combine into formal
authority.

A simulated proof is not a native proof, verifier execution, or cryptographic
proof. A ZK attestation proves only the exact statement encoded by its reviewed
circuit and bound public inputs. A baseline trace-commitment statement does
not prove that an analyzer is sound, that its trace is complete, or that its
underlying verdict is correct. A ZK envelope therefore cannot turn
`UNKNOWN`, `UNSUPPORTED`, `INCOMPLETE_SCAN`, `STALE`, or `ERROR` into
`PROVED_WITHIN_MODEL`. If a future reviewed circuit directly verifies an
obligation, that separately verified artifact must be classified under the
formal-proof policy; the envelope alone is insufficient.

The policy's positive and rejection fixtures are normative examples. They
demonstrate accepted bound proof, counterexample, coverage, test-only,
type-only, and attestation-integrity combinations, and reject authority
escalation, failed verdicts, stale or partial evidence, and missing bindings.

## Threats and conservative outcomes

The analyzer assumes source and dependencies may be malicious or pathological.
It parses source without executing it and applies explicit time, memory, graph,
solver, and output bounds. Unsupported constructs produce `UNSUPPORTED`;
bounded indecision produces `UNKNOWN`; unsafe tool failure produces `ERROR`.

Content identities and links protect against cache or evidence substitution.
Freshness checks protect against cross-revision receipts. Coverage roots and
dispositions expose omitted files and shards. Every cited retrieval record is
resolved by content identity, so poisoned embeddings or ranking drift remain
non-authoritative. Counterexamples are replayed by a deterministic checker.
Native and cryptographic proofs require their reviewed verifiers and exact
bindings; a label, signature, simulation, or envelope is not a substitute.

Resource exhaustion must never weaken identities, completeness, or verdict
rules. The correct bounded result is `UNKNOWN` or `ERROR`, not success.

## Non-goals

This policy does not:

- prove arbitrary functional correctness for dynamic languages;
- treat unsupported or unobserved runtime behavior as safe;
- turn inventory completeness into behavioral correctness;
- make tests, types, retrieval, simulation, and cryptographic integrity
  interchangeable;
- guarantee soundness when the trusted computing base or reviewed model is
  wrong; or
- infer whole-repository safety from a pilot, partial scan, or absence of
  findings.
