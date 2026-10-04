"""Conformance tests for the isolated Solidity CPT Security IR vocabulary."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.security_ir.model import PolicyEffect, SecurityPolicy
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.vocabulary import (
    DEFAULT_SOLIDITY_VOCABULARY,
    SOLIDITY_POLICY_ATTRIBUTES_KEY,
    SOLIDITY_VOCABULARY_SCHEMA_VERSION,
    SolidityAlias,
    SolidityAuthorityType,
    SolidityPolicyAttributes,
    SolidityPolicyRole,
    SolidityTerm,
    SolidityTermKind,
    SolidityVocabulary,
    SolidityVocabularyError,
    authority_type_term,
    parse_solidity_term,
    require_authority_type,
    resolve_solidity_term,
    solidity_term,
    validate_solidity_aliases,
    validate_solidity_policy_attributes,
)


def _term(kind: SolidityTermKind, name: str) -> str:
    return solidity_term(kind, name).canonical


def _exact_attributes() -> SolidityPolicyAttributes:
    return SolidityPolicyAttributes(
        action=_term(SolidityTermKind.ACTION, "transfer_value"),
        preconditions=(
            _term(SolidityTermKind.PRECONDITION, "missing_access_control"),
        ),
        effects=(
            _term(
                SolidityTermKind.EFFECT, "unauthorized_value_transfer"
            ),
        ),
        mitigations=(
            _term(SolidityTermKind.MITIGATION, "enforce_access_control"),
        ),
        security_concepts=(
            _term(SolidityTermKind.SECURITY_CONCEPT, "access_control"),
        ),
        assumptions=(
            _term(SolidityTermKind.ASSUMPTION, "admin_keys_not_compromised"),
        ),
        language=_term(SolidityTermKind.LANGUAGE, "solidity"),
        scope=_term(SolidityTermKind.SCOPE, "value_transfer"),
        authority_type=_term(
            SolidityTermKind.AUTHORITY_TYPE, "observed_syntax"
        ),
    )


def test_terms_are_typed_versioned_canonical_and_round_trip() -> None:
    action = solidity_term(SolidityTermKind.ACTION, "transfer_value")

    assert action.kind is SolidityTermKind.ACTION
    assert action.schema_version == SOLIDITY_VOCABULARY_SCHEMA_VERSION
    assert action.canonical == (
        "security.solidity-cpt/v1/action/transfer_value"
    )
    assert parse_solidity_term(action.canonical) == action
    assert SolidityTerm.from_dict(action.to_dict()) == action
    assert action.policy_role is SolidityPolicyRole.MATCH_CONSTRAINT
    assert action.grants_policy_authority is False


def test_four_authority_types_are_separate_and_non_interchangeable() -> None:
    names = [item.value for item in SolidityAuthorityType]
    assert names == [
        "observed_syntax",
        "inferred_candidate",
        "reviewed_claim",
        "verified_result",
    ]
    terms = [
        authority_type_term(item) for item in SolidityAuthorityType
    ]
    assert len({item.canonical for item in terms}) == 4
    assert all(
        item.kind is SolidityTermKind.AUTHORITY_TYPE
        and item.policy_role is SolidityPolicyRole.AUTHORITY_LATTICE
        and item.grants_policy_authority is False
        for item in terms
    )
    assert require_authority_type("observed_syntax") is (
        SolidityAuthorityType.OBSERVED_SYNTAX
    )
    assert DEFAULT_SOLIDITY_VOCABULARY.authority_types() == tuple(
        SolidityAuthorityType
    )


def test_policy_attributes_are_canonical_security_ir_values() -> None:
    attributes = _exact_attributes()
    payload = attributes.to_dict()
    wrapped = attributes.to_security_ir_attributes()

    assert list(payload["preconditions"]) == sorted(payload["preconditions"])
    assert wrapped == {SOLIDITY_POLICY_ATTRIBUTES_KEY: payload}
    assert (
        validate_solidity_policy_attributes(
            wrapped, require_exact_policy_constraints=True
        )
        == attributes
    )
    assert SolidityPolicyAttributes.from_dict(payload) == attributes
    assert attributes.has_exact_policy_constraints is True
    assert attributes.grants_policy_authority is False


def test_payload_round_trips_through_security_ir_policy_attributes() -> None:
    attributes = _exact_attributes()
    policy = SecurityPolicy(
        policy_id="policy:solidity-cpt:access-control",
        name="require access control",
        effect=PolicyEffect.REQUIRE,
        attributes=attributes.to_security_ir_attributes(),
    )
    serialized = policy.to_dict()

    assert (
        validate_solidity_policy_attributes(
            serialized["attributes"],
            require_exact_policy_constraints=True,
        )
        == attributes
    )


@pytest.mark.parametrize(
    ("kind", "name"),
    (
        (SolidityTermKind.ACTION, "delete_the_chain"),
        (SolidityTermKind.ACTION, "*"),
        (SolidityTermKind.SCOPE, "any"),
        (SolidityTermKind.LANGUAGE, "unknown"),
        (SolidityTermKind.SECURITY_CONCEPT, "top10"),
        (SolidityTermKind.SECURITY_CONCEPT, "quality"),
        (SolidityTermKind.SECURITY_CONCEPT, "safe"),
        (SolidityTermKind.AUTHORITY_TYPE, "proof"),
    ),
)
def test_unknown_wildcard_quality_and_broadened_terms_fail_closed(
    kind: SolidityTermKind, name: str
) -> None:
    with pytest.raises(SolidityVocabularyError):
        solidity_term(kind, name)


def test_version_category_and_payload_shape_drift_fail_closed() -> None:
    canonical = _term(SolidityTermKind.LANGUAGE, "solidity")
    with pytest.raises(
        SolidityVocabularyError,
        match="unsupported Solidity CPT vocabulary version",
    ):
        parse_solidity_term(
            canonical.replace("/v1/", "/v2/")
        )
    with pytest.raises(
        SolidityVocabularyError, match="does not match its typed components"
    ):
        SolidityTerm.from_dict(
            {
                "kind": "language",
                "name": "solidity",
                "schema_version": SOLIDITY_VOCABULARY_SCHEMA_VERSION,
                "term": "security.solidity-cpt/v1/language/yul",
            }
        )


def test_aliases_resolve_without_discarding_kind() -> None:
    resolved = resolve_solidity_term(SolidityTermKind.LANGUAGE, "sol")
    assert resolved.name == "solidity"
    aliases = validate_solidity_aliases(
        (
            SolidityAlias(
                SolidityTermKind.SECURITY_CONCEPT, "reentry", "reentrancy"
            ),
        )
    )
    assert aliases[0].target.name == "reentrancy"


def test_vocabulary_registry_is_immutable_and_complete() -> None:
    vocab = SolidityVocabulary()
    assert vocab.contains(SolidityTermKind.NODE_TYPE, "observed_syntax")
    assert vocab.contains(SolidityTermKind.NODE_TYPE, "verified_result")
    assert vocab.contains(SolidityTermKind.EDGE_TYPE, "grounded_in")
    with pytest.raises(SolidityVocabularyError):
        SolidityVocabulary(
            terms={"action": frozenset({"transfer_value"})}
        )
