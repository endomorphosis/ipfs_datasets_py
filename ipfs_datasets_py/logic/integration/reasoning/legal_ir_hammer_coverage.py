"""Coverage accounting for Legal IR Hammer proof obligations.

This module keeps promotion decisions separate from proof search.  It projects
obligations, trusted proof artifacts, route attempts, reconstruction receipts,
and unsupported lowering attempts into a deterministic contract-field-by-family
matrix.  Unsupported translation is recorded as capability evidence, not as a
counterexample or theorem failure.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .hammer_guidance import HammerGuidanceArtifact
from .legal_ir_hammer_translation import (
    HammerReconstructionReceipt,
    HammerTranslationRecord,
)
from .legal_ir_obligations import (
    LegalIRProofObligation,
    generate_legal_ir_proof_obligations,
)
from .legal_ir_view_contracts import (
    LegalIRViewContract,
    legal_ir_view_contract,
    legal_ir_view_contracts,
)


LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION = "legal-ir-hammer-coverage-v1"

REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES: tuple[str, ...] = (
    "well_formedness",
    "cross_view_consistency",
    "modality",
    "exception",
    "temporal",
    "graph",
    "lifecycle",
    "provenance",
    "round_trip",
)

_TRUSTED_ATTEMPT_LEVELS = {
    "backend",
    "deterministic",
    "kernel",
    "lean_kernel",
    "native",
    "trusted",
}


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


def _content_size(value: Any) -> int:
    return len(_stable_json(value).encode("utf-8"))


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.:-]+", "_", str(value or "").strip().lower()).strip("_")


def _unique(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _as_obligation(value: LegalIRProofObligation | Mapping[str, Any]) -> LegalIRProofObligation:
    if isinstance(value, LegalIRProofObligation):
        return value
    data = dict(value)
    return LegalIRProofObligation(
        obligation_id=str(data.get("obligation_id") or ""),
        statement=str(data.get("statement") or ""),
        kind=str(data.get("kind") or data.get("obligation_kind") or ""),
        legal_ir_view=str(data.get("legal_ir_view") or data.get("target_component") or ""),
        logic_family=str(data.get("logic_family") or data.get("family") or ""),
        sample_id=str(data.get("sample_id") or ""),
        formula_id=str(data.get("formula_id") or data.get("input_formula_id") or ""),
        premise_hints=[str(item) for item in data.get("premise_hints", []) or []],
        metadata=dict(data.get("metadata") or {}),
        schema_version=str(data.get("schema_version") or "legal-ir-proof-obligation-v1"),
    )


def _contract_registry() -> tuple[LegalIRViewContract, ...]:
    return legal_ir_view_contracts().contracts()


def _contract_for_obligation(obligation: LegalIRProofObligation) -> Optional[LegalIRViewContract]:
    metadata = obligation.metadata or {}
    lookup_values = (
        metadata.get("contract_id"),
        metadata.get("contract_view"),
        obligation.legal_ir_view,
        metadata.get("target_component"),
    )
    for value in lookup_values:
        if not value:
            continue
        try:
            return legal_ir_view_contract(str(value))
        except KeyError:
            continue
    return None


def _field_path_for_obligation(obligation: LegalIRProofObligation) -> str:
    metadata = obligation.metadata or {}
    explicit = str(metadata.get("required_field") or metadata.get("field_path") or "").strip()
    if explicit:
        return explicit
    kind = _normalize(obligation.kind)
    if "cross_view" in kind:
        return "cross_view_projection"
    if "provenance" in kind or "source_copy" in kind:
        return "provenance_ids"
    if "well_formed" in kind or kind.endswith("required_fields"):
        return "operator"
    if "deontic" in kind or "modality" in kind or "polarity" in kind:
        return "operator"
    if "exception" in kind:
        return "exceptions"
    if "temporal" in kind:
        return "temporal_anchors"
    if "graph" in kind or "edge" in kind or "frame" in kind:
        return "relationships"
    if "lifecycle" in kind or "event" in kind or "cec" in kind:
        return "lifecycle_transitions"
    if "decompiler" in kind or "round_trip" in kind:
        return "reconstructed_structure"
    if "external_prover" in kind or "route" in kind:
        return "backend_route"
    return "*"


def _field_behavior_family(
    obligation: LegalIRProofObligation,
    field_path: str,
) -> str:
    normalized_field = _normalize(field_path)
    kind = _normalize(obligation.kind)
    contract = _contract_for_obligation(obligation)
    view = _normalize(contract.view.value if contract is not None else obligation.legal_ir_view)
    if "cross_view" in kind:
        return "cross_view_consistency"
    if normalized_field in {"provenance_ids", "provenance.id", "provenance.source_id"}:
        return "provenance"
    if normalized_field in {"exceptions", "exception", "defeaters"}:
        return "exception"
    if normalized_field in {"temporal_anchors", "time_anchor", "deadline", "quantifiers"}:
        return "temporal"
    if normalized_field in {"events", "fluents", "lifecycle_transitions"}:
        return "lifecycle"
    if view in {"knowledge_graphs", "frame_logic"} and normalized_field in {
        "frame_id",
        "graph_id",
        "nodes",
        "object",
        "predicate",
        "relationships",
        "role",
        "subject",
    }:
        return "graph"
    if view == "decompiler" and normalized_field in {
        "arguments",
        "conditions",
        "exceptions",
        "operator",
        "predicate",
        "reconstructed_structure",
        "source_contract_id",
    }:
        return "round_trip"
    return "well_formedness"


def _behavior_family_for_obligation(obligation: LegalIRProofObligation) -> str:
    metadata = obligation.metadata or {}
    scope = _normalize(metadata.get("coverage_scope"))
    if scope == "cross_view_consistency":
        return "cross_view_consistency"
    kind = _normalize(metadata.get("obligation_family") or obligation.kind)
    if "cross_view" in kind:
        return "cross_view_consistency"
    if kind.endswith("required_fields") or metadata.get("required_field"):
        return _field_behavior_family(obligation, _field_path_for_obligation(obligation))
    if "source_copy" in kind:
        return "provenance"
    if "provenance" in kind:
        return "provenance"
    if "exception" in kind:
        return "exception"
    if "temporal" in kind or "tdfol" in kind or "anchor" in kind:
        return "temporal"
    if "knowledge_graph" in kind or "graph" in kind or "frame_role" in kind:
        return "graph"
    if "lifecycle" in kind or "event" in kind or "cec" in kind:
        return "lifecycle"
    if "decompiler" in kind or "round_trip" in kind:
        return "round_trip"
    if "deontic" in kind or "modality" in kind or "polarity" in kind:
        return "modality"
    return "well_formedness"


@dataclass(frozen=True)
class LegalIRHammerCoverageWaiver:
    """Approved exception for a required behavior-family route."""

    waiver_id: str
    behavior_family: str
    reason_code: str
    approved_by: str
    expires_on: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return bool(self.waiver_id and self.behavior_family and self.reason_code and self.approved_by)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "approved_by": self.approved_by,
            "behavior_family": self.behavior_family,
            "expires_on": self.expires_on,
            "metadata": dict(sorted(self.metadata.items())),
            "reason_code": self.reason_code,
            "waiver_id": self.waiver_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRHammerCoverageWaiver":
        return cls(
            waiver_id=str(data.get("waiver_id") or ""),
            behavior_family=str(data.get("behavior_family") or ""),
            reason_code=str(data.get("reason_code") or ""),
            approved_by=str(data.get("approved_by") or ""),
            expires_on=str(data.get("expires_on") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRHammerUnsupportedTranslation:
    """Capability gap encountered while routing a Legal IR obligation."""

    behavior_family: str
    obligation_id: str
    obligation_family: str
    route: str
    reason: str
    translation_record_id: str = ""
    target_format: str = ""
    surface: str = ""
    stage: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior_family": self.behavior_family,
            "metadata": dict(sorted(self.metadata.items())),
            "obligation_family": self.obligation_family,
            "obligation_id": self.obligation_id,
            "reason": self.reason,
            "route": self.route,
            "stage": self.stage,
            "surface": self.surface,
            "target_format": self.target_format,
            "translation_record_id": self.translation_record_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRHammerUnsupportedTranslation":
        return cls(
            behavior_family=str(data.get("behavior_family") or ""),
            obligation_id=str(data.get("obligation_id") or ""),
            obligation_family=str(data.get("obligation_family") or ""),
            route=str(data.get("route") or ""),
            reason=str(data.get("reason") or ""),
            translation_record_id=str(data.get("translation_record_id") or ""),
            target_format=str(data.get("target_format") or ""),
            surface=str(data.get("surface") or ""),
            stage=str(data.get("stage") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRHammerCoverageCell:
    """One contract-field and behavior-family coverage cell."""

    contract_id: str
    contract_view: str
    field_path: str
    behavior_family: str
    obligation_family: str
    obligation_ids: tuple[str, ...] = ()
    executable_routes: tuple[str, ...] = ()
    trusted_routes: tuple[str, ...] = ()
    waiver_ids: tuple[str, ...] = ()
    unsupported_translation_ids: tuple[str, ...] = ()

    @property
    def has_obligation(self) -> bool:
        return bool(self.obligation_ids)

    @property
    def obligation_count(self) -> int:
        return len(self.obligation_ids)

    @property
    def has_executable_trusted_route(self) -> bool:
        return bool(self.trusted_routes)

    @property
    def waived(self) -> bool:
        return bool(self.waiver_ids)

    @property
    def covered(self) -> bool:
        return self.has_obligation and (self.has_executable_trusted_route or self.waived)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior_family": self.behavior_family,
            "contract_id": self.contract_id,
            "contract_view": self.contract_view,
            "covered": self.covered,
            "executable_routes": list(self.executable_routes),
            "field_path": self.field_path,
            "has_executable_trusted_route": self.has_executable_trusted_route,
            "has_obligation": self.has_obligation,
            "obligation_count": self.obligation_count,
            "obligation_family": self.obligation_family,
            "obligation_ids": list(self.obligation_ids),
            "trusted_routes": list(self.trusted_routes),
            "unsupported_translation_ids": list(self.unsupported_translation_ids),
            "waived": self.waived,
            "waiver_ids": list(self.waiver_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRHammerCoverageCell":
        return cls(
            contract_id=str(data.get("contract_id") or ""),
            contract_view=str(data.get("contract_view") or ""),
            field_path=str(data.get("field_path") or ""),
            behavior_family=str(data.get("behavior_family") or ""),
            obligation_family=str(data.get("obligation_family") or ""),
            obligation_ids=tuple(str(item) for item in data.get("obligation_ids", []) or []),
            executable_routes=tuple(str(item) for item in data.get("executable_routes", []) or []),
            trusted_routes=tuple(str(item) for item in data.get("trusted_routes", []) or []),
            waiver_ids=tuple(str(item) for item in data.get("waiver_ids", []) or []),
            unsupported_translation_ids=tuple(
                str(item) for item in data.get("unsupported_translation_ids", []) or []
            ),
        )


@dataclass(frozen=True)
class LegalIRHammerFamilyCoverage:
    """Aggregated coverage status for one required or observed behavior family."""

    behavior_family: str
    required: bool
    obligation_count: int
    covered_obligation_count: int
    cell_count: int
    covered_cell_count: int
    executable_trusted_route_count: int
    waiver_count: int
    unsupported_translation_count: int

    @property
    def has_executable_trusted_route(self) -> bool:
        return self.executable_trusted_route_count > 0

    @property
    def waived(self) -> bool:
        return self.waiver_count > 0

    @property
    def covered(self) -> bool:
        return self.cell_count > 0 and self.covered_cell_count == self.cell_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior_family": self.behavior_family,
            "cell_count": self.cell_count,
            "covered": self.covered,
            "covered_cell_count": self.covered_cell_count,
            "covered_obligation_count": self.covered_obligation_count,
            "executable_trusted_route_count": self.executable_trusted_route_count,
            "has_executable_trusted_route": self.has_executable_trusted_route,
            "obligation_count": self.obligation_count,
            "required": self.required,
            "unsupported_translation_count": self.unsupported_translation_count,
            "waived": self.waived,
            "waiver_count": self.waiver_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRHammerFamilyCoverage":
        return cls(
            behavior_family=str(data.get("behavior_family") or ""),
            required=bool(data.get("required")),
            obligation_count=int(data.get("obligation_count") or 0),
            covered_obligation_count=int(data.get("covered_obligation_count") or 0),
            cell_count=int(data.get("cell_count") or 0),
            covered_cell_count=int(data.get("covered_cell_count") or 0),
            executable_trusted_route_count=int(data.get("executable_trusted_route_count") or 0),
            waiver_count=int(data.get("waiver_count") or 0),
            unsupported_translation_count=int(data.get("unsupported_translation_count") or 0),
        )


@dataclass(frozen=True)
class LegalIRHammerCoverageReport:
    """Complete Hammer obligation coverage report."""

    matrix: tuple[LegalIRHammerCoverageCell, ...]
    coverage_by_family: Mapping[str, LegalIRHammerFamilyCoverage]
    unsupported_translations: tuple[LegalIRHammerUnsupportedTranslation, ...] = ()
    waivers: tuple[LegalIRHammerCoverageWaiver, ...] = ()
    required_families: tuple[str, ...] = REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES
    block_reasons: tuple[str, ...] = ()
    obligation_count: int = 0
    schema_version: str = LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION

    @property
    def required_family_count(self) -> int:
        return len(self.required_families)

    @property
    def covered_family_count(self) -> int:
        return sum(
            1
            for family in self.required_families
            if self.coverage_by_family.get(family)
            and self.coverage_by_family[family].covered
        )

    @property
    def promotion_allowed(self) -> bool:
        return not self.block_reasons

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_reasons": list(self.block_reasons),
            "coverage_by_family": {
                family: self.coverage_by_family[family].to_dict()
                for family in sorted(self.coverage_by_family)
            },
            "covered_family_count": self.covered_family_count,
            "matrix": [cell.to_dict() for cell in self.matrix],
            "obligation_count": int(self.obligation_count),
            "promotion_allowed": self.promotion_allowed,
            "required_families": list(self.required_families),
            "required_family_count": self.required_family_count,
            "schema_version": self.schema_version,
            "unsupported_translations": [
                item.to_dict() for item in self.unsupported_translations
            ],
            "waivers": [waiver.to_dict() for waiver in self.waivers],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRHammerCoverageReport":
        families = {
            str(key): LegalIRHammerFamilyCoverage.from_dict(
                {"behavior_family": key, **dict(value)}
                if isinstance(value, Mapping)
                else {"behavior_family": key}
            )
            for key, value in dict(data.get("coverage_by_family") or {}).items()
        }
        return cls(
            matrix=tuple(
                LegalIRHammerCoverageCell.from_dict(item)
                for item in data.get("matrix", []) or []
                if isinstance(item, Mapping)
            ),
            coverage_by_family=families,
            unsupported_translations=tuple(
                LegalIRHammerUnsupportedTranslation.from_dict(item)
                for item in data.get("unsupported_translations", []) or []
                if isinstance(item, Mapping)
            ),
            waivers=tuple(
                LegalIRHammerCoverageWaiver.from_dict(item)
                for item in data.get("waivers", []) or []
                if isinstance(item, Mapping)
            ),
            required_families=tuple(
                str(item)
                for item in data.get(
                    "required_families",
                    REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES,
                )
            ),
            block_reasons=tuple(str(item) for item in data.get("block_reasons", []) or []),
            obligation_count=int(data.get("obligation_count") or 0),
            schema_version=str(
                data.get("schema_version") or LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True)
class LegalIRMinimizedCounterexample:
    """Result of source-free counterexample minimization."""

    original_sha256: str
    minimized_sha256: str
    original_size_bytes: int
    minimized_size_bytes: int
    result: str
    verified: bool
    result_preserved: bool
    changed: bool
    removed_paths: tuple[str, ...]
    minimized_counterexample: Mapping[str, Any]
    schema_version: str = "legal-ir-hammer-minimized-counterexample-v1"

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.minimized_counterexample)
        payload.update(
            {
                "changed": self.changed,
                "minimized_sha256": self.minimized_sha256,
                "minimized_size_bytes": self.minimized_size_bytes,
                "original_sha256": self.original_sha256,
                "original_size_bytes": self.original_size_bytes,
                "removed_paths": list(self.removed_paths),
                "result": self.result,
                "result_preserved": self.result_preserved,
                "schema_version": self.schema_version,
                "verified": self.verified,
            }
        )
        return payload


@dataclass
class _ObligationEvidence:
    executable_routes: List[str] = field(default_factory=list)
    trusted_routes: List[str] = field(default_factory=list)
    unsupported_ids: List[str] = field(default_factory=list)
    unsupported_items: List[LegalIRHammerUnsupportedTranslation] = field(default_factory=list)


def _artifact_from(value: Any) -> HammerGuidanceArtifact:
    if isinstance(value, HammerGuidanceArtifact):
        return value
    return HammerGuidanceArtifact.from_dict(_as_mapping(value))


def _translation_from(value: Any) -> HammerTranslationRecord:
    if isinstance(value, HammerTranslationRecord):
        return value
    return HammerTranslationRecord.from_dict(_as_mapping(value))


def _receipt_from(value: Any) -> HammerReconstructionReceipt:
    if isinstance(value, HammerReconstructionReceipt):
        return value
    return HammerReconstructionReceipt.from_dict(_as_mapping(value))


def _waiver_from(value: LegalIRHammerCoverageWaiver | Mapping[str, Any]) -> LegalIRHammerCoverageWaiver:
    if isinstance(value, LegalIRHammerCoverageWaiver):
        return value
    return LegalIRHammerCoverageWaiver.from_dict(value)


def _attempt_dicts(route_result: Any) -> List[Dict[str, Any]]:
    if route_result is None:
        return []
    attempts = getattr(route_result, "attempts", None)
    if attempts is not None:
        result: List[Dict[str, Any]] = []
        for attempt in attempts:
            if isinstance(attempt, Mapping):
                result.append(dict(attempt))
            else:
                to_dict = getattr(attempt, "to_dict", None)
                result.append(dict(to_dict() if callable(to_dict) else _as_mapping(attempt)))
        return result
    data = _as_mapping(route_result)
    return [dict(item) for item in data.get("attempts", []) or [] if isinstance(item, Mapping)]


def _route_result_obligation_id(route_result: Any) -> str:
    return str(
        getattr(route_result, "obligation_id", "")
        or _as_mapping(route_result).get("obligation_id")
        or ""
    )


def _attempt_is_executable(attempt: Mapping[str, Any]) -> bool:
    if "executed" in attempt:
        return bool(attempt.get("executed"))
    status = str(attempt.get("status") or "").lower()
    return status not in {"", "cancelled", "skipped"}


def _attempt_is_trusted(attempt: Mapping[str, Any]) -> bool:
    status = str(attempt.get("status") or "").lower()
    trust = str(attempt.get("trust_level") or "").lower()
    return status == "proved" and trust in _TRUSTED_ATTEMPT_LEVELS


def _obligation_from_artifact(artifact: HammerGuidanceArtifact) -> LegalIRProofObligation:
    metadata = dict(artifact.metadata or {})
    return LegalIRProofObligation(
        obligation_id=artifact.obligation_id,
        statement="",
        kind=str(metadata.get("obligation_kind") or metadata.get("kind") or ""),
        legal_ir_view=artifact.legal_ir_view or artifact.target_component,
        logic_family=artifact.logic_family,
        sample_id=str(metadata.get("sample_id") or ""),
        formula_id=str(metadata.get("formula_id") or ""),
        premise_hints=[],
        metadata=metadata,
    )


def _coverage_obligations_from_report_dict(report: Mapping[str, Any]) -> List[LegalIRProofObligation]:
    metadata = dict(report.get("metadata") or {})
    raw = metadata.get("coverage_obligations") or report.get("coverage_obligations")
    if raw:
        return [_as_obligation(item) for item in raw if isinstance(item, Mapping)]
    artifacts = [
        _artifact_from(item)
        for item in report.get("artifacts", []) or []
        if isinstance(item, Mapping)
    ]
    return [_obligation_from_artifact(artifact) for artifact in artifacts]


def _translation_by_obligation(
    translation_records: Sequence[HammerTranslationRecord],
) -> Dict[str, List[HammerTranslationRecord]]:
    grouped: Dict[str, List[HammerTranslationRecord]] = {}
    for record in translation_records:
        grouped.setdefault(record.obligation_id, []).append(record)
    return grouped


def _unsupported_from_attempt(
    *,
    obligation: LegalIRProofObligation,
    behavior_family: str,
    attempt: Mapping[str, Any],
    translation: Optional[HammerTranslationRecord] = None,
) -> LegalIRHammerUnsupportedTranslation:
    route = str(attempt.get("route") or "")
    stage = str(attempt.get("stage") or "")
    reason = str(attempt.get("reason") or attempt.get("skip_reason") or "unsupported_translation")
    metadata = dict(attempt.get("metadata") or {})
    return LegalIRHammerUnsupportedTranslation(
        behavior_family=behavior_family,
        obligation_id=obligation.obligation_id,
        obligation_family=str(obligation.metadata.get("obligation_family") or obligation.kind),
        route=route,
        reason=reason,
        translation_record_id=str(translation.translation_id if translation else ""),
        target_format=str(translation.target_format if translation else ""),
        surface=str(translation.surface.value if translation else ""),
        stage=stage,
        metadata=metadata,
    )


def _collect_evidence(
    *,
    obligations: Sequence[LegalIRProofObligation],
    artifacts: Sequence[HammerGuidanceArtifact],
    route_results: Sequence[Any],
    translation_records: Sequence[HammerTranslationRecord],
    reconstruction_receipts: Sequence[HammerReconstructionReceipt],
) -> tuple[Dict[str, _ObligationEvidence], tuple[LegalIRHammerUnsupportedTranslation, ...]]:
    evidence = {obligation.obligation_id: _ObligationEvidence() for obligation in obligations}
    obligations_by_id = {obligation.obligation_id: obligation for obligation in obligations}
    behavior_by_id = {
        obligation.obligation_id: _behavior_family_for_obligation(obligation)
        for obligation in obligations
    }
    translations_by_id = _translation_by_obligation(translation_records)

    for artifact in artifacts:
        item = evidence.setdefault(artifact.obligation_id, _ObligationEvidence())
        attempts = [
            dict(attempt)
            for attempt in artifact.metadata.get("proof_route_attempts", []) or []
            if isinstance(attempt, Mapping)
        ]
        for attempt in attempts:
            route = str(attempt.get("route") or "")
            if route and _attempt_is_executable(attempt):
                item.executable_routes.append(route)
            if route and artifact.trusted and _attempt_is_trusted(attempt):
                item.trusted_routes.append(route)
            if str(attempt.get("status") or "").lower() == "unsupported_translation":
                obligation = obligations_by_id.get(artifact.obligation_id) or _obligation_from_artifact(artifact)
                translation = next(
                    (
                        record
                        for record in translations_by_id.get(artifact.obligation_id, [])
                        if not record.success
                    ),
                    None,
                )
                item.unsupported_items.append(
                    _unsupported_from_attempt(
                        obligation=obligation,
                        behavior_family=behavior_by_id.get(
                            artifact.obligation_id,
                            _behavior_family_for_obligation(obligation),
                        ),
                        attempt=attempt,
                        translation=translation if route == "smt_atp_portfolio" else None,
                    )
                )
        if artifact.trusted and not item.trusted_routes:
            route = artifact.winner_backend or "hammer_backend"
            item.executable_routes.append(route)
            item.trusted_routes.append(route)

    for route_result in route_results:
        obligation_id = _route_result_obligation_id(route_result)
        if not obligation_id:
            continue
        item = evidence.setdefault(obligation_id, _ObligationEvidence())
        for attempt in _attempt_dicts(route_result):
            route = str(attempt.get("route") or "")
            if route and _attempt_is_executable(attempt):
                item.executable_routes.append(route)
            if route and _attempt_is_trusted(attempt):
                item.trusted_routes.append(route)
            if str(attempt.get("status") or "").lower() == "unsupported_translation":
                obligation = obligations_by_id.get(obligation_id)
                if obligation is None:
                    continue
                translation = next(
                    (
                        record
                        for record in translations_by_id.get(obligation_id, [])
                        if not record.success
                    ),
                    None,
                )
                item.unsupported_items.append(
                    _unsupported_from_attempt(
                        obligation=obligation,
                        behavior_family=behavior_by_id.get(
                            obligation_id,
                            _behavior_family_for_obligation(obligation),
                        ),
                        attempt=attempt,
                        translation=translation if route == "smt_atp_portfolio" else None,
                    )
                )

    for receipt in reconstruction_receipts:
        item = evidence.setdefault(receipt.obligation_id, _ObligationEvidence())
        if receipt.translation_succeeded:
            item.executable_routes.append(receipt.backend or "translation")
        if receipt.trusted:
            item.trusted_routes.append(receipt.backend or "reconstruction_receipt")

    for obligation in obligations:
        item = evidence.setdefault(obligation.obligation_id, _ObligationEvidence())
        for record in translations_by_id.get(obligation.obligation_id, []):
            if record.success:
                item.executable_routes.append(record.target_format or record.surface.value)
            elif not item.unsupported_items:
                attempt = {
                    "route": "smt_atp_portfolio",
                    "stage": "smt_atp",
                    "status": "unsupported_translation",
                    "reason": ";".join(record.errors) or "unsupported_translation",
                    "metadata": {"translation_record_id": record.translation_id},
                }
                item.unsupported_items.append(
                    _unsupported_from_attempt(
                        obligation=obligation,
                        behavior_family=behavior_by_id[obligation.obligation_id],
                        attempt=attempt,
                        translation=record,
                    )
                )

    unsupported: List[LegalIRHammerUnsupportedTranslation] = []
    seen: set[str] = set()
    for item in evidence.values():
        for unsupported_item in item.unsupported_items:
            payload = unsupported_item.to_dict()
            key = _stable_hash(payload)
            if key in seen:
                continue
            seen.add(key)
            unsupported.append(unsupported_item)
            item.unsupported_ids.append(unsupported_item.translation_record_id or key[:16])
        item.executable_routes = list(_unique(item.executable_routes))
        item.trusted_routes = list(_unique(item.trusted_routes))
        item.unsupported_ids = list(_unique(item.unsupported_ids))
    return evidence, tuple(sorted(unsupported, key=lambda value: _stable_json(value.to_dict())))


def _cell_seed(
    obligation: LegalIRProofObligation,
    behavior_family: str,
    field_path: str,
) -> Dict[str, str]:
    contract = _contract_for_obligation(obligation)
    contract_id = (
        str(obligation.metadata.get("contract_id") or "")
        or (contract.contract_id if contract is not None else "")
        or str(obligation.legal_ir_view or "unmapped")
    )
    contract_view = (
        str(obligation.metadata.get("contract_view") or "")
        or (contract.view.value if contract is not None else "")
        or str(obligation.legal_ir_view or "unmapped")
    )
    return {
        "behavior_family": behavior_family,
        "contract_id": contract_id,
        "contract_view": contract_view,
        "field_path": field_path,
        "obligation_family": str(
            obligation.metadata.get("obligation_family")
            or obligation.kind
            or behavior_family
        ),
    }


def _approved_waivers_by_family(
    waivers: Sequence[LegalIRHammerCoverageWaiver],
) -> Dict[str, tuple[LegalIRHammerCoverageWaiver, ...]]:
    grouped: Dict[str, List[LegalIRHammerCoverageWaiver]] = {}
    for waiver in waivers:
        if waiver.approved:
            grouped.setdefault(waiver.behavior_family, []).append(waiver)
    return {
        family: tuple(sorted(items, key=lambda item: item.waiver_id))
        for family, items in grouped.items()
    }


def _build_matrix(
    obligations: Sequence[LegalIRProofObligation],
    evidence: Mapping[str, _ObligationEvidence],
    waivers: Sequence[LegalIRHammerCoverageWaiver],
) -> tuple[LegalIRHammerCoverageCell, ...]:
    waiver_by_family = _approved_waivers_by_family(waivers)
    cells: Dict[tuple[str, str, str, str, str], Dict[str, Any]] = {}
    for obligation in obligations:
        behavior_family = _behavior_family_for_obligation(obligation)
        field_path = _field_path_for_obligation(obligation)
        seed = _cell_seed(obligation, behavior_family, field_path)
        key = (
            seed["contract_id"],
            seed["field_path"],
            seed["behavior_family"],
            seed["obligation_family"],
            seed["contract_view"],
        )
        cell = cells.setdefault(
            key,
            {
                **seed,
                "obligation_ids": [],
                "executable_routes": [],
                "trusted_routes": [],
                "unsupported_translation_ids": [],
                "waiver_ids": [],
            },
        )
        item = evidence.get(obligation.obligation_id, _ObligationEvidence())
        cell["obligation_ids"].append(obligation.obligation_id)
        cell["executable_routes"].extend(item.executable_routes)
        cell["trusted_routes"].extend(item.trusted_routes)
        cell["unsupported_translation_ids"].extend(item.unsupported_ids)
        cell["waiver_ids"].extend(
            waiver.waiver_id for waiver in waiver_by_family.get(behavior_family, ())
        )
    return tuple(
        LegalIRHammerCoverageCell(
            contract_id=str(cell["contract_id"]),
            contract_view=str(cell["contract_view"]),
            field_path=str(cell["field_path"]),
            behavior_family=str(cell["behavior_family"]),
            obligation_family=str(cell["obligation_family"]),
            obligation_ids=_unique(cell["obligation_ids"]),
            executable_routes=_unique(cell["executable_routes"]),
            trusted_routes=_unique(cell["trusted_routes"]),
            waiver_ids=_unique(cell["waiver_ids"]),
            unsupported_translation_ids=_unique(cell["unsupported_translation_ids"]),
        )
        for cell in sorted(
            cells.values(),
            key=lambda value: (
                str(value["behavior_family"]),
                str(value["contract_id"]),
                str(value["field_path"]),
                str(value["obligation_family"]),
            ),
        )
    )


def _family_coverage(
    *,
    matrix: Sequence[LegalIRHammerCoverageCell],
    unsupported_translations: Sequence[LegalIRHammerUnsupportedTranslation],
    required_families: Sequence[str],
) -> Dict[str, LegalIRHammerFamilyCoverage]:
    observed = sorted(
        set(required_families)
        | {cell.behavior_family for cell in matrix}
        | {item.behavior_family for item in unsupported_translations}
    )
    result: Dict[str, LegalIRHammerFamilyCoverage] = {}
    for family in observed:
        cells = [cell for cell in matrix if cell.behavior_family == family]
        unsupported_count = sum(1 for item in unsupported_translations if item.behavior_family == family)
        result[family] = LegalIRHammerFamilyCoverage(
            behavior_family=family,
            required=family in set(required_families),
            obligation_count=sum(cell.obligation_count for cell in cells),
            covered_obligation_count=sum(
                cell.obligation_count for cell in cells if cell.covered
            ),
            cell_count=len(cells),
            covered_cell_count=sum(1 for cell in cells if cell.covered),
            executable_trusted_route_count=sum(
                len(cell.trusted_routes) for cell in cells
            ),
            waiver_count=sum(len(cell.waiver_ids) for cell in cells),
            unsupported_translation_count=unsupported_count,
        )
    return result


def _promotion_block_reasons(
    *,
    matrix: Sequence[LegalIRHammerCoverageCell],
    coverage_by_family: Mapping[str, LegalIRHammerFamilyCoverage],
    required_families: Sequence[str],
) -> tuple[str, ...]:
    reasons: List[str] = []
    cells_by_family = {
        family: [cell for cell in matrix if cell.behavior_family == family]
        for family in required_families
    }
    for family in required_families:
        summary = coverage_by_family.get(family)
        cells = cells_by_family.get(family, [])
        if not summary or not summary.cell_count:
            reasons.append(f"required_family_without_obligation:{family}")
        if not summary or not (
            summary.has_executable_trusted_route or summary.waived
        ):
            reasons.append(f"required_family_without_trusted_route_or_waiver:{family}")
        for cell in cells:
            if cell.covered:
                continue
            reasons.append(
                "required_cell_without_trusted_route_or_waiver:"
                f"{family}:{cell.contract_id}:{cell.field_path}:{cell.obligation_family}"
            )
    return tuple(_unique(reasons))


def build_legal_ir_hammer_coverage_report(
    sample_or_document: Any = None,
    *,
    obligations: Optional[Sequence[LegalIRProofObligation | Mapping[str, Any]]] = None,
    artifacts: Optional[Sequence[HammerGuidanceArtifact | Mapping[str, Any]]] = None,
    route_results: Optional[Sequence[Any]] = None,
    translation_records: Optional[Sequence[HammerTranslationRecord | Mapping[str, Any]]] = None,
    reconstruction_receipts: Optional[Sequence[HammerReconstructionReceipt | Mapping[str, Any]]] = None,
    required_families: Sequence[str] = REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES,
    waivers: Optional[Sequence[LegalIRHammerCoverageWaiver | Mapping[str, Any]]] = None,
) -> LegalIRHammerCoverageReport:
    """Build the deterministic obligation coverage report."""

    resolved_obligations = [
        _as_obligation(item)
        for item in (
            obligations
            if obligations is not None
            else generate_legal_ir_proof_obligations(sample_or_document)
        )
    ]
    resolved_artifacts = [_artifact_from(item) for item in artifacts or ()]
    resolved_records = [_translation_from(item) for item in translation_records or ()]
    resolved_receipts = [_receipt_from(item) for item in reconstruction_receipts or ()]
    resolved_waivers = [_waiver_from(item) for item in waivers or ()]
    resolved_required_families = tuple(dict.fromkeys(str(item) for item in required_families))

    evidence, unsupported = _collect_evidence(
        obligations=resolved_obligations,
        artifacts=resolved_artifacts,
        route_results=list(route_results or ()),
        translation_records=resolved_records,
        reconstruction_receipts=resolved_receipts,
    )
    matrix = _build_matrix(resolved_obligations, evidence, resolved_waivers)
    coverage_by_family = _family_coverage(
        matrix=matrix,
        unsupported_translations=unsupported,
        required_families=resolved_required_families,
    )
    block_reasons = _promotion_block_reasons(
        matrix=matrix,
        coverage_by_family=coverage_by_family,
        required_families=resolved_required_families,
    )
    return LegalIRHammerCoverageReport(
        matrix=matrix,
        coverage_by_family=coverage_by_family,
        unsupported_translations=unsupported,
        waivers=tuple(sorted(resolved_waivers, key=lambda waiver: waiver.waiver_id)),
        required_families=resolved_required_families,
        block_reasons=block_reasons,
        obligation_count=len(resolved_obligations),
    )


def coverage_report_from_hammer_report(
    report: Any,
    *,
    sample_or_document: Any = None,
    obligations: Optional[Sequence[LegalIRProofObligation | Mapping[str, Any]]] = None,
    required_families: Sequence[str] = REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES,
    waivers: Optional[Sequence[LegalIRHammerCoverageWaiver | Mapping[str, Any]]] = None,
) -> LegalIRHammerCoverageReport:
    """Rebuild coverage from a live or serialized Legal IR Hammer report."""

    if isinstance(report, LegalIRHammerCoverageReport):
        return report
    report_mapping = _as_mapping(report)
    if not report_mapping:
        existing = getattr(report, "coverage_report", None)
        if isinstance(existing, LegalIRHammerCoverageReport):
            return existing
    explicit_obligations = obligations
    if explicit_obligations is None:
        if report_mapping:
            explicit_obligations = _coverage_obligations_from_report_dict(report_mapping)
        elif hasattr(report, "artifacts"):
            explicit_obligations = [
                _obligation_from_artifact(artifact)
                for artifact in getattr(report, "artifacts", []) or []
            ]
    if not explicit_obligations and sample_or_document is not None:
        explicit_obligations = generate_legal_ir_proof_obligations(sample_or_document)

    artifacts = (
        report_mapping.get("artifacts", [])
        if report_mapping
        else getattr(report, "artifacts", [])
    )
    translation_records = (
        report_mapping.get("translation_records", [])
        if report_mapping
        else getattr(report, "translation_records", [])
    )
    reconstruction_receipts = (
        report_mapping.get("reconstruction_receipts", [])
        if report_mapping
        else getattr(report, "reconstruction_receipts", [])
    )
    route_results = (
        report_mapping.get("route_results", [])
        if report_mapping
        else getattr(report, "route_results", [])
    )
    return build_legal_ir_hammer_coverage_report(
        sample_or_document,
        obligations=explicit_obligations,
        artifacts=artifacts,
        route_results=route_results,
        translation_records=translation_records,
        reconstruction_receipts=reconstruction_receipts,
        required_families=required_families,
        waivers=waivers,
    )


def _result_value(result: Any) -> Any:
    if isinstance(result, Mapping) and "result" in result:
        return result.get("result")
    return result


def _run_counterexample_verifier(
    verifier: Optional[Callable[[Mapping[str, Any]], Any]],
    candidate: Mapping[str, Any],
) -> Any:
    if verifier is None:
        return candidate.get("result")
    return _result_value(verifier(candidate))


def _path_join(parent: str, child: Any) -> str:
    child_text = str(child)
    return child_text if not parent else f"{parent}.{child_text}"


def _minimize_value(
    value: Any,
    *,
    verifier: Optional[Callable[[Mapping[str, Any]], Any]],
    baseline_result: Any,
    root: Dict[str, Any],
    path: str,
    removed_paths: List[str],
) -> Any:
    if isinstance(value, dict):
        for key in list(value.keys()):
            old = value[key]
            del value[key]
            if _run_counterexample_verifier(verifier, root) == baseline_result:
                removed_paths.append(_path_join(path, key))
                continue
            value[key] = old
            value[key] = _minimize_value(
                value[key],
                verifier=verifier,
                baseline_result=baseline_result,
                root=root,
                path=_path_join(path, key),
                removed_paths=removed_paths,
            )
        return value
    if isinstance(value, list):
        index = 0
        while index < len(value):
            old = value.pop(index)
            if _run_counterexample_verifier(verifier, root) == baseline_result:
                removed_paths.append(f"{path}[{index}]")
                continue
            value.insert(index, old)
            value[index] = _minimize_value(
                value[index],
                verifier=verifier,
                baseline_result=baseline_result,
                root=root,
                path=f"{path}[{index}]",
                removed_paths=removed_paths,
            )
            index += 1
        return value
    return value


def minimize_verified_counterexample(
    counterexample: Mapping[str, Any],
    *,
    verifier: Optional[Callable[[Mapping[str, Any]], Any]] = None,
) -> LegalIRMinimizedCounterexample:
    """Greedily remove counterexample payload parts while preserving result."""

    original = copy.deepcopy(dict(counterexample))
    minimized = copy.deepcopy(original)
    baseline_result = _run_counterexample_verifier(verifier, original)
    removed_paths: List[str] = []
    for key in list(minimized.keys()):
        if key in {"result", "verified"}:
            continue
        old = minimized[key]
        del minimized[key]
        if _run_counterexample_verifier(verifier, minimized) == baseline_result:
            removed_paths.append(str(key))
            continue
        minimized[key] = old
        minimized[key] = _minimize_value(
            minimized[key],
            verifier=verifier,
            baseline_result=baseline_result,
            root=minimized,
            path=str(key),
            removed_paths=removed_paths,
        )
    result_preserved = _run_counterexample_verifier(verifier, minimized) == baseline_result
    original_size = _content_size(original)
    minimized_size = _content_size(minimized)
    return LegalIRMinimizedCounterexample(
        original_sha256=_stable_hash(original),
        minimized_sha256=_stable_hash(minimized),
        original_size_bytes=original_size,
        minimized_size_bytes=minimized_size,
        result=str(baseline_result),
        verified=bool(original.get("verified")),
        result_preserved=result_preserved,
        changed=minimized != original,
        removed_paths=tuple(_unique(removed_paths)),
        minimized_counterexample=minimized,
    )


__all__ = [
    "LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION",
    "REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES",
    "LegalIRHammerCoverageCell",
    "LegalIRHammerCoverageReport",
    "LegalIRHammerCoverageWaiver",
    "LegalIRHammerFamilyCoverage",
    "LegalIRHammerUnsupportedTranslation",
    "LegalIRMinimizedCounterexample",
    "build_legal_ir_hammer_coverage_report",
    "coverage_report_from_hammer_report",
    "minimize_verified_counterexample",
]
