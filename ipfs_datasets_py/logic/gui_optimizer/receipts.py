"""Proposal and receipt closed wire models (VGO-001)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from .schema import (
    ACCESSIBILITY_RECEIPT_INTERFACE,
    ACCESSIBILITY_RECEIPT_SCHEMA,
    GUI_IMPROVEMENT_PROPOSAL_INTERFACE,
    GUI_IMPROVEMENT_PROPOSAL_SCHEMA,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE,
    GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    INTERACTION_RECEIPT_INTERFACE,
    INTERACTION_RECEIPT_SCHEMA,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_CONSTRAINT_RECEIPT_SCHEMA,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    VISUAL_REGRESSION_RECEIPT_SCHEMA,
    AnalysisClassification,
    ConstraintCheckStatus,
    EvidenceLevel,
    GuiOptimizerDecodeError,
    ProposalDecision,
    ProposalRouteKind,
    VerificationStatus,
    VisualDecision,
    decode_closed_record,
    decode_nested_record,
    field_value,
    nested_record_list,
    optional_digest,
    optional_identifier,
    optional_text,
    parse_enum,
    parse_enum_sequence,
    require_bool,
    require_digest,
    require_finite_number,
    require_identifier,
    require_int,
    require_interface,
    require_schema_version,
    require_text,
    store_attrs,
    unique_identifiers,
    unique_repo_paths,
    unique_texts,
)


class _Base:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def canonical_bytes(self) -> bytes:
        from .models import canonical_model_bytes

        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        from .models import canonical_model_json

        return canonical_model_json(self)


def _pct(value: Any, name: str) -> float | int:
    number = require_finite_number(value, name)
    if float(number) < 0 or float(number) > 100:
        raise GuiOptimizerDecodeError(f"{name} must be in the closed range 0..100")
    return number


class GuiImprovementProposal(_Base):
    INTERFACE = GUI_IMPROVEMENT_PROPOSAL_INTERFACE
    SCHEMA_VERSION = GUI_IMPROVEMENT_PROPOSAL_SCHEMA
    _FIELDS = frozenset(
        {
            "acceptance_criteria",
            "analysis_classification",
            "application_id",
            "context_pack_id",
            "decision",
            "expected_screenshot_ids",
            "expected_test_ids",
            "intended_component_ids",
            "intended_file_paths",
            "interface",
            "objective",
            "proposal_id",
            "route_kind",
            "schema_version",
            "screen_id",
            "state_effect_ids",
            "verification_status",
            "visual_effect_summary",
        }
    )
    __slots__ = (
        "proposal_id",
        "application_id",
        "screen_id",
        "objective",
        "intended_file_paths",
        "intended_component_ids",
        "acceptance_criteria",
        "expected_test_ids",
        "expected_screenshot_ids",
        "state_effect_ids",
        "visual_effect_summary",
        "route_kind",
        "context_pack_id",
        "decision",
        "analysis_classification",
        "verification_status",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        proposal_id: str,
        application_id: str,
        screen_id: str,
        objective: str,
        intended_file_paths: Any,
        intended_component_ids: Any,
        acceptance_criteria: Any,
        expected_test_ids: Any,
        expected_screenshot_ids: Any,
        state_effect_ids: Any,
        visual_effect_summary: str,
        route_kind: Any,
        context_pack_id: str,
        decision: Any,
        analysis_classification: Any,
        verification_status: Any,
        interface: str,
        schema_version: str,
    ) -> None:
        paths = unique_repo_paths(intended_file_paths, "intended_file_paths")
        if not paths:
            raise GuiOptimizerDecodeError("intended_file_paths must not be empty")
        components = unique_identifiers(intended_component_ids, "intended_component_ids")
        if not components:
            raise GuiOptimizerDecodeError("intended_component_ids must not be empty")
        criteria = unique_texts(acceptance_criteria, "acceptance_criteria")
        if not criteria:
            raise GuiOptimizerDecodeError("acceptance_criteria must not be empty")
        store_attrs(
            self,
            proposal_id=require_identifier(proposal_id, "proposal_id"),
            application_id=require_identifier(application_id, "application_id"),
            screen_id=require_identifier(screen_id, "screen_id"),
            objective=require_text(objective, "objective"),
            intended_file_paths=paths,
            intended_component_ids=components,
            acceptance_criteria=criteria,
            expected_test_ids=unique_identifiers(expected_test_ids, "expected_test_ids"),
            expected_screenshot_ids=unique_identifiers(
                expected_screenshot_ids, "expected_screenshot_ids"
            ),
            state_effect_ids=unique_identifiers(state_effect_ids, "state_effect_ids"),
            visual_effect_summary=optional_text(visual_effect_summary, "visual_effect_summary"),
            route_kind=parse_enum(route_kind, ProposalRouteKind, "route_kind"),
            context_pack_id=optional_identifier(context_pack_id, "context_pack_id"),
            decision=parse_enum(decision, ProposalDecision, "decision"),
            analysis_classification=parse_enum(
                analysis_classification, AnalysisClassification, "analysis_classification"
            ),
            verification_status=parse_enum(
                verification_status, VerificationStatus, "verification_status"
            ),
            interface=require_interface(interface, GUI_IMPROVEMENT_PROPOSAL_INTERFACE),
            schema_version=require_schema_version(
                schema_version, GUI_IMPROVEMENT_PROPOSAL_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "context_pack_id": self.context_pack_id,
            "decision": self.decision.value,
            "expected_screenshot_ids": list(self.expected_screenshot_ids),
            "expected_test_ids": list(self.expected_test_ids),
            "intended_component_ids": list(self.intended_component_ids),
            "intended_file_paths": list(self.intended_file_paths),
            "interface": self.interface,
            "objective": self.objective,
            "proposal_id": self.proposal_id,
            "route_kind": self.route_kind.value,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "state_effect_ids": list(self.state_effect_ids),
            "verification_status": self.verification_status.value,
            "visual_effect_summary": self.visual_effect_summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiImprovementProposal:
        return decode_closed_record(
            cls,
            value,
            record_name="GuiImprovementProposal",
            builder=lambda p: cls(
                proposal_id=field_value(p, "proposal_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                objective=field_value(p, "objective", ""),
                intended_file_paths=field_value(p, "intended_file_paths", []),
                intended_component_ids=field_value(p, "intended_component_ids", []),
                acceptance_criteria=field_value(p, "acceptance_criteria", []),
                expected_test_ids=field_value(p, "expected_test_ids", []),
                expected_screenshot_ids=field_value(p, "expected_screenshot_ids", []),
                state_effect_ids=field_value(p, "state_effect_ids", []),
                visual_effect_summary=field_value(p, "visual_effect_summary", ""),
                route_kind=field_value(p, "route_kind", ""),
                context_pack_id=field_value(p, "context_pack_id", ""),
                decision=field_value(p, "decision", "pending"),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class VisualRegressionReceipt(_Base):
    INTERFACE = VISUAL_REGRESSION_RECEIPT_INTERFACE
    SCHEMA_VERSION = VISUAL_REGRESSION_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "analysis_classification",
            "application_id",
            "baseline_digest",
            "browser",
            "browser_version",
            "color_scheme",
            "component_version_ids",
            "decision",
            "evidence_level",
            "expected_change_regions",
            "extra_control_count",
            "forbidden_change_regions",
            "interface",
            "locale",
            "manual_review_threshold_percent",
            "max_unexplained_diff_percent",
            "missing_control_count",
            "pixel_diff_percent",
            "receipt_id",
            "repository_revision",
            "requires_human_review",
            "scenario_id",
            "schema_version",
            "screen_id",
            "screenshot_digest",
            "screenshot_height",
            "screenshot_width",
            "structural_diff_percent",
            "text_scale_percent",
            "unexpected_layout_shift_count",
            "verification_status",
            "viewport",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        from .models import ViewportSpec, VisualChangeRegion

        decision = parse_enum(kwargs["decision"], VisualDecision, "decision")
        requires_review = require_bool(
            kwargs["requires_human_review"], "requires_human_review"
        )
        browser = optional_text(kwargs.get("browser", ""), "browser")
        browser_version = optional_text(
            kwargs.get("browser_version", ""), "browser_version"
        )
        if not browser or not browser_version:
            raise GuiOptimizerDecodeError("browser and browser_version must be nonempty")
        pixel = _pct(kwargs["pixel_diff_percent"], "pixel_diff_percent")
        structural = _pct(kwargs["structural_diff_percent"], "structural_diff_percent")
        max_unexplained = _pct(
            kwargs["max_unexplained_diff_percent"], "max_unexplained_diff_percent"
        )
        manual_threshold = _pct(
            kwargs["manual_review_threshold_percent"],
            "manual_review_threshold_percent",
        )
        if decision is VisualDecision.PASS and requires_review:
            raise GuiOptimizerDecodeError("PASS visual receipt cannot require human review")
        if decision is VisualDecision.REVIEW and not requires_review:
            raise GuiOptimizerDecodeError("REVIEW visual receipt requires human review")
        if decision is VisualDecision.PASS and float(pixel) > float(max_unexplained):
            raise GuiOptimizerDecodeError(
                "pixel_diff_percent exceeds max_unexplained_diff_percent but decision is pass"
            )
        if float(pixel) >= float(manual_threshold) and not requires_review:
            raise GuiOptimizerDecodeError(
                "pixel_diff_percent at/above manual_review_threshold_percent requires human review"
            )
        expected = nested_record_list(
            VisualChangeRegion,
            kwargs["expected_change_regions"],
            "expected_change_regions",
        )
        forbidden = nested_record_list(
            VisualChangeRegion,
            kwargs["forbidden_change_regions"],
            "forbidden_change_regions",
        )
        expected_ids = [item.region_id for item in expected]
        forbidden_ids = [item.region_id for item in forbidden]
        if len(expected_ids) != len(set(expected_ids)):
            raise GuiOptimizerDecodeError("expected_change_regions region_ids must be unique")
        if len(forbidden_ids) != len(set(forbidden_ids)):
            raise GuiOptimizerDecodeError("forbidden_change_regions region_ids must be unique")
        overlap_ids = sorted(set(expected_ids) & set(forbidden_ids))
        if overlap_ids:
            raise GuiOptimizerDecodeError(
                "expected and forbidden region IDs must be disjoint"
            )
        for left in expected:
            for right in forbidden:
                if left.overlaps(right):
                    raise GuiOptimizerDecodeError(
                        "expected and forbidden regions geometrically overlap"
                    )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            scenario_id=require_identifier(kwargs["scenario_id"], "scenario_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            component_version_ids=unique_identifiers(
                kwargs["component_version_ids"], "component_version_ids"
            ),
            viewport=decode_nested_record(ViewportSpec, kwargs["viewport"], "viewport"),
            screenshot_digest=require_digest(kwargs["screenshot_digest"], "screenshot_digest"),
            baseline_digest=require_digest(kwargs["baseline_digest"], "baseline_digest"),
            decision=decision,
            evidence_level=parse_enum(kwargs["evidence_level"], EvidenceLevel, "evidence_level"),
            pixel_diff_percent=pixel,
            structural_diff_percent=structural,
            unexpected_layout_shift_count=require_int(
                kwargs["unexpected_layout_shift_count"],
                "unexpected_layout_shift_count",
                minimum=0,
            ),
            missing_control_count=require_int(
                kwargs["missing_control_count"], "missing_control_count", minimum=0
            ),
            extra_control_count=require_int(
                kwargs["extra_control_count"], "extra_control_count", minimum=0
            ),
            screenshot_width=require_int(
                kwargs["screenshot_width"], "screenshot_width", minimum=1
            ),
            screenshot_height=require_int(
                kwargs["screenshot_height"], "screenshot_height", minimum=1
            ),
            expected_change_regions=expected,
            forbidden_change_regions=forbidden,
            max_unexplained_diff_percent=max_unexplained,
            manual_review_threshold_percent=manual_threshold,
            requires_human_review=requires_review,
            color_scheme=require_text(kwargs["color_scheme"], "color_scheme"),
            locale=require_text(kwargs["locale"], "locale"),
            text_scale_percent=require_int(
                kwargs["text_scale_percent"], "text_scale_percent", minimum=25, maximum=500
            ),
            browser=browser,
            browser_version=browser_version,
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(
                kwargs["interface"], VISUAL_REGRESSION_RECEIPT_INTERFACE
            ),
            schema_version=require_schema_version(
                kwargs["schema_version"], VISUAL_REGRESSION_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "baseline_digest": self.baseline_digest,
            "browser": self.browser,
            "browser_version": self.browser_version,
            "color_scheme": self.color_scheme,
            "component_version_ids": list(self.component_version_ids),
            "decision": self.decision.value,
            "evidence_level": self.evidence_level.value,
            "expected_change_regions": [i.to_dict() for i in self.expected_change_regions],
            "extra_control_count": self.extra_control_count,
            "forbidden_change_regions": [i.to_dict() for i in self.forbidden_change_regions],
            "interface": self.interface,
            "locale": self.locale,
            "manual_review_threshold_percent": self.manual_review_threshold_percent,
            "max_unexplained_diff_percent": self.max_unexplained_diff_percent,
            "missing_control_count": self.missing_control_count,
            "pixel_diff_percent": self.pixel_diff_percent,
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "requires_human_review": self.requires_human_review,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screenshot_digest": self.screenshot_digest,
            "screenshot_height": self.screenshot_height,
            "screenshot_width": self.screenshot_width,
            "structural_diff_percent": self.structural_diff_percent,
            "text_scale_percent": self.text_scale_percent,
            "unexpected_layout_shift_count": self.unexpected_layout_shift_count,
            "verification_status": self.verification_status.value,
            "viewport": self.viewport.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> VisualRegressionReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="VisualRegressionReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                scenario_id=field_value(p, "scenario_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                component_version_ids=field_value(p, "component_version_ids", []),
                viewport=field_value(p, "viewport", {}),
                screenshot_digest=field_value(p, "screenshot_digest", ""),
                baseline_digest=field_value(p, "baseline_digest", ""),
                decision=field_value(p, "decision", ""),
                evidence_level=field_value(p, "evidence_level", ""),
                pixel_diff_percent=field_value(p, "pixel_diff_percent", 0.0),
                structural_diff_percent=field_value(p, "structural_diff_percent", 0.0),
                unexpected_layout_shift_count=field_value(
                    p, "unexpected_layout_shift_count", 0
                ),
                missing_control_count=field_value(p, "missing_control_count", 0),
                extra_control_count=field_value(p, "extra_control_count", 0),
                screenshot_width=field_value(p, "screenshot_width", 0),
                screenshot_height=field_value(p, "screenshot_height", 0),
                expected_change_regions=field_value(p, "expected_change_regions", []),
                forbidden_change_regions=field_value(p, "forbidden_change_regions", []),
                max_unexplained_diff_percent=field_value(
                    p, "max_unexplained_diff_percent", 100.0
                ),
                manual_review_threshold_percent=field_value(
                    p, "manual_review_threshold_percent", 100.0
                ),
                requires_human_review=field_value(p, "requires_human_review", False),
                color_scheme=field_value(p, "color_scheme", "light"),
                locale=field_value(p, "locale", "en-US"),
                text_scale_percent=field_value(p, "text_scale_percent", 100),
                browser=field_value(p, "browser", ""),
                browser_version=field_value(p, "browser_version", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class AccessibilityReceipt(_Base):
    INTERFACE = ACCESSIBILITY_RECEIPT_INTERFACE
    SCHEMA_VERSION = ACCESSIBILITY_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "analysis_classification",
            "application_id",
            "automated_pass_count",
            "evidence_level",
            "interface",
            "keyboard_result",
            "manual_check_ids",
            "receipt_id",
            "repository_revision",
            "scenario_id",
            "schema_version",
            "screen_id",
            "screen_reader_reviewed",
            "unsupported_criteria",
            "verification_status",
            "violation_count",
            "violation_ids",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        violation_ids = unique_identifiers(kwargs["violation_ids"], "violation_ids")
        violation_count = require_int(kwargs["violation_count"], "violation_count", minimum=0)
        if violation_count != len(violation_ids):
            raise GuiOptimizerDecodeError(
                "violation_count must equal len(violation_ids)"
            )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            scenario_id=require_identifier(kwargs["scenario_id"], "scenario_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            automated_pass_count=require_int(
                kwargs["automated_pass_count"], "automated_pass_count", minimum=0
            ),
            violation_count=violation_count,
            violation_ids=violation_ids,
            manual_check_ids=unique_identifiers(
                kwargs["manual_check_ids"], "manual_check_ids"
            ),
            unsupported_criteria=unique_texts(
                kwargs["unsupported_criteria"], "unsupported_criteria"
            ),
            keyboard_result=parse_enum(
                kwargs["keyboard_result"], ConstraintCheckStatus, "keyboard_result"
            ),
            screen_reader_reviewed=require_bool(
                kwargs["screen_reader_reviewed"], "screen_reader_reviewed"
            ),
            evidence_level=parse_enum(
                kwargs["evidence_level"], EvidenceLevel, "evidence_level"
            ),
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], ACCESSIBILITY_RECEIPT_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], ACCESSIBILITY_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "automated_pass_count": self.automated_pass_count,
            "evidence_level": self.evidence_level.value,
            "interface": self.interface,
            "keyboard_result": self.keyboard_result.value,
            "manual_check_ids": list(self.manual_check_ids),
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screen_reader_reviewed": self.screen_reader_reviewed,
            "unsupported_criteria": list(self.unsupported_criteria),
            "verification_status": self.verification_status.value,
            "violation_count": self.violation_count,
            "violation_ids": list(self.violation_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> AccessibilityReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="AccessibilityReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                scenario_id=field_value(p, "scenario_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                automated_pass_count=field_value(p, "automated_pass_count", 0),
                violation_count=field_value(p, "violation_count", 0),
                violation_ids=field_value(p, "violation_ids", []),
                manual_check_ids=field_value(p, "manual_check_ids", []),
                unsupported_criteria=field_value(p, "unsupported_criteria", []),
                keyboard_result=field_value(p, "keyboard_result", ""),
                screen_reader_reviewed=field_value(p, "screen_reader_reviewed", False),
                evidence_level=field_value(p, "evidence_level", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class InteractionReceipt(_Base):
    INTERFACE = INTERACTION_RECEIPT_INTERFACE
    SCHEMA_VERSION = INTERACTION_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "action_invocation_ids",
            "analysis_classification",
            "application_id",
            "confirmation_id",
            "event_ids",
            "evidence_level",
            "focus_sequence",
            "interface",
            "receipt_id",
            "recovery_ids",
            "repository_revision",
            "scenario_id",
            "schema_version",
            "screen_id",
            "step_ids",
            "unresolved_observation_ids",
            "verification_status",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            scenario_id=require_identifier(kwargs["scenario_id"], "scenario_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            step_ids=unique_identifiers(kwargs["step_ids"], "step_ids"),
            focus_sequence=unique_texts(kwargs["focus_sequence"], "focus_sequence"),
            event_ids=unique_identifiers(kwargs["event_ids"], "event_ids"),
            action_invocation_ids=unique_identifiers(
                kwargs["action_invocation_ids"], "action_invocation_ids"
            ),
            confirmation_id=optional_identifier(
                kwargs.get("confirmation_id", ""), "confirmation_id"
            ),
            recovery_ids=unique_identifiers(kwargs["recovery_ids"], "recovery_ids"),
            unresolved_observation_ids=unique_identifiers(
                kwargs["unresolved_observation_ids"], "unresolved_observation_ids"
            ),
            evidence_level=parse_enum(
                kwargs["evidence_level"], EvidenceLevel, "evidence_level"
            ),
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], INTERACTION_RECEIPT_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], INTERACTION_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_invocation_ids": list(self.action_invocation_ids),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "confirmation_id": self.confirmation_id,
            "event_ids": list(self.event_ids),
            "evidence_level": self.evidence_level.value,
            "focus_sequence": list(self.focus_sequence),
            "interface": self.interface,
            "receipt_id": self.receipt_id,
            "recovery_ids": list(self.recovery_ids),
            "repository_revision": self.repository_revision,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "step_ids": list(self.step_ids),
            "unresolved_observation_ids": list(self.unresolved_observation_ids),
            "verification_status": self.verification_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> InteractionReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="InteractionReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                scenario_id=field_value(p, "scenario_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                step_ids=field_value(p, "step_ids", []),
                focus_sequence=field_value(p, "focus_sequence", []),
                event_ids=field_value(p, "event_ids", []),
                action_invocation_ids=field_value(p, "action_invocation_ids", []),
                confirmation_id=field_value(p, "confirmation_id", ""),
                recovery_ids=field_value(p, "recovery_ids", []),
                unresolved_observation_ids=field_value(
                    p, "unresolved_observation_ids", []
                ),
                evidence_level=field_value(p, "evidence_level", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiConstraintReceipt(_Base):
    INTERFACE = UI_CONSTRAINT_RECEIPT_INTERFACE
    SCHEMA_VERSION = UI_CONSTRAINT_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "analysis_classification",
            "application_id",
            "check_ids",
            "evidence_level",
            "interface",
            "receipt_id",
            "repository_revision",
            "schema_version",
            "screen_id",
            "solver_id",
            "statuses",
            "unsupported_check_ids",
            "verification_status",
            "violated_check_ids",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        check_ids = unique_identifiers(kwargs["check_ids"], "check_ids")
        statuses = parse_enum_sequence(
            kwargs["statuses"], ConstraintCheckStatus, "statuses"
        )
        if len(check_ids) != len(statuses):
            raise GuiOptimizerDecodeError("check_ids and statuses lengths must agree")
        expected_violated = tuple(
            check_id
            for check_id, status in zip(check_ids, statuses, strict=True)
            if status is ConstraintCheckStatus.VIOLATED
        )
        expected_unsupported = tuple(
            check_id
            for check_id, status in zip(check_ids, statuses, strict=True)
            if status is ConstraintCheckStatus.UNSUPPORTED
        )
        violated = unique_identifiers(kwargs["violated_check_ids"], "violated_check_ids")
        unsupported = unique_identifiers(
            kwargs["unsupported_check_ids"], "unsupported_check_ids"
        )
        if violated != expected_violated:
            raise GuiOptimizerDecodeError(
                "violated_check_ids must exactly match statuses"
            )
        if unsupported != expected_unsupported:
            raise GuiOptimizerDecodeError(
                "unsupported_check_ids must exactly match statuses"
            )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            check_ids=check_ids,
            statuses=statuses,
            violated_check_ids=violated,
            unsupported_check_ids=unsupported,
            solver_id=optional_identifier(kwargs.get("solver_id", ""), "solver_id"),
            evidence_level=parse_enum(
                kwargs["evidence_level"], EvidenceLevel, "evidence_level"
            ),
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], UI_CONSTRAINT_RECEIPT_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], UI_CONSTRAINT_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "check_ids": list(self.check_ids),
            "evidence_level": self.evidence_level.value,
            "interface": self.interface,
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "solver_id": self.solver_id,
            "statuses": [item.value for item in self.statuses],
            "unsupported_check_ids": list(self.unsupported_check_ids),
            "verification_status": self.verification_status.value,
            "violated_check_ids": list(self.violated_check_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConstraintReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="UiConstraintReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                check_ids=field_value(p, "check_ids", []),
                statuses=field_value(p, "statuses", []),
                violated_check_ids=field_value(p, "violated_check_ids", []),
                unsupported_check_ids=field_value(p, "unsupported_check_ids", []),
                solver_id=field_value(p, "solver_id", ""),
                evidence_level=field_value(p, "evidence_level", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class GuiImprovementReceipt(_Base):
    INTERFACE = GUI_IMPROVEMENT_RECEIPT_INTERFACE
    SCHEMA_VERSION = GUI_IMPROVEMENT_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "accessibility_receipt_ids",
            "analysis_classification",
            "application_id",
            "constraint_receipt_ids",
            "context_pack_id",
            "decision",
            "interaction_receipt_ids",
            "interface",
            "invalidation_plan_id",
            "patch_digest",
            "proposal_id",
            "receipt_id",
            "rejection_reasons",
            "repository_revision",
            "schema_version",
            "screen_id",
            "verification_status",
            "visual_receipt_ids",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        decision = parse_enum(kwargs["decision"], ProposalDecision, "decision")
        verification = parse_enum(
            kwargs["verification_status"], VerificationStatus, "verification_status"
        )
        invalidation_plan_id = optional_identifier(
            kwargs.get("invalidation_plan_id", ""), "invalidation_plan_id"
        )
        context_pack_id = optional_identifier(
            kwargs.get("context_pack_id", ""), "context_pack_id"
        )
        patch_digest = optional_digest(kwargs.get("patch_digest", ""), "patch_digest")
        visual = unique_identifiers(kwargs["visual_receipt_ids"], "visual_receipt_ids")
        a11y = unique_identifiers(
            kwargs["accessibility_receipt_ids"], "accessibility_receipt_ids"
        )
        interaction = unique_identifiers(
            kwargs["interaction_receipt_ids"], "interaction_receipt_ids"
        )
        constraint = unique_identifiers(
            kwargs["constraint_receipt_ids"], "constraint_receipt_ids"
        )
        reasons = unique_texts(kwargs["rejection_reasons"], "rejection_reasons")
        if decision is ProposalDecision.ACCEPT:
            if verification not in (
                VerificationStatus.VERIFIED,
                VerificationStatus.INTEGRITY_VALID,
            ):
                raise GuiOptimizerDecodeError(
                    "accepted receipt requires verified or integrity_valid status"
                )
            if not invalidation_plan_id or not context_pack_id or not patch_digest:
                raise GuiOptimizerDecodeError(
                    "accepted receipt requires nonempty invalidation_plan_id, "
                    "context_pack_id, and patch_digest"
                )
            if not visual or not a11y or not interaction or not constraint:
                raise GuiOptimizerDecodeError(
                    "accepted receipt requires nonempty evidence receipt lists"
                )
            if reasons:
                raise GuiOptimizerDecodeError(
                    "accepted receipt cannot carry rejection reasons"
                )
        if decision is ProposalDecision.REJECT and not reasons:
            raise GuiOptimizerDecodeError(
                "rejected receipt requires nonempty rejection reasons"
            )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            proposal_id=require_identifier(kwargs["proposal_id"], "proposal_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            decision=decision,
            visual_receipt_ids=visual,
            accessibility_receipt_ids=a11y,
            interaction_receipt_ids=interaction,
            constraint_receipt_ids=constraint,
            invalidation_plan_id=invalidation_plan_id,
            context_pack_id=context_pack_id,
            patch_digest=patch_digest,
            rejection_reasons=reasons,
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=verification,
            interface=require_interface(
                kwargs["interface"], GUI_IMPROVEMENT_RECEIPT_INTERFACE
            ),
            schema_version=require_schema_version(
                kwargs["schema_version"], GUI_IMPROVEMENT_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_receipt_ids": list(self.accessibility_receipt_ids),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "constraint_receipt_ids": list(self.constraint_receipt_ids),
            "context_pack_id": self.context_pack_id,
            "decision": self.decision.value,
            "interaction_receipt_ids": list(self.interaction_receipt_ids),
            "interface": self.interface,
            "invalidation_plan_id": self.invalidation_plan_id,
            "patch_digest": self.patch_digest,
            "proposal_id": self.proposal_id,
            "receipt_id": self.receipt_id,
            "rejection_reasons": list(self.rejection_reasons),
            "repository_revision": self.repository_revision,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "verification_status": self.verification_status.value,
            "visual_receipt_ids": list(self.visual_receipt_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiImprovementReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="GuiImprovementReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                proposal_id=field_value(p, "proposal_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                decision=field_value(p, "decision", ""),
                visual_receipt_ids=field_value(p, "visual_receipt_ids", []),
                accessibility_receipt_ids=field_value(
                    p, "accessibility_receipt_ids", []
                ),
                interaction_receipt_ids=field_value(p, "interaction_receipt_ids", []),
                constraint_receipt_ids=field_value(p, "constraint_receipt_ids", []),
                invalidation_plan_id=field_value(p, "invalidation_plan_id", ""),
                context_pack_id=field_value(p, "context_pack_id", ""),
                patch_digest=field_value(p, "patch_digest", ""),
                rejection_reasons=field_value(p, "rejection_reasons", []),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


__all__ = [
    "GuiImprovementProposal",
    "VisualRegressionReceipt",
    "AccessibilityReceipt",
    "InteractionReceipt",
    "UiConstraintReceipt",
    "GuiImprovementReceipt",
]
