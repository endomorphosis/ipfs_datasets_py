"""Tests for release-safe CVEfixes classification materialization."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.security_ir.cvefixes.classification import (
    CLASSIFICATION_CONFIG_CID,
    UNRESOLVED_FORMALISM,
    ClassificationMaterializationError,
    materialize_classification,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.projector import (
    canonical_source_row_cid,
    project_cvefixes_row,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    DerivedAuthority,
    FormalView,
    PolicyCandidate,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.source_snapshot import (
    CVEfixesSourceRow,
    adapt_cvefixes_row,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.vocabulary import (
    CVEFIXES_POLICY_ATTRIBUTES_KEY,
    CVEfixesPolicyAttributes,
)


def _raw_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "cve_id": "CVE-2024-12345",
        "hash": "a" * 40,
        "repo_url": "https://github.com/example/project",
        "cve_description": (
            '[{"lang":"en","value":"Untrusted input reached an evaluator."}]'
        ),
        "cvss2_base_score": None,
        "cvss3_base_score": 8.1,
        "published_date": "2024-01-02T03:04Z",
        "severity": "HIGH",
        "cwe_id": "CWE-95",
        "cwe_name": "Eval Injection",
        "cwe_description": "Untrusted input reaches an evaluator.",
        "commit_message": "validate input",
        "commit_date": "2024-01-01 01:02:03 +0000",
        "version_tag": "v1.2.3",
        "repo_total_files": 12,
        "repo_total_commits": 34,
        "file_paths": ["src/evaluator.py"],
        "language": "Python",
        "diff_stats": '{"src/evaluator.py":{"lines_added":1,"lines_deleted":1}}',
        "diff_with_context": None,
        "vulnerable_code": "def run(value):\n    return eval(value)\n",
        "fixed_code": "def run(value):\n    return parse_literal(value)\n",
        "security_keywords": ["injection"],
    }
    row.update(changes)
    return row


def _row(*, row_index: int = 7, **changes: object) -> CVEfixesSourceRow:
    return adapt_cvefixes_row(_raw_row(**changes), row_index=row_index)


def _attributes(candidate: PolicyCandidate) -> CVEfixesPolicyAttributes:
    return CVEfixesPolicyAttributes.from_dict(
        candidate.scope[CVEFIXES_POLICY_ATTRIBUTES_KEY]
    )


def test_materialization_is_deterministic_classification_only_and_bound() -> None:
    row = _row()
    projection = project_cvefixes_row(row)

    first = materialize_classification(row, projection)
    second = materialize_classification(row, projection)
    attributes = _attributes(first.candidate)
    expression = json.loads(first.formal_view.expression)

    assert first == second
    assert first.candidate.cid == second.candidate.cid
    assert first.formal_view.cid == second.formal_view.cid
    assert first.candidate.authority is DerivedAuthority.CANDIDATE
    assert first.formal_view.authority is DerivedAuthority.NON_AUTHORITATIVE
    assert first.candidate.effect == "audit"
    assert first.candidate.config_cid == CLASSIFICATION_CONFIG_CID
    assert first.formal_view.config_cid == CLASSIFICATION_CONFIG_CID
    assert first.candidate.source_cids == (canonical_source_row_cid(row),)
    assert first.candidate.parent_cids == (projection.cid,)
    assert set(first.formal_view.parent_cids) == {
        projection.cid,
        first.candidate.cid,
    }

    assert attributes.classification_only is True
    assert attributes.has_exact_policy_constraints is False
    assert attributes.policy_match_terms == ()
    assert [item.name for item in attributes.cve_ids] == [
        "CVE-2024-12345"
    ]
    assert [item.name for item in attributes.cwe_ids] == ["CWE-95"]
    assert first.candidate.payload["candidate_role"] == "classification_only"
    assert first.candidate.payload["grants_execution_authority"] is False
    assert first.candidate.payload["semantic_facts_promoted"] is False
    assert first.candidate.payload["semantic_fact_count"] == len(
        projection.semantic_facts
    )
    assert first.candidate.payload["language_annotation"]["name"] == "python"
    assert (
        first.candidate.payload["language_annotation_is_policy_constraint"]
        is False
    )

    assert first.formal_view.formalism == UNRESOLVED_FORMALISM
    assert expression["candidate_cid"] == first.candidate.cid
    assert expression["projection_cid"] == projection.cid
    assert expression["resolution"] == "unresolved"
    assert expression["grants_execution_authority"] is False
    assert expression["proof_authoritative"] is False
    assert expression["exact_forbidden_constraints"] == {
        "action": None,
        "effects": [],
        "preconditions": [],
        "scope": None,
    }
    assert "remain unresolved" in expression["statement"]

    # Both wire forms remain stable under the strict schema decoders.
    assert PolicyCandidate.from_dict(first.candidate.to_dict()) == first.candidate
    assert FormalView.from_dict(first.formal_view.to_dict()) == first.formal_view


def test_invalid_optional_vocabulary_values_are_omitted_not_inferred() -> None:
    # The source adapter accepts these inert metadata values, while the closed
    # vocabulary deliberately does not.
    row = _row(
        cve_id="CVE-2100-12345",
        cwe_id="NVD-CWE-noinfo",
        language="Brainfuck",
    )
    projection = project_cvefixes_row(row)

    result = materialize_classification(row, projection)
    attributes = _attributes(result.candidate)

    assert attributes.classification_only is True
    assert attributes.cve_ids == ()
    assert attributes.cwe_ids == ()
    assert attributes.policy_match_terms == ()
    assert result.candidate.payload["classification_status"] == {
        "cve": "omitted_invalid",
        "cwe": "omitted_invalid",
    }
    assert result.candidate.payload["language_annotation"] is None
    assert (
        result.candidate.payload["language_annotation_status"]
        == "omitted_invalid"
    )
    assert json.loads(result.formal_view.expression)[
        "exact_forbidden_constraints"
    ]["action"] is None


def test_projection_language_alias_is_descriptive_not_a_policy_term() -> None:
    row = _row(language="C++")
    projection = project_cvefixes_row(row)

    result = materialize_classification(row, projection)
    attributes = _attributes(result.candidate)

    assert result.candidate.payload["language_annotation"]["name"] == "cpp"
    assert attributes.language is None
    assert attributes.policy_match_terms == ()


def test_cross_row_projection_binding_fails_closed() -> None:
    first_row = _row()
    second_row = _row(row_index=8, hash="b" * 40)
    projection = project_cvefixes_row(first_row)

    with pytest.raises(
        ClassificationMaterializationError,
        match="not bound to the supplied source row",
    ):
        materialize_classification(second_row, projection)


def test_materializer_requires_typed_validated_inputs() -> None:
    row = _row()
    projection = project_cvefixes_row(row)

    with pytest.raises(TypeError, match="row must be CVEfixesSourceRow"):
        materialize_classification(row.to_dict(), projection)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="projection must be ProjectionResult"):
        materialize_classification(row, projection.to_dict())  # type: ignore[arg-type]
