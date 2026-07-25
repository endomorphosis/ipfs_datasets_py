"""Contract tests for immutable Security IR v1 and its legacy adapter."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from ipfs_datasets_py.logic.security_ir.adapter import (
    LegacyAdapterError,
    LegacyAdapterResult,
    LegacyVerificationData,
    adapt_legacy_security_ir,
    to_legacy_security_ir,
)
from ipfs_datasets_py.logic.security_ir.model import (
    Asset,
    Channel,
    Policy,
    Principal,
    Resource,
    SECURITY_IR_SCHEMA_VERSION,
    SecurityClaim,
    SecurityExtension,
    SecurityIR,
    SecurityIRValidationError,
    SecuritySource,
    StateMachine,
    StateTransition,
    ThreatAssumption,
    TrustZone,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
)


FIXTURES = (
    Path(__file__).resolve().parents[3] / "fixtures" / "security_ir" / "v1"
)


def _payload(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}_model.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ("exchange", "xaman"))
def test_golden_legacy_models_round_trip_losslessly(name: str) -> None:
    payload = _payload(name)

    result = adapt_legacy_security_ir(payload)

    assert isinstance(result, LegacyAdapterResult)
    assert isinstance(result.declaration, SecurityIR)
    assert result.declaration.schema_version == SECURITY_IR_SCHEMA_VERSION
    assert result.declaration.declaration_id == payload["model_id"]
    assert result.lossless is True
    assert to_legacy_security_ir(result) == payload
    legacy_model = to_legacy_security_ir(result, as_model=True)
    assert isinstance(legacy_model, SecurityModelIR)
    assert legacy_model.to_dict() == payload


def test_adapter_defensively_copies_declarations_and_run_data() -> None:
    payload = _payload("exchange")
    result = adapt_legacy_security_ir(payload)
    declaration_dict = result.declaration.to_dict()
    verification_dict = result.verification_data.to_dict()

    payload["assets"][0]["symbol"] = "MUTATED"
    payload["claims"][0]["required_assumptions"].append("A1")
    payload["solver_results"][0]["solver_version"] = "mutated"
    payload["metadata"]["labels"].append("mutated")

    assert result.declaration.to_dict() == declaration_dict
    assert result.verification_data.to_dict() == verification_dict
    assert result.declaration.assets[0].symbol == "BTC"
    with pytest.raises(TypeError):
        result.declaration.assets[0].attributes["new"] = True
    with pytest.raises(AttributeError):
        result.verification_data.solver_results.append({})
    with pytest.raises(TypeError):
        result.verification_data.solver_results[0]["result"] = "sat"


def test_typed_records_and_nested_values_are_immutable() -> None:
    source = SecuritySource(
        source_id="source:policy",
        uri="repo://policy.md",
        revision="abc123",
        content_sha256="0" * 64,
        attributes={"nested": {"values": [1, 2]}},
    )
    declaration = SecurityIR(
        declaration_id="security:test",
        sources=(source,),
        principals=(
            Principal(
                "principal:user",
                role_ids=("role:user",),
                source_ids=(source.source_id,),
            ),
        ),
        assets=(Asset("asset:data", kind="information"),),
        trust_zones=(TrustZone("zone:trusted", "Trusted"),),
        channels=(
            Channel(
                "channel:api",
                "principal:user",
                "resource:api",
                trust_zone_ids=("zone:trusted",),
            ),
        ),
        resources=(
            Resource(
                "resource:api",
                owner_principal_ids=("principal:user",),
                asset_ids=("asset:data",),
                trust_zone_ids=("zone:trusted",),
            ),
        ),
        policies=(Policy("policy:auth", "Authentication required"),),
        state_machines=(
            StateMachine(
                "machine:session",
                states=("anonymous", "authenticated"),
                initial_state="anonymous",
                transitions=(
                    StateTransition(
                        "anonymous", "authenticated", "authenticate"
                    ),
                ),
            ),
        ),
        assumptions=(
            ThreatAssumption(
                "assumption:crypto",
                "Cryptographic primitives meet the declared bounds.",
            ),
        ),
        claims=(
            SecurityClaim(
                "claim:auth",
                "Only authenticated users access the API.",
                "authorization",
                assumption_ids=("assumption:crypto",),
                policy_ids=("policy:auth",),
            ),
        ),
        extensions=(
            SecurityExtension(
                "extension:test",
                "example.security",
                "v1",
                {"flags": ["a", "b"]},
            ),
        ),
    )

    assert isinstance(source.attributes, MappingProxyType)
    assert isinstance(source.attributes["nested"], MappingProxyType)
    assert source.attributes["nested"]["values"] == (1, 2)
    assert declaration.to_dict()["sources"][0]["attributes"]["nested"]["values"] == [
        1,
        2,
    ]
    with pytest.raises(FrozenInstanceError):
        declaration.declaration_id = "security:changed"
    with pytest.raises(TypeError):
        declaration.extensions[0].payload["flags"] = ()


def test_verification_observations_do_not_change_declaration_identity() -> None:
    before = _payload("exchange")
    after = copy.deepcopy(before)
    after["proof_obligations"][0]["model_cid"] = "run-specific-model-id"
    after["disproof_vectors"][0]["tactic"] = "different-runtime-search"
    after["runtime_traces"][0]["conformance_status"] = "violated"
    after["solver_results"][0]["solver_version"] = "different-environment"

    first = adapt_legacy_security_ir(before)
    second = adapt_legacy_security_ir(after)

    assert first.declaration.to_dict() == second.declaration.to_dict()
    assert first.declaration.digest == second.declaration.digest
    assert first.declaration.cid == second.declaration.cid
    assert first.verification_data.to_dict() != second.verification_data.to_dict()
    assert any(
        item.code == "security.adapter.verification_detached"
        for item in first.diagnostics
    )


def test_semantic_declaration_mutation_changes_identity() -> None:
    before = _payload("exchange")
    after = copy.deepcopy(before)
    after["claims"][0]["description"] = "A materially different security claim."

    first = adapt_legacy_security_ir(before).declaration
    second = adapt_legacy_security_ir(after).declaration

    assert first.digest != second.digest
    assert first.cid != second.cid


def test_adapter_types_sources_and_reports_incomplete_legacy_grounding() -> None:
    payload = _payload("exchange")
    payload["claims"][0]["evidence_refs"] = [
        {
            "kind": "policy_doc",
            "path": "docs/security-policy.md",
            "review_status": "human_reviewed",
        }
    ]

    result = adapt_legacy_security_ir(payload)

    assert len(result.declaration.sources) == 1
    source = result.declaration.sources[0]
    assert isinstance(source, SecuritySource)
    assert source.uri == "docs/security-policy.md"
    assert source.content_sha256 == ""
    assert result.declaration.claims[0].source_ids == (source.source_id,)
    assert any(
        item.code == "security.adapter.unsupported.source_digest"
        for item in result.diagnostics
    )
    assert to_legacy_security_ir(result) == payload


def test_unsupported_top_level_data_is_preserved_with_a_diagnostic() -> None:
    payload = _payload("exchange")
    payload["vendor_runtime_hint"] = {"mode": "legacy"}

    result = adapt_legacy_security_ir(payload)

    assert result.has_unsupported is True
    assert result.has_loss is False
    assert any(
        item.code == "security.adapter.unsupported.top_level_field"
        and item.location.field_path == "/vendor_runtime_hint"
        for item in result.diagnostics
    )
    assert to_legacy_security_ir(result) == payload
    with pytest.raises(LegacyAdapterError, match="cannot be represented"):
        to_legacy_security_ir(result, as_model=True)


def test_invalid_legacy_input_fails_instead_of_emitting_a_partial_model() -> None:
    payload = _payload("exchange")
    payload["claims"][0]["domain"] = "not-a-known-legacy-domain"

    with pytest.raises(
        LegacyAdapterError, match="references unknown security domain"
    ):
        adapt_legacy_security_ir(payload)


def test_security_ir_serialization_is_strict_and_identity_is_order_stable() -> None:
    result = adapt_legacy_security_ir(_payload("xaman"))
    encoded = result.declaration.to_dict()
    decoded = SecurityIR.from_dict(encoded)
    reversed_claims = SecurityIR.from_dict(
        {**encoded, "claims": list(reversed(encoded["claims"]))}
    )

    assert decoded.to_dict() == encoded
    assert decoded.cid == result.declaration.cid
    assert reversed_claims.cid == decoded.cid
    encoded["unknown"] = True
    with pytest.raises(SecurityIRValidationError, match="unknown SecurityIR field"):
        SecurityIR.from_dict(encoded)


def test_detached_verification_data_is_strictly_typed() -> None:
    with pytest.raises(LegacyAdapterError, match="unknown"):
        LegacyVerificationData.from_dict({"solver_results": [], "verdict": "pass"})
    with pytest.raises(LegacyAdapterError, match=r"solver_results\[0\]"):
        LegacyVerificationData(solver_results=("not-a-record",))
