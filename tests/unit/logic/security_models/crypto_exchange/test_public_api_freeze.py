"""Compatibility freeze for the legacy crypto-exchange Security IR surface.

This suite intentionally tests the existing API in place.  It must not be
used to justify changing the legacy implementation; later adapters depend on
these imports and observable results remaining available.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest

import ipfs_datasets_py.logic.security_models.crypto_exchange as security_ir
import ipfs_datasets_py.logic.security_models.crypto_exchange.claims as claims_api
import ipfs_datasets_py.logic.security_models.crypto_exchange.extractors as extractors_api
import ipfs_datasets_py.logic.security_models.crypto_exchange.ir as ir_api
import ipfs_datasets_py.logic.security_models.crypto_exchange.monitors as monitors_api
import ipfs_datasets_py.logic.security_models.crypto_exchange.reports as reports_api
import ipfs_datasets_py.logic.security_models.crypto_exchange.runners as runners_api
from ipfs_datasets_py.logic import submodule_registry
from ipfs_datasets_py.logic.security_models.crypto_exchange import prove_all
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir import cid as cid_module
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
    validate_ir_payload,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
    blocking_claim_is_secure_outcome,
    build_security_decision_policy,
    classify_release_consumer_outcome,
    decision_outcome_for_proof_status,
    security_decision_outcomes,
    validate_security_decision_policy,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import (
    ProofReceipt,
    validate_proof_receipt,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import (
    ProofReport,
    validate_proof_report,
)


ROOT_PUBLIC_SYMBOLS = [
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

IR_PUBLIC_SYMBOLS = [
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

CLAIM_IDS = [
    "no_unauthorized_withdrawal",
    "no_over_reserved_internal_account",
    "global_asset_conservation",
    "no_deposit_before_finality",
    "no_signing_request_after_wallet_freeze",
    "capability_delegation_no_authority_increase",
    "revoked_capability_no_future_authorization",
    "audit_event_exists_for_critical_transition",
]

SECURITY_MODEL_FIELDS = [
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

CANONICAL_COMPAT_MODEL = (
    '{"accounts":[],"assets":[],"assumptions":["A1"],"capabilities":[],"claims":[],'
    '"disproof_vectors":[],"entities":[],"events":[],"invariants":[],"metadata":{"a":2,"z":1},'
    '"model_id":"compat","policies":[],"principals":[],"proof_obligations":[],'
    '"prover_targets":["z3"],"roles":[],"runtime_traces":[],'
    '"schema_version":"security-model-ir/v1","solver_results":[],"state_machines":[],"wallets":[]}'
)


def _compat_model() -> SecurityModelIR:
    return SecurityModelIR(
        schema_version="security-model-ir/v1",
        model_id="compat",
        assumptions=["A1"],
        prover_targets=["z3"],
        metadata={"z": 1, "a": 2},
    )


def _proved_report() -> ProofReport:
    return ProofReport(
        claim_id="compat-claim",
        claim_version="1.0",
        model_cid="sha256:model",
        model_schema_version="security-model-ir/v1",
        status="PROVED",
        prover="compat-prover",
        solver_name="compat-solver",
        solver_version="1.2.3",
        solver_result="unsat",
        proof_or_trace_cid="sha256:proof",
        assumptions=["A1"],
        compiler_cid="sha256:compiler",
        created_at="2026-01-02T03:04:05+00:00",
        risk="blocking",
        signatures=[],
        evidence_refs=[],
        soundness_notes=[],
    )


def test_curated_package_exports_are_frozen() -> None:
    assert security_ir.__all__ == ROOT_PUBLIC_SYMBOLS
    assert ir_api.__all__ == IR_PUBLIC_SYMBOLS
    assert claims_api.__all__ == [
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
    assert monitors_api.__all__ == ["RuntimeMTLMonitor", "check_runtime_properties"]
    assert runners_api.__all__ == ["BaseSecurityRunner", "CVC5Runner", "Z3Runner"]
    assert extractors_api.__all__ == [
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
    assert reports_api.__all__ == [
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

    for symbol in ROOT_PUBLIC_SYMBOLS:
        assert getattr(security_ir, symbol) is not None
    assert security_ir.SecurityModelIR is ir_api.SecurityModelIR is SecurityModelIR
    assert security_ir.ProofReport is reports_api.ProofReport is ProofReport
    assert security_ir.ProofReceipt is reports_api.ProofReceipt is ProofReceipt


def test_security_model_shape_round_trip_and_validation_contract() -> None:
    assert [item.name for item in fields(SecurityModelIR)] == SECURITY_MODEL_FIELDS

    model = _compat_model()
    assert security_ir.validate_ir(model) is model
    assert SecurityModelIR.from_dict(model.to_dict()).to_dict() == model.to_dict()
    assert SecurityModelIR.from_untrusted_dict(model.to_dict(), strict=True).to_dict() == model.to_dict()

    invalid = model.to_dict()
    invalid["unexpected"] = True
    with pytest.raises(ValueError, match=r"Unknown top-level SecurityModelIR field"):
        validate_ir_payload(invalid, strict=True)
    with pytest.raises(ValueError, match="model_id is required"):
        security_ir.validate_ir(SecurityModelIR(schema_version="security-model-ir/v1", model_id=""))


def test_canonicalization_and_both_legacy_identifier_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _compat_model()
    assert security_ir.canonicalize_ir_json(model) == CANONICAL_COMPAT_MODEL
    assert security_ir.canonicalize_ir(model) == CANONICAL_COMPAT_MODEL.encode("utf-8")

    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: None)
    expected_digest = hashlib.sha256(CANONICAL_COMPAT_MODEL.encode("utf-8")).hexdigest()
    assert security_ir.calculate_model_cid(model) == f"sha256:{expected_digest}"
    artifact_bytes = b'{"a":2,"z":1}'
    assert calculate_artifact_cid({"z": 1, "a": 2}) == (
        f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    )

    observed_payloads: list[bytes] = []

    def fake_cid_for_bytes(payload: bytes) -> str:
        observed_payloads.append(payload)
        return "bafy-compatibility-cid"

    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: fake_cid_for_bytes)
    assert security_ir.calculate_model_cid(model) == "bafy-compatibility-cid"
    assert observed_payloads == [CANONICAL_COMPAT_MODEL.encode("utf-8")]


def test_proof_report_and_receipt_round_trip_and_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: None)
    report = _proved_report()

    assert validate_proof_report(report) is report
    assert ProofReport.from_dict(report.to_dict()).to_dict() == report.to_dict()
    assert report.verify_report_cids() is True
    assert report.cid == report.nondeterministic_report_cid

    receipt = ProofReceipt.from_report(
        report,
        verifier="compat-consumer",
        verifier_version="1.0",
        accepted_assumptions=["A1"],
    )
    assert validate_proof_receipt(receipt) is receipt
    assert ProofReceipt.from_untrusted_dict(receipt.to_dict(), report=report).to_dict() == receipt.to_dict()
    assert receipt.valid is True
    assert receipt.proof_report_cid == report.cid

    tampered = report.to_dict()
    tampered["status"] = "UNKNOWN"
    with pytest.raises(ValueError, match="deterministic_payload_cid does not match"):
        ProofReport.from_untrusted_dict(tampered)
    with pytest.raises(ValueError, match="accepted_assumptions must be provided explicitly"):
        ProofReceipt.from_report(report, verifier="compat-consumer", verifier_version="1.0")


def test_runtime_monitor_public_behavior() -> None:
    events = [
        {"event": "wallet_frozen", "wallet_id": "wallet-1", "timestamp": 1},
        {"event": "signing_request", "wallet_id": "wallet-1", "timestamp": 2},
    ]
    expected = [
        {
            "property": "wallet_frozen -> no future signing_request",
            "index": 1,
            "event": events[1],
        }
    ]

    monitor = security_ir.RuntimeMTLMonitor(events=events)
    assert monitor.check_all() == expected
    assert security_ir.check_runtime_properties(events) == expected
    assert security_ir.check_runtime_properties([]) == []


def test_feature_loop_projector_and_examples() -> None:
    exchange = ir_api.example_minimal_exchange_model()
    xaman = ir_api.example_xaman_wallet_security_model()
    projection = security_ir.SecurityIRFeatureLoopProjector().project_model(exchange)

    assert (exchange.model_id, len(exchange.claims), len(exchange.policies), len(exchange.events)) == (
        "minimal-btc-exchange",
        8,
        9,
        13,
    )
    assert (xaman.model_id, len(xaman.claims), len(xaman.policies), len(xaman.events)) == (
        "xaman-app-wallet-security",
        7,
        1,
        1,
    )
    assert projection["projection_kind"] == "security-ir-feature-loop/v1"
    assert projection["model_id"] == "minimal-btc-exchange"
    assert projection["feature_counts"] == {
        "entities": 2,
        "policies": 9,
        "events": 13,
        "invariants": 3,
        "assumptions": 10,
    }
    assert [
        item["claim_id"] for item in projection["codex_program_synthesis"]["claims"]
    ] == CLAIM_IDS


def test_example_claim_registry_and_release_policies_are_frozen() -> None:
    default_claims = security_ir.default_claims()
    assert [claim.claim_id for claim in default_claims] == CLAIM_IDS
    assert [claim.severity for claim in default_claims] == [
        "blocking",
        "blocking",
        "blocking",
        "high",
        "high",
        "high",
        "high",
        "medium",
    ]

    entries = security_ir.release_policy_entries()
    assert [entry.claim_id for entry in entries] == CLAIM_IDS
    assert [entry.release_gate for entry in entries] == [
        "blocking",
        "blocking",
        "blocking",
        "high",
        "high",
        "high",
        "high",
        "medium",
    ]
    release_result = security_ir.evaluate_release_policy([])
    assert release_result["release_ready"] is False
    assert [item["claim_id"] for item in release_result["failures"]] == CLAIM_IDS[:7]
    assert [item["claim_id"] for item in release_result["attention"]] == CLAIM_IDS[7:]

    policy = build_security_decision_policy()
    assert validate_security_decision_policy(policy) is None
    assert [item.outcome for item in security_decision_outcomes()] == [
        "prove",
        "disprove",
        "unknown",
        "not-modeled",
        "stale-evidence",
        "missing-solver",
        "blocked-production",
    ]
    assert decision_outcome_for_proof_status("PROVED") == "prove"
    assert blocking_claim_is_secure_outcome("prove") is True
    assert blocking_claim_is_secure_outcome("unknown") is False
    assert classify_release_consumer_outcome({"status": "UNKNOWN"})["consumer_result"] == "non-secure"


def test_assumption_and_evidence_policy_entry_points() -> None:
    assumption_result = security_ir.evaluate_assumption_registry(
        _compat_model(),
        as_of="2026-01-02T03:04:05Z",
        require_owner=False,
        require_evidence=False,
        require_current=False,
    )
    assert assumption_result["release_ready"] is True
    assert assumption_result["summary"] == {
        "total": 1,
        "present": 1,
        "owned": 0,
        "evidenced": 0,
        "current": 0,
        "stale": 0,
        "accepted": 1,
    }

    promotion_result = security_ir.evaluate_evidence_promotion_workflow(
        {
            "schema_version": "crypto-exchange-evidence-promotion/v1",
            "evidence_reviews": [],
        },
        as_of="2026-01-02T03:04:05Z",
    )
    assert promotion_result["release_ready"] is True
    assert promotion_result["summary"] == {
        "total_reviews": 0,
        "promoted": 0,
        "quarantined": 0,
        "failures": 0,
    }


def test_runner_contract_without_solver_execution() -> None:
    claim = security_ir.default_claims()[0]
    model = security_ir.example_minimal_exchange_model()

    with pytest.raises(TypeError):
        runners_api.BaseSecurityRunner()

    z3_runner = runners_api.Z3Runner(timeout_ms=1234)
    cvc5_runner = runners_api.CVC5Runner(timeout_ms=4321, executable="/missing/cvc5")
    assert (z3_runner.prover_name, z3_runner.timeout_ms) == ("z3", 1234)
    assert (cvc5_runner.prover_name, cvc5_runner.timeout_ms, cvc5_runner.executable) == (
        "cvc5",
        4321,
        "/missing/cvc5",
    )
    assert cvc5_runner.executable_path("/missing/cvc5") is None

    report = z3_runner.unknown_report(claim, model, "solver intentionally not invoked")
    assert (report.status, report.prover, report.solver_result, report.reason_unknown) == (
        "UNKNOWN",
        "z3",
        "unknown",
        "solver intentionally not invoked",
    )


def test_proof_cli_exit_codes_without_solver_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(prove_all, "prove_claims", lambda model, provers: [])

    assert prove_all.main(["--example"]) == 0
    success_payload = json.loads(capsys.readouterr().out)
    assert success_payload["model_id"] == "minimal-btc-exchange"
    assert success_payload["reports"] == []

    assert prove_all.main(["--example", "--min-modeled-blocking-claims", "1"]) == 1
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc_info:
        prove_all.main(["--example", "--provers", "unsupported"])
    assert exc_info.value.code == 2
    assert "Unsupported provers: unsupported" in capsys.readouterr().err


def test_submodule_registry_discovers_the_frozen_security_surface() -> None:
    spec = submodule_registry.logic_submodule_spec("security_models")
    assert spec.module == "ipfs_datasets_py.logic.security_models"
    assert spec.roles == ("security_models", "proof", "policy", "runtime_monitor")
    assert spec.optimizer_components == ("security_models.crypto_exchange",)
    assert spec.public_symbols == (
        "SecurityModelIR",
        "ProofReport",
        "ProofReceipt",
        "RuntimeMTLMonitor",
    )
    assert spec.target_files == (
        "ipfs_datasets_py/logic/security_models/__init__.py",
        "ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py",
        "ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py",
        "ipfs_datasets_py/logic/security_models/crypto_exchange/runners/z3_runner.py",
    )

    manifest_entry = next(
        item
        for item in submodule_registry.logic_integration_manifest()["submodules"]
        if item["name"] == "security_models"
    )
    assert manifest_entry == spec.to_dict()
    assert submodule_registry.logic_submodule_import_report()["security_models"] == {
        "module": "ipfs_datasets_py.logic.security_models",
        "ok": True,
        "skipped": False,
        "version": None,
    }
