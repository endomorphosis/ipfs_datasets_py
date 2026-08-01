"""Closed UI/UX IR v1 envelope and JSON Schema regression tests (UIR-010)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import jsonschema
import pytest

from ipfs_datasets_py.logic.ir_core.canonical import CollectionSemantics
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    UI_UX_IR_COLLECTION_SCHEMA,
    UI_UX_IR_COLLECTION_SEMANTICS,
    UI_UX_IR_SCHEMA_VERSION,
    UIIR_DOCUMENT_FIELDS,
    UIIR_REQUIRED_PATHS,
    AdaptationPolicy,
    AuthorityKind,
    CompositionEdgeKind,
    EventKind,
    LayoutRegionKind,
    ProgramBindingTargetKind,
    ReviewStatus,
    SourceSpan,
    TerminalOutcomeKind,
    UIAccessibilityBinding,
    UIAdaptiveVariant,
    UIComponent,
    UICompositionEdge,
    UIConfiguration,
    UIContentReference,
    UIDataBinding,
    UIDesignTokenRef,
    UIDeviceCapabilityRequirement,
    UIEffect,
    UIEvent,
    UIFeedbackContract,
    UIFormalConstraintRef,
    UIGuard,
    UIIRDocument,
    UIIRValidationError,
    UIIntentIRBinding,
    UIInvocationBinding,
    UIJourney,
    UILayoutConstraint,
    UILayoutRegion,
    UILocaleDefaults,
    UILocalizationBinding,
    UIMCPIDLBinding,
    UIModalityAlternative,
    UIModalityRequirement,
    UINamespacedExtension,
    UIProducer,
    UIProgramBinding,
    UIProofObligationRef,
    UIRecoveryPath,
    UIReviewBinding,
    UISourceRef,
    UIState,
    UIStateVariable,
    UITerminalOutcome,
    UITransition,
    UITrustBinding,
    UIUXTask,
    load_ui_ux_ir_json_schema,
    reject_unknown_document_fields,
    validate_ui_ir,
)


def _source() -> UISourceRef:
    return UISourceRef(
        ref_id="source:form-v1",
        source_uri="https://example.test/ui/form",
        source_id="form-v1",
        source_revision="rev-1",
        content_sha256="a" * 64,
        container_uri="ipfs://bafy-fixture/form",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
        span=SourceSpan(start_char=0, end_char=120),
    )


def _minimal_document(**overrides: object) -> UIIRDocument:
    source = _source()
    root = UIComponent(
        component_id="component:root",
        role="form",
        purpose="Collect a value and submit it.",
        accessible_name_ref="loc:form-title",
        child_ids=("component:submit",),
        program_binding_ids=("program:submit",),
        feedback_ids=("feedback:error",),
        source_ref_ids=(source.ref_id,),
    )
    submit = UIComponent(
        component_id="component:submit",
        role="button",
        purpose="Submit the form.",
        parent_id="component:root",
        program_binding_ids=("program:submit",),
        source_ref_ids=(source.ref_id,),
    )
    program = UIProgramBinding(
        binding_id="program:submit",
        target_kind=ProgramBindingTargetKind.MCP_IDL,
        target_ref="mcp:submit-form",
        risk_class="medium",
        confirmation_class="confirm",
        source_ref_ids=(source.ref_id,),
    )
    feedback = UIFeedbackContract(
        feedback_id="feedback:error",
        channel="status",
        component_id="component:root",
        source_ref_ids=(source.ref_id,),
    )
    terminal = UITerminalOutcome(
        outcome_id="outcome:success",
        kind=TerminalOutcomeKind.SUCCESS,
        description="Form submitted.",
        source_ref_ids=(source.ref_id,),
    )
    kwargs = {
        "document_id": "ui:form-v1",
        "title": "Example form",
        "sources": (source,),
        "components": (root, submit),
        "entry_components": ("component:root",),
        "terminal_outcomes": (terminal,),
        "program_bindings": (program,),
        "feedback_contracts": (feedback,),
        "producer": UIProducer(
            producer_id="producer:fixture",
            name="UIR-010 fixture",
            version="1.0.0",
        ),
        "configuration": UIConfiguration(
            configuration_id="config:default",
            profile="fixture",
            settings=MappingProxyType({"theme_intent": "neutral"}),
        ),
        "review": UIReviewBinding(
            review_status=ReviewStatus.TRUSTED_FIXTURE,
            reviewer="test",
        ),
        "locale_defaults": UILocaleDefaults(
            default_locale="en",
            fallback_locales=("en-US", "en"),
            text_direction="ltr",
        ),
        "tags": ("fixture", "form"),
    }
    kwargs.update(overrides)
    return UIIRDocument(**kwargs)  # type: ignore[arg-type]


def _rich_document() -> UIIRDocument:
    """Exercise every envelope collection with closed cross-references."""

    source = _source()
    base = _minimal_document()
    region = UILayoutRegion(
        region_id="region:main",
        kind=LayoutRegionKind.STACK,
        component_ids=("component:root", "component:submit"),
        source_ref_ids=(source.ref_id,),
    )
    constraint = UILayoutConstraint(
        constraint_id="layout:order",
        kind="order",
        region_ids=("region:main",),
        component_ids=("component:root",),
        adaptation_policy=AdaptationPolicy.PRESERVE,
        source_ref_ids=(source.ref_id,),
    )
    token = UIDesignTokenRef(
        token_id="token:spacing-md",
        category="spacing",
        token_name="space.md",
        source_ref_ids=(source.ref_id,),
    )
    variable = UIStateVariable(
        variable_id="var:pending",
        value_type="boolean",
        derived=False,
        source_ref_ids=(source.ref_id,),
    )
    idle = UIState(
        state_id="state:idle",
        region_id="region:main",
        source_ref_ids=(source.ref_id,),
    )
    pending = UIState(
        state_id="state:pending",
        region_id="region:main",
        source_ref_ids=(source.ref_id,),
    )
    event = UIEvent(
        event_id="event:submit",
        kind=EventKind.INPUT,
        source_ref_ids=(source.ref_id,),
    )
    formal = UIFormalConstraintRef(
        constraint_id="formal:confirm-before-submit",
        view="tdfol",
        formula_ref="formula:confirm-before-submit",
        source_ref_ids=(source.ref_id,),
    )
    guard = UIGuard(
        guard_id="guard:ready",
        formal_constraint_id="formal:confirm-before-submit",
        source_ref_ids=(source.ref_id,),
    )
    effect = UIEffect(
        effect_id="effect:invoke-submit",
        program_binding_id="program:submit",
        source_ref_ids=(source.ref_id,),
    )
    transition = UITransition(
        transition_id="transition:idle-pending",
        source_state_id="state:idle",
        target_state_id="state:pending",
        event_id="event:submit",
        guard_id="guard:ready",
        effect_ids=("effect:invoke-submit",),
        priority=10,
        source_ref_ids=(source.ref_id,),
    )
    task = UIUXTask(
        task_id="task:submit-form",
        name="Submit form",
        step_component_ids=("component:root", "component:submit"),
        source_ref_ids=(source.ref_id,),
    )
    journey = UIJourney(
        journey_id="journey:happy-path",
        name="Happy path",
        task_ids=("task:submit-form",),
        source_ref_ids=(source.ref_id,),
    )
    recovery = UIRecoveryPath(
        path_id="path:recover",
        kind=TerminalOutcomeKind.FAILURE,
        target_outcome_id="outcome:success",
        recovery_component_id="component:root",
        source_ref_ids=(source.ref_id,),
    )
    a11y = UIAccessibilityBinding(
        accessibility_id="a11y:root",
        component_id="component:root",
        role="form",
        name_ref="loc:form-title",
        source_ref_ids=(source.ref_id,),
    )
    localization = UILocalizationBinding(
        localization_id="loc:form-title",
        message_id="form.title",
        default_text="Example form",
        source_ref_ids=(source.ref_id,),
    )
    input_req = UIModalityRequirement(
        requirement_id="mod-in:pointer",
        direction="input",
        capability_ids=("pointer_mouse", "keyboard"),
        essential=True,
        source_ref_ids=(source.ref_id,),
    )
    output_req = UIModalityRequirement(
        requirement_id="mod-out:display",
        direction="output",
        capability_ids=("display",),
        essential=True,
        source_ref_ids=(source.ref_id,),
    )
    input_req_kb = UIModalityRequirement(
        requirement_id="mod-in:keyboard-only",
        direction="input",
        capability_ids=("keyboard",),
        essential=True,
        source_ref_ids=(source.ref_id,),
    )
    alt = UIModalityAlternative(
        alternative_id="mod-alt:keyboard",
        primary_requirement_id="mod-in:pointer",
        alternative_requirement_id="mod-in:keyboard-only",
        source_ref_ids=(source.ref_id,),
    )
    device = UIDeviceCapabilityRequirement(
        requirement_id="device:desktop",
        capability_ids=("display", "keyboard"),
        source_ref_ids=(source.ref_id,),
    )
    variant = UIAdaptiveVariant(
        variant_id="variant:compact",
        adaptation_policy=AdaptationPolicy.ADAPT,
        capability_predicate_ids=("device:desktop",),
        source_ref_ids=(source.ref_id,),
    )
    data = UIDataBinding(
        binding_id="data:form-values",
        kind="query",
        resource_ref="resource:form-values",
        source_ref_ids=(source.ref_id,),
    )
    content = UIContentReference(
        content_id="content:title",
        kind="text",
        resource_ref="msg:form.title",
        localization_id="loc:form-title",
        source_ref_ids=(source.ref_id,),
    )
    intent = UIIntentIRBinding(
        binding_id="intent:submit",
        intent_document_id="intent:skill-1",
        intent_action_id="action:build",
        source_ref_ids=(source.ref_id,),
    )
    invocation = UIInvocationBinding(
        binding_id="invocation:submit",
        template_cid="bafybeigfixturetemplate0000000000000000000000000000",
        source_ref_ids=(source.ref_id,),
    )
    mcp = UIMCPIDLBinding(
        binding_id="mcp:submit-form",
        interface_cid="bafybeigfixtureinterface000000000000000000000000000",
        method_name="submit_form",
        argument_schema_ref="schema:submit-args",
        result_schema_ref="schema:submit-result",
        source_ref_ids=(source.ref_id,),
    )
    proof = UIProofObligationRef(
        obligation_id="proof:confirm-before-submit",
        constraint_id="formal:confirm-before-submit",
        prover="tdfol",
        source_ref_ids=(source.ref_id,),
    )
    edge = UICompositionEdge(
        edge_id="edge:root-submit",
        kind=CompositionEdgeKind.CHILD,
        source_component_id="component:root",
        target_component_id="component:submit",
        source_ref_ids=(source.ref_id,),
    )
    trust = UITrustBinding(
        trust_id="trust:fixture",
        authority_kind=AuthorityKind.DECLARATION,
        subject_ref="ui:form-v1",
        source_ref_ids=(source.ref_id,),
    )
    extension = UINamespacedExtension(
        extension_id="ext:pilot-meta",
        namespace="uir.pilot.meta",
        version="1",
        payload=MappingProxyType({"pilot": "responsive_form"}),
        required=False,
        source_ref_ids=(source.ref_id,),
    )
    return replace(
        base,
        trust_bindings=(trust,),
        composition_edges=(edge,),
        layout_regions=(region,),
        layout_constraints=(constraint,),
        design_token_refs=(token,),
        state_variables=(variable,),
        states=(idle, pending),
        events=(event,),
        transitions=(transition,),
        guards=(guard,),
        effects=(effect,),
        ux_tasks=(task,),
        journeys=(journey,),
        success_failure_recovery=(recovery,),
        accessibility=(a11y,),
        localization=(localization,),
        input_modality_requirements=(input_req, input_req_kb),
        output_modality_requirements=(output_req,),
        modality_alternatives=(alt,),
        device_capability_requirements=(device,),
        adaptive_variants=(variant,),
        data_bindings=(data,),
        content_references=(content,),
        intent_ir_bindings=(intent,),
        invocation_bindings=(invocation,),
        mcp_idl_bindings=(mcp,),
        formal_constraint_refs=(formal,),
        proof_obligation_refs=(proof,),
        initial_states=("state:idle",),
        extensions=(extension,),
        components=(
            replace(
                base.components[0],
                data_binding_ids=("data:form-values",),
            ),
            base.components[1],
        ),
    )


def test_schema_version_is_ui_ux_ir_v1() -> None:
    assert UI_UX_IR_SCHEMA_VERSION == "ui-ux-ir/v1"
    document = _minimal_document()
    document.validate()
    assert document.schema_version == "ui-ux-ir/v1"
    assert document.to_dict()["schema_version"] == "ui-ux-ir/v1"


def test_minimal_and_rich_documents_validate() -> None:
    _minimal_document().validate()
    rich = _rich_document()
    rich.validate()
    payload = rich.to_dict()
    for field in (
        "sources",
        "components",
        "layout_regions",
        "states",
        "transitions",
        "program_bindings",
        "formal_constraint_refs",
        "entry_components",
        "terminal_outcomes",
        "extensions",
    ):
        assert field in payload
        assert payload[field]


def test_json_schema_is_closed_and_matches_wire_version() -> None:
    schema = load_ui_ux_ir_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "ui-ux-ir/v1"
    assert set(schema["required"]) == set(UIIR_REQUIRED_PATHS)
    assert set(schema["properties"]) == set(UIIR_DOCUMENT_FIELDS)

    validator = jsonschema.Draft202012Validator(schema)
    payload = _rich_document().to_dict()
    validator.validate(payload)

    invalid = dict(payload)
    invalid["unknown_field"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)


def test_reject_unknown_document_fields() -> None:
    payload = _minimal_document().to_dict()
    reject_unknown_document_fields(payload)

    with pytest.raises(UIIRValidationError, match="unknown UIIRDocument field"):
        reject_unknown_document_fields({**payload, "extra": 1})

    incomplete = {
        key: payload[key]
        for key in ("schema_version", "document_id", "title", "sources")
    }
    with pytest.raises(UIIRValidationError, match="missing required"):
        reject_unknown_document_fields(incomplete)


def test_rejects_duplicate_ids() -> None:
    document = _minimal_document()
    duplicate = replace(
        document,
        components=(document.components[0], document.components[0]),
    )
    with pytest.raises(UIIRValidationError, match="Duplicate component"):
        duplicate.validate()


def test_rejects_dangling_references() -> None:
    document = _minimal_document()
    broken = replace(
        document.components[0],
        program_binding_ids=("program:missing",),
    )
    with pytest.raises(UIIRValidationError, match="unknown ids"):
        replace(
            document,
            components=(broken, document.components[1]),
        ).validate()


def test_rejects_dangling_entry_components() -> None:
    document = _minimal_document()
    with pytest.raises(UIIRValidationError, match="entry_components"):
        replace(document, entry_components=("component:missing",)).validate()


def test_rejects_missing_required_paths() -> None:
    document = _minimal_document()
    with pytest.raises(UIIRValidationError, match="sources must not be empty"):
        replace(document, sources=()).validate()
    with pytest.raises(UIIRValidationError, match="components must not be empty"):
        replace(document, components=(), entry_components=("component:root",)).validate()
    with pytest.raises(UIIRValidationError, match="entry_components must not be empty"):
        replace(document, entry_components=()).validate()
    with pytest.raises(UIIRValidationError, match="terminal_outcomes must not be empty"):
        replace(document, terminal_outcomes=()).validate()


def test_rejects_invalid_collection_semantics() -> None:
    document = _minimal_document()
    raw = object.__new__(UIIRDocument)
    for field_name in UIIRDocument.__dataclass_fields__:
        if field_name == "tags":
            object.__setattr__(raw, field_name, ["not-a-tuple"])  # type: ignore[arg-type]
        else:
            object.__setattr__(raw, field_name, getattr(document, field_name))
    with pytest.raises(UIIRValidationError, match="immutable tuple"):
        raw.validate()

    raw_entry = object.__new__(UIIRDocument)
    for field_name in UIIRDocument.__dataclass_fields__:
        if field_name == "entry_components":
            object.__setattr__(
                raw_entry, field_name, ["component:root", "component:root"]
            )  # type: ignore[arg-type]
        else:
            object.__setattr__(raw_entry, field_name, getattr(document, field_name))
    with pytest.raises(UIIRValidationError, match="immutable tuple"):
        raw_entry.validate()


def test_collection_semantics_are_declared_for_envelope() -> None:
    assert (
        UI_UX_IR_COLLECTION_SEMANTICS["UIIRDocument.components"]
        is CollectionSemantics.SET_LIKE
    )
    assert (
        UI_UX_IR_COLLECTION_SEMANTICS["UIComponent.child_ids"]
        is CollectionSemantics.ORDERED
    )
    assert (
        UI_UX_IR_COLLECTION_SCHEMA.semantics_for(("components",))
        is CollectionSemantics.SET_LIKE
    )
    assert (
        UI_UX_IR_COLLECTION_SCHEMA.semantics_for(
            ("components", "0", "child_ids")
        )
        is CollectionSemantics.ORDERED
    )
    assert (
        UI_UX_IR_COLLECTION_SCHEMA.semantics_for(("extensions",))
        is CollectionSemantics.SET_LIKE
    )


def test_rejects_executable_callbacks_in_configuration() -> None:
    document = _minimal_document()
    with pytest.raises(UIIRValidationError, match="executable callback"):
        replace(
            document,
            configuration=UIConfiguration(
                configuration_id="config:bad",
                settings={"on_click": "alert(1)"},
            ),
        ).validate()


def test_rejects_executable_callbacks_in_extension_payload() -> None:
    document = _minimal_document()
    with pytest.raises(UIIRValidationError, match="executable callback"):
        replace(
            document,
            extensions=(
                UINamespacedExtension(
                    extension_id="ext:bad",
                    namespace="uir.custom",
                    version="1",
                    payload={"callback": lambda: None},  # type: ignore[dict-item]
                ),
            ),
        ).validate()


def test_rejects_runtime_artifact_namespaces_as_extensions() -> None:
    document = _minimal_document()
    with pytest.raises(UIIRValidationError, match="not declaration content"):
        replace(
            document,
            extensions=(
                UINamespacedExtension(
                    extension_id="ext:obs",
                    namespace="observation.device",
                    version="1",
                    payload={"ok": True},
                ),
            ),
        ).validate()


def test_namespaced_extensions_are_accepted() -> None:
    document = replace(
        _minimal_document(),
        extensions=(
            UINamespacedExtension(
                extension_id="ext:meta",
                namespace="uir.pilot.meta",
                version="1.0.0",
                payload={"flag": True},
                source_ref_ids=(_source().ref_id,),
            ),
        ),
    )
    document.validate()
    assert document.to_dict()["extensions"][0]["namespace"] == "uir.pilot.meta"


def test_mutation_after_construction_is_rejected() -> None:
    document = _minimal_document()
    with pytest.raises(FrozenInstanceError):
        document.title = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        document.components[0].role = "link"  # type: ignore[misc]


def test_mapping_decoder_is_fail_closed_until_versioned_decoder_exists() -> None:
    with pytest.raises(UIIRValidationError, match="versioned decoder"):
        validate_ui_ir(_minimal_document().to_dict())


def test_unsupported_schema_version_fails_closed() -> None:
    document = _minimal_document()
    with pytest.raises(UIIRValidationError, match="schema_version"):
        replace(document, schema_version="ui-ux-ir/v9").validate()


def test_initial_states_required_when_states_declared() -> None:
    document = _rich_document()
    with pytest.raises(UIIRValidationError, match="initial_states"):
        replace(document, initial_states=()).validate()


def test_source_digest_must_be_lowercase() -> None:
    document = _minimal_document()
    uppercase = replace(
        document.sources[0],
        content_sha256=document.sources[0].content_sha256.upper(),
    )
    with pytest.raises(UIIRValidationError, match="lowercase"):
        replace(document, sources=(uppercase,)).validate()


def test_to_dict_is_closed_and_json_schema_valid() -> None:
    payload = _rich_document().to_dict()
    assert set(payload) <= set(UIIR_DOCUMENT_FIELDS)
    reject_unknown_document_fields(payload)
    jsonschema.Draft202012Validator(load_ui_ux_ir_json_schema()).validate(payload)
