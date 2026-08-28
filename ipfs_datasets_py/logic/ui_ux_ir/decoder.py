"""Fail-closed decoding for UI/UX IR (ui-ux-ir/v1).

Legacy versions require explicit migration before decode. Mirrors SwissKnife
``decodeUiIr`` / ``UIIRDecodeError``.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from .schema import (
    LEGACY_UI_UX_IR_SCHEMA_VERSION,
    UI_UX_IR_SCHEMA_VERSION,
    AuthorityKind,
    LayoutRegionKind,
    ProgramBindingTargetKind,
    ReviewStatus,
    SourceSpan,
    TerminalOutcomeKind,
    UIComponent,
    UIConfiguration,
    UIEvent,
    UIFeedbackContract,
    UIIRDocument,
    UIIRValidationError,
    UIJourney,
    UILayoutRegion,
    UILocaleDefaults,
    UIMCPIDLBinding,
    UINamespacedExtension,
    UIProducer,
    UIProgramBinding,
    UIReviewBinding,
    UISourceRef,
    UIStateVariable,
    UITerminalOutcome,
    UITrustBinding,
    UIUXTask,
    reject_unknown_document_fields,
    validate_ui_ir,
)


class UIIRDecodeError(UIIRValidationError):
    """Raised when an untrusted wire document cannot be decoded exactly."""


def _parse_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise UIIRDecodeError(f"payload is not valid UTF-8: {exc}") from exc
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            raise UIIRDecodeError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise UIIRDecodeError("document payload must be a mapping")
    return dict(payload)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UIIRDecodeError(f"{label} must be an object")
    return dict(value)


def _as_string_array(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise UIIRDecodeError(f"{label} must be an array")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise UIIRDecodeError(f"{label} members must be non-empty strings")
        out.append(item)
    return tuple(out)


def _sorted_unique_strings(values: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(sorted(set(values or ())))


def _decode_source(payload: Mapping[str, Any]) -> UISourceRef:
    span_raw = payload.get("span")
    span: SourceSpan | None = None
    if span_raw is not None:
        span_map = _require_object(span_raw, "UISourceRef.span")
        span = SourceSpan(
            start_char=int(span_map.get("start_char") or 0),
            end_char=int(span_map.get("end_char") or 0),
        )
    status = payload.get("review_status") or ReviewStatus.UNREVIEWED.value
    if isinstance(status, ReviewStatus):
        status = status.value
    return UISourceRef(
        ref_id=str(payload.get("ref_id") or ""),
        source_uri=str(payload.get("source_uri") or ""),
        source_id=str(payload.get("source_id") or ""),
        source_revision=str(payload.get("source_revision") or ""),
        content_sha256=str(payload.get("content_sha256") or ""),
        container_uri=str(payload.get("container_uri") or ""),
        container_sha256=str(payload.get("container_sha256") or ""),
        content_cid=str(payload.get("content_cid") or ""),
        license_expression=str(payload.get("license_expression") or ""),
        review_status=str(status),
        span=span,
    )


def _decode_component(payload: Mapping[str, Any]) -> UIComponent:
    # Fail closed on executable callback keys before stripping unknown fields.
    from .schema import reject_executable_payload

    reject_executable_payload(payload, "UIComponent")
    return UIComponent(
        component_id=str(payload.get("component_id") or ""),
        role=str(payload.get("role") or ""),
        purpose=str(payload.get("purpose") or ""),
        accessible_name_ref=str(payload.get("accessible_name_ref") or ""),
        accessible_description_ref=str(
            payload.get("accessible_description_ref") or ""
        ),
        parent_id=str(payload.get("parent_id") or ""),
        child_ids=_as_string_array(payload.get("child_ids"), "child_ids"),
        modality_binding_ids=_as_string_array(
            payload.get("modality_binding_ids"), "modality_binding_ids"
        ),
        data_binding_ids=_as_string_array(
            payload.get("data_binding_ids"), "data_binding_ids"
        ),
        program_binding_ids=_as_string_array(
            payload.get("program_binding_ids"), "program_binding_ids"
        ),
        feedback_ids=_as_string_array(
            payload.get("feedback_ids"), "feedback_ids"
        ),
        privacy_sensitivity=str(payload.get("privacy_sensitivity") or "none"),
        presentation_classification=str(
            payload.get("presentation_classification") or "interactive"
        ),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_terminal(payload: Mapping[str, Any]) -> UITerminalOutcome:
    return UITerminalOutcome(
        outcome_id=str(payload.get("outcome_id") or ""),
        kind=str(payload.get("kind") or ""),
        description=str(payload.get("description") or ""),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_locale(value: Any) -> UILocaleDefaults:
    if value is None:
        return UILocaleDefaults()
    payload = _require_object(value, "locale_defaults")
    return UILocaleDefaults(
        default_locale=str(payload.get("default_locale") or "en"),
        fallback_locales=_as_string_array(
            payload.get("fallback_locales"), "fallback_locales"
        ),
        text_direction=str(payload.get("text_direction") or "ltr"),
    )


def _decode_record_array(
    value: Any,
    label: str,
    decoder: Callable[[Mapping[str, Any]], Any],
) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise UIIRDecodeError(f"{label} must be an array")
    out = []
    for index, item in enumerate(value):
        out.append(decoder(_require_object(item, f"{label}[{index}]")))
    return tuple(out)


def _decode_mapping_array(value: Any, label: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise UIIRDecodeError(f"{label} must be an array")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        out.append(_require_object(item, f"{label}[{index}]"))
    return tuple(out)


def _decode_trust(payload: Mapping[str, Any]) -> UITrustBinding:
    return UITrustBinding(
        trust_id=str(payload.get("trust_id") or ""),
        authority_kind=str(payload.get("authority_kind") or ""),
        subject_ref=str(payload.get("subject_ref") or ""),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_layout_region(payload: Mapping[str, Any]) -> UILayoutRegion:
    return UILayoutRegion(
        region_id=str(payload.get("region_id") or ""),
        kind=str(payload.get("kind") or LayoutRegionKind.FLOW.value),
        component_ids=_as_string_array(
            payload.get("component_ids"), "component_ids"
        ),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_state_variable(payload: Mapping[str, Any]) -> UIStateVariable:
    return UIStateVariable(
        variable_id=str(payload.get("variable_id") or ""),
        value_type=str(payload.get("value_type") or ""),
        derived=bool(payload.get("derived") or False),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_event(payload: Mapping[str, Any]) -> UIEvent:
    return UIEvent(
        event_id=str(payload.get("event_id") or ""),
        kind=str(payload.get("kind") or ""),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_task(payload: Mapping[str, Any]) -> UIUXTask:
    return UIUXTask(
        task_id=str(payload.get("task_id") or ""),
        name=str(payload.get("name") or ""),
        step_component_ids=_as_string_array(
            payload.get("step_component_ids"), "step_component_ids"
        ),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_journey(payload: Mapping[str, Any]) -> UIJourney:
    return UIJourney(
        journey_id=str(payload.get("journey_id") or ""),
        name=str(payload.get("name") or ""),
        task_ids=_as_string_array(payload.get("task_ids"), "task_ids"),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_program_binding(payload: Mapping[str, Any]) -> UIProgramBinding:
    return UIProgramBinding(
        binding_id=str(payload.get("binding_id") or ""),
        target_kind=str(
            payload.get("target_kind")
            or ProgramBindingTargetKind.LOCAL_STATE.value
        ),
        target_ref=str(payload.get("target_ref") or ""),
        confirmation_class=str(payload.get("confirmation_class") or "none"),
        risk_class=str(payload.get("risk_class") or "low"),
        effect_ids=_as_string_array(payload.get("effect_ids"), "effect_ids"),
        precondition_ids=_as_string_array(
            payload.get("precondition_ids"), "precondition_ids"
        ),
        verification_ids=_as_string_array(
            payload.get("verification_ids"), "verification_ids"
        ),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_mcp_idl_binding(payload: Mapping[str, Any]) -> UIMCPIDLBinding:
    return UIMCPIDLBinding(
        binding_id=str(payload.get("binding_id") or ""),
        interface_cid=str(payload.get("interface_cid") or ""),
        method_name=str(payload.get("method_name") or ""),
        argument_schema_ref=str(payload.get("argument_schema_ref") or ""),
        result_schema_ref=str(payload.get("result_schema_ref") or ""),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_feedback(payload: Mapping[str, Any]) -> UIFeedbackContract:
    return UIFeedbackContract(
        feedback_id=str(payload.get("feedback_id") or ""),
        channel=str(payload.get("channel") or ""),
        component_id=str(payload.get("component_id") or ""),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def _decode_extension(payload: Mapping[str, Any]) -> UINamespacedExtension:
    raw_payload = payload.get("payload")
    if raw_payload is None:
        body: dict[str, Any] = {}
    else:
        body = _require_object(raw_payload, "extension.payload")
    return UINamespacedExtension(
        extension_id=str(payload.get("extension_id") or ""),
        namespace=str(payload.get("namespace") or ""),
        version=str(payload.get("version") or ""),
        payload=body,
        required=bool(payload.get("required") or False),
        source_ref_ids=_as_string_array(
            payload.get("source_ref_ids"), "source_ref_ids"
        ),
    )


def decode_ui_ir(payload: Any) -> UIIRDocument:
    """Decode and validate a ui-ux-ir/v1 document.

    Legacy ``ui-ux-ir/v0.1`` requires explicit migration before decode.
    """
    raw = _parse_payload(payload)
    version = str(raw.get("schema_version") or "")
    if not version:
        raise UIIRDecodeError("UI/UX IR payload missing schema_version")
    if version == LEGACY_UI_UX_IR_SCHEMA_VERSION:
        raise UIIRDecodeError(
            f"Legacy schema_version {version!r} requires explicit migration before decode"
        )
    if version != UI_UX_IR_SCHEMA_VERSION:
        raise UIIRDecodeError(
            f"Unsupported schema_version {version!r}; expected {UI_UX_IR_SCHEMA_VERSION!r}"
        )

    try:
        reject_unknown_document_fields(raw)
    except UIIRValidationError as exc:
        raise UIIRDecodeError(str(exc)) from exc

    sources_raw = raw.get("sources")
    components_raw = raw.get("components")
    terminals_raw = raw.get("terminal_outcomes")
    if not isinstance(sources_raw, (list, tuple)):
        raise UIIRDecodeError("sources must be an array")
    if not isinstance(components_raw, (list, tuple)):
        raise UIIRDecodeError("components must be an array")
    if not isinstance(terminals_raw, (list, tuple)):
        raise UIIRDecodeError("terminal_outcomes must be an array")

    try:
        producer_raw = raw.get("producer")
        configuration_raw = raw.get("configuration")
        review_raw = raw.get("review")

        producer = None
        if producer_raw is not None:
            prod = _require_object(producer_raw, "producer")
            producer = UIProducer(
                producer_id=str(prod.get("producer_id") or ""),
                name=str(prod.get("name") or ""),
                version=str(prod.get("version") or ""),
            )

        configuration = None
        if configuration_raw is not None:
            conf = _require_object(configuration_raw, "configuration")
            settings = conf.get("settings")
            configuration = UIConfiguration(
                configuration_id=str(conf.get("configuration_id") or ""),
                profile=str(conf.get("profile") or "default"),
                settings=dict(settings) if isinstance(settings, Mapping) else {},
            )

        if review_raw is None:
            review = UIReviewBinding()
        else:
            rev = _require_object(review_raw, "review")
            review = UIReviewBinding(
                review_status=str(
                    rev.get("review_status") or ReviewStatus.UNREVIEWED.value
                ),
                reviewer=str(rev.get("reviewer") or ""),
                notes=str(rev.get("notes") or ""),
            )

        document = UIIRDocument(
            schema_version=version,
            document_id=str(raw.get("document_id") or ""),
            title=str(raw.get("title") or ""),
            sources=tuple(
                _decode_source(_require_object(item, f"sources[{i}]"))
                for i, item in enumerate(sources_raw)
            ),
            components=tuple(
                _decode_component(_require_object(item, f"components[{i}]"))
                for i, item in enumerate(components_raw)
            ),
            entry_components=_sorted_unique_strings(
                _as_string_array(raw.get("entry_components"), "entry_components")
            ),
            terminal_outcomes=tuple(
                _decode_terminal(
                    _require_object(item, f"terminal_outcomes[{i}]")
                )
                for i, item in enumerate(terminals_raw)
            ),
            locale_defaults=_decode_locale(raw.get("locale_defaults")),
            tags=_as_string_array(raw.get("tags"), "tags"),
            producer=producer,
            configuration=configuration,
            review=review,
            trust_bindings=_decode_record_array(
                raw.get("trust_bindings"), "trust_bindings", _decode_trust
            ),
            composition_edges=_decode_mapping_array(
                raw.get("composition_edges"), "composition_edges"
            ),
            layout_regions=_decode_record_array(
                raw.get("layout_regions"),
                "layout_regions",
                _decode_layout_region,
            ),
            layout_constraints=_decode_mapping_array(
                raw.get("layout_constraints"), "layout_constraints"
            ),
            design_token_refs=_decode_mapping_array(
                raw.get("design_token_refs"), "design_token_refs"
            ),
            state_variables=_decode_record_array(
                raw.get("state_variables"),
                "state_variables",
                _decode_state_variable,
            ),
            states=_decode_mapping_array(raw.get("states"), "states"),
            events=_decode_record_array(raw.get("events"), "events", _decode_event),
            transitions=_decode_mapping_array(
                raw.get("transitions"), "transitions"
            ),
            guards=_decode_mapping_array(raw.get("guards"), "guards"),
            effects=_decode_mapping_array(raw.get("effects"), "effects"),
            ux_tasks=_decode_record_array(
                raw.get("ux_tasks"), "ux_tasks", _decode_task
            ),
            journeys=_decode_record_array(
                raw.get("journeys"), "journeys", _decode_journey
            ),
            success_failure_recovery=_decode_mapping_array(
                raw.get("success_failure_recovery"), "success_failure_recovery"
            ),
            feedback_contracts=_decode_record_array(
                raw.get("feedback_contracts"),
                "feedback_contracts",
                _decode_feedback,
            ),
            accessibility=_decode_mapping_array(
                raw.get("accessibility"), "accessibility"
            ),
            localization=_decode_mapping_array(
                raw.get("localization"), "localization"
            ),
            input_modality_requirements=_decode_mapping_array(
                raw.get("input_modality_requirements"),
                "input_modality_requirements",
            ),
            output_modality_requirements=_decode_mapping_array(
                raw.get("output_modality_requirements"),
                "output_modality_requirements",
            ),
            modality_alternatives=_decode_mapping_array(
                raw.get("modality_alternatives"), "modality_alternatives"
            ),
            device_capability_requirements=_decode_mapping_array(
                raw.get("device_capability_requirements"),
                "device_capability_requirements",
            ),
            adaptive_variants=_decode_mapping_array(
                raw.get("adaptive_variants"), "adaptive_variants"
            ),
            data_bindings=_decode_mapping_array(
                raw.get("data_bindings"), "data_bindings"
            ),
            content_references=_decode_mapping_array(
                raw.get("content_references"), "content_references"
            ),
            program_bindings=_decode_record_array(
                raw.get("program_bindings"),
                "program_bindings",
                _decode_program_binding,
            ),
            intent_ir_bindings=_decode_mapping_array(
                raw.get("intent_ir_bindings"), "intent_ir_bindings"
            ),
            invocation_bindings=_decode_mapping_array(
                raw.get("invocation_bindings"), "invocation_bindings"
            ),
            mcp_idl_bindings=_decode_record_array(
                raw.get("mcp_idl_bindings"),
                "mcp_idl_bindings",
                _decode_mcp_idl_binding,
            ),
            formal_constraint_refs=_decode_mapping_array(
                raw.get("formal_constraint_refs"), "formal_constraint_refs"
            ),
            proof_obligation_refs=_decode_mapping_array(
                raw.get("proof_obligation_refs"), "proof_obligation_refs"
            ),
            initial_states=_as_string_array(
                raw.get("initial_states"), "initial_states"
            ),
            extensions=_decode_record_array(
                raw.get("extensions"), "extensions", _decode_extension
            ),
        )
    except UIIRValidationError as exc:
        raise UIIRDecodeError(str(exc)) from exc
    except UIIRDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UIIRDecodeError(
            f"Failed to decode UI/UX IR document: {exc}"
        ) from exc

    try:
        return validate_ui_ir(document)
    except UIIRValidationError as exc:
        raise UIIRDecodeError(str(exc)) from exc


# Public aliases
decode_uiir = decode_ui_ir

__all__ = [
    "UIIRDecodeError",
    "decode_ui_ir",
    "decode_uiir",
]
