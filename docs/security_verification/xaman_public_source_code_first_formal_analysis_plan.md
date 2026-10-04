# Xaman Public-Source Code-First Formal Analysis Plan

Status: profile frozen by `PORTAL-CXTP-156`; downstream analysis remains planned.

Corpus: \`https://github.com/XRPL-Labs/Xaman-App\` at
\`942f43876265a7af44f233288ad2b1d00841d5fa\`.

## Objective

Determine whether the reviewed public Xaman source supports or contradicts
precisely stated security properties. The result is limited to the pinned,
hydrated public repository and the formal models derived from it. A result is
one of:

- \`PROVED_UNDER_ASSUMPTIONS\` for a named source-level property with a checked
  proof and a complete assumption ledger;
- \`DISPROVED\` with a minimized, reproducible counterexample tied to source
  facts or a formal model;
- \`UNKNOWN\` or \`NOT_MODELED\` where the code, semantics, or required model are
  incomplete; or
- \`BLOCKED\` only when a local, reproducible analysis dependency is missing.

No result from this plan is a production-release approval, a claim about the
closed Xaman backend, or a statement that the public source equals a mobile
store binary.

## Fixed Inputs

The machine-readable profile is
`security_ir_artifacts/corpora/xaman-app/code-first/formalization-profile.json`.
Its `profile_digest` covers the source identity, input file digests, hydrated
coverage summary, taxonomy, solver scope, promotion policy, and assumption
ledger. Rebuild it with
`PYTHONPATH=. python scripts/ops/security_verification/build_xaman_code_first_formalization_profile.py`.

The analysis begins with the pinned repository URL and commit in
\`source-manifest.json\`, the clean hydrated checkout measured by
\`source-coverage-hydrated.json\`, the source-to-claim map, XRPL transaction
coverage, public package lockfiles, build files, and a solver environment
manifest. Source extraction must attach every fact to a repository-relative
path, line range, file digest, extractor version, and review status.

Heuristic extraction is evidence for modeling review, not proof that an
inferred behavior exists.

## Assumption Ledger

The code-first profile must distinguish source-supported facts from assumptions:

1. The hydrated checkout exactly matches the pinned public commit and dependency
   metadata.
2. TypeScript, JavaScript, React Native, and build-tool semantics are adequate
   for the checked property.
3. Cryptographic primitives and XRPL serialization libraries behave according
   to their documented contracts unless their public implementation is modeled.
4. Native keystore, biometric, secure-enclave, root/jailbreak, and bridge
   behavior are outside the TypeScript boundary unless directly modeled from
   public native source.
5. The remote payload platform, RPC providers, ledger validators, and network
   are untrusted or nondeterministic unless a public, source-supported contract
   is explicitly modeled.
6. A model finding applies only to a path statically reachable from a reviewed
   entry point under recorded preconditions.

Every assumption must state its owner, source, scope, expiration policy, and
whether it blocks promotion of a claim. Missing assumptions are failed proof
preconditions, not reasons to simplify the model.

## Security Properties

The initial pass prioritizes public-client properties:

- authentication and review gates before a signing decision;
- network identity and transaction-network binding;
- deep-link, QR, and payload classification before display or signing;
- transaction-type reachability, required fields, amount and memo handling, and
  explicit rejection of unsupported XRPL semantics;
- client lifecycle ordering, including refusal, cancellation, expiration,
  reconnection, and duplicate-result handling where source paths exist;
- proof-result and evidence-receipt consumers rejecting stale, downgraded,
  malformed, or non-proved inputs; and
- redaction boundaries for generated analysis evidence.

Backend atomic single-use, authoritative payload semantics, proprietary vault
signature generation, XRPL consensus, and deployed release equivalence remain
assumptions or \`NOT_MODELED\` boundaries.

## Formal Method

### Source-To-Model Refinement

Build a reviewed transition map from hydrated TypeScript, React Native, and
public native bridge code. Record entry points, guards, state updates, outbound
calls, error paths, and unsupported dynamic behavior. Every model transition
must have source support; every relevant source transition must be modeled or
reported as a coverage gap.

### State-Machine Checking

Use TLA+/Apalache for review/auth/sign ordering, expiration, cancellation,
reconnection, duplicate callbacks, and network changes. The backend and network
are adversarial or nondeterministic actors unless public source establishes a
stronger client-visible contract.

### Symbolic Protocol Checking

Use Tamarin and ProVerif for deep-link and payload protocol abstractions. Models
include an active attacker for replay, substitution, stale callbacks, and
result-confusion attempts. Missing projections, unexecuted proofs, timeouts,
and malformed models are coverage gaps, never successes.

### SMT Refinement And Transaction Constraints

Use Z3 and CVC5 on the same source-derived \`SecurityModelIR\` constraints.
Check source-to-model refinement, client-enforced transaction constraints, and
proof-consumer fail-closed rules. Both solver inputs must be frozen and
digest-bound. A satisfiable negated property is retained and minimized.

### Kernel-Checked Promotion Rules

Use Lean and Rocq/Coq to check proof-promotion policy: a source property cannot
be promoted when source coverage, solver agreement, assumptions, or
counterexample disposition is missing. Leanstral may suggest proof text, but
only successful Lean/Rocq kernel checks are evidence.

### Mutation And Fuzzing

Run deterministic property-based and mutation campaigns against extracted
transitions and model inputs. Mutate removed guards, reordered callbacks,
network substitution, malformed links/payloads, transaction-type confusion,
stale receipts, and missing result records. These campaigns test the models and
proof gates; they do not send traffic to Xaman services.

## Execution Plan

1. Establish the code-first profile and independent assumption ledger.
2. Produce a reviewed public-source transition and reachability map.
3. Build and execute the state-machine, protocol, and SMT refinement models.
4. Build independent Lean and Rocq proof-promotion checks.
5. Run mutation/disproof campaigns and retain every counterexample.
6. Aggregate solver results into a code-first portfolio and issue a bounded
   verdict naming every unresolved assumption and coverage gap.

Tasks \`PORTAL-CXTP-156\` through \`PORTAL-CXTP-164\` implement this sequence.
They depend only on completed public-source hydration and local solver tooling,
not vendor authorization, production artifacts, a Firebase project, or a live
XRPL network.

## Optional Self-Hosted Testnet

\`PORTAL-CXTP-165\` is intentionally separate and blocked until explicitly
activated. It may validate selected source-model predictions using accounts,
keys, nodes, and Testnet funds controlled by the assessment team. It is not a
premise for a code-first proof and cannot convert a public-source result into
production assurance.

## Evidence And Disclosure

Each task emits source references, model IDs, hashes, commands, solver logs,
timeouts, environment details, counterexamples, and a scope statement. A
credible source-supported defect should be minimized, reproduced without
exposing secrets, and reported through the public responsible-disclosure route
before public disclosure. Negative controls, missing models, and assumptions
must not be reported as product defects.

## Acceptance Rule

The final verdict may state only the property, source commit, model, solver
checks, and assumptions actually established. It remains \`DISPROVED\`,
\`UNKNOWN\`, \`NOT_MODELED\`, or \`BLOCKED\` whenever a required source transition,
solver lane, assumption, or counterexample disposition is unresolved.
