# Code-to-IR Evidence Matrix

Status: In Progress
Date: 2026-07-08
Scope: `ipfs_datasets_py/logic/security_models/crypto_exchange`
Related task: `PORTAL-CXTP-062` (Restore SecurityModelIR schema and source coverage gates)

## Purpose

This matrix is the reviewable map from source-code evidence to the typed
`SecurityModelIR` (`ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py`).
It exists so that:

1. Every production exchange security domain and every Xaman wallet
   security domain has at least one documented extractor path, one claim,
   and one evidence kind feeding the IR.
2. The fail-closed coverage gate (`ir.schema.check_domain_coverage` /
   `ir.schema.validate_domain_coverage`) has a human-reviewable companion
   document instead of only a machine check.
3. Reviewers can see, per domain, which IR collections
   (`claims`, `proof_obligations`, `disproof_vectors`, `runtime_traces`,
   `solver_results`, `assumptions`) are populated today versus still
   pending deeper extractor work (tracked by later taskboard entries such
   as `PORTAL-CXTP-063`/`PORTAL-CXTP-067`).

`DISPROVED`, `UNKNOWN`, `NOT_MODELED`, and any domain missing from this
matrix are treated as non-secure, fail-closed outcomes per
`docs/security_verification/production_release_decision_policy.md`.

## Typed IR surface (`ir/schema.py`)

| IR field | Purpose | Typed shape |
| --- | --- | --- |
| `assumptions` | Bounded threat-model assumptions (`A1`-`A10` plus reviewed custom entries) | `AssumptionEntry` |
| `claims` | Declarative security claims bound to a security `domain` | `ClaimEntry` |
| `proof_obligations` | Prover-bound obligations discharging a `claim_id` | `ProofObligationEntry` |
| `disproof_vectors` | Mutation/attack/counterexample search results bound to a `claim_id` | `DisproofVectorEntry` |
| `runtime_traces` | Runtime/e2e traces checked for conformance against modeled `events` | `RuntimeTraceEntry` |
| `solver_results` | Raw solver invocation results (`sat`/`unsat`/`unknown`/...) bound to a `claim_id` | `SolverResultEntry` |
| every record collection | Evidence provenance | `EvidenceRef` (`kind`, `path`, `review_status`, optional line range/sha256) |
| CIDs | Content addressing for models and reports | `ir.cid.calculate_model_cid`, `reports.proof_report.ProofReport.cid` |

`ir.schema.PRODUCTION_SECURITY_DOMAINS`, `ir.schema.XAMAN_SECURITY_DOMAINS`,
and their union `ir.schema.KNOWN_SECURITY_DOMAINS` are the canonical domain
vocabulary referenced below. `ir.schema.validate_domain_coverage(model)`
raises `ValueError` fail-closed when a required domain has zero `claims`
entries.

## Production exchange domains

| Domain | Source extractor(s) | Representative claim(s) | IR fields populated | Evidence kind(s) | Coverage |
| --- | --- | --- | --- | --- | --- |
| `withdrawals` | `extractors.source_code_extractor.SourceCodeExtractor`, `extractors.python_ast_extractor.PythonASTExtractor` | `claims.withdrawal.NoUnauthorizedWithdrawalClaim` (`no_unauthorized_withdrawal`) | `events` (`withdrawal_requested`/`approved`/`broadcast`/`cancelled`), `state_machines`, `claims`, `proof_obligations`, `disproof_vectors`, `runtime_traces`, `solver_results` | `source_code`, `test_fixture` | Covered |
| `ledger` | `extractors.source_code_extractor.SourceCodeExtractor`, `extractors.openapi_extractor.OpenAPIExtractor` | `claims.ledger.NoOverReservedInternalAccountClaim` (`no_over_reserved_internal_account`), `claims.ledger.GlobalAssetConservationClaim` (`global_asset_conservation`) | `accounts`, `metadata.ledger_totals`, `claims`, `proof_obligations`, `solver_results` | `source_code`, `manual_review`, `test_fixture` | Covered |
| `deposits` | `extractors.source_code_extractor.SourceCodeExtractor`, `extractors.log_trace_extractor.LogTraceExtractor` | `claims.deposit.NoDepositCreditedBeforeFinalityClaim` (`no_deposit_before_finality`) | `events` (`deposit_observed`/`finalized`/`credited`), `state_machines`, `claims`, `proof_obligations`, `runtime_traces`, `solver_results` | `source_code`, `test_fixture` | Covered |
| `hsm` | `extractors.source_code_extractor.SourceCodeExtractor` | `claims.hsm.NoSigningAfterWalletFreezeClaim` (`no_signing_request_after_wallet_freeze`) | `wallets`, `events` (`signing_request`/`wallet_frozen`), `claims`, `proof_obligations`, `disproof_vectors`, `solver_results` | `source_code`, `test_fixture` | Covered |
| `capabilities` | `extractors.source_code_extractor.SourceCodeExtractor`, `extractors.ucan_policy_extractor.UCANPolicyExtractor` | `claims.capability.CapabilityDelegationMonotonicityClaim` (`capability_delegation_no_authority_increase`), `claims.capability.RevokedCapabilityClaim` (`revoked_capability_no_future_authorization`) | `capabilities`, `events` (`capability_revoked`/`privileged_action`), `claims`, `proof_obligations`, `disproof_vectors`, `runtime_traces`, `solver_results` | `source_code`, `policy_doc`, `test_fixture` | Covered |
| `audit` | `extractors.log_trace_extractor.LogTraceExtractor` | `claims.ledger.AuditEventExistsForCriticalTransitionClaim` (`audit_event_exists_for_critical_transition`) | `events` (`audit_logged`), `claims`, `proof_obligations`, `runtime_traces`, `solver_results` | `audit_log`, `test_fixture` | Covered |

Fixture: `ir.examples.example_minimal_exchange_model()` instantiates every
row above end-to-end (claims, proof obligations at `PROVED`, disproof
vectors at `SURVIVED`, runtime traces referencing real modeled events, and
`unsat` Z3 solver results) so `validate_domain_coverage(model,
required_domains=PRODUCTION_SECURITY_DOMAINS)` passes without a live
exchange checkout.

## Xaman wallet corpus domains

The Xaman corpus is pinned at `https://github.com/XRPL-Labs/Xaman-App`
commit `942f43876265a7af44f233288ad2b1d00841d5fa` (see
`docs/security_verification/xaman_corpus_profile.md`, `PORTAL-CXTP-060`).
`extractors.xaman_source_extractor.XamanSourceExtractor._security_category`
classifies corpus paths into the domains below; deep autoformalization of
the corpus into claims/proof obligations is tracked separately by
`PORTAL-CXTP-063` (extractor extension) and `PORTAL-CXTP-067` (claim
compilation). Until that lands, `ir.examples.example_xaman_wallet_security_model()`
provides a reviewed, heuristic fixture so the domain-coverage gate has a
concrete typed-IR instance to check against.

| Domain | Source path pattern | Extractor | Representative claim | IR fields populated | Evidence kind(s) | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| `vault` | `src/common/libs/vault.ts` | `XamanSourceExtractor` (category `vault`) | `claim:xaman_vault_secret_never_plaintext` | `invariants`, `claims`, `proof_obligations` (`NOT_MODELED`), `runtime_traces` | `source_code` (`heuristic`) | Fixture-covered; prover encoding pending `PORTAL-CXTP-067` |
| `payload` | `src/common/libs/payload/*` | `XamanSourceExtractor` (category `payload`) | `claim:xaman_payload_digest_matches_signed_bytes` | `claims`, `proof_obligations` (`NOT_MODELED`) | `source_code` (`heuristic`) | Fixture-covered; prover encoding pending `PORTAL-CXTP-067` |
| `ledger` | `src/common/libs/ledger/*` | `XamanSourceExtractor` (category `ledger`) | `claim:xaman_ledger_transaction_matches_approved_intent` | `claims` | `source_code` (`heuristic`) | Fixture-covered |
| `auth_component` | `src/screens/Overlay/Authenticate/*`, `src/screens/Overlay/PassphraseAuthentication/*` | `XamanSourceExtractor` (category `auth_component`) | `claim:xaman_auth_component_blocks_unauthenticated_signing` | `policies`, `claims`, `disproof_vectors` (`UNKNOWN`) | `source_code` (`heuristic`), `policy_doc` | Fixture-covered |
| `service` | `src/services/*` | `XamanSourceExtractor` (category `service`) | `claim:xaman_service_backend_calls_are_authenticated` | `claims` | `source_code` (`heuristic`) | Fixture-covered |
| `store` | `src/store/*` | `XamanSourceExtractor` (category `store`) | `claim:xaman_store_never_persists_raw_seed` | `claims` | `source_code` (`heuristic`) | Fixture-covered |
| `e2e_flow` | `e2e/*.feature` | `XamanSourceExtractor` (category `e2e_flow`) | `claim:xaman_e2e_flow_covers_signing_lifecycle` | `claims`, `runtime_traces` | `test_fixture` | Fixture-covered |

Fixture: `ir.examples.example_xaman_wallet_security_model()` instantiates
every row above with one claim per domain so
`validate_domain_coverage(model, required_domains=XAMAN_SECURITY_DOMAINS)`
passes.

## Fail-closed coverage gate

`ir.schema.check_domain_coverage(model, required_domains=...)` returns the
sorted list of domains from `required_domains` (default
`KNOWN_SECURITY_DOMAINS`, i.e. every row in both tables above) that have
zero `claims` entries. `ir.schema.validate_domain_coverage(model, ...)`
wraps that check and raises `ValueError` when the list is non-empty, so any
pipeline that calls it fails closed rather than silently shipping an
under-modeled domain.

`ir.canonicalize.canonicalize_domain_coverage_report(model,
required_domains=..., fail_closed=True)` produces a deterministic,
CID-addressable JSON coverage report and enforces the same fail-closed
behavior for artifact-producing pipelines (for example the assurance
baseline emitted by `scripts/ops/security_verification/run_security_ir_assurance_baseline.py`).

`tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py`
enforces, in CI:

1. `PRODUCTION_SECURITY_DOMAINS` and `XAMAN_SECURITY_DOMAINS` stay in sync
   with `prove_all.CLAIM_DOMAINS` and
   `XamanSourceExtractor._security_category`, so this document cannot
   silently drift from the executable domain vocabulary.
2. `example_minimal_exchange_model()` satisfies
   `validate_domain_coverage(..., required_domains=PRODUCTION_SECURITY_DOMAINS)`.
3. `example_xaman_wallet_security_model()` satisfies
   `validate_domain_coverage(..., required_domains=XAMAN_SECURITY_DOMAINS)`.
4. The combined claim set from both fixtures satisfies
   `validate_domain_coverage(..., required_domains=KNOWN_SECURITY_DOMAINS)`.
5. Every domain listed in this matrix's two tables appears in
   `KNOWN_SECURITY_DOMAINS`, and every domain in `KNOWN_SECURITY_DOMAINS`
   appears in this matrix (so a newly added domain cannot ship without an
   evidence-matrix row).
6. Removing a domain's claim from a fixture causes
   `validate_domain_coverage` to raise `ValueError` (proving the gate is
   actually fail-closed, not merely advisory).

## Maintenance

When a new production claim or Xaman corpus category is added:

1. Add the domain to `ir.schema.PRODUCTION_SECURITY_DOMAINS` or
   `ir.schema.XAMAN_SECURITY_DOMAINS`.
2. Add a row to the relevant table above with the extractor, a
   representative claim id, the IR fields it populates, and its evidence
   kind(s).
3. Add at least one `claims` entry for that domain to
   `ir.examples.example_minimal_exchange_model()` or
   `ir.examples.example_xaman_wallet_security_model()` (or a new fixture)
   so `test_code_to_ir_coverage.py` continues to pass.
4. Re-run the validation command below before merging.

## Validation

```
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_ir_schema.py \
  tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py -q
```
