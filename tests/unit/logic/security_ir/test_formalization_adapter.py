"""Conformance tests for the Security IR shared-formalization adapter."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.formalization.samples import FormalizationSample
from ipfs_datasets_py.logic.ir_core.provenance import SourceReviewStatus
from ipfs_datasets_py.logic.security_ir.formalization_adapter import (
    SECURITY_IR_CLAIM_VIEW_ID,
    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION,
    SECURITY_IR_FORMALIZATION_VIEW_REGISTRY,
    SECURITY_IR_POLICY_VIEW_ID,
    SECURITY_IR_THREAT_VIEW_ID,
    SECURITY_IR_TRANSITION_VIEW_ID,
    SecurityIRFormalizationAdapter,
    SecurityIRFormalizationAdapterError,
    adapt_security_ir,
)
from ipfs_datasets_py.logic.security_ir.model import (
    Policy,
    PolicyEffect,
    SecurityClaim,
    SecurityIR,
    SecuritySource,
    StateMachine,
    StateTransition,
    ThreatAssumption,
)


FIXTURES = (
    Path(__file__).resolve().parents[3] / "fixtures" / "security_ir" / "v1"
)


def _payload(name: str) -> dict[str, Any]:
    return json.loads(
        (FIXTURES / f"{name}_model.json").read_text(encoding="utf-8")
    )


def _all_mapping_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(_all_mapping_keys(item) for item in value.values()),
            set(),
        )
    if isinstance(value, list):
        return set().union(
            *(_all_mapping_keys(item) for item in value),
            set(),
        )
    return set()


def _reviewed_declaration() -> SecurityIR:
    source_bytes = b"reviewed security declaration source"
    source = SecuritySource(
        source_id="source:reviewed-security",
        uri="repo://docs/reviewed-security.md",
        revision="revision-1",
        content_sha256=hashlib.sha256(source_bytes).hexdigest(),
        review_status="human_reviewed",
    )
    assumption = ThreatAssumption(
        assumption_id="assumption:trusted-runtime",
        statement="The trusted runtime preserves key isolation.",
        source_ids=(source.source_id,),
    )
    policy = Policy(
        policy_id="policy:authorize-signing",
        name="authorize_signing",
        effect=PolicyEffect.REQUIRE,
        source_ids=(source.source_id,),
    )
    machine = StateMachine(
        state_machine_id="state-machine:signing",
        states=("requested", "authorized", "signed"),
        initial_state="requested",
        transitions=(
            StateTransition(
                source_state="requested",
                target_state="authorized",
                event="authorize",
                guard="biometric_verified",
                effect="record_approval",
            ),
        ),
        source_ids=(source.source_id,),
    )
    claim = SecurityClaim(
        claim_id="claim:authorized-signing",
        statement="Only approved transaction bytes are signed.",
        domain="signing",
        severity="blocking",
        assumption_ids=(assumption.assumption_id,),
        policy_ids=(policy.policy_id,),
        source_ids=(source.source_id,),
    )
    return SecurityIR(
        declaration_id="security:reviewed-signing",
        sources=(source,),
        assumptions=(assumption,),
        policies=(policy,),
        state_machines=(machine,),
        claims=(claim,),
    )


def test_registry_declares_security_specific_shared_views() -> None:
    assert SECURITY_IR_FORMALIZATION_VIEW_REGISTRY.view_ids == tuple(
        sorted(
            (
                SECURITY_IR_CLAIM_VIEW_ID,
                SECURITY_IR_POLICY_VIEW_ID,
                SECURITY_IR_THREAT_VIEW_ID,
                SECURITY_IR_TRANSITION_VIEW_ID,
            )
        )
    )
    assert (
        SECURITY_IR_FORMALIZATION_VIEW_REGISTRY[
            SECURITY_IR_CLAIM_VIEW_ID
        ].logic_family
        == "verification_condition"
    )


@pytest.mark.parametrize("fixture_name", ("exchange", "xaman"))
def test_representative_legacy_declarations_adapt_deterministically(
    fixture_name: str,
) -> None:
    legacy = _payload(fixture_name)
    adapter = SecurityIRFormalizationAdapter()

    sample = adapter.adapt_sample(legacy)
    artifact = adapter.adapt(legacy)

    assert isinstance(sample, FormalizationSample)
    assert isinstance(artifact, FormalizationArtifact)
    assert sample.domain == "security"
    assert sample.declaration_id == legacy["model_id"]
    assert (
        sample.payload["adapter_schema_version"]
        == SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
    )
    assert artifact.declaration_digest == sample.declaration_digest
    assert artifact.metadata["proof_backend_executed"] is False
    assert artifact.metadata["result_artifacts_excluded"] is True
    assert artifact.proof_obligations
    assert all(formula.source_ref_ids for formula in artifact.formulas)
    assert all(
        obligation.source_refs for obligation in artifact.proof_obligations
    )
    assert FormalizationSample.from_json(sample.to_json()) == sample
    assert FormalizationArtifact.from_json(artifact.to_json()) == artifact
    assert adapter.adapt(legacy).digest == artifact.digest
    assert adapt_security_ir(legacy).digest == artifact.digest


def test_threats_policies_transitions_assumptions_and_claims_are_source_bound() -> None:
    declaration = _reviewed_declaration()
    artifact = SecurityIRFormalizationAdapter().adapt(declaration)
    by_kind = {
        formula.metadata["security_construct"]: formula
        for formula in artifact.formulas
    }
    source = artifact.source_map.sources[0]

    assert source.ref_id == "source:reviewed-security"
    assert source.review_status is SourceReviewStatus.HUMAN_REVIEWED
    assert {
        "assumption",
        "policy",
        "state-machine",
        "transition",
        "claim",
    }.issubset(by_kind)
    assert by_kind["assumption"].view_id == SECURITY_IR_THREAT_VIEW_ID
    assert by_kind["policy"].view_id == SECURITY_IR_POLICY_VIEW_ID
    assert by_kind["transition"].view_id == SECURITY_IR_TRANSITION_VIEW_ID
    assert by_kind["claim"].view_id == SECURITY_IR_CLAIM_VIEW_ID
    assert all(
        formula.source_ref_ids == ("source:reviewed-security",)
        for formula in by_kind.values()
    )
    assert artifact.assumptions[0].source_refs == (
        "source:reviewed-security",
    )
    assert artifact.proof_obligations[0].source_refs == (
        "source:reviewed-security",
    )
    bindings = {
        binding.subject_id: binding for binding in artifact.source_map.bindings
    }
    for formula in artifact.formulas:
        assert formula.formula_id in bindings
        assert set(formula.source_ref_ids).issubset(
            bindings[formula.formula_id].source_ref_ids
        )
        assert formula.input_node_ids[0] in bindings


def test_semantic_mutations_change_formulas_and_expected_obligations() -> None:
    declaration = _reviewed_declaration()
    adapter = SecurityIRFormalizationAdapter()
    baseline = adapter.adapt(declaration)

    changed_claim = replace(
        declaration.claims[0],
        statement="A materially different signing property.",
    )
    claim_mutation = adapter.adapt(
        replace(declaration, claims=(changed_claim,))
    )
    changed_transition = replace(
        declaration.state_machines[0].transitions[0],
        guard="hardware_key_and_biometric_verified",
    )
    transition_mutation = adapter.adapt(
        replace(
            declaration,
            state_machines=(
                replace(
                    declaration.state_machines[0],
                    transitions=(changed_transition,),
                ),
            ),
        )
    )

    assert (
        baseline.proof_obligations[0].digest
        != claim_mutation.proof_obligations[0].digest
    )
    assert (
        baseline.proof_obligations[0].digest
        != transition_mutation.proof_obligations[0].digest
    )
    baseline_transition = next(
        item
        for item in baseline.formulas
        if item.metadata["security_construct"] == "transition"
    )
    mutated_transition = next(
        item
        for item in transition_mutation.formulas
        if item.metadata["security_construct"] == "transition"
    )
    assert baseline_transition.expression != mutated_transition.expression
    assert baseline.digest != claim_mutation.digest
    assert baseline.digest != transition_mutation.digest


def test_legacy_result_mutations_never_become_declaration_features() -> None:
    before = _payload("exchange")
    after = copy.deepcopy(before)
    after["proof_obligations"][0]["status"] = "PROVED"
    after["disproof_vectors"][0]["tactic"] = "different_runtime_search"
    after["runtime_traces"][0]["conformance_status"] = "violated"
    after["solver_results"][0]["solver_version"] = "different-environment"
    adapter = SecurityIRFormalizationAdapter()

    first_sample = adapter.adapt_sample(before)
    second_sample = adapter.adapt_sample(after)
    first_artifact = adapter.adapt(before)
    second_artifact = adapter.adapt(after)
    declaration_keys = _all_mapping_keys(
        first_sample.payload.to_dict()["declaration"]
    )

    assert {
        "proof_obligations",
        "disproof_vectors",
        "runtime_traces",
        "solver_results",
    }.isdisjoint(declaration_keys)
    assert first_sample.digest == second_sample.digest
    assert first_artifact.digest == second_artifact.digest
    assert (
        first_artifact.proof_obligations
        == second_artifact.proof_obligations
    )


def test_extensions_remain_explicit_grounded_unsupported_semantics() -> None:
    artifact = SecurityIRFormalizationAdapter().adapt(_payload("xaman"))

    assert artifact.unsupported_diagnostics
    assert all(
        item.code == "ir.feature.unsupported"
        and item.location.traceable
        and item.metadata.get("extension_id")
        for item in artifact.unsupported_diagnostics
    )


def test_compile_rejects_foreign_tampered_and_unknown_view_inputs() -> None:
    adapter = SecurityIRFormalizationAdapter()
    sample = adapter.adapt_sample(_reviewed_declaration())

    with pytest.raises(
        SecurityIRFormalizationAdapterError, match="Security FormalizationSample"
    ):
        adapter.compile(
            replace(sample, domain="legal"),
            adapter.default_config(sample),
        )

    tampered_payload = sample.payload.to_dict()
    tampered_payload["declaration"]["claims"][0][
        "statement"
    ] = "tampered without rebinding the digest"
    tampered = replace(sample, payload=tampered_payload)
    with pytest.raises(
        SecurityIRFormalizationAdapterError, match="digest"
    ):
        adapter.compile(tampered, adapter.default_config(sample))

    unknown_config = replace(
        adapter.default_config(sample),
        target_view_ids=("security-ir-view/unknown/v1",),
    )
    with pytest.raises(
        SecurityIRFormalizationAdapterError, match="unknown views"
    ):
        adapter.compile(sample, unknown_config)
