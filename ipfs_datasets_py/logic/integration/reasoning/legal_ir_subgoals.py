"""Deterministic decomposition of failed Legal IR hammer obligations.

Hammer failures are often too broad to be useful model prompts or safe Codex
work items.  This module turns a failed obligation into a small, source-free
sequence of contract-bound checks.  The decomposition is deliberately not a
proof step: subgoals remain guidance until the normal deterministic validators
and hammer reconstruction gates accept their results.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .legal_ir_obligations import LegalIRProofObligation
from .legal_ir_view_contracts import LegalIRViewContract, legal_ir_view_contract


LEGAL_IR_SUBGOAL_SCHEMA_VERSION = "legal-ir-hammer-subgoal-v1"
LEGAL_IR_SUBGOAL_DECOMPOSITION_SCHEMA_VERSION = (
    "legal-ir-hammer-subgoal-decomposition-v1"
)
DEFAULT_MAX_SUBGOALS_PER_OBLIGATION = 4
HARD_MAX_SUBGOALS_PER_OBLIGATION = 8
DEFAULT_SUBGOAL_VALIDATION_COMMAND = (
    ".venv-cuda/bin/python -m pytest "
    "tests/unit/logic/integration/test_legal_ir_subgoal_decomposition.py -q"
)


@dataclass(frozen=True)
class LegalIRSubgoalDecompositionConfig:
    """Bounds applied to every deterministic decomposition run."""

    max_subgoals_per_obligation: int = DEFAULT_MAX_SUBGOALS_PER_OBLIGATION

    def bounded_max_subgoals(self) -> int:
        try:
            requested = int(self.max_subgoals_per_obligation)
        except (TypeError, ValueError):
            requested = DEFAULT_MAX_SUBGOALS_PER_OBLIGATION
        return max(1, min(requested, HARD_MAX_SUBGOALS_PER_OBLIGATION))


@dataclass(frozen=True)
class LegalIRSubgoal:
    """One source-free, contract-bound unit of a failed hammer obligation."""

    subgoal_id: str
    parent_obligation_id: str
    ordinal: int
    subgoal_kind: str
    statement: str
    primary_contract_id: str
    target_view: str
    target_component: str
    logic_family: str
    failure_mode: str
    premise_hints: Sequence[str] = field(default_factory=tuple)
    allowed_paths: Sequence[str] = field(default_factory=tuple)
    validation_command: str = DEFAULT_SUBGOAL_VALIDATION_COMMAND
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SUBGOAL_SCHEMA_VERSION

    @property
    def proof_obligation_id(self) -> str:
        """Compatibility name used by Leanstral and hammer artifacts."""

        return self.parent_obligation_id

    @property
    def validation_commands(self) -> tuple[str, ...]:
        """Return the intentionally singular validation command as a sequence."""

        return (self.validation_command,)

    def to_codex_todo_projection(self) -> Dict[str, Any]:
        """Return a path-bounded TODO seed; no source or model prose is included."""

        return {
            "allowed_paths": list(self.allowed_paths),
            "contract_id": self.primary_contract_id,
            "failure_mode": self.failure_mode,
            "ordinal": int(self.ordinal),
            "parent_obligation_id": self.parent_obligation_id,
            "subgoal_id": self.subgoal_id,
            "subgoal_kind": self.subgoal_kind,
            "target_component": self.target_component,
            "validation_commands": [self.validation_command],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_paths": list(self.allowed_paths),
            "failure_mode": self.failure_mode,
            "logic_family": self.logic_family,
            "metadata": _json_ready_mapping(self.metadata),
            "ordinal": int(self.ordinal),
            "parent_obligation_id": self.parent_obligation_id,
            "premise_hints": list(self.premise_hints),
            "primary_contract_id": self.primary_contract_id,
            "proof_obligation_id": self.parent_obligation_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "subgoal_id": self.subgoal_id,
            "subgoal_kind": self.subgoal_kind,
            "target_component": self.target_component,
            "target_view": self.target_view,
            "validation_command": self.validation_command,
            "validation_commands": [self.validation_command],
        }


@dataclass(frozen=True)
class LegalIRSubgoalDecomposition:
    """Deterministic summary over all matched failed hammer obligations."""

    subgoals: Sequence[LegalIRSubgoal] = field(default_factory=tuple)
    failed_obligation_ids: Sequence[str] = field(default_factory=tuple)
    unmatched_failure_ids: Sequence[str] = field(default_factory=tuple)
    capped_parent_obligation_ids: Sequence[str] = field(default_factory=tuple)
    max_subgoals_per_obligation: int = DEFAULT_MAX_SUBGOALS_PER_OBLIGATION
    schema_version: str = LEGAL_IR_SUBGOAL_DECOMPOSITION_SCHEMA_VERSION

    @property
    def subgoal_count(self) -> int:
        return len(self.subgoals)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capped_parent_obligation_ids": list(self.capped_parent_obligation_ids),
            "failed_obligation_ids": list(self.failed_obligation_ids),
            "max_subgoals_per_obligation": int(self.max_subgoals_per_obligation),
            "schema_version": self.schema_version,
            "subgoal_count": self.subgoal_count,
            "subgoals": [subgoal.to_dict() for subgoal in self.subgoals],
            "unmatched_failure_ids": list(self.unmatched_failure_ids),
        }


class LegalIRSubgoalDecomposer:
    """Decompose supported failed obligations without consulting a model."""

    def __init__(
        self, config: LegalIRSubgoalDecompositionConfig | None = None
    ) -> None:
        self.config = config or LegalIRSubgoalDecompositionConfig()

    def decompose(
        self,
        obligations: Sequence[LegalIRProofObligation | Mapping[str, Any]],
        failures: Any,
    ) -> LegalIRSubgoalDecomposition:
        obligation_by_id = {
            item["obligation_id"]: item
            for raw in obligations
            if (item := _obligation_mapping(raw))["obligation_id"]
        }
        failure_by_id = _failed_hammer_items_by_obligation(failures)
        max_subgoals = self.config.bounded_max_subgoals()
        subgoals: List[LegalIRSubgoal] = []
        capped: List[str] = []

        for obligation_id in sorted(set(obligation_by_id) & set(failure_by_id)):
            obligation = obligation_by_id[obligation_id]
            failure = failure_by_id[obligation_id]
            templates = _templates_for_obligation(obligation)
            if len(templates) > max_subgoals:
                capped.append(obligation_id)
            contract = _contract_for_obligation(obligation)
            validation_command = _one_validation_command(contract)
            allowed_paths = _allowed_paths(contract)
            failure_mode = _failure_mode(failure)
            parent_statement_hash = hashlib.sha256(
                obligation["statement"].encode("utf-8")
            ).hexdigest()

            for ordinal, template in enumerate(templates[:max_subgoals], start=1):
                kind, statement_predicate, template_hints = template
                payload = {
                    "failure_mode": failure_mode,
                    "ordinal": ordinal,
                    "parent_obligation_id": obligation_id,
                    "primary_contract_id": contract.contract_id,
                    "subgoal_kind": kind,
                }
                subgoal_id = "lir-subgoal-" + _stable_hash(payload)[:20]
                hints = _unique_strings(
                    (*template_hints, *obligation.get("premise_hints", ()))
                )[:8]
                subgoals.append(
                    LegalIRSubgoal(
                        subgoal_id=subgoal_id,
                        parent_obligation_id=obligation_id,
                        ordinal=ordinal,
                        subgoal_kind=kind,
                        statement=(
                            f"{statement_predicate}(parent:{obligation_id}, "
                            f"contract:{contract.contract_id})"
                        ),
                        primary_contract_id=contract.contract_id,
                        target_view=contract.view.value,
                        target_component=contract.target_component,
                        logic_family=obligation["logic_family"],
                        failure_mode=failure_mode,
                        premise_hints=tuple(hints),
                        allowed_paths=allowed_paths,
                        validation_command=validation_command,
                        metadata={
                            "decomposition_family": _decomposition_family(obligation),
                            "parent_statement_sha256": parent_statement_hash,
                            "source_copy_policy": "hash_only",
                        },
                    )
                )

        failed_ids = tuple(sorted(failure_by_id))
        return LegalIRSubgoalDecomposition(
            subgoals=tuple(subgoals),
            failed_obligation_ids=failed_ids,
            unmatched_failure_ids=tuple(sorted(set(failure_by_id) - set(obligation_by_id))),
            capped_parent_obligation_ids=tuple(capped),
            max_subgoals_per_obligation=max_subgoals,
        )


_SUBGOAL_TEMPLATES: Mapping[
    str, Sequence[tuple[str, str, Sequence[str]]]
] = {
    "exception": (
        ("exception_trigger", "exception_trigger_is_typed", ("exception_trigger_identified",)),
        ("exception_scope", "exception_scope_is_bound", ("exception_scope_precedence",)),
        ("exception_priority", "exception_priority_is_ordered", ("defeasible_priority_orders_exceptions",)),
        ("exception_effect", "exception_effect_is_preserved", ("exception_scope_preserved",)),
    ),
    "temporal": (
        ("temporal_event", "temporal_event_is_typed", ("temporal_event_identity",)),
        ("temporal_anchor", "temporal_anchor_is_bound", ("temporal_anchor_present",)),
        ("temporal_relation", "temporal_relation_is_ordered", ("temporal_conditions_have_event_order",)),
        ("temporal_bound", "temporal_bound_is_finite", ("temporal_deadline_bound",)),
    ),
    "knowledge_graph": (
        ("kg_subject", "kg_subject_node_is_typed", ("kg_subject_is_typed",)),
        ("kg_predicate", "kg_predicate_edge_is_typed", ("kg_edges_are_typed",)),
        ("kg_object", "kg_object_node_is_typed", ("kg_object_is_typed",)),
        ("kg_endpoints", "kg_edge_endpoints_are_connected", ("frame_role_bindings_are_preserved",)),
    ),
    "cec": (
        ("cec_event", "cec_event_is_typed", ("cec_event_identity",)),
        ("cec_fluent", "cec_fluent_is_typed", ("cec_fluent_identity",)),
        ("cec_transition", "cec_transition_is_well_formed", ("cec_lifecycle_transition",)),
        ("cec_timepoint", "cec_timepoint_is_ordered", ("cec_temporal_consistency",)),
    ),
    "decompiler": (
        ("decompiler_operator", "decompiler_operator_is_retained", ("decompiler_retains_modal_operator",)),
        ("decompiler_predicate", "decompiler_predicate_signature_is_retained", ("decompiler_preserves_modal_signature",)),
        ("decompiler_structure", "decompiler_structure_is_reconstructed", ("decompiler_preserves_structural_summary",)),
        ("decompiler_provenance", "decompiler_provenance_is_hash_only", ("source_copy_guardrail_requires_summary_not_span",)),
    ),
    "generic": (
        ("contract_local_check", "contract_local_check_is_bounded", ("canonical_contract_required_field",)),
    ),
}


def build_legal_ir_subgoal_decomposition(
    obligations: Sequence[LegalIRProofObligation | Mapping[str, Any]],
    failures: Any,
    *,
    max_subgoals_per_obligation: int = DEFAULT_MAX_SUBGOALS_PER_OBLIGATION,
) -> LegalIRSubgoalDecomposition:
    """Return the complete deterministic decomposition report."""

    return LegalIRSubgoalDecomposer(
        LegalIRSubgoalDecompositionConfig(
            max_subgoals_per_obligation=max_subgoals_per_obligation
        )
    ).decompose(obligations, failures)


def decompose_failed_hammer_obligations(
    obligations: Sequence[LegalIRProofObligation | Mapping[str, Any]],
    failures: Any,
    *,
    max_subgoals_per_obligation: int = DEFAULT_MAX_SUBGOALS_PER_OBLIGATION,
) -> List[LegalIRSubgoal]:
    """Return bounded subgoals for only failed, known hammer obligations."""

    return list(
        build_legal_ir_subgoal_decomposition(
            obligations,
            failures,
            max_subgoals_per_obligation=max_subgoals_per_obligation,
        ).subgoals
    )


def project_legal_ir_subgoals_to_codex_todos(
    subgoals: Iterable[LegalIRSubgoal],
) -> List[Dict[str, Any]]:
    """Project subgoals to deterministic, path- and validation-bounded TODO seeds."""

    return [
        item.to_codex_todo_projection()
        for item in sorted(subgoals, key=lambda value: (value.parent_obligation_id, value.ordinal))
    ]


# Descriptive compatibility aliases for downstream callers.
decompose_failed_hammer_goals = decompose_failed_hammer_obligations
decompose_failed_legal_ir_obligations = decompose_failed_hammer_obligations
decompose_legal_ir_hammer_failures = decompose_failed_hammer_obligations


def _obligation_mapping(value: LegalIRProofObligation | Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(value, LegalIRProofObligation):
        value = value.to_dict()
    elif hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        return {
            "obligation_id": "",
            "statement": "",
            "kind": "",
            "legal_ir_view": "",
            "logic_family": "",
            "premise_hints": (),
            "metadata": {},
        }
    return {
        "obligation_id": str(value.get("obligation_id") or "").strip(),
        "statement": str(value.get("statement") or "").strip(),
        "kind": str(value.get("kind") or value.get("obligation_kind") or "").strip(),
        "legal_ir_view": str(
            value.get("legal_ir_view") or value.get("target_component") or ""
        ).strip(),
        "logic_family": str(value.get("logic_family") or value.get("family") or "modal").strip(),
        "premise_hints": _unique_strings(value.get("premise_hints") or ()),
        "metadata": dict(value.get("metadata") or {})
        if isinstance(value.get("metadata"), Mapping)
        else {},
    }


def _failure_items(value: Any) -> List[Mapping[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            value = value.to_dict()
        except (TypeError, ValueError):
            return []
    if isinstance(value, Mapping):
        nested: List[Mapping[str, Any]] = []
        for key in (
            "artifacts",
            "failures",
            "hammer_guidance_artifacts",
            "items",
            "verified_guidance",
        ):
            if key in value:
                nested.extend(_failure_items(value.get(key)))
        return nested or [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items: List[Mapping[str, Any]] = []
        for item in value:
            items.extend(_failure_items(item))
        return items
    return []


def _failed_hammer_items_by_obligation(value: Any) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in _failure_items(value):
        if not _is_failure(item):
            continue
        ids = _unique_strings(
            item.get("proof_obligation_ids")
            or item.get("proof_obligation_id")
            or item.get("obligation_id")
            or item.get("goal_name")
            or ()
        )
        for obligation_id in ids:
            # Stable selection makes results independent of report input order.
            normalized = _json_ready_mapping(item)
            previous = result.get(obligation_id)
            if previous is None or _stable_json(normalized) < _stable_json(previous):
                result[obligation_id] = normalized
    return result


def _is_failure(item: Mapping[str, Any]) -> bool:
    if item.get("trusted") is True:
        return False
    if item.get("proved") is True and not item.get("failure_reason") and not item.get(
        "rejection_reasons"
    ):
        reconstruction = str(item.get("reconstruction_status") or "").strip().lower()
        return reconstruction in {
            "failed",
            "invalid",
            "native_reconstruction_not_verified",
            "reconstruction_failed",
            "rejected",
            "unverified",
        }
    status = str(item.get("status") or "").strip().lower()
    return status not in {"accepted", "proved", "success", "trusted"}


def _failure_mode(item: Mapping[str, Any]) -> str:
    rejection_reasons = _unique_strings(item.get("rejection_reasons") or ())
    raw = (
        item.get("failure_reason")
        or next(iter(rejection_reasons), "")
        or item.get("reconstruction_status")
        or item.get("status")
        or "hammer_unproved"
    )
    value = re.sub(r"[^a-z0-9_.:-]+", "_", str(raw).strip().lower()).strip("_")
    aliases = {
        "failed": "hammer_proof_failed",
        "timeout": "timed_out",
        "unproved": "hammer_unproved",
    }
    return aliases.get(value, value) or "hammer_unproved"


def _decomposition_family(obligation: Mapping[str, Any]) -> str:
    kind = str(obligation.get("kind") or "").lower()
    view = str(obligation.get("legal_ir_view") or "").lower()
    family = str(obligation.get("logic_family") or "").lower()
    statement = str(obligation.get("statement") or "").lower()
    combined = " ".join((kind, view, family, statement))
    # A decompiler obligation remains a decompiler decomposition even when its
    # specific preservation concern is an exception or deadline.
    if "decompil" in view or "decompil" in kind:
        return "decompiler"
    if "cec" in view or re.search(r"(?:^|[_\s])cec(?:[_\s]|$)", combined):
        return "cec"
    if "knowledge_graph" in combined or "neo4j" in combined or "kg_edge" in combined:
        return "knowledge_graph"
    if "temporal" in combined or "tdfol" in combined or "deadline" in combined:
        return "temporal"
    if "exception" in combined or "defeasib" in combined:
        return "exception"
    return "generic"


def _templates_for_obligation(
    obligation: Mapping[str, Any],
) -> Sequence[tuple[str, str, Sequence[str]]]:
    return _SUBGOAL_TEMPLATES[_decomposition_family(obligation)]


def _contract_for_obligation(obligation: Mapping[str, Any]) -> LegalIRViewContract:
    metadata = obligation.get("metadata")
    contract_id = str(metadata.get("contract_id") or "") if isinstance(metadata, Mapping) else ""
    candidates = (
        contract_id,
        str(obligation.get("legal_ir_view") or ""),
        str(metadata.get("target_component") or "") if isinstance(metadata, Mapping) else "",
        "modal.frame_logic",
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return legal_ir_view_contract(candidate)
        except (KeyError, ValueError):
            continue
    # The canonical registry always contains the frame-logic contract.
    return legal_ir_view_contract("modal.frame_logic")


def _one_validation_command(contract: LegalIRViewContract) -> str:
    projection = contract.codex_todo_projection()
    commands = _unique_strings(projection.get("validation_commands") or ())
    return commands[0] if commands else DEFAULT_SUBGOAL_VALIDATION_COMMAND


def _allowed_paths(contract: LegalIRViewContract) -> tuple[str, ...]:
    projection = contract.codex_todo_projection()
    return tuple(_unique_strings(projection.get("allowed_paths") or ()))


def _unique_strings(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        values = (value,)
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _stable_json(value: Any) -> str:
    return json.dumps(
        value, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _json_ready_mapping(value: Mapping[str, Any]) -> Dict[str, Any]:
    return json.loads(_stable_json(dict(value)))


__all__ = [
    "DEFAULT_MAX_SUBGOALS_PER_OBLIGATION",
    "DEFAULT_SUBGOAL_VALIDATION_COMMAND",
    "HARD_MAX_SUBGOALS_PER_OBLIGATION",
    "LEGAL_IR_SUBGOAL_DECOMPOSITION_SCHEMA_VERSION",
    "LEGAL_IR_SUBGOAL_SCHEMA_VERSION",
    "LegalIRSubgoal",
    "LegalIRSubgoalDecomposer",
    "LegalIRSubgoalDecomposition",
    "LegalIRSubgoalDecompositionConfig",
    "build_legal_ir_subgoal_decomposition",
    "decompose_failed_hammer_goals",
    "decompose_failed_hammer_obligations",
    "decompose_failed_legal_ir_obligations",
    "decompose_legal_ir_hammer_failures",
    "project_legal_ir_subgoals_to_codex_todos",
]
