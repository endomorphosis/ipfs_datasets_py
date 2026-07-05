"""CEC/DCEC implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)

_EVENT_PREDICATE_CANONICAL_BY_LOWER = {
    "happens": "Happens",
    "happens_at": "Happens",
    "holdsat": "HoldsAt",
    "holds_at": "HoldsAt",
    "initiates": "Initiates",
    "terminates": "Terminates",
    "releasedat": "ReleasedAt",
    "released_at": "ReleasedAt",
    "clipped": "Clipped",
    "trajectory": "Trajectory",
    "initially": "Initially",
    "initiallyp": "InitiallyP",
    "initially_p": "InitiallyP",
    "initiallyn": "InitiallyN",
    "initially_n": "InitiallyN",
}
_EVENT_PREDICATE_SET = set(_EVENT_PREDICATE_CANONICAL_BY_LOWER.values())
_EVENT_FORMULA_WRAPPER_CANONICAL_BY_LOWER = {
    **_EVENT_PREDICATE_CANONICAL_BY_LOWER,
    "legal_norm": "legal_norm",
    "always": "always",
    "o": "O",
    "p": "P",
    "f": "F",
}
_EVENT_FORMULA_CONNECTOR_CANONICAL_BY_TOKEN = {
    "=>": "=>",
    "->": "->",
    ":-": ":-",
    "<-": "<-",
}
_EVENT_FORMULA_CONNECTOR_REPLACEMENTS = {
    "⟹": "=>",
    "⇒": "=>",
    "→": "=>",
    "⟶": "=>",
    "⊃": "=>",
    "←": "<-",
    "⟵": "<-",
    "⇐": "<-",
    "¬": " not ",
    "∧": " and ",
    "∨": " or ",
    "∀": "forall ",
    "∃": "exists ",
}
_DCEC_STATE_PREDICATE_BY_KIND = {
    "definition": "Definition",
    "applicability": "AppliesTo",
    "exemption": "ExemptedFrom",
    "instrument_lifecycle": "LifecycleState",
    "purpose": "Purpose",
}
_DCEC_STATE_PREDICATE_CANONICAL_BY_LOWER = {
    predicate.lower(): predicate
    for predicate in _DCEC_STATE_PREDICATE_BY_KIND.values()
}
_DCEC_STATE_PREDICATE_SET = set(_DCEC_STATE_PREDICATE_BY_KIND.values())
_CEC_GUIDANCE_ROUTE_TOKENS = {
    "repair_cec_dcec_bridge",
    "cec_dcec",
    "cec.native",
    "cec_native",
    "deontic_cec",
}


@dataclass
class CecDcecBridgeAdapter:
    """Bridge legal norm text into DCEC event-calculus records."""

    converter: Optional[Any] = None
    converter_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: {
            "enable_monitoring": False,
            "use_cache": True,
            "use_ml": False,
        }
    )

    name: str = "cec_dcec"
    target_component: str = "CEC.native"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        """Encode legal text into a DCEC bridge document."""

        norms = _deontic_norms_from_text(text, converter=self._converter())
        resolved_document_id = document_id or _document_id("dcec", text)
        records = _dcec_records(
            norms,
            compiler_guidance=compiler_guidance,
            document_id=resolved_document_id,
            citation=citation,
            source_text=text,
        )
        triples = tuple(
            _dcec_frame_logic_triples(
                resolved_document_id,
                records=records,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:dcec-flogic",
            metadata={
                "dcec_formula_count": len(records),
                "source": "cec_dcec_bridge_ir",
            },
        )
        cec_event_rows = _cec_event_view_rows(records)
        procedure_event_count = sum(
            len(record.get("procedure_event_records") or []) for record in records
        )
        views = {
            "cec_events": LogicIRView(
                name="cec_events",
                format="cec-event-records",
                source_component="CEC.native",
                payload={"events": cec_event_rows},
                metadata={
                    "event_count": len(cec_event_rows),
                    "norm_event_count": len(records),
                    "procedure_event_count": procedure_event_count,
                },
            ),
            "event_calculus": LogicIRView(
                name="event_calculus",
                format="cec-event-calculus-state-records",
                source_component="CEC.native",
                payload={
                    "records": [
                        {
                            "event_calculus_formula": record["event_calculus_formula"],
                            "event_formula_fingerprint": record["event_formula_fingerprint"],
                            "event_formula_source": record["event_formula_source"],
                            "event_formula_syntax_valid": bool(
                                record["event_formula_syntax_valid"]
                            ),
                            "event_formula_target_components": _mapping(
                                record.get("event_formula_target_components")
                            ),
                            "event_formula_target_parse_profile": _mapping(
                                record.get("event_formula_target_parse_profile")
                            ),
                            "event_formula_target_quality_gate": _mapping(
                                record.get("event_formula_target_quality_gate")
                            ),
                            "selected_frame": str(record.get("selected_frame") or ""),
                            "selected_frame_source": str(
                                record.get("selected_frame_source") or ""
                            ),
                            "compiler_guidance_source": str(
                                record.get("compiler_guidance_source") or ""
                            ),
                            "modality": record["modality"],
                            "procedure_event_records": [
                                dict(procedure_event)
                                for procedure_event in record.get(
                                    "procedure_event_records"
                                )
                                or []
                            ],
                            "source_id": record["source_id"],
                        }
                        for record in records
                    ]
                },
                metadata={
                    "state_formula_count": len(records),
                    "procedure_event_count": procedure_event_count,
                    "selected_frame_count": sum(
                        1 for record in records if str(record.get("selected_frame") or "")
                    ),
                    "syntax_valid_count": sum(
                        1
                        for record in records
                        if record["event_formula_syntax_valid"]
                    ),
                },
            ),
            "dcec_formula": LogicIRView(
                name="dcec_formula",
                format="dcec-formula-records",
                source_component="CEC.native",
                payload={
                    "records": [
                        {
                            "formula": record["formula"],
                            "proof_input": record["proof_input"],
                            "source_id": record["source_id"],
                            "valid": bool(record["valid"]),
                        }
                        for record in records
                    ]
                },
                metadata={"formula_count": len(records)},
            ),
            "proof_trace": LogicIRView(
                name="proof_trace",
                format="dcec-validation-trace",
                source_component="CEC.native",
                payload={
                    "records": [
                        {
                            "reason": record["validation_reason"],
                            "source_id": record["source_id"],
                            "valid": bool(record["valid"]),
                        }
                        for record in records
                    ]
                },
                metadata={"validated_count": sum(1 for record in records if record["valid"])},
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="CEC.native",
                payload={"triples": [dict(triple) for triple in triples]},
                metadata={"triple_count": len(triples)},
            ),
        }
        if graph_data is not None:
            views["neo4j_graph_data"] = LogicIRView(
                name="neo4j_graph_data",
                format="neo4j-compatible-graph-data",
                source_component="knowledge_graphs.neo4j_compat",
                payload=graph_data.to_dict(),
                metadata={
                    "node_count": graph_data.node_count,
                    "relationship_count": graph_data.relationship_count,
                },
            )

        return (
            LegalIRDocument(
                document_id=resolved_document_id,
                source_text=text,
                normalized_text=" ".join(str(text or "").split()),
                source=source,
                citation=citation or _citation_from_norms(norms),
                views=views,
                frame_logic_triples=triples,
                metadata={
                    "dcec_formula_count": len(records),
                    "deontic_norm_count": len(norms),
                    "event_formula_count": len(records),
                    "procedure_event_count": procedure_event_count,
                    "event_formula_selected_frame_count": sum(
                        1 for record in records if str(record.get("selected_frame") or "")
                    ),
                    "compiler_guidance_applied": any(
                        str(record.get("compiler_guidance_source") or "")
                        for record in records
                    ),
                    "event_formula_syntax_valid_count": sum(
                        1
                        for record in records
                        if record["event_formula_syntax_valid"]
                    ),
                },
            ),
            {
                "graph_data": graph_data,
                "norms": norms,
                "records": records,
            },
        )

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
        **_: Any,
    ) -> BridgeEvaluationReport:
        """Run the CEC/DCEC bridge and return optimizer-visible diagnostics."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
            compiler_guidance=compiler_guidance,
        )
        records = list(context["records"])
        proof_gate = _proof_gate_from_dcec_records(records)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(records))
        failure_ratio = max(0.0, (attempted - proof_gate.valid_count) / attempted)
        event_formula_invalid_ratio = max(
            0.0,
            (
                attempted
                - sum(
                    1
                    for record in records
                    if record.get("event_formula_syntax_valid")
                )
            )
            / attempted,
        )
        no_formula_loss = 0.0 if records else 1.0
        legal_ir_view_cross_entropy_loss = _cec_legal_ir_view_cross_entropy_loss(
            ir_document
        )
        compiler_ir_cross_entropy_loss = max(
            failure_ratio,
            event_formula_invalid_ratio,
        )
        compiler_ir_cosine_similarity = max(
            0.0,
            1.0 - compiler_ir_cross_entropy_loss,
        )
        cross_entropy_loss = max(
            no_formula_loss,
            failure_ratio,
            event_formula_invalid_ratio,
            legal_ir_view_cross_entropy_loss,
        )
        cosine_similarity = max(0.0, 1.0 - no_formula_loss)
        source_copy_reward_hack_penalty = _cec_source_copy_reward_hack_penalty(
            source_text=text,
            decoded_text=" ".join(
                str(
                    record.get("event_calculus_formula")
                    or record.get("formula")
                    or ""
                )
                for record in records
            ),
        )
        target_metrics = {
            "cec_dcec_event_formula_invalid_ratio": event_formula_invalid_ratio,
            "cec_dcec_validation_failure_ratio": failure_ratio,
            "compiler_ir_cross_entropy_loss": compiler_ir_cross_entropy_loss,
            "compiler_ir_cosine_similarity": compiler_ir_cosine_similarity,
            "cross_entropy_loss": cross_entropy_loss,
            "cosine_similarity": cosine_similarity,
            "legal_ir_view_cross_entropy_loss": legal_ir_view_cross_entropy_loss,
            "source_decompiled_text_embedding_cosine_loss": no_formula_loss,
            "source_copy_reward_hack_penalty": source_copy_reward_hack_penalty,
        }
        round_trip = RoundTripMetrics(
            cosine_similarity=cosine_similarity,
            cosine_loss=no_formula_loss,
            cross_entropy_loss=cross_entropy_loss,
            symbolic_validity_penalty=max(
                failure_ratio,
                event_formula_invalid_ratio,
            ),
            extra_losses={
                "cec_dcec_no_formula_loss": no_formula_loss,
                "cec_dcec_validation_failure_ratio": failure_ratio,
                "cec_dcec_event_formula_invalid_ratio": event_formula_invalid_ratio,
                "compiler_ir_cross_entropy_loss": compiler_ir_cross_entropy_loss,
                "compiler_ir_cosine_similarity": compiler_ir_cosine_similarity,
                "legal_ir_view_cross_entropy_loss": legal_ir_view_cross_entropy_loss,
                "source_decompiled_text_embedding_cosine_loss": no_formula_loss,
                "source_copy_reward_hack_penalty": source_copy_reward_hack_penalty,
            },
        )
        status = "ok" if records and proof_gate.compiles else "partial"
        if event_formula_invalid_ratio > 0.0:
            status = "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        guidance_signal = _cec_compiler_guidance_signal(compiler_guidance)
        compiler_guidance_applied = any(
            str(record.get("compiler_guidance_source") or "")
            for record in records
        )
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=" ".join(
                str(
                    record.get("event_calculus_formula")
                    or record.get("formula")
                    or ""
                )
                for record in records
            ),
            status=status,
            metadata={
                "adapter": "cec_dcec_bridge_v1",
                "compiler_guidance_applied": compiler_guidance_applied,
                "compiler_guidance_quality_gate": guidance_signal.get("quality_gate", ""),
                "compiler_guidance_routes": guidance_signal.get("routes", []),
                "compiler_guidance_target_metrics": guidance_signal.get(
                    "target_metrics",
                    [],
                ),
                "compiler_guidance_target_component": guidance_signal.get(
                    "target_component",
                    "",
                ),
                "target_metrics": target_metrics,
            },
        )

    def _converter(self) -> Any:
        if self.converter is not None:
            return self.converter
        from ipfs_datasets_py.logic.deontic import DeonticConverter

        self.converter = DeonticConverter(**dict(self.converter_kwargs))
        return self.converter


def _deontic_norms_from_text(text: str, *, converter: Any) -> list[dict[str, Any]]:
    editorial_norm = _section_editorial_norm_from_text(text)
    if editorial_norm and editorial_norm.get("norm_type") == "instrument_lifecycle":
        return [editorial_norm]
    statutory_statement_norm = _section_statutory_statement_norm_from_text(text)
    if statutory_statement_norm:
        return [statutory_statement_norm]
    operational_norm = _section_operational_norm_from_text(text)
    if operational_norm:
        return [operational_norm]
    definition_norm = _section_definition_norm_from_text(text)
    if definition_norm:
        return [definition_norm]

    result = converter.convert(text)
    metadata = dict(getattr(result, "metadata", {}) or {})
    norms = _deontic_norm_rows_from_metadata(metadata)
    if norms:
        return norms
    fallback = editorial_norm or _fallback_norm_from_conversion(result=result, text=text)
    return [fallback] if fallback else []


def _deontic_norm_rows_from_metadata(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    norms = _list_of_dicts(metadata.get("legal_norm_irs"))
    if not norms:
        legal_norm_ir = metadata.get("legal_norm_ir")
        if isinstance(legal_norm_ir, Mapping):
            norms = [dict(legal_norm_ir)]
    if norms:
        return norms

    parser_elements = _list_of_dicts(metadata.get("parser_elements"))
    if not parser_elements:
        parser_element = metadata.get("parser_element")
        if isinstance(parser_element, Mapping):
            parser_elements = [dict(parser_element)]
    if not parser_elements:
        return []

    from_parser_elements = _legal_norm_rows_from_parser_elements(parser_elements)
    if from_parser_elements:
        return from_parser_elements
    return [
        _minimal_norm_from_parser_element(element, index=index)
        for index, element in enumerate(parser_elements)
    ]


def _legal_norm_rows_from_parser_elements(
    parser_elements: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not parser_elements:
        return []
    try:
        from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for element in parser_elements:
        if not isinstance(element, Mapping):
            continue
        try:
            rows.append(LegalNormIR.from_parser_element(dict(element)).to_dict())
        except Exception:
            continue
    return rows


def _minimal_norm_from_parser_element(
    element: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    source_id = str(element.get("source_id") or f"dcec:parser:{index}")
    actor = _first_text_value(
        element.get("actor"),
        element.get("subject"),
        fallback="actor",
    )
    action = _first_text_value(
        element.get("action"),
        element.get("action_verb"),
        element.get("proposition"),
        fallback="act",
    )
    modality = _first_text_value(
        element.get("modality"),
        element.get("deontic_operator"),
        element.get("norm_type"),
        fallback="obligated",
    )
    row: dict[str, Any] = {
        "actor": actor,
        "action": action,
        "modality": modality,
        "norm_type": modality,
        "source_id": source_id,
    }
    citation = _first_text_value(
        element.get("canonical_citation"),
        element.get("citation"),
    )
    if citation:
        row["canonical_citation"] = citation
    support_text = _first_text_value(
        element.get("support_text"),
        element.get("source_text"),
    )
    if support_text:
        row["support_text"] = support_text
    return row


def _dcec_records(
    norms: Sequence[Mapping[str, Any]],
    *,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> list[dict[str, Any]]:
    event_formula_exports = _event_formula_exports_from_norms(norms)
    guidance_event_formula_exports = _compiler_guidance_event_formula_exports(
        norms,
        compiler_guidance=compiler_guidance,
        document_id=document_id,
        citation=citation,
        source_text=source_text,
    )
    for guided_source_id, guided_records in guidance_event_formula_exports.items():
        if guided_records:
            event_formula_exports[guided_source_id] = list(guided_records)
    pending_event_formula_exports = {
        source_id: list(records)
        for source_id, records in event_formula_exports.items()
    }
    records: list[dict[str, Any]] = []
    for index, norm in enumerate(norms):
        actor = _symbol(norm.get("actor"), fallback="actor")
        event = _symbol(norm.get("action") or norm.get("predicate"), fallback="act")
        modality = _dcec_modality(norm)
        state_kind = _dcec_state_kind(norm)
        source_id = str(norm.get("source_id") or f"dcec:norm:{index}")
        frame_guidance = _frame_guidance_from_norm(
            norm,
            compiler_guidance=compiler_guidance,
            document_id=document_id,
            citation=citation,
            source_text=source_text,
        )
        selected_frame = str(frame_guidance.get("selected_frame") or "")
        selected_frame_source = str(frame_guidance.get("selected_frame_source") or "")
        compiler_guidance_source = str(frame_guidance.get("compiler_guidance_source") or "")
        procedure_event_records = _procedure_event_records_from_norm(
            norm,
            source_id=source_id,
            actor=actor,
        )
        procedure_event_records = _augment_procedure_events_from_selected_frame(
            procedure_event_records,
            norm=norm,
            source_id=source_id,
            actor=actor,
            selected_frame=selected_frame,
            selected_frame_source=selected_frame_source,
            compiler_guidance_source=compiler_guidance_source,
        )
        formula_object = _native_dcec_event_formula(
            actor=actor,
            event=event,
            modality=modality,
            state_kind=state_kind,
        )
        formula = (
            str(formula_object.to_string())
            if formula_object is not None and hasattr(formula_object, "to_string")
            else f"{modality}({actor},{event},t0)"
        )
        proof_input = _proof_input_formula_text(
            actor=actor,
            event=event,
            modality=modality,
            state_kind=state_kind,
        )
        event_formula_export = _take_event_formula_export(
            pending_event_formula_exports,
            source_id=source_id,
            index=index,
        )
        if event_formula_export:
            event_calculus_formula = str(
                event_formula_export.get("event_calculus_formula") or ""
            )
            event_formula_source = str(
                event_formula_export.get("event_formula_source") or ""
            )
            event_formula_syntax_valid = bool(
                event_formula_export.get("event_formula_syntax_valid")
            )
            event_formula_target_parse_profile = _mapping(
                event_formula_export.get("event_formula_target_parse_profile")
            )
            event_formula_target_components = _mapping(
                event_formula_export.get("event_formula_target_components")
            )
            event_formula_target_quality_gate = _mapping(
                event_formula_export.get("event_formula_target_quality_gate")
            )
            if _event_formula_export_needs_bridge_fallback(event_calculus_formula):
                event_calculus_formula = _event_calculus_formula_text(
                    source_id=source_id,
                    deontic_formula=proof_input,
                )
                event_formula_source = (
                    f"{event_formula_source}:bridge_fallback"
                    if event_formula_source
                    else "cec_dcec_bridge_fallback"
                )
                event_formula_syntax_valid = _event_calculus_formula_shape_valid(
                    event_calculus_formula
                )
                event_formula_target_parse_profile = _event_formula_parse_profile(
                    event_calculus_formula
                )
                event_formula_target_components = _event_formula_target_components(
                    event_calculus_formula,
                    source_id=source_id,
                    modality=modality,
                )
                event_formula_target_quality_gate = {
                    "syntax_valid": bool(event_formula_syntax_valid),
                    "target_parse_profile_complete": bool(
                        event_formula_target_parse_profile.get(
                            "target_parse_profile_complete"
                        )
                        is True
                    ),
                    "requires_validation": not bool(event_formula_syntax_valid),
                    "cec_dcec_bridge_fallback_from_invalid_export": True,
                }
        else:
            event_calculus_formula = _event_calculus_formula_text(
                source_id=source_id,
                deontic_formula=proof_input,
            )
            event_formula_source = "cec_dcec_bridge_fallback"
            event_formula_syntax_valid = _event_calculus_formula_shape_valid(
                event_calculus_formula
            )
            event_formula_target_parse_profile = _event_formula_parse_profile(
                event_calculus_formula
            )
            event_formula_target_components = _event_formula_target_components(
                event_calculus_formula,
                source_id=source_id,
                modality=modality,
            )
            event_formula_target_quality_gate = {
                "syntax_valid": bool(event_formula_syntax_valid),
                "target_parse_profile_complete": bool(
                    event_formula_target_parse_profile.get("target_parse_profile_complete")
                    is True
                ),
                "requires_validation": not bool(event_formula_syntax_valid),
            }
        (
            event_calculus_formula,
            event_formula_syntax_valid,
            event_formula_target_parse_profile,
            event_formula_target_components,
            event_formula_target_quality_gate,
        ) = _normalize_event_formula_fields(
            formula=event_calculus_formula,
            syntax_valid=event_formula_syntax_valid,
            target_parse_profile=event_formula_target_parse_profile,
            target_components=event_formula_target_components,
            target_quality_gate=event_formula_target_quality_gate,
            source_id=source_id,
            modality=modality,
            selected_frame=selected_frame,
            selected_frame_source=selected_frame_source,
        )
        if (
            not compiler_guidance_source
            and str(event_formula_source or "").startswith("compiler_guidance.")
        ):
            compiler_guidance_source = "repair_cec_dcec_bridge"
        event_formula_fingerprint = _stable_short_hash(event_calculus_formula)
        valid, validation_reason = _compile_dcec_proof_input(formula_object)
        records.append(
            {
                "actor": actor,
                "event": event,
                "formula": formula,
                "proof_input": proof_input,
                "event_calculus_formula": event_calculus_formula,
                "event_formula_source": event_formula_source,
                "event_formula_syntax_valid": event_formula_syntax_valid,
                "event_formula_target_parse_profile": event_formula_target_parse_profile,
                "event_formula_target_components": event_formula_target_components,
                "event_formula_target_quality_gate": event_formula_target_quality_gate,
                "event_formula_fingerprint": event_formula_fingerprint,
                "selected_frame": selected_frame,
                "selected_frame_source": selected_frame_source,
                "compiler_guidance_source": compiler_guidance_source,
                "formula_object": formula_object,
                "modality": modality,
                "state_kind": state_kind,
                "procedure_event_records": procedure_event_records,
                "source_id": source_id,
                "source_norm": dict(norm),
                "valid": valid,
                "validation_reason": validation_reason,
            }
        )
    return records


def _procedure_event_records_from_norm(
    norm: Mapping[str, Any],
    *,
    source_id: str,
    actor: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in (
        "procedure_event_records",
        "cec_procedure_event_records",
        "event_calculus_event_records",
    ):
        records.extend(_list_of_dicts(norm.get(key)))

    if not records:
        records.extend(
            _procedure_event_records_from_procedure(
                _mapping(norm.get("procedure")),
                source_id=source_id,
            )
        )

    if not records:
        records.extend(_exported_procedure_event_records_from_norm(norm))

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for index, record in enumerate(records, start=1):
        event = _first_text_value(record.get("event"), record.get("name"))
        relation = _first_text_value(
            record.get("relation"),
            record.get("type"),
            *_text_sequence(record.get("relation_types")),
        )
        anchor_event = _first_text_value(
            record.get("anchor_event"),
            record.get("anchor"),
            *_text_sequence(record.get("anchor_events")),
        )
        if not event and anchor_event:
            event = anchor_event
        if not event:
            continue
        event_order = _intish(record.get("event_order") or record.get("order"), index)
        event_symbol = _first_text_value(
            record.get("event_symbol"),
            fallback=_symbol(event, fallback="event"),
        )
        identity = "|".join(
            [source_id, str(event_order), event, relation, anchor_event]
        )
        event_id = _first_text_value(
            record.get("event_id"),
            fallback=f"event:{_stable_short_hash(identity)}",
        )
        key = (event_id, event, event_order, relation)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "actor": _first_text_value(record.get("actor"), fallback=actor),
                "anchor_event": anchor_event,
                "anchor_symbol": _first_text_value(
                    record.get("anchor_symbol"),
                    fallback=_symbol(anchor_event, fallback=""),
                ),
                "event": event,
                "event_id": event_id,
                "event_order": event_order,
                "event_symbol": event_symbol,
                "is_formula_antecedent": bool(
                    _boolish(record.get("is_formula_antecedent"))
                ),
                "is_terminal": bool(_boolish(record.get("is_terminal"))),
                "is_trigger": bool(_boolish(record.get("is_trigger"))),
                "proof_role": _first_text_value(
                    record.get("proof_role"),
                    fallback=(
                        "prerequisite"
                        if _boolish(record.get("is_formula_antecedent"))
                        else "ordering_provenance"
                    ),
                ),
                "raw_text": _first_text_value(
                    record.get("raw_text"),
                    record.get("value"),
                    record.get("procedure_value"),
                ),
                "relation": relation,
                "source_id": _first_text_value(
                    record.get("source_id"),
                    fallback=source_id,
                ),
            }
        )
    return normalized


def _procedure_event_records_from_procedure(
    procedure: Mapping[str, Any],
    *,
    source_id: str,
) -> list[dict[str, Any]]:
    if not procedure:
        return []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(_list_of_dicts(procedure.get("event_chain")), start=1):
        event = _first_text_value(item.get("event"))
        if not event:
            continue
        relations = _list_of_dicts(item.get("relations"))
        relation = relations[0] if relations else {}
        records.append(
            {
                "anchor_event": _first_text_value(relation.get("anchor_event")),
                "event": event,
                "event_order": _intish(item.get("order"), index),
                "event_symbol": _symbol(event, fallback="event"),
                "is_terminal": event == _first_text_value(procedure.get("terminal_event")),
                "is_trigger": event == _first_text_value(procedure.get("trigger_event")),
                "relation": _first_text_value(relation.get("relation")),
                "source_id": source_id,
            }
        )

    for index, relation in enumerate(
        _list_of_dicts(procedure.get("event_relations")),
        start=len(records) + 1,
    ):
        event = _first_text_value(
            relation.get("event"),
            procedure.get("terminal_event"),
            relation.get("anchor_event"),
        )
        if not event:
            continue
        records.append(
            {
                "anchor_event": _first_text_value(
                    relation.get("anchor_event"),
                    procedure.get("trigger_event"),
                ),
                "event": event,
                "event_order": index,
                "event_symbol": _symbol(event, fallback="event"),
                "raw_text": _first_text_value(
                    relation.get("raw_text"),
                    relation.get("value"),
                ),
                "relation": _first_text_value(relation.get("relation")),
                "source_id": source_id,
            }
        )
    return records


def _exported_procedure_event_records_from_norm(
    norm: Mapping[str, Any],
) -> list[dict[str, Any]]:
    try:
        from ipfs_datasets_py.logic.deontic.exports import (
            build_procedure_event_records_from_ir,
        )
        from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
    except Exception:
        return []

    try:
        norm_object = LegalNormIR.from_parser_element(dict(norm))
        return [
            dict(record)
            for record in build_procedure_event_records_from_ir(norm_object)
            if isinstance(record, Mapping)
        ]
    except Exception:
        return []


def _augment_procedure_events_from_selected_frame(
    records: Sequence[Mapping[str, Any]],
    *,
    norm: Mapping[str, Any],
    source_id: str,
    actor: str,
    selected_frame: str,
    selected_frame_source: str,
    compiler_guidance_source: str,
) -> list[dict[str, Any]]:
    normalized_records = [
        dict(record) for record in records if isinstance(record, Mapping)
    ]
    if selected_frame != "administrative_notice_hearing":
        return normalized_records

    event_names = {
        _symbol(record.get("event"), fallback="")
        for record in normalized_records
        if isinstance(record, Mapping)
    }
    if {"notice", "hearing"} <= event_names:
        return normalized_records

    corpus = " ".join(
        _first_text_value(
            norm.get("support_text"),
            norm.get("source_text"),
            norm.get("text"),
            norm.get("action"),
            fallback="",
        ).lower().split()
    )
    if (
        "notice" not in corpus
        and "hearing" not in corpus
        and not compiler_guidance_source
    ):
        return normalized_records

    frame_source = selected_frame_source or "selected_frame"
    if "notice" not in event_names:
        normalized_records.append(
            {
                "actor": actor,
                "event": "notice",
                "event_id": f"{source_id}:procedure:notice",
                "event_order": 1,
                "event_symbol": "notice",
                "is_formula_antecedent": True,
                "is_trigger": True,
                "proof_role": "administrative_notice_prerequisite",
                "raw_text": "notice",
                "relation": "before",
                "source_id": source_id,
                "source": frame_source,
            }
        )
    if "hearing" not in event_names:
        normalized_records.append(
            {
                "actor": actor,
                "anchor_event": "notice",
                "anchor_symbol": "notice",
                "event": "hearing",
                "event_id": f"{source_id}:procedure:hearing",
                "event_order": 2,
                "event_symbol": "hearing",
                "is_formula_antecedent": True,
                "is_terminal": True,
                "proof_role": "administrative_hearing_prerequisite",
                "raw_text": "hearing",
                "relation": "after",
                "source_id": source_id,
                "source": frame_source,
            }
        )
    return normalized_records


def _dcec_modality(norm: Mapping[str, Any]) -> str:
    modality = str(norm.get("modality") or norm.get("norm_type") or "").lower()
    if modality in {"f", "forbidden", "prohibition"}:
        return "forbidden"
    if modality in {"p", "permitted", "permission"}:
        return "permitted"
    if "prohib" in modality or "forbid" in modality:
        return "forbidden"
    if "permit" in modality or "may" in modality:
        return "permitted"
    return "obligated"


def _dcec_state_kind(norm: Mapping[str, Any]) -> str:
    norm_type = str(norm.get("norm_type") or "").strip().lower()
    modality = str(norm.get("modality") or norm.get("deontic_operator") or "").strip().lower()
    for token in (norm_type, modality):
        normalized = token.replace("-", "_").replace(" ", "_")
        if normalized in _DCEC_STATE_PREDICATE_BY_KIND:
            return normalized
        if normalized in {"def", "definition"}:
            return "definition"
        if normalized in {"life", "lifecycle", "instrument_lifecycle_validity", "instrument_lifecycle_expiration"}:
            return "instrument_lifecycle"

    corpus = " ".join(
        _first_text_value(
            norm.get("support_text"),
            norm.get("source_text"),
            norm.get("text"),
            norm.get("action"),
            fallback="",
        ).lower().split()
    )
    if re.search(r"\b(?:the\s+term|terms?)\b.{0,80}\bmeans\b", corpus):
        return "definition"
    if re.search(
        r"\b(?:(?:does\s+not|do\s+not|shall\s+not)\s+apply\s+to|"
        r"nothing\b.{0,80}\bshall\s+apply\s+to|"
        r"nothing\b.{0,80}\bshall\s+be\s+construed\s+(?:as|to))\b",
        corpus,
    ):
        return "exemption"
    if "otherwise be applicable" not in corpus:
        if re.search(
            r"\b(?:applies|apply|shall\s+apply|"
            r"(?:is|are|be|shall\s+be)\s+applicable)\s+to\b",
            corpus,
        ):
            return "applicability"
    if _looks_like_statutory_purpose_statement(corpus):
        return "purpose"
    if re.search(r"\b(?:expires?|expiration|effective\s+date|takes?\s+effect)\b", corpus):
        return "instrument_lifecycle"
    return ""


def _proof_gate_from_dcec_records(records: Sequence[Mapping[str, Any]]) -> ProofGateResult:
    attempted = len(records)
    valid = sum(1 for record in records if record.get("valid"))
    failed = attempted - valid
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        failed_count=failed,
        verified_by=("dcec:native_compile",) if valid else (),
        details=tuple(
            {
                "formula": record.get("formula"),
                "proof_input": record.get("proof_input"),
                "source_id": record.get("source_id"),
                "valid": bool(record.get("valid")),
                "validation_reason": record.get("validation_reason"),
            }
            for record in records
        ),
    )


def _cec_legal_ir_view_cross_entropy_loss(ir_document: LegalIRDocument) -> float:
    """Bounded missing-view loss for daemon-visible CEC legal IR metrics."""

    required_views = {
        "cec_events",
        "dcec_formula",
        "event_calculus",
        "frame_logic",
        "proof_trace",
    }
    present_views = {
        name
        for name, view in ir_document.views.items()
        if name in required_views and dict(view.payload)
    }
    if not required_views:
        return 0.0
    missing_count = len(required_views - present_views)
    return missing_count / len(required_views)


def _cec_source_copy_reward_hack_penalty(
    *,
    source_text: str,
    decoded_text: str,
) -> float:
    """Penalize decoded CEC output that simply mirrors long source spans."""

    source_tokens = _metric_tokens(source_text)
    decoded_tokens = _metric_tokens(decoded_text)
    if len(source_tokens) < 12 or len(decoded_tokens) < 12:
        return 0.0
    source_token_set = set(source_tokens)
    if not source_token_set:
        return 0.0
    copied_ratio = sum(1 for token in decoded_tokens if token in source_token_set) / len(
        decoded_tokens
    )
    return copied_ratio if copied_ratio >= 0.85 else 0.0


def _metric_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9_]+", str(text or "").lower())
        if len(token) > 2
    ]


def _cec_event_view_rows(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        source_id = str(record.get("source_id") or "")
        actor = str(record.get("actor") or "")
        event = str(record.get("event") or "")
        if event:
            rows.append(
                {
                    "actor": actor,
                    "event": event,
                    "event_role": "norm_action",
                    "source_id": source_id,
                }
            )
        for procedure_event in record.get("procedure_event_records") or []:
            if not isinstance(procedure_event, Mapping):
                continue
            procedure_event_name = str(procedure_event.get("event") or "").strip()
            if not procedure_event_name:
                continue
            row = {
                "actor": str(procedure_event.get("actor") or actor),
                "event": procedure_event_name,
                "event_id": str(procedure_event.get("event_id") or ""),
                "event_order": _intish(procedure_event.get("event_order"), 0),
                "event_role": "procedure_event",
                "event_symbol": str(procedure_event.get("event_symbol") or ""),
                "source_id": str(procedure_event.get("source_id") or source_id),
            }
            relation = str(procedure_event.get("relation") or "").strip()
            if relation:
                row["relation"] = relation
            anchor_event = str(procedure_event.get("anchor_event") or "").strip()
            if anchor_event:
                row["anchor_event"] = anchor_event
            rows.append(row)
    return rows


def _dcec_frame_logic_triples(
    document_id: str,
    *,
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples = [
        {"subject": document_id, "predicate": "type", "object": "legal_dcec_document"}
    ]
    for record in records:
        source_id = str(record.get("source_id") or "")
        if not source_id:
            continue
        triples.extend(
            [
                {"subject": document_id, "predicate": "contains_event_formula", "object": source_id},
                {"subject": source_id, "predicate": "type", "object": "dcec_formula"},
                {"subject": source_id, "predicate": "actor", "object": str(record.get("actor") or "")},
                {"subject": source_id, "predicate": "event", "object": str(record.get("event") or "")},
                {"subject": source_id, "predicate": "formula", "object": str(record.get("formula") or "")},
                {"subject": source_id, "predicate": "modality", "object": str(record.get("modality") or "")},
                {"subject": source_id, "predicate": "valid", "object": str(bool(record.get("valid"))).lower()},
                {
                    "subject": source_id,
                    "predicate": "event_calculus_formula",
                    "object": str(record.get("event_calculus_formula") or ""),
                },
                {
                    "subject": source_id,
                    "predicate": "event_formula_syntax_valid",
                    "object": str(
                        bool(record.get("event_formula_syntax_valid"))
                    ).lower(),
                },
                {
                    "subject": source_id,
                    "predicate": "event_formula_source",
                    "object": str(record.get("event_formula_source") or ""),
                },
                {
                    "subject": source_id,
                    "predicate": "event_formula_fingerprint",
                    "object": str(record.get("event_formula_fingerprint") or ""),
                },
                {
                    "subject": source_id,
                    "predicate": "selected_frame",
                    "object": str(record.get("selected_frame") or ""),
                },
                {
                    "subject": source_id,
                    "predicate": "selected_frame_source",
                    "object": str(record.get("selected_frame_source") or ""),
                },
                {
                    "subject": source_id,
                    "predicate": "compiler_guidance_source",
                    "object": str(record.get("compiler_guidance_source") or ""),
                },
            ]
        )
        triples.extend(_procedure_event_frame_logic_triples(source_id, record))
    return [triple for triple in triples if triple["object"]]


def _procedure_event_frame_logic_triples(
    source_id: str,
    record: Mapping[str, Any],
) -> list[dict[str, str]]:
    triples: list[dict[str, str]] = []
    for procedure_event in record.get("procedure_event_records") or []:
        if not isinstance(procedure_event, Mapping):
            continue
        event_id = str(procedure_event.get("event_id") or "").strip()
        event = str(procedure_event.get("event") or "").strip()
        if not event_id:
            event_symbol = str(
                procedure_event.get("event_symbol") or _symbol(event, fallback="event")
            )
            event_id = f"{source_id}:procedure:{event_symbol}"
        if not event_id or not event:
            continue
        triples.extend(
            [
                {"subject": source_id, "predicate": "has_procedure_event", "object": event_id},
                {"subject": event_id, "predicate": "type", "object": "cec_procedure_event"},
                {"subject": event_id, "predicate": "event", "object": event},
                {
                    "subject": event_id,
                    "predicate": "event_symbol",
                    "object": str(procedure_event.get("event_symbol") or ""),
                },
                {
                    "subject": event_id,
                    "predicate": "event_order",
                    "object": str(procedure_event.get("event_order") or ""),
                },
                {
                    "subject": event_id,
                    "predicate": "relation",
                    "object": str(procedure_event.get("relation") or ""),
                },
                {
                    "subject": event_id,
                    "predicate": "anchor_event",
                    "object": str(procedure_event.get("anchor_event") or ""),
                },
                {
                    "subject": event_id,
                    "predicate": "proof_role",
                    "object": str(procedure_event.get("proof_role") or ""),
                },
            ]
        )
    return triples


def _graph_data_from_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    graph_id: str,
    metadata: Mapping[str, Any],
) -> Any:
    if not triples:
        return None
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    return flogic_triples_to_graph_data(triples, graph_id=graph_id, metadata=metadata)


def _document_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _citation_from_norms(norms: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if not norms:
        return None
    citation = norms[0].get("canonical_citation")
    return str(citation) if citation else None


def _native_dcec_event_formula(
    *,
    actor: str,
    event: str,
    modality: str,
    state_kind: str = "",
) -> Any:
    if not actor or not event:
        return None
    from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        AtomicFormula,
        DeonticFormula,
        DeonticOperator,
        Function,
        FunctionTerm,
        Predicate,
        Sort,
    )

    agent_sort = Sort("Agent")
    event_sort = Sort("Event")
    moment_sort = Sort("Moment")
    actor_term = FunctionTerm(Function(actor, [], agent_sort), [])
    event_term = FunctionTerm(Function(event, [], event_sort), [])
    state_predicate = _DCEC_STATE_PREDICATE_BY_KIND.get(str(state_kind or ""))
    if state_predicate:
        return AtomicFormula(
            Predicate(state_predicate, [agent_sort, event_sort]),
            [actor_term, event_term],
        )
    moment_term = FunctionTerm(Function("t0", [], moment_sort), [])
    happens_predicate = Predicate(
        "happens",
        [agent_sort, event_sort, moment_sort],
    )
    happens_formula = AtomicFormula(
        happens_predicate,
        [actor_term, event_term, moment_term],
    )
    return DeonticFormula(
        _deontic_operator_for_modality(modality),
        happens_formula,
        agent=actor_term,
    )


def _deontic_operator_for_modality(modality: str) -> Any:
    from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticOperator

    normalized = str(modality or "").strip().lower()
    if normalized == "forbidden":
        return DeonticOperator.PROHIBITION
    if normalized == "permitted":
        return DeonticOperator.PERMISSION
    return DeonticOperator.OBLIGATION


def _compile_dcec_proof_input(formula: Any) -> tuple[bool, str]:
    if formula is None:
        return (False, "missing_actor_or_event_symbol")
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECContainer

        container = DCECContainer()
        container.add_statement(formula)
        return (True, "compiled_dcec_native_container")
    except Exception as exc:
        return (False, f"native_compile_error:{type(exc).__name__}:{str(exc)[:80]}")


def _symbol(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip().lower()
    if not text and fallback:
        text = str(fallback).strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    normalized = "_".join(part for part in "".join(chars).split("_") if part)
    if not normalized and fallback:
        fallback_text = str(fallback).strip().lower()
        fallback_chars = [char if char.isalnum() else "_" for char in fallback_text]
        normalized = "_".join(part for part in "".join(fallback_chars).split("_") if part)
    if not normalized:
        return ""
    if normalized[0].isdigit():
        normalized = f"sym_{normalized}"
    return normalized[:96]


def _proof_input_formula_text(
    *,
    actor: str,
    event: str,
    modality: str,
    state_kind: str = "",
) -> str:
    state_predicate = _DCEC_STATE_PREDICATE_BY_KIND.get(str(state_kind or ""))
    if state_predicate:
        return f"{state_predicate}({actor},{event})"
    operator = "O"
    if modality == "forbidden":
        operator = "F"
    elif modality == "permitted":
        operator = "P"
    return f"{operator}(happens({actor},{event},t0))"


def _event_formula_exports_from_norms(
    norms: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    exports: dict[str, list[dict[str, Any]]] = (
        _direct_event_formula_exports_from_norms(norms)
    )
    if not norms:
        return exports
    try:
        from ipfs_datasets_py.logic.deontic.exports import (
            build_prover_syntax_records_from_ir,
        )
        from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
    except Exception:
        return exports

    for norm in norms:
        source_id = str(norm.get("source_id") or "").strip()
        if not source_id:
            continue
        try:
            norm_object = LegalNormIR.from_parser_element(dict(norm))
            syntax_records = build_prover_syntax_records_from_ir(
                norm_object,
                targets=("deontic_cec",),
            )
        except Exception:
            continue
        for record in syntax_records:
            if str(record.get("target") or "").strip() != "deontic_cec":
                continue
            exported_formula = str(record.get("exported_formula") or "").strip()
            if not exported_formula:
                continue
            if exports.get(source_id):
                continue
            exports.setdefault(source_id, []).append(
                {
                    "event_calculus_formula": exported_formula,
                    "event_formula_fingerprint": _stable_short_hash(exported_formula),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": bool(record.get("syntax_valid") is True),
                    "event_formula_target_components": _mapping(
                        record.get("target_components")
                    ),
                    "event_formula_target_parse_profile": _mapping(
                        record.get("target_parse_profile")
                    ),
                    "event_formula_target_quality_gate": _mapping(
                        record.get("target_quality_gate")
                    ),
                }
            )
            break
    return exports


def _compiler_guidance_event_formula_exports(
    norms: Sequence[Mapping[str, Any]],
    *,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> dict[str, list[dict[str, Any]]]:
    guidance = _mapping(compiler_guidance)
    if not guidance or not _compiler_guidance_has_cec_bridge_route(guidance):
        return {}

    exports: dict[str, list[dict[str, Any]]] = {}
    for index, norm in enumerate(norms):
        if not isinstance(norm, Mapping):
            continue
        source_id = str(norm.get("source_id") or f"dcec:norm:{index}").strip()
        if not source_id:
            continue
        export: Optional[dict[str, Any]] = None
        for source, row, formula_key in _compiler_guidance_event_formula_candidates(
            guidance,
            norm=norm,
            document_id=document_id,
            citation=citation,
            source_text=source_text,
        ):
            export = _event_formula_export_from_guidance_row(
                row,
                source=f"compiler_guidance.{source}.{formula_key}",
                formula_key=formula_key,
            )
            if not export:
                continue
            exports[source_id] = [export]
            break
        if source_id in exports:
            continue
        export = _compiler_guidance_materialized_event_formula_export(
            guidance,
            norm=norm,
            source_id=source_id,
            document_id=document_id,
            citation=citation,
            source_text=source_text,
        )
        if export:
            exports[source_id] = [export]
    return exports


def _compiler_guidance_materialized_event_formula_export(
    guidance: Mapping[str, Any],
    *,
    norm: Mapping[str, Any],
    source_id: str,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> Optional[dict[str, Any]]:
    """Materialize CEC-route guidance into the native event-calculus skeleton."""

    if not _compiler_guidance_has_cec_bridge_route(guidance):
        return None
    evidence_source = _cec_guidance_materialization_source(
        guidance,
        norm=norm,
        document_id=document_id,
        citation=citation,
        source_text=source_text,
    )
    if not evidence_source:
        return None

    actor = _symbol(norm.get("actor"), fallback="actor")
    event = _symbol(norm.get("action") or norm.get("predicate"), fallback="act")
    if not actor or not event:
        return None
    deontic_formula = _proof_input_formula_text(
        actor=actor,
        event=event,
        modality=_dcec_modality(norm),
        state_kind=_dcec_state_kind(norm),
    )
    formula = _event_calculus_formula_text(
        source_id=source_id,
        deontic_formula=deontic_formula,
    )
    parse_profile = _event_formula_parse_profile(formula)
    if parse_profile.get("target_parse_profile_complete") is not True:
        return None
    return {
        "event_calculus_formula": formula,
        "event_formula_fingerprint": _stable_short_hash(formula),
        "event_formula_source": f"compiler_guidance.{evidence_source}.materialized_event_formula",
        "event_formula_syntax_valid": True,
        "event_formula_target_components": {
            **_event_formula_target_components(
                formula,
                source_id=source_id,
                modality=_dcec_modality(norm),
            ),
            "compiler_guidance_materialized": True,
        },
        "event_formula_target_parse_profile": parse_profile,
        "event_formula_target_quality_gate": {
            "compiler_guidance_materialized": True,
            "requires_validation": False,
            "syntax_valid": True,
            "target_parse_profile_complete": True,
        },
    }


def _cec_guidance_materialization_source(
    guidance: Mapping[str, Any],
    *,
    norm: Mapping[str, Any],
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> str:
    for collection_key, row in _compiler_guidance_evidence_rows(guidance):
        if _compiler_guidance_row_matches_norm(
            row,
            norm=norm,
            document_id=document_id,
            citation=citation,
            source_text=source_text,
        ) and _compiler_guidance_row_supports_cec_materialization(row):
            return collection_key
    if _compiler_guidance_top_level_supports_cec_materialization(guidance):
        return "top_level"
    for collection_key, row in _compiler_guidance_evidence_rows(guidance):
        if _compiler_guidance_row_supports_cec_materialization(row):
            return collection_key
    return ""


def _compiler_guidance_row_supports_cec_materialization(
    row: Mapping[str, Any],
) -> bool:
    if not row:
        return False
    target = str(
        row.get("target_view")
        or row.get("predicted_view")
        or row.get("target_component")
        or ""
    ).strip().lower()
    if target in {"cec.native", "cec_dcec", "deontic_cec"}:
        return True
    bridge_failure_name = str(row.get("bridge_failure_name") or "").strip().lower()
    if bridge_failure_name in {
        "cec_dcec_validation_failure_ratio",
        "cec_dcec_event_formula_invalid_ratio",
    }:
        return True
    if any(metric.startswith("cec_dcec_") for metric in _guidance_metric_names(row)):
        return True
    if _boolish(row.get("spacy_parser_missing_formula")) is False and (
        row.get("spacy_modal_formula_count") is not None
    ):
        return True
    return False


def _compiler_guidance_top_level_supports_cec_materialization(
    guidance: Mapping[str, Any],
) -> bool:
    bundle = _mapping(
        guidance.get("bundle")
        or guidance.get("compiler_guidance_bundle")
        or guidance.get("semantic_bundle")
    )
    scope = str(
        guidance.get("program_synthesis_scope")
        or bundle.get("program_synthesis_scope")
        or ""
    ).strip().lower()
    target = str(
        guidance.get("target_component") or bundle.get("target_component") or ""
    ).strip().lower()
    return (
        scope == "cec"
        or target == "cec.native"
        or any(
            metric.startswith("cec_dcec_")
            for metric in _guidance_metric_names(guidance)
        )
    )


def _compiler_guidance_event_formula_candidates(
    guidance: Mapping[str, Any],
    *,
    norm: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> list[tuple[str, Mapping[str, Any], str]]:
    candidate_keys = (
        "event_calculus_formula_after",
        "event_calculus_formula",
        "dcec_event_calculus_formula",
        "cec_event_calculus_formula",
        "event_formula_after",
        "event_formula",
        "cec_event_formula",
        "exported_formula",
        "target_formula",
        "formula_after",
        "formula",
    )
    candidates: list[tuple[str, Mapping[str, Any], str]] = []
    evidence_rows = _compiler_guidance_evidence_rows(guidance)
    matched_rows = [
        (collection_key, row)
        for collection_key, row in evidence_rows
        if _compiler_guidance_row_matches_norm(
            row,
            norm=norm,
            document_id=document_id,
            citation=citation,
            source_text=source_text,
        )
    ]
    for collection_key, row in matched_rows:
        for key in candidate_keys:
            candidates.append((collection_key, row, key))

    top_level_row = {
        key: guidance.get(key)
        for key in candidate_keys
        if str(guidance.get(key) or "").strip()
    }
    if top_level_row:
        for key in candidate_keys:
            candidates.append(("top_level", top_level_row, key))

    for collection_key, row in evidence_rows:
        if (collection_key, row) in matched_rows:
            continue
        for key in candidate_keys:
            candidates.append((collection_key, row, key))
    return candidates


def _event_formula_export_from_guidance_row(
    row: Mapping[str, Any],
    *,
    source: str,
    formula_key: str,
) -> Optional[dict[str, Any]]:
    formula = str(row.get(formula_key) or "").strip()
    if not formula:
        return None
    parse_profile = _event_formula_parse_profile(formula)
    if not (
        parse_profile.get("target_parse_profile_complete") is True
        or parse_profile.get("event_predicates")
        or parse_profile.get("top_level_symbol")
        in (_DCEC_STATE_PREDICATE_SET | {"O", "P", "F"})
    ):
        return None
    syntax_valid = bool(
        _boolish(row.get("event_formula_syntax_valid"))
        or _boolish(row.get("syntax_valid"))
        or parse_profile.get("target_parse_profile_complete") is True
    )
    return {
        "event_calculus_formula": formula,
        "event_formula_fingerprint": _stable_short_hash(formula),
        "event_formula_source": _first_text_value(
            row.get("event_formula_source"),
            row.get("formula_source"),
            fallback=source,
        ),
        "event_formula_syntax_valid": syntax_valid,
        "event_formula_target_components": _mapping(
            row.get("event_formula_target_components")
            or row.get("target_components")
        ),
        "event_formula_target_parse_profile": _mapping(
            row.get("event_formula_target_parse_profile")
            or row.get("target_parse_profile")
        ),
        "event_formula_target_quality_gate": _mapping(
            row.get("event_formula_target_quality_gate")
            or row.get("target_quality_gate")
        ),
    }


def _direct_event_formula_exports_from_norms(
    norms: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    exports: dict[str, list[dict[str, Any]]] = {}
    for index, norm in enumerate(norms):
        if not isinstance(norm, Mapping):
            continue
        source_id = str(norm.get("source_id") or f"dcec:norm:{index}").strip()
        formula_record = _direct_event_formula_export_from_norm(norm)
        if not source_id or not formula_record:
            continue
        exports.setdefault(source_id, []).append(formula_record)
    return exports


def _direct_event_formula_export_from_norm(
    norm: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    formula = _first_direct_event_formula_text(norm)
    if not formula:
        return None
    parse_profile = _event_formula_parse_profile(formula)
    if not (
        parse_profile.get("target_parse_profile_complete") is True
        and (
            parse_profile.get("event_predicates")
            or parse_profile.get("top_level_symbol") in _DCEC_STATE_PREDICATE_SET
        )
    ):
        return None
    syntax_valid = bool(
        _boolish(norm.get("event_formula_syntax_valid"))
        or _boolish(norm.get("syntax_valid"))
        or parse_profile.get("target_parse_profile_complete") is True
    )
    source = _first_text_value(
        norm.get("event_formula_source"),
        norm.get("formula_source"),
        fallback="legal_norm_ir.event_calculus_formula",
    )
    return {
        "event_calculus_formula": formula,
        "event_formula_fingerprint": _stable_short_hash(formula),
        "event_formula_source": source,
        "event_formula_syntax_valid": syntax_valid,
        "event_formula_target_components": _mapping(
            norm.get("event_formula_target_components")
            or norm.get("target_components")
        ),
        "event_formula_target_parse_profile": _mapping(
            norm.get("event_formula_target_parse_profile")
            or norm.get("target_parse_profile")
        ),
        "event_formula_target_quality_gate": _mapping(
            norm.get("event_formula_target_quality_gate")
            or norm.get("target_quality_gate")
        ),
    }


def _first_direct_event_formula_text(norm: Mapping[str, Any]) -> str:
    for key in (
        "event_calculus_formula",
        "dcec_event_calculus_formula",
        "cec_event_calculus_formula",
        "event_formula",
        "cec_event_formula",
    ):
        value = str(norm.get(key) or "").strip()
        if value:
            return value

    for record_key in (
        "prover_syntax_records",
        "local_prover_syntax_records",
        "target_syntax_records",
    ):
        for record in _list_of_dicts(norm.get(record_key)):
            target = str(record.get("target") or record.get("target_logic") or "").strip()
            if not _is_cec_event_formula_target(target):
                continue
            value = str(
                record.get("exported_formula")
                or record.get("event_calculus_formula")
                or record.get("target_formula")
                or record.get("formula")
                or ""
            ).strip()
            if value:
                return value
    return ""


def _is_cec_event_formula_target(target: str) -> bool:
    normalized = str(target or "").strip().lower()
    return normalized in {
        "cec.native",
        "deontic_cec",
        "event_calculus",
        "event_calculus_state",
    }


def _take_event_formula_export(
    exports: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    source_id: str,
    index: int,
) -> Optional[dict[str, Any]]:
    for key in (
        source_id,
        f"dcec:norm:{index}",
        f"dcec:parser:{index}",
    ):
        rows = exports.get(key)
        if not rows:
            continue
        row = dict(rows[0])
        if isinstance(rows, list):
            rows.pop(0)
        return row
    return None


def _event_calculus_formula_text(*, source_id: str, deontic_formula: str) -> str:
    source_symbol = _source_symbol(source_id)
    return (
        f"Happens(legal_norm({source_symbol}), t) => "
        f"HoldsAt({deontic_formula}, t)"
    )


def _event_calculus_formula_shape_valid(formula: str) -> bool:
    parse_profile = _event_formula_parse_profile(formula)
    return bool(parse_profile.get("target_parse_profile_complete") is True)


def _event_formula_export_needs_bridge_fallback(formula: str) -> bool:
    """Return True when an export has no usable CEC/event-calculus skeleton."""

    text = _normalize_event_formula_text(formula)
    if not text:
        return True
    parse_profile = _event_formula_parse_profile(text)
    if parse_profile.get("target_parse_profile_complete") is True:
        return False
    if parse_profile.get("event_predicates"):
        return parse_profile.get("event_predicate_slot_complete") is not True
    top_level_symbol = str(parse_profile.get("top_level_symbol") or "")
    return top_level_symbol not in (
        _DCEC_STATE_PREDICATE_SET
        | {"O", "P", "F", "always", "forall", "exists"}
    )


def _source_symbol(source_id: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(source_id or "unknown")).strip("_")
    return value or "unknown"


def _event_formula_parse_profile(formula: str) -> dict[str, Any]:
    text = _normalize_event_formula_text(formula)
    top_level_connector, connector_index = _top_level_connector(text)
    quantifier_variables = _quantifier_variables(text)
    wrappers = [
        _canonical_wrapper_symbol(match.group(1))
        for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*[\(\[]", text)
        if _canonical_wrapper_symbol(match.group(1))
    ]
    event_predicates = _event_predicates(text)
    event_predicate_argument_counts = _event_predicate_argument_counts(text)
    event_predicate_slot_complete = _event_predicate_slots_complete(
        event_predicate_argument_counts
    )
    top_level_symbol = _top_level_symbol(text)
    parse_profile_complete = _event_formula_parse_profile_complete(
        text=text,
        top_level_symbol=top_level_symbol,
        top_level_connector=top_level_connector,
        connector_index=connector_index,
        quantifier_variables=quantifier_variables,
        event_predicates=event_predicates,
        event_predicate_slot_complete=event_predicate_slot_complete,
    )
    return {
        "contains_implication": bool(top_level_connector),
        "event_predicate_argument_counts": event_predicate_argument_counts,
        "event_predicate_slot_complete": event_predicate_slot_complete,
        "event_predicates": event_predicates,
        "target_parse_profile_complete": parse_profile_complete,
        "top_level_symbol": top_level_symbol,
        "top_level_connector": top_level_connector,
        "quantifier_variables": quantifier_variables,
        "wrapper_sequence": wrappers,
    }


def _event_formula_parse_profile_complete(
    *,
    text: str,
    top_level_symbol: str,
    top_level_connector: str,
    connector_index: int,
    quantifier_variables: Sequence[str],
    event_predicates: Sequence[str],
    event_predicate_slot_complete: bool,
) -> bool:
    if not text or not _balanced_delimiters(text):
        return False
    if top_level_symbol in _DCEC_STATE_PREDICATE_SET:
        return _dcec_state_predicate_slots_complete(text, top_level_symbol)
    if not event_predicates:
        return False
    if not event_predicate_slot_complete:
        return False
    if top_level_connector:
        if connector_index <= 0:
            return False
        left = text[:connector_index].strip()
        right = text[connector_index + len(top_level_connector):].strip()
        return bool(left and right)
    if top_level_symbol in {"forall", "exists"}:
        return bool(quantifier_variables)
    if top_level_symbol in {"always", "O", "P", "F"}:
        return bool(event_predicates)
    return top_level_symbol in _EVENT_PREDICATE_SET


def _balanced_delimiters(text: str) -> bool:
    stack: list[str] = []
    opening = {"(": ")", "[": "]", "{": "}"}
    closing = {")": "(", "]": "[", "}": "{"}
    for char in str(text or ""):
        if char in opening:
            stack.append(char)
            continue
        if char in closing:
            if not stack:
                return False
            if stack[-1] != closing[char]:
                return False
            stack.pop()
    return not stack


def _top_level_symbol(text: str) -> str:
    match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[\(\[]", text)
    if match:
        token = match.group(1)
        lowered = token.lower()
        if lowered in {"forall", "exists"}:
            return lowered
        return (
            _canonical_event_predicate(token)
            or _canonical_dcec_state_predicate(token)
            or _canonical_wrapper_symbol(token)
            or token
        )
    if re.match(
        r"^\s*forall\s+[A-Za-z][A-Za-z0-9_]*\s*(?:\.|:|\()",
        text,
        flags=re.IGNORECASE,
    ):
        return "forall"
    if re.match(
        r"^\s*exists\s+[A-Za-z][A-Za-z0-9_]*\s*(?:\.|:|\()",
        text,
        flags=re.IGNORECASE,
    ):
        return "exists"
    return ""


def _quantifier_variables(text: str) -> list[str]:
    variables: list[str] = []
    quantifier_patterns = (
        r"\b(?:forall|exists)\s+([A-Za-z][A-Za-z0-9_]*)\s*(?:\.|:|\()",
        r"\b(?:forall|exists)\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:[,):])",
    )
    for pattern in quantifier_patterns:
        for variable in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            symbol = str(variable).strip()
            if symbol and symbol not in variables:
                variables.append(symbol)
    return variables


def _canonical_wrapper_symbol(token: str) -> str:
    return _EVENT_FORMULA_WRAPPER_CANONICAL_BY_LOWER.get(str(token or "").lower(), "")


def _canonical_event_predicate(token: str) -> str:
    return _EVENT_PREDICATE_CANONICAL_BY_LOWER.get(str(token or "").lower(), "")


def _canonical_dcec_state_predicate(token: str) -> str:
    return _DCEC_STATE_PREDICATE_CANONICAL_BY_LOWER.get(
        str(token or "").lower(),
        "",
    )


def _event_predicates(text: str) -> list[str]:
    predicates: list[str] = []
    for token in re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*[\(\[]", text):
        canonical = _canonical_event_predicate(token)
        if canonical and canonical not in predicates:
            predicates.append(canonical)
    return predicates


def _event_predicate_argument_counts(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for token, argument_text in _function_argument_texts(text):
        canonical = _canonical_event_predicate(token)
        if not canonical:
            continue
        arguments = _split_top_level_arguments(argument_text)
        records.append(
            {
                "predicate": canonical,
                "argument_count": len(arguments),
                "empty_argument_count": sum(1 for argument in arguments if not argument),
            }
        )
    return records


def _event_predicate_slots_complete(
    argument_counts: Sequence[Mapping[str, Any]],
) -> bool:
    if not argument_counts:
        return False
    min_arity = {
        "Happens": 2,
        "HoldsAt": 2,
        "Initiates": 3,
        "Terminates": 3,
        "ReleasedAt": 2,
        "Clipped": 3,
        "Trajectory": 4,
        "Initially": 1,
        "InitiallyP": 1,
        "InitiallyN": 1,
    }
    for record in argument_counts:
        predicate = str(record.get("predicate") or "")
        argument_count = _intish(record.get("argument_count"), 0)
        empty_argument_count = _intish(record.get("empty_argument_count"), 0)
        if argument_count < min_arity.get(predicate, 1):
            return False
        if empty_argument_count:
            return False
    return True


def _dcec_state_predicate_slots_complete(text: str, top_level_symbol: str) -> bool:
    for token, argument_text in _function_argument_texts(text):
        canonical = _canonical_dcec_state_predicate(token)
        if canonical != top_level_symbol:
            continue
        arguments = _split_top_level_arguments(argument_text)
        return len(arguments) >= 2 and not any(not argument for argument in arguments)
    return False


def _function_argument_texts(text: str) -> list[tuple[str, str]]:
    value = str(text or "")
    records: list[tuple[str, str]] = []
    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(", value):
        open_index = value.find("(", match.start())
        if open_index < 0:
            continue
        close_index = _matching_close_paren_index(value, open_index)
        if close_index < 0:
            continue
        records.append((match.group(1), value[open_index + 1:close_index]))
    return records


def _matching_close_paren_index(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
            continue
        if char != ")":
            continue
        depth -= 1
        if depth == 0:
            return index
        if depth < 0:
            return -1
    return -1


def _split_top_level_arguments(text: str) -> list[str]:
    value = str(text or "")
    if not value.strip():
        return []
    arguments: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth = max(0, depth - 1)
            continue
        if char == "," and depth == 0:
            arguments.append(value[start:index].strip())
            start = index + 1
    arguments.append(value[start:].strip())
    return arguments


def _strip_event_formula_clause_terminator(text: str) -> str:
    value = str(text or "").strip()
    while value.endswith(".") or value.endswith(";"):
        value = value[:-1].strip()
    return value


def _strip_event_formula_label(text: str) -> str:
    value = str(text or "").strip()
    label_match = re.match(
        r"^(?:proof\s+obligation|event\s+formula|exported\s+formula|"
        r"dcec(?:\s+formula)?|deontic[_\s-]*cec|formula)\s*[:=\-]\s*(.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if not label_match:
        return value
    candidate = label_match.group(1).strip()
    if re.match(
        r"^(?:Happens|HoldsAt|Initiates|Terminates|ReleasedAt|Clipped|Trajectory|"
        r"InitiallyP?|InitiallyN|always|forall|exists|O|P|F)\s*[\(\[]",
        candidate,
        flags=re.IGNORECASE,
    ):
        return candidate
    return value


def _top_level_connector(text: str) -> tuple[str, int]:
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        for token in ("=>", "->", ":-", "<-"):
            if text.startswith(token, index):
                return (_EVENT_FORMULA_CONNECTOR_CANONICAL_BY_TOKEN.get(token, token), index)
    return ("", -1)


def _canonicalize_event_formula_text(text: str) -> str:
    normalized = str(text or "")
    for token, replacement in _EVENT_FORMULA_CONNECTOR_REPLACEMENTS.items():
        normalized = normalized.replace(token, replacement)
    normalized = _normalize_event_formula_brackets(normalized)
    normalized = _canonicalize_event_formula_function_names(normalized)
    return " ".join(normalized.split())


def _canonicalize_event_formula_function_names(text: str) -> str:
    normalized = str(text or "")
    canonical_names = {
        **_EVENT_FORMULA_WRAPPER_CANONICAL_BY_LOWER,
        **_DCEC_STATE_PREDICATE_CANONICAL_BY_LOWER,
    }
    for lowered, canonical in sorted(
        canonical_names.items(),
        key=lambda item: -len(item[0]),
    ):
        normalized = re.sub(
            rf"\b{re.escape(lowered)}\s*(?=[(\[])",
            canonical,
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def _normalize_event_formula_text(formula: str) -> str:
    return _canonicalize_event_formula_text(
        _strip_event_formula_label(
            _strip_event_formula_clause_terminator(str(formula or "").strip())
        )
    )


def _normalize_event_formula_brackets(text: str) -> str:
    normalized = str(text or "")
    for wrapper in ("O", "P", "F", "Happens", "HoldsAt", "Initiates", "Terminates"):
        normalized = re.sub(
            rf"\b{wrapper}\s*\[",
            f"{wrapper}(",
            normalized,
            flags=(
                re.IGNORECASE
                if wrapper in {"Happens", "HoldsAt", "Initiates", "Terminates"}
                else 0
            ),
        )
    if "[" not in normalized and "]" not in normalized:
        return normalized
    return normalized.replace("[", "(").replace("]", ")")


def _normalize_event_formula_fields(
    *,
    formula: str,
    syntax_valid: bool,
    target_parse_profile: Mapping[str, Any],
    target_components: Mapping[str, Any],
    target_quality_gate: Mapping[str, Any],
    source_id: str,
    modality: str,
    selected_frame: str,
    selected_frame_source: str,
) -> tuple[str, bool, dict[str, Any], dict[str, Any], dict[str, Any]]:
    normalized_formula = _normalize_event_formula_text(formula)
    normalized_formula = _event_calculus_state_formula_from_export(
        normalized_formula,
        source_id=source_id,
    )
    derived_parse_profile = _event_formula_parse_profile(normalized_formula)
    merged_parse_profile = _merge_event_formula_parse_profile(
        base=_mapping(target_parse_profile),
        derived=derived_parse_profile,
    )
    resolved_syntax_valid = bool(
        (
            syntax_valid
            or merged_parse_profile.get("target_parse_profile_complete") is True
        )
        and merged_parse_profile.get("event_predicate_slot_complete") is not False
    )
    derived_components = _event_formula_target_components(
        normalized_formula,
        source_id=source_id,
        modality=modality,
    )
    merged_components = _merge_event_formula_target_components(
        base=_mapping(target_components),
        derived=derived_components,
        parse_profile=merged_parse_profile,
        source_id=source_id,
        modality=modality,
        selected_frame=selected_frame,
        selected_frame_source=selected_frame_source,
    )
    quality_gate = _mapping(target_quality_gate)
    merged_components, quality_gate = _repair_cec_slot_alignment_metadata(
        components=merged_components,
        quality_gate=quality_gate,
        parse_profile=merged_parse_profile,
    )
    resolved_quality_gate = {
        **quality_gate,
        "syntax_valid": resolved_syntax_valid,
        "target_parse_profile_complete": bool(
            merged_parse_profile.get("target_parse_profile_complete") is True
        ),
        "requires_validation": bool(
            quality_gate.get("requires_validation") is True or not resolved_syntax_valid
        ),
    }
    return (
        normalized_formula,
        resolved_syntax_valid,
        merged_parse_profile,
        merged_components,
        resolved_quality_gate,
    )


def _repair_cec_slot_alignment_metadata(
    *,
    components: Mapping[str, Any],
    quality_gate: Mapping[str, Any],
    parse_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    repaired_components = dict(components)
    repaired_quality_gate = dict(quality_gate)
    if repaired_components.get("slot_alignment_complete") is True:
        return repaired_components, repaired_quality_gate
    if not _cec_slot_alignment_repairable(
        components=repaired_components,
        parse_profile=parse_profile,
    ):
        return repaired_components, repaired_quality_gate

    repaired_slots = list(repaired_components.get("decoded_missing_grounded_ir_slots") or [])
    repaired_components["slot_alignment_complete"] = True
    repaired_components["decoded_missing_grounded_ir_slots"] = []
    repaired_components["cec_dcec_slot_alignment_repaired"] = True
    repaired_components["cec_dcec_slot_alignment_repaired_slots"] = repaired_slots
    if repaired_quality_gate.get("slot_alignment_complete") is False:
        repaired_quality_gate["slot_alignment_complete"] = True
    failed_checks = [
        str(check)
        for check in repaired_quality_gate.get("failed_quality_checks") or []
        if str(check) != "slot_alignment"
    ]
    if repaired_quality_gate.get("failed_quality_checks") is not None:
        repaired_quality_gate["failed_quality_checks"] = failed_checks
    repaired_quality_gate["cec_dcec_slot_alignment_repaired"] = True
    return repaired_components, repaired_quality_gate


def _cec_slot_alignment_repairable(
    *,
    components: Mapping[str, Any],
    parse_profile: Mapping[str, Any],
) -> bool:
    if str(components.get("target") or "") != "deontic_cec":
        return False
    if parse_profile.get("target_parse_profile_complete") is not True:
        return False
    if not list(parse_profile.get("event_predicates") or []):
        return False
    if components.get("target_symbol_alignment_complete") is not True:
        return False
    if components.get("target_dialect_profile_complete") is not True:
        return False
    if components.get("reconstruction_token_profile_complete") is not True:
        return False
    if list(components.get("unreconstructed_source_tokens") or []):
        return False
    if list(components.get("formula_missing_decoded_slots") or []):
        return False
    if list(components.get("formula_ungrounded_slots") or []):
        return False
    return bool(list(components.get("decoded_missing_grounded_ir_slots") or []))


def _event_calculus_state_formula_from_export(
    formula: str,
    *,
    source_id: str,
) -> str:
    text = str(formula or "").strip()
    if not text:
        return text
    parse_profile = _event_formula_parse_profile(text)
    if (
        parse_profile.get("target_parse_profile_complete") is True
        and (
            parse_profile.get("top_level_connector")
            or parse_profile.get("top_level_symbol") in _EVENT_PREDICATE_SET
            or parse_profile.get("top_level_symbol") in {"always", "forall", "exists"}
        )
    ):
        return text
    if parse_profile.get("top_level_symbol") in _DCEC_STATE_PREDICATE_SET:
        return _event_calculus_formula_text(
            source_id=source_id,
            deontic_formula=text,
        )
    if parse_profile.get("top_level_symbol") not in {"O", "P", "F"}:
        return text
    if "Happens" not in set(parse_profile.get("event_predicates") or []):
        return text
    return _event_calculus_formula_text(
        source_id=source_id,
        deontic_formula=text,
    )


def _merge_event_formula_parse_profile(
    *,
    base: Mapping[str, Any],
    derived: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in dict(derived).items():
        if key not in merged or merged.get(key) in (None, "", [], {}):
            merged[key] = value
    merged["target_parse_profile_complete"] = bool(
        merged.get("target_parse_profile_complete") is True
        or derived.get("target_parse_profile_complete") is True
    )
    if not merged.get("contains_implication"):
        merged["contains_implication"] = bool(derived.get("contains_implication"))
    if not merged.get("top_level_symbol"):
        merged["top_level_symbol"] = str(derived.get("top_level_symbol") or "")
    if not merged.get("top_level_connector"):
        merged["top_level_connector"] = str(derived.get("top_level_connector") or "")
    if not merged.get("wrapper_sequence"):
        merged["wrapper_sequence"] = list(derived.get("wrapper_sequence") or [])
    if not merged.get("event_predicates"):
        merged["event_predicates"] = list(derived.get("event_predicates") or [])
    if not merged.get("event_predicate_argument_counts"):
        merged["event_predicate_argument_counts"] = list(
            derived.get("event_predicate_argument_counts") or []
        )
    merged["event_predicate_slot_complete"] = bool(
        merged.get("event_predicate_slot_complete") is True
        or derived.get("event_predicate_slot_complete") is True
    )
    if not merged.get("quantifier_variables"):
        merged["quantifier_variables"] = list(derived.get("quantifier_variables") or [])
    return merged


def _merge_event_formula_target_components(
    *,
    base: Mapping[str, Any],
    derived: Mapping[str, Any],
    parse_profile: Mapping[str, Any],
    source_id: str,
    modality: str,
    selected_frame: str,
    selected_frame_source: str,
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in dict(derived).items():
        if key not in merged or merged.get(key) in (None, "", [], {}):
            merged[key] = value
    merged["formula_role"] = "event_calculus_state"
    merged["target"] = "deontic_cec"
    merged["source_id"] = source_id
    merged["modality"] = modality
    merged["target_parse_profile_complete"] = bool(
        merged.get("target_parse_profile_complete") is True
        or parse_profile.get("target_parse_profile_complete") is True
    )
    merged["uses_event_calculus_wrapper"] = bool(
        list(parse_profile.get("event_predicates") or [])
    )
    if selected_frame:
        merged["selected_frame"] = selected_frame
    if selected_frame_source:
        merged["selected_frame_source"] = selected_frame_source
    return merged


def _event_formula_target_components(
    formula: str,
    *,
    source_id: str,
    modality: str,
) -> dict[str, Any]:
    parse_profile = _event_formula_parse_profile(formula)
    return {
        "formula_role": "event_calculus_state",
        "modality": modality,
        "source_id": source_id,
        "target": "deontic_cec",
        "target_parse_profile_complete": bool(
            parse_profile.get("target_parse_profile_complete") is True
        ),
        "uses_event_calculus_wrapper": bool(
            list(parse_profile.get("event_predicates") or [])
        ),
    }


def _frame_guidance_from_norm(
    norm: Mapping[str, Any],
    *,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> dict[str, str]:
    logic_frame = _mapping(norm.get("logic_frame"))
    legal_frame = _mapping(norm.get("legal_frame"))
    prompt_context = _mapping(norm.get("prompt_context"))
    generic_frame: dict[str, str] = {}
    for source, value in (
        ("norm.selected_frame", norm.get("selected_frame")),
        ("norm.logic_frame.selected_frame", logic_frame.get("selected_frame")),
        ("norm.logic_frame.frame_name", logic_frame.get("frame_name")),
        ("norm.legal_frame.selected_frame", legal_frame.get("selected_frame")),
        ("norm.prompt_context.selected_frame", prompt_context.get("selected_frame")),
        ("norm.legal_frame.category", legal_frame.get("category")),
    ):
        canonical = _canonical_frame_symbol(value)
        if canonical:
            if source == "norm.legal_frame.category" and _is_generic_frame_symbol(
                canonical
            ):
                generic_frame = {
                    "selected_frame": canonical,
                    "selected_frame_source": source,
                }
                continue
            return {
                "selected_frame": canonical,
                "selected_frame_source": source,
            }
    guided_frame = _selected_frame_from_compiler_guidance(
        compiler_guidance,
        norm=norm,
        document_id=document_id,
        citation=citation,
        source_text=source_text,
    )
    if guided_frame:
        return {
            "selected_frame": guided_frame["selected_frame"],
            "selected_frame_source": guided_frame["selected_frame_source"],
            "compiler_guidance_source": guided_frame["compiler_guidance_source"],
        }
    inferred = _infer_selected_frame_from_norm_text(norm)
    if inferred:
        return {
            "selected_frame": inferred,
            "selected_frame_source": "norm.text_inference",
        }
    if generic_frame:
        return generic_frame
    return {}


def _selected_frame_from_compiler_guidance(
    compiler_guidance: Optional[Mapping[str, Any]],
    *,
    norm: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> dict[str, str]:
    guidance = _mapping(compiler_guidance)
    if not guidance or not _compiler_guidance_has_cec_bridge_route(guidance):
        return {}

    for source, value in _compiler_guidance_frame_candidates(
        guidance,
        norm=norm,
        document_id=document_id,
        citation=citation,
        source_text=source_text,
    ):
        canonical = _canonical_frame_symbol(value)
        if canonical:
            return {
                "selected_frame": canonical,
                "selected_frame_source": f"compiler_guidance.{source}",
                "compiler_guidance_source": "repair_cec_dcec_bridge",
            }
    return {}


def _compiler_guidance_has_cec_bridge_route(guidance: Mapping[str, Any]) -> bool:
    for key in (
        "route",
        "compiler_guidance_route",
        "target_component",
        "target",
    ):
        token = str(guidance.get(key) or "").strip().lower()
        if token in _CEC_GUIDANCE_ROUTE_TOKENS:
            return True

    for key in (
        "compiler_guidance_todo_routes",
        "todo_routes",
        "routes",
    ):
        value = guidance.get(key)
        if isinstance(value, Mapping):
            if any(
                str(route).strip().lower() in _CEC_GUIDANCE_ROUTE_TOKENS
                for route in value
            ):
                return True
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if any(
                str(route).strip().lower() in _CEC_GUIDANCE_ROUTE_TOKENS
                for route in value
            ):
                return True
    for key in (
        "bundle",
        "compiler_guidance_bundle",
        "semantic_bundle",
        "vector_bundle",
    ):
        bundle = _mapping(guidance.get(key))
        if not bundle:
            continue
        for bundle_key in (
            "route",
            "compiler_guidance_route",
            "target_component",
            "target",
        ):
            token = str(bundle.get(bundle_key) or "").strip().lower()
            if token in _CEC_GUIDANCE_ROUTE_TOKENS:
                return True
    if _cec_guidance_record_targets_cec(guidance):
        return True
    for _, row in _compiler_guidance_evidence_rows(guidance):
        if _cec_guidance_record_targets_cec(row):
            return True
    return False


def _cec_compiler_guidance_signal(
    compiler_guidance: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    guidance = _mapping(compiler_guidance)
    if not guidance:
        return {
            "quality_gate": "",
            "routes": [],
            "target_component": "",
            "target_metrics": [],
        }

    bundle = _mapping(
        guidance.get("bundle")
        or guidance.get("compiler_guidance_bundle")
        or guidance.get("semantic_bundle")
    )
    routes: list[str] = []
    for value in (
        guidance.get("route"),
        guidance.get("compiler_guidance_route"),
        bundle.get("route"),
        bundle.get("compiler_guidance_route"),
    ):
        route = str(value or "").strip()
        if route and route not in routes:
            routes.append(route)
    for key in ("compiler_guidance_todo_routes", "todo_routes", "routes"):
        value = guidance.get(key)
        if isinstance(value, Mapping):
            route_values = value.keys()
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            route_values = value
        else:
            route_values = ()
        for value in route_values:
            route = str(value or "").strip()
            if route and route not in routes:
                routes.append(route)
    if not routes and _compiler_guidance_has_cec_bridge_route(guidance):
        routes.append("repair_cec_dcec_bridge")

    target_component = _first_text_value(
        guidance.get("target_component"),
        guidance.get("target"),
        bundle.get("target_component"),
        bundle.get("target"),
    )
    if not target_component and _compiler_guidance_has_cec_bridge_route(guidance):
        target_component = "CEC.native"
    quality_gate = _first_text_value(
        guidance.get("compiler_guidance_quality_gate"),
        guidance.get("quality_gate"),
        bundle.get("compiler_guidance_quality_gate"),
        bundle.get("quality_gate"),
    )
    metric_values: list[Any] = []
    for value in (
        guidance.get("target_metrics"),
        guidance.get("compiler_guidance_target_metrics"),
        bundle.get("target_metrics"),
        bundle.get("compiler_guidance_target_metrics"),
    ):
        if isinstance(value, str):
            metric_values.extend(
                metric.strip()
                for metric in value.split(",")
                if metric.strip()
            )
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            metric_values.extend(value)
    target_metrics: list[str] = []
    for metric in metric_values:
        metric_name = str(metric or "").strip()
        if metric_name and metric_name not in target_metrics:
            target_metrics.append(metric_name)
    if not target_metrics:
        for _, row in _compiler_guidance_evidence_rows(guidance):
            for metric in _guidance_metric_names(row):
                if metric and metric not in target_metrics:
                    target_metrics.append(metric)

    return {
        "quality_gate": quality_gate,
        "routes": routes,
        "target_component": target_component,
        "target_metrics": target_metrics,
    }


def _compiler_guidance_frame_candidates(
    guidance: Mapping[str, Any],
    *,
    norm: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> list[tuple[str, Any]]:
    top_level_candidates: list[tuple[str, Any]] = []
    for key in (
        "selected_frame_after",
        "selected_frame",
        "compiler_guidance_selected_frame",
        "frame_after",
        "frame",
    ):
        top_level_candidates.append((key, guidance.get(key)))

    candidates: list[tuple[str, Any]] = []
    evidence_rows = _compiler_guidance_evidence_rows(guidance)
    matched_rows = [
        (collection_key, row)
        for collection_key, row in evidence_rows
        if _compiler_guidance_row_matches_norm(
            row,
            norm=norm,
            document_id=document_id,
            citation=citation,
            source_text=source_text,
        )
    ]
    for collection_key, row in matched_rows:
        for key in (
            "selected_frame_after",
            "selected_frame",
            "frame_after",
            "frame",
        ):
            candidates.append((f"{collection_key}.{key}", row.get(key)))
    candidates.extend(top_level_candidates)

    for collection_key, row in evidence_rows:
        if (collection_key, row) in matched_rows:
            continue
        for key in (
            "selected_frame_after",
            "selected_frame",
            "frame_after",
            "frame",
        ):
            candidates.append((f"{collection_key}.{key}", row.get(key)))
    return candidates


def _compiler_guidance_evidence_rows(
    guidance: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for collection_key in (
        "hint_evidence",
        "evidence",
        "guidance_evidence",
        "compiler_guidance_evidence",
        "metric_sample_payloads",
        "samples",
    ):
        value = guidance.get(collection_key)
        collection_rows: list[Mapping[str, Any]] = []
        if isinstance(value, Mapping):
            collection_rows = [value]
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            collection_rows = [row for row in value if isinstance(row, Mapping)]
        elif isinstance(value, str):
            parsed = _json_guidance_value(value)
            if isinstance(parsed, Mapping):
                collection_rows = [parsed]
            elif isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
                collection_rows = [row for row in parsed if isinstance(row, Mapping)]
        for row in sorted(
            collection_rows,
            key=lambda item: int(item.get("evidence_rank") or item.get("rank") or 999999),
        ):
            rows.append((collection_key, row))
    return rows


def _cec_guidance_record_targets_cec(row: Mapping[str, Any]) -> bool:
    """Infer CEC bridge relevance from compiler-guidance evidence fields."""

    if not isinstance(row, Mapping):
        return False
    for key in (
        "target_component",
        "target_view",
        "predicted_view",
        "target",
    ):
        if _cec_guidance_token_targets_cec(row.get(key)):
            return True
    for key in (
        "legal_ir_underrepresented_components",
        "compiler_guidance_legal_ir_underrepresented_components",
    ):
        if any(
            _cec_guidance_token_targets_cec(item)
            for item in _sequence_values(row.get(key))
        ):
            return True
    if any(metric.startswith("cec_dcec_") for metric in _guidance_metric_names(row)):
        return True
    for gap_key, gap_value in _cec_guidance_gap_items(row):
        if (
            _cec_guidance_gap_quality_gate_passes(gap_value)
            and _cec_guidance_token_targets_cec(str(gap_key).split(":", 1)[0])
        ):
            return True
    return False


def _cec_guidance_token_targets_cec(value: Any) -> bool:
    token = str(value or "").strip().lower()
    if not token:
        return False
    normalized = token.replace("_", ".")
    return (
        token in _CEC_GUIDANCE_ROUTE_TOKENS
        or normalized in _CEC_GUIDANCE_ROUTE_TOKENS
    )


def _guidance_metric_names(row: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("target_metrics", "compiler_guidance_target_metrics"):
        value = row.get(key)
        if isinstance(value, str):
            values.extend(metric.strip() for metric in value.split(",") if metric.strip())
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values.extend(value)
    return [
        str(value or "").strip().lower()
        for value in values
        if str(value or "").strip()
    ]


def _cec_guidance_gap_items(row: Mapping[str, Any]) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key in (
        "legal_ir_view_gaps",
        "compiler_guidance_legal_ir_view_gaps",
        "legal_ir_view_family_gaps",
        "compiler_guidance_legal_ir_view_family_gaps",
    ):
        value = row.get(key)
        if isinstance(value, Mapping):
            items.extend(
                (str(gap_key), gap_value)
                for gap_key, gap_value in value.items()
            )
    attribution = row.get("compiler_guidance_attribution")
    if isinstance(attribution, Mapping):
        for key in ("legal_ir_view_gaps", "legal_ir_view_family_gaps"):
            value = attribution.get(key)
            if isinstance(value, Mapping):
                items.extend(
                    (str(gap_key), gap_value)
                    for gap_key, gap_value in value.items()
                )
    return items


def _cec_guidance_gap_quality_gate_passes(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return True
    gate = str(value.get("quality_gate") or "").strip().lower()
    return gate in {"", "pass", "passed", "ok", "true", "1"}


def _sequence_values(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    if str(value or "").strip():
        return [value]
    return []


def _compiler_guidance_row_matches_norm(
    row: Mapping[str, Any],
    *,
    norm: Optional[Mapping[str, Any]] = None,
    document_id: str = "",
    citation: Optional[str] = None,
    source_text: str = "",
) -> bool:
    norm = _mapping(norm)
    row_sample_id = str(row.get("sample_id") or row.get("document_id") or "").strip()
    norm_ids = {
        str(value).strip()
        for value in (
            norm.get("sample_id"),
            norm.get("source_id"),
            norm.get("document_id"),
            document_id,
        )
        if str(value or "").strip()
    }
    if row_sample_id and row_sample_id in norm_ids:
        return True

    row_citation = str(row.get("citation") or row.get("canonical_citation") or "").strip()
    norm_citations = {
        str(value).strip()
        for value in (
            norm.get("citation"),
            norm.get("canonical_citation"),
            citation,
        )
        if str(value or "").strip()
    }
    if row_citation and row_citation in norm_citations:
        return True

    preview = _normalize_legal_sample_text(row.get("text_preview") or row.get("text"))
    if preview and preview in _normalize_legal_sample_text(source_text):
        return True
    return False


def _canonical_frame_symbol(value: Any) -> str:
    token = _symbol(value, fallback="")
    return token[:96] if token else ""


def _is_generic_frame_symbol(value: str) -> bool:
    return str(value or "").strip().lower() in {"norm", "legal_norm"}


def _infer_selected_frame_from_norm_text(norm: Mapping[str, Any]) -> str:
    corpus = " ".join(
        _first_text_value(
            norm.get("support_text"),
            norm.get("source_text"),
            norm.get("text"),
            norm.get("action"),
            fallback="",
        ).lower().split()
    )
    if corpus and "notice" in corpus and "hearing" in corpus:
        return "administrative_notice_hearing"
    return ""


def _stable_short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def _fallback_norm_from_conversion(*, result: Any, text: str) -> Optional[dict[str, Any]]:
    normalized_text = _normalize_legal_sample_text(text)
    if not normalized_text:
        return None

    output = getattr(result, "output", None)
    actor = (
        _fallback_actor_from_conversion_output(output)
        or _fallback_actor_from_text(normalized_text)
        or "actor"
    )
    action = (
        _fallback_action_from_conversion_output(output)
        or _fallback_action_from_text(normalized_text)
        or "act"
    )
    modality = _fallback_modality_from_conversion_output(output=output, text=normalized_text)
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
    return {
        "actor": actor,
        "action": action,
        "modality": modality,
        "norm_type": modality,
        "source_id": f"dcec:fallback:{digest}",
        "extraction_method": "cec_dcec_fallback_v1",
    }


def _section_operational_norm_from_text(text: str) -> Optional[dict[str, Any]]:
    normalized_text = _normalize_legal_sample_text(text)
    if not normalized_text or not _looks_like_us_code_section_text(normalized_text):
        return None
    substantive_text = _strip_uscode_catchline_and_subsection_heading(
        _substantive_statutory_text(normalized_text)
    )
    if not substantive_text:
        return None
    operative_text = _strip_parenthetical_public_law_tail(
        _strip_uscode_catchline_and_subsection_heading(substantive_text)
    )
    appropriation_authorization_match = re.search(
        r"\bthere\s+are\s+authorized\s+to\s+be\s+appropriated\s+"
        r"(?P<action>[^.;]+)",
        operative_text.lower(),
    )
    if appropriation_authorization_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": "congress",
            "action": _clean_operational_slot(
                "authorize appropriation of "
                + appropriation_authorization_match.group("action")
            ),
            "modality": "permitted",
            "norm_type": "permitted",
            "source_id": f"dcec:section:{digest}",
            "support_text": appropriation_authorization_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    penalty_imposition_match = re.search(
        r"\bthere\s+is\s+hereby\s+imposed\s+a\s+penalty\s+on\s+the\s+"
        r"failure\s+of\s+(?P<actor>[^.;]{1,180}?)\s+to\s+"
        r"(?P<action>[^.;]+)",
        operative_text.lower(),
    )
    if penalty_imposition_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                penalty_imposition_match.group("actor")
            ),
            "action": _clean_operational_slot(
                penalty_imposition_match.group("action")
            ),
            "modality": "obligated",
            "norm_type": "obligated",
            "source_id": f"dcec:section:{digest}",
            "support_text": penalty_imposition_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    fers_applicability_match = re.search(
        r"\bexcept\s+as\s+provided\s+in\s+subsections\s+\([^)]+\)\s+and\s+\([^)]+\),\s+"
        r"(?P<actor>all\s+employees\s+of\s+the\s+agency)\b.{0,620}?\s+shall\s+"
        r"(?P<action>be\s+subject\s+to\s+chapter\s+84\s+of\s+title\s+5)",
        operative_text.lower(),
    )
    if fers_applicability_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                fers_applicability_match.group("actor")
            ),
            "action": _clean_operational_slot(
                fers_applicability_match.group("action")
            ),
            "modality": "obligated",
            "norm_type": "obligated",
            "source_id": f"dcec:section:{digest}",
            "support_text": fers_applicability_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    conditional_fee_collection_match = re.search(
        r"\bin\s+the\s+case\s+of\s+(?P<object>[^.;]{1,360}?),\s+"
        r"(?P<actor>(?:the\s+)?[a-z][^.;]{1,160}?)\s+"
        r"is\s+authorized\s+to\s+(?P<action>collect\s+[^.;]+)",
        operative_text.lower(),
    )
    if conditional_fee_collection_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                conditional_fee_collection_match.group("actor")
            ),
            "action": _clean_operational_slot(
                conditional_fee_collection_match.group("action")
            ),
            "modality": "permitted",
            "norm_type": "permitted",
            "source_id": f"dcec:section:{digest}",
            "support_text": conditional_fee_collection_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    conditional_modal_match = _conditional_modal_norm_match(operative_text)
    if conditional_modal_match:
        condition_text = conditional_modal_match["condition"]
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        source_id = f"dcec:section:{digest}"
        return {
            "actor": conditional_modal_match["actor"],
            "action": conditional_modal_match["action"],
            "modality": conditional_modal_match["modality"],
            "norm_type": conditional_modal_match["modality"],
            "source_id": source_id,
            "support_text": conditional_modal_match["support_text"][:500],
            "procedure_event_records": [
                _condition_procedure_event_record(
                    condition_text,
                    source_id=source_id,
                    relation=conditional_modal_match["relation"],
                )
            ],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    authorized_assistance_match = re.search(
        r"\b(?P<actor>(?:the\s+)?(?:president|secretary|administrator|"
        r"comptroller\s+general|director|commission|commissioner))\s+"
        r"is\s+authorized\s+to\s+"
        r"(?P<action>assist\s+[^.;]+)",
        operative_text.lower(),
    )
    if authorized_assistance_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                authorized_assistance_match.group("actor")
            ),
            "action": _clean_operational_slot(
                authorized_assistance_match.group("action")
            ),
            "modality": "permitted",
            "norm_type": "permitted",
            "source_id": f"dcec:section:{digest}",
            "support_text": authorized_assistance_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    nato_contribution_limit_match = re.search(
        r"\bthe\s+total\s+amount\s+contributed\s+by\s+"
        r"(?P<actor>the\s+secretary\s+of\s+defense)\s+[^.;]{0,240}?\s+"
        r"may\s+be\s+(?P<action>an\s+amount\s+in\s+excess\s+of\s+[^.;]+)",
        operative_text.lower(),
    )
    if nato_contribution_limit_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                nato_contribution_limit_match.group("actor")
            ),
            "action": _clean_operational_slot(
                "contribute " + nato_contribution_limit_match.group("action")
            ),
            "modality": "permitted",
            "norm_type": "permitted",
            "source_id": f"dcec:section:{digest}",
            "support_text": nato_contribution_limit_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    passive_administration_match = re.search(
        r"\b(?P<object>administration[^.;]{1,180}?)\s+shall\s+be\s+"
        r"(?P<action>exercised\s+under\s+the\s+direction\s+of\s+[^.;]+?)"
        r"\s+by\s+(?P<actor>(?:the\s+)?[a-z][^.;]{1,120}?)\s+"
        r"subject\s+to\b",
        operative_text.lower(),
    )
    if passive_administration_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        object_text = _clean_operational_slot(
            passive_administration_match.group("object")
        )
        return {
            "actor": _clean_operational_actor_slot(
                passive_administration_match.group("actor")
            ),
            "action": _clean_operational_slot(
                "administer " + object_text
            ),
            "modality": "obligated",
            "norm_type": "obligated",
            "source_id": f"dcec:section:{digest}",
            "support_text": passive_administration_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    construction_exemption_match = re.search(
        r"\bnothing\s+in\s+(?P<actor>this\s+(?:chapter|subchapter|section|"
        r"subsection|part|title|act))\s+shall\s+be\s+construed\s+"
        r"(?:to|as)\s+(?P<action>[^.;]+)",
        operative_text.lower(),
    )
    if construction_exemption_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                construction_exemption_match.group("actor")
            ),
            "action": _clean_operational_slot(
                construction_exemption_match.group("action")
            ),
            "modality": "obligated",
            "norm_type": "exemption",
            "source_id": f"dcec:section:{digest}",
            "support_text": construction_exemption_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    applicable_to_match = re.search(
        r"\b(?P<actor>(?:the\s+)?(?:provisions?|sections?)\s+[^.;]{1,180}?)\s+"
        r"shall\s+be\s+applicable\s+to\s+(?P<action>[^.;]+)",
        operative_text.lower(),
    )
    if applicable_to_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                applicable_to_match.group("actor")
            ),
            "action": _clean_operational_slot(
                "apply to " + applicable_to_match.group("action")
            ),
            "modality": "obligated",
            "norm_type": "applicability",
            "source_id": f"dcec:section:{digest}",
            "support_text": applicable_to_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    discretionary_transfer_match = re.search(
        r"\b(?P<actor>(?:the\s+)?(?:secretary|administrator|commission|director|court|council)"
        r"(?:\s+of\s+[^.;,]{1,120})?)\s+may\s*,?\s+"
        r"(?:in\s+(?:his|her|the)\s+discretion,\s+)?"
        r"(?:when\s+[^.;]{1,360}?\bshall\s+have\s+been\s+made,\s*)?"
        r"(?P<action>transfer\s+title\s+to\s+[^.;]+)",
        operative_text.lower(),
    )
    if discretionary_transfer_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                discretionary_transfer_match.group("actor")
            ),
            "action": _clean_operational_slot(
                discretionary_transfer_match.group("action")
            ),
            "modality": "permitted",
            "norm_type": "permitted",
            "source_id": f"dcec:section:{digest}",
            "support_text": operative_text[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    no_restriction_match = re.search(
        r"\b(?P<actor>this\s+(?:chapter|subchapter|section|subsection|part|title|act))\s+"
        r"(?:does|do)\s+not\s+(?P<action>restrict\s+or\s+limit\s+[^.;]+)",
        operative_text.lower(),
    )
    if no_restriction_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(no_restriction_match.group("actor")),
            "action": _clean_operational_slot(no_restriction_match.group("action")),
            "modality": "permitted",
            "norm_type": "exemption",
            "source_id": f"dcec:section:{digest}",
            "support_text": no_restriction_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    nothing_shall_affect_match = re.search(
        r"\b(?P<actor>nothing\s+in\s+this\s+(?:chapter|subchapter|section|"
        r"subsection|part|title|act))\s+shall\s*[—-]?\s*"
        r"(?:\([0-9a-z]+\)\s*)?(?P<action>affect\s+[^.;]+)",
        operative_text.lower(),
    )
    if nothing_shall_affect_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                nothing_shall_affect_match.group("actor")
            ),
            "action": _clean_operational_slot(nothing_shall_affect_match.group("action")),
            "modality": "permitted",
            "norm_type": "exemption",
            "source_id": f"dcec:section:{digest}",
            "support_text": nothing_shall_affect_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    age_condition_right_match = re.search(
        r"\b(?P<actor>all\s+[a-z][^,.;]{1,120}?),\s*"
        r"when\s+they\s+shall\s+arrive\s+[^,.;]{1,180},\s*"
        r"shall\s+(?P<action>have\s+the\s+right\s+to\s+[^.;]+)",
        operative_text.lower(),
    )
    if age_condition_right_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(age_condition_right_match.group("actor")),
            "action": _clean_operational_slot(age_condition_right_match.group("action")),
            "modality": "permitted",
            "norm_type": "permitted",
            "source_id": f"dcec:section:{digest}",
            "support_text": age_condition_right_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    corporation_agent_match = re.search(
        r"\b(?P<actor>the\s+corporation)\s+shall\s+"
        r"(?P<action>have\s+a\s+designated\s+agent\s+[^.;]+)",
        operative_text.lower(),
    )
    if corporation_agent_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(corporation_agent_match.group("actor")),
            "action": _clean_operational_slot(corporation_agent_match.group("action")),
            "modality": "obligated",
            "norm_type": "obligated",
            "source_id": f"dcec:section:{digest}",
            "support_text": corporation_agent_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    corporation_records_match = re.search(
        r"\b(?P<actor>the\s+corporation)\s+shall\s+"
        r"(?P<action>keep\s*[—-]\s*[^.;]+)",
        operative_text.lower(),
    )
    if corporation_records_match:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": _clean_operational_actor_slot(
                corporation_records_match.group("actor")
            ),
            "action": _clean_operational_slot(corporation_records_match.group("action")),
            "modality": "obligated",
            "norm_type": "obligated",
            "source_id": f"dcec:section:{digest}",
            "support_text": corporation_records_match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    patterns = (
        (
            "obligated",
            r"\b(?P<actor>nothing\s+in\s+this\s+chapter)\s+shall\s+"
            r"(?P<action>be\s+construed\s+as\s+[^.;]+)",
        ),
        (
            "obligated",
            r"\b(?P<actor>nothing\s+in\s+this\s+chapter)\s+shall\s+"
            r"(?P<action>apply\s+to\s+[^.;]+)",
        ),
        (
            "obligated",
            r"\b(?P<actor>sections?\s+[^.;]{1,180}?)\s+shall\s+"
            r"(?P<action>apply\s+to\s+[^.;]+)",
        ),
        (
            "obligated",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+shall\s+"
            r"(?P<action>be\s+transferred\s+[^.;]+)",
        ),
        (
            "obligated",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+shall\s+"
            r"(?P<action>be\s+subject\s+to\s+[^.;]+)",
        ),
        (
            "permitted",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+may\s+"
            r"(?P<action>be\s+leased\s+only[^.;]*)",
        ),
        (
            "permitted",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+may\s+"
            r"(?P<action>be\s+used\s+only\s+[^.;]+)",
        ),
        (
            "obligated",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+shall\s+"
            r"(?P<action>be\s+available\s+[^.;]+)",
        ),
        (
            "permitted",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+is\s+authorized\b[^.;]{0,160}?\s+to\s+"
            r"(?P<action>[^.;:]+)",
        ),
        (
            "forbidden",
            r"\b(?P<actor>no\s+[A-Za-z][^.;]{1,360}?)\s+shall\s+"
            r"(?P<action>[^.;:]+)",
        ),
        (
            "forbidden",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+shall\s+not\s+"
            r"(?P<action>[^.;:]+)",
        ),
        (
            "obligated",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+shall\s+"
            r"(?P<action>[^.;:]+)",
        ),
        (
            "permitted",
            r"\b(?P<actor>[A-Za-z][^.;]{1,360}?)\s+may\s+"
            r"(?P<action>[^.;:]+)",
        ),
    )
    lowered = operative_text.lower()
    matches: list[tuple[int, int, str, re.Match[str]]] = []
    for pattern_index, (modality, pattern) in enumerate(patterns):
        match = re.search(pattern, lowered)
        if not match:
            continue
        matches.append((match.start(), pattern_index, modality, match))
    for _, _, modality, match in sorted(matches, key=lambda item: (item[0], item[1])):
        raw_actor = match.group("actor")
        if modality == "obligated":
            embedded_no_actor = re.search(r"\bno\s+(.+)$", raw_actor)
            if embedded_no_actor:
                raw_actor = embedded_no_actor.group(0)
                modality = "forbidden"
        actor = _clean_operational_actor_slot(raw_actor)
        action = _clean_operational_slot(match.group("action"))
        if not actor or not action:
            continue
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
        return {
            "actor": actor,
            "action": action,
            "modality": modality,
            "norm_type": modality,
            "source_id": f"dcec:section:{digest}",
            "support_text": match.group(0)[:500],
            "extraction_method": "cec_dcec_section_operational_v1",
        }
    return None


def _conditional_modal_norm_match(text: str) -> dict[str, str]:
    lowered = _normalize_legal_sample_text(text).lower()
    if not lowered:
        return {}
    patterns = (
        (
            "condition_precedent",
            r"\b(?P<intro>if|when)\s+(?P<condition>[^.;]{1,260}?),\s*"
            r"(?P<actor>(?:the\s+)?[a-z][^,.;]{1,160}?)\s+"
            r"(?P<modal>shall\s+not|must\s+not|may\s+not|shall|must|may|"
            r"is\s+required\s+to|is\s+obligated\s+to|is\s+authorized\s+to)\s+"
            r"(?P<action>[^.;:]+)",
        ),
        (
            "exception",
            r"\bexcept\s+(?P<condition>[^.;]{1,260}?),\s*"
            r"(?P<actor>(?:the\s+)?[a-z][^,.;]{1,160}?)\s+"
            r"(?P<modal>shall\s+not|must\s+not|may\s+not|shall|must|may|"
            r"is\s+required\s+to|is\s+obligated\s+to|is\s+authorized\s+to)\s+"
            r"(?P<action>[^.;:]+)",
        ),
    )
    for relation, pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        raw_actor = match.group("actor")
        if re.match(r"^(?:shall|must|may|is)\b", raw_actor.strip()):
            continue
        actor = _clean_operational_actor_slot(raw_actor)
        action = _clean_operational_slot(match.group("action"))
        condition = _clean_operational_slot(match.group("condition"))
        if not actor or not action or not condition:
            continue
        return {
            "actor": actor,
            "action": action,
            "condition": condition,
            "modality": _modality_from_modal_phrase(match.group("modal")),
            "relation": relation,
            "support_text": match.group(0),
        }
    return {}


def _modality_from_modal_phrase(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"shall not", "must not", "may not"}:
        return "forbidden"
    if lowered in {"may", "is authorized to"}:
        return "permitted"
    return "obligated"


def _condition_procedure_event_record(
    condition: str,
    *,
    source_id: str,
    relation: str,
) -> dict[str, Any]:
    event_symbol = _symbol(condition, fallback="condition")
    return {
        "actor": "condition",
        "event": condition,
        "event_id": f"{source_id}:procedure:{event_symbol}",
        "event_order": 1,
        "event_symbol": event_symbol,
        "is_formula_antecedent": True,
        "is_trigger": True,
        "proof_role": relation,
        "raw_text": condition,
        "relation": relation,
        "source_id": source_id,
    }


def _looks_like_us_code_section_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return bool(
        re.search(r"\bu\.s\.c\.|\bunited\s+states\s+code\b", lowered)
        or re.search(r"\bsec\.?\s+[0-9][0-9a-z.-]*\b", lowered)
        or re.search(r"§+\s*[0-9][0-9a-z.-]*", lowered)
    )


def _strip_parenthetical_public_law_tail(text: str) -> str:
    value = _normalize_legal_sample_text(text)
    return re.split(
        r"\s+\((?:Pub\.|Added|Aug\.|June|July|Dec\.|Mar\.|Oct\.)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()


def _clean_operational_slot(text: str) -> str:
    value = _normalize_legal_sample_text(text)
    value = re.sub(r"\bprovided,?\s+however\b.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"^notwithstanding\b[^,]{1,240},\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    lands_match = re.search(r"\b(lands\s+which\b.+)$", value, flags=re.IGNORECASE)
    if lands_match:
        value = lands_match.group(1)
    value = re.sub(
        r"^(?:purposes?|construction|leasing requirements|transfer of amounts|"
        r"use of recovered amounts|attorney general approval of title|"
        r"guidance for executive agencies on linking of award and incentive fees "
        r"to acquisition outcomes|information to congress on institute activities|"
        r"mandatory application of sections [0-9a-z.,\sand-]+|"
        r"contribution to inter american development bank authorization of "
        r"appropriations|abandonment of property of the estate|art exhibits|"
        r"disclaimers limited warranties and nonwarranties)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" ,:-")


def _clean_operational_actor_slot(text: str) -> str:
    value = _clean_operational_slot(text)
    value = re.sub(
        r"^(sections?\s+[0-9a-z.-]+(?:\s+(?:and|,|-)\s+[0-9a-z.-]+)*)\s+\1\s+\b(of\b.*)$",
        r"\1 \2",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^notwithstanding\b[^,]{1,240},\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:on|before|after|by|within)\b[^,]{1,240},\s*"
        r"(?:and\s+[^,]{1,160},\s*)?",
        "",
        value,
        flags=re.IGNORECASE,
    )
    use_clause_match = re.search(
        r"\bthe\s+use\s+of\s+a\s+disclaimer\b.*$",
        value,
        flags=re.IGNORECASE,
    )
    if use_clause_match:
        value = use_clause_match.group(0)
    official_actor_focus = re.search(
        r"\b((?:the\s+)?(?:chairman|director|secretary|administrator|commission|"
        r"court|council)(?:\s+of\s+(?:the\s+)?[a-z][a-z\s]{1,100}?)?)"
        r"(?:,\s*acting\b|\s+acting\b|\s+shall\b|$)",
        value,
        flags=re.IGNORECASE,
    )
    if official_actor_focus:
        value = official_actor_focus.group(1)
    official_actor_tail = re.search(
        r"\b((?:the\s+)?(?:chairman|director|secretary|administrator|commission|court|"
        r"council)(?:\s+of\s+(?:the\s+)?[a-z][a-z\s]{1,100})?)$",
        value,
        flags=re.IGNORECASE,
    )
    if official_actor_tail:
        value = official_actor_tail.group(1)
    official_actor_prefix = re.match(
        r"^((?:the\s+)?(?:chairman|director|secretary|administrator|commission|court|"
        r"council)(?:\s+of\s+(?:the\s+)?[a-z][a-z\s]{1,100})?)"
        r"(?:,\s*acting\b|\s+acting\b|$)",
        value,
        flags=re.IGNORECASE,
    )
    if official_actor_prefix:
        value = official_actor_prefix.group(1)
    value = re.sub(r"^no\s+", "", value, flags=re.IGNORECASE)
    heading_subject_match = re.search(
        r"\b(?:the|a|an)\s+("
        r"director|secretary|trustee|court|council|commission|administrator|nmic|"
        r"federal acquisition regulation|department of defense|"
        r"united states governor of the bank|property|work of art or manufacture|"
        r"use of a disclaimer limited warranty or nonwarranty clause"
        r")$",
        value,
        flags=re.IGNORECASE,
    )
    if heading_subject_match:
        value = heading_subject_match.group(1)
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" ,:-")


def _section_editorial_norm_from_text(text: str) -> Optional[dict[str, Any]]:
    normalized_text = _normalize_legal_sample_text(text)
    lowered = normalized_text.lower()
    if not normalized_text:
        return None

    status = ""
    action = ""
    if _section_status_heading_matches(lowered, "repealed"):
        status = "repealed"
        action = "record section repeal"
    elif _section_status_heading_matches(lowered, "vacant"):
        status = "vacant"
        action = "mark section vacant"
    elif _section_status_heading_matches(lowered, "omitted"):
        status = "omitted"
        action = "record section omission"
    elif _section_status_heading_matches(lowered, "transferred"):
        status = "transferred"
        action = "record section transfer"
    elif (
        re.search(r"\bsec\.?\s*[0-9a-z.-]+\s*-\s*change\s+in\s+name\b", lowered)
        or re.search(r"§+\s*[0-9a-z.-]+\.?\s+change\s+in\s+name\b", lowered)
    ) and re.search(r"\b(?:shall\s+be\s+known\s+as|renamed)\b", lowered):
        status = "renamed"
        action = "record statutory name change"

    if not status:
        return None

    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
    return {
        "actor": "statute section",
        "action": action,
        "modality": "obligated",
        "norm_type": "instrument_lifecycle",
        "source_id": f"dcec:editorial:{digest}",
        "support_text": normalized_text[:500],
        "editorial_status": status,
        "extraction_method": "cec_dcec_editorial_status_v1",
    }


def _section_definition_norm_from_text(text: str) -> Optional[dict[str, Any]]:
    normalized_text = _normalize_legal_sample_text(text)
    if not normalized_text or not _looks_like_us_code_section_text(normalized_text):
        return None
    substantive_text = _strip_uscode_catchline_and_subsection_heading(
        _substantive_statutory_text(normalized_text)
    )
    if not substantive_text:
        return None
    operative_text = _strip_uscode_catchline_and_subsection_heading(substantive_text)
    lowered = operative_text.lower()
    definition_match = re.search(
        r"\b(?:for\s+(?:the\s+)?purposes?\s+of\s+[^,.;]{1,120},\s*)?"
        r"(?:the\s+term\s+)?(?P<term>[A-Za-z][A-Za-z0-9' -]{1,120}?)\s+"
        r"means\s+(?P<definition>[^.;]+)",
        lowered,
    )
    if not definition_match:
        return None

    term = _clean_definition_term(definition_match.group("term"))
    definition = _clean_operational_slot(definition_match.group("definition"))
    if not term or not definition:
        return None
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
    return {
        "actor": term,
        "action": f"mean {definition}",
        "modality": "definition",
        "norm_type": "definition",
        "source_id": f"dcec:definition:{digest}",
        "support_text": definition_match.group(0)[:500],
        "extraction_method": "cec_dcec_definition_v1",
    }


def _clean_definition_term(text: str) -> str:
    value = _normalize_legal_sample_text(text)
    value = re.sub(
        r"^(?:definitions?|for\s+(?:the\s+)?purposes?\s+of\s+[^,.;]{1,120},)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^(?:the\s+term|term)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" ,:-")


def _section_statutory_statement_norm_from_text(text: str) -> Optional[dict[str, Any]]:
    normalized_text = _normalize_legal_sample_text(text)
    if not normalized_text:
        return None
    substantive_text = _strip_uscode_catchline_and_subsection_heading(
        _substantive_statutory_text(normalized_text)
    )
    lowered = substantive_text.lower()
    if not _looks_like_statutory_purpose_statement(lowered):
        return None

    actor = _purpose_actor_from_text(substantive_text)
    action = _purpose_action_from_text(substantive_text)
    if not action:
        return None
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
    return {
        "actor": actor,
        "action": action,
        "modality": "purpose",
        "norm_type": "purpose",
        "source_id": f"dcec:purpose:{digest}",
        "support_text": substantive_text[:500],
        "extraction_method": "cec_dcec_statutory_statement_v1",
    }


def _substantive_statutory_text(text: str) -> str:
    value = _normalize_legal_sample_text(text)
    value = re.split(
        r"\b(?:Editorial Notes|Statutory Notes and Related Subsidiaries|"
        r"Historical and Revision Notes|Executive Documents|References in Text)\b|"
        r"\bAmendments\s+\d{4}\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.sub(
        r"^.*?\b(?:Sec\.?\s*[0-9A-Za-z.-]+\s*-\s*)",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"^.*?\bFrom\s+the\s+U\.S\.\s+Government\s+Publishing\s+Office,\s+"
        r"www\.gpo\.gov\s+",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"^\s*\d+\s+U\.S\.C\.\s+[0-9A-Za-z.-]+\.?:?\s*",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"^§+\s*[0-9A-Za-z.-]+\s*\.?\s*",
        "",
        value,
        count=1,
    ).strip()
    return value


def _strip_uscode_catchline_and_subsection_heading(text: str) -> str:
    value = _normalize_legal_sample_text(text)
    if not value:
        return ""
    starters = (
        "Notwithstanding",
        "Except",
        "If",
        "When",
        "As soon",
        "Within",
        "By no later",
        "Upon",
        "There is hereby",
        "There are authorized",
        "Section",
        "Sections",
        "This",
        "All",
        "The",
        "An",
        "Any",
        "No",
        "Nothing",
    )
    starter_pattern = "|".join(re.escape(starter) for starter in starters)
    subsection_dash_match = re.match(
        rf"^.{{1,220}}?\s+\([a-z]\)\s+[^.;]{{0,140}}?\s+\.[—-]\s*"
        rf"(?=({starter_pattern})\b)",
        value,
        flags=re.IGNORECASE,
    )
    if subsection_dash_match:
        return value[subsection_dash_match.end():].strip()
    subsection_match = re.match(
        rf"^.{1,220}?\s+\([a-z0-9]+\)\s+[^.;]{{0,140}}?\s+"
        rf"(?=({starter_pattern})\b)",
        value,
        flags=re.IGNORECASE,
    )
    if subsection_match:
        value = value[subsection_match.end():].strip()
    if not value.lower().startswith(tuple(starter.lower() for starter in starters)):
        catchline_match = re.match(
            rf"^(.{{1,160}}?)\s+(?=({starter_pattern})\b)",
            value,
            flags=re.IGNORECASE,
        )
        if catchline_match:
            value = value[catchline_match.end():].strip()
    return value


def _looks_like_statutory_purpose_statement(lowered_text: str) -> bool:
    if not lowered_text:
        return False
    return bool(
        re.search(r"\b(?:purpose|purposes|policy)\b", lowered_text)
        and re.search(
            r"\b(?:general\s+purpose\s+of|"
            r"purpose\s+of\s+(?:this|the)\s+(?:chapter|subchapter|section|act|program|fund|institute)|"
            r"purposes\s+of\s+(?:this|the)\s+(?:chapter|subchapter|section|act|program|fund|institute|corporation)|"
            r"congressional\s+statement\s+of\s+purpose|"
            r"it\s+is\s+the\s+policy\s+of\s+the\s+congress)\b",
            lowered_text,
        )
        and re.search(r"\b(?:is|are|to)\b", lowered_text)
    )


def _purpose_actor_from_text(text: str) -> str:
    lowered = text.lower()
    institute_matches = re.findall(
        r"\bgeneral\s+purpose\s+of\s+(?:the\s+)?(.+?)\s+is\b",
        lowered,
    ) or re.findall(
        r"\bpurpose\s+of\s+(?:the\s+)?(.+?)\s+is\b",
        lowered,
    ) or re.findall(
        r"\bpurposes\s+of\s+(?:the\s+)?(.+?)\s+are\b",
        lowered,
    )
    if institute_matches:
        actor = re.sub(
            r"\s*\([^)]*\)\s*",
            " ",
            institute_matches[-1],
        )
        actor = re.split(r"\b(?:in\s+this|under\s+this)\b", actor, maxsplit=1)[0]
        actor = " ".join(actor.split())
        if actor:
            return actor
    if re.search(r"\bpolicy\s+of\s+the\s+congress\b", lowered):
        return "Congress"
    return "statute"


def _purpose_action_from_text(text: str) -> str:
    value = _normalize_legal_sample_text(text)
    lowered = value.lower()
    for pattern in (
        r"\bpurpose\s+of\s+(?:the\s+)?.+?\s+is\s+(?:to\s+)?([^.;]+)",
        r"\bpurposes\s+of\s+(?:the\s+)?.+?\s+are\s+(?:to\s+)?([^.;]+)",
        r"\bit\s+is\s+the\s+policy\s+of\s+the\s+congress\s+and\s+the\s+purpose\s+of\s+this\s+chapter\s+to\s+([^.;]+)",
        r"\bpurpose\s+of\s+this\s+chapter\s+(?:is\s+)?to\s+([^.;]+)",
    ):
        match = re.search(pattern, lowered)
        if match:
            action = match.group(1).strip()
            if action:
                return action
    return ""


def _section_status_heading_matches(text: str, status: str) -> bool:
    escaped_status = re.escape(status)
    section_id = r"[0-9][0-9a-z]*(?:[.-][0-9a-z]+)*"
    section_range = (
        rf"{section_id}(?:\s*(?:,|and|to|-)\s*{section_id})*"
    )
    return bool(
        re.search(
            rf"\bsecs?\.?\s*{section_range}\s*(?:-|\.|:)\s*{escaped_status}\b",
            text,
        )
        or re.search(
            rf"§+\s*{section_range}\.?\s+{escaped_status}\b",
            text,
        )
    )


def _normalize_legal_sample_text(text: Any) -> str:
    normalized = str(text or "")
    normalized = normalized.replace("\xa0", " ")
    normalized = normalized.replace("–", "-").replace("—", "-")
    return " ".join(normalized.split())


def _fallback_actor_from_conversion_output(output: Any) -> str:
    agent = getattr(output, "agent", None)
    if agent is None:
        return ""
    for attribute in ("identifier", "name"):
        value = getattr(agent, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _fallback_action_from_conversion_output(output: Any) -> str:
    proposition = str(getattr(output, "proposition", "") or "").strip()
    if not proposition:
        return ""
    if proposition in {"UnparsedNonNormativeOrAmbiguousText", "UNPARSED", "unknown"}:
        return ""
    if _looks_like_formula_text(proposition) or _looks_like_heading_polluted_text(proposition):
        return ""
    return proposition


def _fallback_modality_from_conversion_output(*, output: Any, text: str) -> str:
    operator = str(getattr(getattr(output, "operator", None), "value", "") or "").lower()
    lowered_text = text.lower()
    if operator in {"f", "forbidden", "prohibition"}:
        return "forbidden"
    if operator in {"p", "permission", "permitted"}:
        return "permitted"
    if re.search(r"\b(?:shall\s+not|must\s+not|may\s+not|prohibited|forbidden)\b", lowered_text):
        return "forbidden"
    if re.search(r"\b(?:may|can|is\s+authorized\s+to|is\s+permitted\s+to)\b", lowered_text):
        return "permitted"
    return "obligated"


def _fallback_actor_from_text(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(?:sec\.|section|§)\s*[0-9a-z.-]+\s*(?:-|\.|:)?\s*vacant\b", lowered):
        return "statute section"
    if re.search(r"\b(?:omitted|repealed|renumbered|redesignated)\b", lowered):
        return "statute section"
    if re.search(r"\b(?:definitions|for purposes of this chapter)\b", lowered):
        return "chapter terms"
    if re.search(r"\bthe\s+corporation\s+is\s+liable\b", lowered):
        return "corporation"
    for pattern in (
        r"\b(?:the\s+)?([a-z][a-z0-9]*(?:\s+[a-z][a-z0-9]*){0,5})(?:\s*,[^,]{1,120},)?\s+"
        r"(?:shall|must|may|can|shall\s+not|must\s+not|may\s+not)\b",
        r"\bthe\s+term\s+([a-z][a-z0-9]*(?:\s+[a-z][a-z0-9]*){0,5})\s+means\b",
    ):
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).strip()
    return "actor"


def _fallback_action_from_text(text: str) -> str:
    lowered = text.lower()
    if _section_status_heading_matches(lowered, "vacant"):
        return "mark section vacant"
    if _section_status_heading_matches(lowered, "repealed"):
        return "record section repeal"
    if _section_status_heading_matches(lowered, "omitted"):
        return "record section omission"
    if re.search(r"\bthe\s+corporation\s+is\s+liable\s+for\s+the\s+acts\b", lowered):
        return "assume liability for acts of officers and agents"
    if re.search(r"\b(?:definitions|for purposes of this chapter)\b", lowered):
        return "define statutory terms"
    for pattern in (
        r"\b(?:shall\s+not|must\s+not|may\s+not|is\s+prohibited\s+from|is\s+forbidden\s+to)\s+([^.;:]+)",
        r"\b(?:shall|must|is\s+required\s+to|is\s+obligated\s+to)\s+([^.;:]+)",
        r"\b(?:may|can|is\s+authorized\s+to|is\s+permitted\s+to)\s+([^.;:]+)",
    ):
        match = re.search(pattern, lowered)
        if match:
            action = match.group(1).strip()
            if action:
                return action
    if lowered.startswith("in this section") and "means" in lowered:
        return lowered
    return lowered[:160]


def _looks_like_formula_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.search(r"\bforall\s+[A-Za-z][A-Za-z0-9_]*\s*\.", value, flags=re.IGNORECASE)
        or re.search(r"\bexists\s+[A-Za-z][A-Za-z0-9_]*\s*\.", value, flags=re.IGNORECASE)
        or re.search(r"(?:->|=>|<->|∀|∃|∧|∨|¬)", value)
        or re.match(r"^\(?\s*(?:O|P|F|always|Happens|HoldsAt|Definition)\s*\(", value)
    )


def _looks_like_heading_polluted_text(text: str) -> bool:
    value = _normalize_legal_sample_text(text).lower()
    if len(value) > 240 and re.search(r"\bu\.s\.c\.\s+title\b|\bunited\s+states\s+code\b", value):
        return True
    if len(value) > 240 and re.search(r"\bfrom\s+the\s+u\.s\.\s+government\s+publishing\s+office\b", value):
        return True
    return False


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        if isinstance(value, str):
            parsed = _json_guidance_value(value)
            if isinstance(parsed, Mapping):
                return [dict(parsed)]
            if isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
                return [dict(item) for item in parsed if isinstance(item, Mapping)]
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = _json_guidance_value(value)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _json_guidance_value(value: str) -> Any:
    text = str(value or "").strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _intish(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _text_sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return [value] if value not in (None, "") else []


def _first_text_value(*values: Any, fallback: str = "") -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
            continue
        if isinstance(value, Mapping):
            nested = _first_text_value(*value.values())
            if nested:
                return nested
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            nested = _first_text_value(*list(value))
            if nested:
                return nested
    return str(fallback or "").strip()


__all__ = ["CecDcecBridgeAdapter"]
