"""Conformance tests for the isolated CVEfixes Security IR vocabulary."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.security_ir.cvefixes.vocabulary import (
    CVEFIXES_POLICY_ATTRIBUTES_KEY,
    CVEFIXES_VOCABULARY_SCHEMA_VERSION,
    CVEfixesAlias,
    CVEfixesPolicyAttributes,
    CVEfixesPolicyRole,
    CVEfixesTerm,
    CVEfixesTermKind,
    CVEfixesVocabularyError,
    cve_classification,
    cvefixes_term,
    cwe_classification,
    parse_cvefixes_term,
    resolve_cvefixes_term,
    validate_cvefixes_aliases,
    validate_cvefixes_policy_attributes,
)
from ipfs_datasets_py.logic.security_ir.model import PolicyEffect, SecurityPolicy


def _term(kind: CVEfixesTermKind, name: str) -> str:
    return cvefixes_term(kind, name).canonical


def _exact_attributes() -> CVEfixesPolicyAttributes:
    return CVEfixesPolicyAttributes(
        action=_term(
            CVEfixesTermKind.ACTION,
            "construct_path_from_untrusted_input",
        ),
        preconditions=(
            _term(
                CVEfixesTermKind.PRECONDITION,
                "missing_canonicalization",
            ),
            _term(
                CVEfixesTermKind.PRECONDITION,
                "attacker_controls_path",
            ),
        ),
        effects=(
            _term(
                CVEfixesTermKind.EFFECT,
                "read_outside_allowed_root",
            ),
        ),
        mitigations=(
            _term(
                CVEfixesTermKind.MITIGATION,
                "canonicalize_and_confine",
            ),
        ),
        language=_term(CVEfixesTermKind.LANGUAGE, "python"),
        scope=_term(CVEfixesTermKind.SCOPE, "filesystem"),
        cve_ids=("CVE-2024-12345",),
        cwe_ids=("CWE-22",),
    )


def test_terms_are_typed_versioned_canonical_and_round_trip() -> None:
    action = cvefixes_term(
        CVEfixesTermKind.ACTION,
        "construct_path_from_untrusted_input",
    )

    assert action.kind is CVEfixesTermKind.ACTION
    assert action.schema_version == CVEFIXES_VOCABULARY_SCHEMA_VERSION
    assert action.canonical == (
        "security.cvefixes/v1/action/"
        "construct_path_from_untrusted_input"
    )
    assert parse_cvefixes_term(action.canonical) == action
    assert CVEfixesTerm.from_dict(action.to_dict()) == action
    assert action.policy_role is CVEfixesPolicyRole.MATCH_CONSTRAINT
    assert action.grants_policy_authority is False


def test_policy_attributes_are_canonical_security_ir_values() -> None:
    attributes = _exact_attributes()
    payload = attributes.to_dict()
    wrapped = attributes.to_security_ir_attributes()

    assert list(payload["preconditions"]) == sorted(payload["preconditions"])
    assert wrapped == {CVEFIXES_POLICY_ATTRIBUTES_KEY: payload}
    assert (
        validate_cvefixes_policy_attributes(
            wrapped, require_exact_policy_constraints=True
        )
        == attributes
    )
    assert CVEfixesPolicyAttributes.from_dict(payload) == attributes
    assert attributes.has_exact_policy_constraints is True
    assert attributes.grants_policy_authority is False
    assert all(
        term.kind not in {CVEfixesTermKind.CVE, CVEfixesTermKind.CWE}
        for term in attributes.policy_match_terms
    )


def test_payload_round_trips_through_security_ir_policy_attributes() -> None:
    attributes = _exact_attributes()
    policy = SecurityPolicy(
        policy_id="policy:cvefixes:path-confinement",
        name="deny path traversal",
        effect=PolicyEffect.DENY,
        attributes=attributes.to_security_ir_attributes(),
    )
    serialized = policy.to_dict()

    assert (
        validate_cvefixes_policy_attributes(
            serialized["attributes"],
            require_exact_policy_constraints=True,
        )
        == attributes
    )


@pytest.mark.parametrize(
    ("kind", "name"),
    (
        (CVEfixesTermKind.ACTION, "delete_the_internet"),
        (CVEfixesTermKind.ACTION, "*"),
        (CVEfixesTermKind.SCOPE, "file*"),
        (CVEfixesTermKind.SCOPE, "any"),
        (CVEfixesTermKind.LANGUAGE, "unknown"),
        (CVEfixesTermKind.CWE, "CWE-*"),
        (CVEfixesTermKind.CWE, "cwe-22"),
    ),
)
def test_unknown_and_wildcard_broadened_terms_fail_closed(
    kind: CVEfixesTermKind, name: str
) -> None:
    with pytest.raises(CVEfixesVocabularyError):
        cvefixes_term(kind, name)


def test_version_category_and_payload_shape_drift_fail_closed() -> None:
    canonical = _term(CVEfixesTermKind.LANGUAGE, "python")
    with pytest.raises(
        CVEfixesVocabularyError, match="unsupported CVEfixes vocabulary version"
    ):
        parse_cvefixes_term(canonical.replace("/v1/", "/v2/"))
    with pytest.raises(CVEfixesVocabularyError, match="expected a scope term"):
        parse_cvefixes_term(
            canonical, expected_kind=CVEfixesTermKind.SCOPE
        )

    payload = _exact_attributes().to_dict()
    with pytest.raises(CVEfixesVocabularyError, match="fields are not canonical"):
        CVEfixesPolicyAttributes.from_dict({**payload, "vendor": "magic"})
    with pytest.raises(
        CVEfixesVocabularyError, match="unsupported CVEfixes policy"
    ):
        CVEfixesPolicyAttributes.from_dict(
            {**payload, "schema_version": "security.cvefixes/v2"}
        )
    with pytest.raises(CVEfixesVocabularyError, match="must be unique"):
        replace(
            _exact_attributes(),
            effects=(
                _term(
                    CVEfixesTermKind.EFFECT,
                    "read_outside_allowed_root",
                ),
            )
            * 2,
        )


def test_cve_and_cwe_are_classification_not_policy_authority() -> None:
    cve = cve_classification("CVE-2024-12345")
    cwe = cwe_classification("CWE-22")
    attributes = CVEfixesPolicyAttributes(
        cve_ids=(cve,),
        cwe_ids=(cwe,),
    )

    assert cve.policy_role is CVEfixesPolicyRole.CLASSIFICATION_ONLY
    assert cwe.policy_role is CVEfixesPolicyRole.CLASSIFICATION_ONLY
    assert cwe.grants_policy_authority is False
    assert attributes.classification_only is True
    assert attributes.has_exact_policy_constraints is False
    assert attributes.policy_match_terms == ()
    with pytest.raises(
        CVEfixesVocabularyError,
        match="classifications are not sufficient policy authority",
    ):
        attributes.require_exact_policy_constraints()
    with pytest.raises(CVEfixesVocabularyError):
        validate_cvefixes_policy_attributes(
            attributes.to_security_ir_attributes(),
            require_exact_policy_constraints=True,
        )


def test_scoped_aliases_preserve_scope_and_cannot_broaden() -> None:
    resolved = resolve_cvefixes_term(
        CVEfixesTermKind.ACTION,
        "build_tainted_path",
        scope="filesystem",
    )

    assert resolved.term.name == "construct_path_from_untrusted_input"
    assert resolved.scope is not None
    assert resolved.scope.name == "filesystem"
    assert resolved.to_dict() == {
        "scope": _term(CVEfixesTermKind.SCOPE, "filesystem"),
        "term": _term(
            CVEfixesTermKind.ACTION,
            "construct_path_from_untrusted_input",
        ),
    }
    with pytest.raises(CVEfixesVocabularyError, match="requires an exact scope"):
        resolve_cvefixes_term(
            CVEfixesTermKind.ACTION, "build_tainted_path"
        )
    with pytest.raises(CVEfixesVocabularyError, match="not valid in scope"):
        resolve_cvefixes_term(
            CVEfixesTermKind.ACTION,
            "build_tainted_path",
            scope="process",
        )
    with pytest.raises(CVEfixesVocabularyError, match="wildcard"):
        resolve_cvefixes_term(
            CVEfixesTermKind.ACTION,
            "build_tainted_path",
            scope="file*",
        )


def test_alias_registry_rejects_scope_erasure_and_duplicate_targets() -> None:
    with pytest.raises(CVEfixesVocabularyError, match="require an exact scope"):
        CVEfixesAlias(
            CVEfixesTermKind.ACTION,
            "path_builder",
            "construct_path_from_untrusted_input",
        )

    alias = CVEfixesAlias(
        CVEfixesTermKind.ACTION,
        "path_builder",
        "construct_path_from_untrusted_input",
        "filesystem",
    )
    with pytest.raises(CVEfixesVocabularyError, match="duplicate"):
        validate_cvefixes_aliases((alias, alias))

    # The same source spelling may be explicitly defined for two scopes, but
    # each target retains its scope and therefore cannot be merged.
    scoped = validate_cvefixes_aliases(
        (
            alias,
            CVEfixesAlias(
                CVEfixesTermKind.ACTION,
                "path_builder",
                "execute_command_from_untrusted_input",
                "process",
            ),
        )
    )
    assert {item.target.scope.name for item in scoped if item.target.scope} == {
        "filesystem",
        "process",
    }
