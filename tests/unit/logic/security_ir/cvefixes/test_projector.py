"""Conformance tests for loss-aware vulnerable/fixed semantic projection."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.security_ir.cvefixes.projector import (
    AMBIGUOUS_PATH,
    DEFAULT_LANGUAGE_ADAPTERS,
    DiagnosticCode,
    EvidencePolarity,
    ExtractionMethod,
    LanguageAdapterRegistry,
    ModelSemanticCandidate,
    ProjectionError,
    ProjectorConfig,
    SemanticKind,
    UnitKind,
    VulnerableFixedProjector,
    canonical_source_row_cid,
    project_cvefixes_row,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.source_snapshot import (
    CVEfixesSourceRow,
    adapt_cvefixes_row,
)


VULNERABLE_CODE = """\
def read_user_file(root, user_path):
    return open(user_path).read()
"""

FIXED_CODE = """\
def read_user_file(root, user_path):
    if ".." in user_path:
        raise ValueError("unsafe path")
    return open(root + "/" + user_path).read()
"""

UNIFIED_DIFF = """\
diff --git a/src/reader.py b/src/reader.py
index 1111111..2222222 100644
--- a/src/reader.py
+++ b/src/reader.py
@@ -1,2 +1,4 @@
 def read_user_file(root, user_path):
-    return open(user_path).read()
+    if ".." in user_path:
+        raise ValueError("unsafe path")
+    return open(root + "/" + user_path).read()
"""


def _raw_row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "cve_id": "CVE-2024-12345",
        "hash": "a" * 40,
        "repo_url": "https://github.com/example/project",
        "cve_description": (
            '[{"lang":"en","value":"Untrusted paths could escape the root."}]'
        ),
        "cvss2_base_score": None,
        "cvss3_base_score": 7.5,
        "published_date": "2024-01-02T03:04Z",
        "severity": "HIGH",
        "cwe_id": "CWE-22",
        "cwe_name": "Path Traversal",
        "cwe_description": "Untrusted path input escapes a root.",
        "commit_message": "confine user paths",
        "commit_date": "2024-01-01 01:02:03 +0000",
        "version_tag": "v1.2.3",
        "repo_total_files": 12,
        "repo_total_commits": 34,
        "file_paths": ["src/reader.py"],
        "language": "Python",
        "diff_stats": '{"src/reader.py":{"lines_added":3,"lines_deleted":1}}',
        "diff_with_context": UNIFIED_DIFF,
        "vulnerable_code": VULNERABLE_CODE,
        "fixed_code": FIXED_CODE,
        "security_keywords": ["path traversal"],
    }
    value.update(changes)
    return value


def _row(**changes: object) -> CVEfixesSourceRow:
    return adapt_cvefixes_row(_raw_row(**changes), row_index=7)


def _codes(result) -> set[DiagnosticCode]:
    return {item.code for item in result.diagnostics}


def test_python_projection_is_deterministic_paired_and_provenance_bound() -> None:
    row = _row()
    first = project_cvefixes_row(row)
    second = project_cvefixes_row(row)

    assert first == second
    assert first.projection_id == second.projection_id
    assert first.to_dict() == second.to_dict()
    assert first.source_cid == canonical_source_row_cid(row)
    assert first.supported is True
    assert {item.unit_kind for item in first.pairs} == {
        UnitKind.FILE,
        UnitKind.HUNK,
        UnitKind.SYMBOL,
    }
    assert all(item.complete for item in first.pairs)
    assert len(first.complete_pairs) == len(first.pairs)
    assert {item.path for item in first.pairs} == {"src/reader.py"}

    for unit in first.code_units:
        assert unit.source_cids == (first.source_cid,)
        assert unit.config_cid == first.config_cid
        assert unit.payload["source_revision"].startswith("d4f5c4e")
        assert unit.payload["source_row_index"] == 7
        assert unit.payload["grants_execution_authority"] is False
        assert len(unit.payload["body_sha256"]) == 64
        if unit.polarity == "vulnerable":
            assert (
                unit.payload["evidence_polarity"]
                == EvidencePolarity.VULNERABLE_POSITIVE.value
            )
        else:
            assert (
                unit.payload["evidence_polarity"]
                == EvidencePolarity.FIXED_NEGATIVE.value
            )

    # The public record contains bounded excerpts and body identities rather
    # than relying on an unbounded body as its only evidence.
    assert all(
        len(unit.payload["excerpt"]) <= ProjectorConfig().max_excerpt_chars
        for unit in first.code_units
    )
    with pytest.raises(TypeError):
        first.code_units[0].payload["source_row_index"] = 8
    with pytest.raises(FrozenInstanceError):
        first.pairs[0].path = "changed.py"  # type: ignore[misc]


def test_grounded_facts_cover_semantic_kinds_without_granting_authority() -> None:
    result = project_cvefixes_row(_row())

    assert {item.kind for item in result.semantic_facts} == {
        SemanticKind.PRECONDITION,
        SemanticKind.ACTION,
        SemanticKind.EFFECT,
        SemanticKind.MITIGATION,
    }
    assert all(
        item.extraction_method is ExtractionMethod.DETERMINISTIC_SYNTAX
        for item in result.semantic_facts
    )
    assert all(item.confidence == 1.0 for item in result.semantic_facts)
    assert all(not item.model_id for item in result.semantic_facts)
    assert all(
        item.to_dict()["authority"] == "observed_candidate"
        and item.to_dict()["grants_execution_authority"] is False
        for item in result.semantic_facts
    )
    assert any(
        item.kind is SemanticKind.MITIGATION
        and item.evidence_polarity is EvidencePolarity.FIXED_NEGATIVE
        and item.predicate.startswith("added_guard:")
        for item in result.semantic_facts
    )
    assert {
        item.evidence_polarity for item in result.semantic_facts
    } == {
        EvidencePolarity.VULNERABLE_POSITIVE,
        EvidencePolarity.FIXED_NEGATIVE,
    }


def test_fixed_code_remains_negative_evidence_not_a_forbidden_positive() -> None:
    result = project_cvefixes_row(_row())
    units = {item.cid: item for item in result.code_units}
    fixed_facts = [
        item
        for item in result.semantic_facts
        if units[item.code_unit_cid].polarity == "fixed"
    ]

    assert fixed_facts
    assert all(
        item.evidence_polarity is EvidencePolarity.FIXED_NEGATIVE
        for item in fixed_facts
    )
    assert all(
        item.evidence_polarity is not EvidencePolarity.VULNERABLE_POSITIVE
        for item in fixed_facts
    )


def test_unsupported_language_retains_pairs_and_explicitly_abstains() -> None:
    row = _row(
        language="Rust",
        file_paths=["src/reader.rs"],
        vulnerable_code="fn read(path: &str) { unsafe_read(path); }",
        fixed_code="fn read(path: &str) { confined_read(path); }",
        diff_with_context="-fn read(path: &str) { unsafe_read(path); }\n"
        "+fn read(path: &str) { confined_read(path); }\n",
    )

    result = project_cvefixes_row(row)

    assert result.supported is False
    assert DiagnosticCode.UNSUPPORTED_LANGUAGE in _codes(result)
    assert result.code_units
    assert result.complete_pairs
    assert result.semantic_facts == ()
    assert {item.polarity for item in result.code_units} == {
        "vulnerable",
        "fixed",
    }
    assert all(
        item.payload["grants_execution_authority"] is False
        for item in result.code_units
    )


def test_ambiguous_multifile_bodies_and_hunks_are_retained_without_assignment() -> None:
    row = _row(
        language="Go",
        file_paths=["a.go", "b.go"],
        vulnerable_code="dangerous(value)",
        fixed_code="safe(value)",
        diff_with_context="-dangerous(value)\n+safe(value)\n",
    )

    result = project_cvefixes_row(row)

    assert DiagnosticCode.AMBIGUOUS_PATH in _codes(result)
    assert DiagnosticCode.AMBIGUOUS_HUNK in _codes(result)
    assert {item.path for item in result.pairs} == {AMBIGUOUS_PATH}
    assert all(
        tuple(item.payload["candidate_paths"]) == ("a.go", "b.go")
        for item in result.code_units
    )
    serialized = result.to_dict()
    assert "a.go" in str(serialized) and "b.go" in str(serialized)
    assert not any(item.path in {"a.go", "b.go"} for item in result.code_units)


@pytest.mark.parametrize(
    ("missing_field", "code"),
    [
        ("vulnerable_code", DiagnosticCode.MISSING_VULNERABLE),
        ("fixed_code", DiagnosticCode.MISSING_FIXED),
    ],
)
def test_unpaired_side_is_retained_with_diagnostic(
    missing_field: str, code: DiagnosticCode
) -> None:
    changes = {
        missing_field: None,
        "diff_with_context": None,
    }
    result = project_cvefixes_row(_row(**changes))

    assert result.code_units
    assert result.complete_pairs == ()
    assert code in _codes(result)
    assert all(
        bool(item.vulnerable_cid) != bool(item.fixed_cid)
        for item in result.pairs
    )


def test_malformed_supported_syntax_is_retained_with_parse_diagnostics() -> None:
    result = project_cvefixes_row(
        _row(
            vulnerable_code="def broken(:\n",
            fixed_code="def also_broken(:\n",
            diff_with_context=None,
        )
    )

    assert result.supported is True
    assert result.code_units
    assert result.complete_pairs
    assert DiagnosticCode.SYNTAX_UNPARSEABLE in _codes(result)
    assert DiagnosticCode.NO_SEMANTIC_FACTS in _codes(result)
    assert result.semantic_facts == ()


def test_model_candidates_are_separate_versioned_facts() -> None:
    row = _row()
    deterministic = project_cvefixes_row(row)
    vulnerable_unit = next(
        item
        for item in deterministic.code_units
        if item.unit_kind == "file" and item.polarity == "vulnerable"
    )
    candidate = ModelSemanticCandidate(
        kind=SemanticKind.EFFECT,
        predicate="candidate:read_outside_root",
        evidence_polarity=EvidencePolarity.VULNERABLE_POSITIVE,
        code_unit_cid=vulnerable_unit.cid,
        model_id="security-projector",
        model_revision="0123456789abcdef",
        confidence=0.73,
    )

    projected = project_cvefixes_row(row, model_candidates=(candidate,))
    model_facts = [
        item
        for item in projected.semantic_facts
        if item.extraction_method is ExtractionMethod.MODEL_ASSISTED
    ]

    assert len(model_facts) == 1
    assert model_facts[0].model_id == "security-projector"
    assert model_facts[0].model_revision == "0123456789abcdef"
    assert model_facts[0].confidence == 0.73
    assert all(
        item.extraction_method is ExtractionMethod.DETERMINISTIC_SYNTAX
        for item in deterministic.semantic_facts
    )
    assert model_facts[0].to_dict()["grants_execution_authority"] is False


def test_model_candidate_binding_and_polarity_fail_closed() -> None:
    row = _row()
    result = project_cvefixes_row(row)
    fixed_unit = next(
        item
        for item in result.code_units
        if item.unit_kind == "file" and item.polarity == "fixed"
    )

    with pytest.raises(ProjectionError, match="outside this projection"):
        project_cvefixes_row(
            row,
            model_candidates=(
                ModelSemanticCandidate(
                    kind=SemanticKind.ACTION,
                    predicate="candidate:unsafe_action",
                    evidence_polarity=EvidencePolarity.VULNERABLE_POSITIVE,
                    code_unit_cid=canonical_source_row_cid(row),
                    model_id="model",
                    model_revision="revision",
                    confidence=0.5,
                ),
            ),
        )
    with pytest.raises(ProjectionError, match="polarity conflicts"):
        project_cvefixes_row(
            row,
            model_candidates=(
                ModelSemanticCandidate(
                    kind=SemanticKind.ACTION,
                    predicate="candidate:unsafe_action",
                    evidence_polarity=EvidencePolarity.VULNERABLE_POSITIVE,
                    code_unit_cid=fixed_unit.cid,
                    model_id="model",
                    model_revision="revision",
                    confidence=0.5,
                ),
            ),
        )


def test_diff_hunks_preserve_old_new_lines_and_context_pairing() -> None:
    result = project_cvefixes_row(_row())
    hunk_pair = next(item for item in result.pairs if item.unit_kind is UnitKind.HUNK)
    units = {item.cid: item for item in result.code_units}
    vulnerable = units[hunk_pair.vulnerable_cid]
    fixed = units[hunk_pair.fixed_cid]

    assert vulnerable.payload["start_line"] == 1
    assert fixed.payload["start_line"] == 1
    assert "open(user_path)" in vulnerable.payload["excerpt"]
    assert '".." in user_path' not in vulnerable.payload["excerpt"]
    assert '".." in user_path' in fixed.payload["excerpt"]
    assert "open(user_path)" not in fixed.payload["excerpt"]
    assert vulnerable.payload["pair_key"] == fixed.payload["pair_key"]
    assert DiagnosticCode.DIFF_UNPARSEABLE not in _codes(result)


def test_resource_limits_are_explicit_and_deterministic() -> None:
    config = ProjectorConfig(max_hunks=1, max_symbols_per_unit=1)
    row = _row(
        vulnerable_code=(
            "def first():\n    return one()\n"
            "def second():\n    return two()\n"
        ),
        fixed_code=(
            "def first():\n    return safe_one()\n"
            "def second():\n    return safe_two()\n"
        ),
        diff_with_context=(
            "@@ -1 +1 @@\n-one()\n+safe_one()\n"
            "@@ -3 +3 @@\n-two()\n+safe_two()\n"
        ),
    )

    result = project_cvefixes_row(row, config=config)

    assert DiagnosticCode.LIMIT_EXCEEDED in _codes(result)
    assert len([item for item in result.pairs if item.unit_kind is UnitKind.HUNK]) == 1
    assert (
        len([item for item in result.pairs if item.unit_kind is UnitKind.SYMBOL])
        == 1
    )
    assert result == project_cvefixes_row(row, config=config)


def test_registry_versions_are_bound_into_effective_config_identity() -> None:
    default = VulnerableFixedProjector(
        ProjectorConfig(), DEFAULT_LANGUAGE_ADAPTERS
    )

    class VersionedPythonAdapter:
        language = "python"
        version = "test-python-adapter/v2"

        def project(self, source: str):
            return DEFAULT_LANGUAGE_ADAPTERS.resolve("python").project(source)

    changed = VulnerableFixedProjector(
        ProjectorConfig(),
        LanguageAdapterRegistry(
            (VersionedPythonAdapter(),),
            aliases={"python": "python", "py": "python"},
        ),
    )

    assert default.config_cid != changed.config_cid
    assert (
        default.project(_row()).projection_id
        != changed.project(_row()).projection_id
    )


def test_invalid_external_source_cid_fails_even_for_diagnostic_only_row() -> None:
    row = _row(
        vulnerable_code=None,
        fixed_code=None,
        diff_with_context=None,
    )

    with pytest.raises(ProjectionError, match="CIDv1"):
        project_cvefixes_row(row, source_cid="not-a-cid")
