"""Tests for first-class LegalIR ambiguity values."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_AMBIGUITY_SCHEMA_VERSION,
    LegalIRAmbiguity,
    LegalIRAmbiguityBuilder,
    LegalIRAmbiguityDiagnosticType,
    LegalIRAmbiguityImpact,
    LegalIRAmbiguityKind,
    LegalIRAmbiguityRoute,
    LegalIRAmbiguitySourceSpan,
    LegalIRAmbiguityStatus,
    LegalIRAmbiguityUse,
    LegalIRCompetingParse,
    assert_legal_ir_ambiguity_resolved,
    build_legal_ir_ambiguity_report,
    legal_ir_ambiguity_allowed_for_use,
    route_legal_ir_ambiguity,
    validate_legal_ir_ambiguities,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_uncertainty import (
    ROUTE_HAMMER_LEANSTRAL_AUDIT,
    route_learned_guidance_by_uncertainty,
)


def _span() -> LegalIRAmbiguitySourceSpan:
    return LegalIRAmbiguitySourceSpan(
        span_id="span:ambiguity:1",
        source_document_id="doc:ors-192",
        start_offset=14,
        end_offset=58,
        source_node_id="node:ambiguous-duty",
        citation="ORS 192.001",
        normalized_text_sha256="a" * 64,
    )


def test_competing_parses_are_typed_serializable_and_fail_closed() -> None:
    ambiguity = LegalIRAmbiguity(
        ambiguity_id="amb:deontic-scope",
        ambiguity_kind=LegalIRAmbiguityKind.COMPETING_PARSE,
        status=LegalIRAmbiguityStatus.COMPETING,
        confidence=0.64,
        impact=LegalIRAmbiguityImpact.HIGH,
        source_spans=(_span(),),
        competing_parses=(
            LegalIRCompetingParse(
                parse_id="parse:obligation",
                target_view="deontic.ir",
                parse_kind="deontic_operator",
                confidence=0.55,
                typed_payload={"operator": "O", "subject": "agency"},
                span_ids=("span:ambiguity:1",),
            ),
            LegalIRCompetingParse(
                parse_id="parse:permission",
                target_view="deontic.ir",
                parse_kind="deontic_operator",
                confidence=0.45,
                typed_payload={"operator": "P", "subject": "agency"},
                span_ids=("span:ambiguity:1",),
            ),
        ),
        learned_label="obligation",
    )

    report = validate_legal_ir_ambiguities(
        (ambiguity,),
        ambiguity_report_id="ambiguity-report-core",
    )
    rebuilt = build_legal_ir_ambiguity_report(report.to_dict())

    assert report.schema_version == LEGAL_IR_AMBIGUITY_SCHEMA_VERSION
    assert rebuilt.to_dict() == report.to_dict()
    assert not report.proof_safe
    assert not report.learned_target_safe
    assert report.audit_required
    assert report.route is LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
    assert {
        diagnostic.diagnostic_type for diagnostic in report.diagnostics
    } >= {
        LegalIRAmbiguityDiagnosticType.COMPETING_PARSE_WITHOUT_CHOICE,
        LegalIRAmbiguityDiagnosticType.HIGH_IMPACT_AMBIGUITY,
        LegalIRAmbiguityDiagnosticType.LEARNED_LABEL_COLLAPSE_BLOCKED,
    }
    assert not legal_ir_ambiguity_allowed_for_use(
        report,
        artifact_use=LegalIRAmbiguityUse.PROOF_TARGET,
    )
    assert not legal_ir_ambiguity_allowed_for_use(
        report,
        artifact_use=LegalIRAmbiguityUse.LEARNED_TARGET,
    )
    with pytest.raises(ValueError):
        assert_legal_ir_ambiguity_resolved(report)


def test_unsupported_interpretations_and_human_review_route_explicitly() -> None:
    builder = LegalIRAmbiguityBuilder(ambiguity_report_id="ambiguity-report-routes")
    builder.add_unsupported_interpretation(
        "amb:unsupported-temporal",
        {
            "parse_id": "parse:invented-temporal-rule",
            "target_view": "temporal",
            "supported": False,
            "support_reason": "No authority version supports the sunset inference.",
            "typed_payload": {"label": "auto_sunset_exception"},
        },
        confidence=0.41,
        impact=LegalIRAmbiguityImpact.HIGH,
        source_spans=(_span(),),
        law_version_ids=("law:ors-192-001-v2",),
    )
    builder.add_ambiguity(
        "amb:operator-review",
        LegalIRAmbiguityKind.REQUIRED_HUMAN_REVIEW,
        status=LegalIRAmbiguityStatus.REVIEW_REQUIRED,
        confidence=0.73,
        impact=LegalIRAmbiguityImpact.MEDIUM,
        source_spans=(_span(),),
        human_review_required=True,
        human_review_reason="Agency discretion term is undefined in the source.",
    )
    report = builder.to_report()
    routed = route_legal_ir_ambiguity(report)

    assert routed["audit_count"] == 1
    assert routed["audit_ambiguities"][0]["ambiguity_id"] == "amb:unsupported-temporal"
    assert routed["operator_diagnostic_count"] == 1
    assert routed["operator_diagnostics"][0]["ambiguity_id"] == "amb:operator-review"
    assert {
        diagnostic.diagnostic_type for diagnostic in report.diagnostics
    } >= {
        LegalIRAmbiguityDiagnosticType.UNSUPPORTED_INTERPRETATION_PRESENT,
        LegalIRAmbiguityDiagnosticType.HUMAN_REVIEW_REQUIRED,
    }


def test_resolved_ambiguity_requires_selected_parse_and_source_span() -> None:
    report = validate_legal_ir_ambiguities(
        (
            LegalIRAmbiguity(
                ambiguity_id="amb:resolved",
                ambiguity_kind=LegalIRAmbiguityKind.COMPETING_PARSE,
                status=LegalIRAmbiguityStatus.RESOLVED,
                confidence=0.92,
                impact=LegalIRAmbiguityImpact.LOW,
                source_spans=(_span(),),
                competing_parses=(
                    LegalIRCompetingParse(
                        parse_id="parse:selected",
                        target_view="deontic.ir",
                        confidence=0.92,
                        span_ids=("span:ambiguity:1",),
                    ),
                    LegalIRCompetingParse(
                        parse_id="parse:rejected",
                        target_view="deontic.ir",
                        confidence=0.08,
                        span_ids=("span:ambiguity:1",),
                    ),
                ),
                selected_parse_id="parse:selected",
            ),
        )
    )

    assert report.proof_safe
    assert report.learned_target_safe
    assert assert_legal_ir_ambiguity_resolved(report) is not None


def test_uncertainty_gate_routes_ambiguity_to_audit_not_learned_label() -> None:
    routed = route_learned_guidance_by_uncertainty(
        {
            "ambiguities": [
                {
                    "ambiguity_id": "amb:learned-collapse",
                    "ambiguity_kind": "competing_parse",
                    "confidence": 0.81,
                    "learned_label": "agency_obligation",
                    "competing_parses": [
                        {"parse_id": "parse:o", "target_view": "deontic.ir"},
                        {"parse_id": "parse:p", "target_view": "deontic.ir"},
                    ],
                }
            ]
        }
    )

    assert routed["codex_guidance_items"] == []
    assert routed["audit_guidance_items"][0]["ambiguity_id"] == "amb:learned-collapse"
    assert (
        routed["audit_guidance_items"][0]["uncertainty_route"]
        == ROUTE_HAMMER_LEANSTRAL_AUDIT
    )
    assert routed["report"]["audit_guidance_ids"] == ["amb:learned-collapse"]
