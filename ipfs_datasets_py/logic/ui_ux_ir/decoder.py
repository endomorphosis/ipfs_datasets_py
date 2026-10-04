"""Exact-version decoding for UI/UX IR wire documents (UIR-011)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .schema import (
    LEGACY_UI_UX_IR_SCHEMA_VERSION,
    ReviewStatus,
    SourceSpan,
    TerminalOutcomeKind,
    UIComponent,
    UILocaleDefaults,
    UIIRDocument,
    UIIRValidationError,
    UISourceRef,
    UITerminalOutcome,
    UI_UX_IR_SCHEMA_VERSION,
    reject_unknown_document_fields,
    validate_ui_ir,
)


class UIIRDecodeError(UIIRValidationError):
    """Raised when an untrusted payload cannot be decoded exactly."""


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UIIRDecodeError(f"{label} must be an object")
    return value


def _tuple_str(value: Any, label: str) -> tuple[str, ...]:
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


def _decode_source(payload: Mapping[str, Any]) -> UISourceRef:
    span_raw = payload.get("span")
    span = None
    if span_raw is not None:
        span_map = _require_mapping(span_raw, "UISourceRef.span")
        span = SourceSpan(
            start_char=int(span_map.get("start_char", 0)),
            end_char=int(span_map.get("end_char", 0)),
        )
    review = payload.get("review_status", ReviewStatus.UNREVIEWED)
    if isinstance(review, str):
        review = ReviewStatus(review)
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
        review_status=review,
        span=span,
    )


def _decode_component(payload: Mapping[str, Any]) -> UIComponent:
    return UIComponent(
        component_id=str(payload.get("component_id") or ""),
        role=str(payload.get("role") or ""),
        purpose=str(payload.get("purpose") or ""),
        accessible_name_ref=str(payload.get("accessible_name_ref") or ""),
        accessible_description_ref=str(payload.get("accessible_description_ref") or ""),
        parent_id=str(payload.get("parent_id") or ""),
        child_ids=_tuple_str(payload.get("child_ids"), "UIComponent.child_ids"),
        modality_binding_ids=_tuple_str(
            payload.get("modality_binding_ids"), "UIComponent.modality_binding_ids"
        ),
        data_binding_ids=_tuple_str(
            payload.get("data_binding_ids"), "UIComponent.data_binding_ids"
        ),
        program_binding_ids=_tuple_str(
            payload.get("program_binding_ids"), "UIComponent.program_binding_ids"
        ),
        feedback_ids=_tuple_str(payload.get("feedback_ids"), "UIComponent.feedback_ids"),
        privacy_sensitivity=str(payload.get("privacy_sensitivity") or "none"),
        presentation_classification=str(
            payload.get("presentation_classification") or "interactive"
        ),
        source_ref_ids=_tuple_str(
            payload.get("source_ref_ids"), "UIComponent.source_ref_ids"
        ),
    )


def _decode_terminal(payload: Mapping[str, Any]) -> UITerminalOutcome:
    kind = payload.get("kind", TerminalOutcomeKind.SUCCESS)
    if isinstance(kind, str):
        kind = TerminalOutcomeKind(kind)
    return UITerminalOutcome(
        outcome_id=str(payload.get("outcome_id") or ""),
        kind=kind,
        description=str(payload.get("description") or ""),
        source_ref_ids=_tuple_str(
            payload.get("source_ref_ids"), "UITerminalOutcome.source_ref_ids"
        ),
    )


def _decode_locale(payload: Mapping[str, Any] | None) -> UILocaleDefaults:
    if not payload:
        return UILocaleDefaults()
    data = _require_mapping(payload, "locale_defaults")
    return UILocaleDefaults(
        default_locale=str(data.get("default_locale") or "en"),
        fallback_locales=_tuple_str(
            data.get("fallback_locales"), "locale_defaults.fallback_locales"
        ),
        text_direction=str(data.get("text_direction") or "ltr"),
    )


def decode_ui_ir(payload: Mapping[str, Any] | str | bytes) -> UIIRDocument:
    """Decode a wire payload into a validated ``UIIRDocument``.

    Unknown versions and unknown top-level fields fail closed. Legacy versions
    must be migrated explicitly via :mod:`migrations` before decode.
    """

    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UIIRDecodeError(f"UI/UX IR payload is not valid UTF-8 JSON: {exc}") from exc
    elif isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise UIIRDecodeError(f"UI/UX IR payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise UIIRDecodeError("UI/UX IR payload must decode to an object")

    version = str(payload.get("schema_version") or "")
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
        reject_unknown_document_fields(payload)
    except UIIRValidationError as exc:
        raise UIIRDecodeError(str(exc)) from exc

    sources_raw = payload.get("sources") or ()
    components_raw = payload.get("components") or ()
    terminals_raw = payload.get("terminal_outcomes") or ()
    if not isinstance(sources_raw, (list, tuple)):
        raise UIIRDecodeError("sources must be an array")
    if not isinstance(components_raw, (list, tuple)):
        raise UIIRDecodeError("components must be an array")
    if not isinstance(terminals_raw, (list, tuple)):
        raise UIIRDecodeError("terminal_outcomes must be an array")

    try:
        document = UIIRDocument(
            document_id=str(payload.get("document_id") or ""),
            title=str(payload.get("title") or ""),
            schema_version=version,
            sources=tuple(
                _decode_source(_require_mapping(item, "sources[]")) for item in sources_raw
            ),
            components=tuple(
                _decode_component(_require_mapping(item, "components[]"))
                for item in components_raw
            ),
            entry_components=_tuple_str(
                payload.get("entry_components"), "entry_components"
            ),
            terminal_outcomes=tuple(
                _decode_terminal(_require_mapping(item, "terminal_outcomes[]"))
                for item in terminals_raw
            ),
            locale_defaults=_decode_locale(payload.get("locale_defaults")),
            tags=_tuple_str(payload.get("tags"), "tags"),
        )
    except UIIRValidationError as exc:
        raise UIIRDecodeError(str(exc)) from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise UIIRDecodeError(f"Failed to decode UI/UX IR document: {exc}") from exc

    return validate_ui_ir(document)


__all__ = ["UIIRDecodeError", "decode_ui_ir"]
