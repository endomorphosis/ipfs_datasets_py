"""Shared single-flight LegalIR evaluation artifact graph.

The compiler runtime evaluates the same complete LegalIR input for several
consumers: unguided/guided compiler metrics, train/validation passes, Hammer,
Leanstral, and promotion evidence.  This module materializes the shared
role-independent work as a small immutable DAG and stores it behind the
existing typed :mod:`legal_ir_evaluation_cache` envelope.

Every node carries the complete cache-key digest and a payload checksum.  A
cached graph is reused only when the key, graph schema, node schema,
dependencies, and checksums all validate.  Concurrent misses are coalesced in
process, and when an existing ``LegalIREvaluationCache`` is supplied the
computed graph is persisted as a normal ``LegalIREvaluationArtifact`` so older
consumers can still decode the top-level compiler metric payload.
"""

from __future__ import annotations

import copy
import math
import re
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Final, Optional

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
    generate_legal_ir_proof_obligations,
    legal_ir_view_contracts,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    InvalidEvaluationArtifactError,
    LegalIREvaluationArtifact,
    LegalIREvaluationCache,
    LegalIREvaluationCacheKey,
    stable_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (
    evaluate_latent_clustering_strata,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
    LATENT_DIAGNOSTIC_ALLOWED_SPLITS,
    LATENT_DIAGNOSTIC_PROHIBITED_SPLITS,
    LATENT_DIAGNOSTIC_SPLIT_IDENTITY,
    LegalIRMetricLineage,
    attach_metric_lineage,
    build_latent_diagnostic_metric_lineage,
    representation_content_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    coerce_latent_records,
    evaluate_latent_diagnostics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_uncertainty import (
    evaluate_legal_ir_calibration,
)


LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION: Final = "legal-ir-evaluation-artifact-graph-v1"
LEGAL_IR_ARTIFACT_NODE_SCHEMA_VERSION: Final = "legal-ir-evaluation-artifact-node-v1"
LEGAL_IR_ARTIFACT_GRAPH_KEY: Final = "_legal_ir_artifact_graph"
MAX_EVALUATION_GRAPH_OBLIGATIONS: Final = 256

NORMALIZATION_NODE: Final = "normalization"
TOKENIZATION_NODE: Final = "tokenization"
COMPILATION_NODE: Final = "compilation"
EMBEDDING_NODE: Final = "embedding"
VIEW_CONTRACT_NODE: Final = "view_contract"
OBLIGATION_NODE: Final = "obligation"
BASELINE_METRIC_NODE: Final = "baseline_metric"

LEGAL_IR_ARTIFACT_NODE_ORDER: Final[tuple[str, ...]] = (
    NORMALIZATION_NODE,
    TOKENIZATION_NODE,
    COMPILATION_NODE,
    EMBEDDING_NODE,
    VIEW_CONTRACT_NODE,
    OBLIGATION_NODE,
    BASELINE_METRIC_NODE,
)
LEGAL_IR_ARTIFACT_NODE_KINDS: Final = frozenset(LEGAL_IR_ARTIFACT_NODE_ORDER)

LEGAL_IR_ARTIFACT_CONSUMER_ROLES: Final[tuple[str, ...]] = (
    "unguided",
    "guided",
    "train",
    "validation",
    "hammer",
    "leanstral",
    "promotion",
)
LEGAL_IR_LATENT_DIAGNOSTIC_KEY: Final = "_legal_ir_latent_diagnostics"
LEGAL_IR_COLLAPSE_TRIGGER_KEY: Final = "_legal_ir_collapse_triggers"
LEGAL_IR_LATENT_DIAGNOSTIC_REPORT_SCHEMA_VERSION: Final = "legal-ir-latent-diagnostic-report-v1"
TRIGGER_LOW_EFFECTIVE_RANK: Final = "low_effective_rank"
TRIGGER_HIGH_ANISOTROPY: Final = "high_spectral_anisotropy"
TRIGGER_DUPLICATE_MEMORIZATION: Final = "duplicate_memorization"
TRIGGER_FALSE_NEIGHBORHOODS: Final = "false_neighborhoods"
TRIGGER_LOW_LATENT_USE: Final = "low_latent_use"
TRIGGER_HIGH_ECE: Final = "high_expected_calibration_error"
TRIGGER_HIGH_BRIER: Final = "high_brier_score"
TRIGGER_UNKNOWN_DENOMINATOR: Final = "unknown_denominator"
TRIGGER_FAMILY_IMBALANCE: Final = "family_imbalance"
TRIGGER_HIDDEN_TEST_SPLIT: Final = "hidden_test_split"
TRIGGER_CENTERED_DEGENERACY: Final = "centered_spectrum_degeneracy"


class LegalIRArtifactGraphError(RuntimeError):
    """Base error for invalid LegalIR artifact graphs."""


class LegalIRArtifactGraphProvenanceError(
    LegalIRArtifactGraphError, InvalidEvaluationArtifactError
):
    """Raised when a cached graph belongs to another key or producer state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidEvaluationArtifactError("artifact graph contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    if hasattr(value, "__dict__"):
        return _json_value(
            {
                str(key): item
                for key, item in sorted(vars(value).items())
                if not str(key).startswith("_")
            }
        )
    return repr(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    return value


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return stable_digest(_json_value(payload))


def _consumer_role(role: str) -> str:
    normalized = str(role or "unspecified").strip().lower().replace("-", "_")
    return normalized or "unspecified"


def _source_text(sample: Any) -> str:
    if isinstance(sample, str):
        return sample
    if isinstance(sample, Mapping):
        return str(
            sample.get("normalized_text") or sample.get("text") or sample.get("source_text") or ""
        )
    return str(
        getattr(sample, "normalized_text", None)
        or getattr(sample, "text", None)
        or getattr(sample, "source_text", None)
        or ""
    )


def _sample_identifier(sample: Any) -> str:
    if isinstance(sample, Mapping):
        return str(sample.get("sample_id") or sample.get("document_id") or "")
    return str(getattr(sample, "sample_id", None) or getattr(sample, "document_id", None) or "")


def _normalise_text(sample: Any) -> str:
    return re.sub(r"\s+", " ", _source_text(sample)).strip()


def _tokenize_text(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[A-Za-z0-9_]+(?:'[A-Za-z0-9_]+)?", str(text).lower()))


def _default_embedding(sample: Any) -> tuple[float, ...]:
    raw: Any = ()
    if isinstance(sample, Mapping):
        raw = sample.get("embedding_vector", ())
    else:
        raw = getattr(sample, "embedding_vector", ())
    try:
        return tuple(float(value) for value in (raw or ()))
    except (TypeError, ValueError) as exc:
        raise InvalidEvaluationArtifactError(
            "embedding producer returned non-numeric values"
        ) from exc


def _default_embedding_model(sample: Any) -> str:
    if isinstance(sample, Mapping):
        return str(sample.get("embedding_model") or "")
    return str(getattr(sample, "embedding_model", "") or "")


def _modal_document(compilation_result: Any, sample: Any) -> Any:
    return (
        getattr(compilation_result, "modal_ir", None) or getattr(sample, "modal_ir", None) or sample
    )


def _default_view_contract_payload(compilation_result: Any, sample: Any) -> Mapping[str, Any]:
    contracts = legal_ir_view_contracts()
    return {
        "contract_count": len(contracts),
        "contract_ids": [contract.contract_id for contract in contracts],
        "registry_version": LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
        "target_components": [contract.target_component for contract in contracts],
    }


def _default_obligation_payload(compilation_result: Any, sample: Any) -> Mapping[str, Any]:
    obligations = generate_legal_ir_proof_obligations(
        _modal_document(compilation_result, sample),
        max_obligations=MAX_EVALUATION_GRAPH_OBLIGATIONS + 1,
    )
    truncated = len(obligations) > MAX_EVALUATION_GRAPH_OBLIGATIONS
    obligations = obligations[:MAX_EVALUATION_GRAPH_OBLIGATIONS]
    return {
        "obligation_count": len(obligations),
        "obligation_ids": [item.obligation_id for item in obligations],
        "obligation_materialization_limit": MAX_EVALUATION_GRAPH_OBLIGATIONS,
        "obligations_truncated": truncated,
        "obligations": [item.to_dict() for item in obligations],
    }


def _default_baseline_metrics(compilation_result: Any, sample: Any) -> Mapping[str, Any]:
    losses = getattr(compilation_result, "losses", {}) or {}
    if not isinstance(losses, Mapping):
        return {}
    return {
        str(name): float(value)
        for name, value in losses.items()
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    }


def _default_compiler_payload(compilation_result: Any) -> Mapping[str, Any]:
    modal_ir = getattr(compilation_result, "modal_ir", None)
    frame_candidates = getattr(compilation_result, "frame_candidates", ()) or ()
    decoded = getattr(compilation_result, "decoded_modal_text", None)
    decoded_text = getattr(decoded, "text", None)
    if decoded_text is None:
        decoded_text = getattr(compilation_result, "decoded_text", None)
    if decoded_text is None:
        decoded_text = decoded
    return {
        "decoded_modal_text": str(decoded_text or ""),
        "frame_candidate_count": len(frame_candidates),
        "kg_triple_count": len(getattr(compilation_result, "kg_triples", ()) or ()),
        "losses": _json_value(getattr(compilation_result, "losses", {}) or {}),
        "metadata": _json_value(getattr(compilation_result, "metadata", {}) or {}),
        "modal_formula_count": len(getattr(modal_ir, "formulas", ()) or ()),
    }


def _result_view_families(
    compilation_result: Any,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
) -> tuple[str, ...]:
    families: set[str] = set()
    metadata = getattr(compilation_result, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        for key in ("legal_ir_view_families", "legal_ir_view_family", "target_families"):
            raw = metadata.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                families.update(str(item) for item in raw if str(item))
            elif raw:
                families.add(str(raw))
    if isinstance(compiler_guidance, Mapping):
        for key in ("legal_ir_view", "target_component"):
            raw = compiler_guidance.get(key)
            if raw:
                families.add(str(raw).split(".", 1)[0])
    return tuple(sorted(families or {"unknown"}))


@dataclass(frozen=True, slots=True)
class LegalIRArtifactNode:
    """One immutable materialized node in the shared LegalIR DAG."""

    kind: str
    key_digest: str
    payload: Mapping[str, Any]
    dependencies: tuple[str, ...] = ()
    producer_id: str = ""
    materialization_seconds: float = 0.0
    created_at: str = field(default_factory=_utc_now)
    payload_sha256: str = ""
    schema_version: str = LEGAL_IR_ARTIFACT_NODE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip()
        if kind not in LEGAL_IR_ARTIFACT_NODE_KINDS:
            raise InvalidEvaluationArtifactError(f"unsupported artifact node kind: {kind!r}")
        key_digest = str(self.key_digest or "").strip()
        if not key_digest:
            raise LegalIRArtifactGraphProvenanceError("artifact node key_digest is empty")
        payload = _json_value(self.payload)
        if not isinstance(payload, Mapping):
            raise InvalidEvaluationArtifactError("artifact node payload must be a mapping")
        payload_sha256 = str(self.payload_sha256 or _payload_digest(payload)).strip()
        if payload_sha256 != _payload_digest(payload):
            raise LegalIRArtifactGraphProvenanceError(
                f"{kind} artifact node payload checksum does not match"
            )
        dependencies = tuple(str(item) for item in self.dependencies if str(item))
        for dependency in dependencies:
            if dependency not in LEGAL_IR_ARTIFACT_NODE_KINDS:
                raise LegalIRArtifactGraphProvenanceError(
                    f"{kind} artifact node has unknown dependency {dependency!r}"
                )
        seconds = float(self.materialization_seconds or 0.0)
        if not math.isfinite(seconds) or seconds < 0.0:
            raise InvalidEvaluationArtifactError("materialization_seconds must be finite")
        try:
            datetime.fromisoformat(str(self.created_at).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise InvalidEvaluationArtifactError("created_at must be ISO-8601") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "key_digest", key_digest)
        object.__setattr__(self, "payload", _freeze(payload))
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "producer_id", str(self.producer_id or kind))
        object.__setattr__(self, "materialization_seconds", seconds)
        object.__setattr__(self, "payload_sha256", payload_sha256)
        if self.schema_version != LEGAL_IR_ARTIFACT_NODE_SCHEMA_VERSION:
            raise InvalidEvaluationArtifactError("artifact node schema version is stale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "dependencies": list(self.dependencies),
            "key_digest": self.key_digest,
            "kind": self.kind,
            "materialization_seconds": round(float(self.materialization_seconds), 9),
            "payload": _plain(self.payload),
            "payload_sha256": self.payload_sha256,
            "producer_id": self.producer_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LegalIRArtifactNode":
        return cls(
            kind=str(payload.get("kind") or ""),
            key_digest=str(payload.get("key_digest") or ""),
            payload=(
                payload.get("payload", {}) if isinstance(payload.get("payload"), Mapping) else {}
            ),
            dependencies=tuple(str(item) for item in payload.get("dependencies", ()) or ()),
            producer_id=str(payload.get("producer_id") or ""),
            materialization_seconds=float(payload.get("materialization_seconds", 0.0) or 0.0),
            created_at=str(payload.get("created_at") or ""),
            payload_sha256=str(payload.get("payload_sha256") or ""),
            schema_version=str(payload.get("schema_version") or ""),
        )


@dataclass(frozen=True, slots=True)
class LegalIRArtifactGraphBundle:
    """Complete shared LegalIR artifact DAG for one evaluation cache key."""

    key: LegalIREvaluationCacheKey
    nodes: Mapping[str, LegalIRArtifactNode]
    consumers: tuple[str, ...] = ()
    created_at: str = field(default_factory=_utc_now)
    schema_version: str = LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.key, LegalIREvaluationCacheKey):
            raise TypeError("key must be LegalIREvaluationCacheKey")
        if self.schema_version != LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION:
            raise InvalidEvaluationArtifactError("artifact graph schema version is stale")
        raw_nodes = dict(self.nodes or {})
        missing = [kind for kind in LEGAL_IR_ARTIFACT_NODE_ORDER if kind not in raw_nodes]
        if missing:
            raise LegalIRArtifactGraphProvenanceError(
                "artifact graph is incomplete: " + ", ".join(missing)
            )
        nodes: dict[str, LegalIRArtifactNode] = {}
        for kind in LEGAL_IR_ARTIFACT_NODE_ORDER:
            node = raw_nodes[kind]
            if not isinstance(node, LegalIRArtifactNode):
                if isinstance(node, Mapping):
                    node = LegalIRArtifactNode.from_dict(node)
                else:
                    raise InvalidEvaluationArtifactError(f"{kind} node has the wrong type")
            if node.kind != kind:
                raise LegalIRArtifactGraphProvenanceError(
                    f"artifact graph stored {node.kind!r} under {kind!r}"
                )
            if node.key_digest != self.complete_digest:
                raise LegalIRArtifactGraphProvenanceError(
                    f"{kind} node belongs to another complete digest"
                )
            for dependency in node.dependencies:
                if dependency not in nodes:
                    raise LegalIRArtifactGraphProvenanceError(
                        f"{kind} node dependency {dependency!r} is missing or unordered"
                    )
            nodes[kind] = node
        try:
            datetime.fromisoformat(str(self.created_at).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise InvalidEvaluationArtifactError("created_at must be ISO-8601") from exc
        consumers = tuple(
            dict.fromkeys(_consumer_role(role) for role in self.consumers if str(role))
        )
        object.__setattr__(self, "nodes", MappingProxyType(nodes))
        object.__setattr__(self, "consumers", consumers)

    @property
    def complete_digest(self) -> str:
        return self.key.digest

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def materialization_seconds(self) -> float:
        return sum(float(node.materialization_seconds) for node in self.nodes.values())

    @property
    def graph_digest(self) -> str:
        return stable_digest(
            {
                "complete_digest": self.complete_digest,
                "key": self.key.to_dict(),
                "node_payloads": {kind: node.payload_sha256 for kind, node in self.nodes.items()},
                "schema_version": self.schema_version,
            }
        )

    @property
    def compiler_payload(self) -> Mapping[str, Any]:
        payload = self.nodes[COMPILATION_NODE].payload.get("compiler_artifact", {})
        return payload if isinstance(payload, Mapping) else {}

    @property
    def embedding(self) -> tuple[float, ...]:
        raw = self.nodes[EMBEDDING_NODE].payload.get("embedding", ())
        return tuple(float(value) for value in raw or ())

    @property
    def baseline_metrics(self) -> Mapping[str, Any]:
        payload = self.nodes[BASELINE_METRIC_NODE].payload.get("metrics", {})
        return payload if isinstance(payload, Mapping) else {}

    @property
    def per_view_metrics(self) -> Mapping[str, Any]:
        payload = self.nodes[BASELINE_METRIC_NODE].payload.get("per_view_metrics", {})
        return payload if isinstance(payload, Mapping) else {}

    @property
    def metadata(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "artifact_graph_digest": self.graph_digest,
                "artifact_graph_schema_version": self.schema_version,
                "complete_digest": self.complete_digest,
                "consumer_roles": self.consumers,
                "materialized_node_count": self.node_count,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete_digest": self.complete_digest,
            "consumers": list(self.consumers),
            "created_at": self.created_at,
            "graph_digest": self.graph_digest,
            "key": self.key.to_dict(),
            "materialization_seconds": round(self.materialization_seconds, 9),
            "node_order": list(LEGAL_IR_ARTIFACT_NODE_ORDER),
            "nodes": {kind: self.nodes[kind].to_dict() for kind in LEGAL_IR_ARTIFACT_NODE_ORDER},
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LegalIRArtifactGraphBundle":
        if payload.get("schema_version") != LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION:
            raise InvalidEvaluationArtifactError("artifact graph schema version is stale")
        raw_key = payload.get("key")
        if not isinstance(raw_key, Mapping):
            raise LegalIRArtifactGraphProvenanceError("artifact graph key is missing")
        bundle = cls(
            key=LegalIREvaluationCacheKey.from_dict(raw_key),
            nodes=payload.get("nodes", {}) if isinstance(payload.get("nodes"), Mapping) else {},
            consumers=tuple(str(item) for item in payload.get("consumers", ()) or ()),
            created_at=str(payload.get("created_at") or ""),
            schema_version=str(payload.get("schema_version") or ""),
        )
        if str(payload.get("complete_digest") or "") != bundle.complete_digest:
            raise LegalIRArtifactGraphProvenanceError("artifact graph complete digest mismatch")
        if str(payload.get("graph_digest") or "") != bundle.graph_digest:
            raise LegalIRArtifactGraphProvenanceError("artifact graph digest mismatch")
        return bundle

    @classmethod
    def from_evaluation_artifact(
        cls, artifact: LegalIREvaluationArtifact
    ) -> "LegalIRArtifactGraphBundle":
        if not isinstance(artifact, LegalIREvaluationArtifact):
            raise TypeError("artifact must be LegalIREvaluationArtifact")
        raw_graph = artifact.compiler_artifact.get(LEGAL_IR_ARTIFACT_GRAPH_KEY)
        if not isinstance(raw_graph, Mapping):
            raise LegalIRArtifactGraphProvenanceError(
                "evaluation artifact is missing graph metadata"
            )
        bundle = cls.from_dict(raw_graph)
        if bundle.key != artifact.key:
            raise LegalIRArtifactGraphProvenanceError("artifact graph key does not match cache key")
        return bundle

    def to_evaluation_artifact(self) -> LegalIREvaluationArtifact:
        compiler_payload = dict(_plain(self.compiler_payload))
        compiler_payload[LEGAL_IR_ARTIFACT_GRAPH_KEY] = self.to_dict()
        return LegalIREvaluationArtifact(
            key=self.key,
            compiler_artifact=compiler_payload,
            embedding=self.embedding,
            metrics=self.baseline_metrics,
            per_view_metrics=self.per_view_metrics,
            metadata=self.metadata,
            compilation_seconds=self.nodes[COMPILATION_NODE].materialization_seconds,
            embedding_seconds=self.nodes[EMBEDDING_NODE].materialization_seconds,
            metric_seconds=(
                self.nodes[NORMALIZATION_NODE].materialization_seconds
                + self.nodes[TOKENIZATION_NODE].materialization_seconds
                + self.nodes[VIEW_CONTRACT_NODE].materialization_seconds
                + self.nodes[OBLIGATION_NODE].materialization_seconds
                + self.nodes[BASELINE_METRIC_NODE].materialization_seconds
            ),
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class LegalIRArtifactGraphBuildPlan:
    """Callbacks used to build a graph without binding to one codec type."""

    sample: Any
    compile: Callable[[], Any]
    compiler_payload: Callable[[Any], Mapping[str, Any]] = _default_compiler_payload
    normalize: Callable[[Any], str] = _normalise_text
    tokenize: Callable[[str], Sequence[str]] = _tokenize_text
    embed: Callable[[Any], Sequence[float]] = _default_embedding
    view_contracts: Callable[[Any, Any], Mapping[str, Any]] = _default_view_contract_payload
    obligations: Callable[[Any, Any], Mapping[str, Any]] = _default_obligation_payload
    baseline_metrics: Callable[[Any, Any], Mapping[str, Any]] = _default_baseline_metrics
    compiler_guidance: Optional[Mapping[str, Any]] = None
    producer_namespace: str = "legal_ir_artifact_graph"
    known_compilation_seconds: Optional[float] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not callable(self.compile):
            raise TypeError("compile must be callable")


class LegalIRArtifactGraphStore:
    """Single-flight materializer for complete LegalIR artifact graphs."""

    def __init__(
        self,
        evaluation_cache: Optional[LegalIREvaluationCache] = None,
        *,
        memory_entries: int = 256,
    ) -> None:
        self.evaluation_cache = evaluation_cache
        self.memory_entries = max(0, int(memory_entries))
        self._lock = threading.RLock()
        self._memory: OrderedDict[str, LegalIRArtifactGraphBundle] = OrderedDict()
        self._flights: dict[str, Future[LegalIRArtifactGraphBundle]] = {}
        self._stats: Counter[str] = Counter()
        self._role_requests: Counter[str] = Counter()
        self._role_hits: Counter[str] = Counter()
        self._consumer_requests: Counter[str] = Counter()
        self._consumer_hits: Counter[str] = Counter()
        self._saved_wall_time_seconds = 0.0

    def _record_request(self, role: str, consumers: Sequence[str]) -> None:
        normalized_role = _consumer_role(role)
        normalized_consumers = tuple(
            dict.fromkeys(_consumer_role(item) for item in consumers if str(item))
        ) or (normalized_role,)
        with self._lock:
            self._stats["lookups"] += 1
            self._role_requests[normalized_role] += 1
            for consumer in normalized_consumers:
                self._consumer_requests[consumer] += 1

    def _record_hit(
        self,
        bundle: LegalIRArtifactGraphBundle,
        *,
        role: str,
        consumers: Sequence[str],
        kind: str,
    ) -> None:
        normalized_role = _consumer_role(role)
        normalized_consumers = tuple(
            dict.fromkeys(_consumer_role(item) for item in consumers if str(item))
        ) or (normalized_role,)
        with self._lock:
            self._stats["hits"] += 1
            self._stats[f"{kind}_hits"] += 1
            self._stats["avoided_graph_materializations"] += 1
            self._stats["avoided_node_materializations"] += bundle.node_count
            self._saved_wall_time_seconds += bundle.materialization_seconds
            self._role_hits[normalized_role] += 1
            for consumer in normalized_consumers:
                self._consumer_hits[consumer] += 1

    def _memory_get(self, key: LegalIREvaluationCacheKey) -> Optional[LegalIRArtifactGraphBundle]:
        digest = key.digest
        with self._lock:
            bundle = self._memory.get(digest)
            if bundle is None:
                return None
            if bundle.key != key:
                self._memory.pop(digest, None)
                self._stats["provenance_rejections"] += 1
                return None
            self._memory.move_to_end(digest)
            return bundle

    def _memory_put(self, bundle: LegalIRArtifactGraphBundle) -> None:
        if self.memory_entries <= 0:
            return
        with self._lock:
            self._memory[bundle.complete_digest] = bundle
            self._memory.move_to_end(bundle.complete_digest)
            while len(self._memory) > self.memory_entries:
                self._memory.popitem(last=False)
                self._stats["memory_evictions"] += 1

    def _cache_get(
        self, key: LegalIREvaluationCacheKey, *, role: str
    ) -> Optional[LegalIRArtifactGraphBundle]:
        if self.evaluation_cache is None:
            return None
        artifact = self.evaluation_cache.get(key, role=role)
        if artifact is None:
            return None
        try:
            bundle = LegalIRArtifactGraphBundle.from_evaluation_artifact(artifact)
        except (TypeError, ValueError, InvalidEvaluationArtifactError, LegalIRArtifactGraphError):
            with self._lock:
                self._stats["provenance_rejections"] += 1
            return None
        self._memory_put(bundle)
        return bundle

    def get_or_materialize(
        self,
        key: LegalIREvaluationCacheKey,
        plan: LegalIRArtifactGraphBuildPlan,
        *,
        role: str = "unspecified",
        consumers: Sequence[str] = (),
    ) -> LegalIRArtifactGraphBundle:
        if not isinstance(key, LegalIREvaluationCacheKey):
            raise TypeError("key must be LegalIREvaluationCacheKey")
        self._record_request(role, consumers)
        bundle = self._memory_get(key)
        if bundle is not None:
            self._record_hit(bundle, role=role, consumers=consumers, kind="memory")
            return bundle
        bundle = self._cache_get(key, role=role)
        if bundle is not None:
            self._record_hit(bundle, role=role, consumers=consumers, kind="cache")
            return bundle

        digest = key.digest
        with self._lock:
            future = self._flights.get(digest)
            owner = future is None
            if owner:
                future = Future()
                self._flights[digest] = future
            else:
                self._stats["coalesced_waiters"] += 1
        assert future is not None
        if not owner:
            bundle = future.result()
            self._record_hit(bundle, role=role, consumers=consumers, kind="coalesced")
            return bundle

        try:
            process_lock = getattr(self.evaluation_cache, "_process_lock", None)
            context = process_lock(key) if callable(process_lock) else _NullContext()
            with context:
                bundle = self._memory_get(key) or self._cache_get(key, role=role)
                if bundle is not None:
                    self._record_hit(
                        bundle,
                        role=role,
                        consumers=consumers,
                        kind="process_coalesced",
                    )
                else:
                    with self._lock:
                        self._stats["misses"] += 1
                    started = time.monotonic()
                    bundle = build_legal_ir_artifact_graph_bundle(
                        key,
                        plan,
                        consumers=consumers or (role,),
                    )
                    elapsed = max(0.0, time.monotonic() - started)
                    self._memory_put(bundle)
                    if self.evaluation_cache is not None:
                        self.evaluation_cache.put(bundle.to_evaluation_artifact())
                    with self._lock:
                        self._stats["computations"] += 1
                        self._stats["node_materializations"] += bundle.node_count
                        self._stats["computed_wall_time_milliseconds"] += int(
                            round(elapsed * 1000.0)
                        )
            future.set_result(bundle)
            return bundle
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()
            raise
        finally:
            with self._lock:
                self._flights.pop(digest, None)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
            lookups = int(stats.get("lookups", 0))
            hits = int(stats.get("hits", 0))
            return {
                "schema_version": LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION,
                "lookups": lookups,
                "hits": hits,
                "misses": int(stats.get("misses", 0)),
                "hit_rate": round(hits / lookups, 9) if lookups else 0.0,
                "memory_hits": int(stats.get("memory_hits", 0)),
                "cache_hits": int(stats.get("cache_hits", 0)),
                "coalesced_hits": int(stats.get("coalesced_hits", 0)),
                "process_coalesced_hits": int(stats.get("process_coalesced_hits", 0)),
                "coalesced_waiters": int(stats.get("coalesced_waiters", 0)),
                "computations": int(stats.get("computations", 0)),
                "node_materializations": int(stats.get("node_materializations", 0)),
                "avoided_graph_materializations": int(
                    stats.get("avoided_graph_materializations", 0)
                ),
                "avoided_node_materializations": int(stats.get("avoided_node_materializations", 0)),
                "provenance_rejections": int(stats.get("provenance_rejections", 0)),
                "memory_evictions": int(stats.get("memory_evictions", 0)),
                "saved_wall_time_seconds": round(self._saved_wall_time_seconds, 9),
                "computed_wall_time_seconds": round(
                    int(stats.get("computed_wall_time_milliseconds", 0)) / 1000.0,
                    3,
                ),
                "role_requests": dict(sorted(self._role_requests.items())),
                "role_hits": dict(sorted(self._role_hits.items())),
                "consumer_requests": dict(sorted(self._consumer_requests.items())),
                "consumer_hits": dict(sorted(self._consumer_hits.items())),
                "memory_entry_count": len(self._memory),
            }

    stats = summary


class _NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: Any) -> None:
        return None


def _timed_node(
    *,
    kind: str,
    key_digest: str,
    payload_fn: Callable[[], Mapping[str, Any]],
    dependencies: Sequence[str] = (),
    producer_id: str = "",
    known_seconds: Optional[float] = None,
) -> LegalIRArtifactNode:
    started = time.monotonic()
    payload = payload_fn()
    elapsed = max(0.0, time.monotonic() - started)
    if known_seconds is not None:
        elapsed = max(0.0, float(known_seconds))
    return LegalIRArtifactNode(
        kind=kind,
        key_digest=key_digest,
        payload=payload,
        dependencies=tuple(dependencies),
        producer_id=producer_id or kind,
        materialization_seconds=elapsed,
    )


def build_legal_ir_artifact_graph_bundle(
    key: LegalIREvaluationCacheKey,
    plan: LegalIRArtifactGraphBuildPlan,
    *,
    consumers: Sequence[str] = (),
) -> LegalIRArtifactGraphBundle:
    """Materialize every required node exactly once for ``key``."""

    key_digest = key.digest
    producer_namespace = str(plan.producer_namespace or "legal_ir_artifact_graph")

    normalized_value: dict[str, Any] = {}

    def normalization_payload() -> Mapping[str, Any]:
        normalized = str(plan.normalize(plan.sample))
        tokens_for_hash = _tokenize_text(normalized)
        normalized_value["text"] = normalized
        return {
            "char_count": len(normalized),
            "normalized_text_sha256": stable_digest({"text": normalized}),
            "sample_id_hash": stable_digest({"sample_id": _sample_identifier(plan.sample)}),
            "tokenizable": bool(tokens_for_hash),
        }

    nodes: dict[str, LegalIRArtifactNode] = {}
    nodes[NORMALIZATION_NODE] = _timed_node(
        kind=NORMALIZATION_NODE,
        key_digest=key_digest,
        payload_fn=normalization_payload,
        producer_id=f"{producer_namespace}:normalize",
    )

    token_value: dict[str, Any] = {}

    def tokenization_payload() -> Mapping[str, Any]:
        tokens = tuple(str(item) for item in plan.tokenize(str(normalized_value.get("text", ""))))
        token_value["tokens"] = tokens
        return {
            "token_count": len(tokens),
            "token_hashes": [stable_digest({"token": token}) for token in tokens],
            "tokens_sha256": stable_digest({"tokens": list(tokens)}),
        }

    nodes[TOKENIZATION_NODE] = _timed_node(
        kind=TOKENIZATION_NODE,
        key_digest=key_digest,
        payload_fn=tokenization_payload,
        dependencies=(NORMALIZATION_NODE,),
        producer_id=f"{producer_namespace}:tokenize",
    )

    compilation_result_holder: dict[str, Any] = {}

    def compilation_payload() -> Mapping[str, Any]:
        result = plan.compile()
        compilation_result_holder["result"] = result
        compiler_payload = dict(_json_value(plan.compiler_payload(result)))
        return {
            "compiler_artifact": compiler_payload,
            "compiler_artifact_sha256": stable_digest(compiler_payload),
            "input_token_count": len(token_value.get("tokens", ())),
        }

    nodes[COMPILATION_NODE] = _timed_node(
        kind=COMPILATION_NODE,
        key_digest=key_digest,
        payload_fn=compilation_payload,
        dependencies=(TOKENIZATION_NODE,),
        producer_id=f"{producer_namespace}:compile",
        known_seconds=plan.known_compilation_seconds,
    )
    compilation_result = compilation_result_holder["result"]

    def embedding_payload() -> Mapping[str, Any]:
        embedding = tuple(float(value) for value in plan.embed(plan.sample))
        if any(not math.isfinite(value) for value in embedding):
            raise InvalidEvaluationArtifactError("embedding contains a non-finite value")
        return {
            "dimension": len(embedding),
            "embedding": list(embedding),
            "embedding_model": _default_embedding_model(plan.sample),
            "embedding_sha256": stable_digest({"embedding": list(embedding)}),
        }

    nodes[EMBEDDING_NODE] = _timed_node(
        kind=EMBEDDING_NODE,
        key_digest=key_digest,
        payload_fn=embedding_payload,
        dependencies=(NORMALIZATION_NODE,),
        producer_id=f"{producer_namespace}:embed",
    )

    def view_contract_payload() -> Mapping[str, Any]:
        payload = dict(_json_value(plan.view_contracts(compilation_result, plan.sample)))
        payload.setdefault("registry_version", LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION)
        return payload

    nodes[VIEW_CONTRACT_NODE] = _timed_node(
        kind=VIEW_CONTRACT_NODE,
        key_digest=key_digest,
        payload_fn=view_contract_payload,
        dependencies=(COMPILATION_NODE,),
        producer_id=f"{producer_namespace}:view_contract",
    )

    def obligation_payload() -> Mapping[str, Any]:
        return dict(_json_value(plan.obligations(compilation_result, plan.sample)))

    nodes[OBLIGATION_NODE] = _timed_node(
        kind=OBLIGATION_NODE,
        key_digest=key_digest,
        payload_fn=obligation_payload,
        dependencies=(COMPILATION_NODE, VIEW_CONTRACT_NODE),
        producer_id=f"{producer_namespace}:obligation",
    )

    def baseline_payload() -> Mapping[str, Any]:
        metrics = dict(_json_value(plan.baseline_metrics(compilation_result, plan.sample)))
        per_view_metrics = {
            family: copy.deepcopy(metrics)
            for family in _result_view_families(compilation_result, plan.compiler_guidance)
        }
        return {
            "metrics": metrics,
            "metric_count": len(metrics),
            "per_view_metrics": per_view_metrics,
            "producer_metadata": _json_value(plan.metadata),
        }

    nodes[BASELINE_METRIC_NODE] = _timed_node(
        kind=BASELINE_METRIC_NODE,
        key_digest=key_digest,
        payload_fn=baseline_payload,
        dependencies=(COMPILATION_NODE, EMBEDDING_NODE, VIEW_CONTRACT_NODE, OBLIGATION_NODE),
        producer_id=f"{producer_namespace}:baseline_metric",
    )

    return LegalIRArtifactGraphBundle(
        key=key,
        nodes=nodes,
        consumers=tuple(consumers),
    )


def legal_ir_evaluation_artifact_from_compilation(
    key: LegalIREvaluationCacheKey,
    *,
    sample: Any,
    compilation_result: Any,
    compiler_payload: Optional[Mapping[str, Any]] = None,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
    compilation_seconds: float = 0.0,
    producer_namespace: str = "legal_ir_compiler_metric",
    metadata: Optional[Mapping[str, Any]] = None,
) -> LegalIREvaluationArtifact:
    """Build a typed cache artifact with a complete embedded DAG.

    This helper is for call sites that have already performed compilation
    inside a surrounding timeout or instrumentation context.
    """

    plan = LegalIRArtifactGraphBuildPlan(
        sample=sample,
        compile=lambda: compilation_result,
        compiler_payload=(lambda _result: compiler_payload)
        if compiler_payload is not None
        else _default_compiler_payload,
        compiler_guidance=compiler_guidance,
        known_compilation_seconds=compilation_seconds,
        producer_namespace=producer_namespace,
        metadata=metadata or {},
    )
    return build_legal_ir_artifact_graph_bundle(
        key,
        plan,
        consumers=tuple(metadata.get("consumers", ()) if isinstance(metadata, Mapping) else ()),
    ).to_evaluation_artifact()


@dataclass(frozen=True, slots=True)
class CollapseTriggerConfig:
    """Fail-closed thresholds for latent collapse and miscalibration."""

    min_effective_rank: float = 1.5
    max_spectral_anisotropy: float = 0.85
    max_duplicate_intra_cosine: float = 0.98
    max_false_neighborhood_rate: float = 0.35
    min_latent_use_rate: float = 0.5
    max_expected_calibration_error: float = 0.08
    max_brier_score: float = 0.25
    min_family_balance_ratio: float = 0.25
    neighbor_k: int = 3
    reliability_bin_count: int = 10

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_brier_score": self.max_brier_score,
            "max_duplicate_intra_cosine": self.max_duplicate_intra_cosine,
            "max_expected_calibration_error": self.max_expected_calibration_error,
            "max_false_neighborhood_rate": self.max_false_neighborhood_rate,
            "max_spectral_anisotropy": self.max_spectral_anisotropy,
            "min_effective_rank": self.min_effective_rank,
            "min_family_balance_ratio": self.min_family_balance_ratio,
            "min_latent_use_rate": self.min_latent_use_rate,
            "neighbor_k": self.neighbor_k,
            "reliability_bin_count": self.reliability_bin_count,
        }


@dataclass(frozen=True, slots=True)
class CollapseTrigger:
    """One explicit collapse or calibration trigger."""

    trigger_id: str
    metric: str
    actual: Optional[float]
    threshold: Optional[float]
    severity: str
    reason: str
    unknown_denominator: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual": None if self.actual is None else round(float(self.actual), 12),
            "metric": self.metric,
            "reason": self.reason,
            "severity": self.severity,
            "threshold": None if self.threshold is None else round(float(self.threshold), 12),
            "trigger_id": self.trigger_id,
            "unknown_denominator": bool(self.unknown_denominator),
        }


@dataclass(frozen=True, slots=True)
class LegalIRLatentDiagnosticReport:
    """Content-bound diagnostic/calibration report with collapse triggers."""

    latent: Mapping[str, Any]
    clustering: Mapping[str, Any]
    calibration: Mapping[str, Any]
    collapse_triggers: tuple[CollapseTrigger, ...]
    unknown_denominators: tuple[str, ...]
    metric_lineage: Mapping[str, Any]
    representation_digest: str
    split_identity: str = LATENT_DIAGNOSTIC_SPLIT_IDENTITY
    schema_version: str = LEGAL_IR_LATENT_DIAGNOSTIC_REPORT_SCHEMA_VERSION
    prohibited_split_count: int = 0

    @property
    def collapsed(self) -> bool:
        return any(trigger.severity == "hard" for trigger in self.collapse_triggers)

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict(include_digest=False))

    def metric_vector(self) -> dict[str, float]:
        values: dict[str, float] = {}
        spectrum = self.latent.get("spectrum", {})
        if isinstance(spectrum, Mapping):
            for key, value in spectrum.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    number = float(value)
                    if math.isfinite(number):
                        values[str(key)] = round(number, 12)
        neighborhoods = self.latent.get("false_neighborhoods", {})
        if isinstance(neighborhoods, Mapping):
            rate = neighborhoods.get("false_neighborhood_rate")
            if isinstance(rate, (int, float)) and math.isfinite(float(rate)):
                values["false_neighborhood_rate"] = round(float(rate), 12)
        for key in (
            "brier_score",
            "expected_calibration_error",
            "success_conditioned_confidence",
            "failure_conditioned_confidence",
        ):
            value = self.calibration.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[key] = round(float(value), 12)
        values["collapse_trigger_count"] = float(len(self.collapse_triggers))
        values["hard_collapse_trigger_count"] = float(
            sum(1 for trigger in self.collapse_triggers if trigger.severity == "hard")
        )
        return values

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "calibration": _plain(self.calibration),
            "clustering": _plain(self.clustering),
            "collapse_triggers": [trigger.to_dict() for trigger in self.collapse_triggers],
            "collapsed": self.collapsed,
            "confidence_is_not_authority": True,
            "latent": _plain(self.latent),
            "latent_similarity_is_not_equivalence": True,
            "metric_lineage": _plain(self.metric_lineage),
            "prohibited_split_count": self.prohibited_split_count,
            "representation_digest": self.representation_digest,
            "schema_version": self.schema_version,
            "split_identity": self.split_identity,
            "unknown_denominators": list(self.unknown_denominators),
        }
        if include_digest:
            payload["report_digest"] = self.digest
        return payload


def evaluate_collapse_triggers(
    *,
    latent: Mapping[str, Any],
    clustering: Mapping[str, Any],
    calibration: Mapping[str, Any],
    prohibited_split_count: int,
    config: CollapseTriggerConfig,
) -> tuple[CollapseTrigger, ...]:
    """Emit explicit collapse/calibration triggers, including unknown denominators."""

    triggers: list[CollapseTrigger] = []
    spectrum = latent.get("spectrum", {}) if isinstance(latent.get("spectrum"), Mapping) else {}
    neighborhoods = (
        latent.get("false_neighborhoods", {})
        if isinstance(latent.get("false_neighborhoods"), Mapping)
        else {}
    )
    unknown = list(spectrum.get("unknown_denominators") or ())
    unknown.extend(neighborhoods.get("unknown_denominators") or ())
    unknown.extend(calibration.get("unknown_denominators") or ())
    if prohibited_split_count:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_HIDDEN_TEST_SPLIT,
                metric="prohibited_split_count",
                actual=float(prohibited_split_count),
                threshold=0.0,
                severity="hard",
                reason="latent diagnostics may use development/calibration only",
            )
        )
    if "spectrum:centered_matrix_is_zero" in unknown:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_CENTERED_DEGENERACY,
                metric="effective_rank",
                actual=None,
                threshold=config.min_effective_rank,
                severity="hard",
                reason="centered representation matrix is degenerate",
                unknown_denominator=True,
            )
        )
    effective_rank = spectrum.get("effective_rank")
    if effective_rank is None:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_UNKNOWN_DENOMINATOR,
                metric="effective_rank",
                actual=None,
                threshold=config.min_effective_rank,
                severity="hard",
                reason="effective rank denominator is unknown",
                unknown_denominator=True,
            )
        )
    elif float(effective_rank) < config.min_effective_rank:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_LOW_EFFECTIVE_RANK,
                metric="effective_rank",
                actual=float(effective_rank),
                threshold=config.min_effective_rank,
                severity="hard",
                reason="effective rank collapsed below threshold",
            )
        )
    anisotropy = spectrum.get("spectral_anisotropy")
    if anisotropy is not None and float(anisotropy) > config.max_spectral_anisotropy:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_HIGH_ANISOTROPY,
                metric="spectral_anisotropy",
                actual=float(anisotropy),
                threshold=config.max_spectral_anisotropy,
                severity="hard",
                reason="spectral mass is concentrated on one direction",
            )
        )
    latent_use = spectrum.get("latent_use_rate")
    if latent_use is not None and float(latent_use) < config.min_latent_use_rate:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_LOW_LATENT_USE,
                metric="latent_use_rate",
                actual=float(latent_use),
                threshold=config.min_latent_use_rate,
                severity="hard",
                reason="latent was unused for too many records",
            )
        )
    false_rate = neighborhoods.get("false_neighborhood_rate")
    if false_rate is not None and float(false_rate) > config.max_false_neighborhood_rate:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_FALSE_NEIGHBORHOODS,
                metric="false_neighborhood_rate",
                actual=float(false_rate),
                threshold=config.max_false_neighborhood_rate,
                severity="hard",
                reason="nearest neighbors mix families; similarity is not equivalence",
            )
        )
    duplicate = clustering.get("axes", {}).get("duplicate", {}) if isinstance(clustering, Mapping) else {}
    intra = duplicate.get("intra_cosine") if isinstance(duplicate, Mapping) else None
    if intra is not None and float(intra) >= config.max_duplicate_intra_cosine:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_DUPLICATE_MEMORIZATION,
                metric="duplicate_intra_cosine",
                actual=float(intra),
                threshold=config.max_duplicate_intra_cosine,
                severity="hard",
                reason="duplicate groups occupy identical neighborhoods",
            )
        )
    family = clustering.get("axes", {}).get("family", {}) if isinstance(clustering, Mapping) else {}
    balance = family.get("balance_ratio") if isinstance(family, Mapping) else None
    missing = list(clustering.get("missing_families") or ())
    if missing or (balance is not None and float(balance) < config.min_family_balance_ratio):
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_FAMILY_IMBALANCE,
                metric="family_balance_ratio",
                actual=None if balance is None else float(balance),
                threshold=config.min_family_balance_ratio,
                severity="hard",
                reason="family strata are missing or unbalanced",
                unknown_denominator=balance is None,
            )
        )
    ece = calibration.get("expected_calibration_error")
    if ece is None:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_UNKNOWN_DENOMINATOR,
                metric="expected_calibration_error",
                actual=None,
                threshold=config.max_expected_calibration_error,
                severity="diagnostic",
                reason="ECE denominator is unknown",
                unknown_denominator=True,
            )
        )
    elif float(ece) > config.max_expected_calibration_error:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_HIGH_ECE,
                metric="expected_calibration_error",
                actual=float(ece),
                threshold=config.max_expected_calibration_error,
                severity="hard",
                reason="expected calibration error exceeds the diagnostic bound",
            )
        )
    brier = calibration.get("brier_score")
    if brier is not None and float(brier) > config.max_brier_score:
        triggers.append(
            CollapseTrigger(
                trigger_id=TRIGGER_HIGH_BRIER,
                metric="brier_score",
                actual=float(brier),
                threshold=config.max_brier_score,
                severity="hard",
                reason="Brier score exceeds the diagnostic bound",
            )
        )
    return tuple(triggers)


def materialize_latent_diagnostic_report(
    records: Sequence[Any],
    *,
    config: Optional[CollapseTriggerConfig] = None,
    required_families: Sequence[str] = (),
    checkpoint_identity: str = "",
    state_hash: str = "",
    compiler_commit: str = "compiler-independent",
    cache_key: str = "not-cached",
) -> LegalIRLatentDiagnosticReport:
    """Build a content-bound diagnostic/calibration report and collapse triggers."""

    policy = config or CollapseTriggerConfig()
    batch = coerce_latent_records(records)
    prohibited = [item for item in batch if item.split in LATENT_DIAGNOSTIC_PROHIBITED_SPLITS]
    allowed = [
        item
        for item in batch
        if item.split in LATENT_DIAGNOSTIC_ALLOWED_SPLITS
        or item.split not in LATENT_DIAGNOSTIC_PROHIBITED_SPLITS
    ]
    diagnostic_batch = allowed if not prohibited else allowed
    latent = evaluate_latent_diagnostics(diagnostic_batch, neighbor_k=policy.neighbor_k)
    clustering = evaluate_latent_clustering_strata(
        diagnostic_batch,
        required_families=required_families,
        min_balance_ratio=policy.min_family_balance_ratio,
    )
    calibration = evaluate_legal_ir_calibration(
        diagnostic_batch,
        bin_count=policy.reliability_bin_count,
    )
    lineage = build_latent_diagnostic_metric_lineage(
        diagnostic_batch,
        state_hash=state_hash,
        compiler_commit=compiler_commit,
        checkpoint_identity=checkpoint_identity,
        cache_key=cache_key,
        config_payload=policy.to_dict(),
    )
    latent_payload = latent.to_dict()
    clustering_payload = clustering.to_dict()
    calibration_payload = calibration.to_dict()
    triggers = evaluate_collapse_triggers(
        latent=latent_payload,
        clustering=clustering_payload,
        calibration=calibration_payload,
        prohibited_split_count=len(prohibited),
        config=policy,
    )
    unknown = list(latent.spectrum.unknown_denominators)
    unknown.extend(latent.false_neighborhoods.unknown_denominators)
    unknown.extend(calibration.unknown_denominators)
    for axis in clustering.axes.values():
        unknown.extend(axis.unknown_denominators)
    unknown.extend(clustering.ood.unknown_denominators)
    report = LegalIRLatentDiagnosticReport(
        latent=latent_payload,
        clustering=clustering_payload,
        calibration=calibration_payload,
        collapse_triggers=triggers,
        unknown_denominators=tuple(dict.fromkeys(unknown)),
        metric_lineage=lineage.to_dict(),
        representation_digest=representation_content_digest(diagnostic_batch),
        prohibited_split_count=len(prohibited),
    )
    return report


def attach_latent_diagnostics(
    artifact: LegalIREvaluationArtifact,
    report: LegalIRLatentDiagnosticReport,
) -> LegalIREvaluationArtifact:
    """Attach a diagnostic report without mutating the required artifact DAG."""

    if not isinstance(artifact, LegalIREvaluationArtifact):
        raise TypeError("artifact must be LegalIREvaluationArtifact")
    compiler_payload = dict(_plain(artifact.compiler_artifact))
    compiler_payload[LEGAL_IR_LATENT_DIAGNOSTIC_KEY] = report.to_dict()
    compiler_payload[LEGAL_IR_COLLAPSE_TRIGGER_KEY] = [
        trigger.to_dict() for trigger in report.collapse_triggers
    ]
    metadata = dict(_plain(artifact.metadata))
    metadata["latent_diagnostic_digest"] = report.digest
    metadata["collapse_triggered"] = report.collapsed
    metadata["latent_similarity_is_not_equivalence"] = True
    metadata["confidence_is_not_authority"] = True
    metrics = dict(_plain(artifact.metrics))
    metrics.update(report.metric_vector())
    attached = attach_metric_lineage(metrics, _lineage_from_report(report))
    return LegalIREvaluationArtifact(
        key=artifact.key,
        compiler_artifact=compiler_payload,
        embedding=artifact.embedding,
        metrics=attached,
        per_view_metrics=artifact.per_view_metrics,
        metadata=metadata,
        compilation_seconds=artifact.compilation_seconds,
        embedding_seconds=artifact.embedding_seconds,
        metric_seconds=artifact.metric_seconds,
        created_at=artifact.created_at,
    )


def _lineage_from_report(report: LegalIRLatentDiagnosticReport) -> LegalIRMetricLineage:
    return LegalIRMetricLineage.from_mapping(report.metric_lineage)


__all__ = [
    "BASELINE_METRIC_NODE",
    "COMPILATION_NODE",
    "CollapseTrigger",
    "CollapseTriggerConfig",
    "EMBEDDING_NODE",
    "LEGAL_IR_ARTIFACT_CONSUMER_ROLES",
    "LEGAL_IR_ARTIFACT_GRAPH_KEY",
    "LEGAL_IR_COLLAPSE_TRIGGER_KEY",
    "LEGAL_IR_LATENT_DIAGNOSTIC_KEY",
    "LEGAL_IR_LATENT_DIAGNOSTIC_REPORT_SCHEMA_VERSION",
    "LegalIRLatentDiagnosticReport",
    "MAX_EVALUATION_GRAPH_OBLIGATIONS",
    "LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION",
    "LEGAL_IR_ARTIFACT_NODE_KINDS",
    "LEGAL_IR_ARTIFACT_NODE_ORDER",
    "LEGAL_IR_ARTIFACT_NODE_SCHEMA_VERSION",
    "LegalIRArtifactGraphBuildPlan",
    "LegalIRArtifactGraphBundle",
    "LegalIRArtifactGraphError",
    "LegalIRArtifactGraphProvenanceError",
    "LegalIRArtifactGraphStore",
    "LegalIRArtifactNode",
    "NORMALIZATION_NODE",
    "OBLIGATION_NODE",
    "TOKENIZATION_NODE",
    "TRIGGER_CENTERED_DEGENERACY",
    "TRIGGER_DUPLICATE_MEMORIZATION",
    "TRIGGER_FALSE_NEIGHBORHOODS",
    "TRIGGER_FAMILY_IMBALANCE",
    "TRIGGER_HIDDEN_TEST_SPLIT",
    "TRIGGER_HIGH_ANISOTROPY",
    "TRIGGER_HIGH_BRIER",
    "TRIGGER_HIGH_ECE",
    "TRIGGER_LOW_EFFECTIVE_RANK",
    "TRIGGER_LOW_LATENT_USE",
    "TRIGGER_UNKNOWN_DENOMINATOR",
    "VIEW_CONTRACT_NODE",
    "attach_latent_diagnostics",
    "build_legal_ir_artifact_graph_bundle",
    "evaluate_collapse_triggers",
    "legal_ir_evaluation_artifact_from_compilation",
    "materialize_latent_diagnostic_report",
]


def evaluate_reviewed_source_span_producer_artifact(*, binding, rows, split_manifest,
        admission_inputs, exposure_records, compiler_commit, input_profile,
        checkpoint_declarations, permitted_context, retrieved_examples, producer,
        allow_heldout_evaluation=False):
    """Evaluate one opt-in validation callback against replayed reviewed targets.

    Default hparam_selection never relabels heldout/training use. Explicit
    allow_heldout_evaluation requires the consumer's frozen complete-component
    heldout receipt and empty supplied context/retrieval; it does not establish
    external/model exposure exclusion or generalization. Producer
    arguments contain detached id/source_text/context, never reviewed targets.
    Context records are closed {id, content} declarations and must name examples
    authorized for training by the same split owner. That establishes split
    eligibility, not source/licensing/definition authority. Exact target-ID and
    target-subtree screening is limited, not encoded-leak prevention or a process
    sandbox. Profile budgets and checkpoint identities are declarations only.
    No model loading, token-budget enforcement, native proof or corpus authority
    is inferred from a callback or a successful structural comparison.
    Malformed/missing/duplicate producer rows refuse the whole batch; callers
    must preserve that failure rather than drop cases or award partial credit.
    Stored artifacts are historical observations. Generic cache retrieval does
    not replay current admission: any later eligibility use requires another
    canonical reviewed-consumer validation against current review inputs.
    """
    import json
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_consumer_binding import (
        consume_reviewed_source_span_binding_v2,
        validate_reviewed_source_span_consumer_binding_v2,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
        COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA, evaluate_complete_norm_payloads,
    )

    def require(condition, message):
        if not condition:
            raise InvalidEvaluationArtifactError(message)

    def snapshot(value):
        # The generic legacy JSON helper coerces custom objects; this opt-in
        # boundary instead accepts bounded, lossless ordinary JSON only.
        count = 0
        def visit(item, depth=0):
            nonlocal count
            count += 1
            require(depth <= 64 and count <= 1_000_000, "bounded evaluation JSON required")
            if type(item) is dict:
                require(all(type(key) is str for key in item), "ordinary string JSON keys required")
                for child in item.values():
                    visit(child, depth + 1)
            elif type(item) is list:
                for child in item:
                    visit(child, depth + 1)
            else:
                require(item is None or type(item) in (str, int, bool)
                        or type(item) is float and math.isfinite(item), "lossless ordinary JSON required")
        visit(value)
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
        require(len(raw) <= 32 * 1024**2, "evaluation JSON exceeds existing 32MiB comparison bound")
        return json.loads(raw)

    def closed(value, fields, label):
        require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")

    def text(value):
        return type(value) is str and 0 < len(value) <= 512 and not any(c in value for c in "\r\n\0")

    require(callable(producer), "explicit producer callback required")
    require(type(allow_heldout_evaluation) is bool, "explicit boolean heldout opt-in required")
    operation = "heldout_evaluation" if allow_heldout_evaluation else "hparam_selection"
    originals = [rows, split_manifest, exposure_records, input_profile,
                 checkpoint_declarations, permitted_context, retrieved_examples]
    frozen = snapshot(originals)
    row_copy, manifest_copy, exposure_copy, profile, checkpoints, context, retrieval = frozen
    require(type(row_copy) is list and 1 <= len(row_copy) <= 4096, "complete bounded rows required")
    closed(profile, ("profile_id", "max_source_tokens", "max_context_tokens", "max_output_tokens"), "input profile")
    require(text(profile["profile_id"]) and all(type(profile[name]) is int and profile[name] > 0
            for name in ("max_source_tokens", "max_context_tokens", "max_output_tokens")), "declared input profile required")
    closed(checkpoints, ("encoder", "decoder"), "checkpoint declarations")
    for declaration in checkpoints.values():
        closed(declaration, ("id", "sha256"), "checkpoint declaration")
        require(text(declaration["id"]) and type(declaration["sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", declaration["sha256"]) is not None,
                "explicit checkpoint identity and SHA256 declaration required")
    require(text(compiler_commit), "explicit compiler identity declaration required")
    before = validate_reviewed_source_span_consumer_binding_v2(binding, rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
    require(before["operation"] == operation and before["status"] == "ready",
            "ready reviewed binding for the explicit operation required; no relabelling")
    heldout = None
    if allow_heldout_evaluation:
        heldout = snapshot(before.get("heldout_evaluation"))
        require(type(heldout) is dict
                and heldout.get("schema") == "reviewed-single-component-heldout/v1"
                and heldout.get("purpose") == "frozen-single-component-final-scoring/v1"
                and heldout.get("population_scope") == "exact_complete_admitted_component_only"
                and heldout.get("partition") == "holdout"
                and heldout.get("split_manifest_sha256") == before["input_sha256s"]["split_manifest"]
                and type(heldout.get("dependency_group")) is dict
                and type(heldout.get("dependency_group_sha256")) is str
                and re.fullmatch(r"[0-9a-f]{64}", heldout["dependency_group_sha256"]) is not None,
                "replayed complete-component frozen heldout contract required")
        require(context == [], "heldout callback requires empty supplied context")
    identifiers = [row["id"] for row in row_copy]
    require(type(retrieval) is dict and set(retrieval) == set(identifiers), "exact retrieval case population required")
    if allow_heldout_evaluation:
        require(all(records == [] for records in retrieval.values()), "heldout callback requires empty retrieval")
    # Validate all references using the public scorer before any producer call.
    evaluate_complete_norm_payloads([dict(case_id=row["id"], reference=row["canonical_ir"],
        candidate=None, outcome="incomplete") for row in row_copy])
    manifest = splits.LegalIRSplitManifest.from_mapping(manifest_copy)
    target_ids = set(identifiers) | {row["unit_id"] for row in row_copy}
    target_digests = {stable_digest(row["canonical_ir"]) for row in row_copy}
    target_digests.update(stable_digest(row["canonical_ir"]["typed_expression"]) for row in row_copy)

    def screen(value):
        if type(value) is str:
            require(value not in target_ids, "reference target ID in producer context")
        elif type(value) in (dict, list):
            require(stable_digest(value) not in target_digests, "reference target subtree in producer context")
            for child in (list(value) + list(value.values()) if type(value) is dict else value):
                screen(child)

    def context_records(records):
        require(type(records) is list and len(records) <= 4096, "bounded ordered context records required")
        for record in records:
            closed(record, ("id", "content"), "context record")
            require(text(record["id"]) and record["id"] not in target_ids, "non-target context ID required")
            try:
                splits.authorize_legal_ir_split_use(manifest, operation="training",
                                                   items=[{"sample_id": record["id"]}])
            except splits.LegalIRSplitPolicyError as error:
                raise InvalidEvaluationArtifactError(
                    "producer context is not authorized for training") from error
            screen(record)
    context_records(context)
    for records in retrieval.values():
        context_records(records)
    arguments = [dict(id=row["id"], source_text=row["source_text"],
        context=dict(permitted=context, retrieved=retrieval[row["id"]])) for row in row_copy]
    arguments = snapshot(arguments)
    output_holder = {}

    def dispatch(consumed_rows):
        require(stable_digest(snapshot(consumed_rows)) == stable_digest(row_copy), "consumed reference population differs")
        offered = snapshot(arguments)
        started = time.monotonic()
        try:
            output_holder["outputs"] = producer(tuple(offered))
        except Exception as error:
            output_holder["outputs"] = [dict(id=row["id"], outcome="error", candidate=None) for row in row_copy]
            output_holder["exception_type"] = type(error).__name__
        finally:
            output_holder["producer_seconds"] = max(0.0, time.monotonic() - started)
            require(stable_digest(snapshot(offered)) == stable_digest(arguments), "producer mutated its detached arguments")

    # The canonical consumer itself replays admission before dispatching once.
    # Replay again on every callback exit, including a refused output/mutation.
    try:
        consume_reviewed_source_span_binding_v2(binding, rows, split_manifest=split_manifest,
            admission_inputs=admission_inputs, exposure_records=exposure_records, consumer=dispatch)
    finally:
        after = validate_reviewed_source_span_consumer_binding_v2(binding, rows,
            split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
        require(after["operation"] == operation and after["status"] == "ready",
                "reviewed operation admission no longer ready after callback")
        if allow_heldout_evaluation:
            require(stable_digest(snapshot(after.get("heldout_evaluation"))) == stable_digest(heldout),
                    "frozen heldout purpose/split/dependency group changed during callback")
        require(stable_digest(snapshot(originals)) == stable_digest(frozen), "bound source/context/profile inputs changed during callback")
    outputs = snapshot(output_holder["outputs"])
    require(type(outputs) is list and len(outputs) == len(row_copy), "complete ordered producer population required")
    for row, output in zip(row_copy, outputs):
        closed(output, ("id", "outcome", "candidate"), "producer result")
        require(output["id"] == row["id"], "producer IDs/order differ from fixed reference population")
    started = time.monotonic()
    report = evaluate_complete_norm_payloads([dict(case_id=row["id"], reference=row["canonical_ir"],
        candidate=output["candidate"], outcome=output["outcome"]) for row, output in zip(row_copy, outputs)])
    metric_seconds = max(0.0, time.monotonic() - started)
    configuration = dict(profile="reviewed-source-span-producer-validation/v1",
        admission_identity_sha256=before["admission_identity_sha256"],
        declaration_sha256=before["declaration_sha256"], input_sha256s=before["input_sha256s"],
        operation=operation, target_codec=before["target_codec"],
        input_profile=profile, checkpoint_declarations=checkpoints,
        permitted_context=context, retrieved_examples=retrieval,
        producer_arguments_sha256=stable_digest(arguments), producer_outputs_sha256=stable_digest(outputs),
        admission_before_sha256=stable_digest(before), admission_after_sha256=stable_digest(after))
    if allow_heldout_evaluation:
        configuration.update(profile="reviewed-source-span-producer-heldout/v1", heldout_evaluation=heldout)
    # A bare list falls through the legacy object hash; wrap rows explicitly.
    key = LegalIREvaluationCacheKey.for_sample({"rows": row_copy}, compiler_commit=compiler_commit,
        state_hash=stable_digest(checkpoints), metric_schema=COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA,
        configuration=configuration)
    payload = dict(configuration=configuration, reference_population=row_copy,
        producer_arguments=arguments, producer_outputs=outputs, admission_before=before,
        admission_after=after, comparison=report, producer_callback_count=1,
        producer_exception_type=output_holder.get("exception_type"),
        producer_callback_seconds=output_holder["producer_seconds"], comparison_seconds=metric_seconds,
        producer_authenticity_verified=False, loaded_checkpoint_identity_verified=False,
        declared_compiler_identity=compiler_commit, actual_toolchain_identity_verified=False,
        native_proof_verified=False, formal_checks_status="not_performed",
        source_fidelity_proved=False, semantic_equivalence_proved=False, corpus_admitted=False,
        accepted_semantic_count=None,
        compute_and_cost=dict(status="callback_and_comparison_wall_clock_only",
            training_compute=None, model_cpu_compute=None, model_gpu_compute=None,
            inference_tokens=None, total_monetary_cost=None,
            cost_per_correctly_accepted_formalization=None),
        artifact_observation_scope="historical_at_callback_time",
        cache_retrieval_replays_admission=False, current_review_replay_required_for_later_eligibility=True,
        heldout_evaluation=heldout, empty_context_enforced_at_argument_boundary=allow_heldout_evaluation,
        external_training_exposure_verified=False, model_pretraining_exposure_verified=False,
        heldout_generalization_established=False,
        token_budget_enforced=False, context_authority_scope=("empty_supplied_context_at_callback_argument_boundary"
            if allow_heldout_evaluation else "training_split_eligibility_declaration_only"),
        context_screen_scope="exact_target_ID_and_subtree_only_not_encoded_leaks_or_process_sandbox",
        reference_authority_scope="replayed_review_policy_eligibility_not_legal_truth_or_proof")
    return LegalIREvaluationArtifact(key=key,
        compiler_artifact={"reviewed_source_span_producer_evaluation": payload},
        metrics={"complete_norm_payload": report},
        metadata={"profile": configuration["profile"], "content_sha256": stable_digest(payload)},
        metric_seconds=output_holder["producer_seconds"] + metric_seconds)


__all__ += ["evaluate_reviewed_source_span_producer_artifact"]
