"""Compose existing typed contracts into one CanonicalTypedBridge envelope.

This module does not invent a logic family or a second canonicalizer.  It
wraps CanonicalRoundTripIR, FormalizationArtifact-shaped payloads, and
LegalIRDocument views while retaining family identity and recording every
required construct as represented or explicitly unsupported.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_ROUNDTRIP_IR_INTERFACE,
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    CANONICAL_TYPED_BRIDGE_INTERFACE,
    BridgeAssumption,
    BridgeRepresentationKind,
    BridgeSourceReference,
    BridgeTraceKind,
    BridgeTraceRef,
    BridgeUnsupportedConstruct,
    BridgeView,
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalTypedBridge,
    CompilerResult,
    ConstructDisposition,
    DomainLogicSliceRole,
    UnsupportedDisposition,
    infer_slice_member_ids,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

from .types import LegalIRDocument, LogicIRView


FORMALIZATION_ARTIFACT_SCHEMA_ID = "formalization-artifact/v1"
LEGAL_IR_DOCUMENT_SCHEMA_ID = "LegalIRDocument@1"
_FAMILY_FROM_DOMAIN = {
    "legal": "legal",
    "security": "security",
    "intent": "intent",
    "deontic": "deontic",
    "modal": "modal",
    "tdfol": "tdfol",
    "cec": "cec",
}


def _source_cid_for_text(text: str) -> str:
    return cid_for_bytes(text.encode("utf-8"))


def _view(
    *,
    name: str,
    kind: BridgeRepresentationKind,
    schema_id: str,
    family_id: str,
    payload: Mapping[str, Any],
) -> BridgeView:
    return BridgeView(
        name=name,
        kind=kind,
        schema_id=schema_id,
        family_id=family_id,
        payload=dict(payload),
    )


def _source_reference(
    *,
    ref_id: str,
    text: str,
    source_uri: str = "",
    source_revision: str = "",
    start: int | None = None,
    end: int | None = None,
) -> BridgeSourceReference:
    return BridgeSourceReference(
        ref_id=ref_id,
        source_cid=_source_cid_for_text(text),
        source_uri=source_uri,
        source_revision=source_revision,
        start=0 if start is None and text else start,
        end=end if end is not None else (len(text) if text else None),
    )


def _assumptions_from_mapping(
    values: Sequence[Mapping[str, Any]] | Sequence[Any],
) -> tuple[BridgeAssumption, ...]:
    assumptions: list[BridgeAssumption] = []
    for item in values:
        if isinstance(item, BridgeAssumption):
            assumptions.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        assumption_id = str(item.get("assumption_id") or item.get("id") or "").strip()
        statement = str(item.get("statement") or item.get("text") or "").strip()
        if not assumption_id or not statement:
            continue
        source_ref_ids = item.get("source_ref_ids") or item.get("source_ids") or ()
        assumptions.append(
            BridgeAssumption(
                assumption_id=assumption_id,
                statement=statement,
                source_ref_ids=tuple(str(ref) for ref in source_ref_ids),
            )
        )
    return tuple(assumptions)


def _trace_refs_from_mapping(
    values: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[BridgeTraceRef, ...]:
    if not values:
        return ()
    refs: list[BridgeTraceRef] = []
    for kind_name, items in values.items():
        kind = BridgeTraceKind(kind_name)
        for item in items:
            refs.append(
                BridgeTraceRef(
                    kind=kind,
                    trace_id=str(item["trace_id"]),
                    trace_cid=item.get("trace_cid"),
                    schema_id=str(item.get("schema_id") or ""),
                )
            )
    return tuple(refs)


def _unsupported_slice(family_id: str) -> DomainLogicSliceRole:
    return DomainLogicSliceRole(
        disposition=ConstructDisposition.UNSUPPORTED,
        family_id=family_id,
        unsupported=BridgeUnsupportedConstruct(
            construct_id="domain_logic_slice",
            code="gap.domain_logic_slice",
            message=(
                "No DomainLogicSlice schema or family exists at the bound "
                "authority tree; the construct is retained as unsupported "
                "rather than invented or silently aliased to an existing family AST."
            ),
            disposition=UnsupportedDisposition.EXPLICIT_PARTIAL,
            family_id=family_id,
        ),
    )


def wrap_canonical_ir(
    ir: CanonicalRoundTripIR | Mapping[str, Any],
    *,
    family_id: str = "canonical_roundtrip",
    source_text: str = "",
    source_uri: str = "",
    assumptions: Sequence[BridgeAssumption] = (),
    provenance: Mapping[str, Any] | None = None,
    adapter_name: str = "",
    metadata: Mapping[str, Any] | None = None,
    project_slice: bool = True,
) -> CanonicalTypedBridge:
    """Wrap a CanonicalRoundTripIR without collapsing it into another family."""

    canonical = ir if isinstance(ir, CanonicalRoundTripIR) else CanonicalRoundTripIR.from_dict(ir)
    view = _view(
        name="canonical_roundtrip_ir",
        kind=BridgeRepresentationKind.CANONICAL_IR,
        schema_id=CANONICAL_ROUNDTRIP_IR_INTERFACE,
        family_id=family_id,
        payload=canonical.to_dict(),
    )
    sources = ()
    extra_views: list[BridgeView] = [view]
    if source_text:
        sources = (
            _source_reference(
                ref_id="source:canonical",
                text=source_text,
                source_uri=source_uri,
            ),
        )
        extra_views.append(
            _view(
                name="source_text",
                kind=BridgeRepresentationKind.SOURCE_TEXT,
                schema_id="source.text@1",
                family_id=family_id,
                payload={"source_text": source_text, "source_uri": source_uri},
            )
        )
    slice_role = None if project_slice else _unsupported_slice(family_id)
    return CanonicalTypedBridge.compose(
        family_id=family_id,
        authority_schema=CANONICAL_ROUNDTRIP_IR_INTERFACE,
        views=extra_views,
        source_references=sources,
        assumptions=assumptions,
        provenance=provenance or {"source_contract": CANONICAL_ROUNDTRIP_IR_INTERFACE},
        domain_logic_slice=slice_role,
        adapter_name=adapter_name,
        metadata=metadata or {"wrapped": "canonical_roundtrip_ir"},
        representation_kind=BridgeRepresentationKind.CANONICAL_IR,
    )


def wrap_compiler_result(
    result: CompilerResult,
    *,
    family_id: str = "deontic",
    source_text: str = "",
    adapter_name: str = "",
) -> CanonicalTypedBridge:
    """Wrap a compiler result, retaining source maps and unsupported semantics."""

    if result.canonical_ir is None:
        raise ValueError("compiler result has no CanonicalRoundTripIR to wrap")
    wrapped = wrap_canonical_ir(
        result.canonical_ir,
        family_id=family_id,
        source_text=source_text,
        provenance=dict(result.provenance),
        adapter_name=adapter_name,
        metadata={
            "compiler_interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
            "compiler_result_cid": result.result_cid,
            "request_cid": result.request_cid,
            "source_map_receipt": result.source_map_receipt(),
            "wrapped": "compiler_result",
        },
    )
    if not result.unsupported_semantics:
        return wrapped
    extra = tuple(
        BridgeUnsupportedConstruct(
            construct_id=item.code,
            code=item.code,
            message=item.message,
            disposition=item.disposition,
            family_id=family_id,
            source_cid=item.source_cid,
            start=item.start,
            end=item.end,
        )
        for item in result.unsupported_semantics
    )
    return CanonicalTypedBridge.compose(
        family_id=family_id,
        authority_schema=CANONICAL_ROUNDTRIP_IR_INTERFACE,
        views=tuple(wrapped.views.values()),
        source_references=wrapped.source_references,
        assumptions=wrapped.assumptions,
        provenance=dict(result.provenance),
        unsupported_constructs=(*wrapped.unsupported_constructs, *extra),
        trace_refs=wrapped.trace_refs,
        domain_logic_slice=wrapped.domain_logic_slice,
        adapter_name=adapter_name,
        metadata=dict(wrapped.metadata),
        representation_kind=BridgeRepresentationKind.CANONICAL_IR,
    )


def wrap_legal_ir_document(
    document: LegalIRDocument,
    *,
    family_id: str = "legal",
    adapter_name: str = "",
    assumptions: Sequence[BridgeAssumption] = (),
    project_slice: bool = True,
) -> CanonicalTypedBridge:
    """Wrap a LegalIRDocument without aliasing it to CanonicalRoundTripIR."""

    payload = document.to_dict()
    views = [
        _view(
            name="legal_ir_document",
            kind=BridgeRepresentationKind.LEGAL_IR_DOCUMENT,
            schema_id=LEGAL_IR_DOCUMENT_SCHEMA_ID,
            family_id=family_id,
            payload=payload,
        )
    ]
    if document.source_text:
        views.append(
            _view(
                name="source_text",
                kind=BridgeRepresentationKind.SOURCE_TEXT,
                schema_id="source.text@1",
                family_id=family_id,
                payload={"source_text": document.source_text, "source": document.source},
            )
        )
    for name, view in document.views.items():
        item = view if isinstance(view, LogicIRView) else LogicIRView(**dict(view))
        kind = _kind_for_legal_view(name, item)
        views.append(
            _view(
                name=name,
                kind=kind,
                schema_id=item.format or f"legal-ir-view:{name}",
                family_id=family_id,
                payload=dict(item.to_dict()),
            )
        )
    sources = ()
    if document.source_text:
        sources = (
            _source_reference(
                ref_id=document.document_id or "source:legal",
                text=document.source_text,
                source_uri=document.citation or document.source,
            ),
        )
    return CanonicalTypedBridge.compose(
        family_id=family_id,
        authority_schema=LEGAL_IR_DOCUMENT_SCHEMA_ID,
        views=views,
        source_references=sources,
        assumptions=assumptions,
        provenance={
            "document_id": document.document_id,
            "legal_ir_version": document.version,
            "source": document.source,
        },
        domain_logic_slice=None if project_slice else _unsupported_slice(family_id),
        adapter_name=adapter_name,
        metadata={
            "canonical_hash": document.canonical_hash(),
            "wrapped": "legal_ir_document",
        },
        representation_kind=BridgeRepresentationKind.LEGAL_IR_DOCUMENT,
    )


def _artifact_payload(artifact: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(artifact, Mapping):
        return dict(artifact)
    to_dict = getattr(artifact, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError("formalization artifact must be a mapping or provide to_dict()")


def _source_references_from_artifact(
    payload: Mapping[str, Any],
) -> tuple[BridgeSourceReference, ...]:
    source_map = payload.get("source_map")
    if not isinstance(source_map, Mapping):
        return ()
    sources: list[BridgeSourceReference] = []
    for item in source_map.get("sources") or ():
        if not isinstance(item, Mapping):
            continue
        ref_id = str(item.get("ref_id") or item.get("source_id") or "").strip()
        content_cid = str(item.get("content_cid") or "").strip()
        if not ref_id or not content_cid:
            continue
        try:
            sources.append(
                BridgeSourceReference(
                    ref_id=ref_id,
                    source_cid=content_cid,
                    source_uri=str(item.get("source_uri") or ""),
                    source_revision=str(item.get("source_revision") or ""),
                )
            )
        except CanonicalContractError:
            continue
    return tuple(sources)


def wrap_formalization_artifact(
    artifact: Mapping[str, Any] | Any,
    *,
    family_id: str | None = None,
    adapter_name: str = "",
    project_slice: bool = True,
) -> CanonicalTypedBridge:
    """Wrap a FormalizationArtifact payload without importing the compiler."""

    payload = _artifact_payload(artifact)
    domain = str(payload.get("domain") or family_id or "legal")
    resolved_family = family_id or _FAMILY_FROM_DOMAIN.get(domain, domain)
    views = [
        _view(
            name="formalization_artifact",
            kind=BridgeRepresentationKind.FORMALIZATION_ARTIFACT,
            schema_id=str(payload.get("schema_version") or FORMALIZATION_ARTIFACT_SCHEMA_ID),
            family_id=resolved_family,
            payload=payload,
        )
    ]
    assumptions = _assumptions_from_mapping(payload.get("assumptions") or ())
    sources = list(_source_references_from_artifact(payload))
    return CanonicalTypedBridge.compose(
        family_id=resolved_family,
        authority_schema=FORMALIZATION_ARTIFACT_SCHEMA_ID,
        views=views,
        source_references=sources,
        assumptions=assumptions,
        provenance={
            "declaration_digest": payload.get("declaration_digest"),
            "declaration_id": payload.get("declaration_id"),
            "domain": domain,
            "sample_id": payload.get("sample_id"),
        },
        domain_logic_slice=None if project_slice else _unsupported_slice(resolved_family),
        adapter_name=adapter_name,
        metadata={
            "digest": payload.get("digest"),
            "wrapped": "formalization_artifact",
        },
        representation_kind=BridgeRepresentationKind.FORMALIZATION_ARTIFACT,
    )


def extract_view(bridge: CanonicalTypedBridge, name: str) -> Mapping[str, Any]:
    """Return one retained existing-contract payload by view name."""

    payload = bridge.views[name].to_dict()["payload"]
    if not isinstance(payload, dict):
        raise TypeError(f"view {name!r} payload must be an object")
    return payload


def extract_canonical_ir(bridge: CanonicalTypedBridge) -> CanonicalRoundTripIR:
    """Rehydrate the CanonicalRoundTripIR view without changing its CID."""

    return CanonicalRoundTripIR.from_dict(extract_view(bridge, "canonical_roundtrip_ir"))


def extract_legal_ir_document(bridge: CanonicalTypedBridge) -> dict[str, Any]:
    """Return the retained LegalIRDocument payload."""

    return dict(extract_view(bridge, "legal_ir_document"))


def extract_formalization_artifact(bridge: CanonicalTypedBridge) -> dict[str, Any]:
    """Return the retained FormalizationArtifact payload."""

    return dict(extract_view(bridge, "formalization_artifact"))


def family_payload_identity(bridge: CanonicalTypedBridge) -> tuple[str, str]:
    """Return ``(family_id, payload_cid)`` used as the envelope authority."""

    return bridge.family_identity.family_id, bridge.family_identity.payload_cid


def _kind_for_legal_view(name: str, view: LogicIRView) -> BridgeRepresentationKind:
    lowered = f"{name} {view.format} {view.source_component}".lower()
    if "prover" in lowered:
        return BridgeRepresentationKind.PROVER_SYNTAX
    if "deontic" in lowered or "modal" in lowered or "tdfol" in lowered or "cec" in lowered:
        return BridgeRepresentationKind.TYPED_SYNTAX
    if name in {"frame_logic", "logic_family"}:
        return BridgeRepresentationKind.LOGIC_FAMILY
    if name not in {
        "legal_ir_document",
        "canonical_roundtrip_ir",
        "source_text",
        "formalization_artifact",
        "typed_syntax",
        "prover_syntax",
        "controlled_natural_language",
        "logic_family",
    }:
        return BridgeRepresentationKind.FAMILY_EXTENSION
    return BridgeRepresentationKind.LOGIC_FAMILY


def compose_typed_bridge(
    *,
    family_id: str,
    authority_schema: str,
    views: Sequence[BridgeView] | Mapping[str, BridgeView],
    source_references: Sequence[BridgeSourceReference] = (),
    assumptions: Sequence[BridgeAssumption] = (),
    provenance: Mapping[str, Any] | None = None,
    unsupported_constructs: Sequence[BridgeUnsupportedConstruct] = (),
    trace_refs: Sequence[BridgeTraceRef] = (),
    adapter_name: str = "",
    metadata: Mapping[str, Any] | None = None,
    project_slice: bool = True,
) -> CanonicalTypedBridge:
    """Public compose helper used by migrations and adapter conformance."""

    return CanonicalTypedBridge.compose(
        family_id=family_id,
        authority_schema=authority_schema,
        views=views,
        source_references=source_references,
        assumptions=assumptions,
        provenance=provenance,
        unsupported_constructs=unsupported_constructs,
        trace_refs=trace_refs,
        domain_logic_slice=None if project_slice else _unsupported_slice(family_id),
        adapter_name=adapter_name,
        metadata=metadata,
    )


__all__ = [
    "CANONICAL_TYPED_BRIDGE_INTERFACE",
    "FORMALIZATION_ARTIFACT_SCHEMA_ID",
    "LEGAL_IR_DOCUMENT_SCHEMA_ID",
    "compose_typed_bridge",
    "extract_canonical_ir",
    "extract_formalization_artifact",
    "extract_legal_ir_document",
    "extract_view",
    "family_payload_identity",
    "infer_slice_member_ids",
    "wrap_canonical_ir",
    "wrap_compiler_result",
    "wrap_formalization_artifact",
    "wrap_legal_ir_document",
]
