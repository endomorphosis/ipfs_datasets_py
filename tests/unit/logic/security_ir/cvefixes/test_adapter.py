"""Conformance tests for the CVEfixes-to-Security-IR adapter."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.adapter import (
    CVEFIXES_ADAPTER_ATTRIBUTES_KEY,
    CVEfixesAdapterError,
    CVEfixesAdapterResult,
    CVEfixesSecurityIRAdapter,
    CandidateReview,
    CandidateReviewState,
    adapt_cvefixes_candidate,
    to_cvefixes_candidate,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    PolicyCandidate,
    SourceRecord,
    canonical_config_cid,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.vocabulary import (
    CVEFIXES_POLICY_ATTRIBUTES_KEY,
    CVEfixesPolicyAttributes,
    CVEfixesTermKind,
    cvefixes_term,
)
from ipfs_datasets_py.logic.security_ir.model import (
    PolicyEffect,
    SecurityIR,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


SOURCE_SNAPSHOT_CID = _cid("source-snapshot")
CONFIG_CID = canonical_config_cid({"adapter_test": "v1"})


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


def _attributes() -> CVEfixesPolicyAttributes:
    def term(kind: CVEfixesTermKind, name: str) -> str:
        return cvefixes_term(kind, name).canonical

    return CVEfixesPolicyAttributes(
        action=term(
            CVEfixesTermKind.ACTION,
            "construct_path_from_untrusted_input",
        ),
        preconditions=(
            term(CVEfixesTermKind.PRECONDITION, "attacker_controls_path"),
            term(
                CVEfixesTermKind.PRECONDITION,
                "missing_canonicalization",
            ),
        ),
        effects=(
            term(CVEfixesTermKind.EFFECT, "read_outside_allowed_root"),
        ),
        mitigations=(
            term(CVEfixesTermKind.MITIGATION, "canonicalize_and_confine"),
        ),
        language=term(CVEfixesTermKind.LANGUAGE, "python"),
        scope=term(CVEfixesTermKind.SCOPE, "filesystem"),
        cve_ids=("CVE-2024-12345",),
        cwe_ids=("CWE-22",),
    )


def _candidate(
    *,
    scope_extra: dict[str, object] | None = None,
    payload_extra: dict[str, object] | None = None,
    effect: str = "deny",
) -> PolicyCandidate:
    scope = _attributes().to_dict()
    scope.update(scope_extra or {})
    payload = {"severity": "high"}
    payload.update(payload_extra or {})
    return PolicyCandidate(
        source_cids=(SOURCE_SNAPSHOT_CID,),
        parent_cids=(_cid("vulnerable-code-unit"),),
        config_cid=CONFIG_CID,
        effect=effect,
        scope=scope,
        payload=payload,
    )


def _observed_review() -> CandidateReview:
    return CandidateReview(CandidateReviewState.OBSERVED_CANDIDATE)


def _reviewed() -> CandidateReview:
    return CandidateReview(
        CandidateReviewState.REVIEWED_PATTERN,
        review_id="review:cvefixes:path-pattern",
        reviewer_id="principal:security-reviewer",
        attributes={"method": "two_person_scope_review"},
    )


def test_grounded_candidate_maps_to_canonical_declaration_without_authority() -> None:
    candidate = _candidate()
    result = CVEfixesSecurityIRAdapter().adapt(
        candidate,
        sources=(_source(),),
        review=_observed_review(),
    )
    declaration = result.declaration

    assert isinstance(declaration, SecurityIR)
    assert len(declaration.sources) == 1
    assert declaration.sources[0].revision == (
        "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"
    )
    assert declaration.sources[0].review_status == "observed_candidate"
    assert len(declaration.resources) == 1
    assert declaration.resources[0].kind == "filesystem"
    assert declaration.policies[0].effect is PolicyEffect.DENY
    assert declaration.policies[0].resource_ids == (
        declaration.resources[0].resource_id,
    )
    assert len(declaration.assumptions) == 2
    assert declaration.claims[0].assumption_ids == tuple(
        item.assumption_id for item in declaration.assumptions
    )
    assert declaration.claims[0].policy_ids == (
        declaration.policies[0].policy_id,
    )

    policy_attributes = declaration.policies[0].attributes
    assert CVEfixesPolicyAttributes.from_dict(
        policy_attributes[CVEFIXES_POLICY_ATTRIBUTES_KEY]
    ) == _attributes()
    adapter_attributes = policy_attributes[CVEFIXES_ADAPTER_ATTRIBUTES_KEY]
    assert adapter_attributes["grants_execution_authority"] is False
    assert adapter_attributes["requires_authoritative_adoption"] is True
    assert result.authority == "candidate"
    assert result.proof_authoritative is False
    assert result.grants_execution_authority is False


def test_mapping_is_loss_aware_round_trippable_and_tamper_evident() -> None:
    candidate = _candidate(
        payload_extra={
            # Detached result-like data is retained by the result but is not
            # imported into the declaration.
            "evaluation": {"verdict": "passed", "score": 0.99},
            "projection_diagnostic": "bounded excerpt omitted",
        }
    )
    result = adapt_cvefixes_candidate(
        candidate,
        sources=(_source(),),
        review=_observed_review(),
    )

    assert to_cvefixes_candidate(result) == candidate
    assert CVEfixesAdapterResult.from_json(result.to_json()) == result
    assert SecurityIR.from_dict(result.declaration.to_dict()) == (
        result.declaration
    )
    declaration_json = result.declaration.canonical_json()
    assert '"evaluation"' not in declaration_json
    assert '"verdict"' not in declaration_json
    assert "bounded excerpt omitted" not in declaration_json

    tampered = result.to_dict()
    tampered["declaration"]["policies"][0]["effect"] = "allow"
    with pytest.raises(CVEfixesAdapterError, match="does not match"):
        CVEfixesAdapterResult.from_dict(tampered)

    duplicate_key = result.to_json().replace(
        '{"adapter_version":',
        '{"adapter_version":"duplicate","adapter_version":',
        1,
    )
    with pytest.raises(CVEfixesAdapterError, match="duplicate JSON key"):
        CVEfixesAdapterResult.from_json(duplicate_key)


@pytest.mark.parametrize("review", (None, "observed_candidate", {}))
def test_source_and_typed_review_state_are_mandatory(review: object) -> None:
    with pytest.raises(CVEfixesAdapterError, match="review state is mandatory"):
        adapt_cvefixes_candidate(  # type: ignore[arg-type]
            _candidate(),
            sources=(_source(),),
            review=review,
        )

    with pytest.raises(CVEfixesAdapterError, match="source record is mandatory"):
        adapt_cvefixes_candidate(
            _candidate(),
            sources=(),
            review=_observed_review(),
        )


def test_candidate_cannot_claim_authority_or_emit_allow_policy() -> None:
    with pytest.raises(CVEfixesAdapterError, match="cannot claim"):
        adapt_cvefixes_candidate(
            _candidate(payload_extra={"grants_execution_authority": True}),
            sources=(_source(),),
            review=_observed_review(),
        )

    with pytest.raises(CVEfixesAdapterError, match="only deny"):
        adapt_cvefixes_candidate(
            _candidate(effect="allow"),
            sources=(_source(),),
            review=_observed_review(),
        )

    wire_review = _observed_review().to_dict()
    wire_review["grants_execution_authority"] = True
    with pytest.raises(CVEfixesAdapterError, match="cannot grant"):
        CandidateReview.from_dict(wire_review)


@pytest.mark.parametrize(
    "scope_extra",
    (
        {"path_pattern": "src/**/handlers.py"},
        {"generalized": True},
        {"scope_mode": "regex"},
    ),
)
def test_wildcard_and_generalized_scope_requires_explicit_review(
    scope_extra: dict[str, object],
) -> None:
    candidate = _candidate(scope_extra=scope_extra)

    with pytest.raises(CVEfixesAdapterError, match="explicit reviewed_pattern"):
        adapt_cvefixes_candidate(
            candidate,
            sources=(_source(),),
            review=_observed_review(),
        )

    result = adapt_cvefixes_candidate(
        candidate,
        sources=(_source(),),
        review=_reviewed(),
    )
    metadata = result.declaration.policies[0].attributes[
        CVEFIXES_ADAPTER_ATTRIBUTES_KEY
    ]
    assert metadata["generalized_scope"] is True
    assert metadata["review"]["state"] == "reviewed_pattern"
    assert metadata["grants_execution_authority"] is False


def test_reviewed_pattern_requires_stable_human_review_binding() -> None:
    with pytest.raises(CVEfixesAdapterError, match="requires review_id"):
        CandidateReview(CandidateReviewState.REVIEWED_PATTERN)


def test_optional_state_machine_is_declarative_and_source_bound() -> None:
    state_machine = {
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
    result = adapt_cvefixes_candidate(
        _candidate(payload_extra={"state_machine": state_machine}),
        sources=(_source(),),
        review=_observed_review(),
    )

    machine = result.declaration.state_machines[0]
    assert machine.states == ("vulnerable", "fixed")
    assert machine.transitions[0].event == "apply_mitigation"
    assert machine.source_ids == (
        result.declaration.sources[0].source_id,
    )
    serialized = json.dumps(machine.to_dict(), sort_keys=True)
    assert "runtime_trace" not in serialized
    assert "verification_result" not in serialized


def test_candidate_source_lineage_must_be_covered() -> None:
    unrelated = replace(
        _source(),
        source_cids=(_cid("unrelated-source"),),
        record_id="",
    )
    with pytest.raises(CVEfixesAdapterError, match="not covered"):
        adapt_cvefixes_candidate(
            _candidate(),
            sources=(unrelated,),
            review=_observed_review(),
        )
