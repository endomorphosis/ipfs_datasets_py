"""UIR-040: capability negotiation, projection solving, and loss receipts."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.projection.capabilities import (
    BudgetKind,
    CapabilityRequirement,
    NegotiationStatus,
    ProfileBudget,
    ProfileFamily,
    REQUIRED_BUDGET_KINDS,
    UIDeviceProfile,
    UI_DEVICE_PROFILE_INTERFACE,
    default_profile_catalogue,
    desktop_profile,
    glasses_profile,
    headless_profile,
    mobile_profile,
    negotiate_capabilities,
    validate_device_profile,
    voice_profile,
)
from ipfs_datasets_py.logic.ui_ux_ir.projection.loss import (
    LossCategory,
    MandatorySemanticKind,
    MANDATORY_SEMANTIC_KINDS,
    assert_no_silent_mandatory_omission,
    build_loss_report,
    make_loss,
)
from ipfs_datasets_py.logic.ui_ux_ir.projection.solver import (
    PresentationDisposition,
    ProjectionItem,
    ProjectionPolicy,
    ProjectionProblem,
    ProjectionStatus,
    UIProjectionSolver,
    UI_PROJECTION_ARTIFACT_INTERFACE,
    UI_PROJECTION_SOLVER_INTERFACE,
    project_ui_ir,
    solve_projection,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import AdaptationPolicy, UIIRValidationError


def _consent_confirm_error_problem() -> ProjectionProblem:
    """Canonical problem with mandatory action/consent/error/confirmation/feedback/a11y."""

    return ProjectionProblem(
        problem_id="problem:consent-flow",
        document_id="doc:consent-flow",
        items=(
            ProjectionItem(
                item_id="action_submit",
                semantic_kind=MandatorySemanticKind.ACTION.value,
                mandatory=True,
                required_capability_ids=("display",),
                alternative_capability_ids=("spatial_display",),
                fallback_capability_ids=("audio", "speech_output"),
                fallback_ref="fallback:audio:submit",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=1,
                text_chars=24,
                attention_cost=5,
                field_of_view_share=8,
                safe_area_share=5,
                priority=10,
                label="Submit",
            ),
            ProjectionItem(
                item_id="consent_privacy",
                semantic_kind=MandatorySemanticKind.CONSENT.value,
                mandatory=True,
                required_capability_ids=("display",),
                fallback_capability_ids=("audio", "speech_output"),
                fallback_ref="fallback:audio:consent",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=1,
                text_chars=80,
                attention_cost=8,
                field_of_view_share=12,
                safe_area_share=8,
                priority=5,
                label="Consent to processing",
            ),
            ProjectionItem(
                item_id="consequence_irrevocable",
                semantic_kind=MandatorySemanticKind.CONSEQUENCE.value,
                mandatory=True,
                required_capability_ids=("display",),
                fallback_capability_ids=("audio",),
                fallback_ref="fallback:audio:consequence",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=60,
                attention_cost=6,
                field_of_view_share=8,
                priority=6,
            ),
            ProjectionItem(
                item_id="error_surface",
                semantic_kind=MandatorySemanticKind.ERROR.value,
                mandatory=True,
                required_capability_ids=("display",),
                alternative_capability_ids=("audio", "haptic"),
                fallback_capability_ids=("notification",),
                fallback_ref="fallback:notification:error",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=40,
                attention_cost=4,
                field_of_view_share=6,
                priority=8,
            ),
            ProjectionItem(
                item_id="confirm_delete",
                semantic_kind=MandatorySemanticKind.CONFIRMATION.value,
                mandatory=True,
                required_capability_ids=("display",),
                fallback_capability_ids=("audio", "speech_output"),
                fallback_ref="fallback:audio:confirm",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=1,
                text_chars=48,
                attention_cost=7,
                field_of_view_share=10,
                priority=7,
            ),
            ProjectionItem(
                item_id="feedback_live",
                semantic_kind=MandatorySemanticKind.FEEDBACK.value,
                mandatory=True,
                required_capability_ids=("display",),
                alternative_capability_ids=("audio", "haptic"),
                fallback_capability_ids=("notification",),
                fallback_ref="fallback:notification:feedback",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=30,
                attention_cost=3,
                field_of_view_share=4,
                priority=15,
            ),
            ProjectionItem(
                item_id="a11y_name",
                semantic_kind=MandatorySemanticKind.ACCESSIBILITY.value,
                mandatory=True,
                required_capability_ids=("display",),
                alternative_capability_ids=("audio", "speech_output"),
                fallback_capability_ids=("agent_structured",),
                fallback_ref="fallback:a11y:name",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=20,
                attention_cost=2,
                field_of_view_share=2,
                priority=1,
            ),
            ProjectionItem(
                item_id="decor_banner",
                semantic_kind="decorative",
                mandatory=False,
                required_capability_ids=("display",),
                adaptation_policy=AdaptationPolicy.OMIT,
                action_cost=0,
                text_chars=200,
                attention_cost=10,
                field_of_view_share=20,
                priority=300,
            ),
        ),
        capability_requirements=(
            CapabilityRequirement(
                requirement_id="req_output_primary",
                capability_ids=("display",),
                essential=True,
                alternative_capability_ids=("spatial_display",),
                fallback_capability_ids=("audio", "speech_output"),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Capabilities / profiles
# ---------------------------------------------------------------------------


def test_profiles_are_capability_based_not_brands() -> None:
    catalogue = default_profile_catalogue()
    families = {profile.family for profile in catalogue}
    assert ProfileFamily.DESKTOP in families
    assert ProfileFamily.MOBILE in families
    assert ProfileFamily.GLASSES in families
    assert ProfileFamily.VOICE in families
    assert ProfileFamily.HEADLESS in families
    for profile in catalogue:
        payload = profile.to_dict()
        assert payload["interface"] == UI_DEVICE_PROFILE_INTERFACE
        assert "brand" not in payload
        assert "vendor" not in payload
        budget_kinds = {b["kind"] for b in payload["budgets"]}
        assert REQUIRED_BUDGET_KINDS <= budget_kinds


def test_device_profile_rejects_unknown_capability() -> None:
    with pytest.raises(UIIRValidationError):
        validate_device_profile(
            UIDeviceProfile(
                profile_id="profile:bad",
                family=ProfileFamily.CUSTOM,
                input_capability_ids=("raw_emg_stream",),
                output_capability_ids=("display",),
            )
        )


def test_negotiation_satisfied_on_desktop() -> None:
    profile = desktop_profile()
    result = negotiate_capabilities(
        profile,
        (
            CapabilityRequirement(
                requirement_id="r1",
                capability_ids=("display",),
                essential=True,
            ),
            CapabilityRequirement(
                requirement_id="r2",
                capability_ids=("keyboard",),
                essential=True,
                direction="input",
            ),
        ),
    )
    assert result.status is NegotiationStatus.SATISFIED
    assert result.unsatisfiable_requirement_ids == ()
    assert "display" in result.used_capability_ids


def test_negotiation_fallback_when_primary_missing() -> None:
    profile = voice_profile()
    result = negotiate_capabilities(
        profile,
        (
            CapabilityRequirement(
                requirement_id="r_display",
                capability_ids=("display",),
                essential=True,
                fallback_capability_ids=("audio", "speech_output"),
            ),
        ),
    )
    assert result.status is NegotiationStatus.FALLBACK
    assert result.fallback_requirement_ids == ("r_display",)
    assert result.unsatisfiable_requirement_ids == ()


def test_negotiation_unsatisfiable_essential_without_fallback() -> None:
    profile = headless_profile()
    result = negotiate_capabilities(
        profile,
        (
            CapabilityRequirement(
                requirement_id="r_spatial",
                capability_ids=("spatial_display",),
                essential=True,
            ),
        ),
    )
    assert result.status is NegotiationStatus.UNSATISFIABLE
    assert "r_spatial" in result.unsatisfiable_requirement_ids


# ---------------------------------------------------------------------------
# Loss receipts
# ---------------------------------------------------------------------------


def test_loss_receipt_forbids_silent_mandatory_omission() -> None:
    required = {
        "action_submit": MandatorySemanticKind.ACTION.value,
        "consent_privacy": MandatorySemanticKind.CONSENT.value,
    }
    with pytest.raises(UIIRValidationError, match="Silent omission"):
        assert_no_silent_mandatory_omission(
            required,
            losses=(),
            preserved_ids=(),
        )

    # Explicit unsatisfiable receipt is acceptable.
    losses = (
        make_loss(
            loss_id="loss:unsat:action_submit",
            semantic_id="action_submit",
            semantic_kind=MandatorySemanticKind.ACTION,
            category=LossCategory.UNSATISFIABLE,
            reason="no capability",
            mandatory=True,
        ),
        make_loss(
            loss_id="loss:unsat:consent_privacy",
            semantic_id="consent_privacy",
            semantic_kind=MandatorySemanticKind.CONSENT,
            category=LossCategory.UNSATISFIABLE,
            reason="no capability",
            mandatory=True,
        ),
    )
    assert_no_silent_mandatory_omission(required, losses, preserved_ids=())


def test_mandatory_kinds_closed_set() -> None:
    for kind in (
        "action",
        "consent",
        "consequence",
        "error",
        "confirmation",
        "feedback",
        "accessibility",
    ):
        assert kind in MANDATORY_SEMANTIC_KINDS


def test_loss_report_digest_is_deterministic() -> None:
    losses = (
        make_loss(
            loss_id="loss:b",
            semantic_id="s2",
            semantic_kind="decorative",
            category=LossCategory.OMITTED,
            reason="optional omit",
        ),
        make_loss(
            loss_id="loss:a",
            semantic_id="s1",
            semantic_kind=MandatorySemanticKind.FEEDBACK,
            category=LossCategory.FALLBACK,
            reason="fallback",
            fallback_ref="fb:1",
        ),
    )
    report_a = build_loss_report("report:1", losses)
    report_b = build_loss_report("report:1", tuple(reversed(losses)))
    assert report_a.digest() == report_b.digest()
    assert report_a.to_dict()["losses"][0]["loss_id"] == "loss:a"


# ---------------------------------------------------------------------------
# Solver: satisfied / deterministic
# ---------------------------------------------------------------------------


def test_desktop_projection_preserves_mandatory_semantics() -> None:
    problem = _consent_confirm_error_problem()
    artifact = solve_projection(problem, desktop_profile())
    assert artifact.interface == UI_PROJECTION_ARTIFACT_INTERFACE
    assert artifact.status is ProjectionStatus.SATISFIED
    by_id = {node.item_id: node for node in artifact.nodes}
    for item_id in (
        "action_submit",
        "consent_privacy",
        "consequence_irrevocable",
        "error_surface",
        "confirm_delete",
        "feedback_live",
        "a11y_name",
    ):
        assert by_id[item_id].disposition is PresentationDisposition.PRESERVED
        assert by_id[item_id].mandatory is True
    # No unsatisfiable losses.
    assert not artifact.loss_report.has_unsatisfiable
    # Budgets respected.
    for usage in artifact.budget_usage:
        assert usage.exceeded is False


def test_solver_is_deterministic() -> None:
    problem = _consent_confirm_error_problem()
    profile = glasses_profile()
    a = solve_projection(problem, profile)
    b = solve_projection(problem, profile)
    assert a.digest() == b.digest()
    assert a.to_dict() == b.to_dict()
    assert a.bounds.steps_used == b.bounds.steps_used


def test_ui_projection_solver_class_interface() -> None:
    solver = UIProjectionSolver()
    assert solver.interface == UI_PROJECTION_SOLVER_INTERFACE
    artifact = solver.solve(_consent_confirm_error_problem(), mobile_profile())
    assert artifact.status in {
        ProjectionStatus.SATISFIED,
        ProjectionStatus.DEGRADED,
        ProjectionStatus.FALLBACK,
    }


# ---------------------------------------------------------------------------
# Solver: glasses budgets force fallback / omit optional
# ---------------------------------------------------------------------------


def test_glasses_budgets_force_fallback_not_silent_omit() -> None:
    """Tight FOV/action/attention budgets must not silently drop mandatories."""

    problem = _consent_confirm_error_problem()
    artifact = solve_projection(problem, glasses_profile())
    assert artifact.status in {
        ProjectionStatus.FALLBACK,
        ProjectionStatus.DEGRADED,
        ProjectionStatus.UNSATISFIABLE,
    }

    mandatory_nodes = [n for n in artifact.nodes if n.mandatory]
    for node in mandatory_nodes:
        assert node.disposition is not PresentationDisposition.OMITTED
        assert node.disposition in {
            PresentationDisposition.PRESERVED,
            PresentationDisposition.ADAPTED,
            PresentationDisposition.SUMMARIZED,
            PresentationDisposition.FALLBACK,
            PresentationDisposition.UNSATISFIABLE,
        }

    # Decorative optional may be omitted with an explicit receipt.
    decor = next(n for n in artifact.nodes if n.item_id == "decor_banner")
    if decor.disposition is PresentationDisposition.OMITTED:
        omit_losses = [
            loss
            for loss in artifact.loss_report.losses
            if loss.semantic_id == "decor_banner"
        ]
        assert omit_losses
        assert omit_losses[0].category in {
            LossCategory.OMITTED,
            LossCategory.SUMMARIZED,
        }

    # Every mandatory semantic has preserve or explicit loss.
    required = {
        n.item_id: n.semantic_kind for n in artifact.nodes if n.mandatory
    }
    preserved = [
        n.item_id
        for n in artifact.nodes
        if n.disposition
        in {
            PresentationDisposition.PRESERVED,
            PresentationDisposition.ADAPTED,
            PresentationDisposition.SUMMARIZED,
            PresentationDisposition.FALLBACK,
        }
    ]
    assert_no_silent_mandatory_omission(
        required, artifact.loss_report.losses, preserved
    )


def test_budget_kinds_tracked_in_usage() -> None:
    artifact = solve_projection(_consent_confirm_error_problem(), glasses_profile())
    kinds = {usage.kind for usage in artifact.budget_usage}
    for kind in REQUIRED_BUDGET_KINDS:
        assert kind in kinds
    assert "memory" in kinds


# ---------------------------------------------------------------------------
# Solver: unsatisfiable core
# ---------------------------------------------------------------------------


def test_unsatisfiable_when_mandatory_has_no_capability_or_fallback() -> None:
    problem = ProjectionProblem(
        problem_id="problem:unsat-core",
        items=(
            ProjectionItem(
                item_id="action_gaze_only",
                semantic_kind=MandatorySemanticKind.ACTION.value,
                mandatory=True,
                required_capability_ids=("spatial_display",),
                # no alternative / fallback capabilities or refs with FALLBACK policy
                adaptation_policy=AdaptationPolicy.PRESERVE,
                action_cost=1,
                text_chars=10,
                field_of_view_share=5,
            ),
            ProjectionItem(
                item_id="error_surface",
                semantic_kind=MandatorySemanticKind.ERROR.value,
                mandatory=True,
                required_capability_ids=("display",),
                fallback_capability_ids=("notification",),
                fallback_ref="fallback:notification:error",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=20,
            ),
        ),
    )
    # Headless has neither spatial_display nor display.
    artifact = solve_projection(problem, headless_profile())
    assert artifact.status is ProjectionStatus.UNSATISFIABLE
    unsat = [
        loss
        for loss in artifact.loss_report.losses
        if loss.category is LossCategory.UNSATISFIABLE
    ]
    assert any(loss.semantic_id == "action_gaze_only" for loss in unsat)
    # Explicit result — never a silent success.
    assert artifact.to_dict()["status"] == "unsatisfiable"


def test_mandatory_item_rejects_omit_policy() -> None:
    with pytest.raises(UIIRValidationError, match="cannot declare"):
        ProjectionItem(
            item_id="bad",
            semantic_kind=MandatorySemanticKind.CONSENT.value,
            mandatory=True,
            adaptation_policy=AdaptationPolicy.OMIT,
        ).validate()


# ---------------------------------------------------------------------------
# Solver: voice / headless fallback paths
# ---------------------------------------------------------------------------


def test_voice_profile_uses_audio_fallback_for_display_actions() -> None:
    problem = _consent_confirm_error_problem()
    artifact = solve_projection(problem, voice_profile())
    assert artifact.status in {
        ProjectionStatus.FALLBACK,
        ProjectionStatus.DEGRADED,
        ProjectionStatus.UNSATISFIABLE,
    }
    # Consent must not disappear without receipt.
    consent = next(n for n in artifact.nodes if n.item_id == "consent_privacy")
    assert consent.disposition is not PresentationDisposition.OMITTED
    if consent.disposition is PresentationDisposition.FALLBACK:
        losses = [
            loss
            for loss in artifact.loss_report.losses
            if loss.semantic_id == "consent_privacy"
        ]
        assert losses
        assert losses[0].category is LossCategory.FALLBACK
        assert losses[0].fallback_ref


def test_project_ui_ir_from_document_mapping() -> None:
    document = {
        "document_id": "doc:mapped",
        "components": [
            {
                "component_id": "btn_ok",
                "role": "button",
                "purpose": "Confirm",
                "program_binding_ids": ["bind:ok"],
            },
            {
                "component_id": "lbl_hint",
                "role": "text",
                "purpose": "Optional hint",
            },
        ],
        "feedback_contracts": [
            {
                "feedback_id": "fb_status",
                "channel": "status",
                "component_id": "btn_ok",
            }
        ],
        "accessibility": [
            {
                "accessibility_id": "a11y_btn",
                "component_id": "btn_ok",
                "role": "button",
                "name_ref": "msg:ok",
            }
        ],
        "output_modality_requirements": [
            {
                "requirement_id": "out_display",
                "direction": "output",
                "capability_ids": ["display"],
                "essential": True,
            }
        ],
    }
    artifact = project_ui_ir(document, desktop_profile())
    assert artifact.document_id == "doc:mapped"
    assert artifact.status is ProjectionStatus.SATISFIED
    kinds = {node.semantic_kind for node in artifact.nodes}
    assert MandatorySemanticKind.ACTION.value in kinds
    assert MandatorySemanticKind.FEEDBACK.value in kinds
    assert MandatorySemanticKind.ACCESSIBILITY.value in kinds


def test_bounds_receipt_present() -> None:
    profile = desktop_profile()
    artifact = solve_projection(_consent_confirm_error_problem(), profile)
    assert artifact.bounds.max_solve_ms == profile.max_solve_ms
    assert artifact.bounds.max_solve_steps == profile.max_solve_steps
    assert artifact.bounds.max_memory_nodes == profile.max_memory_nodes
    assert artifact.bounds.steps_used >= 1
    assert artifact.bounds.elapsed_ms >= 0
    assert artifact.bounds.bound_exceeded is False


def test_extremely_tight_budget_yields_explicit_fallback_or_unsat() -> None:
    """Profile with action_count=0 cannot host mandatory actions silently."""

    tight = validate_device_profile(
        UIDeviceProfile(
            profile_id="profile:tight",
            family=ProfileFamily.CUSTOM,
            input_capability_ids=("keyboard",),
            output_capability_ids=("display", "audio", "fallback"),
            budgets=(
                ProfileBudget(kind=BudgetKind.ACTION_COUNT, limit=0),
                ProfileBudget(kind=BudgetKind.TEXT_DENSITY, limit=10, unit="chars"),
                ProfileBudget(kind=BudgetKind.UPDATE_RATE, limit=1, unit="hz"),
                ProfileBudget(kind=BudgetKind.LATENCY, limit=50, unit="ms"),
                ProfileBudget(kind=BudgetKind.ATTENTION, limit=1, unit="points"),
                ProfileBudget(kind=BudgetKind.FIELD_OF_VIEW, limit=5, unit="percent"),
                ProfileBudget(kind=BudgetKind.SAFE_AREA, limit=10, unit="percent"),
                ProfileBudget(kind=BudgetKind.MEMORY, limit=10, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.FALLBACK,
            max_solve_ms=100,
            max_solve_steps=5000,
            max_memory_nodes=50,
        )
    )
    problem = ProjectionProblem(
        problem_id="problem:tight",
        items=(
            ProjectionItem(
                item_id="action_only",
                semantic_kind=MandatorySemanticKind.ACTION.value,
                mandatory=True,
                required_capability_ids=("display",),
                fallback_capability_ids=("audio",),
                fallback_ref="fallback:audio:action",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=2,
                text_chars=40,
                attention_cost=10,
                field_of_view_share=20,
                priority=1,
            ),
        ),
    )
    artifact = solve_projection(problem, tight, ProjectionPolicy(policy_id="p:tight"))
    assert artifact.status in {
        ProjectionStatus.FALLBACK,
        ProjectionStatus.UNSATISFIABLE,
        ProjectionStatus.DEGRADED,
    }
    node = artifact.nodes[0]
    assert node.disposition is not PresentationDisposition.OMITTED
    assert node.disposition in {
        PresentationDisposition.FALLBACK,
        PresentationDisposition.UNSATISFIABLE,
        PresentationDisposition.SUMMARIZED,
        PresentationDisposition.ADAPTED,
        PresentationDisposition.PRESERVED,
    }
    # If still over hard action budget of 0 after fallback (cost may reduce to 1),
    # status should be unsatisfiable with explicit receipt.
    action_usage = next(u for u in artifact.budget_usage if u.kind == "action_count")
    if action_usage.exceeded:
        assert artifact.status is ProjectionStatus.UNSATISFIABLE or any(
            loss.category
            in {LossCategory.UNSATISFIABLE, LossCategory.BUDGET_EXCEEDED, LossCategory.FALLBACK}
            for loss in artifact.loss_report.losses
        )


def test_empty_problem_rejected() -> None:
    with pytest.raises(UIIRValidationError, match="must not be empty"):
        ProjectionProblem(problem_id="p:empty", items=()).validate()
