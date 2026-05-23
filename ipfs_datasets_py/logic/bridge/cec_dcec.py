"""CEC/DCEC implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
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
    "holdsat": "HoldsAt",
    "initiates": "Initiates",
    "terminates": "Terminates",
    "releasedat": "ReleasedAt",
    "clipped": "Clipped",
    "trajectory": "Trajectory",
    "initially": "Initially",
    "initiallyp": "InitiallyP",
    "initiallyn": "InitiallyN",
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
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        """Encode legal text into a DCEC bridge document."""

        norms = _deontic_norms_from_text(text, converter=self._converter())
        resolved_document_id = document_id or _document_id("dcec", text)
        records = _dcec_records(norms)
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
        views = {
            "cec_events": LogicIRView(
                name="cec_events",
                format="cec-event-records",
                source_component="CEC.native",
                payload={
                    "events": [
                        {
                            "actor": record["actor"],
                            "event": record["event"],
                            "source_id": record["source_id"],
                        }
                        for record in records
                    ]
                },
                metadata={"event_count": len(records)},
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
                            "modality": record["modality"],
                            "source_id": record["source_id"],
                        }
                        for record in records
                    ]
                },
                metadata={
                    "state_formula_count": len(records),
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
        **_: Any,
    ) -> BridgeEvaluationReport:
        """Run the CEC/DCEC bridge and return optimizer-visible diagnostics."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
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
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - no_formula_loss),
            cosine_loss=no_formula_loss,
            symbolic_validity_penalty=max(
                failure_ratio,
                event_formula_invalid_ratio,
            ),
            extra_losses={
                "cec_dcec_no_formula_loss": no_formula_loss,
                "cec_dcec_validation_failure_ratio": failure_ratio,
                "cec_dcec_event_formula_invalid_ratio": event_formula_invalid_ratio,
            },
        )
        status = "ok" if records and proof_gate.compiles else "partial"
        if event_formula_invalid_ratio > 0.0:
            status = "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
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
            metadata={"adapter": "cec_dcec_bridge_v1"},
        )

    def _converter(self) -> Any:
        if self.converter is not None:
            return self.converter
        from ipfs_datasets_py.logic.deontic import DeonticConverter

        self.converter = DeonticConverter(**dict(self.converter_kwargs))
        return self.converter


def _deontic_norms_from_text(text: str, *, converter: Any) -> list[dict[str, Any]]:
    result = converter.convert(text)
    metadata = dict(getattr(result, "metadata", {}) or {})
    norms = _deontic_norm_rows_from_metadata(metadata)
    if norms:
        return norms
    fallback = _fallback_norm_from_conversion(result=result, text=text)
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


def _dcec_records(norms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    event_formula_exports = _event_formula_exports_from_norms(norms)
    pending_event_formula_exports = {
        source_id: list(records)
        for source_id, records in event_formula_exports.items()
    }
    records: list[dict[str, Any]] = []
    for index, norm in enumerate(norms):
        actor = _symbol(norm.get("actor"), fallback="actor")
        event = _symbol(norm.get("action") or norm.get("predicate"), fallback="act")
        modality = _dcec_modality(norm)
        source_id = str(norm.get("source_id") or f"dcec:norm:{index}")
        formula_object = _native_dcec_event_formula(
            actor=actor,
            event=event,
            modality=modality,
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
        )
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
                "formula_object": formula_object,
                "modality": modality,
                "source_id": source_id,
                "source_norm": dict(norm),
                "valid": valid,
                "validation_reason": validation_reason,
            }
        )
    return records


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
            ]
        )
    return [triple for triple in triples if triple["object"]]


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


def _native_dcec_event_formula(*, actor: str, event: str, modality: str) -> Any:
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


def _proof_input_formula_text(*, actor: str, event: str, modality: str) -> str:
    operator = "O"
    if modality == "forbidden":
        operator = "F"
    elif modality == "permitted":
        operator = "P"
    return f"{operator}(happens({actor},{event},t0))"


def _event_formula_exports_from_norms(
    norms: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    exports: dict[str, list[dict[str, Any]]] = {}
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


def _source_symbol(source_id: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(source_id or "unknown")).strip("_")
    return value or "unknown"


def _event_formula_parse_profile(formula: str) -> dict[str, Any]:
    text = _canonicalize_event_formula_text(
        _strip_event_formula_clause_terminator(str(formula or "").strip())
    )
    top_level_connector, connector_index = _top_level_connector(text)
    quantifier_variables = _quantifier_variables(text)
    wrappers = [
        _canonical_wrapper_symbol(match.group(1))
        for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*[\(\[]", text)
        if _canonical_wrapper_symbol(match.group(1))
    ]
    event_predicates = _event_predicates(text)
    top_level_symbol = _top_level_symbol(text)
    parse_profile_complete = _event_formula_parse_profile_complete(
        text=text,
        top_level_symbol=top_level_symbol,
        top_level_connector=top_level_connector,
        connector_index=connector_index,
        quantifier_variables=quantifier_variables,
        event_predicates=event_predicates,
    )
    return {
        "contains_implication": bool(top_level_connector),
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
) -> bool:
    if not text or not _balanced_delimiters(text):
        return False
    if not event_predicates:
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
        return _canonical_event_predicate(token) or _canonical_wrapper_symbol(token) or token
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
    for variable in re.findall(
        r"\b(?:forall|exists)\s+([A-Za-z][A-Za-z0-9_]*)\s*(?:\.|:|\()",
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


def _event_predicates(text: str) -> list[str]:
    predicates: list[str] = []
    for token in re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*[\(\[]", text):
        canonical = _canonical_event_predicate(token)
        if canonical and canonical not in predicates:
            predicates.append(canonical)
    return predicates


def _strip_event_formula_clause_terminator(text: str) -> str:
    value = str(text or "").strip()
    while value.endswith(".") or value.endswith(";"):
        value = value[:-1].strip()
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
    return " ".join(normalized.split())


def _normalize_event_formula_fields(
    *,
    formula: str,
    syntax_valid: bool,
    target_parse_profile: Mapping[str, Any],
    target_components: Mapping[str, Any],
    target_quality_gate: Mapping[str, Any],
    source_id: str,
    modality: str,
) -> tuple[bool, dict[str, Any], dict[str, Any], dict[str, Any]]:
    derived_parse_profile = _event_formula_parse_profile(formula)
    merged_parse_profile = _merge_event_formula_parse_profile(
        base=_mapping(target_parse_profile),
        derived=derived_parse_profile,
    )
    resolved_syntax_valid = bool(
        syntax_valid or merged_parse_profile.get("target_parse_profile_complete") is True
    )
    derived_components = _event_formula_target_components(
        formula,
        source_id=source_id,
        modality=modality,
    )
    merged_components = _merge_event_formula_target_components(
        base=_mapping(target_components),
        derived=derived_components,
        parse_profile=merged_parse_profile,
        source_id=source_id,
        modality=modality,
    )
    quality_gate = _mapping(target_quality_gate)
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
        resolved_syntax_valid,
        merged_parse_profile,
        merged_components,
        resolved_quality_gate,
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


def _stable_short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def _fallback_norm_from_conversion(*, result: Any, text: str) -> Optional[dict[str, Any]]:
    normalized_text = " ".join(str(text or "").split())
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
    for pattern in (
        r"\b(?:the\s+)?([a-z][a-z0-9]*(?:\s+[a-z][a-z0-9]*){0,5})(?:\s*,[^,]{1,120},)?\s+"
        r"(?:shall|must|may|can|shall\s+not|must\s+not|may\s+not)\b",
        r"\bthe\s+term\s+([a-z][a-z0-9]*(?:\s+[a-z][a-z0-9]*){0,5})\s+means\b",
    ):
        match = re.search(pattern, text.lower())
        if match:
            return match.group(1).strip()
    return "actor"


def _fallback_action_from_text(text: str) -> str:
    lowered = text.lower()
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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


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
