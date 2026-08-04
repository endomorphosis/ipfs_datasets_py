"""Compile Solidity graph candidates into declaration-only Security IR.

This adapter is the CRYPTOIR-G770 entry point that turns source-grounded
GraphRAG candidates into canonical :class:`SecurityIR` declarations.  It:

* cites exact source spans and graph / source / config / partition CIDs;
* converts retrieved premises into ``context_only`` assumptions with
  ``proof_authority=False``;
* keeps corpus quality scores out of safety labels;
* never imports solver results, traces, model scores, or evaluation labels
  into declaration features; and
* abstains on unknown or lossy semantics instead of inventing claims.

A generated declaration is candidate evidence only.  It does not prove a
property, authorize execution, or decide contract safety.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from ..model import (
    Policy,
    PolicyEffect,
    Resource,
    SecurityClaim,
    SecurityExtension,
    SecurityIR,
    SecuritySource,
    ThreatAssumption,
)
from .graph import (
    GraphNodeType,
    SoliditySecurityGraph,
)
from .schemas import GraphNode


SOLIDITY_SECURITY_IR_ADAPTER_VERSION: Final = "solidity-cpt-security-ir-adapter/v1"
SOLIDITY_SECURITY_IR_ADAPTER_PRODUCER: Final = (
    "solidity-cpt-top10-security-ir-adapter"
)
SOLIDITY_CANDIDATE_DOMAIN: Final = "solidity.contract_security"
SOLIDITY_ADAPTER_IDENTITY_DOMAIN: Final = (
    "solidity-cpt-security-ir/adapter-result"
)
SOLIDITY_EXTENSION_VOCABULARY: Final = "solidity-cpt-top10.formalization"
SOLIDITY_EXTENSION_VERSION: Final = "1.0.0"

_RESULT_FEATURE_KEYS: Final = frozenset(
    {
        "counterexample",
        "disproof_vectors",
        "evaluation_label",
        "evaluation_labels",
        "model_score",
        "model_scores",
        "proof_obligations",  # run results, not declaration obligations
        "runtime_trace",
        "runtime_traces",
        "solver_result",
        "solver_results",
        "solver_verdict",
        "trace",
    }
)
_SAFETY_LABEL_KEYS: Final = frozenset(
    {
        "is_safe",
        "is_secure",
        "safety_label",
        "security_label",
        "vulnerability_label",
    }
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SPAN_FIELDS: Final = (
    "start_line",
    "start_column",
    "start_offset",
    "end_line",
    "end_column",
    "end_offset",
)


class SolidityAdapterError(ValueError):
    """Raised when graph candidates cannot be adapted safely."""


class CandidateAuthority(str, Enum):
    """Non-interchangeable authority for adapted Security IR candidates."""

    CANDIDATE = "candidate"
    CONTEXT_ONLY = "context_only"
    OBSERVED_SYNTAX = "observed_syntax"
    ABSTAINED = "abstained"


class AdapterDisposition(str, Enum):
    """Whether adaptation produced a declaration or abstained."""

    DECLARED = "declared"
    ABSTAINED = "abstained"


def _canonical_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:32]}"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SolidityAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise SolidityAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise SolidityAdapterError(f"{name} must not have surrounding whitespace")
    if "\x00" in value:
        raise SolidityAdapterError(f"{name} must not contain NUL")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise SolidityAdapterError(f"{name} is not a stable identifier")
    return normalized


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SolidityAdapterError(f"{name} must be a mapping")
    return value


def _freeze(value: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value or {})
    except ProvenanceValidationError as exc:
        raise SolidityAdapterError(f"{name}: {exc}") from exc


def _contains_forbidden_feature(value: Any, keys: frozenset[str]) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in keys and item not in (False, None, ""):
                return True
            if _contains_forbidden_feature(item, keys):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_forbidden_feature(item, keys) for item in value)
    return False


def _payload_dict(node: GraphNode) -> dict[str, Any]:
    payload = node.payload
    if isinstance(payload, Mapping):
        return thaw_json(payload) if not isinstance(payload, dict) else dict(payload)
    return {}


def _span_from_payload(payload: Mapping[str, Any]) -> dict[str, int] | None:
    raw = payload.get("span")
    if not isinstance(raw, Mapping):
        # Nested unit payload may carry span under unit_kind wrappers.
        nested = payload.get("payload")
        if isinstance(nested, Mapping):
            return _span_from_payload(nested)
        return None
    span: dict[str, int] = {}
    for field_name in _SPAN_FIELDS:
        value = raw.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        span[field_name] = value
    if span["end_offset"] < span["start_offset"]:
        return None
    return span


def _node_name(node: GraphNode, payload: Mapping[str, Any]) -> str:
    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    predicate = payload.get("predicate")
    if isinstance(predicate, str) and predicate.strip():
        return predicate.strip()
    return node.node_type


@dataclass(frozen=True, slots=True)
class RetrievedPremise:
    """A GraphRAG or external premise admitted only as context.

    Presence never establishes truth and never supplies proof authority.
    """

    premise_id: str
    statement: str
    source_refs: tuple[str, ...] = ()
    graph_node_cids: tuple[str, ...] = ()
    source_spans: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: str = "context_only"
    proof_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "premise_id", _identifier(self.premise_id, "premise_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        refs = tuple(
            _text(item, "source_ref") for item in (self.source_refs or ())
        )
        if len(refs) != len(set(refs)):
            raise SolidityAdapterError("source_refs must be unique")
        object.__setattr__(self, "source_refs", refs)
        nodes = tuple(
            _text(item, "graph_node_cid")
            for item in (self.graph_node_cids or ())
        )
        if len(nodes) != len(set(nodes)):
            raise SolidityAdapterError("graph_node_cids must be unique")
        object.__setattr__(self, "graph_node_cids", nodes)
        spans = tuple(
            MappingProxyType(dict(_mapping(item, "source_span")))
            for item in (self.source_spans or ())
        )
        object.__setattr__(self, "source_spans", spans)
        object.__setattr__(self, "metadata", _freeze(self.metadata, "metadata"))
        if self.authority != "context_only":
            raise SolidityAdapterError(
                "retrieved premises must have authority=context_only"
            )
        if self.proof_authority is not False:
            raise SolidityAdapterError(
                "retrieved premises must have proof_authority=False"
            )
        if _contains_forbidden_feature(
            thaw_json(self.metadata), _RESULT_FEATURE_KEYS | _SAFETY_LABEL_KEYS
        ):
            raise SolidityAdapterError(
                "retrieved premise metadata cannot carry result or safety features"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "graph_node_cids": list(self.graph_node_cids),
            "metadata": thaw_json(self.metadata),
            "premise_id": self.premise_id,
            "proof_authority": False,
            "source_refs": list(self.source_refs),
            "source_spans": [dict(item) for item in self.source_spans],
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetrievedPremise":
        value = _mapping(value, "retrieved premise")
        return cls(
            premise_id=value.get("premise_id", ""),
            statement=value.get("statement", ""),
            source_refs=tuple(value.get("source_refs", ())),
            graph_node_cids=tuple(value.get("graph_node_cids", ())),
            source_spans=tuple(value.get("source_spans", ())),
            metadata=value.get("metadata", {}),
            authority=value.get("authority", "context_only"),
            proof_authority=value.get("proof_authority", False),
        )


@dataclass(frozen=True, slots=True)
class AdapterAbstention:
    """Explicit refusal to invent Security IR from lossy or unknown semantics."""

    reason_code: str
    message: str
    node_cids: tuple[str, ...] = ()
    unsupported_frontiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason_code", _identifier(self.reason_code, "reason_code")
        )
        object.__setattr__(self, "message", _text(self.message, "message"))
        object.__setattr__(
            self,
            "node_cids",
            tuple(_text(item, "node_cid") for item in self.node_cids),
        )
        object.__setattr__(
            self,
            "unsupported_frontiers",
            tuple(
                _text(item, "unsupported_frontier")
                for item in self.unsupported_frontiers
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "node_cids": list(self.node_cids),
            "reason_code": self.reason_code,
            "unsupported_frontiers": list(self.unsupported_frontiers),
        }


@dataclass(frozen=True, slots=True)
class SolidityAdapterResult:
    """Declaration-only adaptation result with explicit provenance bindings."""

    disposition: AdapterDisposition
    declaration: SecurityIR | None
    graph_cid: str
    source_cids: tuple[str, ...]
    config_cid: str
    partition_cid: str
    candidate_authority: CandidateAuthority
    semantic_prerequisites: tuple[str, ...]
    unsupported_frontiers: tuple[str, ...]
    source_spans: tuple[Mapping[str, Any], ...]
    retrieved_premises: tuple[RetrievedPremise, ...]
    abstentions: tuple[AdapterAbstention, ...] = ()
    quality_score: float | None = None
    quality_is_safety_label: bool = False
    adapter_version: str = SOLIDITY_SECURITY_IR_ADAPTER_VERSION
    result_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AdapterDisposition):
            try:
                object.__setattr__(
                    self,
                    "disposition",
                    AdapterDisposition(self.disposition),
                )
            except (TypeError, ValueError) as exc:
                raise SolidityAdapterError(
                    f"unsupported disposition: {self.disposition!r}"
                ) from exc
        if not isinstance(self.candidate_authority, CandidateAuthority):
            try:
                object.__setattr__(
                    self,
                    "candidate_authority",
                    CandidateAuthority(self.candidate_authority),
                )
            except (TypeError, ValueError) as exc:
                raise SolidityAdapterError(
                    f"unsupported candidate authority: {self.candidate_authority!r}"
                ) from exc
        object.__setattr__(self, "graph_cid", _text(self.graph_cid, "graph_cid"))
        object.__setattr__(
            self,
            "source_cids",
            tuple(_text(item, "source_cid") for item in self.source_cids),
        )
        object.__setattr__(self, "config_cid", _text(self.config_cid, "config_cid"))
        object.__setattr__(
            self,
            "partition_cid",
            _text(self.partition_cid, "partition_cid", allow_empty=True),
        )
        object.__setattr__(
            self,
            "semantic_prerequisites",
            tuple(
                _text(item, "semantic_prerequisite")
                for item in self.semantic_prerequisites
            ),
        )
        object.__setattr__(
            self,
            "unsupported_frontiers",
            tuple(
                _text(item, "unsupported_frontier")
                for item in self.unsupported_frontiers
            ),
        )
        object.__setattr__(
            self,
            "source_spans",
            tuple(
                MappingProxyType(dict(_mapping(item, "source_span")))
                for item in self.source_spans
            ),
        )
        premises = tuple(
            item
            if isinstance(item, RetrievedPremise)
            else RetrievedPremise.from_dict(_mapping(item, "retrieved premise"))
            for item in self.retrieved_premises
        )
        for premise in premises:
            if premise.authority != "context_only" or premise.proof_authority:
                raise SolidityAdapterError(
                    "retrieved premises must remain context_only without proof authority"
                )
        object.__setattr__(self, "retrieved_premises", premises)
        abstentions = tuple(
            item
            if isinstance(item, AdapterAbstention)
            else AdapterAbstention(
                reason_code=_mapping(item, "abstention").get("reason_code", "unknown"),
                message=_mapping(item, "abstention").get("message", "abstained"),
                node_cids=tuple(
                    _mapping(item, "abstention").get("node_cids", ())
                ),
                unsupported_frontiers=tuple(
                    _mapping(item, "abstention").get(
                        "unsupported_frontiers", ()
                    )
                ),
            )
            for item in self.abstentions
        )
        object.__setattr__(self, "abstentions", abstentions)
        if self.quality_is_safety_label is not False:
            raise SolidityAdapterError(
                "quality must never become a safety label"
            )
        if self.quality_score is not None:
            if (
                isinstance(self.quality_score, bool)
                or not isinstance(self.quality_score, (int, float))
                or not 0.0 <= float(self.quality_score) <= 1.0
            ):
                raise SolidityAdapterError(
                    "quality_score must be in [0, 1] when present"
                )
            object.__setattr__(self, "quality_score", float(self.quality_score))
        if self.disposition is AdapterDisposition.DECLARED:
            if not isinstance(self.declaration, SecurityIR):
                raise SolidityAdapterError(
                    "declared adaptation requires a SecurityIR declaration"
                )
            self.declaration.validate()
            if _contains_forbidden_feature(
                self.declaration.to_dict(), _RESULT_FEATURE_KEYS
            ):
                raise SolidityAdapterError(
                    "declaration features must not include solver or evaluation results"
                )
        elif self.declaration is not None:
            raise SolidityAdapterError(
                "abstained adaptation must not carry a declaration"
            )
        object.__setattr__(
            self,
            "adapter_version",
            _text(self.adapter_version, "adapter_version"),
        )
        if self.adapter_version != SOLIDITY_SECURITY_IR_ADAPTER_VERSION:
            raise SolidityAdapterError("unsupported adapter version")
        computed = self.identity.cid
        if self.result_id and self.result_id != computed:
            raise SolidityAdapterError(
                "result_id does not match rehashed adapter result"
            )
        object.__setattr__(self, "result_id", computed)

    @property
    def identity(self):
        return canonical_identity(
            self.deterministic_dict(),
            domain=SOLIDITY_ADAPTER_IDENTITY_DOMAIN,
            schema_version=self.adapter_version,
        )

    @property
    def cid(self) -> str:
        return self.result_id

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "abstentions": [item.to_dict() for item in self.abstentions],
            "adapter_version": self.adapter_version,
            "candidate_authority": self.candidate_authority.value,
            "config_cid": self.config_cid,
            "declaration": (
                None if self.declaration is None else self.declaration.to_dict()
            ),
            "disposition": self.disposition.value,
            "graph_cid": self.graph_cid,
            "partition_cid": self.partition_cid,
            "quality_is_safety_label": False,
            "quality_score": self.quality_score,
            "retrieved_premises": [
                item.to_dict() for item in self.retrieved_premises
            ],
            "semantic_prerequisites": list(self.semantic_prerequisites),
            "source_cids": list(self.source_cids),
            "source_spans": [dict(item) for item in self.source_spans],
            "unsupported_frontiers": list(self.unsupported_frontiers),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, **self.deterministic_dict()}


class SoliditySecurityIRAdapter:
    """Convert Solidity security graphs into candidate Security IR declarations."""

    version: Final = SOLIDITY_SECURITY_IR_ADAPTER_VERSION
    producer_id: Final = SOLIDITY_SECURITY_IR_ADAPTER_PRODUCER

    def adapt(
        self,
        graph: SoliditySecurityGraph,
        *,
        partition_cid: str = "",
        retrieved_premises: Sequence[RetrievedPremise | Mapping[str, Any]] = (),
        quality_score: float | None = None,
        force_abstain: bool = False,
        abstain_reason: str = "",
    ) -> SolidityAdapterResult:
        """Adapt a graph into a declaration-only Security IR candidate.

        Parameters
        ----------
        graph:
            Provenance-bound Solidity security graph.
        partition_cid:
            Optional partition snapshot CID fencing retrieval/learning use.
        retrieved_premises:
            Optional GraphRAG hits.  Each is stored as a context-only assumption
            with ``proof_authority=False``.
        quality_score:
            Optional corpus quality observation.  Never becomes a safety label.
        force_abstain:
            When true, refuse declaration production (unknown/lossy path).
        abstain_reason:
            Human-readable abstention message when *force_abstain* is set.
        """

        if not isinstance(graph, SoliditySecurityGraph):
            raise SolidityAdapterError(
                "adapt requires a SoliditySecurityGraph instance"
            )
        if quality_score is not None and (
            isinstance(quality_score, bool)
            or not isinstance(quality_score, (int, float))
            or not 0.0 <= float(quality_score) <= 1.0
        ):
            raise SolidityAdapterError(
                "quality_score must be in [0, 1] when present"
            )

        premises = tuple(
            item
            if isinstance(item, RetrievedPremise)
            else RetrievedPremise.from_dict(_mapping(item, "retrieved premise"))
            for item in retrieved_premises
        )
        for premise in premises:
            if premise.proof_authority or premise.authority != "context_only":
                raise SolidityAdapterError(
                    "retrieved premises must be context_only with proof_authority=False"
                )

        quality_nodes = graph.nodes_by_type(GraphNodeType.QUALITY_SCORE)
        observed_quality = quality_score
        for node in quality_nodes:
            payload = _payload_dict(node)
            if payload.get("is_security_label") is not False:
                raise SolidityAdapterError(
                    "quality_score graph nodes must declare is_security_label=False"
                )
            if observed_quality is None and isinstance(
                payload.get("score"), (int, float)
            ) and not isinstance(payload.get("score"), bool):
                observed_quality = float(payload["score"])

        # Reject leakage of result authority into graph features used for adaptation.
        for node in graph.nodes:
            payload = _payload_dict(node)
            if _contains_forbidden_feature(payload, _RESULT_FEATURE_KEYS):
                raise SolidityAdapterError(
                    f"graph node {node.cid} carries forbidden result features"
                )
            if node.node_type != GraphNodeType.QUALITY_SCORE.value and (
                _contains_forbidden_feature(payload, _SAFETY_LABEL_KEYS)
            ):
                raise SolidityAdapterError(
                    f"graph node {node.cid} carries a safety label feature"
                )

        unsupported_frontiers: list[str] = []
        for node in graph.nodes:
            payload = _payload_dict(node)
            if payload.get("parse_status") in {"failed", "unsupported", "partial"}:
                unsupported_frontiers.append(
                    f"parse:{payload.get('parse_status')}:{node.cid}"
                )
            if payload.get("authority_type") == "verified_result" and not payload.get(
                "verification_id"
            ):
                unsupported_frontiers.append(f"unverified_result:{node.cid}")
            if payload.get("lossy") is True or payload.get("unknown_semantics") is True:
                unsupported_frontiers.append(f"lossy_or_unknown:{node.cid}")

        source_spans: list[dict[str, Any]] = []
        for node in graph.nodes:
            payload = _payload_dict(node)
            span = _span_from_payload(payload)
            if span is not None:
                source_spans.append(
                    {
                        "graph_node_cid": node.cid,
                        "path": payload.get("path", ""),
                        "span": span,
                    }
                )

        semantic_prerequisites = (
            "inert_solidity_parse",
            "source_grounded_graph",
            "no_deployed_bytecode_equality",
            "no_execution_semantics",
            "candidate_authority_only",
        )

        if force_abstain or unsupported_frontiers and not any(
            node.node_type
            in {
                GraphNodeType.FUNCTION.value,
                GraphNodeType.CONTRACT.value,
                GraphNodeType.CALL_SITE.value,
                GraphNodeType.CANDIDATE_CLAIM.value,
            }
            for node in graph.nodes
        ):
            reason = abstain_reason or (
                "unknown or lossy semantics prevent safe Security IR compilation"
            )
            return SolidityAdapterResult(
                disposition=AdapterDisposition.ABSTAINED,
                declaration=None,
                graph_cid=graph.cid,
                source_cids=graph.source_cids,
                config_cid=graph.config_cid,
                partition_cid=partition_cid,
                candidate_authority=CandidateAuthority.ABSTAINED,
                semantic_prerequisites=semantic_prerequisites,
                unsupported_frontiers=tuple(sorted(set(unsupported_frontiers))),
                source_spans=tuple(source_spans),
                retrieved_premises=premises,
                abstentions=(
                    AdapterAbstention(
                        reason_code="lossy_or_unknown_semantics",
                        message=reason,
                        node_cids=tuple(
                            item.split(":", 2)[-1]
                            for item in unsupported_frontiers
                            if ":" in item
                        ),
                        unsupported_frontiers=tuple(
                            sorted(set(unsupported_frontiers))
                        ),
                    ),
                ),
                quality_score=(
                    None
                    if observed_quality is None
                    else float(observed_quality)
                ),
                quality_is_safety_label=False,
            )

        declaration = self._build_declaration(
            graph=graph,
            premises=premises,
            partition_cid=partition_cid,
            unsupported_frontiers=tuple(sorted(set(unsupported_frontiers))),
            source_spans=tuple(source_spans),
            semantic_prerequisites=semantic_prerequisites,
        )
        return SolidityAdapterResult(
            disposition=AdapterDisposition.DECLARED,
            declaration=declaration,
            graph_cid=graph.cid,
            source_cids=graph.source_cids,
            config_cid=graph.config_cid,
            partition_cid=partition_cid,
            candidate_authority=CandidateAuthority.CANDIDATE,
            semantic_prerequisites=semantic_prerequisites,
            unsupported_frontiers=tuple(sorted(set(unsupported_frontiers))),
            source_spans=tuple(source_spans),
            retrieved_premises=premises,
            abstentions=(),
            quality_score=(
                None if observed_quality is None else float(observed_quality)
            ),
            quality_is_safety_label=False,
        )

    def _build_declaration(
        self,
        *,
        graph: SoliditySecurityGraph,
        premises: Sequence[RetrievedPremise],
        partition_cid: str,
        unsupported_frontiers: Sequence[str],
        source_spans: Sequence[Mapping[str, Any]],
        semantic_prerequisites: Sequence[str],
    ) -> SecurityIR:
        source_records: list[SecuritySource] = []
        for source_cid in graph.source_cids:
            source_records.append(
                SecuritySource(
                    source_id=f"src:{source_cid}",
                    uri=f"urn:solidity-cpt:source:{source_cid}",
                    revision=graph.schema_version,
                    content_sha256="",
                    review_status="machine_extracted",
                    attributes={
                        "binding": "graph_source_cid",
                        "candidate_authority": CandidateAuthority.CANDIDATE.value,
                        "config_cid": graph.config_cid,
                        "graph_cid": graph.cid,
                        "partition_cid": partition_cid,
                        "source_cid": source_cid,
                    },
                )
            )
        # Declaration identity source (canonical binding, not raw body).
        declaration_seed = {
            "config_cid": graph.config_cid,
            "graph_cid": graph.cid,
            "partition_cid": partition_cid,
            "source_cids": list(graph.source_cids),
        }
        declaration_digest = hashlib.sha256(
            _canonical_bytes(declaration_seed)
        ).hexdigest()
        declaration_id = f"decl:solidity-cpt:{declaration_digest[:32]}"
        source_ids = tuple(item.source_id for item in source_records)
        if not source_ids:
            # Graphs always bind sources; keep fail-closed fallback explicit.
            raise SolidityAdapterError("graph has no source CIDs to ground declaration")

        resources: list[Resource] = []
        policies: list[Policy] = []
        assumptions: list[ThreatAssumption] = []
        claims: list[SecurityClaim] = []

        # Structural observed units become resources (never safety verdicts).
        for node in graph.nodes:
            if node.node_type not in {
                GraphNodeType.CONTRACT.value,
                GraphNodeType.LIBRARY.value,
                GraphNodeType.INTERFACE.value,
                GraphNodeType.FUNCTION.value,
                GraphNodeType.MODIFIER.value,
            }:
                continue
            payload = _payload_dict(node)
            name = _node_name(node, payload)
            resource_id = _stable_id("resource", node.cid)
            resources.append(
                Resource(
                    resource_id=resource_id,
                    kind=f"solidity.{node.node_type}",
                    source_ids=source_ids,
                    attributes={
                        "candidate_authority": CandidateAuthority.OBSERVED_SYNTAX.value,
                        "config_cid": graph.config_cid,
                        "graph_cid": graph.cid,
                        "graph_node_cid": node.cid,
                        "name": name,
                        "partition_cid": partition_cid,
                        "path": payload.get("path", ""),
                        "proof_authority": False,
                        "source_cids": list(node.source_cids),
                        "unit_kind": payload.get("unit_kind", node.node_type),
                    },
                )
            )

        # External/low-level calls become require-style candidate policies.
        for node in graph.nodes:
            if node.node_type != GraphNodeType.CALL_SITE.value:
                continue
            payload = _payload_dict(node)
            policy_id = _stable_id("policy", node.cid)
            policies.append(
                Policy(
                    policy_id=policy_id,
                    name=f"call-site:{_node_name(node, payload) or node.cid[:16]}",
                    effect=PolicyEffect.REQUIRE,
                    resource_ids=(),
                    source_ids=source_ids,
                    attributes={
                        "candidate_authority": CandidateAuthority.CANDIDATE.value,
                        "config_cid": graph.config_cid,
                        "graph_cid": graph.cid,
                        "graph_node_cid": node.cid,
                        "kind": "solidity.call_site_guard",
                        "partition_cid": partition_cid,
                        "proof_authority": False,
                        "source_cids": list(node.source_cids),
                    },
                )
            )

        # Effect summaries become candidate claims (properties to check later).
        effect_nodes = [
            node
            for node in graph.nodes
            if node.node_type
            in {
                GraphNodeType.EFFECT_SUMMARY.value,
                GraphNodeType.CANDIDATE_CLAIM.value,
                GraphNodeType.SECURITY_CONCEPT.value,
            }
        ]
        for node in effect_nodes:
            payload = _payload_dict(node)
            claim_id = _stable_id("claim", node.cid)
            statement = (
                f"Candidate property grounded in {node.node_type} "
                f"{_node_name(node, payload)!r}; not a proof of safety."
            )
            claims.append(
                SecurityClaim(
                    claim_id=claim_id,
                    statement=statement,
                    domain=SOLIDITY_CANDIDATE_DOMAIN,
                    severity="unspecified",
                    assumption_ids=(),
                    policy_ids=(),
                    source_ids=source_ids,
                    attributes={
                        "candidate_authority": CandidateAuthority.CANDIDATE.value,
                        "config_cid": graph.config_cid,
                        "graph_cid": graph.cid,
                        "graph_node_cid": node.cid,
                        "is_proof": False,
                        "partition_cid": partition_cid,
                        "proof_authority": False,
                        "source_cids": list(node.source_cids),
                        "source_spans": [
                            dict(item)
                            for item in source_spans
                            if item.get("graph_node_cid") == node.cid
                        ],
                    },
                )
            )

        # If no effect/concept claims exist, emit one function-level candidate.
        if not claims:
            functions = [
                node
                for node in graph.nodes
                if node.node_type == GraphNodeType.FUNCTION.value
            ]
            for node in functions[:8]:
                payload = _payload_dict(node)
                claim_id = _stable_id("claim", "function", node.cid)
                claims.append(
                    SecurityClaim(
                        claim_id=claim_id,
                        statement=(
                            "Candidate obligation target for function "
                            f"{_node_name(node, payload)!r}: property to check, "
                            "not evidence that the property holds."
                        ),
                        domain=SOLIDITY_CANDIDATE_DOMAIN,
                        severity="unspecified",
                        assumption_ids=(),
                        policy_ids=(),
                        source_ids=source_ids,
                        attributes={
                            "candidate_authority": CandidateAuthority.CANDIDATE.value,
                            "config_cid": graph.config_cid,
                            "graph_cid": graph.cid,
                            "graph_node_cid": node.cid,
                            "is_proof": False,
                            "partition_cid": partition_cid,
                            "proof_authority": False,
                            "source_cids": list(node.source_cids),
                        },
                    )
                )

        # Retrieved premises → context_only assumptions without proof authority.
        for premise in premises:
            assumptions.append(
                ThreatAssumption(
                    assumption_id=premise.premise_id,
                    statement=premise.statement,
                    source_ids=source_ids,
                    attributes={
                        "authority": "context_only",
                        "candidate_authority": CandidateAuthority.CONTEXT_ONLY.value,
                        "config_cid": graph.config_cid,
                        "graph_cid": graph.cid,
                        "graph_node_cids": list(premise.graph_node_cids),
                        "partition_cid": partition_cid,
                        "proof_authority": False,
                        "retrieved": True,
                        "source_refs": list(premise.source_refs),
                        "source_spans": [dict(item) for item in premise.source_spans],
                    },
                )
            )

        # Bind context assumptions into claims when present.
        if assumptions and claims:
            assumption_ids = tuple(item.assumption_id for item in assumptions)
            claims = [
                SecurityClaim(
                    claim_id=item.claim_id,
                    statement=item.statement,
                    domain=item.domain,
                    severity=item.severity,
                    assumption_ids=assumption_ids,
                    policy_ids=item.policy_ids,
                    source_ids=item.source_ids,
                    attributes=thaw_json(item.attributes),
                )
                for item in claims
            ]

        extension = SecurityExtension(
            extension_id="ext:solidity-cpt-formalization-binding",
            vocabulary=SOLIDITY_EXTENSION_VOCABULARY,
            version=SOLIDITY_EXTENSION_VERSION,
            payload={
                "adapter_version": SOLIDITY_SECURITY_IR_ADAPTER_VERSION,
                "candidate_authority": CandidateAuthority.CANDIDATE.value,
                "config_cid": graph.config_cid,
                "graph_cid": graph.cid,
                "obligation_is_not_proof": True,
                "partition_cid": partition_cid,
                "producer_id": SOLIDITY_SECURITY_IR_ADAPTER_PRODUCER,
                "proof_authority": False,
                "quality_is_safety_label": False,
                "result_artifacts_excluded": True,
                "semantic_prerequisites": list(semantic_prerequisites),
                "source_cids": list(graph.source_cids),
                "source_spans": [dict(item) for item in source_spans],
                "unsupported_frontiers": list(unsupported_frontiers),
            },
            required=False,
            source_ids=source_ids,
        )

        declaration = SecurityIR(
            declaration_id=declaration_id,
            resources=tuple(resources),
            policies=tuple(policies),
            assumptions=tuple(assumptions),
            claims=tuple(claims),
            sources=tuple(source_records),
            extensions=(extension,),
        )
        declaration.validate()
        if _contains_forbidden_feature(
            declaration.to_dict(), _RESULT_FEATURE_KEYS
        ):
            raise SolidityAdapterError(
                "declaration unexpectedly contains result-authority features"
            )
        return declaration


def adapt_solidity_security_graph(
    graph: SoliditySecurityGraph,
    **kwargs: Any,
) -> SolidityAdapterResult:
    """Module-level convenience wrapper around :class:`SoliditySecurityIRAdapter`."""

    return SoliditySecurityIRAdapter().adapt(graph, **kwargs)


__all__ = [
    "AdapterAbstention",
    "AdapterDisposition",
    "CandidateAuthority",
    "RetrievedPremise",
    "SOLIDITY_CANDIDATE_DOMAIN",
    "SOLIDITY_SECURITY_IR_ADAPTER_PRODUCER",
    "SOLIDITY_SECURITY_IR_ADAPTER_VERSION",
    "SolidityAdapterError",
    "SolidityAdapterResult",
    "SoliditySecurityIRAdapter",
    "adapt_solidity_security_graph",
]
