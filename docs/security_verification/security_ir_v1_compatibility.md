# Security IR v1 compatibility surface

Status: frozen legacy compatibility inventory

Interface: `SecurityIRLegacyCompatibility@1`

Scope: `ipfs_datasets_py.logic.security_models.crypto_exchange`

## Purpose

This document records the Security IR Python and command-line surface that
existed before the IR-family refactor. The accompanying contract test makes
the inventory executable. The freeze preserves compatibility; it does not
approve the legacy model's mutability, solver coupling, optional-dependency
CID variance, or proof-authority semantics.

Production modules, package exports, registry declarations, promoted
artifacts, and CLI behavior are deliberately unchanged by this freeze.
Golden payload fixtures and exact promoted artifact bytes belong to the
follow-up Security IR v1 corpus task.

## Curated Python imports

The primary compatibility namespace is:

```python
from ipfs_datasets_py.logic.security_models import crypto_exchange
from ipfs_datasets_py.logic.security_models.crypto_exchange import (
    DEFAULT_THREAT_MODEL_ASSUMPTIONS,
    ProofReceipt,
    ProofReport,
    ReleasePolicyEntry,
    RuntimeMTLMonitor,
    SecurityIRFeatureLoopProjector,
    SecurityModelIR,
    Z3Runner,
    calculate_model_cid,
    canonicalize_ir,
    canonicalize_ir_json,
    check_runtime_properties,
    default_claims,
    evaluate_assumption_registry,
    evaluate_evidence_promotion_workflow,
    evaluate_release_policy,
    example_minimal_exchange_model,
    release_policy_entries,
    validate_ir,
)
```

The following subpackages also have frozen curated exports:

| Namespace | Compatibility surface |
| --- | --- |
| `crypto_exchange.ir` | `SecurityModelIR`; threat/domain constants; model and domain-report canonicalizers; model CID; domain coverage helpers and validators; minimal exchange and Xaman example builders |
| `crypto_exchange.claims` | `SecurityClaim`; eight concrete default claim classes; `default_claims` |
| `crypto_exchange.reports` | `ProofReport`, `ProofReceipt`, `CounterexampleReport`; the currently exported Xaman report builders and proof-consumer validator |
| `crypto_exchange.monitors` | `RuntimeMTLMonitor`, `check_runtime_properties` |
| `crypto_exchange.runners` | `BaseSecurityRunner`, `Z3Runner`, `CVC5Runner` |
| `crypto_exchange.extractors` | `SecurityIRFeatureLoopProjector` and the current source, trace, OpenAPI, UCAN, TypeScript, Python, and Xaman extractors |

Some established call sites use direct module imports that are not re-exported
from the package root. These remain part of the reviewed compatibility
inventory:

- `ir.schema`: `validate_ir_payload`, `validate_ir`,
  `validate_event_registry`, `validate_state_machines`,
  `validate_domain_coverage`, and the domain coverage queries.
- `ir.cid`: `calculate_artifact_cid` and `calculate_model_cid`.
- `reports.proof_report`: `ProofReport` and `validate_proof_report`.
- `reports.proof_receipt`: `ProofReceipt` and `validate_proof_receipt`.
- `release_policy`: release-policy entries/evaluation and the frozen security
  decision outcome builder, classifier, and validator.
- `prove_all`: `prove_claims`, `compare_prover_reports`, and `main`.

Adding new names does not implicitly make them part of this v1 contract.
Removing, renaming, moving, or changing the identity of an inventoried symbol
requires an explicit compatibility decision.

## Data and behavior contracts

### `SecurityModelIR`

`SecurityModelIR` remains a slotted mutable dataclass with these fields, in
order:

```text
schema_version, model_id, entities, assets, wallets, accounts, roles,
principals, capabilities, policies, events, state_machines, invariants,
claims, proof_obligations, disproof_vectors, runtime_traces, solver_results,
assumptions, prover_targets, metadata
```

The compatibility constructors are `from_dict` and
`from_untrusted_dict(..., strict=True)`, serialization is `to_dict`, and
`validate_ir` returns a validated `SecurityModelIR`. Strict payload validation
rejects unknown and missing top-level fields. The default schema used by the
examples is `security-model-ir/v1`.

### Canonical bytes and identifiers

`canonicalize_ir_json` validates the model, recursively sorts mapping keys,
preserves list order, emits compact ASCII JSON, and
`canonicalize_ir` returns its UTF-8 bytes.

`calculate_model_cid` addresses those canonical bytes. Current behavior has
two environment-dependent representations:

1. when `ipfs_datasets_py.utils.cid_utils.cid_for_bytes` is importable and
   succeeds, its CID string is returned;
2. when that optional path is unavailable or raises one of its handled
   dependency/value/type errors, `sha256:<lowercase hex>` is returned.

This variance is frozen as legacy behavior, not selected as the future shared
identity profile. `calculate_artifact_cid` applies the same addressing choice
to compact, key-sorted ASCII JSON.

### Reports and receipts

`ProofReport` retains `proof-report/v1`, the statuses `PROVED`, `DISPROVED`,
`UNKNOWN`, and `NOT_MODELED`, and the risk levels `blocking`, `high`,
`medium`, and `low`. It exposes deterministic and nondeterministic payload
CIDs, `to_dict`/`from_dict`/`from_untrusted_dict`, `cid`, and
`validate_proof_report`.

`ProofReceipt` retains `proof-receipt/v1`,
`to_dict`/`from_dict`/`from_untrusted_dict`, `validate_report`, `from_report`,
and `validate_proof_receipt`. Receipt construction requires explicit accepted
assumptions unless the existing unsafe test-only report-assumption option is
selected.

### Claims, runners, monitors, projector, validators, and policies

The default claim order is:

1. `no_unauthorized_withdrawal`
2. `no_over_reserved_internal_account`
3. `global_asset_conservation`
4. `no_deposit_before_finality`
5. `no_signing_request_after_wallet_freeze`
6. `capability_delegation_no_authority_increase`
7. `revoked_capability_no_future_authorization`
8. `audit_event_exists_for_critical_transition`

The same order binds the default release policy. The first three claims are
blocking, the next four are high, and audit linkage is medium.

`BaseSecurityRunner.run_claim` remains the runner contract. `Z3Runner` and
`CVC5Runner` retain their prover names, timeout constructor argument, and
`ProofReport` return type. Availability checks may provision optional solver
dependencies, so the freeze test exercises their no-solver `UNKNOWN` report
path instead.

`RuntimeMTLMonitor` retains event-ordering, post-freeze signing,
withdrawal-completion, deposit-finality, and post-revocation checks.
`check_all` and `check_runtime_properties` return violation dictionaries.

`SecurityIRFeatureLoopProjector.project_model` retains the
`security-ir-feature-loop/v1` projection and its model identity, feature
counts, extracted features, ingestion principles, and default-claim synthesis
section.

The validation compatibility surface includes model/payload/domain
validators, proof report and receipt integrity validators, assumption and
reviewed-evidence policy evaluators, release-policy evaluation, and the
security-decision policy validator. A non-`prove` result for a blocking claim
continues to classify as non-secure.

## Command-line compatibility

The canonical proof command and its ops wrapper are:

```text
python -m ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all
python scripts/ops/security_verification/run_security_ir_proof_suite.py
```

Their exit contract is:

| Exit | Meaning |
| --- | --- |
| `0` | Invocation completed and no selected fail-closed condition fired |
| `1` | Invocation completed but a selected proof, coverage, agreement, release, assumption, or required-domain gate failed |
| `2` | Argument/model validation or an execution-policy precondition failed |

`argparse` usage errors raise `SystemExit(2)`. Solver results are not needed to
test this exit mapping: the contract test substitutes an empty report set and
exercises a passing invocation, a failing minimum-coverage gate, and an
unsupported-prover argument.

The current supporting CLIs remain discoverable at:

- `scripts/ops/security_verification/autoformalize_security_ir.py`
- `scripts/ops/security_verification/project_security_ir_feature_loop.py`
- `scripts/ops/security_verification/emit_security_typescript_schema.py`
- `scripts/ops/security_verification/run_security_ir_proof_suite.py`

They continue to use `0` for successful generation and argparse's `2` for
usage errors. This freeze adds no console-script registration.

## `submodule_registry` discovery

`logic.submodule_registry.logic_submodule_spec("security_models")` continues
to identify:

```text
module: ipfs_datasets_py.logic.security_models
roles: security_models, proof, policy, runtime_monitor
optimizer component: security_models.crypto_exchange
public symbols: SecurityModelIR, ProofReport, ProofReceipt, RuntimeMTLMonitor
```

The target-file hints remain the `security_models` package initializer, the
`crypto_exchange` initializer, `ir/schema.py`, and `runners/z3_runner.py`.
The entry is present in `logic_integration_manifest`, and
`logic_submodule_import_report` imports it successfully.

## Executable evidence

Run:

```text
python -m pytest tests/unit/logic/security_models/crypto_exchange/test_public_api_freeze.py -q
```

The test inventories exact curated exports and exercises model validation,
canonicalization, both legacy identifier branches, report and receipt
integrity, monitors, examples, claims, the projector, runners, policies,
proof-CLI exit behavior, and registry discovery. It neither invokes a solver
nor mutates production code or checked-in Security IR artifacts.
