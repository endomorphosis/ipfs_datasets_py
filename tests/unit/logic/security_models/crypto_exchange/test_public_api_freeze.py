"""Executable compatibility contract for the legacy Security IR v1 surface."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import fields

import pytest

from ipfs_datasets_py.logic.security_models import crypto_exchange
from ipfs_datasets_py.logic.security_models.crypto_exchange import (
    SecurityIRFeatureLoopProjector,
    SecurityModelIR,
    canonicalize_ir,
    canonicalize_ir_json,
    check_runtime_properties,
    default_claims,
    example_minimal_exchange_model,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange import claims, extractors, ir, monitors, reports, runners
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir import cid as cid_module
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_xaman_wallet_security_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    check_domain_coverage,
    validate_domain_coverage,
    validate_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
    evaluate_release_policy,
    release_policy_entries,
    release_policy_for_claim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import (
    ProofReceipt,
    validate_proof_receipt,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import (
    ProofReport,
    validate_proof_report,
)


EXPECTED_CLAIM_IDS = [
    "no_unauthorized_withdrawal",
    "no_over_reserved_internal_account",
    "global_asset_conservation",
    "no_deposit_before_finality",
    "no_signing_request_after_wallet_freeze",
    "capability_delegation_no_authority_increase",
    "revoked_capability_no_future_authorization",
    "audit_event_exists_for_critical_transition",
]


def test_public_namespace_exports_are_frozen() -> None:
    assert crypto_exchange.__all__ == [
        "DEFAULT_THREAT_MODEL_ASSUMPTIONS",
        "ProofReceipt",
        "ProofReport",
        "ReleasePolicyEntry",
        "RuntimeMTLMonitor",
        "SecurityIRFeatureLoopProjector",
        "SecurityModelIR",
        "Z3Runner",
        "calculate_model_cid",
        "canonicalize_ir",
        "canonicalize_ir_json",
        "check_runtime_properties",
        "default_claims",
        "evaluate_assumption_registry",
        "evaluate_evidence_promotion_workflow",
        "evaluate_release_policy",
        "example_minimal_exchange_model",
        "release_policy_entries",
        "validate_ir",
    ]
    assert ir.__all__ == [
        "DEFAULT_THREAT_MODEL_ASSUMPTIONS",
        "KNOWN_SECURITY_DOMAINS",
        "PRODUCTION_SECURITY_DOMAINS",
        "XAMAN_SECURITY_DOMAINS",
        "SecurityModelIR",
        "calculate_model_cid",
        "canonicalize_domain_coverage_report",
        "canonicalize_domain_coverage_report_json",
        "canonicalize_ir",
        "canonicalize_ir_json",
        "check_domain_coverage",
        "claim_domains",
        "domain_coverage_report",
        "example_minimal_exchange_model",
        "example_xaman_wallet_security_model",
        "validate_domain_coverage",
        "validate_ir",
    ]
    assert claims.__all__ == [
        "AuditEventExistsForCriticalTransitionClaim",
        "CapabilityDelegationMonotonicityClaim",
        "NoDepositCreditedBeforeFinalityClaim",
        "GlobalAssetConservationClaim",
        "NoOverReservedInternalAccountClaim",
        "NoSigningAfterWalletFreezeClaim",
        "NoUnauthorizedWithdrawalClaim",
        "RevokedCapabilityClaim",
        "SecurityClaim",
        "default_claims",
    ]
    assert extractors.__all__ == [
        "SecurityIRFeatureLoopProjector",
        "LogTraceExtractor",
        "OpenAPIExtractor",
        "PythonASTExtractor",
        "SourceCodeExtractor",
        "TypeScriptSchemaEmitter",
        "UCANPolicyExtractor",
        "XamanRuntimeTraceIngestor",
        "XamanSourceExtractor",
    ]
    assert monitors.__all__ == ["RuntimeMTLMonitor", "check_runtime_properties"]
    assert reports.__all__ == [
        "CounterexampleReport",
        "ProofReceipt",
        "ProofReport",
        "XamanProofConsumerError",
        "build_xaman_assurance_packet",
        "build_xaman_production_blocker_bridge",
        "build_xaman_proof_consumer_report",
        "build_xaman_testnet_assurance_bundle",
        "build_xaman_testnet_assurance_verdict",
        "build_xaman_testnet_solver_portfolio_manifest",
        "build_xaman_testnet_solver_portfolio_report",
        "validate_xaman_proof_consumer_packet",
    ]
    assert runners.__all__ == ["BaseSecurityRunner", "CVC5Runner", "Z3Runner"]

    for namespace in (crypto_exchange, ir, claims, extractors, monitors, reports, runners):
        for name in namespace.__all__:
            assert getattr(namespace, name) is not None


def test_security_model_ir_shape_round_trip_and_validators_are_frozen() -> None:
    assert [item.name for item in fields(SecurityModelIR)] == [
        "schema_version",
        "model_id",
        "entities",
        "assets",
        "wallets",
        "accounts",
        "roles",
        "principals",
        "capabilities",
        "policies",
        "events",
        "state_machines",
        "invariants",
        "claims",
        "proof_obligations",
        "disproof_vectors",
        "runtime_traces",
        "solver_results",
        "assumptions",
        "prover_targets",
        "metadata",
    ]

    model = SecurityModelIR(
        schema_version="security-model-ir/v1",
        model_id="freeze-model",
        assumptions=["A1"],
    )
    assert validate_ir(model) is model
    assert SecurityModelIR.from_dict(model.to_dict()).to_dict() == model.to_dict()

    untrusted = model.to_dict()
    untrusted["unknown_field"] = True
    with pytest.raises(ValueError, match="Unknown top-level SecurityModelIR field"):
        SecurityModelIR.from_untrusted_dict(untrusted)

    exchange = example_minimal_exchange_model()
    assert check_domain_coverage(exchange, required_domains={"withdrawals"}) == []
    assert validate_domain_coverage(exchange, required_domains={"withdrawals"}) is exchange
    assert check_domain_coverage(exchange, required_domains={"vault"}) == ["vault"]
    with pytest.raises(ValueError, match="missing claim coverage.*vault"):
        validate_domain_coverage(exchange, required_domains={"vault"})


def test_canonicalization_and_both_legacy_identifier_paths_are_frozen(monkeypatch) -> None:
    model = SecurityModelIR(
        schema_version="security-model-ir/v1",
        model_id="freeze-model",
        assumptions=["A1"],
    )
    expected_json = (
        '{"accounts":[],"assets":[],"assumptions":["A1"],"capabilities":[],"claims":[],'
        '"disproof_vectors":[],"entities":[],"events":[],"invariants":[],"metadata":{},'
        '"model_id":"freeze-model","policies":[],"principals":[],"proof_obligations":[],'
        '"prover_targets":["z3"],"roles":[],"runtime_traces":[],'
        '"schema_version":"security-model-ir/v1","solver_results":[],"state_machines":[],'
        '"wallets":[]}'
    )
    assert canonicalize_ir_json(model) == expected_json
    assert canonicalize_ir(model) == expected_json.encode("utf-8")

    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: None)
    expected_fallback = f"sha256:{hashlib.sha256(expected_json.encode('utf-8')).hexdigest()}"
    assert cid_module.calculate_model_cid(model) == expected_fallback

    artifact_bytes = b'{"a":1,"b":2}'
    assert cid_module.calculate_artifact_cid({"b": 2, "a": 1}) == (
        f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    )

    seen: list[bytes] = []

    def _fake_cid(payload: bytes) -> str:
        seen.append(payload)
        return "cid:optional-implementation"

    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: _fake_cid)
    assert cid_module.calculate_model_cid(model) == "cid:optional-implementation"
    assert seen == [expected_json.encode("utf-8")]


def _proof_report(**overrides: object) -> ProofReport:
    payload: dict[str, object] = {
        "claim_id": "no_unauthorized_withdrawal",
        "claim_version": "1.0",
        "model_cid": "cid:model",
        "model_schema_version": "security-model-ir/v1",
        "status": "PROVED",
        "prover": "contract-runner",
        "solver_name": "contract-runner",
        "solver_version": "1.0",
        "solver_result": "unsat",
        "proof_or_trace_cid": "cid:proof",
        "assumptions": ["A1"],
        "compiler_cid": "cid:compiler",
        "created_at": "2026-07-24T00:00:00+00:00",
        "risk": "blocking",
        "signatures": [],
        "evidence_refs": [
            {
                "kind": "test_fixture",
                "path": "test_public_api_freeze.py",
                "review_status": "trusted_fixture",
            }
        ],
        "soundness_notes": [],
    }
    payload.update(overrides)
    return ProofReport(**payload)  # type: ignore[arg-type]


def test_proof_report_and_receipt_contracts_are_frozen() -> None:
    report = _proof_report()
    assert report.schema_version == "proof-report/v1"
    assert report.generated_at == "2026-07-24T00:00:00+00:00"
    assert report.cid == report.nondeterministic_report_cid
    assert report.verify_report_cids() is True
    assert validate_proof_report(report) is report

    decoded = ProofReport.from_untrusted_dict(report.to_dict())
    assert decoded.to_dict() == report.to_dict()

    receipt = ProofReceipt.from_report(
        report,
        accepted_assumptions=["A1"],
        verifier="contract-consumer",
        verifier_version="1.0",
    )
    assert receipt.schema_version == "proof-receipt/v1"
    assert receipt.report_schema_version == "proof-report/v1"
    assert receipt.proof_report_cid == report.cid
    assert receipt.valid is True
    assert validate_proof_receipt(receipt) is receipt
    assert ProofReceipt.from_untrusted_dict(receipt.to_dict(), report=report).to_dict() == receipt.to_dict()

    tampered = report.to_dict()
    tampered["claim_id"] = "tampered"
    with pytest.raises(ValueError, match="deterministic_payload_cid does not match"):
        ProofReport.from_untrusted_dict(tampered)


def test_runtime_monitor_contract_is_frozen() -> None:
    events = [
        {"event": "wallet_frozen", "wallet_id": "wallet:1", "timestamp": 1},
        {"event": "signing_request", "wallet_id": "wallet:1", "timestamp": 2},
        {"event": "withdrawal_approved", "withdrawal_id": "withdrawal:1", "timestamp": 3},
        {"event": "deposit_credited", "deposit_id": "deposit:1", "timestamp": 4},
        {"event": "capability_revoked", "capability_id": "capability:1", "timestamp": 5},
        {"event": "privileged_action", "capability_id": "capability:1", "timestamp": 6},
    ]
    violations = check_runtime_properties(events)
    assert [item["property"] for item in violations] == [
        "wallet_frozen -> no future signing_request",
        "withdrawal_approved -> eventually broadcast_or_cancelled",
        "deposit_observed -> credited only after finality",
        "capability_revoked -> no privileged action after revocation",
    ]
    assert monitors.RuntimeMTLMonitor(events).check_all() == violations

    ordering_violations = check_runtime_properties(
        [
            {"event": "custom_event", "timestamp": 2},
            {"event": "custom_event", "timestamp": 1},
        ]
    )
    assert [item["property"] for item in ordering_violations] == [
        "event ordering is monotonic when timestamps exist"
    ]


def test_feature_loop_projector_contract_is_frozen() -> None:
    projection = SecurityIRFeatureLoopProjector().project_model(example_minimal_exchange_model())
    assert list(projection) == [
        "projection_kind",
        "model_id",
        "model_cid",
        "ingestion_principles",
        "feature_counts",
        "features",
        "codex_program_synthesis",
    ]
    assert projection["projection_kind"] == "security-ir-feature-loop/v1"
    assert projection["model_id"] == "minimal-btc-exchange"
    assert projection["feature_counts"] == {
        "entities": 2,
        "policies": 9,
        "events": 13,
        "invariants": 3,
        "assumptions": 10,
    }
    assert list(projection["features"]) == [
        "languages",
        "source_inputs",
        "entity_names",
        "principal_ids",
        "capability_ids",
        "policy_names",
        "critical_events",
        "invariant_descriptions",
        "assumption_ids",
        "prover_targets",
    ]
    assert [
        item["claim_id"]
        for item in projection["codex_program_synthesis"]["claims"]
    ] == EXPECTED_CLAIM_IDS


def test_runner_contracts_do_not_require_optional_solvers() -> None:
    class ContractRunner(runners.BaseSecurityRunner):
        prover_name = "contract"

        def run_claim(self, claim, model):
            return self.unknown_report(claim, model, "solver intentionally absent")

    assert runners.BaseSecurityRunner.prover_name == "unknown"
    assert runners.Z3Runner.prover_name == "z3"
    assert runners.CVC5Runner.prover_name == "cvc5"
    assert runners.Z3Runner(timeout_ms=123).timeout_ms == 123
    cvc5 = runners.CVC5Runner(timeout_ms=456, executable="/definitely/not/cvc5")
    assert (cvc5.timeout_ms, cvc5.executable) == (456, "/definitely/not/cvc5")

    report = ContractRunner().run_claim(default_claims()[0], example_minimal_exchange_model())
    assert report.status == "UNKNOWN"
    assert report.solver_result == "unknown"
    assert report.reason_unknown == "solver intentionally absent"
    assert report.counterexample == {"reason": "solver intentionally absent"}


def test_default_examples_claims_and_policies_are_frozen() -> None:
    exchange = example_minimal_exchange_model()
    xaman = example_xaman_wallet_security_model()
    assert (exchange.schema_version, exchange.model_id) == (
        "security-model-ir/v1",
        "minimal-btc-exchange",
    )
    assert (xaman.schema_version, xaman.model_id) == (
        "security-model-ir/v1",
        "xaman-app-wallet-security",
    )
    assert validate_ir(exchange) is exchange
    assert validate_ir(xaman) is xaman
    assert [claim.claim_id for claim in default_claims()] == EXPECTED_CLAIM_IDS

    expected_gates = {
        "no_unauthorized_withdrawal": "blocking",
        "no_over_reserved_internal_account": "blocking",
        "global_asset_conservation": "blocking",
        "no_deposit_before_finality": "high",
        "no_signing_request_after_wallet_freeze": "high",
        "capability_delegation_no_authority_increase": "high",
        "revoked_capability_no_future_authorization": "high",
        "audit_event_exists_for_critical_transition": "medium",
    }
    assert {
        entry.claim_id: entry.release_gate
        for entry in release_policy_entries()
    } == expected_gates
    assert release_policy_for_claim("global_asset_conservation").release_gate == "blocking"

    decision = evaluate_release_policy([])
    assert decision["release_ready"] is False
    assert len(decision["failures"]) == 7
    assert len(decision["attention"]) == 1

    assumption_decision = crypto_exchange.evaluate_assumption_registry(
        exchange,
        required_assumptions=["A1"],
        accepted_assumptions=["A1"],
        as_of="2026-07-24T00:00:00Z",
    )
    assert assumption_decision["release_ready"] is True
    assert assumption_decision["summary"] == {
        "total": 1,
        "present": 1,
        "owned": 1,
        "evidenced": 1,
        "current": 1,
        "stale": 0,
        "accepted": 1,
    }

    promotion_decision = crypto_exchange.evaluate_evidence_promotion_workflow(
        {
            "schema_version": "crypto-exchange-evidence-promotion/v1",
            "evidence_reviews": [],
        },
        as_of="2026-07-24T00:00:00Z",
    )
    assert promotion_decision["release_ready"] is True
    assert promotion_decision["summary"] == {
        "total_reviews": 0,
        "promoted": 0,
        "quarantined": 0,
        "failures": 0,
    }


def test_prove_all_cli_exit_classes_are_frozen(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic.security_models.crypto_exchange import prove_all

    success_path = tmp_path / "success.json"
    monkeypatch.setattr(prove_all, "prove_claims", lambda model, provers: [])
    assert prove_all.main(["--example", "--out", str(success_path)]) == 0
    assert json.loads(success_path.read_text(encoding="utf-8"))["reports"] == []

    failure_path = tmp_path / "failure.json"
    monkeypatch.setattr(
        prove_all,
        "prove_claims",
        lambda model, provers: [
            _proof_report(
                status="DISPROVED",
                solver_result="sat",
                proof_or_trace_cid="cid:counterexample",
                counterexample={"witness": "frozen"},
            )
        ],
    )
    assert prove_all.main(
        ["--example", "--fail-on", "disproof", "--out", str(failure_path)]
    ) == 1

    policy_model = deepcopy(example_minimal_exchange_model())
    policy_model.metadata["proof_dependency_modes"] = {
        "flogic": "simulated",
        "zkp": "not-used",
    }
    monkeypatch.setattr(prove_all, "_load_model", lambda args: policy_model)
    assert prove_all.main(["--example", "--require-real-ergoai"]) == 2

    with pytest.raises(SystemExit) as exc_info:
        prove_all.main(["--example", "--model", "also-selected.json"])
    assert exc_info.value.code == 2


def test_submodule_registry_security_ir_discovery_is_frozen() -> None:
    from ipfs_datasets_py.logic.submodule_registry import (
        logic_integration_manifest,
        logic_submodule_names,
        logic_submodule_spec,
    )

    assert "security_models" in logic_submodule_names(required_only=True)
    spec = logic_submodule_spec("security_models")
    assert spec.module == "ipfs_datasets_py.logic.security_models"
    assert spec.required is True
    assert spec.import_check is True
    assert spec.roles == ("security_models", "proof", "policy", "runtime_monitor")
    assert spec.optimizer_components == ("security_models.crypto_exchange",)
    assert spec.ast_scope == "security_models"
    assert spec.public_symbols == (
        "SecurityModelIR",
        "ProofReport",
        "ProofReceipt",
        "RuntimeMTLMonitor",
    )

    manifest_entry = next(
        entry
        for entry in logic_integration_manifest()["submodules"]
        if entry["name"] == "security_models"
    )
    assert manifest_entry == spec.to_dict()
