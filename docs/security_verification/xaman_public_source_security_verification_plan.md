# Xaman Public-Source Security Verification Plan

Status: public-source verification in progress; vendor release assurance blocked

Corpus: `https://github.com/XRPL-Labs/Xaman-App` at
`942f43876265a7af44f233288ad2b1d00841d5fa`.

## Decision Boundary

This plan evaluates the public React Native Xaman wallet source and its
committed Android, iOS, TypeScript, e2e, and build configuration. It can
produce one of the following results:

- a counterexample or source-supported defect in the modeled public code;
- a conditional proof that a precisely modeled source property holds under
  enumerated assumptions; or
- an explicit `UNKNOWN`, `NOT_MODELED`, or blocked finding.

It cannot establish that the released Xaman mobile applications, Xaman
platform/backend, native secure-storage implementation, biometric integration,
XRPL infrastructure, or operator controls are secure without vendor-authorized
build provenance, device traces, backend evidence, and owner review. The
public-source result must never be represented as a vendor release approval.

## Current Evidence Review

The local Xaman corpus pin matches the upstream `master` revision as checked
on 2026-07-10. The existing assurance packet correctly rejects a security
verdict. Z3 and CVC5 agree for all ten modeled Xaman claims, but every result
is `blocked_assumption`; there is no solver disagreement and no accepted proof.

The current blockers are:

1. Native vault cryptography and biometric security are outside the reviewed
   JavaScript/TypeScript source boundary.
2. Backend payload authentication, single-use behavior, expiration, and PATCH
   conflict handling are outside the public mobile repository.
3. Device/runtime equivalence is unproven because no build-provenanced Android
   or iOS trace bundle exists.
4. XRPL consensus, node honesty, finality, and provider behavior are external
   trust assumptions.
5. Transaction validation is incomplete for at least `TrustSet`, `OfferCreate`,
   and `SignerListSet`; the current counterexample is a real source-model gap
   that must be extended or retained as blocking.
6. The current proof receipt consumer is Lean-checked but not integrated into a
   production consumer.
7. Apalache, Tamarin, and ProVerif lanes are not run because their executables
   are unavailable. These are coverage gaps, not evidence of a defect.

The seven current counterexamples include expected negative-control mutations.
They prove that the fail-closed gates reject removed authentication, replay,
network, stale-evidence, and downgraded-solver protections. They are not seven
confirmed vulnerabilities in Xaman. The unsupported transaction-class finding
and all assumptions remain release-blocking until evidence changes the model.

## Formal Verification Strategy

### Public-Source Lane

1. Keep the corpus pin and public release provenance current, recording source
   and tag drift without silently changing the tested commit.
2. Extend static source inventories for the native vault/biometric bridge,
   deep links, payload API boundaries, proof-receipt handling, and all XRPL
   transaction classes reachable from the application.
3. Add typed `SecurityModelIR` facts only when source evidence identifies the
   relevant implementation and preconditions. Preserve every unsupported path
   as `NOT_MODELED` or `blocked_assumption`.
4. Reproduce public build and committed e2e checks in a pinned Android/iOS
   verifier environment. Build success does not constitute real-device runtime
   evidence, but build inputs and failures refine the model boundary.
5. Run Z3 and CVC5 differentially after each model change. A claim may advance
   only when both results agree, its source evidence is reviewed, and all
   consumed assumptions are current and explicitly accepted for the
   public-source profile.
6. Expand mutation tests for native-auth bypass, payload replay, network
   mismatch, stale receipt acceptance, backend double-use, and transaction
   types not yet modeled.

### Optional Solver Coverage

Install Apalache only for stateful payload/signing interleavings. Install
Tamarin and ProVerif only for explicit attacker and secrecy questions spanning
payload creation, deep links, authorization, and signing. These tools must be
version-pinned, their models must be checked by the executable, and an absent
lane must be reported as a coverage gap. Leanstral may suggest Lean proofs but
has no authority without Lean/Lake checking.

### Vendor-Evidence Lane

The following needs XRPL Labs authorization or a similarly authoritative
operator:

- mobile-store artifact identifiers and reproducible build/provenance;
- sanitized real-device traces for setup, import, review, authentication,
  signing, rejection, expiration, replay, network binding, and broadcast;
- backend payload service source or a reviewable API/security contract,
  including single-use and conflict semantics;
- native vault, secure-enclave/keystore, biometric, root/jailbreak, and device
  policy evidence;
- relevant XRPL node/provider, finality, and availability assumptions; and
- a responsible-disclosure contact and review process for non-public findings.

Until that evidence exists, tasks must keep vendor release assurance blocked.

## Acceptance Criteria

### Public-Source Assessment

A public-source assessment is complete only when all reachable source domains
are inventoried; unmodeled components and assumptions are visible; the
applicable public-source claims have reviewed evidence; Z3/CVC5 run
differentially; negative controls fail closed; and solver coverage gaps are
reported. The result may still be conditional or blocked.

### Vendor Release Assurance

Vendor assurance additionally requires all vendor-evidence inputs, current
owner approval, actual device/runtime conformance, reviewed backend and native
boundaries, and the existing production evidence gates. It is not achievable
from the public GitHub repository alone.

## Task Sequence

`PORTAL-CXTP-119` through `PORTAL-CXTP-126` improve the public-source
assessment and remove local solver/tooling blocks. `PORTAL-CXTP-127` through
`PORTAL-CXTP-129` are intentionally blocked pending authorized Xaman operator
evidence and final review.
