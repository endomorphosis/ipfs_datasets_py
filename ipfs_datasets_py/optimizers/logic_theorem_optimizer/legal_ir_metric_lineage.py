"""Lineage and causality checks for LegalIR metric blocks.

Learned LegalIR metrics and deterministic compiler LegalIR metrics measure
different systems.  This module gives both paths a common, source-free lineage
contract so validation can prove that metric movement is attributable to the
right path and that caches are not reused across stale states or paths.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Final, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    sample_content_hash,
    stable_digest,
)


LEGAL_IR_METRIC_LINEAGE_SCHEMA_VERSION: Final = "legal-ir-metric-lineage-v1"
LEARNED_IR_METRIC_PATH: Final = "learned_ir"
DETERMINISTIC_COMPILER_IR_METRIC_PATH: Final = "deterministic_compiler_ir"
VALID_LEGAL_IR_METRIC_PATHS: Final = frozenset(
    {LEARNED_IR_METRIC_PATH, DETERMINISTIC_COMPILER_IR_METRIC_PATH}
)


class LegalIRMetricLineageError(RuntimeError):
    """Base class for metric lineage contract failures."""


class LegalIRMetricInvariantError(LegalIRMetricLineageError):
    """Raised when materially different lineages report invariant metrics."""


class LegalIRMetricCacheReuseError(LegalIRMetricLineageError):
    """Raised when a cached metric block belongs to another lineage."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("metric lineage value contains a non-finite float")
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
                key: item
                for key, item in vars(value).items()
                if not str(key).startswith("_")
            }
        )
    return repr(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _non_empty_hash(value: Any, *, fallback_payload: Any) -> str:
    text = str(value or "").strip()
    return text if text else _digest(fallback_payload)


def _sample_hashes(samples: Optional[Sequence[Any]], fallback: Any) -> tuple[str, ...]:
    if samples:
        return tuple(sample_content_hash(sample) for sample in samples)
    if isinstance(fallback, Mapping):
        values = fallback.get("sample_hashes")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            hashes = tuple(str(value) for value in values if str(value))
            if hashes:
                return hashes
        ids = fallback.get("sample_ids")
        if isinstance(ids, Sequence) and not isinstance(ids, (str, bytes, bytearray)):
            hashes = tuple(_digest({"sample_id": str(value)}) for value in ids if str(value))
            if hashes:
                return hashes
    return (_digest({"sample_fallback": fallback}),)


def _metric_values(
    block: Mapping[str, Any],
    metric_names: Optional[Sequence[str]] = None,
) -> dict[str, float]:
    selected = set(str(name) for name in metric_names or ())
    values: dict[str, float] = {}
    for name, value in block.items():
        if selected and name not in selected:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number):
            values[str(name)] = round(number, 12)
    return values


@dataclass(frozen=True, slots=True)
class LegalIRMetricLineage:
    """Source-free identity for one learned or deterministic metric block."""

    path: str
    sample_hashes: tuple[str, ...]
    state_hash: str
    compiler_commit: str
    metric_schema: str
    target_hash: str
    cache_namespace: str
    cache_key: str
    config_hash: str
    schema_version: str = LEGAL_IR_METRIC_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        path = str(self.path or "").strip()
        if path not in VALID_LEGAL_IR_METRIC_PATHS:
            raise ValueError(f"path must be one of {sorted(VALID_LEGAL_IR_METRIC_PATHS)}")
        sample_hashes = tuple(str(value).strip() for value in self.sample_hashes if str(value).strip())
        if not sample_hashes:
            raise ValueError("sample_hashes must be non-empty")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "sample_hashes", sample_hashes)
        for name in (
            "state_hash",
            "compiler_commit",
            "metric_schema",
            "target_hash",
            "cache_namespace",
            "cache_key",
            "config_hash",
            "schema_version",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            if any(character in value for character in "\r\n\0"):
                raise ValueError(f"{name} is not a valid lineage component")
            object.__setattr__(self, name, value)
        if self.schema_version != LEGAL_IR_METRIC_LINEAGE_SCHEMA_VERSION:
            raise ValueError("metric lineage schema version is stale")

    @property
    def sample_count(self) -> int:
        return len(self.sample_hashes)

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict(include_digest=False))

    def material_identity(self) -> dict[str, Any]:
        """Return dimensions that must invalidate metrics and caches."""

        return {
            "path": self.path,
            "sample_hashes": list(self.sample_hashes),
            "state_hash": self.state_hash,
            "compiler_commit": self.compiler_commit,
            "metric_schema": self.metric_schema,
            "target_hash": self.target_hash,
            "config_hash": self.config_hash,
        }

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "cache_key": self.cache_key,
            "cache_namespace": self.cache_namespace,
            "compiler_commit": self.compiler_commit,
            "config_hash": self.config_hash,
            "metric_schema": self.metric_schema,
            "path": self.path,
            "sample_count": self.sample_count,
            "sample_hashes": list(self.sample_hashes),
            "schema_version": self.schema_version,
            "state_hash": self.state_hash,
            "target_hash": self.target_hash,
        }
        if include_digest:
            payload["lineage_digest"] = self.digest
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LegalIRMetricLineage":
        return cls(
            path=str(payload.get("path") or ""),
            sample_hashes=tuple(str(value) for value in payload.get("sample_hashes", ()) or ()),
            state_hash=str(payload.get("state_hash") or ""),
            compiler_commit=str(payload.get("compiler_commit") or ""),
            metric_schema=str(payload.get("metric_schema") or ""),
            target_hash=str(payload.get("target_hash") or ""),
            cache_namespace=str(payload.get("cache_namespace") or ""),
            cache_key=str(payload.get("cache_key") or ""),
            config_hash=str(payload.get("config_hash") or ""),
            schema_version=str(payload.get("schema_version") or ""),
        )


def metric_lineage_from_block(block: Mapping[str, Any]) -> LegalIRMetricLineage:
    payload = block.get("metric_lineage")
    if not isinstance(payload, Mapping):
        raise LegalIRMetricCacheReuseError("metric block is missing metric_lineage")
    return LegalIRMetricLineage.from_mapping(payload)


def attach_metric_lineage(
    block: Mapping[str, Any],
    lineage: LegalIRMetricLineage,
) -> dict[str, Any]:
    attached = dict(block)
    attached["metric_lineage"] = lineage.to_dict()
    attached["metric_lineage_digest"] = lineage.digest
    attached["metric_lineage_schema_version"] = LEGAL_IR_METRIC_LINEAGE_SCHEMA_VERSION
    return attached


def metric_lineage_matches_block(
    block: Mapping[str, Any],
    expected: LegalIRMetricLineage,
) -> bool:
    try:
        observed = metric_lineage_from_block(block)
    except LegalIRMetricLineageError:
        return False
    return observed.to_dict(include_digest=False) == expected.to_dict(include_digest=False)


def require_cache_lineage(
    block: Mapping[str, Any],
    expected: LegalIRMetricLineage,
) -> None:
    if not metric_lineage_matches_block(block, expected):
        raise LegalIRMetricCacheReuseError(
            "cached LegalIR metric block does not match requested lineage"
        )


def build_learned_ir_metric_lineage(
    evaluation: Any,
    *,
    samples: Optional[Sequence[Any]] = None,
    state_hash: str = "",
    compiler_commit: str = "compiler-independent",
    metric_schema: str = "legal-ir-daemon-metrics-v2",
    target_hash: str = "",
    cache_namespace: str = "learned_ir_metric_block",
    cache_key: str = "not-cached",
    config_hash: str = "",
) -> LegalIRMetricLineage:
    losses = dict(getattr(evaluation, "legal_ir_losses", {}) or {})
    target_distribution = dict(getattr(evaluation, "legal_ir_view_distribution", {}) or {})
    predicted_distribution = dict(
        getattr(evaluation, "legal_ir_predicted_view_distribution", {}) or {}
    )
    decoded_ids = sorted(dict(getattr(evaluation, "decoded_embeddings", {}) or {}))
    state_payload = {
        "decoded_sample_ids": decoded_ids,
        "legal_ir_losses": losses,
        "predicted_view_distribution": predicted_distribution,
    }
    target_payload = {
        "legal_ir_target_count": int(getattr(evaluation, "legal_ir_target_count", 0) or 0),
        "legal_ir_target_hashes": dict(getattr(evaluation, "legal_ir_target_hashes", {}) or {}),
        "target_view_distribution": target_distribution,
    }
    config_payload = {
        "evaluation_type": f"{evaluation.__class__.__module__}.{evaluation.__class__.__qualname__}",
    }
    return LegalIRMetricLineage(
        path=LEARNED_IR_METRIC_PATH,
        sample_hashes=_sample_hashes(samples, {"sample_ids": decoded_ids, "losses": losses}),
        state_hash=_non_empty_hash(state_hash, fallback_payload=state_payload),
        compiler_commit=str(compiler_commit or "compiler-independent"),
        metric_schema=str(metric_schema or "legal-ir-daemon-metrics-v2"),
        target_hash=_non_empty_hash(target_hash, fallback_payload=target_payload),
        cache_namespace=str(cache_namespace or "learned_ir_metric_block"),
        cache_key=str(cache_key or "not-cached"),
        config_hash=_non_empty_hash(config_hash, fallback_payload=config_payload),
    )


def build_compiler_ir_metric_lineage(
    samples: Sequence[Any],
    *,
    codec_identity: Mapping[str, Any],
    state_hash: str,
    compiler_commit: str,
    metric_schema: str,
    target_payload: Mapping[str, Any],
    cache_namespace: str,
    cache_key: str,
    config_payload: Mapping[str, Any],
) -> LegalIRMetricLineage:
    return LegalIRMetricLineage(
        path=DETERMINISTIC_COMPILER_IR_METRIC_PATH,
        sample_hashes=_sample_hashes(samples, {"sample_ids": []}),
        state_hash=str(state_hash or "state-independent"),
        compiler_commit=str(compiler_commit or _digest(codec_identity)),
        metric_schema=str(metric_schema or "legal-ir-daemon-metrics-v2"),
        target_hash=_digest(target_payload),
        cache_namespace=str(cache_namespace or "compiler_ir_metric_block"),
        cache_key=str(cache_key or "not-cached"),
        config_hash=_digest(config_payload),
    )


def material_lineage_delta(
    before: LegalIRMetricLineage | Mapping[str, Any],
    after: LegalIRMetricLineage | Mapping[str, Any],
) -> dict[str, tuple[Any, Any]]:
    left = before if isinstance(before, LegalIRMetricLineage) else metric_lineage_from_block(before)
    right = after if isinstance(after, LegalIRMetricLineage) else metric_lineage_from_block(after)
    delta: dict[str, tuple[Any, Any]] = {}
    left_identity = left.material_identity()
    right_identity = right.material_identity()
    for name in sorted(set(left_identity) | set(right_identity)):
        if left_identity.get(name) != right_identity.get(name):
            delta[name] = (left_identity.get(name), right_identity.get(name))
    return delta


def reject_unexplained_invariant_metrics(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    metric_names: Optional[Sequence[str]] = None,
    explanation_key: str = "metric_invariance_explanation",
) -> None:
    """Fail closed when materially different lineages produce identical metrics."""

    if str(after.get(explanation_key) or before.get(explanation_key) or "").strip():
        return
    if not material_lineage_delta(before, after):
        return
    before_values = _metric_values(before, metric_names)
    after_values = _metric_values(after, metric_names)
    shared = sorted(set(before_values) & set(after_values))
    if not shared:
        return
    invariant = [name for name in shared if before_values[name] == after_values[name]]
    if len(invariant) == len(shared):
        raise LegalIRMetricInvariantError(
            "LegalIR metrics are invariant across materially different lineages: "
            + ", ".join(invariant[:12])
        )


def assert_metric_path_responsiveness(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    expected_path: str,
    moved_metric_names: Sequence[str],
) -> None:
    """Assert that a controlled perturbation moved metrics on one expected path."""

    before_lineage = metric_lineage_from_block(before)
    after_lineage = metric_lineage_from_block(after)
    if before_lineage.path != expected_path or after_lineage.path != expected_path:
        raise LegalIRMetricLineageError("metric perturbation used the wrong path")
    if not material_lineage_delta(before_lineage, after_lineage):
        raise LegalIRMetricLineageError("metric perturbation did not change lineage")
    before_values = _metric_values(before, moved_metric_names)
    after_values = _metric_values(after, moved_metric_names)
    moved = [
        name
        for name in moved_metric_names
        if name in before_values
        and name in after_values
        and before_values[name] != after_values[name]
    ]
    if not moved:
        raise LegalIRMetricInvariantError(
            "controlled perturbation did not move any expected metric"
        )
