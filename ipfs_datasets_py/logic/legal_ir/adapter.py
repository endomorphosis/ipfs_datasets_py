"""Compatibility adapter from the established Legal IR to shared contracts.

The Legal parser and its training sample predate the domain-neutral
``logic.formalization`` contracts.  This module is intentionally an adapter:
it does not change, wrap, or replace the existing parser, modal IR classes, or
their serialization.

Two identities are kept deliberately separate:

* ``FormalizationArtifact.artifact_id`` identifies the shared projection.
* ``declaration_digest`` and ``legacy_output_identity`` retain the exact
  ``ModalIRDocument.canonical_hash()`` value produced by Legal IR.

Source bodies, embeddings, traces, and training/runtime results are not copied
into formal declarations.  Their canonical digests and dispositions are kept
in an explicit unsupported-field manifest, and compilation emits grounded
``ir.feature.unsupported`` diagnostics for each one.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompilerConfig,
    UnsupportedSemanticsPolicy,
)
from ipfs_datasets_py.logic.formalization.samples import (
    FormalizationSample,
    FormalizationValidationError,
)
from ipfs_datasets_py.logic.formalization.views import (
    CrossViewLink,
    CrossViewRelation,
    FormalFormula,
    FormalSymbol,
    FormalizationView,
    SymbolTable,
    ViewRegistry,
)
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticReport,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    SourceRef,
    SourceReviewStatus,
    SourceSpan,
)


LEGAL_IR_FORMALIZATION_ADAPTER_VERSION: Final = "legal-ir-formalization-adapter/v1"
LEGAL_IR_DOMAIN: Final = "legal"
LEGAL_IR_ADAPTER_PRODUCER_ID: Final = "legal-ir-formalization-adapter"
LEGAL_IR_ADAPTER_CONFIG_ID: Final = "legal-ir-adapter-default"

_SHARED_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_REVIEWED_STATUSES = frozenset(
    {SourceReviewStatus.HUMAN_REVIEWED, SourceReviewStatus.TRUSTED_FIXTURE}
)
_KNOWN_LEGAL_SAMPLE_FIELDS = frozenset(
    {
        "citation",
        "embedding_model",
        "embedding_vector",
        "frame_candidates",
        "losses",
        "modal_ir",
        "normalized_text",
        "parser_trace",
        "sample_id",
        "section",
        "selected_frame",
        "source",
        "text",
        "title",
    }
)

_DEONTIC_VIEW_ID = "legal-ir-view/deontic/v1"
_FRAME_LOGIC_VIEW_ID = "legal-ir-view/frame-logic/v1"
_TDFOL_VIEW_ID = "legal-ir-view/tdfol/v1"
_CEC_VIEW_ID = "legal-ir-view/cec/v1"


@dataclass(frozen=True, slots=True)
class _LegalViewDescriptor:
    contract_id: str
    view: str
    target_component: str
    logic_family: str
    description: str
    aliases: tuple[str, ...]
    preservation_rules: tuple[str, ...]


# These are versioned public identifiers from legal_ir_view_contracts.  Keeping
# a small v1 descriptor here prevents importing the heavyweight reasoning
# package at adapter-import time.  The adapter conformance test compares every
# entry with the canonical Legal registry, making drift explicit.
_LEGAL_VIEW_DESCRIPTORS: Final = (
    _LegalViewDescriptor(
        _DEONTIC_VIEW_ID,
        "deontic",
        "deontic.ir",
        "deontic",
        "Normative force, polarity, scope, conditions, and defeasible exceptions.",
        ("deontic.ir", "deontic_ir", "deontic_norms"),
        (
            "operator_force",
            "prohibition_polarity",
            "condition_scope",
            "exception_precedence",
        ),
    ),
    _LegalViewDescriptor(
        _FRAME_LOGIC_VIEW_ID,
        "frame_logic",
        "modal.frame_logic",
        "frame_logic",
        "Typed frame roles and relations shared by modal and graph views.",
        ("modal.frame_logic", "modal_frame_logic", "frame-logic"),
        ("typed_role", "relation_direction", "modal_operator", "exception_scope"),
    ),
    _LegalViewDescriptor(
        _TDFOL_VIEW_ID,
        "tdfol",
        "TDFOL.prover",
        "temporal_first_order",
        "Typed first-order temporal formula and explicit time anchors.",
        ("TDFOL.prover", "tdfol_prover", "TDFOL", "temporal"),
        (
            "quantifier_scope",
            "temporal_anchor",
            "event_order",
            "deontic_force",
        ),
    ),
    _LegalViewDescriptor(
        _CEC_VIEW_ID,
        "cec",
        "CEC.native",
        "event_calculus",
        "Event-calculus events, fluents, and lifecycle transitions.",
        ("CEC.native", "cec_native", "event_calculus", "dcec"),
        (
            "event_identity",
            "fluent_identity",
            "transition_direction",
            "time_anchor",
        ),
    ),
    _LegalViewDescriptor(
        "legal-ir-view/knowledge-graphs/v1",
        "knowledge_graphs",
        "knowledge_graphs.neo4j_compat",
        "graph_projection",
        "Neo4j-compatible typed nodes and directed relationships.",
        (
            "knowledge_graphs.neo4j_compat",
            "knowledge_graphs_neo4j_compat",
            "knowledge_graph",
            "neo4j_compat",
        ),
        (
            "endpoint_identity",
            "edge_direction",
            "edge_type",
            "provenance_identity",
        ),
    ),
    _LegalViewDescriptor(
        "legal-ir-view/external-provers/v1",
        "external_provers",
        "external_provers.router",
        "proof_translation",
        "Bounded prover route, backend result, and reconstruction receipt.",
        (
            "external_provers.router",
            "external_provers_router",
            "prover_router",
            "prover",
        ),
        (
            "input_formula_id",
            "modal_operator",
            "type_encoding",
            "route_status",
            "trust_boundary",
        ),
    ),
    _LegalViewDescriptor(
        "legal-ir-view/decompiler/v1",
        "decompiler",
        "modal.ir_decompiler",
        "structural_round_trip",
        "Deterministic structural round trip from typed IR without copied source text.",
        (
            "modal.ir_decompiler",
            "modal.decompiler",
            "ir_decompiler",
            "round_trip",
        ),
        (
            "formula_identity",
            "operator_force",
            "predicate_signature",
            "argument_roles",
            "condition_scope",
            "exception_scope",
        ),
    ),
)


class LegalIRAdapterError(FormalizationValidationError):
    """Raised when a Legal sample cannot be projected without ambiguity."""


def _build_view_registry() -> ViewRegistry:
    views = []
    for descriptor in _LEGAL_VIEW_DESCRIPTORS:
        views.append(
            FormalizationView(
                view_id=descriptor.contract_id,
                logic_family=descriptor.logic_family,
                description=descriptor.description,
                capabilities=descriptor.preservation_rules,
                metadata={
                    "aliases": list(descriptor.aliases),
                    "canonical_legal_view": descriptor.view,
                    "legal_contract_schema": "legal-ir-view-contract-v1",
                    "preservation_rules": list(descriptor.preservation_rules),
                    "target_component": descriptor.target_component,
                },
            )
        )
    return ViewRegistry(views, registry_id="legal-ir-formalization-views")


LEGAL_IR_FORMALIZATION_VIEW_REGISTRY: Final = _build_view_registry()
# Readable compatibility spelling for consumers that already use "view registry".
LEGAL_IR_VIEW_REGISTRY: Final = LEGAL_IR_FORMALIZATION_VIEW_REGISTRY


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise LegalIRAdapterError(f"Legal sample contains non-JSON data: {exc}") from exc


def _digest_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _shared_id(value: Any, *, kind: str) -> str:
    text = str(value or "")
    if _SHARED_ID_RE.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return f"legal-{kind}:{digest}"


def _binding_id(subject_id: str, role: str) -> str:
    digest = hashlib.sha256(f"{role}\0{subject_id}".encode("utf-8")).hexdigest()[:24]
    return f"binding:legal-{role}:{digest}"


def _as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise LegalIRAdapterError(f"{field_name} must be a mapping")


def _as_sequence(value: Any, field_name: str) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return list(value)
    raise LegalIRAdapterError(f"{field_name} must be a sequence")


def _legal_sample_dict(legal_sample: Any) -> dict[str, Any]:
    if isinstance(legal_sample, Mapping):
        result = {str(key): item for key, item in legal_sample.items()}
    else:
        validator = getattr(legal_sample, "validate", None)
        if callable(validator):
            try:
                validator()
            except ValueError as exc:
                raise LegalIRAdapterError(str(exc)) from exc
        serializer = getattr(legal_sample, "to_dict", None)
        if not callable(serializer):
            raise LegalIRAdapterError(
                "legal_sample must be a LegalSample or its persisted mapping"
            )
        result = _as_mapping(serializer(), "LegalSample.to_dict()")

    missing = sorted(
        field
        for field in (
            "citation",
            "modal_ir",
            "normalized_text",
            "sample_id",
            "section",
            "source",
            "text",
            "title",
        )
        if field not in result
    )
    if missing:
        raise LegalIRAdapterError(
            "Legal sample is missing required field(s): " + ", ".join(missing)
        )
    if result.get("source") != "us_code":
        raise LegalIRAdapterError("Legal sample source must be 'us_code'")
    for field in (
        "citation",
        "normalized_text",
        "sample_id",
        "section",
        "text",
        "title",
    ):
        if not isinstance(result.get(field), str) or not result[field]:
            raise LegalIRAdapterError(f"Legal sample {field} must be a non-empty string")
    modal = _as_mapping(result["modal_ir"], "modal_ir")
    if modal.get("normalized_text") != result["normalized_text"]:
        raise LegalIRAdapterError(
            "modal_ir.normalized_text must match Legal sample normalized_text"
        )
    if modal.get("source") != result["source"]:
        raise LegalIRAdapterError("modal_ir.source must match Legal sample source")
    if not isinstance(modal.get("document_id"), str) or not modal["document_id"]:
        raise LegalIRAdapterError("modal_ir.document_id must be a non-empty string")
    _as_sequence(modal.get("formulas", ()), "modal_ir.formulas")
    return result


def _externalized_field(
    field_path: str,
    value: Any,
    disposition: str,
    reason: str,
) -> dict[str, str]:
    return {
        "content_digest": f"sha256:{_digest_value(value)}",
        "disposition": disposition,
        "field_path": field_path,
        "reason": reason,
    }


def _unsupported_field_manifest(data: Mapping[str, Any]) -> list[dict[str, str]]:
    fields = [
        _externalized_field(
            "/text",
            data["text"],
            "externalized_source_body",
            "raw statutory text is represented by the shared SourceRef",
        ),
        _externalized_field(
            "/normalized_text",
            data["normalized_text"],
            "externalized_source_body",
            "normalized statutory text is not a formal declaration feature",
        ),
        _externalized_field(
            "/modal_ir/normalized_text",
            data["modal_ir"].get("normalized_text"),
            "externalized_source_body",
            "the legacy modal document's source copy is content-bound, not embedded",
        ),
        _externalized_field(
            "/embedding_model",
            data.get("embedding_model"),
            "unsupported_training_feature",
            "Legal embedding configuration is outside shared formal semantics",
        ),
        _externalized_field(
            "/embedding_vector",
            data.get("embedding_vector", []),
            "unsupported_training_feature",
            "source-derived embedding values are not declaration semantics",
        ),
        _externalized_field(
            "/parser_trace",
            data.get("parser_trace", {}),
            "unsupported_producer_trace",
            "the Legal parser trace is not a formal view",
        ),
        _externalized_field(
            "/losses",
            data.get("losses", {}),
            "unsupported_runtime_result",
            "training losses cannot become declaration features",
        ),
    ]
    if data["text"] != data["normalized_text"]:
        fields.append(
            _externalized_field(
                "/modal_ir/formulas/*/provenance",
                [
                    item.get("provenance")
                    for item in data["modal_ir"].get("formulas", ())
                    if isinstance(item, Mapping)
                ],
                "unsupported_coordinate_alignment",
                "legacy formula offsets address normalized text; the shared "
                "raw-source span is conservatively widened to the whole source",
            )
        )
    for name in sorted(set(data) - _KNOWN_LEGAL_SAMPLE_FIELDS):
        fields.append(
            _externalized_field(
                f"/{name}",
                data[name],
                "unsupported_legal_extension",
                "the persisted Legal field has no reviewed shared-contract mapping",
            )
        )
    return fields


def _modal_semantics(modal: Mapping[str, Any]) -> dict[str, Any]:
    """Return all Legal modal semantics while excluding the source-body copy."""

    return {
        key: value
        for key, value in modal.items()
        if key != "normalized_text"
    }


def _char_to_byte(text: str, offset: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise LegalIRAdapterError("Legal formula character offsets must be integers")
    if offset < 0 or offset > len(text):
        raise LegalIRAdapterError(
            f"Legal formula character offset {offset} is outside source text"
        )
    return len(text[:offset].encode("utf-8"))


def _view_for_family(family: Any) -> tuple[str, bool]:
    normalized = str(family or "").strip().lower()
    if normalized in {"deontic", "conditional_normative"}:
        return _DEONTIC_VIEW_ID, False
    if normalized in {"temporal", "temporal_first_order", "tdfol"}:
        # A modal temporal formula is retained but is not falsely advertised as
        # an already typed TDFOL lowering.
        return _TDFOL_VIEW_ID, True
    if normalized in {"event", "event_calculus", "dynamic"}:
        return _CEC_VIEW_ID, True
    return _DEONTIC_VIEW_ID, True


def _legacy_identity(data: Mapping[str, Any]) -> str:
    modal = _as_mapping(data["modal_ir"], "modal_ir")
    return hashlib.sha256(_canonical_json(modal).encode("utf-8")).hexdigest()


def _source_span_ids(
    sample: FormalizationSample,
) -> tuple[str, str]:
    source_id = sample.source_ref_ids[0]
    whole_span = next(
        (
            span.span_id
            for span in sample.provenance.spans
            if span.source_ref_id == source_id
            and span.metadata.get("scope") == "legal_document"
        ),
        sample.span_ids[0],
    )
    return source_id, whole_span


def _deontic_projection(
    legacy_formula: Mapping[str, Any],
    *,
    source_ref_id: str,
    span_id: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    operator = _as_mapping(legacy_formula.get("operator", {}), "formula.operator")
    predicate = _as_mapping(legacy_formula.get("predicate", {}), "formula.predicate")
    arguments = _as_sequence(
        predicate.get("arguments", ()), "formula.predicate.arguments"
    )
    symbol = str(operator.get("symbol") or "")
    label = str(operator.get("label") or "").lower()
    force = {
        "o": "obligation",
        "o|": "obligation",
        "p": "permission",
        "f": "prohibition",
    }.get(symbol.lower())
    if force is None:
        if "prohibit" in label:
            force = "prohibition"
        elif "permission" in label:
            force = "permission"
        elif "obligation" in label:
            force = "obligation"

    unsupported: list[str] = []
    if force is None:
        unsupported.append("operator has no reviewed deontic force mapping")
        force = "obligation"
    if not arguments or not str(arguments[0]):
        unsupported.append("predicate has no typed actor argument")
    if len(arguments) < 2:
        unsupported.append("predicate has no typed governed-object argument")
    if not predicate.get("name"):
        unsupported.append("predicate has no governed action name")
    actor = str(arguments[0]) if arguments else "unresolved_actor"
    governed_object: Any
    if len(arguments) == 2:
        governed_object = arguments[1]
    elif len(arguments) > 2:
        governed_object = {"arguments": arguments[1:]}
    else:
        governed_object = {"arguments": []}
    expression = {
        "action": str(predicate.get("name") or "unresolved_action"),
        "actor": actor,
        "conditions": list(legacy_formula.get("conditions") or ()),
        "exceptions": list(legacy_formula.get("exceptions") or ()),
        "formula_id": str(legacy_formula.get("formula_id") or ""),
        "legal_modal_ir": dict(legacy_formula),
        "norm_type": force,
        "object": governed_object,
        "operator": {"obligation": "O", "permission": "P", "prohibition": "F"}[force],
        "polarity": "negative" if force == "prohibition" else "positive",
        "provenance_ids": [source_ref_id, span_id],
    }
    return expression, tuple(unsupported)


def _symbol_specs(
    legacy_formula: Mapping[str, Any],
    shared_formula_id: str,
) -> list[tuple[str, str, str, str, dict[str, Any]]]:
    operator = _as_mapping(legacy_formula.get("operator", {}), "formula.operator")
    predicate = _as_mapping(legacy_formula.get("predicate", {}), "formula.predicate")
    result: list[tuple[str, str, str, str, dict[str, Any]]] = []
    if operator.get("symbol"):
        result.append(
            (
                _shared_id(f"{shared_formula_id}:operator", kind="symbol"),
                str(operator["symbol"]),
                "operator",
                str(operator.get("family") or "modal"),
                {"legal_operator": operator},
            )
        )
    if predicate.get("name"):
        result.append(
            (
                _shared_id(f"{shared_formula_id}:predicate", kind="symbol"),
                str(predicate["name"]),
                "predicate",
                str(predicate.get("role") or "legal_clause"),
                {"legal_predicate": predicate},
            )
        )
    for index, argument in enumerate(predicate.get("arguments") or ()):
        result.append(
            (
                _shared_id(
                    f"{shared_formula_id}:argument:{index}", kind="symbol"
                ),
                str(argument),
                "constant",
                "legal_argument",
                {"argument_index": index},
            )
        )
    return result


@dataclass(frozen=True, slots=True)
class LegalIRFormalizationAdapter:
    """Project reviewed Legal samples into shared sample and view contracts."""

    source_review_status: SourceReviewStatus = SourceReviewStatus.TRUSTED_FIXTURE
    license_expression: str = ""
    producer_id: str = LEGAL_IR_ADAPTER_PRODUCER_ID
    producer_version: str = LEGAL_IR_FORMALIZATION_ADAPTER_VERSION

    def __post_init__(self) -> None:
        try:
            status = (
                self.source_review_status
                if isinstance(self.source_review_status, SourceReviewStatus)
                else SourceReviewStatus(self.source_review_status)
            )
        except (TypeError, ValueError) as exc:
            raise LegalIRAdapterError(
                f"unknown Legal source review status: {self.source_review_status!r}"
            ) from exc
        object.__setattr__(self, "source_review_status", status)
        if status not in _REVIEWED_STATUSES:
            raise LegalIRAdapterError(
                "Legal formalization requires a human-reviewed or trusted-fixture source"
            )
        if not _SHARED_ID_RE.fullmatch(self.producer_id):
            raise LegalIRAdapterError("producer_id must be a stable shared identifier")

    @property
    def view_registry(self) -> ViewRegistry:
        return LEGAL_IR_FORMALIZATION_VIEW_REGISTRY

    @property
    def view_aliases(self) -> dict[str, tuple[str, ...]]:
        return {
            descriptor.contract_id: (
                descriptor.view,
                descriptor.target_component,
                *descriptor.aliases,
            )
            for descriptor in _LEGAL_VIEW_DESCRIPTORS
        }

    def existing_output_identity(self, legal_sample: Any) -> str:
        """Return the unchanged legacy ``ModalIRDocument`` SHA-256 hex hash."""

        return _legacy_identity(_legal_sample_dict(legal_sample))

    # Compatibility spelling used by migration and artifact code.
    legacy_output_identity = existing_output_identity

    def adapt_sample(self, legal_sample: Any) -> FormalizationSample:
        """Adapt a Legal sample without copying source/training result fields."""

        data = _legal_sample_dict(legal_sample)
        modal = _as_mapping(data["modal_ir"], "modal_ir")
        legacy_identity = _legacy_identity(data)
        sample_id = _shared_id(data["sample_id"], kind="sample")
        declaration_id = _shared_id(modal["document_id"], kind="document")
        source_ref_id = _shared_id(f"source:{sample_id}", kind="source")
        whole_span_id = _shared_id(f"span:{sample_id}:document", kind="span")
        text = data["text"]

        formula_aliases: dict[str, str] = {}
        spans = [
            SourceSpan(
                span_id=whole_span_id,
                source_ref_id=source_ref_id,
                start_byte=0,
                end_byte=len(text.encode("utf-8")),
                start_char=0,
                end_char=len(text),
                metadata={"scope": "legal_document"},
            )
        ]
        for index, item in enumerate(modal.get("formulas") or ()):
            formula = _as_mapping(item, f"modal_ir.formulas[{index}]")
            legacy_formula_id = str(formula.get("formula_id") or "")
            if not legacy_formula_id:
                raise LegalIRAdapterError(
                    f"modal_ir.formulas[{index}].formula_id must not be empty"
                )
            shared_formula_id = _shared_id(legacy_formula_id, kind="formula")
            if shared_formula_id in formula_aliases:
                raise LegalIRAdapterError("Legal modal formula IDs must be unique")
            formula_aliases[shared_formula_id] = legacy_formula_id
            provenance = _as_mapping(
                formula.get("provenance", {}),
                f"modal_ir.formulas[{index}].provenance",
            )
            if provenance.get("source_id") not in {
                data["sample_id"],
                modal["document_id"],
            }:
                raise LegalIRAdapterError(
                    f"formula {legacy_formula_id!r} provenance source_id "
                    "does not identify the Legal sample or modal document"
                )
            start_char = provenance.get("start_char")
            end_char = provenance.get("end_char")
            # ModalIR offsets address ``normalized_text``.  When normalization
            # changed the source, inventing exact raw offsets would be worse
            # than a conservative, explicitly diagnosed whole-source span.
            _char_to_byte(data["normalized_text"], start_char)
            _char_to_byte(data["normalized_text"], end_char)
            exact_raw_alignment = text == data["normalized_text"]
            if exact_raw_alignment:
                shared_start_char = start_char
                shared_end_char = end_char
                start_byte = _char_to_byte(text, start_char)
                end_byte = _char_to_byte(text, end_char)
            else:
                shared_start_char = 0
                shared_end_char = len(text)
                start_byte = 0
                end_byte = len(text.encode("utf-8"))
            if end_byte <= start_byte:
                raise LegalIRAdapterError(
                    f"formula {legacy_formula_id!r} has an empty or reversed span"
                )
            spans.append(
                SourceSpan(
                    span_id=_shared_id(
                        f"span:{shared_formula_id}", kind="formula-span"
                    ),
                    source_ref_id=source_ref_id,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    start_char=shared_start_char,
                    end_char=shared_end_char,
                    metadata={
                        "citation": provenance.get("citation") or data["citation"],
                        "coordinate_alignment": (
                            "exact" if exact_raw_alignment else "whole_source"
                        ),
                        "legacy_formula_id": legacy_formula_id,
                        "normalized_end_char": end_char,
                        "normalized_start_char": start_char,
                    },
                )
            )

        semantic_payload = {
            "adapter_schema_version": LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
            "id_aliases": {
                "declaration_id": modal["document_id"],
                "formula_ids": formula_aliases,
                "sample_id": data["sample_id"],
            },
            "legacy_output_identity": {
                "algorithm": "sha256",
                "hexdigest": legacy_identity,
                "identity_contract": "ModalIRDocument.canonical_hash",
            },
            "legal_document": {
                "citation": data["citation"],
                "frame_candidates": list(data.get("frame_candidates") or ()),
                "modal_ir": _modal_semantics(modal),
                "section": data["section"],
                "selected_frame": data.get("selected_frame"),
                "source": data["source"],
                "title": data["title"],
            },
            "unsupported_fields": _unsupported_field_manifest(data),
            "view_aliases": {
                key: list(values) for key, values in self.view_aliases.items()
            },
        }
        source = SourceRef(
            ref_id=source_ref_id,
            source_uri=(
                "urn:legal-ir:us-code:"
                f"{quote(str(data['title']), safe='')}:"
                f"{quote(str(data['section']), safe='')}:"
                f"{quote(str(data['sample_id']), safe='')}"
            ),
            source_id=data["sample_id"],
            source_revision=str(modal.get("version") or "modal-ir-v1"),
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            license_expression=self.license_expression,
            review_status=self.source_review_status,
            metadata={
                "citation": data["citation"],
                "legal_source": "us_code",
                "normalized_text_sha256": hashlib.sha256(
                    data["normalized_text"].encode("utf-8")
                ).hexdigest(),
            },
        )
        subjects = tuple(dict.fromkeys((sample_id, declaration_id)))
        provenance = Provenance(
            provenance_id=_shared_id(
                f"provenance:{sample_id}", kind="provenance"
            ),
            sources=(source,),
            spans=tuple(spans),
            bindings=tuple(
                ProvenanceBinding(
                    binding_id=_binding_id(subject, "source"),
                    subject_id=subject,
                    source_ref_ids=(source_ref_id,),
                    span_ids=(whole_span_id,),
                    metadata={
                        "legacy_declaration_id": modal["document_id"],
                        "legacy_sample_id": data["sample_id"],
                    },
                )
                for subject in subjects
            ),
            metadata={
                "adapter_schema_version": LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
                "legacy_output_identity": legacy_identity,
            },
        )
        return FormalizationSample(
            sample_id=sample_id,
            domain=LEGAL_IR_DOMAIN,
            declaration_id=declaration_id,
            declaration_digest=f"sha256:{legacy_identity}",
            payload=semantic_payload,
            provenance=provenance,
            source_ref_ids=(source_ref_id,),
            span_ids=tuple(span.span_id for span in spans),
            tags=("legal", "reviewed", "us_code"),
            metadata={
                "legacy_modal_ir_canonical_hash": legacy_identity,
                "legacy_output_identity": legacy_identity,
                "legacy_sample_id": data["sample_id"],
            },
        )

    # Common migration spelling.
    to_formalization_sample = adapt_sample

    def default_config(
        self, sample_or_legal_sample: FormalizationSample | Any
    ) -> FormalizationCompilerConfig:
        sample = (
            sample_or_legal_sample
            if isinstance(sample_or_legal_sample, FormalizationSample)
            else self.adapt_sample(sample_or_legal_sample)
        )
        payload = sample.payload.to_dict()
        legal_document = _as_mapping(payload.get("legal_document"), "legal_document")
        modal = _as_mapping(legal_document.get("modal_ir"), "legal_document.modal_ir")
        targets = set()
        for item in modal.get("formulas") or ():
            formula = _as_mapping(item, "modal formula")
            operator = _as_mapping(
                formula.get("operator", {}), "modal formula operator"
            )
            targets.add(_view_for_family(operator.get("family"))[0])
        frame_logic = _as_mapping(
            modal.get("frame_logic", {}), "legal_document.modal_ir.frame_logic"
        )
        if frame_logic.get("triples"):
            targets.add(_FRAME_LOGIC_VIEW_ID)
        if not targets:
            targets.add(_DEONTIC_VIEW_ID)
        return FormalizationCompilerConfig(
            compiler_id=self.producer_id,
            compiler_version=self.producer_version,
            target_view_ids=tuple(targets),
            config_id=LEGAL_IR_ADAPTER_CONFIG_ID,
            producer_id=self.producer_id,
            unsupported_policy=UnsupportedSemanticsPolicy.PRESERVE_OPAQUE,
            options={
                "adapter_schema_version": LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
                "legacy_identity_contract": "ModalIRDocument.canonical_hash",
            },
        )

    def compile(
        self,
        sample: FormalizationSample,
        config: FormalizationCompilerConfig,
    ) -> FormalizationArtifact:
        """Compile an adapted Legal sample without invoking any proof backend."""

        if not isinstance(sample, FormalizationSample) or sample.domain != LEGAL_IR_DOMAIN:
            raise LegalIRAdapterError(
                "LegalIRFormalizationAdapter.compile requires a Legal FormalizationSample"
            )
        payload = sample.payload.to_dict()
        if payload.get("adapter_schema_version") != LEGAL_IR_FORMALIZATION_ADAPTER_VERSION:
            raise LegalIRAdapterError("sample was not produced by this Legal adapter schema")
        unknown_views = set(config.target_view_ids) - set(self.view_registry.view_ids)
        if unknown_views:
            raise LegalIRAdapterError(
                "Legal compiler targets unknown views: "
                + ", ".join(sorted(unknown_views))
            )

        legal_document = _as_mapping(payload["legal_document"], "legal_document")
        modal = _as_mapping(legal_document["modal_ir"], "legal_document.modal_ir")
        aliases = _as_mapping(payload["id_aliases"], "id_aliases")
        formula_aliases = _as_mapping(aliases["formula_ids"], "id_aliases.formula_ids")
        source_ref_id, whole_span_id = _source_span_ids(sample)
        span_by_legacy_formula = {
            str(span.metadata.get("legacy_formula_id")): span.span_id
            for span in sample.provenance.spans
            if span.metadata.get("legacy_formula_id")
        }
        severity = (
            DiagnosticSeverity.ERROR
            if config.strict_unsupported
            else DiagnosticSeverity.WARNING
        )

        formulas: list[FormalFormula] = []
        symbols: list[FormalSymbol] = []
        diagnostics: list[Diagnostic] = []
        bindings = list(sample.provenance.bindings)
        binding_producer_id = config.producer_id or self.producer_id
        legacy_to_shared = {
            str(legacy): str(shared) for shared, legacy in formula_aliases.items()
        }

        for index, raw_formula in enumerate(modal.get("formulas") or ()):
            legacy_formula = _as_mapping(
                raw_formula, f"legal_document.modal_ir.formulas[{index}]"
            )
            legacy_formula_id = str(legacy_formula.get("formula_id") or "")
            shared_formula_id = legacy_to_shared.get(legacy_formula_id)
            if shared_formula_id is None:
                raise LegalIRAdapterError(
                    f"missing shared ID alias for Legal formula {legacy_formula_id!r}"
                )
            span_id = span_by_legacy_formula.get(legacy_formula_id, whole_span_id)
            operator = _as_mapping(
                legacy_formula.get("operator", {}), "formula.operator"
            )
            preferred_view, inherently_opaque = _view_for_family(
                operator.get("family")
            )
            target_view = preferred_view
            reasons: list[str] = []
            if inherently_opaque:
                reasons.append(
                    f"Legal logic family {operator.get('family')!r} requires "
                    "opaque retention pending a reviewed lowering"
                )
            if target_view not in config.target_view_ids:
                target_view = config.target_view_ids[0]
                inherently_opaque = True
                reasons.append(
                    f"preferred Legal view {preferred_view!r} was not requested"
                )

            if preferred_view == _DEONTIC_VIEW_ID:
                expression, projection_reasons = _deontic_projection(
                    legacy_formula,
                    source_ref_id=source_ref_id,
                    span_id=span_id,
                )
                reasons.extend(projection_reasons)
            else:
                expression = {
                    "formula_id": legacy_formula_id,
                    "legal_modal_ir": legacy_formula,
                    "provenance_ids": [source_ref_id, span_id],
                    "unlowered_logic_family": operator.get("family"),
                }
                reasons.append(
                    "legacy modal semantics have no faithful typed lowering in "
                    f"{preferred_view}"
                )

            formula_symbol_ids = []
            for symbol_id, name, kind, sort, metadata in _symbol_specs(
                legacy_formula, shared_formula_id
            ):
                symbols.append(
                    FormalSymbol(
                        symbol_id=symbol_id,
                        name=name,
                        kind=kind,
                        sort=_shared_id(sort, kind="sort"),
                        source_ref_ids=(source_ref_id,),
                        span_ids=(span_id,),
                        metadata=metadata,
                    )
                )
                formula_symbol_ids.append(symbol_id)
                bindings.append(
                    ProvenanceBinding(
                        binding_id=_binding_id(symbol_id, "symbol"),
                        subject_id=symbol_id,
                        source_ref_ids=(source_ref_id,),
                        span_ids=(span_id,),
                        producer_id=binding_producer_id,
                        config_id=config.config_id,
                        parent_subject_ids=(sample.declaration_id,),
                        derived=True,
                    )
                )

            opaque = inherently_opaque or bool(reasons)
            formulas.append(
                FormalFormula(
                    formula_id=shared_formula_id,
                    view_id=target_view,
                    expression=expression,
                    symbol_ids=tuple(formula_symbol_ids),
                    source_ref_ids=(source_ref_id,),
                    span_ids=(span_id,),
                    input_node_ids=(sample.declaration_id,),
                    opaque=opaque,
                    metadata={
                        "legal_contract_aliases": list(
                            self.view_aliases[target_view]
                        ),
                        "legacy_formula_id": legacy_formula_id,
                        "legacy_logic_family": operator.get("family"),
                        "preferred_view_id": preferred_view,
                    },
                )
            )
            bindings.append(
                ProvenanceBinding(
                    binding_id=_binding_id(shared_formula_id, "formula"),
                    subject_id=shared_formula_id,
                    source_ref_ids=(source_ref_id,),
                    span_ids=(span_id,),
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    parent_subject_ids=(sample.declaration_id,),
                    derived=True,
                    metadata={"legacy_formula_id": legacy_formula_id},
                )
            )
            if opaque:
                diagnostics.append(
                    self._unsupported_diagnostic(
                        subject_id=shared_formula_id,
                        source_ref_id=source_ref_id,
                        span_id=span_id,
                        field_path=f"/modal_ir/formulas/{index}",
                        reason="; ".join(dict.fromkeys(reasons)),
                        severity=severity,
                        config=config,
                        view_id=target_view,
                        opaque_formula_id=shared_formula_id,
                    )
                )

        frame_formula_ids: list[str] = []
        frame_logic = _as_mapping(modal.get("frame_logic", {}), "modal_ir.frame_logic")
        for index, raw_triple in enumerate(frame_logic.get("triples") or ()):
            triple = _as_mapping(raw_triple, f"frame_logic.triples[{index}]")
            frame_formula_id = _shared_id(
                f"{sample.declaration_id}:frame:{index}", kind="frame-formula"
            )
            target_view = _FRAME_LOGIC_VIEW_ID
            frame_reasons = [
                f"frame-logic triple has no {field}"
                for field in ("subject", "predicate", "object")
                if not triple.get(field)
            ]
            opaque = target_view not in config.target_view_ids or bool(frame_reasons)
            if opaque:
                if target_view not in config.target_view_ids:
                    target_view = config.target_view_ids[0]
                    frame_reasons.append(
                        "frame-logic view was not requested by compiler config"
                    )
            expression = {
                "formula_id": frame_formula_id,
                "frame_id": (
                    frame_logic.get("selected_frame")
                    or legal_document.get("selected_frame")
                    or "unselected_frame"
                ),
                "legal_frame_logic": frame_logic,
                "object": triple.get("object"),
                "predicate": triple.get("predicate"),
                "provenance_ids": [source_ref_id, whole_span_id],
                "role": str(triple.get("predicate") or "relation"),
                "subject": triple.get("subject"),
            }
            formulas.append(
                FormalFormula(
                    formula_id=frame_formula_id,
                    view_id=target_view,
                    expression=expression,
                    source_ref_ids=(source_ref_id,),
                    span_ids=(whole_span_id,),
                    input_node_ids=(sample.declaration_id,),
                    opaque=opaque,
                    metadata={
                        "legal_contract_aliases": list(
                            self.view_aliases[target_view]
                        ),
                        "preferred_view_id": _FRAME_LOGIC_VIEW_ID,
                    },
                )
            )
            frame_formula_ids.append(frame_formula_id)
            bindings.append(
                ProvenanceBinding(
                    binding_id=_binding_id(frame_formula_id, "frame"),
                    subject_id=frame_formula_id,
                    source_ref_ids=(source_ref_id,),
                    span_ids=(whole_span_id,),
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    parent_subject_ids=(sample.declaration_id,),
                    derived=True,
                )
            )
            if opaque:
                diagnostics.append(
                    self._unsupported_diagnostic(
                        subject_id=frame_formula_id,
                        source_ref_id=source_ref_id,
                        span_id=whole_span_id,
                        field_path=f"/modal_ir/frame_logic/triples/{index}",
                        reason="; ".join(frame_reasons),
                        severity=severity,
                        config=config,
                        view_id=target_view,
                        opaque_formula_id=frame_formula_id,
                    )
                )

        for unsupported in payload.get("unsupported_fields") or ():
            item = _as_mapping(unsupported, "unsupported_fields item")
            diagnostics.append(
                self._unsupported_diagnostic(
                    subject_id=sample.declaration_id,
                    source_ref_id=source_ref_id,
                    span_id=whole_span_id,
                    field_path=str(item.get("field_path") or "/"),
                    reason=(
                        f"{item.get('field_path')}: {item.get('reason')} "
                        f"({item.get('disposition')})"
                    ),
                    severity=severity,
                    config=config,
                    metadata={
                        "content_digest": item.get("content_digest"),
                        "disposition": item.get("disposition"),
                    },
                )
            )

        if not formulas:
            diagnostics.append(
                self._unsupported_diagnostic(
                    subject_id=sample.declaration_id,
                    source_ref_id=source_ref_id,
                    span_id=whole_span_id,
                    field_path="/modal_ir/formulas",
                    reason="Legal modal document contains no formal formulas",
                    severity=severity,
                    config=config,
                    view_id=config.target_view_ids[0],
                )
            )

        emitted_views = {formula.view_id for formula in formulas}
        for view_id in sorted(set(config.target_view_ids) - emitted_views):
            if any(
                item.metadata.get("view_id") == view_id
                for item in diagnostics
            ):
                continue
            diagnostics.append(
                self._unsupported_diagnostic(
                    subject_id=sample.declaration_id,
                    source_ref_id=source_ref_id,
                    span_id=whole_span_id,
                    field_path="/compiler_config/target_view_ids",
                    reason=f"Legal sample emits no formula for requested view {view_id}",
                    severity=severity,
                    config=config,
                    view_id=view_id,
                )
            )

        cross_view_links = [
            CrossViewLink(
                link_id=_shared_id(
                    f"link:{formula.formula_id}:{frame_id}", kind="cross-view-link"
                ),
                source_formula_id=formula.formula_id,
                target_formula_id=frame_id,
                relation=CrossViewRelation.CORRESPONDS_TO,
                preserved_properties=(
                    "legal_source_identity",
                    "provenance",
                    "selected_frame",
                ),
                source_ref_ids=(source_ref_id,),
                span_ids=formula.span_ids,
            )
            for formula in formulas
            if formula.formula_id not in frame_formula_ids
            for frame_id in frame_formula_ids
            if formula.view_id
            != next(
                item.view_id for item in formulas if item.formula_id == frame_id
            )
        ]

        producer = ProducerBinding(
            producer_id=binding_producer_id,
            name="Legal IR shared-formalization adapter",
            version=config.compiler_version,
            metadata={"compiler_id": config.compiler_id},
        )
        config_binding = ConfigBinding(
            config_id=config.config_id,
            content_sha256=config.identity.hexdigest,
            schema_id=config.schema_version,
        )
        source_map = Provenance(
            provenance_id=sample.provenance.provenance_id,
            sources=sample.provenance.sources,
            spans=sample.provenance.spans,
            producers=tuple(
                {
                    item.producer_id: item
                    for item in (*sample.provenance.producers, producer)
                }.values()
            ),
            configs=tuple(
                {
                    item.config_id: item
                    for item in (*sample.provenance.configs, config_binding)
                }.values()
            ),
            bindings=tuple(bindings),
            metadata=sample.provenance.metadata,
        )
        report = DiagnosticReport(
            report_id=_shared_id(
                f"diagnostics:{sample.sample_id}:{config.digest[7:23]}",
                kind="diagnostics",
            ),
            diagnostics=tuple(
                sorted(diagnostics, key=lambda item: item.diagnostic_id)
            ),
            provenance_id=source_map.provenance_id,
            # A generic config may omit ``producer_id``.  The diagnostic
            # remains attributable to this adapter without mutating config
            # identity.
            producer_id=binding_producer_id,
            config_id=config.config_id,
            metadata={
                "adapter_schema_version": LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
                "unsupported_field_count": len(
                    payload.get("unsupported_fields") or ()
                ),
            },
        )
        legacy_identity = _as_mapping(
            payload["legacy_output_identity"], "legacy_output_identity"
        )["hexdigest"]
        return FormalizationArtifact.from_sample(
            sample,
            compiler_config=config,
            view_registry=self.view_registry,
            symbol_table=SymbolTable(
                table_id=_shared_id(
                    f"symbols:{sample.declaration_id}", kind="symbol-table"
                ),
                symbols=tuple(symbols),
                metadata={"domain": LEGAL_IR_DOMAIN},
            ),
            formulas=tuple(formulas),
            cross_view_links=tuple(cross_view_links),
            source_map=source_map,
            diagnostics=report,
            metadata={
                "adapter_schema_version": LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
                "legacy_modal_ir_canonical_hash": legacy_identity,
                "legacy_output_identity": legacy_identity,
                "view_aliases": {
                    key: list(values) for key, values in self.view_aliases.items()
                },
            },
        )

    def adapt_artifact(
        self,
        legal_sample: Any,
        config: FormalizationCompilerConfig | None = None,
    ) -> FormalizationArtifact:
        sample = self.adapt_sample(legal_sample)
        return self.compile(sample, config or self.default_config(sample))

    # The complete adaptation is the artifact; ``adapt_sample`` remains
    # available to source-only consumers.
    adapt = adapt_artifact

    def _unsupported_diagnostic(
        self,
        *,
        subject_id: str,
        source_ref_id: str,
        span_id: str,
        field_path: str,
        reason: str,
        severity: DiagnosticSeverity,
        config: FormalizationCompilerConfig,
        view_id: str = "",
        opaque_formula_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> Diagnostic:
        detail = dict(metadata or {})
        detail.update(
            {
                "adapter_schema_version": LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
                "construct_id": subject_id,
                "field_path": field_path,
                "opaque_formula_id": opaque_formula_id,
                "view_id": view_id,
            }
        )
        return Diagnostic(
            code=DiagnosticCode.UNSUPPORTED_FEATURE,
            message=reason,
            severity=severity,
            location=DiagnosticLocation(
                subject_ids=(subject_id,),
                source_ref_ids=(source_ref_id,),
                span_ids=(span_id,),
                field_path=field_path,
            ),
            producer_id=config.producer_id or self.producer_id,
            config_id=config.config_id,
            metadata=detail,
        )


# Short name used by the architecture objective and migration call sites.
LegalIRAdapter = LegalIRFormalizationAdapter


def adapt_legal_sample(
    legal_sample: Any,
    *,
    config: FormalizationCompilerConfig | None = None,
    source_review_status: SourceReviewStatus = SourceReviewStatus.TRUSTED_FIXTURE,
    license_expression: str = "",
) -> FormalizationArtifact:
    """Functional convenience wrapper around :class:`LegalIRFormalizationAdapter`."""

    return LegalIRFormalizationAdapter(
        source_review_status=source_review_status,
        license_expression=license_expression,
    ).adapt_artifact(legal_sample, config=config)


__all__ = [
    "LEGAL_IR_ADAPTER_CONFIG_ID",
    "LEGAL_IR_ADAPTER_PRODUCER_ID",
    "LEGAL_IR_DOMAIN",
    "LEGAL_IR_FORMALIZATION_ADAPTER_VERSION",
    "LEGAL_IR_FORMALIZATION_VIEW_REGISTRY",
    "LEGAL_IR_VIEW_REGISTRY",
    "LegalIRAdapter",
    "LegalIRAdapterError",
    "LegalIRFormalizationAdapter",
    "adapt_legal_sample",
]
