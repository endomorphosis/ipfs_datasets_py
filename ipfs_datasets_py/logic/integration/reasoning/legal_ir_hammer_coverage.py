"""Coverage and promotion gates for Legal IR Hammer obligations.

The Hammer runner produces proof artifacts, translation receipts, and route
audits.  This module turns those records into the promotion-facing coverage
surface: every required Legal IR behavior family must either have an executed
trusted route or an explicit approved waiver, while unsupported translations
and verified counterexamples remain separated from proof failures.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Final, Mapping, Optional, Sequence

from .hammer_guidance import HammerGuidanceArtifact
from .legal_ir_hammer_translation import HammerReconstructionReceipt, HammerTranslationRecord
from .legal_ir_obligations import LegalIRProofObligation, generate_legal_ir_proof_obligations
from .legal_ir_proof_router import (
    LegalIRProofRouteResult,
    ProofRouteStatus,
    ProofTrustLevel,
)
from .legal_ir_view_contracts import (
    LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
    LegalIRViewContract,
    legal_ir_view_contracts,
)


LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION: Final = "legal-ir-hammer-coverage-v1"


class LegalIRHammerCoverageFamily(str, Enum):
    """Promotion-relevant Legal IR behavior families."""

    WELL_FORMEDNESS = "well_formedness"
    CROSS_VIEW_CONSISTENCY = "cross_view_consistency"
    MODALITY = "modality"
    EXCEPTION = "exception"
    TEMPORAL = "temporal"
    GRAPH = "graph"
    LIFECYCLE = "lifecycle"
    PROVENANCE = "provenance"
    ROUND_TRIP = "round_trip"


REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES: Final[tuple[str, ...]] = tuple(
    family.value for family in LegalIRHammerCoverageFamily
)

_FIELD_KEYS: Final = frozenset(
    {
        "required_field",
        "field_path",
        "slot",
        "target_field",
    }
)
_COUNTEREXAMPLE_PROTECTED_KEYS: Final = frozenset(
    {
        "checker",
        "counterexample_digest",
        "counterexample_type",
        "evidence_id",
        "evidence_ids",
        "kind",
        "receipt_id",
        "receipt_ids",
        "result",
        "status",
        "verified",
        "verifier",
        "verifier_attested",
        "witness_digest",
    }
)


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _unique_text(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _coverage_family_for_obligation(obligation: LegalIRProofObligation) -> str:
    kind = str(obligation.kind or "").lower()
    metadata = dict(obligation.metadata or {})
    scope = str(metadata.get("coverage_scope") or "").lower()
    family = str(metadata.get("obligation_family") or obligation.kind or "").lower()
    view = str(obligation.legal_ir_view or "").lower()
    field = str(metadata.get("required_field") or "").lower()

    if scope == "cross_view_consistency" or kind.startswith("cross_view") or family.startswith("cross_view"):
        return LegalIRHammerCoverageFamily.CROSS_VIEW_CONSISTENCY.value
    if scope == "required_field" or kind.endswith("_required_fields") or family.endswith("_required_fields"):
        if field.endswith("provenance_ids") or field == "provenance_ids":
            return LegalIRHammerCoverageFamily.PROVENANCE.value
        return LegalIRHammerCoverageFamily.WELL_FORMEDNESS.value
    if "provenance" in kind or "provenance" in family:
        return LegalIRHammerCoverageFamily.PROVENANCE.value
    if "round_trip" in kind or "decompiler" in kind or "round_trip" in family or "decompiler" in family or "decompiler" in view:
        return LegalIRHammerCoverageFamily.ROUND_TRIP.value
    if "exception" in kind or "exception" in family:
        return LegalIRHammerCoverageFamily.EXCEPTION.value
    if "temporal" in kind or "temporal" in family or "tdfol" in view:
        return LegalIRHammerCoverageFamily.TEMPORAL.value
    if "lifecycle" in kind or "event_consistency" in family or "cec" in view:
        return LegalIRHammerCoverageFamily.LIFECYCLE.value
    if "graph" in kind or "knowledge_graph" in kind or "graph" in family or "knowledge_graph" in view:
        return LegalIRHammerCoverageFamily.GRAPH.value
    if "modal" in kind or "deontic" in kind or "polarity" in kind or "frame_role" in kind:
        return LegalIRHammerCoverageFamily.MODALITY.value
    return LegalIRHammerCoverageFamily.WELL_FORMEDNESS.value


def _required_cells_from_contracts(
    contracts: Sequence[LegalIRViewContract],
) -> tuple[dict[str, str], ...]:
    cells: list[dict[str, str]] = []
    for contract in contracts:
        required_field_families = tuple(
            family
            for family in contract.obligation_families
            if family.endswith("_required_fields")
        ) or (f"{contract.view.value}_required_fields",)
        for requirement in contract.required_fields:
            behavior_family = (
                LegalIRHammerCoverageFamily.PROVENANCE.value
                if requirement.path == contract.provenance_requirements.identifier_field
                else LegalIRHammerCoverageFamily.WELL_FORMEDNESS.value
            )
            for obligation_family in required_field_families:
                cells.append(
                    {
                        "behavior_family": behavior_family,
                        "contract_id": contract.contract_id,
                        "contract_view": contract.view.value,
                        "field_path": requirement.path,
                        "obligation_family": obligation_family,
                        "target_component": contract.target_component,
                    }
                )
        for obligation_family in contract.all_obligation_families:
            if obligation_family.endswith("_required_fields"):
                continue
            cells.append(
                {
                    "behavior_family": _coverage_family_for_family_name(obligation_family),
                    "contract_id": contract.contract_id,
                    "contract_view": contract.view.value,
                    "field_path": "",
                    "obligation_family": obligation_family,
                    "target_component": contract.target_component,
                }
            )
    return tuple(cells)


def _coverage_family_for_family_name(obligation_family: str) -> str:
    fake = LegalIRProofObligation(
        obligation_id="registry-family",
        statement="registry_family",
        kind=str(obligation_family),
        legal_ir_view="",
        logic_family="",
        metadata={"obligation_family": str(obligation_family)},
    )
    return _coverage_family_for_obligation(fake)


@dataclass(frozen=True)
class LegalIRHammerCoverageWaiver:
    """Explicit promotion waiver for one matrix slice."""

    waiver_id: str
    behavior_family: str
    reason_code: str
    approved_by: str
    contract_id: str = ""
    field_path: str = ""
    obligation_family: str = ""
    approved: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return bool(
            self.approved
            and self.waiver_id
            and self.behavior_family
            and self.reason_code
            and self.approved_by
        )

    def applies_to(self, cell: "LegalIRHammerCoverageCell") -> bool:
        if not self.valid:
            return False
        if self.behavior_family and self.behavior_family != cell.behavior_family:
            return False
        if self.contract_id and self.contract_id != cell.contract_id:
            return False
        if self.field_path and self.field_path != cell.field_path:
            return False
        if self.obligation_family and self.obligation_family != cell.obligation_family:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": bool(self.approved),
            "approved_by": self.approved_by,
            "behavior_family": self.behavior_family,
            "contract_id": self.contract_id,
            "field_path": self.field_path,
            "metadata": dict(sorted(self.metadata.items())),
            "obligation_family": self.obligation_family,
            "reason_code": self.reason_code,
            "valid": self.valid,
            "waiver_id": self.waiver_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegalIRHammerCoverageWaiver":
        return cls(
            waiver_id=str(value.get("waiver_id") or value.get("id") or ""),
            behavior_family=str(value.get("behavior_family") or value.get("family") or ""),
            reason_code=str(value.get("reason_code") or value.get("reason") or ""),
            approved_by=str(value.get("approved_by") or value.get("approver") or ""),
            contract_id=str(value.get("contract_id") or ""),
            field_path=str(value.get("field_path") or value.get("required_field") or ""),
            obligation_family=str(value.get("obligation_family") or ""),
            approved=bool(
                value.get(
                    "approved",
                    str(value.get("status") or "approved").lower()
                    in {"approved", "active"},
                )
            ),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRUnsupportedTranslation:
    """Capability gap record kept separate from failed theorem records."""

    unsupported_id: str
    obligation_id: str
    behavior_family: str
    route: str = ""
    reason: str = ""
    translation_record_id: str = ""
    surface: str = ""
    target_format: str = ""
    errors: tuple[str, ...] = ()
    contract_id: str = ""
    field_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "behavior_family": self.behavior_family,
            "contract_id": self.contract_id,
            "errors": list(self.errors),
            "field_path": self.field_path,
            "obligation_id": self.obligation_id,
            "reason": self.reason,
            "route": self.route,
            "surface": self.surface,
            "target_format": self.target_format,
            "translation_record_id": self.translation_record_id,
            "unsupported_id": self.unsupported_id,
        }


@dataclass(frozen=True)
class LegalIRCounterexampleMinimization:
    """Source-free summary of a verified counterexample shrink pass."""

    minimization_id: str
    original_digest: str
    minimized_digest: str
    original_result: str
    minimized_result: str
    original_size_bytes: int
    minimized_size_bytes: int
    removed_paths: tuple[str, ...] = ()
    verified: bool = True

    @property
    def result_preserved(self) -> bool:
        return self.original_result == self.minimized_result

    @property
    def changed(self) -> bool:
        return self.original_digest != self.minimized_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "minimized_digest": self.minimized_digest,
            "minimized_result": self.minimized_result,
            "minimized_size_bytes": int(self.minimized_size_bytes),
            "minimization_id": self.minimization_id,
            "original_digest": self.original_digest,
            "original_result": self.original_result,
            "original_size_bytes": int(self.original_size_bytes),
            "removed_paths": list(self.removed_paths),
            "result_preserved": self.result_preserved,
            "verified": bool(self.verified),
        }


@dataclass(frozen=True)
class LegalIRHammerCoverageCell:
    """One contract-field-by-family matrix cell."""

    behavior_family: str
    contract_id: str
    contract_view: str
    target_component: str
    field_path: str
    obligation_family: str
    obligation_ids: tuple[str, ...] = ()
    executable_routes: tuple[str, ...] = ()
    trusted_routes: tuple[str, ...] = ()
    route_statuses: Mapping[str, str] = field(default_factory=dict)
    trusted_receipt_ids: tuple[str, ...] = ()
    trusted_guidance_ids: tuple[str, ...] = ()
    unsupported_translation_ids: tuple[str, ...] = ()
    waiver_ids: tuple[str, ...] = ()

    @property
    def obligation_count(self) -> int:
        return len(self.obligation_ids)

    @property
    def has_obligation(self) -> bool:
        return bool(self.obligation_ids)

    @property
    def has_executable_route(self) -> bool:
        return bool(self.executable_routes)

    @property
    def has_executable_trusted_route(self) -> bool:
        return bool(self.trusted_routes or self.trusted_receipt_ids or self.trusted_guidance_ids)

    @property
    def waived(self) -> bool:
        return bool(self.waiver_ids)

    @property
    def covered(self) -> bool:
        return self.has_executable_trusted_route or self.waived

    @property
    def unsupported_translation_count(self) -> int:
        return len(self.unsupported_translation_ids)

    def key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.contract_id,
            self.contract_view,
            self.target_component,
            self.field_path,
            self.obligation_family,
            self.behavior_family,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "behavior_family": self.behavior_family,
            "contract_id": self.contract_id,
            "contract_view": self.contract_view,
            "covered": self.covered,
            "executable_routes": list(self.executable_routes),
            "field_path": self.field_path,
            "has_executable_route": self.has_executable_route,
            "has_executable_trusted_route": self.has_executable_trusted_route,
            "has_obligation": self.has_obligation,
            "obligation_count": self.obligation_count,
            "obligation_family": self.obligation_family,
            "obligation_ids": list(self.obligation_ids),
            "route_statuses": dict(sorted(self.route_statuses.items())),
            "target_component": self.target_component,
            "trusted_guidance_ids": list(self.trusted_guidance_ids),
            "trusted_receipt_ids": list(self.trusted_receipt_ids),
            "trusted_routes": list(self.trusted_routes),
            "unsupported_translation_count": self.unsupported_translation_count,
            "unsupported_translation_ids": list(self.unsupported_translation_ids),
            "waived": self.waived,
            "waiver_ids": list(self.waiver_ids),
        }


@dataclass(frozen=True)
class LegalIRHammerCoverageReport:
    """Complete Hammer obligation coverage report and promotion decision."""

    coverage_id: str
    matrix: tuple[LegalIRHammerCoverageCell, ...]
    required_families: tuple[str, ...]
    block_reasons: tuple[str, ...]
    unsupported_translations: tuple[LegalIRUnsupportedTranslation, ...] = ()
    counterexample_minimizations: tuple[LegalIRCounterexampleMinimization, ...] = ()
    waivers: tuple[LegalIRHammerCoverageWaiver, ...] = ()
    obligation_count: int = 0
    schema_version: str = LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION
    contract_registry_version: str = LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION

    @property
    def promotion_allowed(self) -> bool:
        return not self.block_reasons

    @property
    def covered_family_count(self) -> int:
        return len(
            {
                cell.behavior_family
                for cell in self.matrix
                if cell.covered and cell.behavior_family in self.required_families
            }
        )

    @property
    def required_family_count(self) -> int:
        return len(self.required_families)

    @property
    def coverage_by_family(self) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        for family in self.required_families:
            cells = [cell for cell in self.matrix if cell.behavior_family == family]
            summary[family] = {
                "cell_count": len(cells),
                "covered_cell_count": sum(1 for cell in cells if cell.covered),
                "executable_trusted_route_count": sum(
                    1 for cell in cells if cell.has_executable_trusted_route
                ),
                "missing_cell_count": sum(1 for cell in cells if not cell.covered),
                "unsupported_translation_count": sum(
                    cell.unsupported_translation_count for cell in cells
                ),
                "waived_cell_count": sum(1 for cell in cells if cell.waived),
            }
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_reasons": list(self.block_reasons),
            "contract_registry_version": self.contract_registry_version,
            "counterexample_minimizations": [
                item.to_dict() for item in self.counterexample_minimizations
            ],
            "coverage_by_family": self.coverage_by_family,
            "coverage_id": self.coverage_id,
            "covered_family_count": self.covered_family_count,
            "matrix": [cell.to_dict() for cell in self.matrix],
            "matrix_cell_count": len(self.matrix),
            "obligation_count": int(self.obligation_count),
            "promotion_allowed": self.promotion_allowed,
            "required_families": list(self.required_families),
            "required_family_count": self.required_family_count,
            "schema_version": self.schema_version,
            "unsupported_translation_count": len(self.unsupported_translations),
            "unsupported_translations": [
                item.to_dict() for item in self.unsupported_translations
            ],
            "waivers": [waiver.to_dict() for waiver in self.waivers],
        }


CounterexampleVerifier = Callable[[Mapping[str, Any]], Any]


def minimize_verified_counterexample(
    counterexample: Mapping[str, Any],
    *,
    verifier: Optional[CounterexampleVerifier] = None,
) -> LegalIRCounterexampleMinimization:
    """Minimize a verified counterexample while preserving verifier result.

    The minimized witness is never returned or persisted by this API.  Only
    digests, byte counts, and removed paths are recorded.
    """

    original = _json_ready(counterexample)
    if not isinstance(original, Mapping):
        raise TypeError("counterexample must be a mapping")
    original_map = dict(original)
    if not bool(original_map.get("verified") or original_map.get("verifier_attested")):
        raise ValueError("counterexample must be verifier-attested before minimization")
    expected = _counterexample_result(original_map, verifier)
    minimized, removed = _minimize_value(
        original_map,
        (),
        expected,
        verifier,
        lambda candidate: candidate if isinstance(candidate, Mapping) else {},
    )
    minimized_result = _counterexample_result(minimized, verifier)
    if minimized_result != expected:
        minimized = original_map
        removed = ()
        minimized_result = expected
    original_json = _stable_json(original_map)
    minimized_json = _stable_json(minimized)
    payload = {
        "minimized_digest": _stable_hash(minimized),
        "original_digest": _stable_hash(original_map),
        "removed_paths": list(removed),
        "result": expected,
    }
    return LegalIRCounterexampleMinimization(
        minimization_id=f"lir-counterexample-min-{_stable_hash(payload)[:20]}",
        original_digest=_stable_hash(original_map),
        minimized_digest=_stable_hash(minimized),
        original_result=expected,
        minimized_result=minimized_result,
        original_size_bytes=len(original_json.encode("utf-8")),
        minimized_size_bytes=len(minimized_json.encode("utf-8")),
        removed_paths=tuple(removed),
        verified=minimized_result == expected,
    )


def minimize_verified_counterexamples(
    counterexamples: Sequence[Mapping[str, Any]],
    *,
    verifier: Optional[CounterexampleVerifier] = None,
) -> tuple[LegalIRCounterexampleMinimization, ...]:
    return tuple(
        minimize_verified_counterexample(counterexample, verifier=verifier)
        for counterexample in counterexamples
    )


def build_legal_ir_hammer_coverage_report(
    sample_or_document: Any = None,
    *,
    obligations: Optional[Sequence[LegalIRProofObligation | Mapping[str, Any]]] = None,
    artifacts: Sequence[HammerGuidanceArtifact | Mapping[str, Any]] = (),
    translation_records: Sequence[HammerTranslationRecord | Mapping[str, Any]] = (),
    reconstruction_receipts: Sequence[HammerReconstructionReceipt | Mapping[str, Any]] = (),
    route_results: Sequence[LegalIRProofRouteResult | Mapping[str, Any]] = (),
    waivers: Sequence[LegalIRHammerCoverageWaiver | Mapping[str, Any]] = (),
    counterexamples: Sequence[Mapping[str, Any]] = (),
    counterexample_verifier: Optional[CounterexampleVerifier] = None,
    required_families: Sequence[str] = REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES,
    contracts: Optional[Sequence[LegalIRViewContract]] = None,
) -> LegalIRHammerCoverageReport:
    """Build a coverage matrix from Hammer proof and translation artifacts."""

    resolved_obligations = [
        _as_obligation(item)
        for item in (
            obligations
            if obligations is not None
            else generate_legal_ir_proof_obligations(sample_or_document)
        )
    ]
    resolved_contracts = tuple(contracts or legal_ir_view_contracts())
    resolved_waivers = tuple(
        waiver
        if isinstance(waiver, LegalIRHammerCoverageWaiver)
        else LegalIRHammerCoverageWaiver.from_mapping(waiver)
        for waiver in waivers
    )
    required = tuple(dict.fromkeys(str(item) for item in required_families if str(item)))
    artifacts_by_obligation = _artifacts_by_obligation(artifacts)
    receipts_by_obligation = _receipts_by_obligation(reconstruction_receipts)
    routes_by_obligation = _routes_by_obligation(route_results)
    translations_by_obligation = _translations_by_obligation(translation_records)
    unsupported = _unsupported_translation_records(
        resolved_obligations,
        routes_by_obligation,
        translations_by_obligation,
    )
    unsupported_by_obligation = _unsupported_by_obligation(unsupported)

    cell_values: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for base in _required_cells_from_contracts(resolved_contracts):
        key = (
            base["contract_id"],
            base["contract_view"],
            base["target_component"],
            base["field_path"],
            base["obligation_family"],
            base["behavior_family"],
        )
        cell_values.setdefault(key, _empty_cell_value(base))

    for obligation in resolved_obligations:
        descriptor = _cell_descriptor(obligation, resolved_contracts)
        key = (
            descriptor["contract_id"],
            descriptor["contract_view"],
            descriptor["target_component"],
            descriptor["field_path"],
            descriptor["obligation_family"],
            descriptor["behavior_family"],
        )
        value = cell_values.setdefault(key, _empty_cell_value(descriptor))
        value["obligation_ids"].append(obligation.obligation_id)
        route_result = routes_by_obligation.get(obligation.obligation_id)
        artifact = artifacts_by_obligation.get(obligation.obligation_id)
        receipt = receipts_by_obligation.get(obligation.obligation_id)
        value["route_statuses"].update(_route_statuses(route_result))
        value["executable_routes"].extend(_executable_routes(route_result, artifact, receipt))
        value["trusted_routes"].extend(_trusted_routes(route_result, artifact, receipt))
        if artifact is not None and bool(_mapping(artifact).get("trusted")):
            value["trusted_guidance_ids"].append(str(_mapping(artifact).get("guidance_id") or ""))
        if receipt is not None and bool(_mapping(receipt).get("trusted")):
            value["trusted_receipt_ids"].append(str(_mapping(receipt).get("receipt_id") or ""))
        value["unsupported_translation_ids"].extend(
            item.unsupported_id
            for item in unsupported_by_obligation.get(obligation.obligation_id, ())
        )

    matrix: list[LegalIRHammerCoverageCell] = []
    for key in sorted(cell_values):
        value = cell_values[key]
        provisional = LegalIRHammerCoverageCell(
            behavior_family=value["behavior_family"],
            contract_id=value["contract_id"],
            contract_view=value["contract_view"],
            target_component=value["target_component"],
            field_path=value["field_path"],
            obligation_family=value["obligation_family"],
            obligation_ids=_unique_text(value["obligation_ids"]),
            executable_routes=_unique_text(value["executable_routes"]),
            trusted_routes=_unique_text(value["trusted_routes"]),
            route_statuses=dict(sorted(value["route_statuses"].items())),
            trusted_receipt_ids=_unique_text(value["trusted_receipt_ids"]),
            trusted_guidance_ids=_unique_text(value["trusted_guidance_ids"]),
            unsupported_translation_ids=_unique_text(value["unsupported_translation_ids"]),
        )
        waiver_ids = tuple(
            waiver.waiver_id for waiver in resolved_waivers if waiver.applies_to(provisional)
        )
        matrix.append(
            LegalIRHammerCoverageCell(
                behavior_family=provisional.behavior_family,
                contract_id=provisional.contract_id,
                contract_view=provisional.contract_view,
                target_component=provisional.target_component,
                field_path=provisional.field_path,
                obligation_family=provisional.obligation_family,
                obligation_ids=provisional.obligation_ids,
                executable_routes=provisional.executable_routes,
                trusted_routes=provisional.trusted_routes,
                route_statuses=provisional.route_statuses,
                trusted_receipt_ids=provisional.trusted_receipt_ids,
                trusted_guidance_ids=provisional.trusted_guidance_ids,
                unsupported_translation_ids=provisional.unsupported_translation_ids,
                waiver_ids=waiver_ids,
            )
        )

    counterexample_minimizations = minimize_verified_counterexamples(
        counterexamples,
        verifier=counterexample_verifier,
    )
    block_reasons = _promotion_block_reasons(matrix, required)
    payload = {
        "blocks": block_reasons,
        "matrix": [cell.to_dict() for cell in matrix],
        "required": required,
        "unsupported": [item.to_dict() for item in unsupported],
    }
    return LegalIRHammerCoverageReport(
        coverage_id=f"lir-hammer-coverage-{_stable_hash(payload)[:24]}",
        matrix=tuple(matrix),
        required_families=required,
        block_reasons=block_reasons,
        unsupported_translations=tuple(unsupported),
        counterexample_minimizations=counterexample_minimizations,
        waivers=resolved_waivers,
        obligation_count=len(resolved_obligations),
    )


def coverage_report_from_hammer_report(
    hammer_report: Any,
    *,
    sample_or_document: Any = None,
    obligations: Optional[Sequence[LegalIRProofObligation | Mapping[str, Any]]] = None,
    waivers: Sequence[LegalIRHammerCoverageWaiver | Mapping[str, Any]] = (),
    counterexamples: Sequence[Mapping[str, Any]] = (),
    counterexample_verifier: Optional[CounterexampleVerifier] = None,
    required_families: Sequence[str] = REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES,
) -> LegalIRHammerCoverageReport:
    """Convenience wrapper for :class:`LegalIRHammerReport`-like objects."""

    hammer_map = _mapping(hammer_report)
    artifacts = _sequence(
        getattr(hammer_report, "artifacts", None) or hammer_map.get("artifacts")
    )
    translation_records = _sequence(
        getattr(hammer_report, "translation_records", None)
        or hammer_map.get("translation_records")
    )
    reconstruction_receipts = _sequence(
        getattr(hammer_report, "reconstruction_receipts", None)
        or hammer_map.get("reconstruction_receipts")
    )
    route_results = _sequence(
        getattr(hammer_report, "route_results", None)
        or getattr(hammer_report, "proof_routing_results", None)
        or hammer_map.get("route_results")
    )
    resolved_obligations = obligations
    if resolved_obligations is None and (
        artifacts or translation_records or reconstruction_receipts or route_results
    ):
        resolved_obligations = _obligations_from_report_records(
            artifacts=artifacts,
            translation_records=translation_records,
            reconstruction_receipts=reconstruction_receipts,
            route_results=route_results,
        )

    return build_legal_ir_hammer_coverage_report(
        sample_or_document,
        obligations=resolved_obligations,
        artifacts=artifacts,
        translation_records=translation_records,
        reconstruction_receipts=reconstruction_receipts,
        route_results=route_results,
        waivers=waivers,
        counterexamples=counterexamples,
        counterexample_verifier=counterexample_verifier,
        required_families=required_families,
    )


def _obligations_from_report_records(
    *,
    artifacts: Sequence[Any],
    translation_records: Sequence[Any],
    reconstruction_receipts: Sequence[Any],
    route_results: Sequence[Any],
) -> tuple[LegalIRProofObligation, ...]:
    """Recover source-free obligation descriptors from persisted Hammer records."""

    rows: dict[str, dict[str, Any]] = {}

    def row(obligation_id: str) -> dict[str, Any]:
        return rows.setdefault(
            obligation_id,
            {
                "formula_id": "",
                "kind": "",
                "legal_ir_view": "",
                "logic_family": "",
                "metadata": {},
                "obligation_id": obligation_id,
                "premise_hints": [],
                "sample_id": "",
                "statement": "",
            },
        )

    for artifact in artifacts:
        data = _mapping(artifact)
        obligation_id = str(data.get("obligation_id") or "")
        if not obligation_id:
            continue
        metadata = dict(data.get("metadata") or {})
        current = row(obligation_id)
        current["kind"] = str(
            current["kind"]
            or metadata.get("obligation_kind")
            or metadata.get("kind")
            or ""
        )
        current["legal_ir_view"] = str(
            current["legal_ir_view"]
            or data.get("legal_ir_view")
            or metadata.get("legal_ir_view")
            or data.get("target_component")
            or metadata.get("target_component")
            or ""
        )
        current["logic_family"] = str(
            current["logic_family"]
            or data.get("logic_family")
            or metadata.get("logic_family")
            or ""
        )
        current["formula_id"] = str(current["formula_id"] or metadata.get("formula_id") or "")
        current["sample_id"] = str(current["sample_id"] or metadata.get("sample_id") or "")
        current["metadata"].update(metadata)

    for record in translation_records:
        data = _mapping(record)
        obligation_id = str(data.get("obligation_id") or "")
        if not obligation_id:
            continue
        current = row(obligation_id)
        current["formula_id"] = str(
            current["formula_id"] or data.get("input_formula_id") or ""
        )

    for receipt in reconstruction_receipts:
        data = _mapping(receipt)
        obligation_id = str(data.get("obligation_id") or "")
        if not obligation_id:
            continue
        current = row(obligation_id)
        current["formula_id"] = str(
            current["formula_id"] or data.get("input_formula_id") or ""
        )

    for route in route_results:
        data = _mapping(route)
        obligation_id = str(data.get("obligation_id") or "")
        if obligation_id:
            row(obligation_id)

    obligations: list[LegalIRProofObligation] = []
    for obligation_id in sorted(rows):
        data = rows[obligation_id]
        kind = str(data["kind"] or data["metadata"].get("obligation_family") or "")
        statement = str(
            data["statement"]
            or f"persisted_hammer_obligation(obligation:{obligation_id})"
        )
        obligations.append(
            LegalIRProofObligation(
                obligation_id=obligation_id,
                statement=statement,
                kind=kind,
                legal_ir_view=str(
                    data["legal_ir_view"]
                    or data["metadata"].get("target_component")
                    or ""
                ),
                logic_family=str(data["logic_family"] or ""),
                sample_id=str(data["sample_id"] or ""),
                formula_id=str(data["formula_id"] or ""),
                premise_hints=[str(item) for item in data["premise_hints"]],
                metadata=dict(data["metadata"]),
            )
        )
    return tuple(obligations)


def _as_obligation(value: LegalIRProofObligation | Mapping[str, Any]) -> LegalIRProofObligation:
    if isinstance(value, LegalIRProofObligation):
        return value
    return LegalIRProofObligation(
        obligation_id=str(value.get("obligation_id") or ""),
        statement=str(value.get("statement") or ""),
        kind=str(value.get("kind") or ""),
        legal_ir_view=str(value.get("legal_ir_view") or value.get("target_component") or ""),
        logic_family=str(value.get("logic_family") or value.get("family") or ""),
        sample_id=str(value.get("sample_id") or ""),
        formula_id=str(value.get("formula_id") or ""),
        premise_hints=[str(item) for item in value.get("premise_hints", []) or []],
        metadata=dict(value.get("metadata") or {}),
        schema_version=str(value.get("schema_version") or "legal-ir-proof-obligation-v1"),
    )


def _empty_cell_value(descriptor: Mapping[str, str]) -> dict[str, Any]:
    return {
        "behavior_family": descriptor["behavior_family"],
        "contract_id": descriptor["contract_id"],
        "contract_view": descriptor["contract_view"],
        "executable_routes": [],
        "field_path": descriptor["field_path"],
        "obligation_family": descriptor["obligation_family"],
        "obligation_ids": [],
        "route_statuses": {},
        "target_component": descriptor["target_component"],
        "trusted_guidance_ids": [],
        "trusted_receipt_ids": [],
        "trusted_routes": [],
        "unsupported_translation_ids": [],
    }


def _cell_descriptor(
    obligation: LegalIRProofObligation,
    contracts: Sequence[LegalIRViewContract],
) -> dict[str, str]:
    metadata = dict(obligation.metadata or {})
    contract_id = str(metadata.get("contract_id") or "")
    contract = _contract_for_obligation(obligation, contracts, contract_id)
    behavior_family = _coverage_family_for_obligation(obligation)
    field_path = ""
    for key in _FIELD_KEYS:
        if metadata.get(key):
            field_path = str(metadata[key])
            break
    obligation_family = str(
        metadata.get("obligation_family")
        or obligation.kind
        or behavior_family
    )
    return {
        "behavior_family": behavior_family,
        "contract_id": contract.contract_id if contract is not None else contract_id,
        "contract_view": contract.view.value if contract is not None else str(metadata.get("contract_view") or ""),
        "field_path": field_path,
        "obligation_family": obligation_family,
        "target_component": (
            contract.target_component
            if contract is not None
            else str(obligation.legal_ir_view or metadata.get("target_component") or "")
        ),
    }


def _contract_for_obligation(
    obligation: LegalIRProofObligation,
    contracts: Sequence[LegalIRViewContract],
    contract_id: str,
) -> Optional[LegalIRViewContract]:
    for contract in contracts:
        if contract_id and contract.contract_id == contract_id:
            return contract
    candidates = {
        str(obligation.legal_ir_view or ""),
        str(obligation.metadata.get("contract_view") or ""),
        str(obligation.metadata.get("target_component") or ""),
    }
    for contract in contracts:
        if contract.target_component in candidates or contract.view.value in candidates:
            return contract
    return None


def _artifacts_by_obligation(
    artifacts: Sequence[HammerGuidanceArtifact | Mapping[str, Any]],
) -> dict[str, HammerGuidanceArtifact | Mapping[str, Any]]:
    return {
        str(_mapping(artifact).get("obligation_id") or ""): artifact
        for artifact in artifacts
        if str(_mapping(artifact).get("obligation_id") or "")
    }


def _receipts_by_obligation(
    receipts: Sequence[HammerReconstructionReceipt | Mapping[str, Any]],
) -> dict[str, HammerReconstructionReceipt | Mapping[str, Any]]:
    return {
        str(_mapping(receipt).get("obligation_id") or ""): receipt
        for receipt in receipts
        if str(_mapping(receipt).get("obligation_id") or "")
    }


def _routes_by_obligation(
    route_results: Sequence[LegalIRProofRouteResult | Mapping[str, Any]],
) -> dict[str, LegalIRProofRouteResult | Mapping[str, Any]]:
    return {
        str(_mapping(route).get("obligation_id") or ""): route
        for route in route_results
        if str(_mapping(route).get("obligation_id") or "")
    }


def _translations_by_obligation(
    records: Sequence[HammerTranslationRecord | Mapping[str, Any]],
) -> dict[str, tuple[HammerTranslationRecord | Mapping[str, Any], ...]]:
    grouped: dict[str, list[HammerTranslationRecord | Mapping[str, Any]]] = {}
    for record in records:
        obligation_id = str(_mapping(record).get("obligation_id") or "")
        if obligation_id:
            grouped.setdefault(obligation_id, []).append(record)
    return {key: tuple(value) for key, value in grouped.items()}


def _route_statuses(route_result: Any) -> dict[str, str]:
    if route_result is None:
        return {}
    route_map = _mapping(route_result)
    attempts = route_map.get("attempts") or []
    statuses: dict[str, str] = {}
    for attempt in attempts:
        attempt_map = _mapping(attempt)
        route = str(attempt_map.get("route") or "")
        status = str(attempt_map.get("status") or "")
        if route:
            statuses[route] = status
    return statuses


def _executable_routes(route_result: Any, artifact: Any, receipt: Any) -> tuple[str, ...]:
    routes: list[str] = []
    if route_result is not None:
        for attempt in _mapping(route_result).get("attempts") or []:
            attempt_map = _mapping(attempt)
            if bool(attempt_map.get("executed", _attempt_executed(attempt_map))):
                routes.append(str(attempt_map.get("route") or ""))
    if not routes and (artifact is not None or receipt is not None):
        routes.append("hammer_pipeline")
    return _unique_text(routes)


def _trusted_routes(route_result: Any, artifact: Any, receipt: Any) -> tuple[str, ...]:
    trusted: list[str] = []
    if route_result is not None:
        route_map = _mapping(route_result)
        required = ProofTrustLevel.parse(route_map.get("required_trust") or "backend")
        for attempt in route_map.get("attempts") or []:
            attempt_map = _mapping(attempt)
            if str(attempt_map.get("status") or "") != ProofRouteStatus.PROVED.value:
                continue
            trust = ProofTrustLevel.parse(attempt_map.get("trust_level") or "none")
            if trust >= required and _attempt_executed(attempt_map):
                trusted.append(str(attempt_map.get("route") or ""))
    if not trusted and bool(_mapping(artifact).get("trusted")):
        trusted.append("hammer_guidance")
    if not trusted and bool(_mapping(receipt).get("trusted")):
        trusted.append("hammer_receipt")
    return _unique_text(trusted)


def _attempt_executed(attempt_map: Mapping[str, Any]) -> bool:
    status = str(attempt_map.get("status") or "")
    return status not in {ProofRouteStatus.SKIPPED.value, ProofRouteStatus.CANCELLED.value}


def _unsupported_translation_records(
    obligations: Sequence[LegalIRProofObligation],
    routes_by_obligation: Mapping[str, Any],
    translations_by_obligation: Mapping[str, Sequence[Any]],
) -> tuple[LegalIRUnsupportedTranslation, ...]:
    obligations_by_id = {item.obligation_id: item for item in obligations}
    records: list[LegalIRUnsupportedTranslation] = []
    for obligation_id, route_result in sorted(routes_by_obligation.items()):
        obligation = obligations_by_id.get(obligation_id)
        behavior_family = (
            _coverage_family_for_obligation(obligation)
            if obligation is not None
            else LegalIRHammerCoverageFamily.WELL_FORMEDNESS.value
        )
        descriptor = (
            _cell_descriptor(obligation, legal_ir_view_contracts())
            if obligation is not None
            else {"contract_id": "", "field_path": ""}
        )
        for attempt in _mapping(route_result).get("attempts") or []:
            attempt_map = _mapping(attempt)
            if str(attempt_map.get("status") or "") != ProofRouteStatus.UNSUPPORTED_TRANSLATION.value:
                continue
            payload = {
                "obligation_id": obligation_id,
                "reason": str(attempt_map.get("reason") or ""),
                "route": str(attempt_map.get("route") or ""),
            }
            records.append(
                LegalIRUnsupportedTranslation(
                    unsupported_id=f"lir-unsupported-translation-{_stable_hash(payload)[:20]}",
                    obligation_id=obligation_id,
                    behavior_family=behavior_family,
                    route=str(attempt_map.get("route") or ""),
                    reason=str(attempt_map.get("reason") or ""),
                    contract_id=str(descriptor.get("contract_id") or ""),
                    field_path=str(descriptor.get("field_path") or ""),
                )
            )
    for obligation_id, translations in sorted(translations_by_obligation.items()):
        obligation = obligations_by_id.get(obligation_id)
        behavior_family = (
            _coverage_family_for_obligation(obligation)
            if obligation is not None
            else LegalIRHammerCoverageFamily.WELL_FORMEDNESS.value
        )
        descriptor = (
            _cell_descriptor(obligation, legal_ir_view_contracts())
            if obligation is not None
            else {"contract_id": "", "field_path": ""}
        )
        for translation in translations:
            data = _mapping(translation)
            if bool(data.get("success", True)):
                continue
            errors = tuple(str(item) for item in data.get("errors", []) or [])
            payload = {
                "errors": errors,
                "obligation_id": obligation_id,
                "record": str(data.get("translation_id") or data.get("record_id") or ""),
            }
            records.append(
                LegalIRUnsupportedTranslation(
                    unsupported_id=f"lir-unsupported-translation-{_stable_hash(payload)[:20]}",
                    obligation_id=obligation_id,
                    behavior_family=behavior_family,
                    reason="translation_record_failed",
                    translation_record_id=str(data.get("translation_id") or data.get("record_id") or ""),
                    surface=str(data.get("surface") or ""),
                    target_format=str(data.get("target_format") or ""),
                    errors=errors,
                    contract_id=str(descriptor.get("contract_id") or ""),
                    field_path=str(descriptor.get("field_path") or ""),
                )
            )
    deduped: dict[str, LegalIRUnsupportedTranslation] = {
        record.unsupported_id: record for record in records
    }
    return tuple(deduped[key] for key in sorted(deduped))


def _unsupported_by_obligation(
    records: Sequence[LegalIRUnsupportedTranslation],
) -> dict[str, tuple[LegalIRUnsupportedTranslation, ...]]:
    grouped: dict[str, list[LegalIRUnsupportedTranslation]] = {}
    for record in records:
        grouped.setdefault(record.obligation_id, []).append(record)
    return {key: tuple(value) for key, value in grouped.items()}


def _promotion_block_reasons(
    matrix: Sequence[LegalIRHammerCoverageCell],
    required_families: Sequence[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    for family in required_families:
        cells = [cell for cell in matrix if cell.behavior_family == family]
        if not cells:
            reasons.append(f"missing_required_family:{family}")
            continue
        if not any(cell.has_executable_trusted_route or cell.waived for cell in cells):
            reasons.append(f"required_family_without_trusted_route_or_waiver:{family}")
        for cell in cells:
            if cell.has_obligation and not cell.covered:
                field_or_family = cell.field_path or cell.obligation_family or "semantic"
                reasons.append(
                    "required_cell_without_trusted_route_or_waiver:"
                    f"{family}:{cell.contract_id}:{field_or_family}"
                )
    return tuple(dict.fromkeys(reasons))


def _counterexample_result(
    value: Mapping[str, Any],
    verifier: Optional[CounterexampleVerifier],
) -> str:
    if verifier is not None:
        return _stable_json(verifier(value))
    for key in ("result", "status", "outcome"):
        if key in value:
            return _stable_json(value[key])
    return _stable_json(
        {
            "counterexample_type": value.get("counterexample_type") or value.get("kind") or "counterexample",
            "verified": bool(value.get("verified") or value.get("verifier_attested")),
        }
    )


def _minimize_value(
    value: Any,
    path: tuple[str, ...],
    expected_result: str,
    verifier: Optional[CounterexampleVerifier],
    root_builder: Callable[[Any], Mapping[str, Any]],
) -> tuple[Any, tuple[str, ...]]:
    current = copy.deepcopy(value)
    removed: list[str] = []
    if isinstance(current, Mapping):
        current_map = dict(current)
        changed = True
        while changed:
            changed = False
            for key in sorted(list(current_map), key=str):
                key_text = str(key)
                if key_text in _COUNTEREXAMPLE_PROTECTED_KEYS:
                    continue
                candidate = dict(current_map)
                candidate.pop(key)
                if _candidate_preserves_result(
                    root_builder(candidate),
                    expected_result,
                    verifier,
                ):
                    current_map = candidate
                    removed.append(_path((*path, key_text)))
                    changed = True
                    break
        for key in sorted(list(current_map), key=str):
            child, child_removed = _minimize_value(
                current_map[key],
                (*path, str(key)),
                expected_result,
                verifier,
                lambda child_candidate, key=key, current_map=current_map: root_builder(
                    {**current_map, key: child_candidate}
                ),
            )
            if child_removed:
                candidate = {**current_map, key: child}
                if _candidate_preserves_result(
                    root_builder(candidate),
                    expected_result,
                    verifier,
                ):
                    current_map = candidate
                    removed.extend(child_removed)
        return current_map, tuple(removed)
    if isinstance(current, list):
        current_list = list(current)
        changed = True
        while changed:
            changed = False
            for index in range(len(current_list)):
                candidate = current_list[:index] + current_list[index + 1 :]
                if _candidate_preserves_result(
                    root_builder(candidate),
                    expected_result,
                    verifier,
                ):
                    current_list = candidate
                    removed.append(_path((*path, str(index))))
                    changed = True
                    break
        return current_list, tuple(removed)
    return current, ()


def _candidate_preserves_result(
    candidate: Any,
    expected_result: str,
    verifier: Optional[CounterexampleVerifier],
) -> bool:
    if not isinstance(candidate, Mapping):
        if verifier is None:
            return False
        try:
            return _stable_json(verifier(candidate)) == expected_result  # type: ignore[arg-type]
        except Exception:
            return False
    if not bool(candidate.get("verified") or candidate.get("verifier_attested")):
        return False
    try:
        return _counterexample_result(candidate, verifier) == expected_result
    except Exception:
        return False


def _path(parts: Sequence[str]) -> str:
    return ".".join(str(part) for part in parts if str(part))


__all__ = [
    "LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION",
    "REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES",
    "LegalIRCounterexampleMinimization",
    "LegalIRHammerCoverageCell",
    "LegalIRHammerCoverageFamily",
    "LegalIRHammerCoverageReport",
    "LegalIRHammerCoverageWaiver",
    "LegalIRUnsupportedTranslation",
    "build_legal_ir_hammer_coverage_report",
    "coverage_report_from_hammer_report",
    "minimize_verified_counterexample",
    "minimize_verified_counterexamples",
]
