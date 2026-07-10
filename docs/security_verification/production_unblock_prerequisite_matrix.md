# Production Unblock Prerequisite Matrix

Status: current as of 2026-07-10

This matrix records what is required to unblock the production evidence path
(`PORTAL-CXTP-077` through `PORTAL-CXTP-084`). It distinguishes real
production inputs from research and local tool preparation. None of the local
preparation items is a substitute for reviewed evidence from the deployed
system.

## Required Inputs By Production Blocker

| Blocker | Must obtain | Research needed | Tool preparation | Cannot be substituted by |
| --- | --- | --- | --- | --- |
| 077 environment evidence | Reviewed environment, custody, chain, database, CI/CD, monitoring, audit, and owner/freshness facts | Target-specific cryptography, key lifecycle, finality, RPC, governance, HSM, and operational trust assumptions | Reproducible evidence-digest and proof-worker environment | Xaman source, local machine facts, or generated profiles |
| 078 source inventory | Deployed repository revisions, build provenance, artifact digests, schemas, contracts, policy, and source-to-claim mappings | Architecture and data-flow analysis of the actual wallet/exchange release | SBOM/build-attestation parsing and source snapshot/digest tooling | Public repositories unless they are the exact deployed revision |
| 079 SecurityModelIR | Reviewed outputs of 077/078 plus runtime/model mappings and assumption owner signoff | Formalization review of source behavior, trust boundaries, and unmodeled domains | Z3/CVC5 worker lock and model canonicalization tooling | Heuristic extraction without human review |
| 080 claim gate | Complete production domains, claim owners, assumptions, and release-gate policy | Threat-model review for missing wallet, custody, ledger, API, audit, and runtime claims | Claim coverage and policy validation scripts | A passing unit-test suite alone |
| 081 proof baseline | Immutable production model, current source/environment evidence, and solver reports | Validate theories, abstractions, and assumptions against release behavior | Z3/CVC5 are required; pin their executable, version, and digest in the proof worker | Leanstral suggestions or a single-solver result |
| 082 disproof suite | Production claims, mutations, counterexamples, and baseline results | Target-specific replay, authorization, accounting, signer, finality, and chain mismatch attack analysis | SMT differential runner; optional protocol/TLA tools only if their coverage is required | Xaman-only counterexamples without production mapping |
| 083 runtime evidence | Sanitized release-window traces, schemas, event stream names, provenance, and freshness approval | Event-to-model semantics, pseudonymization safety, and observability coverage | Trace exporter, schema validator, digest tooling, and approved secure export path | Synthetic traces or development telemetry |
| 084 handoff | All preceding outputs, reviewer signoff, current evidence, and a release decision | Independent evidence consistency and residual-risk review | Full-bundle validator and guarded status updater | Manual status edits or partial evidence |

## Current Tool Decision

The current solver dependency probe reports the required primary baseline as
available: Python 3.12.12, Node 24.18.0, npm 11.16.0, TypeScript 5.5.4, Z3
4.16.0, and CVC5 1.3.2. No primary solver installation is required to begin
the 077-084 preparation work.

Lean 4.31.0 is also available but optional. Apalache, Tamarin, ProVerif, and
Coq are currently absent and optional. Install them only after the approved
threat model shows that their TLA+, protocol, or proof-kernel coverage is part
of the target release gate. Their installation cannot replace the required
Z3/CVC5 differential baseline or make missing production evidence acceptable.

Leanstral remains an advisory proof-engineering aid. Its output may help write
Lean proofs, but it is not evidence until checked by Lean/Lake and bound to
reviewed production inputs.

## Research And Preparation Order

1. Approve the evidence boundary and assign owners.
2. Freeze the exact production release target and build provenance.
3. Perform target-specific research on chain/finality/RPC, custody/signing,
   exchange accounting/nonce semantics, mobile/backend runtime, and audit
   controls. Record sources, owners, conclusions, and unresolved assumptions.
4. Rehearse redacted source, configuration, and trace export without copying
   credentials, key material, or raw customer data into this repository.
5. Lock a reproducible proof worker with absolute executable paths, versions,
   hashes, and command environment; re-probe immediately before production
   proof execution.
6. Collect, review, and digest the actual evidence; then perform model,
   baseline, disproof, runtime, and handoff tasks in dependency order.

Public research can inform assumptions and threat models. It cannot clear an
assumption, authorize a production release, or replace source, environment,
runtime, and owner evidence from the real deployment.
