"""Deterministic repair records for verified Legal IR gaps.

These records are compiler/decompiler guidance, not generated proof text.  They
summarize typed semantics that can be projected into Codex TODOs or hammer
obligations without rewarding source-span copying.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence


LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION = "legal-ir-verified-gap-repair-v1"
LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION = "legal-ir-clustered-gap-repair-v1"

_HAMMER_FAILURE_CLUSTER_SCHEMA_VERSION = "legal-ir-hammer-failure-cluster-v1"
_HAMMER_FAILURE_CLUSTER_DEDUPE_FIELDS = (
    "contract_id",
    "obligation_family",
    "target_view",
    "failure_reason",
    "allowed_paths",
)
_CLUSTER_CONTAINER_KEYS = (
    "clusters",
    "clustered_gaps",
    "failure_clusters",
    "todos",
    "tasks",
    "items",
)
_FORBIDDEN_SOURCE_KEYS = frozenset(
    {
        "copied_text",
        "draft_text",
        "full_text",
        "normalized_text",
        "raw_source",
        "source_span",
        "source_text",
        "text",
    }
)


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
    clustered_gaps: Any = None,
) -> List[LegalIRVerifiedGapRepair]:
    """Return deterministic compiler/decompiler repair records for verified gaps.

    ``clustered_gaps`` is an additive compatibility hook for recurrence-qualified
    task-029 output.  Existing callers that provide only individual hammer
    guidance retain the v1 behavior and record schema.
    """

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

    if clustered_gaps is not None:
        repairs.extend(
            generate_clustered_verified_legal_ir_gap_repairs(
                clustered_gaps,
                sample_or_document=sample_or_document,
            )
        )

    return _dedupe_repairs(repairs)


def generate_clustered_verified_legal_ir_gap_repairs(
    clusters_or_sample: Any = None,
    *,
    clustered_gaps: Any = None,
    sample_or_document: Any = None,
) -> List[LegalIRVerifiedGapRepair]:
    """Compile recurrence-qualified task-029 clusters into repair records.

    The primary calling convention is ``(clusters, sample_or_document=sample)``.
    ``(sample, clustered_gaps=clusters)`` is also accepted so callers can migrate
    from :func:`generate_verified_legal_ir_gap_repairs` without rearranging their
    pipeline.  A cluster may be a ``ModalTodo``, its serialized dictionary, the
    nested metadata dictionary, or an envelope containing a sequence of those.

    Individual hammer failures are intentionally ignored here.  Recurrence and
    replay-impact qualification belongs to the clustering boundary and is
    rechecked before a compiler lane is invoked.
    """

    if clustered_gaps is not None:
        clusters = clustered_gaps
        sample = sample_or_document if sample_or_document is not None else clusters_or_sample
    else:
        clusters = clusters_or_sample
        sample = sample_or_document

    text = _text_for(sample)
    provenance_id = _sample_id_for(sample) if sample is not None else "legal-ir-cluster"
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    repairs: List[LegalIRVerifiedGapRepair] = []

    for cluster in _normalized_qualified_clusters(clusters):
        contract = _cluster_contract(cluster)
        if contract is None:
            continue
        target_component = str(
            getattr(contract, "target_component", "")
            or cluster["target_view"]
        )
        lane = _cluster_repair_lane(contract)
        action = _cluster_action(cluster["obligation_family"], target_component)
        allowed_paths = _cluster_allowed_paths(cluster, contract=contract, lane=lane)
        if not allowed_paths:
            # A clustered task without a bounded, contract-approved path must not
            # become autonomous compiler work.
            continue

        semantics = _compile_cluster_semantics(
            cluster,
            text=text,
            provenance_id=provenance_id,
            source_hash=source_hash,
        )
        identity = {
            field_name: cluster[field_name]
            for field_name in _HAMMER_FAILURE_CLUSTER_DEDUPE_FIELDS
        }
        repair_id = "lir-cluster-repair-" + _stable_hash(identity)[:20]
        validation_commands = _cluster_validation_commands(cluster, lane=lane)
        target_metrics = _unique_strings(
            [
                *cluster.get("target_metrics", []),
                *list(getattr(contract, "metric_families", ()) or ()),
                *_TARGET_METRICS.get(target_component, ()),
            ]
        )
        proof_ids = _unique_strings(cluster.get("proof_obligation_ids", []))
        repairs.append(
            LegalIRVerifiedGapRepair(
                repair_id=repair_id,
                gap_family=str(cluster["obligation_family"]),
                action=action,
                target_component=target_component,
                typed_semantics=semantics,
                allowed_paths=allowed_paths,
                proof_obligation_ids=proof_ids,
                target_metrics=target_metrics,
                validation_commands=validation_commands,
                metadata={
                    "cluster_dedupe_signature": str(cluster["dedupe_signature"]),
                    "cluster_schema_version": _HAMMER_FAILURE_CLUSTER_SCHEMA_VERSION,
                    "contract_id": str(cluster["contract_id"]),
                    "failure_reason": str(cluster["failure_reason"]),
                    "high_impact_replay_failure": bool(
                        cluster.get("high_impact_replay_failure")
                    ),
                    "obligation_family": str(cluster["obligation_family"]),
                    "promotion_rule": (
                        "improve_or_preserve_fixed_canary_per_view_metrics_and_symbolic_validity"
                    ),
                    "qualification_reason": str(cluster["qualification_reason"]),
                    "sample_id": provenance_id,
                    "source_text_sha256": source_hash,
                    "support_count": int(cluster["support_count"]),
                    "target_view": str(cluster["target_view"]),
                },
                schema_version=LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION,
            )
        )

    repairs.sort(
        key=lambda repair: (
            str(repair.metadata.get("contract_id") or ""),
            repair.gap_family,
            str(repair.metadata.get("target_view") or ""),
            str(repair.metadata.get("failure_reason") or ""),
            tuple(repair.allowed_paths),
            repair.repair_id,
        )
    )
    return _dedupe_repairs(repairs)


def generate_clustered_legal_ir_compiler_repairs(
    clusters_or_sample: Any = None,
    *,
    clustered_gaps: Any = None,
    sample_or_document: Any = None,
) -> List[LegalIRVerifiedGapRepair]:
    """Compatibility alias for clustered verified compiler repairs."""

    return generate_clustered_verified_legal_ir_gap_repairs(
        clusters_or_sample,
        clustered_gaps=clustered_gaps,
        sample_or_document=sample_or_document,
    )


def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            converted = value.to_dict()
        except (TypeError, ValueError):
            return {}
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _cluster_candidates(value: Any) -> List[Dict[str, Any]]:
    mapping = _as_mapping(value)
    if mapping:
        metadata = _as_mapping(mapping.get("metadata"))
        merged = {**mapping, **metadata} if metadata else mapping
        if _looks_like_failure_cluster(merged):
            return [merged]
        nested: List[Dict[str, Any]] = []
        for key in _CLUSTER_CONTAINER_KEYS:
            if key in mapping:
                nested.extend(_cluster_candidates(mapping.get(key)))
        return nested
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        candidates: List[Dict[str, Any]] = []
        for item in value:
            candidates.extend(_cluster_candidates(item))
        return candidates
    return []


def _looks_like_failure_cluster(value: Mapping[str, Any]) -> bool:
    schema = str(value.get("cluster_schema_version") or value.get("schema_version") or "")
    source = str(value.get("source") or "")
    return bool(
        schema == _HAMMER_FAILURE_CLUSTER_SCHEMA_VERSION
        or source == "hammer_failure_projection_v1"
        or (
            isinstance(value.get("cluster_key"), Mapping)
            and value.get("dedupe_signature")
            and (
                value.get("qualification_reason")
                or value.get("recurring_verified_failure")
                or value.get("high_impact_replay_failure")
            )
        )
    )


def _normalized_qualified_clusters(value: Any) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for candidate in _cluster_candidates(value):
        cluster = _normalize_cluster(candidate)
        if cluster is None:
            continue
        signature = str(cluster["dedupe_signature"])
        existing = grouped.get(signature)
        if existing is None:
            grouped[signature] = cluster
            continue
        existing["proof_obligation_ids"] = sorted(
            _unique_strings(
                [
                    *existing.get("proof_obligation_ids", []),
                    *cluster.get("proof_obligation_ids", []),
                ]
            )
        )
        existing["target_metrics"] = sorted(
            _unique_strings(
                [*existing.get("target_metrics", []), *cluster.get("target_metrics", [])]
            )
        )
        existing["validation_commands"] = sorted(
            _unique_strings(
                [
                    *existing.get("validation_commands", []),
                    *cluster.get("validation_commands", []),
                ]
            )
        )
        existing["available_backends"] = sorted(
            _unique_strings(
                [
                    *existing.get("available_backends", []),
                    *cluster.get("available_backends", []),
                ]
            )
        )
        existing["support_count"] = max(
            int(existing.get("support_count") or 0),
            int(cluster.get("support_count") or 0),
        )
        existing["high_impact_replay_failure"] = bool(
            existing.get("high_impact_replay_failure")
            or cluster.get("high_impact_replay_failure")
        )
        existing["qualification_reason"] = sorted(
            _unique_strings(
                [
                    existing.get("qualification_reason"),
                    cluster.get("qualification_reason"),
                ]
            )
        )[0]
    normalized = list(grouped.values())
    normalized.sort(
        key=lambda item: (
            item["contract_id"],
            item["obligation_family"],
            item["target_view"],
            item["failure_reason"],
            tuple(item["allowed_paths"]),
            item["dedupe_signature"],
        )
    )
    return normalized


def _normalize_cluster(value: Mapping[str, Any]) -> Dict[str, Any] | None:
    cluster_key = _as_mapping(value.get("cluster_key") or value.get("dedupe_key_values"))

    def field(name: str, default: Any = "") -> Any:
        explicit = value.get(name)
        keyed = cluster_key.get(name)
        if explicit not in (None, "") and keyed not in (None, ""):
            explicit_normalized = (
                _safe_paths(explicit) if name == "allowed_paths" else str(explicit).strip()
            )
            keyed_normalized = (
                _safe_paths(keyed) if name == "allowed_paths" else str(keyed).strip()
            )
            if explicit_normalized != keyed_normalized:
                return None
        return explicit if explicit not in (None, "") else keyed if keyed not in (None, "") else default

    contract_id = field("contract_id")
    obligation_family = field("obligation_family")
    target_view = field("target_view")
    failure_reason = field("failure_reason")
    allowed_paths = field("allowed_paths", [])
    if None in (contract_id, obligation_family, target_view, failure_reason, allowed_paths):
        return None

    contract_id = str(contract_id).strip()
    obligation_family = _atom(obligation_family, fallback="")
    target_view = str(target_view).strip()
    failure_reason = _atom(failure_reason, fallback="")
    allowed_paths = _safe_paths(allowed_paths)
    if not all((contract_id, obligation_family, target_view, failure_reason, allowed_paths)):
        return None
    if failure_reason == "backend_unavailable":
        return None

    support_count = _safe_positive_int(value.get("support_count"))
    recurrence_threshold = max(2, _safe_positive_int(value.get("recurrence_threshold")) or 2)
    recurring = _truthy(value.get("recurring_verified_failure")) or support_count >= recurrence_threshold
    high_impact = _truthy(value.get("high_impact_replay_failure"))
    qualification_reason = str(value.get("qualification_reason") or "").strip()
    qualified = recurring or high_impact
    if not qualified:
        return None
    if support_count <= 0:
        support_count = 1 if high_impact else recurrence_threshold

    canonical_key = {
        "allowed_paths": allowed_paths,
        "contract_id": contract_id,
        "failure_reason": failure_reason,
        "obligation_family": obligation_family,
        "target_view": target_view,
    }
    computed_signature = "hammer-failure:" + _stable_hash(canonical_key)[:20]
    supplied_signature = str(value.get("dedupe_signature") or "").strip()
    # Task-029 signatures use the same canonical key.  Do not trust arbitrary
    # caller-provided identities, but accept older envelopes with no signature.
    if supplied_signature and supplied_signature != computed_signature:
        return None

    return {
        **canonical_key,
        "dedupe_signature": computed_signature,
        "high_impact_replay_failure": high_impact,
        "proof_obligation_ids": _unique_strings(value.get("proof_obligation_ids") or []),
        "qualification_reason": qualification_reason
        or ("high_impact_replay_failure" if high_impact and not recurring else "recurring_verified_failure"),
        "support_count": support_count,
        "target_metrics": _unique_strings(value.get("target_metrics") or []),
        "validation_commands": _unique_strings(value.get("validation_commands") or []),
        "available_backends": _cluster_available_backends(value),
    }


def _cluster_contract(cluster: Mapping[str, Any]) -> Any:
    try:
        from .legal_ir_view_contracts import legal_ir_view_contract

        resolved: List[Any] = []
        for candidate in (cluster.get("contract_id"), cluster.get("target_view")):
            try:
                resolved.append(legal_ir_view_contract(str(candidate)))
            except (KeyError, TypeError, ValueError):
                return None
        if resolved and all(item.contract_id == resolved[0].contract_id for item in resolved):
            return resolved[0]
    except ImportError:
        pass
    return None


def _cluster_repair_lane(contract: Any) -> Any:
    lanes = tuple(getattr(contract, "repair_lanes", ()) or ())
    return lanes[0] if lanes else None


def _cluster_allowed_paths(
    cluster: Mapping[str, Any], *, contract: Any, lane: Any
) -> List[str]:
    explicit = _safe_paths(cluster.get("allowed_paths"))
    contract_paths = _safe_paths(getattr(lane, "allowed_paths", ()) or ())
    if not contract_paths and contract is not None:
        contract_paths = _safe_paths(
            contract.codex_todo_projection().get("allowed_paths", [])
        )
    if contract_paths:
        approved = set(contract_paths)
        return [path for path in explicit if path in approved][:8]
    return explicit[:8]


def _cluster_validation_commands(cluster: Mapping[str, Any], *, lane: Any) -> List[str]:
    commands = _unique_strings(
        [
            *cluster.get("validation_commands", []),
            *list(getattr(lane, "validation_commands", ()) or ()),
            (
                "python -m pytest -q "
                "tests/unit/logic/integration/test_clustered_legal_ir_compiler_repairs.py "
                "tests/unit/logic/integration/test_legal_ir_verified_gap_repairs.py"
            ),
        ]
    )
    return [command for command in commands if "pytest" in command][:8]


def _cluster_action(obligation_family: str, target_component: str) -> str:
    family = _atom(obligation_family, fallback="")
    if "exception" in family:
        return "repair_exception_scope_precedence"
    if "prohibition" in family or "polarity" in family:
        return "repair_deontic_prohibition_polarity"
    if "temporal" in family or "deadline" in family or "anchor" in family:
        return "repair_temporal_deadline_scope"
    if "frame" in family and "role" in family:
        return "repair_frame_role_bindings"
    if "knowledge_graph" in family or "endpoint" in family:
        return "repair_kg_actor_action_object_remedy_edges"
    if "cec" in family or "lifecycle" in family:
        return "repair_cec_lifecycle_event_projection"
    if "prover" in family or "route" in family:
        return "repair_external_prover_router"
    return {
        "modal.frame_logic": "repair_flogic_ontology_constraints",
        "deontic.ir": "repair_deontic_bridge_quality_gate",
        "TDFOL.prover": "repair_tdfol_bridge_parse",
        "CEC.native": "repair_cec_dcec_bridge",
        "knowledge_graphs.neo4j_compat": "repair_multiview_legal_ir_graph_projection",
        "external_provers.router": "repair_external_prover_router",
    }.get(target_component, "repair_legal_ir_contract")


def _compile_cluster_semantics(
    cluster: Mapping[str, Any],
    *,
    text: str,
    provenance_id: str,
    source_hash: str,
) -> Dict[str, Any]:
    family = _atom(cluster.get("obligation_family"), fallback="")
    view = str(cluster.get("target_view") or "").lower()
    common = {
        "contract_id": str(cluster.get("contract_id") or ""),
        "failure_reason": str(cluster.get("failure_reason") or ""),
        "obligation_family": family,
        "provenance_id": provenance_id,
        "source_copy_policy": "hash_only",
        "source_text_sha256": source_hash,
    }

    if "exception" in family:
        result = _call_text_lane(
            "ipfs_datasets_py.logic.modal", "compile_exception_precedence", text, provenance_id
        )
        fallback = {
            "exception_scope": "defeasible_override",
            "precedence": "exception_over_general_rule",
        }
    elif "prohibition" in family or "polarity" in family or (
        "deontic" in view and "required_fields" not in family
    ):
        result = _call_text_lane(
            "ipfs_datasets_py.logic.deontic", "compile_prohibition_polarity", text, provenance_id
        )
        fallback = {"deontic_operator": "F", "norm_type": "prohibition", "polarity": "negative"}
    elif "temporal" in family or "deadline" in family or "anchor" in family or "tdfol" in view:
        result = _call_text_lane(
            "ipfs_datasets_py.logic.TDFOL", "compile_temporal_deadline", text, provenance_id
        )
        fallback = {"event_relation": "deadline_or_ordering", "temporal_logic": "TDFOL", "time_anchor": "typed_event_anchor"}
    elif "frame" in family and "role" in family:
        result = _call_text_lane(
            "ipfs_datasets_py.logic.modal", "compile_frame_role_bindings", text, provenance_id
        )
        fallback = {"role_bindings": ["agent", "action", "object", "recipient", "remedy"]}
    elif "knowledge_graph" in family or "endpoint" in family or "knowledge_graph" in view or "neo4j" in view:
        result = _call_text_lane(
            "ipfs_datasets_py.logic.knowledge_graphs", "compile_legal_role_graph", text, provenance_id
        )
        fallback = {"edge_types": ["HAS_ACTOR", "HAS_ACTION", "HAS_OBJECT", "HAS_REMEDY"], "directed": True}
    elif "cec" in family or "lifecycle" in family or "cec" in view:
        result = _call_text_lane(
            "ipfs_datasets_py.logic.CEC.native", "compile_lifecycle_events", text, provenance_id
        )
        fallback = {"event_calculus": "CEC", "transition_operators": ["Happens", "Initiates", "Terminates"]}
    elif "prover" in family or "route" in family or "external" in view:
        result = _call_route_lane(cluster, provenance_id=provenance_id)
        fallback = {"route_policy": "deterministic_capability_order", "timeout_policy": "bounded_per_backend"}
    else:
        result = {}
        fallback = {"preservation": "canonical_contract_required_fields_and_semantics"}

    return dict(sorted(_source_free({**common, **fallback, **result}).items()))


def _call_text_lane(module_name: str, function_name: str, text: str, provenance_id: str) -> Dict[str, Any]:
    try:
        function = getattr(importlib.import_module(module_name), function_name)
        value = function(text, provenance_id=provenance_id)
    except (ImportError, AttributeError):
        return {}
    mapping = _as_mapping(value)
    return mapping if mapping else {}


def _call_route_lane(cluster: Mapping[str, Any], *, provenance_id: str) -> Dict[str, Any]:
    try:
        function = getattr(
            importlib.import_module("ipfs_datasets_py.logic.external_provers"),
            "select_deterministic_prover_route",
        )
        value = function(
            formula_family=_formula_family_for_cluster(cluster),
            available_backends=cluster.get("available_backends") or None,
            obligation_id=_first_string(cluster.get("proof_obligation_ids")),
            input_formula_id=provenance_id,
            provenance_id=provenance_id,
            require_reconstruction=True,
        )
    except (ImportError, AttributeError):
        return {}
    mapping = _as_mapping(value)
    if mapping:
        return mapping
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return {"backend_route": _unique_strings(value)}
    return {}


def _formula_family_for_cluster(cluster: Mapping[str, Any]) -> str:
    text = " ".join(
        str(cluster.get(key) or "").lower()
        for key in ("obligation_family", "target_view", "failure_reason")
    )
    if "temporal" in text or "tdfol" in text:
        return "temporal"
    if "deontic" in text or "prohibition" in text or "exception" in text:
        return "deontic"
    return "first_order"


def _cluster_available_backends(value: Mapping[str, Any]) -> List[str]:
    explicit = _unique_strings(value.get("available_backends") or [])
    if explicit:
        return explicit
    statuses = value.get("backend_statuses")
    if isinstance(statuses, Mapping):
        return sorted(
            str(name)
            for name, status in statuses.items()
            if str(status).lower() not in {"unavailable", "disabled"}
        )
    return []


def _source_free(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _source_free(item)
            for key, item in value.items()
            if str(key).lower() not in _FORBIDDEN_SOURCE_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_source_free(item) for item in value]
    return value


def _safe_paths(values: Any) -> List[str]:
    safe: List[str] = []
    for raw in _unique_strings(values):
        path = raw.replace("\\", "/").strip().rstrip("/")
        parts = [part for part in path.split("/") if part]
        if (
            not path
            or path.startswith("/")
            or any(part in {".", ".."} for part in parts)
            or not path.startswith(("ipfs_datasets_py/", "tests/"))
        ):
            continue
        safe.append(path)
    return sorted(dict.fromkeys(safe))[:8]


def _unique_strings(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray, str)):
        raw_values = values
    else:
        raw_values = [values]
    return list(dict.fromkeys(str(value).strip() for value in raw_values if str(value).strip()))


def _atom(value: Any, *, fallback: str = "unknown") -> str:
    normalized = re.sub(r"[^a-z0-9_.:-]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or fallback


def _safe_positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "verified"}


def _first_string(values: Any) -> str:
    items = _unique_strings(values)
    return items[0] if items else ""


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
    "LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION",
    "LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION",
    "LegalIRVerifiedGapRepair",
    "generate_clustered_legal_ir_compiler_repairs",
    "generate_clustered_verified_legal_ir_gap_repairs",
    "generate_verified_legal_ir_gap_repairs",
]
