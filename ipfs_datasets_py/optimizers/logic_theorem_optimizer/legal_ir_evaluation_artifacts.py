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
        allow_heldout_evaluation=False, reviewed_training_context=None, context_policy_guard=None,
        typed_structure_profile=None, candidate_syntax_profile=None, known_candidate_inputs=None,
        reviewed_training_context_profile=None):
    """Evaluate one opt-in validation callback against replayed reviewed targets.

    Default hparam_selection never relabels heldout/training use. Explicit
    allow_heldout_evaluation requires the consumer's frozen complete-component
    heldout receipt. The source-only purpose requires empty context. The rich
    purpose requires complete, disjoint, revalidated TRAIN examples and an
    explicit live caller policy. Producer
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
    Explicit typed_structure_profile adds canonical AST formula-wire/signature
    checks and a distinct cache identity; it never grants native proof or legal
    authority. The default structural-comparison report remains unchanged.
    Explicit candidate_syntax_profile requires separately supplied known facts
    for every case. The selected canonical candidate-v2/v3 owner checks all nine fields and
    exact declared source/context/selection identity; unsupported references and
    outputs remain visible. Known facts never enter producer arguments and are
    never inferred from targets. Equality does not authenticate these declarations
    or establish legal meaning, training eligibility or proof.
    Explicit reviewed_training_context_profile selects the V4 aggregate context
    route over complete V3 endpoint components. This does not upgrade the heldout
    purpose or grant model/context permission: present TRAIN reviews, the exact
    union population and the existing independent context policy are replayed.
    Stored artifacts are historical observations. Generic cache retrieval does
    not replay current admission: any later eligibility use requires another
    canonical reviewed-consumer validation against current review inputs.
    """
    import json
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_consumer_binding import (
        REVIEWED_HELDOUT_CONTEXT_PURPOSE, REVIEWED_HELDOUT_PURPOSE, REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE,
        _reviewed_binding_dispatch, _reviewed_binding_version,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
        COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA, evaluate_complete_norm_payloads,
        CANONICAL_TYPED_STRUCTURE_PROFILE, COMPLETE_NORM_TYPED_STRUCTURE_METRICS_SCHEMA,
        evaluate_complete_norm_typed_structure,
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

    require(typed_structure_profile is None or type(typed_structure_profile) is str
            and typed_structure_profile == CANONICAL_TYPED_STRUCTURE_PROFILE,
            "explicit canonical typed-structure profile required")
    candidate_owner = None
    if candidate_syntax_profile is not None:
        from ...logic.autoformal import legal_norm_content_adjudication_v1 as candidate_owner
        candidate_profiles = (candidate_owner.CANDIDATE_SYNTAX_PROFILE_V2, candidate_owner.CANDIDATE_SYNTAX_PROFILE_V3)
        require(type(candidate_syntax_profile) is str and candidate_syntax_profile in candidate_profiles,
                "explicit complete-candidate syntax profile required")
    require((candidate_syntax_profile is None) == (known_candidate_inputs is None),
            "complete-candidate profile and independent known inputs required together")
    known_frozen = snapshot(known_candidate_inputs) if candidate_owner is not None else None

    def candidate_audit(examples):
        from .legal_ir_semantic_metrics import evaluate_complete_norm_candidate_syntax
        return evaluate_complete_norm_candidate_syntax(examples,
            known_candidate_inputs=known_frozen, candidate_syntax_profile=candidate_syntax_profile)

    require(callable(producer), "explicit producer callback required")
    require(type(allow_heldout_evaluation) is bool, "explicit boolean heldout opt-in required")
    operation = "heldout_evaluation" if allow_heldout_evaluation else "hparam_selection"
    rich_heldout = reviewed_training_context is not None
    require((rich_heldout and allow_heldout_evaluation and callable(context_policy_guard))
            or (not rich_heldout and context_policy_guard is None),
            "explicit heldout TRAIN context and live context policy required together")
    aggregate_rich = reviewed_training_context_profile is not None
    if aggregate_rich:
        from . import legal_structured_retrieval as structured_context
        require(type(reviewed_training_context_profile) is str
                and reviewed_training_context_profile == structured_context.AGGREGATE_CONTEXT_V4_PROFILE
                and rich_heldout, "explicit supported aggregate reviewed TRAIN context profile required")
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
    validate_binding, consume_binding = _reviewed_binding_dispatch(binding)
    admission_version = _reviewed_binding_version(binding)
    before = validate_binding(binding, rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
    require(before["operation"] == operation and before["status"] == "ready",
            "ready reviewed binding for the explicit operation required; no relabelling")
    heldout = None
    if allow_heldout_evaluation:
        heldout = snapshot(before.get("heldout_evaluation"))
        purpose = ((REVIEWED_HELDOUT_CONTEXT_PURPOSE if admission_version == "v2"
                    else REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE) if rich_heldout else REVIEWED_HELDOUT_PURPOSE)
        require(admission_version != "v3" or not rich_heldout
                or type(heldout) is dict and heldout.get("purpose") == purpose,
                "V3 rich TRAIN context requires its explicit frozen heldout contract")
        require(type(heldout) is dict
                and heldout.get("schema") == "reviewed-single-component-heldout/v1"
                and heldout.get("purpose") == purpose
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
    if allow_heldout_evaluation and not rich_heldout:
        require(all(records == [] for records in retrieval.values()), "heldout callback requires empty retrieval")
    # Validate all references using the public scorer before any producer call.
    evaluate_complete_norm_payloads([dict(case_id=row["id"], reference=row["canonical_ir"],
        candidate=None, outcome="incomplete") for row in row_copy])
    if typed_structure_profile is not None:
        evaluate_complete_norm_typed_structure([dict(case_id=row["id"], reference=row["canonical_ir"],
            candidate=None, outcome="incomplete") for row in row_copy])
    if candidate_owner is not None:
        candidate_audit([dict(case_id=row["id"], reference=row["canonical_ir"],
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
            if not rich_heldout:
                screen(record)
    context_records(context)
    for records in retrieval.values():
        context_records(records)

    def replay_rich_context():
        from . import legal_span_consumer_binding as consumer
        from . import legal_structured_retrieval as structured

        inputs = reviewed_training_context
        if aggregate_rich:
            require(admission_version == "v3", "V4 aggregate context requires existing V3 heldout endpoint admission")
            closed(inputs, ("schema", "components", "split_manifest", "query_rows", "retrieval_rows"),
                   "V4 aggregate TRAIN context inputs")
            require(snapshot(inputs["query_rows"]) == [{"id": row["id"], "source_text": row["source_text"]}
                    for row in row_copy] and snapshot(inputs["split_manifest"]) == manifest_copy,
                    "aggregate TRAIN context must bind exact heldout sources and common manifest")
            payload = structured.consume_reviewed_contexts_v4(**inputs,
                expected_query_rows_sha256=structured.reviewed_context_inputs_sha256(inputs["query_rows"]),
                expected_retrieval_rows_sha256=structured.reviewed_context_inputs_sha256(inputs["retrieval_rows"]),
                consumer=lambda complete: complete, heldout_evaluation=heldout)
            require(retrieval == {row["id"]: [{"id": example["id"], "content": example}
                    for example in row["examples"]] for row in payload["rows"]},
                    "offered examples differ from complete aggregate TRAIN context")
            return {"profile": reviewed_training_context_profile,
                "endpoint_context_profile": heldout["inference_context_profile"],
                "heldout_dependency_group_sha256": payload["heldout_dependency_group_sha256"],
                "training_dependency_manifest_sha256": payload["training_dependency_manifest_sha256"],
                "training_admission_inputs_sha256": payload["training_admission_inputs_sha256"],
                "context_payload_sha256": structured.reviewed_context_inputs_sha256(payload),
                "retrieved_example_ids": sorted({record["id"] for records in retrieval.values() for record in records})}
        closed(inputs, ("binding", "training_rows", "split_manifest", "admission_inputs",
                       "exposure_records", "query_rows", "retrieval_rows"), "reviewed TRAIN context inputs")
        require(snapshot(inputs["query_rows"]) == [{"id": row["id"], "source_text": row["source_text"]}
                for row in row_copy] and snapshot(inputs["split_manifest"]) == manifest_copy,
                "reviewed TRAIN context must bind the exact heldout source and common manifest")
        payload = structured._consume_reviewed_contexts(**inputs,
            expected_query_rows_sha256=structured.reviewed_context_inputs_sha256(inputs["query_rows"]),
            expected_retrieval_rows_sha256=structured.reviewed_context_inputs_sha256(inputs["retrieval_rows"]),
            consumer=lambda complete: complete, heldout_evaluation=heldout, _admission_version=admission_version)
        require(retrieval == {row["id"]: [{"id": example["id"], "content": example}
                for example in row["examples"]] for row in payload["rows"]},
                "offered heldout examples differ from complete reviewed TRAIN retrieval")
        return {"profile": heldout["inference_context_profile"],
            "heldout_dependency_group_sha256": payload["heldout_dependency_group_sha256"],
            "training_dependency_manifest_sha256": payload["training_dependency_manifest_sha256"],
            "training_admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(inputs["admission_inputs"]),
            "context_payload_sha256": structured.reviewed_context_inputs_sha256(payload),
            "retrieved_example_ids": sorted({record["id"] for records in retrieval.values() for record in records})}

    rich_context_receipt = None
    if rich_heldout:
        from .legal_structured_retrieval import _screen_reviewed_heldout_context

        rich_context_receipt = replay_rich_context()
        _screen_reviewed_heldout_context(list(retrieval.values()), heldout_evaluation=heldout, reference_rows=row_copy)
        require(context_policy_guard(snapshot(rich_context_receipt)) is None,
                "trusted context policy must return None or raise its original denial")
        require(replay_rich_context() == rich_context_receipt, "reviewed TRAIN context changed during context policy")
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
        # Capture the actual returned observation before any later consumer or
        # policy callback can mutate a producer-owned list or nested payload.
        # JSON/shape failures keep their existing exception semantics; only
        # exceptions from producer itself become complete error populations.
        output_holder["outputs"] = snapshot(output_holder["outputs"])

    def recheck_exit_evidence():
        after = validate_binding(binding, rows,
            split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
        require(after["operation"] == operation and after["status"] == "ready",
                "reviewed operation admission no longer ready after callback")
        if allow_heldout_evaluation:
            require(stable_digest(snapshot(after.get("heldout_evaluation"))) == stable_digest(heldout),
                    "frozen heldout purpose/split/dependency group changed during callback")
        if rich_heldout:
            require(replay_rich_context() == rich_context_receipt, "reviewed TRAIN context changed during callback")
        require(stable_digest(snapshot(originals)) == stable_digest(frozen), "bound source/context/profile inputs changed during callback")
        if candidate_owner is not None:
            require(stable_digest(snapshot(known_candidate_inputs)) == stable_digest(known_frozen),
                    "independent candidate facts changed during callback")
        return after

    # The canonical consumer replays admission around dispatch. Recheck the
    # independent live context policy on exit as well, including error paths.
    # Its last callback can mutate inputs, so all evidence fences run after it.
    try:
        consume_binding(binding, rows, split_manifest=split_manifest,
            admission_inputs=admission_inputs, exposure_records=exposure_records, consumer=dispatch)
    finally:
        after = recheck_exit_evidence()
        if rich_heldout:
            policy_failure = None
            try:
                require(context_policy_guard(snapshot(rich_context_receipt)) is None,
                        "trusted context policy must return None or raise its original denial")
            except BaseException as error:
                policy_failure = error
            try:
                after = recheck_exit_evidence()
            except BaseException as fence_failure:
                if policy_failure is not None:
                    # Preserve the caller's original denial, while retaining
                    # any failed post-policy fence as its explicit cause.
                    raise policy_failure from fence_failure
                raise
            if policy_failure is not None:
                raise policy_failure
    outputs = snapshot(output_holder["outputs"])
    require(type(outputs) is list and len(outputs) == len(row_copy), "complete ordered producer population required")
    for row, output in zip(row_copy, outputs):
        closed(output, ("id", "outcome", "candidate"), "producer result")
        require(output["id"] == row["id"], "producer IDs/order differ from fixed reference population")
    started = time.monotonic()
    report = evaluate_complete_norm_payloads([dict(case_id=row["id"], reference=row["canonical_ir"],
        candidate=output["candidate"], outcome=output["outcome"]) for row, output in zip(row_copy, outputs)])
    typed_report = None
    if typed_structure_profile is not None:
        typed_report = evaluate_complete_norm_typed_structure([dict(case_id=row["id"], reference=row["canonical_ir"],
            candidate=output["candidate"], outcome=output["outcome"]) for row, output in zip(row_copy, outputs)])
    candidate_report = None
    if candidate_owner is not None:
        candidate_report = candidate_audit([dict(case_id=row["id"], reference=row["canonical_ir"],
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
    if rich_heldout:
        configuration.update(profile="reviewed-source-span-producer-heldout-rich-TRAIN/v1",
                             rich_training_context=rich_context_receipt)
    if aggregate_rich:
        configuration.update(profile="reviewed-source-span-producer-heldout-aggregate-TRAIN/v4",
                             reviewed_training_context_profile=reviewed_training_context_profile)
    if typed_report is not None:
        configuration["typed_structure_profile"] = typed_structure_profile
    if candidate_report is not None:
        configuration.update(candidate_syntax_profile=candidate_syntax_profile,
                             known_candidate_inputs_sha256=stable_digest(known_frozen))
    metric_schema = COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA
    if typed_report is not None:
        metric_schema += "+" + COMPLETE_NORM_TYPED_STRUCTURE_METRICS_SCHEMA
    if candidate_report is not None:
        metric_schema += "+" + candidate_report["schema"]
    # A bare list falls through the legacy object hash; wrap rows explicitly.
    key = LegalIREvaluationCacheKey.for_sample({"rows": row_copy}, compiler_commit=compiler_commit,
        state_hash=stable_digest(checkpoints), metric_schema=metric_schema,
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
        heldout_evaluation=heldout, empty_context_enforced_at_argument_boundary=allow_heldout_evaluation and not rich_heldout,
        external_training_exposure_verified=False, model_pretraining_exposure_verified=False,
        heldout_generalization_established=False,
        token_budget_enforced=False, context_authority_scope=("replayed_reviewed_TRAIN_examples_with_caller_context_policy"
            if rich_heldout else "empty_supplied_context_at_callback_argument_boundary"
            if allow_heldout_evaluation else "training_split_eligibility_declaration_only"),
        context_screen_scope="exact_target_ID_and_subtree_only_not_encoded_leaks_or_process_sandbox",
        reference_authority_scope="replayed_review_policy_eligibility_not_legal_truth_or_proof")
    metrics = {"complete_norm_payload": report}
    if typed_report is not None:
        payload["typed_structure_comparison"] = typed_report
        payload["formal_checks_status"] = "canonical_typed_structure_only_no_native_proof"
        metrics["canonical_typed_structure"] = typed_report
    if candidate_report is not None:
        payload["candidate_syntax_comparison"] = candidate_report
        payload["candidate_syntax_known_inputs"] = known_frozen
        payload["formal_checks_status"] = ("canonical_typed_and_complete_candidate_syntax_only_no_native_proof"
            if typed_report is not None else "complete_candidate_syntax_only_no_native_proof")
        metrics["complete_candidate_syntax"] = candidate_report
    return LegalIREvaluationArtifact(key=key,
        compiler_artifact={"reviewed_source_span_producer_evaluation": payload},
        metrics=metrics,
        metadata={"profile": configuration["profile"], "content_sha256": stable_digest(payload)},
        metric_seconds=output_holder["producer_seconds"] + metric_seconds)


__all__ += ["evaluate_reviewed_source_span_producer_artifact"]


def compare_reviewed_source_span_retention(before, after, *, expected_before_sha256, expected_after_sha256, cache_source_epoch_profile=None):
    """Compare two pinned source-only heldout observations on one frozen panel.

    The expected digests use stable_digest(artifact.to_dict()). Scores are
    recomputed from each saved producer output against the identical reviewed
    reference. This is a structural retention measurement under declared
    checkpoint identities. The normal source-producer route also replays its
    observed input commitments: only checkpoint artifacts and their derived
    profile ID may vary. Generic callbacks require the same literal profile.
    Digest-omitted observations also replay strict saved-text assembly through
    the pure input owner. This does not replay current admission, reopen assets
    or load a model.
    """
    from hashlib import sha256
    from .legal_ir_semantic_metrics import (
        COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA, evaluate_complete_norm_payloads,
    )
    from .legal_span_consumer_binding import (REVIEWED_HELDOUT_EXPOSURE, REVIEWED_HELDOUT_PURPOSE,
        REVIEWED_SCHEMA, REVIEWED_PROFILE, REVIEWED_V3_SCHEMA, REVIEWED_V3_PROFILE)

    def require(condition, message):
        if not condition:
            raise InvalidEvaluationArtifactError(message)

    def capture(artifact, expected):
        require(type(artifact) is LegalIREvaluationArtifact, "reviewed retention requires evaluation artifacts")
        offered = artifact.to_dict()
        require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
                and stable_digest(offered) == expected, "independent retention artifact commitment differs")
        payload = offered["compiler_artifact"].get("reviewed_source_span_producer_evaluation")
        require(type(payload) is dict and type(payload.get("configuration")) is dict
                and offered["metadata"].get("content_sha256") == stable_digest(payload),
                "complete reviewed producer evaluation artifact required")
        config = payload["configuration"]
        require(set(config) == {"profile", "admission_identity_sha256", "declaration_sha256", "input_sha256s",
                "operation", "target_codec", "input_profile", "checkpoint_declarations", "permitted_context",
                "retrieved_examples", "producer_arguments_sha256", "producer_outputs_sha256",
                "admission_before_sha256", "admission_after_sha256", "heldout_evaluation"},
                "closed source-only retention configuration required")
        heldout = config.get("heldout_evaluation")
        require(config.get("profile") == "reviewed-source-span-producer-heldout/v1"
                and config.get("operation") == "heldout_evaluation"
                and type(heldout) is dict and heldout.get("schema") == "reviewed-single-component-heldout/v1"
                and heldout.get("purpose") == REVIEWED_HELDOUT_PURPOSE
                and heldout.get("partition") == "holdout" and heldout == payload.get("heldout_evaluation")
                and heldout.get("inference_context_profile") == "declared_source_only_empty_retrieval_context"
                and type(heldout.get("dependency_group")) is dict
                and heldout.get("dependency_group_sha256") == stable_digest(heldout.get("dependency_group"))
                and heldout.get("population_scope") == "exact_complete_admitted_component_only",
                "retention requires an exact source-only frozen heldout component")
        references = payload.get("reference_population")
        require(type(references) is list and 0 < len(references) <= 4096
                and all(type(row) is dict and set(row) == {"id", "unit_id", "source_text", "canonical_ir"}
                        and all(type(row[field]) is str and bool(row[field])
                                for field in ("id", "unit_id", "source_text")) for row in references)
                and len({row["id"] for row in references}) == len(references),
                "complete ordered reviewed retention references required")
        source_units = heldout["dependency_group"].get("source_units")
        require(type(source_units) is list and len(source_units) == len(references)
                and all(type(unit) is dict and unit.get("id") == row["id"]
                        and unit.get("unit_id") == row["unit_id"]
                        for unit, row in zip(source_units, references, strict=True))
                and len({row["unit_id"] for row in references}) == len(references)
                and heldout["dependency_group"].get("declaration_sha256") == config["declaration_sha256"]
                and type(config["input_sha256s"]) is dict
                and config["input_sha256s"].get("rows") == stable_digest(references)
                and heldout.get("split_manifest_sha256") == config["input_sha256s"].get("split_manifest"),
                "retention references differ from the complete admitted dependency component")
        profile = config["input_profile"]
        require(type(profile) is dict
                and set(profile) == {"profile_id", "max_source_tokens", "max_context_tokens", "max_output_tokens"}
                and type(profile["profile_id"]) is str and 0 < len(profile["profile_id"]) <= 512
                and all(type(profile[field]) is int and profile[field] > 0 for field in
                        ("max_source_tokens", "max_context_tokens", "max_output_tokens")),
                "complete declared retention token budgets required")
        require(config.get("permitted_context") == []
                and config.get("retrieved_examples") == {row["id"]: [] for row in references}
                and heldout.get("training_example_ids") == heldout.get("retrieved_example_ids") == []
                and payload.get("empty_context_enforced_at_argument_boundary") is True
                and payload.get("producer_arguments") == [{"id": row["id"], "source_text": row["source_text"],
                    "context": {"permitted": [], "retrieved": []}} for row in references],
                "retention requires identical source-only arguments and empty retrieval/context")
        checkpoints = config.get("checkpoint_declarations")
        require(type(checkpoints) is dict and set(checkpoints) == {"encoder", "decoder"}
                and all(type(item) is dict and set(item) == {"id", "sha256"}
                        and type(item["id"]) is str and bool(item["id"])
                        and type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                        for item in checkpoints.values()),
                "complete declared retention checkpoint identities required")
        return offered, payload, config

    previous, prior_payload, prior_config = capture(before, expected_before_sha256)
    current, next_payload, next_config = capture(after, expected_after_sha256)

    def normal_source_observation(offered, payload, config):
        metadata = offered["metadata"]
        contracts = {
            "reviewed-decoder-source-producer/v1:": (
                "reviewed-decoder-source-producer-observation/v1", "reviewed-decoder-source-producer-policy/v1",
                REVIEWED_SCHEMA, REVIEWED_PROFILE, None),
            "reviewed-decoder-source-producer/v2:": (
                "reviewed-decoder-source-producer-observation/v2", "reviewed-decoder-source-producer-policy/v2",
                REVIEWED_V3_SCHEMA, REVIEWED_V3_PROFILE, "complete-reviewed-mixed-sort-norm-admission/v3"),
            "reviewed-decoder-profiled-producer/v1:": (
                "reviewed-decoder-source-producer-observation/v3", "reviewed-decoder-source-producer-policy/v3",
                REVIEWED_V3_SCHEMA, REVIEWED_V3_PROFILE, "complete-reviewed-mixed-sort-norm-admission/v3"),
            "reviewed-decoder-qwen2-profiled-producer/v1:": (
                "reviewed-decoder-source-producer-observation/v4", "reviewed-decoder-source-producer-policy/v4",
                REVIEWED_V3_SCHEMA, REVIEWED_V3_PROFILE, "complete-reviewed-mixed-sort-norm-admission/v3"),
            "reviewed-decoder-digest-omitted-producer/v1:": (
                "reviewed-decoder-digest-omitted-source-producer-observation/v1",
                "reviewed-decoder-digest-omitted-source-producer-policy/v1",
                REVIEWED_V3_SCHEMA, REVIEWED_V3_PROFILE, "complete-reviewed-mixed-sort-norm-admission/v3"),
        }
        observation = metadata.get("source_generation_observation")
        expected = metadata.get("source_generation_input_commitment_sha256")
        selected = [(prefix, contract) for prefix, contract in contracts.items()
                    if config["input_profile"]["profile_id"].startswith(prefix)]
        if observation is None and expected is None and not selected:
            return None
        require(len(selected) == 1, "normal retention requires a supported explicit source-producer profile")
        prefix, (observation_schema, policy_schema, consumer_schema, consumer_profile, admission_profile) = selected[0]
        require(type(observation) is dict
                and observation.get("schema") == observation_schema
                and type(observation.get("calls")) is int and observation["calls"] == 1
                and observation.get("loaded_checkpoint_identity_scope")
                    == "exact supplied pair equals already-loaded backend at entry and exit only"
                and all(observation.get(field) is False for field in ("training_or_restore_performed",
                    "resource_authority_granted", "pretrained_quality_verified", "process_sandbox")),
                "normal retention requires the complete observed source generation")
        commitment = observation.get("input_commitment")
        fields = {"schema", "backend_identity", "assets", "model_checkpoint", "optimizer_checkpoint",
            "source_contexts_sha256", "admission_inputs_sha256", "max_source_tokens", "max_output_tokens",
            "operation", "training_requested", "restore_requested", "source_sha256", "exposure_sha256",
            "supplied_context_supported"}
        if admission_profile is not None:
            fields.add("admission_profile")
        digest_omitted_generation = prefix == "reviewed-decoder-digest-omitted-producer/v1:"
        qwen2_generation = digest_omitted_generation or prefix == "reviewed-decoder-qwen2-profiled-producer/v1:"
        profiled_generation = qwen2_generation or prefix == "reviewed-decoder-profiled-producer/v1:"
        if profiled_generation:
            fields.add("generation_policy")
        if qwen2_generation:
            fields.add("runtime_profile")
        if digest_omitted_generation:
            fields.add("output_derivation")
        require((admission_profile is None and "admission_profile" not in observation
                 or admission_profile is not None and observation.get("admission_profile") == admission_profile)
                and all(type(payload.get(field)) is dict
                    and payload[field].get("schema") == consumer_schema
                    and payload[field].get("profile") == consumer_profile
                    for field in ("admission_before", "admission_after")),
                "normal retention source-producer admission domain differs")
        require(type(commitment) is dict and set(commitment) == fields
                and commitment.get("schema") == policy_schema
                and (admission_profile is None or commitment.get("admission_profile") == admission_profile)
                and expected == observation.get("input_commitment_sha256") == stable_digest(commitment)
                and observation.get("input_profile_id") == config["input_profile"]["profile_id"] == prefix + expected,
                "normal retention source-generation commitment or derived profile differs")
        if profiled_generation:
            # Metadata-only replay of the closed producer-policy contract. Do
            # not import numerical/runtime owners in this saved-artifact path.
            generation = commitment["generation_policy"]
            generation_fields = {"schema", "generation_profile", "conditioning_profile", "max_generation_seconds"}
            if qwen2_generation:
                generation_fields.add("context_budget_profile")
            if digest_omitted_generation:
                generation_fields.add("target_codec")
            require(type(generation) is dict and set(generation) == generation_fields
                    and type(generation["schema"]) is str
                    and generation["schema"] == ("reviewed-decoder-digest-omitted-generation-policy/v1" if digest_omitted_generation
                                                else "reviewed-decoder-generation-policy/v2" if qwen2_generation
                                                else "reviewed-decoder-generation-policy/v1")
                    and type(generation["generation_profile"]) is str
                    and generation["generation_profile"] == ("builtin-qwen2-dynamic-kv/v1" if qwen2_generation
                                                            else "builtin-llama-dynamic-kv/v1")
                    and type(generation["conditioning_profile"]) is str
                    and generation["conditioning_profile"] == ("qwen2-chatml-digest-omitted-legal-ir/v1" if digest_omitted_generation
                                                              else "qwen2-chatml-complete-legal-ir/v1" if qwen2_generation
                                                              else "chatml-complete-legal-ir/v1")
                    and (not digest_omitted_generation or type(generation["target_codec"]) is str
                         and generation["target_codec"] == "complete-reviewed-norm-digest-omitted-json/v1")
                    and (not qwen2_generation or type(commitment["runtime_profile"]) is str
                         and commitment["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
                         and type(generation["context_budget_profile"]) is str
                         and generation["context_budget_profile"] == "qwen2-full-context-8192/v1"),
                    "normal retention profiled generation policy differs")
            seconds = generation["max_generation_seconds"]
            try:
                finite_positive = type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0
            except OverflowError:
                finite_positive = False
            require(finite_positive, "normal retention profiled generation policy differs")
        if digest_omitted_generation:
            derivation = commitment["output_derivation"]
            require(type(derivation) is dict and set(derivation) == {
                        "schema", "target_codec", "only_computed_field", "other_default_filling"}
                    and type(derivation["schema"]) is str
                    and derivation["schema"] == "reviewed-digest-omitted-output-assembly/v1"
                    and type(derivation["target_codec"]) is str
                    and derivation["target_codec"] == "complete-reviewed-norm-digest-omitted-json/v1"
                    and type(derivation["only_computed_field"]) is str
                    and derivation["only_computed_field"] == "typed_expression.content_digest"
                    and derivation["other_default_filling"] is False,
                    "normal retention digest-omitted assembly declaration differs")
        profile = config["input_profile"]
        identity = commitment["backend_identity"]
        require(commitment["operation"] == config["operation"]
                and commitment["training_requested"] is commitment["restore_requested"] is False
                and commitment["supplied_context_supported"] == "empty_permitted_and_retrieved_only"
                and commitment["max_source_tokens"] == profile["max_source_tokens"]
                and commitment["max_output_tokens"] == profile["max_output_tokens"]
                and profile["max_context_tokens"] == 1
                and commitment["exposure_sha256"] == config["input_sha256s"]["exposure"]
                and all(commitment["admission_inputs_sha256"] == payload[field].get("admission_inputs_sha256")
                        for field in ("admission_before", "admission_after"))
                and type(identity) is dict and set(identity) == {"backend_id", "implementation_sha256",
                    "checkpoint_format", "target_codec", "source_conditioned", "pretrained"}
                and identity["backend_id"] == config["checkpoint_declarations"]["decoder"]["id"]
                and identity["source_conditioned"] is True and type(identity["pretrained"]) is bool
                and identity["target_codec"] == ("complete-reviewed-norm-digest-omitted-json/v1" if digest_omitted_generation
                                                 else "complete-reviewed-norm-json/v2"),
                "normal retention producer policy differs from evaluator inputs")
        if digest_omitted_generation:
            require(type(identity["checkpoint_format"]) is str
                    and identity["checkpoint_format"] == "torch-weights-only-digest-omitted-reviewed-state-pair/v1"
                    and type(identity["backend_id"]) is str
                    and re.fullmatch(r"torch-digest-omitted-reviewed-decoder/v1:[0-9a-f]{64}", identity["backend_id"])
                        is not None,
                    "normal retention digest-omitted checkpoint identity differs")
        code = commitment["source_sha256"]
        require(type(code) is dict and set(code) == {"worker", "inputs", "consumer", "admission", "splits"}
                and all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                        for value in [*code.values(), identity["implementation_sha256"],
                                      commitment["source_contexts_sha256"], commitment["admission_inputs_sha256"]])
                and identity["implementation_sha256"] == code["worker"],
                "normal retention requires exact producer code and source-context commitments")

        def artifact_reference(value):
            return type(value) is dict and set(value) == {"path", "sha256", "bytes"} \
                and type(value["path"]) is str and bool(value["path"]) \
                and type(value["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None \
                and type(value["bytes"]) is int and value["bytes"] > 0

        pair = {key: commitment[key] for key in ("model_checkpoint", "optimizer_checkpoint")}
        assets = commitment["assets"]
        require(all(artifact_reference(value) for value in pair.values())
                and pair["model_checkpoint"]["path"] != pair["optimizer_checkpoint"]["path"]
                and pair["model_checkpoint"]["sha256"] == config["checkpoint_declarations"]["decoder"]["sha256"]
                and type(assets) is list and 1 <= len(assets) <= 64 and all(artifact_reference(value) for value in assets)
                and len({value["path"] for value in assets}) == len(assets),
                "normal retention requires the exact declared checkpoint pair and assets")
        normalized_assets = []
        for asset in assets:
            aliases = [key for key, value in pair.items() if asset["path"] == value["path"]]
            require(not aliases or asset == pair[aliases[0]], "normal retention asset conflicts with checkpoint identity")
            normalized_assets.append({"checkpoint_role": aliases[0]} if aliases else asset)
        preflight = observation.get("factory_preflight")
        call = observation.get("last_call")
        require(type(preflight) is dict and set(preflight) == {"reviewed_binding_ready",
                    "already_loaded_pair_match", "independent_context_matches_admitted_facts"}
                and all(value is True for value in preflight.values())
                and type(call) is dict and call.get("entry_pair_match") is call.get("exit_pair_match") is True
                and "closeout_exception_type" not in call,
                "normal retention requires observed matched-pair entry and exit")
        outputs = payload.get("producer_outputs")
        require(type(outputs) is list and len(outputs) == len(payload["reference_population"])
                and all(type(output) is dict and set(output) == {"id", "outcome", "candidate"}
                        and output["id"] == row["id"] for row, output in
                        zip(payload["reference_population"], outputs, strict=True)),
                "normal retention requires every ordered producer output")
        if call.get("completed") is True:
            raw = call.get("raw_generation_outputs")
            require(call.get("exception_type") is None and payload.get("producer_exception_type") is None
                    and call.get("producer_outputs") == outputs and type(raw) is list
                    and len(raw) == len(payload["reference_population"])
                    and all(type(item) is dict and set(item) == {"id", "unit_id", "outcome", "candidate",
                                "generated_token_ids", "generated_text", "reason"}
                            and item["unit_id"] == row["unit_id"]
                            and {key: item[key] for key in ("id", "outcome", "candidate")} == output
                            for item, row, output in zip(raw, payload["reference_population"], outputs, strict=True)),
                    "normal retention outputs differ from observed generation")
            if digest_omitted_generation:
                # Replay the producer's exact row commitments without importing
                # numerical owners or interpreting EOS/text as legal meaning.
                derivations = call.get("output_derivation")
                require(type(derivations) is list and len(derivations) == len(raw),
                        "normal retention digest-omitted derivation population differs")
                for item, output, derivation in zip(raw, outputs, derivations, strict=True):
                    text = item["generated_text"]
                    require(text is None or type(text) is str,
                            "normal retention digest-omitted raw text must retain null or string")
                    text_sha = None if text is None else sha256(text.encode("utf-8")).hexdigest()
                    complete = output["outcome"] == "complete"
                    candidate_sha = None
                    if complete:
                        from ipfs_datasets_py.logic.autoformal.training_cycle_inputs import (
                            _reviewed_wire, assemble_reviewed_decoder_digest_omitted_target,
                        )
                        try:
                            candidate_sha = sha256(_reviewed_wire(output["candidate"])).hexdigest()
                        except (ValueError, TypeError, KeyError, RecursionError):
                            require(False, "normal retention digest-omitted complete candidate wire refused")
                    require(type(derivation) is dict and set(derivation) == {
                                "id", "raw_model_text_sha256", "assembled_full_target_sha256", "outcome",
                                "computed_field", "other_fields_repaired"}
                            and derivation["id"] == item["id"]
                            and derivation["outcome"] == output["outcome"]
                            and derivation["raw_model_text_sha256"] == text_sha
                            and derivation["assembled_full_target_sha256"] == candidate_sha
                            and derivation["computed_field"] == "typed_expression.content_digest"
                            and derivation["other_fields_repaired"] is False,
                            "normal retention digest-omitted row derivation differs")
                    if complete:
                        require(type(text) is str,
                                "normal retention digest-omitted complete output requires raw text")
                        try:
                            assembled = assemble_reviewed_decoder_digest_omitted_target(text,
                                target_codec="complete-reviewed-norm-digest-omitted-json/v1")
                        except (ValueError, TypeError, KeyError, RecursionError):
                            require(False, "normal retention digest-omitted complete raw wire refused strict assembly")
                        require(stable_digest(assembled) == stable_digest(output["candidate"]),
                                "normal retention digest-omitted candidate differs from strict raw assembly")
        else:
            require(call.get("completed") is False and type(call.get("exception_type")) is str
                    and call["exception_type"] == payload.get("producer_exception_type")
                    and call.get("producer_outputs") is None and call.get("raw_generation_outputs") is None
                    and all(output.get("outcome") == "error" and output.get("candidate") is None for output in outputs),
                    "normal retention failed invocation must preserve every error case")
            if digest_omitted_generation:
                require("output_derivation" not in call,
                        "normal retention digest-omitted failed invocation cannot invent row derivations")
        receipt = call.get("input_receipt")
        if receipt is not None:
            rows = payload["reference_population"]
            require(type(receipt) is dict and receipt.get("schema") == "reviewed-decoder-generation-input-receipt/v1"
                    and receipt.get("profile") == "source-only-reviewed-decoder-generation-inputs/v1"
                    and receipt.get("source_arguments_sha256") == call.get("source_arguments_sha256")
                        == config["producer_arguments_sha256"]
                    and receipt.get("prepared_records_sha256") == call.get("source_records_sha256")
                    and receipt.get("source_contexts_sha256") == commitment["source_contexts_sha256"]
                    and receipt.get("max_source_tokens") == profile["max_source_tokens"]
                    and receipt.get("record_count") == len(rows)
                    and type(receipt.get("tokenizer_contract")) is dict
                    and type(receipt.get("row_commitments")) is list and len(receipt["row_commitments"]) == len(rows)
                    and all(type(observed) is dict and observed.get("id") == row["id"]
                            and observed.get("unit_id") == row["unit_id"]
                            and observed.get("source_text_sha256") == sha256(row["source_text"].encode("utf-8")).hexdigest()
                            for observed, row in zip(receipt["row_commitments"], rows, strict=True)),
                    "normal retention input receipt differs from source generation commitments")
        else:
            require(call.get("completed") is False, "normal retention completed generation requires its input receipt")
        normalized = {key: value for key, value in commitment.items() if key not in pair and key != "assets"}
        normalized["assets"] = normalized_assets
        return {"fixed_commitment": normalized, "input_receipt": receipt, "checkpoint_pair": pair,
                "input_commitment_sha256": expected}

    cache_profile_evidence = None
    cache_projected_commitments = None
    prior_generation = normal_source_observation(previous, prior_payload, prior_config)
    next_generation = normal_source_observation(current, next_payload, next_config)
    require((prior_generation is None) == (next_generation is None), "retention producer routes differ")
    if cache_source_epoch_profile is not None:
        require(prior_generation is not None and next_generation is not None,
                "cache retention profile requires actual normal digest source observations")
        cache_profile_evidence, cache_projected_commitments = _reviewed_digest_cache_retention_profile(
            cache_source_epoch_profile, (prior_generation, next_generation))
    if prior_generation is not None:
        require(stable_digest(prior_generation["fixed_commitment"] if cache_projected_commitments is None else cache_projected_commitments[0]) == stable_digest(next_generation["fixed_commitment"] if cache_projected_commitments is None else cache_projected_commitments[1])
                and (prior_generation["input_receipt"] is None or next_generation["input_receipt"] is None
                     or stable_digest(prior_generation["input_receipt"]) == stable_digest(next_generation["input_receipt"])),
                "normal retention observations differ in frozen producer inputs or tokenized source")
    # The producer output and decoder identity are the only variable inputs.
    # Compare all other configuration fields, including admission observations,
    # rather than silently accepting future unbound fields.
    variable_fields = {"checkpoint_declarations", "producer_outputs_sha256"}
    def fixed_configuration(config):
        fixed = {key: value for key, value in config.items() if key not in variable_fields}
        if prior_generation is not None:
            fixed["input_profile"] = {key: value for key, value in config["input_profile"].items() if key != "profile_id"}
        return fixed
    require(stable_digest(fixed_configuration(prior_config)) == stable_digest(fixed_configuration(next_config))
            and prior_config["checkpoint_declarations"]["encoder"] == next_config["checkpoint_declarations"]["encoder"]
            and stable_digest(prior_payload["reference_population"]) == stable_digest(next_payload["reference_population"])
            and stable_digest(prior_payload["producer_arguments"]) == stable_digest(next_payload["producer_arguments"])
            and before.key.compiler_commit == after.key.compiler_commit,
            "retention observations differ in frozen source, split, dependencies, context, compiler, encoder or budget")

    def rescore(artifact, offered, payload, config):
        references = payload["reference_population"]
        outputs = payload.get("producer_outputs")
        require(type(outputs) is list and len(outputs) == len(references)
                and all(type(output) is dict and set(output) == {"id", "outcome", "candidate"}
                        and output["id"] == row["id"] for row, output in zip(references, outputs, strict=True)),
                "retention requires a complete ordered output for every frozen case")
        for field in ("producer_arguments", "producer_outputs", "admission_before", "admission_after"):
            require(field in payload and config.get(field + "_sha256") == stable_digest(payload[field]),
                    "retention producer or admission commitment differs")
        for field in ("admission_before", "admission_after"):
            admission = payload[field]
            require(type(admission) is dict and admission.get("status") == "ready"
                    and admission.get("semantic_use_eligible") is True
                    and admission.get("semantic_admission_replayed") is True
                    and admission.get("operation") == "heldout_evaluation"
                    and admission.get("heldout_evaluation") == config["heldout_evaluation"]
                    and admission.get("row_count") == admission.get("ready_row_count") == len(references)
                    and admission.get("blocked_row_count") == admission.get("rows_discarded") == 0
                    and admission.get("blockers") == []
                    and all(admission.get(key) == config[key] for key in
                            ("admission_identity_sha256", "declaration_sha256", "input_sha256s", "target_codec")),
                    "retention artifact differs from its observed heldout admission")
            observed_rows = admission.get("rows")
            source_units = config["heldout_evaluation"]["dependency_group"]["source_units"]
            require(type(observed_rows) is list and len(observed_rows) == len(references)
                    and all(type(observed) is dict and observed.get("row_index") == index
                            and observed.get("id") == row["id"] and observed.get("unit_id") == row["unit_id"]
                            and observed.get("status") == "ready" and observed.get("blockers") == []
                            and observed.get("occurrence_cid") == unit.get("occurrence_cid")
                            and observed.get("source_text_sha256") == sha256(row["source_text"].encode("utf-8")).hexdigest()
                            and observed.get("canonical_ir_sha256") == stable_digest(row["canonical_ir"])
                            and type(observed.get("exposure")) is dict
                            and all(observed["exposure"].get(key) == observed[key] for key in
                                    ("id", "source_text_sha256", "canonical_ir_sha256"))
                            and observed["exposure"].get("target_exposure") == REVIEWED_HELDOUT_EXPOSURE
                            for index, (observed, row, unit) in enumerate(zip(observed_rows, references,
                                                                           source_units, strict=True))),
                    "retention references differ from observed reviewed admission rows")
        require(payload.get("declared_compiler_identity") == artifact.key.compiler_commit
                and artifact.key == LegalIREvaluationCacheKey.for_sample({"rows": references},
                    compiler_commit=artifact.key.compiler_commit,
                    state_hash=stable_digest(config["checkpoint_declarations"]),
                    metric_schema=COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA, configuration=config),
                "retention evaluation cache key differs from its complete observation")
        report = evaluate_complete_norm_payloads([dict(case_id=row["id"], reference=row["canonical_ir"],
            candidate=output["candidate"], outcome=output["outcome"])
            for row, output in zip(references, outputs, strict=True)])
        require(report == payload.get("comparison") == offered["metrics"].get("complete_norm_payload"),
                "stored retention scores differ from complete rescoring")
        return report

    prior_scores = rescore(before, previous, prior_payload, prior_config)
    next_scores = rescore(after, current, next_payload, next_config)
    labels = {(1, 1): "retained", (1, 0): "lost", (0, 1): "gained", (0, 0): "still_incorrect"}
    counts = dict.fromkeys(labels.values(), 0)
    cases = []
    for left, right in zip(prior_scores["cases"], next_scores["cases"], strict=True):
        status = labels[left["scores"]["full_nine_payload_exact"], right["scores"]["full_nine_payload_exact"]]
        counts[status] += 1
        cases.append({"id": left["case_id"], "before_outcome": left["outcome"],
                      "after_outcome": right["outcome"], "status": status})
    baseline_exact = counts["retained"] + counts["lost"]
    result = {"schema": "reviewed-source-span-retention/v1", "before_artifact_sha256": expected_before_sha256,
        "after_artifact_sha256": expected_after_sha256, "reference_population_sha256": before.key.sample_hash,
        "split_manifest_sha256": prior_config["heldout_evaluation"]["split_manifest_sha256"],
        "dependency_group_sha256": prior_config["heldout_evaluation"]["dependency_group_sha256"],
        "before_decoder": prior_config["checkpoint_declarations"]["decoder"],
        "after_decoder": next_config["checkpoint_declarations"]["decoder"],
        "denominator": len(cases), "baseline_exact": baseline_exact,
        "after_exact": counts["retained"] + counts["gained"], "counts": counts, "cases": cases,
        "retention_rate": counts["retained"] / baseline_exact if baseline_exact else None,
        "before_outcome_counts": prior_scores["outcome_counts"], "after_outcome_counts": next_scores["outcome_counts"],
        "before_complete_norm_scores": prior_scores, "after_complete_norm_scores": next_scores,
        "producer_route": "normal_source_producer" if prior_generation is not None else "generic_callback",
        "before_source_generation": prior_generation, "after_source_generation": next_generation,
        "scope": "paired_full_nine_payload_exactness_on_one_declared_frozen_heldout_component",
        "current_admission_replayed": False, "loaded_checkpoint_identity_verified": False,
        "heldout_generalization_established": False, "proof_authority": False}
    if cache_profile_evidence is not None:
        result["cache_source_epoch_profile"] = cache_profile_evidence
    return result


__all__ += ["compare_reviewed_source_span_retention"]


REVIEWED_DIGEST_CACHE_RETENTION_PROFILE = "reviewed-digest-cache-source-retention-profile/v1"


def _reviewed_retention_metadata_json(reference, *, limit, budget):
    """Read only bounded saved JSON metadata; never load numerical/runtime owners."""
    import hashlib
    import json
    import os
    import stat
    from pathlib import Path

    def need(value, message):
        if not value:
            raise InvalidEvaluationArtifactError(message)

    need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
         and type(reference["path"]) is str and 0 < len(reference["path"]) <= 4096
         and type(reference["bytes"]) is int and 0 < reference["bytes"] <= limit
         and type(reference["sha256"]) is str
         and re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is not None,
         "bounded exact retention metadata reference required")
    path = Path(reference["path"])
    need(path.is_absolute() and ".." not in path.parts,
         "ordinary absolute retention metadata path required")
    budget[0] += reference["bytes"]
    need(budget[0] <= 64 * 1024 ** 2, "retention metadata aggregate byte cap exceeded")
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")
    stamp = lambda info: tuple(getattr(info, key) for key in fields)
    directories = {}
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode), "ordinary retention metadata ancestry required")
        directories[str(parent)] = (info.st_dev, info.st_ino, info.st_mode)
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
         and before.st_uid == os.getuid() and before.st_size == reference["bytes"],
         "ordinary single-link owned retention metadata required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        opened = os.fstat(descriptor)
        need(stamp(before) == stamp(opened), "retention metadata changed at open")
        raw = bytearray()
        while True:
            chunk = os.read(descriptor, min(1024 ** 2, reference["bytes"] + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            need(len(raw) <= reference["bytes"], "retention metadata grew during read")
        ended = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    need(stamp(before) == stamp(opened) == stamp(ended) == stamp(after)
         and len(raw) == reference["bytes"] and hashlib.sha256(raw).hexdigest() == reference["sha256"],
         "retention metadata bytes or full identity changed")
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and directories[str(parent)] == (info.st_dev, info.st_ino, info.st_mode),
             "retention metadata ancestry changed")

    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, "duplicate retention metadata JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        raise InvalidEvaluationArtifactError("nonfinite retention metadata JSON value")

    try:
        value = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InvalidEvaluationArtifactError("ordinary retention metadata JSON required") from error
    need(type(value) is dict, "retention metadata JSON object required")
    return value, bytes(raw), {key: str(getattr(after, key)) for key in fields}


def _reviewed_digest_cache_retention_profile_metadata(profile, generations):
    """Prove only a closed saved-metadata identity projection, never numeric equality."""
    import copy
    import hashlib
    import json

    def need(value, message):
        if not value:
            raise InvalidEvaluationArtifactError(message)

    def wire(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    same = lambda left, right: wire(left) == wire(right)
    source_names = {"worker", "inputs", "consumer", "admission", "splits"}
    scope = "declared-current-at-migration-cohort-not-historical-execution-attestation/v1"
    codec = "complete-reviewed-norm-digest-omitted-json/v1"
    roles = ("pristine0", "TRAIN3")
    role_fields = {"role", "current_configuration_artifact", "migration_receipt_artifact",
        "derivative_candidate_artifact", "original_parent_manifest_artifact", "compatibility_contract_artifact"}
    parent_fields = {"schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
        "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
        "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed"}
    receipt_fields = {"schema", "profile", "old_checkpoint_manifest", "old_configuration_artifact",
        "old_pipeline_artifact", "current_configuration_artifact", "source_contract_artifact", "current_pipeline_artifact",
        "derivative_model_checkpoint", "derivative_optimizer_checkpoint", "target_job_spec", "migrated_training_binding",
        "original_progress", "pipeline_proof", "source_projection_sha256", "dependency_scope",
        "historical_dependency_execution_requalified", "model_Adam_steps_RNG_and_progress_preserved", "qualified",
        "promotion_performed", "legal_meaning_verified", "convergence_proved", "corpus_admitted",
        "new_checkpoint_lineage_id", "new_base_version_id", "origin_kind", "training_resume_eligible"}
    contract_fields = {"schema", "profile", "old_checkpoint_manifest_sha256", "old_configuration_sha256",
        "current_configuration_sha256", "old_tokenizer_pipeline_sha256", "old_source_sha256", "current_source_sha256",
        "old_source_artifacts", "current_source_artifacts", "dependency_snapshot_artifact",
        "old_training_binding_artifact", "dependency_association_scope"}
    need(type(profile) is dict and set(profile) == {"schema", "arms"}
         and profile["schema"] == REVIEWED_DIGEST_CACHE_RETENTION_PROFILE
         and type(profile["arms"]) is list and len(profile["arms"]) == 2
         and all(type(arm) is dict and set(arm) == role_fields and arm["role"] == role
                 for arm, role in zip(profile["arms"], roles, strict=True)),
         "explicit ordered pristine0/TRAIN3 retention metadata roles required")
    need(type(generations) is tuple and len(generations) == 2
         and all(type(item) is dict and set(item) == {"fixed_commitment", "input_receipt", "checkpoint_pair", "input_commitment_sha256"}
                 for item in generations), "normal digest source generation required for cache retention profile")
    budget = [0]
    evidence = []
    projected = []
    configurations = []
    old_populations = []
    pipeline_proofs = []
    for role, arm, generation in zip(roles, profile["arms"], generations, strict=True):
        commitment = generation["fixed_commitment"]
        identity = commitment.get("backend_identity")
        need(commitment.get("schema") == "reviewed-decoder-digest-omitted-source-producer-policy/v1"
             and type(identity) is dict and set(identity) == {"backend_id", "implementation_sha256", "checkpoint_format", "target_codec", "source_conditioned", "pretrained"}
             and identity["checkpoint_format"] == "torch-weights-only-digest-omitted-reviewed-state-pair/v1"
             and identity["target_codec"] == codec and identity["source_conditioned"] is True
             and type(identity["pretrained"]) is bool,
             "cache retention profile is exclusive to maintained digest-omitted observations")
        values = {}
        observations = {}
        for name in sorted(role_fields - {"role"}):
            value, raw, full9 = _reviewed_retention_metadata_json(arm[name], limit=4 * 1024 ** 2, budget=budget)
            values[name] = (value, raw)
            observations[name] = {"artifact": dict(arm[name]), "full9": full9}
        configuration, configuration_raw = values["current_configuration_artifact"]
        receipt, _ = values["migration_receipt_artifact"]
        candidate, _ = values["derivative_candidate_artifact"]
        parent, _ = values["original_parent_manifest_artifact"]
        contract, _ = values["compatibility_contract_artifact"]
        migration_profile = "digest-omitted-" + ("PRISTINE0" if role == "pristine0" else "TRAIN3") + "-to-pure-tokenizer-caches/v1"
        origin = "pristine0" if role == "pristine0" else "trained3"
        progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0} if role == "pristine0" else {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 3}
        need(set(contract) == contract_fields and contract["schema"] == "reviewed-digest-omitted-cache-source-compatibility/v2"
             and contract["profile"] == migration_profile and contract["dependency_association_scope"] == scope,
             "closed current-cohort compatibility metadata required")
        source, old_source = contract["current_source_sha256"], contract["old_source_sha256"]
        need(type(source) is type(old_source) is dict and set(source) == set(old_source) == source_names
             and all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                     for mapping in (source, old_source) for value in mapping.values())
             and same(source, commitment.get("source_sha256")) and identity["implementation_sha256"] == source["worker"]
             and all(source[key] == old_source[key] for key in ("consumer", "admission", "splits")),
             "cache retention source implementation or common producers differ")
        need(set(parent) == parent_fields and parent["schema"] == "reviewed-digest-omitted-decoder-checkpoint/v1"
             and parent["qualified"] is parent["promotion_performed"] is False
             and same(parent["producer_pins"], old_source) and same(parent["progress"], progress)
             and all(type(value) is int for value in parent["progress"].values())
             and type(parent["batch_size"]) is int and parent["batch_size"] == 1
             and type(parent["seed"]) is int and parent["seed"] == 1729,
             "exact original zero/three-step digest parent metadata required")
        need(parent["backend_identity"] == {"backend_id": "torch-digest-omitted-reviewed-decoder/v1:" + contract["old_configuration_sha256"],
                 "implementation_sha256": old_source["worker"], "checkpoint_format": "torch-weights-only-digest-omitted-reviewed-state-pair/v1",
                 "target_codec": codec, "source_conditioned": True, "pretrained": identity["pretrained"]},
             "original parent backend identity differs from declared original configuration/Source")
        need(contract["old_checkpoint_manifest_sha256"] == arm["original_parent_manifest_artifact"]["sha256"]
             and contract["current_configuration_sha256"] == arm["current_configuration_artifact"]["sha256"],
             "compatibility parent/configuration references differ")
        population, population_raw, population_full9 = _reviewed_retention_metadata_json(contract["old_training_binding_artifact"], limit=4 * 1024 ** 2, budget=budget)
        observations["old_training_binding_artifact"] = {"artifact": dict(contract["old_training_binding_artifact"]), "full9": population_full9}
        need(population.get("schema") == "reviewed-decoder-digest-omitted-training-input-receipt/v1"
             and population.get("target_codec") == codec and type(population.get("record_count")) is int
             and population["record_count"] == 3,
             "exact same-objective original/prospective T3 population required")
        if role == "pristine0":
            need(parent["training_binding"] is None and parent["parent_checkpoint_sha256"] is None,
                 "pristine parent must have no historical updates or training population")
        else:
            need(same(parent["training_binding"], population), "TRAIN3 parent population differs from authenticated binding")
        version = digest(wire({"profile": migration_profile, "old_manifest": arm["original_parent_manifest_artifact"]["sha256"],
            "current_source": source, "population": contract["old_training_binding_artifact"]["sha256"]}))
        marker = {"schema": "reviewed-digest-cache-source-marker/v1", "profile": migration_profile,
            "origin_checkpoint_sha256": arm["original_parent_manifest_artifact"]["sha256"], "lineage_sha256": version}
        need(configuration_raw == wire(configuration) and configuration.get("schema") == "torch-complete-reviewed-decoder-configuration/v4"
             and configuration.get("cache_source_epoch_marker") == marker
             and configuration.get("device") == "cpu" and configuration.get("model_profile") == "builtin-qwen2-bfloat16/v1"
             and configuration.get("architecture") == "causal_lm" and configuration.get("target_codec") == codec
             and configuration.get("training_conditioning_profile") == "qwen2-chatml-digest-omitted-legal-ir/v1"
             and type(configuration.get("pretrained_declaration")) is bool
             and identity == {"backend_id": "torch-digest-omitted-reviewed-decoder/v1:" + digest(configuration_raw),
                 "implementation_sha256": source["worker"], "checkpoint_format": "torch-weights-only-digest-omitted-reviewed-state-pair/v1",
                 "target_codec": codec, "source_conditioned": True, "pretrained": configuration["pretrained_declaration"]},
             "backend identity must derive from exact complete canonical marked configuration")
        need(set(receipt) == receipt_fields and receipt["schema"] == "reviewed-digest-omitted-cache-source-migration/v1"
             and receipt["profile"] == migration_profile and receipt["origin_kind"] == origin
             and same(receipt["original_progress"], progress) and receipt["training_resume_eligible"] is True
             and receipt["model_Adam_steps_RNG_and_progress_preserved"] is True
             and all(receipt[name] is False for name in ("qualified", "promotion_performed", "legal_meaning_verified", "convergence_proved", "corpus_admitted", "historical_dependency_execution_requalified"))
             and receipt["old_checkpoint_manifest"] == arm["original_parent_manifest_artifact"]
             and receipt["current_configuration_artifact"] == arm["current_configuration_artifact"]
             and receipt["source_contract_artifact"] == arm["compatibility_contract_artifact"]
             and receipt["old_configuration_artifact"]["sha256"] == contract["old_configuration_sha256"]
             and receipt["old_pipeline_artifact"]["sha256"] == contract["old_tokenizer_pipeline_sha256"]
             and receipt["dependency_scope"] == scope,
             "migration receipt metadata, origin, references or nonauthorizing scope differ")
        spec = receipt["target_job_spec"]
        need(type(spec) is dict and spec.get("schema_version") == "reviewed-mixed-digest-omitted-decoder-job/v1"
             and spec.get("parent_checkpoint_artifact") == arm["original_parent_manifest_artifact"]
             and spec.get("base_model_checkpoint") == parent["model_state"] and spec.get("base_optimizer_checkpoint") == parent["optimizer_state"]
             and spec.get("checkpoint_lineage_id") == parent["checkpoint_lineage_id"] and spec.get("base_version_id") == parent["base_version_id"]
             and same(spec.get("backend_identity"), identity) and same(spec.get("expected_source_sha256"), source)
             and spec.get("expected_admission_inputs_sha256") == population.get("admission_inputs_sha256")
             and type(spec.get("stage_artifact")) is dict and spec["stage_artifact"].get("sha256") == population.get("stage_artifact_sha256"),
             "receipt target spec differs from original pair/current identity/T3 binding")
        migrated = receipt["migrated_training_binding"]
        need(type(migrated) is dict and set(migrated) == set(population)
             and migrated.get("schema") == population["schema"] and migrated.get("target_codec") == codec,
             "complete migrated same-objective binding required")
        need(all(same(population[key], migrated[key]) for key in set(population) - {"implementation", "tokenizer_contract"}),
             "migrated population/context/token/admission values changed")
        old_implementation, implementation = population.get("implementation"), migrated.get("implementation")
        need(type(old_implementation) is type(implementation) is dict,
             "complete old/current input implementation maps required")
        old_keys = [key for key, value in old_implementation.items() if value == old_source["inputs"]]
        new_keys = [key for key, value in implementation.items() if value == source["inputs"]]
        need(len(old_keys) == len(new_keys) == 1
             and same({key: value for key, value in old_implementation.items() if key != old_keys[0]},
                      {key: value for key, value in implementation.items() if key != new_keys[0]}),
             "unrelated input dependency or exact maintained input change differs")
        proof = receipt["pipeline_proof"]
        need(type(proof) is dict and set(proof) == {"old_contract", "current_contract", "old_binding", "current_binding", "method_proofs"}
             and same(proof["old_contract"], population["tokenizer_contract"])
             and same(proof["current_contract"], migrated["tokenizer_contract"])
             and same(configuration.get("tokenizer"), migrated["tokenizer_contract"])
             and same(configuration.get("tokenizer_binding"), proof["current_binding"])
             and type(generation["input_receipt"]) is dict
             and same(generation["input_receipt"].get("tokenizer_contract"), configuration["tokenizer"])
             and receipt["current_pipeline_artifact"]["sha256"] == configuration["tokenizer"].get("pipeline_sha256")
             and receipt["current_pipeline_artifact"]["bytes"] == configuration["tokenizer"].get("pipeline_bytes")
             and configuration["tokenizer_binding"].get("configuration_sha256") == "sha256:" + receipt["current_pipeline_artifact"]["sha256"],
             "saved current tokenizer/pipeline/binding commitments differ")
        need(set(candidate) == parent_fields | {"cache_source_epoch_migration", "cache_epoch_parent_checkpoint_artifact"}
             and candidate["schema"] == "reviewed-digest-omitted-cache-source-checkpoint/v1"
             and candidate["cache_source_epoch_migration"] == arm["migration_receipt_artifact"]
             and candidate["cache_epoch_parent_checkpoint_artifact"] == arm["original_parent_manifest_artifact"]
             and candidate["parent_checkpoint_sha256"] == arm["original_parent_manifest_artifact"]["sha256"]
             and candidate["checkpoint_lineage_id"] == receipt["new_checkpoint_lineage_id"] == "digest-cache-source-lineage:" + version
             and candidate["base_version_id"] == receipt["new_base_version_id"] == "digest-cache-source-version:" + version
             and same(candidate["backend_identity"], identity) and same(candidate["producer_pins"], source)
             and candidate["model_state"] == receipt["derivative_model_checkpoint"] == generation["checkpoint_pair"]["model_checkpoint"]
             and candidate["optimizer_state"] == receipt["derivative_optimizer_checkpoint"] == generation["checkpoint_pair"]["optimizer_checkpoint"]
             and same(candidate["training_binding"], migrated) and same(candidate["progress"], progress)
             and all(type(value) is int for value in candidate["progress"].values())
             and candidate["assets"] == parent["assets"] and candidate["batch_size"] == parent["batch_size"]
             and candidate["seed"] == parent["seed"] and candidate["qualified"] is candidate["promotion_performed"] is False
             and candidate["token_budgets"] == {"max_source_tokens": spec.get("max_source_tokens"),
                 "max_target_tokens": spec.get("max_target_tokens"), "tokenizer_contract": migrated["tokenizer_contract"]},
             "derivative candidate pair, ancestry, lineage, progress or binding differs")
        need(parent["token_budgets"] == {"max_source_tokens": spec.get("max_source_tokens"),
            "max_target_tokens": spec.get("max_target_tokens"), "tokenizer_contract": population["tokenizer_contract"]},
            "original complete token budgets differ")
        projected_commitment = copy.deepcopy(commitment)
        del projected_commitment["backend_identity"]["backend_id"]
        projected.append(projected_commitment)
        configurations.append({key: value for key, value in configuration.items() if key != "cache_source_epoch_marker"})
        old_populations.append(population_raw)
        pipeline_proofs.append(proof)
        evidence.append({"role": role, "metadata_artifacts": observations, "actual_backend_identity": copy.deepcopy(identity),
            "proved_configuration_sha256": digest(configuration_raw), "proved_marker": marker,
            "original_progress": progress, "derivative_candidate": dict(arm["derivative_candidate_artifact"]),
            "migration_receipt": dict(arm["migration_receipt_artifact"]), "numeric_pair_bytes_read": False})
    need(same(configurations[0], configurations[1]) and old_populations[0] == old_populations[1]
         and same(pipeline_proofs[0], pipeline_proofs[1]),
         "cache retention arms differ beyond exact derived markers or original shared population/tokenizer proof")
    return ({"schema": REVIEWED_DIGEST_CACHE_RETENTION_PROFILE, "arms": evidence,
        "projection": "remove_only_proved_derived_backend_id_from_comparison_copies",
        "metadata_bytes_authenticated": budget[0], "metadata_only": True,
        "numeric_equality_recomputed": False, "fresh_execution_or_admission_replayed": False,
        "historical_dependency_execution_requalified": False, "loaded_checkpoint_identity_verified": False}, tuple(projected))


def _reviewed_digest_cache_retention_profile(profile, generations):
    try:
        return _reviewed_digest_cache_retention_profile_metadata(profile, generations)
    except InvalidEvaluationArtifactError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise InvalidEvaluationArtifactError("invalid bounded cache retention metadata profile") from error
