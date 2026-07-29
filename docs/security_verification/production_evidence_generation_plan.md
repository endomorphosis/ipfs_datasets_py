# Production Evidence Generation Plan

Status: pending authorized production access and named owner assignment

Related tasks: `PORTAL-CXTP-077` through `PORTAL-CXTP-084`, with detailed
collection work packages `PORTAL-CXTP-098` through `PORTAL-CXTP-110`.

## Purpose And Security Decision

This plan produces the reviewed production evidence needed to evaluate a
specific wallet and exchange release. It does not authorize a claim that the
system is secure. A release may be described only as **secure under stated
assumptions** after the existing production claim gate, proof baseline,
disproof suite, runtime conformance checks, and release handoff all pass.

The Xaman-App corpus is a public test corpus. It may inform models and
regression tests, but it is not production evidence unless its exact revision,
build, deployment, runtime behavior, and approval are the intended production
target and are supplied by the accountable operator.

## Evidence Boundary And Handling

1. Identify one release target before collecting any evidence: application
   version, source revision, build artifact digest, deployment identifier,
   platform, environment, chain or network, and collection time.
2. Keep raw credentials, keys, seed phrases, access tokens, customer data, and
   unredacted secrets out of this repository. Store them in the approved secure
   system and produce reviewed, redacted exports, digests, attestation IDs, and
   evidence references for this evidence package.
3. Each committed evidence artifact needs an owner, collection timestamp,
   review status, SHA-256 digest, provenance, and a defined freshness window.
   Use `human_reviewed` for real production evidence; `trusted_fixture` is
   permitted only for non-production test fixtures.
4. All exports must be immutable once collected. A changed deployment, source
   revision, configuration, build, or production event schema invalidates the
   affected evidence and requires recollection and rerunning dependent proofs.

## Evidence Package Layout

The completed package uses `security_ir_artifacts/production/evidence-bundle.json`
as its manifest. The manifest references durable, sanitized artifacts under
these paths:

```text
security_ir_artifacts/production/evidence/
  source/          source inventories, commits, SBOMs, build attestations
  environment/     configuration snapshots, custody, chain, audit evidence
  runtime/         sanitized traces, schemas, trace-to-model mapping
  reviews/         owner signoffs and independent review records
  solver/          versioned proof, differential, and disproof reports
```

The manifest must have non-empty `source_snapshots`, `environment_evidence`,
`runtime_traces`, `owner_signoff`, and `solver_reports` arrays. Every referenced
file must exist locally and match its recorded SHA-256 digest.

## Work Phases

### Phase 0: Authorize Collection And Establish Governance

The security release owner approves the evidence boundary, redaction policy,
retention period, collection freshness window, and use of a collection-stage
validation report. Assign owners for security architecture, wallet key
management, transaction signing, exchange ledger, withdrawal nonce service,
chain risk, security governance, custody platform, blockchain infrastructure,
audit compliance, runtime observability, and release management.

The collection-stage report is intentionally not a release decision. It can
show that supplied source, environment, runtime, and review evidence is
complete enough to build the production model. Only the existing full evidence
bundle validation may produce `PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED`.

### Phase 1: Pin The Production Release And Supply Chain

Collect the deployed repository URLs and commits, reproducible build inputs,
package lockfiles or SBOMs, CI run IDs, signed build attestations, artifact
digests, deployment IDs, mobile binary digests, backend image digests, smart
contract addresses and bytecode hashes, and schema or migration revisions.

The source inventory must cover the wallet, signing path, payload APIs,
withdrawal/deposit services, internal ledger, authentication and authorization
policy, custody/HSM integration, monitoring and audit components, and the
proof-receipt consumer. Each blocking or high claim must have a line-level or
module-level source mapping or a documented `NOT_MODELED` decision that blocks
release.

### Phase 2: Capture Production Environment And Operational Assumptions

Collect reviewed, redacted evidence for:

- cryptographic primitive and library versions, entropy source, key lifecycle,
  wallet vault configuration, and key custody controls;
- signing canonicalization, approval binding, policy checks, HSM attestation,
  refusal behavior, administrative quorum, and break-glass controls;
- database engine, isolation level, transaction boundaries, retries, ledger
  writes, reservations, nonce uniqueness, idempotency, and failure recovery;
- chain and asset finality, reorganization response, RPC provider trust,
  quorum or fallback policy, and stale-data bounds;
- CI/CD provenance, runtime deployment topology, monitoring, audit-log
  tamper-evidence, retention, and incident response procedures.

This phase resolves the real facts behind assumptions A1 through A10 in
`production_environment_profile.md`. It produces the JSON environment profile
and the evidence references needed by `PORTAL-CXTP-077`.

### Phase 3: Capture Runtime Evidence

Export a sanitized release-window trace set with schema versions and device or
deployment provenance. It must cover payload intake, presentation and review,
authentication, authorization, signing and refusal, expiration, replay,
network binding, broadcast, confirmation or finality, rejection, cancellation,
and critical audit events.

Map each runtime event to a `SecurityModelIR` event. Preserve stable correlation
identifiers using an approved pseudonymization scheme so counterexamples can be
traced without exposing customer data. Trace windows, collection clocks, and
freshness dates must be reviewable.

### Phase 4: Review And Construct A Collection-Stage Bundle

An independent reviewer checks source-to-claim mappings, artifact digests,
redaction safety, and the consistency of environment and trace evidence with
the pinned release. Accountable owners sign explicit scope statements. The
collection-stage validator reports completeness without accepting the release;
this prevents the present bootstrap cycle in which final solver reports are
required before source and environment collection can be recognized.

The full `evidence-bundle.json` remains fail-closed until it contains solver
reports for all required claims with `outcome: prove`:

- `no_unauthorized_withdrawal`
- `no_over_reserved_internal_account`
- `global_asset_conservation`
- `no_deposit_before_finality`
- `no_signing_request_after_wallet_freeze`
- `capability_delegation_no_authority_increase`
- `revoked_capability_no_future_authorization`

### Phase 5: Formalize And Test The Production Release

Use the reviewed evidence to complete `PORTAL-CXTP-079` and
`PORTAL-CXTP-080`: construct the production `SecurityModelIR`, bind every
assumption to current evidence, map source and traces to model events, and
enforce required domain and claim coverage. Z3 and CVC5 are the required
differential SMT baseline. Lean and Leanstral may assist proof engineering, but
Leanstral output has no proof authority until Lean/Lake checks it; optional
Apalache, Tamarin, ProVerif, and Coq lanes may add coverage but cannot turn an
unknown result into a proof.

Run `PORTAL-CXTP-081` and `PORTAL-CXTP-082` only against the pinned release.
All known-bad replay, authorization bypass, accounting mismatch, stale receipt,
missing custody approval, signer downgrade, and chain mismatch mutations must
fail closed. Any solver disagreement, unsupported theory, stale input, absent
trace, or unresolved assumption blocks release.

### Phase 6: Runtime Conformance And Handoff

Run `PORTAL-CXTP-083` with the reviewed trace bundle, then execute
`PORTAL-CXTP-084` and the guarded blocker updater. The release handoff must
list all evidence paths, digests, owners, review dates, expiry dates, solver
versions, claim outcomes, counterexamples, and remaining gaps. The updater may
change task status only when the full evidence bundle passes and every relevant
packet permits the update.

## Delivery Sequence

```text
authorization and RACI
  -> pinned release provenance
  -> source + environment + runtime collection
  -> independent review and collection-stage report
  -> PORTAL-CXTP-077 and PORTAL-CXTP-078 outputs
  -> SecurityModelIR and claim gate (079-080)
  -> proof, disproof, and runtime conformance (081-083)
  -> full bundle validation and release handoff (084, 095)
```

Source, environment, and runtime collection can proceed in parallel after the
release target is frozen. Formal proof execution cannot begin until their
reviewed outputs are complete. No task is allowed to infer a production fact
from the Xaman corpus, local development machine, or a generated placeholder.

## Acceptance Checklist

The evidence package is ready for the existing full validator only when:

- every referenced artifact is present, immutable, digest-verified, fresh, and
  marked `human_reviewed`;
- every required operational owner has approved an explicit scope statement;
- `security_ir_artifacts/production/security-model-ir.json` is bound to the
  pinned release and has current assumption evidence;
- all blocking and high claims have both Z3 and CVC5 production evidence and
  the final accepted outcome is `prove`;
- expected-bad mutations have a recorded non-secure outcome;
- runtime evidence maps to model events and is within its approved freshness
  interval; and
- the full validator reports `overall_status: pass` and
  `security_decision: PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED`.

Until then, the correct outcome is `blocked-production`, not a partial or
conditional secure-release claim.

## Research, Tooling, And Preparation

The task-specific prerequisite matrix is
`docs/security_verification/production_unblock_prerequisite_matrix.md`.

Z3 and CVC5 are required for the primary production proof baseline and are
currently available in this checkout. TypeScript, Python, Node, npm, and Lean
are also available. Re-probe and pin their exact executable paths, versions,
and digests on the dedicated proof worker immediately before the production
baseline; a local developer probe is not durable production evidence.

Apalache, Tamarin, ProVerif, and Coq are optional and currently unavailable.
Install them only if the approved target threat model makes their temporal,
protocol, or proof-kernel coverage a release requirement. They add assurance
coverage but do not unblock missing source, environment, runtime, freshness,
or owner evidence for `PORTAL-CXTP-077` through `PORTAL-CXTP-084`.

Target-specific research is required before formalization: consensus and
finality rules, RPC/provider trust, custody and signing semantics, database
isolation and nonce behavior, ledger conservation, authentication and
administrative controls, mobile/backend build provenance, observability, and
audit retention. Findings must be reviewed and linked to the frozen production
release rather than copied from a public corpus or general documentation.
