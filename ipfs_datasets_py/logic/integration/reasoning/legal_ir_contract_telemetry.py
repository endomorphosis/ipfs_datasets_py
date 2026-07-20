"""Deterministic, source-free telemetry for canonical LegalIR contracts.

The telemetry emitted here is deliberately safe to persist in daemon summaries,
hammer guidance, and learning artifacts.  It records contract and field names,
stable identifiers, counts, and hashes of mismatching typed values; it never
copies a source span or a payload value into the output.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .legal_ir_view_contracts import (
    LegalIRContractValidationResult,
    LegalIRViewContract,
    legal_ir_view_contract,
    legal_ir_view_contracts,
)


LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION: Final = "legal-ir-contract-telemetry-v1"

_VIEW_CONTAINER_KEYS: Final = (
    "legal_ir_contract_payloads",
    "legal_ir_views",
    "view_payloads",
    "contract_views",
    "projections",
)
_COMMON_PRESERVATION_FIELDS: Final = (
    "formula_id",
    "operator",
    "predicate",
    "arguments",
    "conditions",
    "exceptions",
    "provenance_ids",
)
_DECOMPILER_PRESERVATION_FIELDS: Final = (
    "formula_id",
    "operator",
    "predicate",
    "arguments",
    "conditions",
    "exceptions",
    "provenance_ids",
)
_MISSING = object()


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _string(value: Any) -> str:
    return str(value or "").strip()


def _sample_id(sample_or_document: Any, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    if isinstance(sample_or_document, str):
        return sample_or_document.strip() or "legal-ir-sample"
    sample = _mapping(sample_or_document)
    document = _mapping(sample.get("modal_ir")) or sample
    value = (
        sample.get("sample_id")
        or sample.get("document_id")
        or sample.get("id")
        or document.get("document_id")
    )
    if value:
        return str(value)
    references = _collect_provenance_references(sample)
    return f"legal-ir-sample-{_stable_hash(references or ['anonymous'])[:16]}"


def _resolve_contract(value: Any) -> LegalIRViewContract | None:
    try:
        return legal_ir_view_contract(str(value))
    except KeyError:
        return None


def _payload_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        payload = value.get("payload")
        if isinstance(payload, Mapping):
            return [dict(payload)]
        return [dict(value)]
    entries: list[dict[str, Any]] = []
    for item in _sequence(value):
        converted = _mapping(item)
        if converted:
            nested = converted.get("payload")
            entries.append(dict(nested) if isinstance(nested, Mapping) else converted)
    return entries


def _add_view_payload(
    result: dict[str, list[dict[str, Any]]],
    view_or_alias: Any,
    payload: Any,
) -> None:
    contract = _resolve_contract(view_or_alias)
    if contract is None:
        payload_map = _mapping(payload)
        contract = _resolve_contract(
            payload_map.get("view")
            or payload_map.get("legal_ir_view")
            or payload_map.get("contract_id")
            or payload_map.get("target_component")
        )
    if contract is None:
        return
    result.setdefault(contract.view.value, []).extend(_payload_entries(payload))


def _modal_document(sample_or_document: Any) -> dict[str, Any]:
    sample = _mapping(sample_or_document)
    raw = sample.get("modal_ir", sample_or_document)
    return _mapping(raw)


def _provenance_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[Any] = []
    direct = payload.get("provenance_ids", _MISSING)
    if direct is not _MISSING:
        values.extend(_sequence(direct))
    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("id", "source_id"):
            if provenance.get(key):
                values.append(provenance[key])
    for key in ("provenance_id", "source_id", "source_cid"):
        if payload.get(key):
            values.append(payload[key])
    return tuple(sorted({str(item).strip() for item in values if str(item).strip()}))


def _derive_modal_ir_payloads(sample_or_document: Any) -> dict[str, list[dict[str, Any]]]:
    """Project the compiler's canonical modal IR into observable contract views.

    Only views materially represented in the modal document are projected.  In
    particular, this function does not pretend that CEC, an external prover, or
    a decompiler ran merely because a modal formula exists.
    """

    document = _modal_document(sample_or_document)
    formulas = [_mapping(item) for item in _sequence(document.get("formulas"))]
    formulas = [item for item in formulas if item]
    result: dict[str, list[dict[str, Any]]] = {}
    deontic_contract = legal_ir_view_contract("deontic")

    for formula in formulas:
        operator = _mapping(formula.get("operator"))
        predicate = _mapping(formula.get("predicate"))
        symbol = _string(operator.get("symbol") or formula.get("operator"))
        family = _string(operator.get("family")).lower()
        arguments = [str(item) for item in _sequence(predicate.get("arguments"))]
        provenance = _mapping(formula.get("provenance"))
        provenance_ids = list(_provenance_ids({"provenance": provenance}))
        formula_id = _string(formula.get("formula_id"))
        force = deontic_contract.modality_semantics.force_for(symbol)
        if family in {"deontic", "conditional_normative"} or force:
            result.setdefault("deontic", []).append(
                {
                    "action": _string(predicate.get("name")),
                    "actor": arguments[0] if arguments else "",
                    "conditions": list(_sequence(formula.get("conditions"))),
                    "exceptions": list(_sequence(formula.get("exceptions"))),
                    "formula_id": formula_id,
                    "norm_type": force or family,
                    "object": arguments[1] if len(arguments) > 1 else "",
                    "operator": symbol,
                    "polarity": "negative" if force == "prohibition" else "positive",
                    "provenance_ids": provenance_ids,
                }
            )
        if family == "temporal":
            anchors = [
                item
                for item in _sequence(formula.get("conditions"))
                if re.search(r"\b(before|after|within|until|deadline|when|by)\b", str(item), re.I)
            ]
            result.setdefault("tdfol", []).append(
                {
                    "expression": {
                        "arguments": arguments,
                        "operator": symbol,
                        "predicate": _string(predicate.get("name")),
                    },
                    "formula_id": formula_id,
                    "provenance_ids": provenance_ids,
                    "quantifiers": list(_sequence(formula.get("quantifiers"))),
                    "temporal_anchors": anchors,
                }
            )

    frame_logic = _mapping(document.get("frame_logic"))
    triples = [_mapping(item) for item in _sequence(frame_logic.get("triples"))]
    triples = [item for item in triples if item]
    all_references = sorted(
        {
            reference
            for formula in formulas
            for reference in _provenance_ids(_mapping(formula))
        }
    )
    if triples:
        for index, triple in enumerate(triples):
            formula = formulas[min(index, len(formulas) - 1)] if formulas else {}
            predicate = _mapping(formula.get("predicate"))
            result.setdefault("frame_logic", []).append(
                {
                    "formula_id": _string(formula.get("formula_id")) or f"frame-triple-{index + 1}",
                    "frame_id": _string(frame_logic.get("selected_frame") or frame_logic.get("graph_id"))
                    or f"frame-{index + 1}",
                    "object": triple.get("object", ""),
                    "predicate": triple.get("predicate", ""),
                    "provenance_ids": list(_provenance_ids(formula)) or all_references,
                    "role": _string(predicate.get("role")) or "relation",
                    "subject": triple.get("subject", ""),
                }
            )

        node_ids = sorted(
            {
                str(triple.get(endpoint)).strip()
                for triple in triples
                for endpoint in ("subject", "object")
                if str(triple.get(endpoint) or "").strip()
            }
        )
        result["knowledge_graphs"] = [
            {
                "graph_id": _string(frame_logic.get("graph_id"))
                or f"{_string(document.get('document_id')) or 'legal-ir'}:graph",
                "nodes": [{"id": node_id, "type": "LegalIREntity"} for node_id in node_ids],
                "provenance_ids": all_references,
                "relationships": [
                    {
                        "source": triple.get("subject"),
                        "target": triple.get("object"),
                        "type": triple.get("predicate"),
                    }
                    for triple in triples
                ],
            }
        ]
    return result


def extract_legal_ir_contract_payloads(
    sample_or_document: Any,
    view_payloads: Mapping[str, Any] | None = None,
    *,
    derive_modal_ir_views: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Return canonical-view payloads found on a sample in stable view order."""

    found: dict[str, list[dict[str, Any]]] = {}
    if view_payloads is not None:
        for key, value in view_payloads.items():
            _add_view_payload(found, key, value)
    else:
        sample = _mapping(sample_or_document)
        containers: list[Mapping[str, Any]] = []
        for key in _VIEW_CONTAINER_KEYS:
            value = sample.get(key)
            if isinstance(value, Mapping):
                containers.append(value)
        modal = _mapping(sample.get("modal_ir"))
        metadata = _mapping(modal.get("metadata"))
        for key in _VIEW_CONTAINER_KEYS:
            value = metadata.get(key)
            if isinstance(value, Mapping):
                containers.append(value)
        for container in containers:
            for key, value in container.items():
                _add_view_payload(found, key, value)
        for contract in legal_ir_view_contracts():
            for key in (contract.view.value, contract.contract_id, contract.target_component):
                if key in sample:
                    _add_view_payload(found, key, sample[key])
                    break

    if derive_modal_ir_views and view_payloads is None:
        derived = _derive_modal_ir_payloads(sample_or_document)
        for view, payloads in derived.items():
            found.setdefault(view, payloads)

    return {
        contract.view.value: found[contract.view.value]
        for contract in legal_ir_view_contracts()
        if found.get(contract.view.value)
    }


def _collect_provenance_references(value: Any) -> tuple[str, ...]:
    references: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, Mapping):
            for key, child in current.items():
                lowered = str(key).lower()
                if lowered in {"provenance_ids", "provenance_id"}:
                    references.update(
                        str(item).strip() for item in _sequence(child) if str(item).strip()
                    )
                elif lowered in {"source_id", "source_cid"}:
                    text = str(child or "").strip()
                    if text:
                        references.add(text)
                elif lowered in {"provenance", "metadata", "payload"}:
                    walk(child)
                elif isinstance(child, (Mapping, list, tuple)):
                    walk(child)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for child in current:
                walk(child)

    walk(value)
    return tuple(sorted(references))


def _normalized_semantic_value(payload: Mapping[str, Any], field_name: str) -> Any:
    structure = _mapping(payload.get("reconstructed_structure"))
    if field_name == "formula_id":
        return payload.get("formula_id", payload.get("input_formula_id", _MISSING))
    if field_name == "operator":
        value = payload.get("operator", structure.get("operator", _MISSING))
        if isinstance(value, Mapping):
            value = value.get("symbol", value.get("operator", _MISSING))
        return _string(value).lower() if value is not _MISSING else _MISSING
    if field_name == "predicate":
        value = payload.get("predicate", structure.get("predicate", _MISSING))
        if value is _MISSING:
            value = payload.get("action", structure.get("action", _MISSING))
        if isinstance(value, Mapping):
            value = value.get("name", value.get("predicate", _MISSING))
        return _string(value).lower() if value is not _MISSING else _MISSING
    if field_name == "arguments":
        value = payload.get("arguments", structure.get("arguments", _MISSING))
        if value is _MISSING and ("actor" in payload or "object" in payload):
            value = [payload.get("actor"), payload.get("object")]
        return [str(item) for item in _sequence(value)] if value is not _MISSING else _MISSING
    if field_name in {"conditions", "exceptions", "temporal_anchors"}:
        value = payload.get(field_name, structure.get(field_name, _MISSING))
        return list(_sequence(value)) if value is not _MISSING else _MISSING
    if field_name == "provenance_ids":
        values = _provenance_ids(payload)
        return list(values) if values else _MISSING
    return payload.get(field_name, structure.get(field_name, _MISSING))


def _formula_key(payload: Mapping[str, Any], index: int) -> str:
    value = _normalized_semantic_value(payload, "formula_id")
    return _string(value) if value is not _MISSING else f"payload-{index + 1}"


@dataclass(frozen=True)
class LegalIRCrossViewMismatch:
    """Hash-only evidence that two projections disagree on a shared slot."""

    mismatch_id: str
    field_path: str
    formula_id: str
    left_view: str
    right_view: str
    left_value_sha256: str
    right_value_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field_path": self.field_path,
            "formula_id": self.formula_id,
            "left_value_sha256": self.left_value_sha256,
            "left_view": self.left_view,
            "mismatch_id": self.mismatch_id,
            "right_value_sha256": self.right_value_sha256,
            "right_view": self.right_view,
        }


@dataclass(frozen=True)
class LegalIRDecompilerPreservationFailure:
    """One typed slot not preserved by a decompiler projection."""

    failure_id: str
    field_path: str
    formula_id: str
    reason: str
    source_contract_id: str
    source_value_sha256: str = ""
    reconstructed_value_sha256: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "failure_id": self.failure_id,
            "field_path": self.field_path,
            "formula_id": self.formula_id,
            "reason": self.reason,
            "reconstructed_value_sha256": self.reconstructed_value_sha256,
            "source_contract_id": self.source_contract_id,
            "source_value_sha256": self.source_value_sha256,
        }


def _cross_view_mismatches(
    sample_id: str,
    payloads: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[LegalIRCrossViewMismatch, ...]:
    by_formula: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for view, entries in payloads.items():
        for index, payload in enumerate(entries):
            by_formula.setdefault(_formula_key(payload, index), []).append((view, payload))

    mismatches: list[LegalIRCrossViewMismatch] = []
    for formula_id in sorted(by_formula):
        entries = sorted(by_formula[formula_id], key=lambda item: item[0])
        for left_index, (left_view, left) in enumerate(entries):
            for right_view, right in entries[left_index + 1 :]:
                for field_name in _COMMON_PRESERVATION_FIELDS:
                    if "decompiler" in {left_view, right_view} and field_name != "provenance_ids":
                        # Source/decompiler structural slots have their own failure
                        # records below, including missing-field reasons.  Keeping
                        # them out of the generic cross-view set avoids comparing
                        # the decompiler with unrelated compiler lanes.
                        continue
                    if field_name in {"predicate", "arguments"} and "decompiler" not in {
                        left_view,
                        right_view,
                    }:
                        # Compiler lanes use intentionally different typed encodings
                        # for predicates/arguments.  Their shared invariant is tested
                        # against the structural decompiler, not byte-for-byte here.
                        continue
                    left_value = _normalized_semantic_value(left, field_name)
                    right_value = _normalized_semantic_value(right, field_name)
                    if left_value is _MISSING or right_value is _MISSING:
                        continue
                    if _stable_json(left_value) == _stable_json(right_value):
                        continue
                    id_payload = [sample_id, formula_id, left_view, right_view, field_name]
                    mismatches.append(
                        LegalIRCrossViewMismatch(
                            mismatch_id=f"lir-cross-view-{_stable_hash(id_payload)[:20]}",
                            field_path=field_name,
                            formula_id=formula_id,
                            left_view=left_view,
                            right_view=right_view,
                            left_value_sha256=_stable_hash(left_value),
                            right_value_sha256=_stable_hash(right_value),
                        )
                    )
    return tuple(mismatches)


def _decompiler_failures(
    sample_id: str,
    payloads: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[LegalIRDecompilerPreservationFailure, ...]:
    failures: list[LegalIRDecompilerPreservationFailure] = []
    for index, decoded in enumerate(payloads.get("decompiler", ())):
        formula_id = _formula_key(decoded, index)
        source_contract_id = _string(
            decoded.get("source_contract_id") or decoded.get("contract_id")
        )
        source_contract = _resolve_contract(source_contract_id)
        candidates = list(payloads.get(source_contract.view.value, ())) if source_contract else []
        source = next(
            (item for item in candidates if _formula_key(item, 0) == formula_id),
            candidates[0] if len(candidates) == 1 else None,
        )
        if source is None:
            reason = "unknown_source_contract" if source_contract is None else "source_payload_unavailable"
            failure_payload = [sample_id, formula_id, source_contract_id, "source_contract", reason]
            failures.append(
                LegalIRDecompilerPreservationFailure(
                    failure_id=f"lir-decompiler-{_stable_hash(failure_payload)[:20]}",
                    field_path="source_contract_id",
                    formula_id=formula_id,
                    reason=reason,
                    source_contract_id=source_contract_id,
                )
            )
            continue
        for field_name in _DECOMPILER_PRESERVATION_FIELDS:
            source_value = _normalized_semantic_value(source, field_name)
            decoded_value = _normalized_semantic_value(decoded, field_name)
            if source_value is _MISSING:
                continue
            reason = ""
            if decoded_value is _MISSING:
                reason = "missing_preserved_field"
            elif _stable_json(source_value) != _stable_json(decoded_value):
                reason = "preserved_value_mismatch"
            if not reason:
                continue
            failure_payload = [sample_id, formula_id, source_contract_id, field_name, reason]
            failures.append(
                LegalIRDecompilerPreservationFailure(
                    failure_id=f"lir-decompiler-{_stable_hash(failure_payload)[:20]}",
                    field_path=field_name,
                    formula_id=formula_id,
                    reason=reason,
                    source_contract_id=source_contract_id,
                    source_value_sha256=_stable_hash(source_value),
                    reconstructed_value_sha256=(
                        "" if decoded_value is _MISSING else _stable_hash(decoded_value)
                    ),
                )
            )
    return tuple(failures)


@dataclass(frozen=True)
class LegalIRContractSampleTelemetry:
    """Deterministic contract telemetry for one compiler/decompiler sample."""

    sample_id: str
    contract_coverage: dict[str, dict[str, Any]]
    missing_required_fields: dict[str, tuple[str, ...]]
    validation_issue_counts: dict[str, int]
    cross_view_mismatches: tuple[LegalIRCrossViewMismatch, ...] = ()
    decompiler_preservation_failures: tuple[LegalIRDecompilerPreservationFailure, ...] = ()
    source_references: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION

    @property
    def legal_ir_contract_coverage(self) -> float:
        if not self.contract_coverage:
            return 0.0
        valid = sum(1 for item in self.contract_coverage.values() if item["valid"])
        return valid / len(self.contract_coverage)

    @property
    def coverage(self) -> float:
        """Short compatibility alias for ``legal_ir_contract_coverage``."""

        return self.legal_ir_contract_coverage

    @property
    def legal_ir_contract_view_family_gaps(self) -> tuple[str, ...]:
        return tuple(
            view for view, item in self.contract_coverage.items() if not item["valid"]
        )

    @property
    def view_family_gaps(self) -> tuple[str, ...]:
        return self.legal_ir_contract_view_family_gaps

    @property
    def legal_ir_contract_failure_counts(self) -> dict[str, int]:
        missing = sum(len(fields) for fields in self.missing_required_fields.values())
        provenance = sum(
            count
            for code, count in self.validation_issue_counts.items()
            if code in {
                "empty_required_field",
                "invalid_provenance_id",
                "missing_provenance_id",
                "source_text_forbidden",
            }
            and ("provenance" in code or code == "source_text_forbidden")
        )
        return {
            "cross_view_mismatches": len(self.cross_view_mismatches),
            "decompiler_preservation_failures": len(self.decompiler_preservation_failures),
            "missing_required_fields": missing,
            "provenance_policy_failures": provenance,
            "validation_errors": sum(self.validation_issue_counts.values()),
        }

    @property
    def failure_counts(self) -> dict[str, int]:
        return self.legal_ir_contract_failure_counts

    def guidance_projection(self) -> dict[str, Any]:
        """Return the compact source-free projection embedded in hammer artifacts."""

        return {
            "cross_view_mismatches": [item.to_dict() for item in self.cross_view_mismatches],
            "decompiler_preservation_failures": [
                item.to_dict() for item in self.decompiler_preservation_failures
            ],
            "legal_ir_contract_coverage": round(self.legal_ir_contract_coverage, 12),
            "legal_ir_contract_failure_counts": self.legal_ir_contract_failure_counts,
            "legal_ir_contract_view_family_gaps": list(
                self.legal_ir_contract_view_family_gaps
            ),
            "missing_required_fields": {
                view: list(fields) for view, fields in self.missing_required_fields.items()
            },
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_references": list(self.source_references),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.guidance_projection(),
            "contract_coverage": {
                view: dict(values) for view, values in self.contract_coverage.items()
            },
            "validation_issue_counts": dict(self.validation_issue_counts),
        }


def collect_legal_ir_contract_telemetry(
    sample_or_document: Any = None,
    view_payloads: Mapping[str, Any] | None = None,
    *,
    sample_id: str | None = None,
    derive_modal_ir_views: bool = True,
) -> LegalIRContractSampleTelemetry:
    """Validate every observed view and emit deterministic per-sample telemetry."""

    resolved_sample_id = _sample_id(sample_or_document, sample_id)
    payloads = extract_legal_ir_contract_payloads(
        sample_or_document,
        view_payloads,
        derive_modal_ir_views=derive_modal_ir_views,
    )
    coverage: dict[str, dict[str, Any]] = {}
    missing: dict[str, tuple[str, ...]] = {}
    issue_counts: Counter[str] = Counter()

    for contract in legal_ir_view_contracts():
        entries = payloads.get(contract.view.value, [])
        validations: list[LegalIRContractValidationResult] = [
            contract.validate(payload) for payload in entries
        ]
        for validation in validations:
            issue_counts.update(issue.code for issue in validation.issues)
        missing_fields = tuple(
            sorted(
                {
                    field_name
                    for validation in validations
                    for field_name in validation.missing_required_fields
                }
            )
        )
        if missing_fields:
            missing[contract.view.value] = missing_fields
        valid_count = sum(1 for validation in validations if validation.valid)
        covered_fields = sorted(
            set(contract.required_field_names)
            - {
                field_name
                for validation in validations
                for field_name in validation.missing_required_fields
            }
        ) if entries else []
        coverage[contract.view.value] = {
            "contract_id": contract.contract_id,
            "covered_required_field_count": len(covered_fields),
            "issue_count": sum(len(validation.issues) for validation in validations),
            "payload_count": len(entries),
            "present": bool(entries),
            "required_field_count": len(contract.required_fields),
            "valid": bool(entries) and valid_count == len(entries),
            "valid_payload_count": valid_count,
        }

    references = _collect_provenance_references(payloads)
    return LegalIRContractSampleTelemetry(
        sample_id=resolved_sample_id,
        contract_coverage=coverage,
        missing_required_fields=missing,
        validation_issue_counts=dict(sorted(issue_counts.items())),
        cross_view_mismatches=_cross_view_mismatches(resolved_sample_id, payloads),
        decompiler_preservation_failures=_decompiler_failures(
            resolved_sample_id, payloads
        ),
        source_references=references,
    )


def emit_legal_ir_contract_telemetry(
    sample_or_document: Any = None,
    view_payloads: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> LegalIRContractSampleTelemetry:
    """Compatibility name emphasizing that the returned record is persistable."""

    return collect_legal_ir_contract_telemetry(sample_or_document, view_payloads, **kwargs)


def _telemetry_dict(value: LegalIRContractSampleTelemetry | Mapping[str, Any]) -> dict[str, Any]:
    return value.to_dict() if isinstance(value, LegalIRContractSampleTelemetry) else dict(value)


def summarize_legal_ir_contract_telemetry(
    records: Sequence[LegalIRContractSampleTelemetry | Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate sample records under the stable daemon summary field names."""

    items = [_telemetry_dict(item) for item in records]
    coverage_values = [float(item.get("legal_ir_contract_coverage", 0.0) or 0.0) for item in items]
    failures: Counter[str] = Counter(
        {
            "cross_view_mismatches": 0,
            "decompiler_preservation_failures": 0,
            "missing_required_fields": 0,
            "provenance_policy_failures": 0,
            "validation_errors": 0,
        }
    )
    gaps: Counter[str] = Counter()
    references: set[str] = set()
    for item in items:
        failures.update(
            {
                str(key): int(value or 0)
                for key, value in dict(item.get("legal_ir_contract_failure_counts") or {}).items()
            }
        )
        gaps.update(str(view) for view in item.get("legal_ir_contract_view_family_gaps", []) or [])
        references.update(str(value) for value in item.get("source_references", []) or [] if str(value))
    coverage = sum(coverage_values) / len(coverage_values) if coverage_values else 0.0
    return {
        "contract_telemetry_schema_version": LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION,
        "legal_ir_contract_coverage": round(coverage, 12),
        "legal_ir_contract_failure_counts": dict(sorted(failures.items())),
        "legal_ir_contract_sample_count": len(items),
        "legal_ir_contract_view_family_gaps": dict(sorted(gaps.items())),
        "legal_ir_provenance_source_references": sorted(references),
    }


def attach_legal_ir_contract_telemetry(
    artifacts: Sequence[Mapping[str, Any]],
    telemetry: LegalIRContractSampleTelemetry | Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return hammer guidance artifacts decorated with source-free telemetry."""

    telemetry_dict = _telemetry_dict(telemetry)
    compact = {
        key: telemetry_dict[key]
        for key in (
            "cross_view_mismatches",
            "decompiler_preservation_failures",
            "legal_ir_contract_coverage",
            "legal_ir_contract_failure_counts",
            "legal_ir_contract_view_family_gaps",
            "missing_required_fields",
            "sample_id",
            "schema_version",
            "source_references",
        )
        if key in telemetry_dict
    }
    decorated: list[dict[str, Any]] = []
    for artifact in artifacts:
        payload = dict(artifact)
        metadata = dict(payload.get("metadata") or {})
        metadata["legal_ir_contract_telemetry"] = compact
        payload["metadata"] = metadata
        payload["legal_ir_contract_telemetry"] = compact
        decorated.append(payload)
    return decorated


# Straightforward aliases used by callers that describe the operation as a build.
build_legal_ir_contract_telemetry = collect_legal_ir_contract_telemetry
aggregate_legal_ir_contract_telemetry = summarize_legal_ir_contract_telemetry
LegalIRContractTelemetry = LegalIRContractSampleTelemetry


__all__ = [
    "LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION",
    "LegalIRContractSampleTelemetry",
    "LegalIRContractTelemetry",
    "LegalIRCrossViewMismatch",
    "LegalIRDecompilerPreservationFailure",
    "aggregate_legal_ir_contract_telemetry",
    "attach_legal_ir_contract_telemetry",
    "build_legal_ir_contract_telemetry",
    "collect_legal_ir_contract_telemetry",
    "emit_legal_ir_contract_telemetry",
    "extract_legal_ir_contract_payloads",
    "summarize_legal_ir_contract_telemetry",
]
