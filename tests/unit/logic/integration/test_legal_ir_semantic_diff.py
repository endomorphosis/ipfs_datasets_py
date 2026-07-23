"""Tests for LegalIR semantic diffs and amendment impact analysis."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning import (
    DEFAULT_SEMANTIC_DIFF_VALIDATION_COMMAND,
    LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION,
    LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION,
    LegalIRArtifactFamily,
    LegalIRSemanticChangeKind,
    LegalIRSemanticDiffReport,
    build_legal_ir_amendment_impact_analysis,
    compute_legal_ir_semantic_diff,
    known_legal_ir_schema_versions,
    legal_ir_semantic_diff,
    project_legal_ir_semantic_diff_to_codex_todos,
    validate_legal_ir_schema_compatibility,
)


def _before_snapshot() -> dict[str, object]:
    return {
        "schema_version": "legal-ir-artifact-v1",
        "schema_versions": {
            "legal_ir": "legal-ir-v1",
            "obligations": "legal-ir-proof-obligation-v1",
        },
        "compiler_commit": "compiler-a",
        "source_revisions": {
            "doc-1": {"revision_id": "doc-1", "sha256": "source-old"},
        },
        "learned_guidance": {
            "active": False,
            "export_id": "",
        },
        "amendments": {
            "amd-7": {
                "amendment_id": "amd-7",
                "status": "introduced",
                "affected_obligation_ids": ["obl-disclose", "obl-retain"],
                "affected_citations": ["ORS 192.410"],
            }
        },
        "obligations": [
            {
                "obligation_id": "obl-disclose",
                "statement": "The agency shall disclose records within 30 days.",
                "operator": "shall",
                "subject": ["agency"],
                "action": ["disclose"],
                "object": ["records"],
                "conditions": ["public records request received"],
                "exceptions": [],
                "citations": ["ORS 192.410"],
                "temporal_window": {"effective_date": "2025-01-01"},
                "ambiguity": {"status": "unresolved", "unresolved_count": 1},
                "proof_status": {"status": "proved", "trust_status": "trusted"},
                "amendment_ids": ["amd-7"],
            },
            {
                "obligation_id": "obl-notice",
                "statement": "The agency shall notify requesters after denial.",
                "operator": "shall",
                "subject": ["agency"],
                "action": ["notify"],
                "conditions": ["denial issued", "written request"],
                "citations": ["ORS 192.411"],
                "proof_status": {"status": "proved"},
            },
            {
                "obligation_id": "obl-retain",
                "statement": "The agency shall retain logs for five years.",
                "operator": "shall",
                "subject": ["agency"],
                "action": ["retain"],
                "object": ["logs"],
                "citations": ["ORS 192.500"],
                "proof_status": {"status": "proved"},
                "amendment_ids": ["amd-7"],
            },
        ],
    }


def _after_snapshot() -> dict[str, object]:
    return {
        "schema_version": "legal-ir-artifact-v2",
        "schema_versions": {
            "legal_ir": "legal-ir-v2",
            "obligations": "legal-ir-proof-obligation-v1",
        },
        "compiler_commit": "compiler-b",
        "source_revisions": {
            "doc-1": {"revision_id": "doc-1", "sha256": "source-new"},
        },
        "learned_guidance": {
            "active": True,
            "export_id": "guidance-5",
        },
        "amendments": {
            "amd-7": {
                "amendment_id": "amd-7",
                "status": "enacted",
                "affected_obligation_ids": ["obl-disclose", "obl-retain", "obl-publish"],
                "affected_citations": ["ORS 192.410", "ORS 192.420"],
            }
        },
        "obligations": [
            {
                "obligation_id": "obl-disclose",
                "statement": "The agency shall disclose nonexempt records within 45 days.",
                "operator": "shall",
                "subject": ["agency"],
                "action": ["disclose"],
                "object": ["records"],
                "conditions": ["public records request received", "request is perfected"],
                "exceptions": ["security exemption"],
                "citations": ["ORS 192.420"],
                "temporal_window": {"effective_date": "2026-01-01"},
                "ambiguity": {"status": "resolved", "unresolved_count": 0},
                "proof_status": {"status": "theorem_failed", "trust_status": "untrusted"},
                "amendment_ids": ["amd-7"],
                "metadata": {
                    "compiler_impact": {
                        "verified": True,
                        "regression": True,
                        "target_component": "legal_ir.proof_router",
                        "owned_paths": [
                            "ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_router.py"
                        ],
                        "validation_commands": [DEFAULT_SEMANTIC_DIFF_VALIDATION_COMMAND],
                    }
                },
            },
            {
                "obligation_id": "obl-notice",
                "statement": "The agency shall notify requesters after denial.",
                "operator": "shall",
                "subject": ["agency"],
                "action": ["notify"],
                "conditions": ["denial issued"],
                "citations": ["ORS 192.411"],
                "proof_status": {"status": "proved"},
            },
            {
                "obligation_id": "obl-publish",
                "statement": "The agency shall publish a fee schedule.",
                "operator": "shall",
                "subject": ["agency"],
                "action": ["publish"],
                "object": ["fee_schedule"],
                "citations": ["ORS 192.420"],
                "proof_status": {"status": "unknown"},
                "amendment_ids": ["amd-7"],
            },
        ],
    }


def test_semantic_diff_classifies_required_change_kinds_and_dimensions() -> None:
    report = compute_legal_ir_semantic_diff(_before_snapshot(), _after_snapshot())
    payload = report.to_dict()

    assert payload["schema_version"] == LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION
    assert report.before_digest != report.after_digest
    assert {
        LegalIRSemanticChangeKind.OBLIGATION_ADDED.value,
        LegalIRSemanticChangeKind.OBLIGATION_REMOVED.value,
        LegalIRSemanticChangeKind.OBLIGATION_NARROWED.value,
        LegalIRSemanticChangeKind.OBLIGATION_BROADENED.value,
        LegalIRSemanticChangeKind.TEMPORALLY_SHIFTED.value,
        LegalIRSemanticChangeKind.CITATION_CHANGED.value,
        LegalIRSemanticChangeKind.AMBIGUITY_CHANGED.value,
        LegalIRSemanticChangeKind.PROOF_STATUS_CHANGED.value,
        LegalIRSemanticChangeKind.SOURCE_REVISION_CHANGED.value,
        LegalIRSemanticChangeKind.AMENDMENT_CHANGED.value,
        LegalIRSemanticChangeKind.COMPILER_COMMIT_CHANGED.value,
        LegalIRSemanticChangeKind.SCHEMA_VERSION_CHANGED.value,
        LegalIRSemanticChangeKind.LEARNED_GUIDANCE_CHANGED.value,
    } <= set(report.change_kinds)
    assert payload["summary"]["version_dimensions_changed"] == [
        "source_revision",
        "amendment",
        "compiler_commit",
        "schema_version",
        "learned_guidance",
    ]


def test_amendment_impact_links_affected_obligations_citations_and_changes() -> None:
    impacts = build_legal_ir_amendment_impact_analysis(_before_snapshot(), _after_snapshot())

    assert len(impacts) == 1
    impact = impacts[0].to_dict()
    assert impact["amendment_id"] == "amd-7"
    assert {"obl-disclose", "obl-retain", "obl-publish"} <= set(
        impact["affected_obligation_ids"]
    )
    assert {"ORS 192.410", "ORS 192.420"} <= set(impact["affected_citations"])
    assert LegalIRSemanticChangeKind.OBLIGATION_REMOVED.value in impact["change_kinds"]
    assert LegalIRSemanticChangeKind.OBLIGATION_ADDED.value in impact["change_kinds"]


def test_codex_todos_emit_only_verified_compiler_impact_regressions() -> None:
    report = compute_legal_ir_semantic_diff(_before_snapshot(), _after_snapshot())

    assert report.summary["verified_compiler_regression_count"] == 1
    assert len(report.codex_todos) == 1
    todo = report.codex_todos[0].to_dict()
    assert todo["schema_version"] == LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION
    assert todo["action"] == "repair_compiler_impact_regression"
    assert todo["target_component"] == "legal_ir.proof_router"
    assert todo["owned_paths"] == [
        "ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_router.py"
    ]
    assert todo["evidence"]["verified_compiler_impact"] is True
    assert todo["evidence"]["regression"] is True

    unverified_after = _after_snapshot()
    obligations = list(unverified_after["obligations"])  # type: ignore[index]
    disclose = dict(obligations[0])
    disclose["metadata"] = {}
    obligations[0] = disclose
    unverified_after["obligations"] = obligations

    unverified = compute_legal_ir_semantic_diff(_before_snapshot(), unverified_after)

    assert any(change.regression for change in unverified.changes)
    assert unverified.codex_todos == ()
    assert project_legal_ir_semantic_diff_to_codex_todos(unverified) == []


def test_dict_api_and_report_round_trip_are_deterministic() -> None:
    first = compute_legal_ir_semantic_diff(_before_snapshot(), _after_snapshot())
    second = compute_legal_ir_semantic_diff(_before_snapshot(), _after_snapshot())
    payload = legal_ir_semantic_diff(_before_snapshot(), _after_snapshot())
    loaded = LegalIRSemanticDiffReport.from_dict(payload)

    assert first.to_dict() == second.to_dict()
    assert payload == first.to_dict()
    assert loaded.to_dict() == first.to_dict()


def test_semantic_diff_schema_versions_are_registered_for_reuse() -> None:
    report = compute_legal_ir_semantic_diff(_before_snapshot(), _after_snapshot())
    todo = report.codex_todos[0].to_dict()

    assert LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION in known_legal_ir_schema_versions()
    assert LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION in known_legal_ir_schema_versions()
    assert validate_legal_ir_schema_compatibility(
        report.to_dict(),
        artifact_family=LegalIRArtifactFamily.COMPILER_OUTPUT,
    ).reusable
    assert validate_legal_ir_schema_compatibility(
        todo,
        artifact_family=LegalIRArtifactFamily.COMPILER_OUTPUT,
    ).reusable
