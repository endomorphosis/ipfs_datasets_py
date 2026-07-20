"""Deterministic repair records for verified Legal IR gaps.

These records are compiler/decompiler guidance, not generated proof text.  They
summarize typed semantics that can be projected into Codex TODOs or hammer
obligations without rewarding source-span copying.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence


LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION = "legal-ir-verified-gap-repair-v1"


_TARGET_ALLOWED_PATHS: Mapping[str, Sequence[str]] = {
    "CEC.native": (
        "ipfs_datasets_py/logic/bridge/cec_dcec.py",
        "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
        "ipfs_datasets_py/logic/CEC/native/temporal.py",
    ),
    "TDFOL.prover": (
        "ipfs_datasets_py/logic/bridge/fol_tdfol.py",
        "ipfs_datasets_py/logic/TDFOL/tdfol_converter.py",
        "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
        "ipfs_datasets_py/logic/TDFOL/tdfol_prover.py",
    ),
    "deontic.ir": (
        "ipfs_datasets_py/logic/bridge/deontic_norms.py",
        "ipfs_datasets_py/logic/deontic/converter.py",
        "ipfs_datasets_py/logic/deontic/ir.py",
        "ipfs_datasets_py/logic/deontic/prover_syntax.py",
    ),
    "external_provers.router": (
        "ipfs_datasets_py/logic/bridge/external_prover_router.py",
        "ipfs_datasets_py/logic/external_provers/prover_router.py",
        "ipfs_datasets_py/logic/external_provers/lazy_installer.py",
    ),
    "knowledge_graphs.neo4j_compat": (
        "ipfs_datasets_py/logic/modal/kg_bridge.py",
        "ipfs_datasets_py/knowledge_graphs/neo4j_compat/legal_ir_projection.py",
    ),
    "modal.frame_logic": (
        "ipfs_datasets_py/logic/bridge/modal_frame_logic.py",
        "ipfs_datasets_py/logic/modal/compiler.py",
        "ipfs_datasets_py/logic/modal/kg_bridge.py",
    ),
}

_TARGET_METRICS: Mapping[str, Sequence[str]] = {
    "CEC.native": ("cec_dcec_validation_failure_ratio", "hammer_proof_success_rate"),
    "TDFOL.prover": ("tdfol_parse_failure_ratio", "hammer_proof_success_rate"),
    "deontic.ir": ("deontic_decoder_slot_loss", "symbolic_validity_penalty"),
    "external_provers.router": (
        "legal_ir_multiview_proof_failure_ratio",
        "hammer_proof_success_rate",
    ),
    "knowledge_graphs.neo4j_compat": (
        "legal_ir_multiview_graph_failure_penalty",
        "symbolic_validity_penalty",
    ),
    "modal.frame_logic": ("flogic_similarity_loss", "symbolic_validity_penalty"),
}

_EXCEPTION_RE = re.compile(
    r"\b(except\s+as\s+provided|unless|subject\s+to|notwithstanding)\b",
    re.IGNORECASE,
)
_PROHIBITION_RE = re.compile(
    r"\b(shall\s+not|must\s+not|may\s+not|prohibited\s+from|forbidden)\b",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    r"\b("
    r"within\s+\d+\s+(?:day|days|month|months|year|years)|"
    r"not\s+later\s+than|no\s+later\s+than|"
    r"before|after|until|expires?|effective\s+(?:on|date)"
    r")\b",
    re.IGNORECASE,
)
_REMEDY_RE = re.compile(
    r"\b(penalty|civil\s+action|remedy|damages|sanction|fine|injunction)\b",
    re.IGNORECASE,
)
_LIFECYCLE_RE = re.compile(
    r"\b(file|issue|grant|deny|revoke|terminate|expire|appeal|review|enforce)\b",
    re.IGNORECASE,
)
_ACTOR_ACTION_RE = re.compile(
    r"\b(?P<actor>[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?|agency|person|secretary|court|officer|applicant|recipient)\s+"
    r"(?P<modal>shall|must|may|is\s+authorized\s+to|is\s+required\s+to|shall\s+not|must\s+not|may\s+not)\s+"
    r"(?P<action>[a-z][a-z_ -]+?)(?:\.|,|;|\b(?:if|unless|except|within|before|after|and|or)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LegalIRVerifiedGapRepair:
    """One deterministic repair target derived from verified Legal IR gaps."""

    repair_id: str
    gap_family: str
    action: str
    target_component: str
    typed_semantics: Dict[str, Any]
    allowed_paths: List[str] = field(default_factory=list)
    proof_obligation_ids: List[str] = field(default_factory=list)
    target_metrics: List[str] = field(default_factory=list)
    validation_commands: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "allowed_paths": list(self.allowed_paths),
            "gap_family": self.gap_family,
            "metadata": dict(sorted(self.metadata.items())),
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "repair_id": self.repair_id,
            "schema_version": self.schema_version,
            "target_component": self.target_component,
            "target_metrics": list(self.target_metrics),
            "typed_semantics": dict(sorted(self.typed_semantics.items())),
            "validation_commands": list(self.validation_commands),
        }


def generate_verified_legal_ir_gap_repairs(
    sample_or_document: Any,
    *,
    hammer_guidance: Any = None,
) -> List[LegalIRVerifiedGapRepair]:
    """Return deterministic compiler/decompiler repair records for verified gaps."""

    text = _text_for(sample_or_document)
    sample_id = _sample_id_for(sample_or_document)
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    guidance_items = _hammer_guidance_items(hammer_guidance)
    guidance_by_view = _guidance_by_view(guidance_items)
    repairs: List[LegalIRVerifiedGapRepair] = []

    def add(
        *,
        gap_family: str,
        action: str,
        target_component: str,
        typed_semantics: Mapping[str, Any],
        proof_obligation_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "action": action,
            "gap_family": gap_family,
            "proof_obligation_ids": list(proof_obligation_ids),
            "sample_id": sample_id,
            "target_component": target_component,
            "typed_semantics": dict(typed_semantics),
        }
        repair_id = "lir-gap-repair-" + _stable_hash(payload)[:20]
        repairs.append(
            LegalIRVerifiedGapRepair(
                repair_id=repair_id,
                gap_family=gap_family,
                action=action,
                target_component=target_component,
                typed_semantics=dict(typed_semantics),
                allowed_paths=list(_TARGET_ALLOWED_PATHS.get(target_component, ())),
                proof_obligation_ids=list(dict.fromkeys(proof_obligation_ids)),
                target_metrics=list(_TARGET_METRICS.get(target_component, ())),
                validation_commands=[
                    (
                        "python -m pytest -q "
                        "tests/unit/logic/integration/test_legal_ir_verified_gap_repairs.py"
                    )
                ],
                metadata={
                    "sample_id": sample_id,
                    "source_text_sha256": source_hash,
                    **dict(metadata or {}),
                },
            )
        )

    if _EXCEPTION_RE.search(text):
        add(
            gap_family="exception_scope_precedence",
            action="repair_exception_scope_precedence",
            target_component="modal.frame_logic",
            typed_semantics={
                "exception_scope": "defeasible_override",
                "precedence": "exception_over_general_rule",
                "source_copy_policy": "hash_only",
            },
            proof_obligation_ids=_proof_ids_for(guidance_by_view, "modal.frame_logic"),
        )

    if _PROHIBITION_RE.search(text):
        add(
            gap_family="prohibition_guidance",
            action="repair_deontic_prohibition_polarity",
            target_component="deontic.ir",
            typed_semantics={
                "deontic_operator": "F",
                "norm_type": "prohibition",
                "polarity": "negative",
                "source_copy_policy": "hash_only",
            },
            proof_obligation_ids=_proof_ids_for(guidance_by_view, "deontic.ir"),
        )

    if _DEADLINE_RE.search(text):
        add(
            gap_family="temporal_deadline",
            action="repair_temporal_deadline_scope",
            target_component="TDFOL.prover",
            typed_semantics={
                "event_relation": "deadline_or_ordering",
                "temporal_logic": "TDFOL",
                "time_anchor": "source_cue",
                "source_copy_policy": "hash_only",
            },
            proof_obligation_ids=_proof_ids_for(guidance_by_view, "TDFOL.prover"),
        )

    role_record = _actor_action_object_record(text)
    if role_record:
        if _REMEDY_RE.search(text):
            role_record["remedy_present"] = True
        add(
            gap_family="knowledge_graph_role_edges",
            action="repair_kg_actor_action_object_remedy_edges",
            target_component="knowledge_graphs.neo4j_compat",
            typed_semantics={
                "edge_types": ["actor", "action", "object", "remedy"],
                **role_record,
                "source_copy_policy": "hash_only",
            },
            proof_obligation_ids=_proof_ids_for(
                guidance_by_view,
                "knowledge_graphs.neo4j_compat",
            ),
        )

    lifecycle_events = _unique_lower(match.group(1) for match in _LIFECYCLE_RE.finditer(text))
    if lifecycle_events:
        add(
            gap_family="cec_lifecycle_events",
            action="repair_cec_lifecycle_event_projection",
            target_component="CEC.native",
            typed_semantics={
                "event_calculus": "CEC",
                "lifecycle_events": lifecycle_events,
                "source_copy_policy": "hash_only",
            },
            proof_obligation_ids=_proof_ids_for(guidance_by_view, "CEC.native"),
        )

    external_ids = _proof_ids_for(guidance_by_view, "external_provers.router")
    external_failures = [
        item
        for item in guidance_items
        if "proof" in str(item.get("failure_reason") or "").lower()
        or "prover" in str(item.get("legal_ir_view") or "").lower()
    ]
    if external_ids or external_failures:
        add(
            gap_family="external_prover_routing",
            action="repair_external_prover_router",
            target_component="external_provers.router",
            typed_semantics={
                "fallback_backends": ["z3", "cvc5", "vampire", "eprover"],
                "route": "hammer_backend_parallel_search",
                "timeout_policy": "bounded_per_backend",
                "source_copy_policy": "hash_only",
            },
            proof_obligation_ids=external_ids
            or _proof_ids_from_items(external_failures),
        )

    return _dedupe_repairs(repairs)


def _text_for(value: Any) -> str:
    return str(
        _get(value, "text")
        or _get(value, "normalized_text")
        or _get(_get(value, "modal_ir"), "normalized_text")
        or ""
    )


def _sample_id_for(value: Any) -> str:
    return str(
        _get(value, "sample_id")
        or _get(value, "document_id")
        or _get(_get(value, "modal_ir"), "document_id")
        or "legal-ir-sample"
    )


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, ensure_ascii=True, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _unique_lower(values: Sequence[Any]) -> List[str]:
    return list(
        dict.fromkeys(str(value).strip().lower() for value in values if str(value).strip())
    )


def _actor_action_object_record(text: str) -> Dict[str, Any]:
    match = _ACTOR_ACTION_RE.search(text)
    if not match:
        return {}
    action = re.sub(r"\s+", "_", match.group("action").strip().lower()).strip("_")
    action_tokens = [token for token in action.split("_") if token]
    actor = re.sub(
        r"^(?:the|a|an)\s+",
        "",
        match.group("actor").strip().lower(),
    )
    return {
        "action": "_".join(action_tokens[:4]) or "unknown_action",
        "actor": actor,
        "modal_cue": re.sub(r"\s+", "_", match.group("modal").strip().lower()),
        "object_hint": "_".join(action_tokens[1:5]) if len(action_tokens) > 1 else "",
    }


def _hammer_guidance_items(value: Any) -> List[Mapping[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            value = value.to_dict()
        except (TypeError, ValueError):
            return []
    if isinstance(value, Mapping):
        payload = dict(value)
        nested: List[Mapping[str, Any]] = []
        for key in ("artifacts", "hammer_guidance_artifacts", "verified_guidance", "items"):
            if key in payload:
                nested.extend(_hammer_guidance_items(payload.get(key)))
        if nested:
            return nested
        if str(payload.get("schema_version") or "").startswith("legal-ir-hammer-"):
            return [payload]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        items: List[Mapping[str, Any]] = []
        for item in value:
            items.extend(_hammer_guidance_items(item))
        return items
    return []


def _guidance_by_view(items: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for item in items:
        view = str(
            item.get("legal_ir_view")
            or item.get("target_view")
            or item.get("target_component")
            or ""
        )
        if not view:
            continue
        grouped.setdefault(view, []).append(item)
    return grouped


def _proof_ids_for(
    guidance_by_view: Mapping[str, Sequence[Mapping[str, Any]]],
    view: str,
) -> List[str]:
    return _proof_ids_from_items(guidance_by_view.get(view, ()))


def _proof_ids_from_items(items: Sequence[Mapping[str, Any]]) -> List[str]:
    proof_ids: List[str] = []
    for item in items:
        values = item.get("proof_obligation_ids") or item.get("obligation_id")
        if isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray, str)):
            proof_ids.extend(str(value) for value in values if str(value))
        elif values:
            proof_ids.append(str(values))
    return list(dict.fromkeys(proof_ids))


def _dedupe_repairs(
    repairs: Sequence[LegalIRVerifiedGapRepair],
) -> List[LegalIRVerifiedGapRepair]:
    seen: set[str] = set()
    deduped: List[LegalIRVerifiedGapRepair] = []
    for repair in repairs:
        if repair.repair_id in seen:
            continue
        seen.add(repair.repair_id)
        deduped.append(repair)
    return deduped


__all__ = [
    "LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION",
    "LegalIRVerifiedGapRepair",
    "generate_verified_legal_ir_gap_repairs",
]
