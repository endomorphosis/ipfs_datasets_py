# Security IR v1 compatibility surface

Status: frozen legacy compatibility contract  
Interface: `SecurityIRLegacyCompatibility@1`  
Implementation: `ipfs_datasets_py.logic.security_models.crypto_exchange`

This document inventories the public Security IR surface that existed before
the IR-family refactor. The accompanying contract test makes the inventory
executable. This freeze preserves compatibility; it does not approve the
legacy model's semantics, make optional solvers authoritative, or promote
runtime observations into proofs.

## Compatibility window

These imports and behaviors remain supported throughout the Security IR v1
strangler migration. They must not be removed until a replacement facade has
shipped with an announced deprecation period of at least two tagged releases.
Additions are allowed only with a deliberate update to this inventory and its
contract test. A migration may re-export or adapt these values, but callers
using the paths below must continue to observe the frozen behavior.

## Public Python namespaces

The primary facade is:

```python
from ipfs_datasets_py.logic.security_models import crypto_exchange
```

Its exact `__all__` inventory is:

| Kind | Names |
| --- | --- |
| Model and assumptions | `SecurityModelIR`, `DEFAULT_THREAT_MODEL_ASSUMPTIONS` |
| Canonicalization and identity | `canonicalize_ir`, `canonicalize_ir_json`, `calculate_model_cid` |
| Validation | `validate_ir` |
| Reports and receipts | `ProofReport`, `ProofReceipt` |
| Runtime monitoring | `RuntimeMTLMonitor`, `check_runtime_properties` |
| Projection | `SecurityIRFeatureLoopProjector` |
| Runners | `Z3Runner` |
| Claims and examples | `default_claims`, `example_minimal_exchange_model` |
| Policies | `ReleasePolicyEntry`, `release_policy_entries`, `evaluate_release_policy`, `evaluate_assumption_registry`, `evaluate_evidence_promotion_workflow` |

The following subordinate namespaces are also public:

| Namespace | Frozen exports |
| --- | --- |
| `crypto_exchange.ir` | `DEFAULT_THREAT_MODEL_ASSUMPTIONS`, `KNOWN_SECURITY_DOMAINS`, `PRODUCTION_SECURITY_DOMAINS`, `XAMAN_SECURITY_DOMAINS`, `SecurityModelIR`, `calculate_model_cid`, `canonicalize_domain_coverage_report`, `canonicalize_domain_coverage_report_json`, `canonicalize_ir`, `canonicalize_ir_json`, `check_domain_coverage`, `claim_domains`, `domain_coverage_report`, `example_minimal_exchange_model`, `example_xaman_wallet_security_model`, `validate_domain_coverage`, `validate_ir` |
| `crypto_exchange.claims` | `AuditEventExistsForCriticalTransitionClaim`, `CapabilityDelegationMonotonicityClaim`, `NoDepositCreditedBeforeFinalityClaim`, `GlobalAssetConservationClaim`, `NoOverReservedInternalAccountClaim`, `NoSigningAfterWalletFreezeClaim`, `NoUnauthorizedWithdrawalClaim`, `RevokedCapabilityClaim`, `SecurityClaim`, `default_claims` |
| `crypto_exchange.extractors` | `SecurityIRFeatureLoopProjector`, `LogTraceExtractor`, `OpenAPIExtractor`, `PythonASTExtractor`, `SourceCodeExtractor`, `TypeScriptSchemaEmitter`, `UCANPolicyExtractor`, `XamanRuntimeTraceIngestor`, `XamanSourceExtractor` |
| `crypto_exchange.monitors` | `RuntimeMTLMonitor`, `check_runtime_properties` |
| `crypto_exchange.reports` | `CounterexampleReport`, `ProofReceipt`, `ProofReport`, `XamanProofConsumerError`, `build_xaman_assurance_packet`, `build_xaman_production_blocker_bridge`, `build_xaman_proof_consumer_report`, `build_xaman_testnet_assurance_bundle`, `build_xaman_testnet_assurance_verdict`, `build_xaman_testnet_solver_portfolio_manifest`, `build_xaman_testnet_solver_portfolio_report`, `validate_xaman_proof_consumer_packet` |
| `crypto_exchange.runners` | `BaseSecurityRunner`, `CVC5Runner`, `Z3Runner` |

These supported module-level imports complete the validation and identity
surface even though they are not re-exported by the primary facade:

- `ir.cid.calculate_artifact_cid`
- `ir.schema.validate_ir_payload`
- `ir.schema.check_domain_coverage`
- `ir.schema.validate_domain_coverage`
- `reports.proof_report.validate_proof_report`
- `reports.proof_receipt.validate_proof_receipt`
- `release_policy.release_policy_for_claim`
- `prove_all.main`

## Frozen data and behavior contracts

### `SecurityModelIR`

`SecurityModelIR` remains a slotted dataclass with fields in this order:

1. `schema_version`
2. `model_id`
3. `entities`
4. `assets`
5. `wallets`
6. `accounts`
7. `roles`
8. `principals`
9. `capabilities`
10. `policies`
11. `events`
12. `state_machines`
13. `invariants`
14. `claims`
15. `proof_obligations`
16. `disproof_vectors`
17. `runtime_traces`
18. `solver_results`
19. `assumptions`
20. `prover_targets`
21. `metadata`

`to_dict()`, `from_dict()`, and `from_untrusted_dict()` remain supported.
`validate_ir()` returns a normalized `SecurityModelIR` and fails closed on
invalid collection shapes, identifiers, references, policies, claims,
events, assumptions, evidence, and prover targets. Domain coverage helpers
remain a separate proof-readiness gate.

### Canonicalization and identifiers

`canonicalize_ir_json()` validates first, recursively sorts mapping keys, uses
compact ASCII JSON, and preserves list order. `canonicalize_ir()` returns its
UTF-8 bytes. `calculate_model_cid()` hashes those canonical bytes.
`calculate_artifact_cid()` hashes compact, key-sorted JSON for a JSON-like
artifact.

Both identifier functions use `ipfs_datasets_py.utils.cid_utils.cid_for_bytes`
when that optional implementation is callable. If it is unavailable or
rejects the payload, the legacy result is `sha256:<lowercase hex digest>`.
Both representations are therefore compatible legacy identifiers; callers
must not infer which representation is available from the model alone.

### Reports and receipts

`ProofReport` retains the schema `proof-report/v1`, the statuses `PROVED`,
`DISPROVED`, `UNKNOWN`, and `NOT_MODELED`, deterministic and nondeterministic
payload CIDs, serialization helpers, and CID integrity validation.

`ProofReceipt` retains the schema `proof-receipt/v1`. `from_report()` accepts
only configured statuses and explicitly accepted assumptions by default,
binds the receipt to the report CID, and produces a valid consumer receipt.
Deriving accepted assumptions from a report remains an explicitly unsafe,
test-only opt-in.

### Monitors and projector

`RuntimeMTLMonitor.check_all()` resets and returns violations for:

- non-monotonic event timestamps;
- signing after wallet freeze;
- approved withdrawals without timely broadcast or cancellation;
- deposit credit before finality; and
- privileged action after capability revocation.

`check_runtime_properties()` is the convenience wrapper for the same checks.

`SecurityIRFeatureLoopProjector.project_model()` validates the model and emits
`security-ir-feature-loop/v1` with the model identity, ingestion principles,
feature counts, deterministic feature lists, and the eight default synthesis
claims. `project_path()` remains the source-autoformalization entry point.

### Runners

`BaseSecurityRunner`, `Z3Runner`, and `CVC5Runner` retain their runner
contracts and prover names `unknown`, `z3`, and `cvc5`. Missing solvers map to
non-secure `UNKNOWN` reports; availability is not proof success. Z3 Python
bindings and the CVC5 executable remain optional environment dependencies.

### Policies, examples, and claims

The default release policy contains these claim/gate pairs:

| Claim | Gate |
| --- | --- |
| `no_unauthorized_withdrawal` | `blocking` |
| `no_over_reserved_internal_account` | `blocking` |
| `global_asset_conservation` | `blocking` |
| `no_deposit_before_finality` | `high` |
| `no_signing_request_after_wallet_freeze` | `high` |
| `capability_delegation_no_authority_increase` | `high` |
| `revoked_capability_no_future_authorization` | `high` |
| `audit_event_exists_for_critical_transition` | `medium` |

Missing blocking/high reports and their fail-closed statuses prevent release.
Assumption freshness and evidence-promotion evaluators remain independent
policy reports exposed by the primary facade.

`example_minimal_exchange_model()` returns model
`minimal-btc-exchange`; `example_xaman_wallet_security_model()` returns
`xaman-app-wallet-security`. Both use schema `security-model-ir/v1`. The
ordered claim IDs returned by `default_claims()` are the eight policy claim
IDs in the table above.

## CLI compatibility

The legacy entry point remains:

```bash
python -m ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all
```

`prove_all.main(argv)` retains these exit classes:

| Exit | Meaning |
| --- | --- |
| `0` | The selected run completed and no requested failure gate fired. This is not automatically a production-security verdict. |
| `1` | A requested proof, coverage, agreement, release, assumption, or domain gate failed. |
| `2` | An execution dependency policy was violated, such as forbidden simulated F-logic or ZKP use. |
| argparse `SystemExit(2)` | CLI arguments or explicit assumption management were invalid. |

JSON is printed to stdout unless `--out` is supplied. Solver absence,
`UNKNOWN`, and `NOT_MODELED` remain explicit report outcomes; whether they
produce exit `1` depends on the requested fail-closed gates.

## Registry discovery

`ipfs_datasets_py.logic.submodule_registry` must continue to discover the
required entry named `security_models`:

- module: `ipfs_datasets_py.logic.security_models`
- roles: `security_models`, `proof`, `policy`, `runtime_monitor`
- optimizer component: `security_models.crypto_exchange`
- AST scope: `security_models`
- public discovery symbols: `SecurityModelIR`, `ProofReport`, `ProofReceipt`,
  `RuntimeMTLMonitor`
- import checking: enabled

The entry must remain present in `logic_submodule_names()`,
`logic_submodule_spec()`, and `logic_integration_manifest()`.

## Executable receipt

The compatibility receipt is
`tests/unit/logic/security_models/crypto_exchange/test_public_api_freeze.py`.
It intentionally does not invoke an optional solver, mutate registry state, or
write promoted artifacts.
