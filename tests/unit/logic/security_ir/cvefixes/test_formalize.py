"""Conformance tests for CVEfixes forbidden-logic formalization."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.adapter import (
    CVEfixesAdapterResult,
    CandidateReview,
    CandidateReviewState,
    adapt_cvefixes_candidate,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.formalize import (
    CVEFIXES_DEONTIC_OPERATOR,
    CVEFIXES_FORMALIZATION_TARGET_VIEWS,
    CVEFIXES_PROHIBITION_MODALITY,
    CVEfixesControlPolarity,
    CVEfixesFormalizationAdapter,
    CVEfixesFormalizationError,
    formalize_cvefixes_candidate,
    prohibition_expected_for_control,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    PolicyCandidate,
    SourceRecord,
    canonical_config_cid,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.vocabulary import (
    CVEfixesPolicyAttributes,
    CVEfixesTermKind,
    cvefixes_term,
)
from ipfs_datasets_py.logic.security_ir.formalization_adapter import (
    SECURITY_IR_CLAIM_VIEW_ID,
    SECURITY_IR_POLICY_VIEW_ID,
    SECURITY_IR_THREAT_VIEW_ID,
    SECURITY_IR_TRANSITION_VIEW_ID,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


SOURCE_SNAPSHOT_CID = _cid("source-snapshot")
CONFIG_CID = canonical_config_cid({"formalize_test": "v1"})


def _term(kind: CVEfixesTermKind, name: str) -> str:
    return cvefixes_term(kind, name).canonical


def _attributes() -> CVEfixesPolicyAttributes:
    return CVEfixesPolicyAttributes(
        action=_term(
            CVEfixesTermKind.ACTION,
            "construct_path_from_untrusted_input",
        ),
        preconditions=(
            _term(CVEfixesTermKind.PRECONDITION, "attacker_controls_path"),
            _term(CVEfixesTermKind.PRECONDITION, "missing_canonicalization"),
        ),
        effects=(
            _term(CVEfixesTermKind.EFFECT, "read_outside_allowed_root"),
        ),
        mitigations=(
            _term(CVEfixesTermKind.MITIGATION, "canonicalize_and_confine"),
        ),
        language=_term(CVEfixesTermKind.LANGUAGE, "python"),
        scope=_term(CVEfixesTermKind.SCOPE, "filesystem"),
        cve_ids=("CVE-2024-12345",),
        cwe_ids=("CWE-22",),
    )


def _source() -> SourceRecord:
    return SourceRecord(
        source_cids=(SOURCE_SNAPSHOT_CID,),
        parent_cids=(_cid("source-parent"),),
        config_cid=CONFIG_CID,
        source_uri="hf://datasets/hitoshura25/cvefixes",
        source_revision="d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2",
        row_key="CVE-2024-12345:deadbeef",
        payload={
            "content_sha256": "a" * 64,
            "cve_id": "CVE-2024-12345",
        },
    )


def _result(*, with_transition: bool = True) -> CVEfixesAdapterResult:
    payload: dict[str, object] = {"severity": "high"}
    if with_transition:
        payload["state_machine"] = {
            "states": ["vulnerable", "fixed"],
            "initial_state": "vulnerable",
            "transitions": [
                {
                    "source_state": "vulnerable",
                    "target_state": "fixed",
                    "event": "apply_mitigation",
                    "guard": "canonicalize_and_confine",
                    "effect": "path_confined",
                }
            ],
        }
    candidate = PolicyCandidate(
        source_cids=(SOURCE_SNAPSHOT_CID,),
        parent_cids=(_cid("vulnerable-code-unit"),),
        config_cid=CONFIG_CID,
        effect="deny",
        scope=_attributes().to_dict(),
        payload=payload,
    )
    return adapt_cvefixes_candidate(
        candidate,
        sources=(_source(),),
        review=CandidateReview(CandidateReviewState.OBSERVED_CANDIDATE),
    )


def _policy_formula(artifact: FormalizationArtifact):
    return next(
        item
        for item in artifact.formulas
        if item.view_id == SECURITY_IR_POLICY_VIEW_ID
    )


def _all_authority_flags(value: object) -> list[object]:
    flags: list[object] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "authoritative",
                "grants_execution_authority",
                "proof_authoritative",
            }:
                flags.append(item)
            flags.extend(_all_authority_flags(item))
    elif isinstance(value, list):
        for item in value:
            flags.extend(_all_authority_flags(item))
    return flags


def test_deny_candidate_maps_to_typed_exact_scope_prohibition() -> None:
    result = _result()
    artifact = formalize_cvefixes_candidate(result)
    formula = _policy_formula(artifact)
    expression = formula.expression.to_dict()
    symbols = {
        item.symbol_id: item for item in artifact.symbol_table.symbols
    }

    assert expression["kind"] == "deontic_prohibition"
    assert expression["deontic_operator"] == CVEFIXES_DEONTIC_OPERATOR
    assert expression["modality"] == CVEFIXES_PROHIBITION_MODALITY
    assert expression["source_policy_effect"] == "deny"
    assert expression["typed_scope"] == _attributes().to_dict()
    assert set(formula.symbol_ids) == set(expression["typed_symbol_ids"])
    assert all(identifier in symbols for identifier in formula.symbol_ids)
    assert {
        symbols[identifier].sort for identifier in formula.symbol_ids
    } >= {
        "cvefixes_action",
        "cvefixes_effect",
        "cvefixes_precondition",
        "cvefixes_scope",
    }
    assert all(
        symbols[identifier].metadata["exact_scope"]
        == _attributes().scope.canonical
        for identifier in formula.symbol_ids
    )
    assert artifact.declaration_id == result.declaration.declaration_id
    assert artifact.metadata["proof_backend_executed"] is False


def test_shared_views_emit_threat_transition_claim_and_obligation_contracts() -> None:
    artifact = CVEfixesFormalizationAdapter().adapt(_result())
    emitted_views = {item.view_id for item in artifact.formulas}

    assert set(CVEFIXES_FORMALIZATION_TARGET_VIEWS) == {
        SECURITY_IR_CLAIM_VIEW_ID,
        SECURITY_IR_POLICY_VIEW_ID,
        SECURITY_IR_THREAT_VIEW_ID,
        SECURITY_IR_TRANSITION_VIEW_ID,
    }
    assert set(CVEFIXES_FORMALIZATION_TARGET_VIEWS).issubset(emitted_views)
    assert len(
        [
            item
            for item in artifact.formulas
            if item.metadata["security_construct"] == "assumption"
        ]
    ) == 2
    transition = next(
        item
        for item in artifact.formulas
        if item.metadata["security_construct"] == "transition"
    )
    assert transition.expression["transition"]["source_state"] == "vulnerable"
    assert transition.expression["transition"]["target_state"] == "fixed"
    assert artifact.proof_obligations
    assert artifact.proof_obligations[0].assumption_ids == tuple(
        item.assumption_id for item in artifact.assumptions
    )
    assert all(item.source_refs for item in artifact.proof_obligations)
    assert FormalizationArtifact.from_json(artifact.to_json()) == artifact
    assert CVEfixesFormalizationAdapter().adapt(_result()).digest == artifact.digest


def test_missing_optional_transition_is_an_explicit_grounded_diagnostic() -> None:
    artifact = formalize_cvefixes_candidate(_result(with_transition=False))
    diagnostic = next(
        item
        for item in artifact.unsupported_diagnostics
        if item.metadata.get("view_id") == SECURITY_IR_TRANSITION_VIEW_ID
    )

    assert diagnostic.location.traceable
    assert diagnostic.code == "ir.feature.unsupported"
    assert "no construct" in diagnostic.message
    assert SECURITY_IR_TRANSITION_VIEW_ID not in {
        item.view_id for item in artifact.formulas
    }


def test_formulas_and_obligations_are_explicitly_non_authoritative() -> None:
    adapter = CVEfixesFormalizationAdapter()
    artifact = adapter.adapt(_result())
    wire = artifact.to_dict()

    assert adapter.authority == "candidate"
    assert adapter.proof_authoritative is False
    assert adapter.grants_execution_authority is False
    assert artifact.metadata["authoritative"] is False
    assert artifact.metadata["proof_authoritative"] is False
    assert artifact.metadata["grants_execution_authority"] is False
    assert _all_authority_flags(wire)
    assert all(value is False for value in _all_authority_flags(wire))
    assert all(
        item.metadata["proof_authoritative"] is False
        for item in artifact.proof_obligations
    )


def test_vulnerable_and_fixed_controls_have_opposite_expected_polarity() -> None:
    assert prohibition_expected_for_control(
        CVEfixesControlPolarity.VULNERABLE_POSITIVE
    )
    assert prohibition_expected_for_control("vulnerable")
    assert not prohibition_expected_for_control(
        CVEfixesControlPolarity.FIXED_NEGATIVE
    )
    assert not prohibition_expected_for_control("fixed")

    with pytest.raises(CVEfixesFormalizationError, match="unsupported"):
        prohibition_expected_for_control("unknown")


def test_tampered_or_foreign_adapter_results_fail_closed() -> None:
    result = _result()
    tampered_policy = replace(
        result.declaration.policies[0],
        name="tampered policy",
    )
    tampered = replace(
        result,
        declaration=replace(
            result.declaration,
            policies=(tampered_policy,),
        ),
    )

    with pytest.raises(CVEfixesFormalizationError, match="does not match"):
        formalize_cvefixes_candidate(tampered)
    with pytest.raises(CVEfixesFormalizationError, match="requires"):
        formalize_cvefixes_candidate(result.declaration)  # type: ignore[arg-type]


def test_candidate_result_fields_never_become_formal_features() -> None:
    baseline = _result()
    candidate = replace(
        baseline.candidate,
        payload={
            **dict(baseline.candidate.payload),
            "evaluation": {
                "verdict": "passed",
                "solver_results": [{"status": "proved"}],
            },
        },
        record_id="",
    )
    changed = adapt_cvefixes_candidate(
        candidate,
        sources=baseline.sources,
        review=baseline.review,
        declaration_id=baseline.declaration.declaration_id,
    )
    artifact = formalize_cvefixes_candidate(changed)
    serialized = json.dumps(artifact.to_dict(), sort_keys=True)

    assert '"evaluation"' not in serialized
    assert '"solver_results"' not in serialized
    assert '"verdict"' not in serialized
