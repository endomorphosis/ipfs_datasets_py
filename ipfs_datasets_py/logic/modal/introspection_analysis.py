"""Normalize, cluster, and rank LegalIR introspection disagreements.

This module consumes the compact packets emitted by ``introspection_export``
and raw metric/introspection records from the same pipeline.  It projects noisy
loss names onto owned compiler surfaces, builds canonical semantic signatures,
and ranks recurring clusters by operational impact instead of raw loss alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


INTROSPECTION_ANALYSIS_SCHEMA_VERSION = "legal-ir-introspection-analysis-v1"
INTROSPECTION_ANALYSIS_CONFIG_VERSION = "legal-ir-introspection-analysis-config-v1"

REQUIRED_LEGAL_IR_GAP_FAMILIES: Tuple[str, ...] = (
    "deontic",
    "frame_logic",
    "tdfol",
    "knowledge_graph",
    "event_calculus",
    "temporal",
    "provenance",
    "decompiler",
    "prover",
)

_WORD_RE = re.compile(r"[^a-z0-9]+")
_EPSILON = 1.0e-12


class IntrospectionAnalysisSchemaError(ValueError):
    """Raised when LegalIR introspection analysis data is not schema-valid."""


@dataclass(frozen=True)
class OwnedCompilerSurface:
    """Compiler-owned code surface for a normalized semantic gap family."""

    surface: str
    semantic_family: str
    code_paths: Tuple[str, ...]
    component_prefixes: Tuple[str, ...]
    base_formal_severity: float

    def __post_init__(self) -> None:
        if self.semantic_family not in REQUIRED_LEGAL_IR_GAP_FAMILIES:
            raise IntrospectionAnalysisSchemaError(
                f"unknown LegalIR gap family: {self.semantic_family!r}"
            )
        if not self.surface.strip():
            raise IntrospectionAnalysisSchemaError("compiler surface must not be empty")
        if not self.code_paths:
            raise IntrospectionAnalysisSchemaError("owned compiler surface must include code paths")
        if (
            not isinstance(self.base_formal_severity, (float, int))
            or not math.isfinite(float(self.base_formal_severity))
            or float(self.base_formal_severity) < 0.0
            or float(self.base_formal_severity) > 1.0
        ):
            raise IntrospectionAnalysisSchemaError(
                "base_formal_severity must be between 0 and 1"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_formal_severity": _stable_float(self.base_formal_severity),
            "code_paths": list(self.code_paths),
            "component_prefixes": list(self.component_prefixes),
            "semantic_family": self.semantic_family,
            "surface": self.surface,
        }


OWNED_COMPILER_SURFACES: Dict[str, OwnedCompilerSurface] = {
    "deontic.ir": OwnedCompilerSurface(
        surface="deontic.ir",
        semantic_family="deontic",
        code_paths=(
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
            "ipfs_datasets_py/logic/deontic/ir.py",
        ),
        component_prefixes=("deontic.", "conditional_normative", "normative"),
        base_formal_severity=0.86,
    ),
    "modal.frame_logic": OwnedCompilerSurface(
        surface="modal.frame_logic",
        semantic_family="frame_logic",
        code_paths=(
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/flogic/semantic_normalizer.py",
            "ipfs_datasets_py/logic/bridge/modal_frame_logic.py",
        ),
        component_prefixes=("modal.frame_logic", "frame_logic", "flogic", "frame."),
        base_formal_severity=0.72,
    ),
    "TDFOL.prover": OwnedCompilerSurface(
        surface="TDFOL.prover",
        semantic_family="tdfol",
        code_paths=(
            "ipfs_datasets_py/logic/TDFOL/tdfol_converter.py",
            "ipfs_datasets_py/logic/TDFOL/tdfol_prover.py",
            "ipfs_datasets_py/logic/bridge/fol_tdfol.py",
        ),
        component_prefixes=("TDFOL.", "tdfol", "fol."),
        base_formal_severity=0.9,
    ),
    "knowledge_graphs.neo4j_compat": OwnedCompilerSurface(
        surface="knowledge_graphs.neo4j_compat",
        semantic_family="knowledge_graph",
        code_paths=(
            "ipfs_datasets_py/logic/modal/kg_bridge.py",
            "ipfs_datasets_py/logic/bridge/multiview.py",
        ),
        component_prefixes=("knowledge_graphs.", "knowledge_graph", "neo4j", "kg."),
        base_formal_severity=0.66,
    ),
    "event_calculus.core": OwnedCompilerSurface(
        surface="event_calculus.core",
        semantic_family="event_calculus",
        code_paths=(
            "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
            "ipfs_datasets_py/logic/CEC/native/fluents.py",
            "ipfs_datasets_py/logic/bridge/cec_dcec.py",
        ),
        component_prefixes=("event_calculus", "CEC.event", "cec.event", "fluent"),
        base_formal_severity=0.78,
    ),
    "modal.temporal": OwnedCompilerSurface(
        surface="modal.temporal",
        semantic_family="temporal",
        code_paths=(
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/CEC/native/temporal.py",
            "ipfs_datasets_py/logic/TDFOL/inference_rules/temporal.py",
        ),
        component_prefixes=("temporal", "time.", "deadline", "interval"),
        base_formal_severity=0.76,
    ),
    "modal.source_provenance": OwnedCompilerSurface(
        surface="modal.source_provenance",
        semantic_family="provenance",
        code_paths=(
            "ipfs_datasets_py/logic/modal/compiler.py",
            "ipfs_datasets_py/logic/modal/leanstral.py",
        ),
        component_prefixes=("provenance", "source_span", "source_cid", "span."),
        base_formal_severity=0.82,
    ),
    "modal.ir_decompiler": OwnedCompilerSurface(
        surface="modal.ir_decompiler",
        semantic_family="decompiler",
        code_paths=(
            "ipfs_datasets_py/logic/modal/decompiler.py",
            "ipfs_datasets_py/logic/modal/codec.py",
        ),
        component_prefixes=("modal.ir_decompiler", "decompiler", "decoded", "round_trip"),
        base_formal_severity=0.62,
    ),
    "external_provers.router": OwnedCompilerSurface(
        surface="external_provers.router",
        semantic_family="prover",
        code_paths=(
            "ipfs_datasets_py/logic/external_provers/prover_router.py",
            "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py",
            "ipfs_datasets_py/logic/bridge/external_prover_router.py",
        ),
        component_prefixes=("external_provers.", "prover", "proof", "lean", "z3", "vampire"),
        base_formal_severity=1.0,
    ),
}


@dataclass(frozen=True)
class IntrospectionAnalysisConfig:
    """Ranking weights and version labels for LegalIR gap analysis."""

    heldout_impact_weight: float = 0.36
    recurrence_weight: float = 0.26
    confidence_weight: float = 0.2
    formal_severity_weight: float = 0.18
    residual_gap_weight: float = 0.03
    max_gaps_per_cluster: int = 50
    config_version: str = INTROSPECTION_ANALYSIS_CONFIG_VERSION

    def __post_init__(self) -> None:
        if self.config_version != INTROSPECTION_ANALYSIS_CONFIG_VERSION:
            raise IntrospectionAnalysisSchemaError(
                f"unsupported analysis config_version: {self.config_version}"
            )
        for key in (
            "heldout_impact_weight",
            "recurrence_weight",
            "confidence_weight",
            "formal_severity_weight",
            "residual_gap_weight",
        ):
            value = float(getattr(self, key))
            if not math.isfinite(value) or value < 0.0:
                raise IntrospectionAnalysisSchemaError(f"{key} must be a non-negative finite number")
        if not isinstance(self.max_gaps_per_cluster, int) or self.max_gaps_per_cluster <= 0:
            raise IntrospectionAnalysisSchemaError("max_gaps_per_cluster must be a positive integer")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_version": self.config_version,
            "confidence_weight": _stable_float(self.confidence_weight),
            "formal_severity_weight": _stable_float(self.formal_severity_weight),
            "heldout_impact_weight": _stable_float(self.heldout_impact_weight),
            "max_gaps_per_cluster": int(self.max_gaps_per_cluster),
            "recurrence_weight": _stable_float(self.recurrence_weight),
            "residual_gap_weight": _stable_float(self.residual_gap_weight),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "IntrospectionAnalysisConfig":
        return cls(
            heldout_impact_weight=_float_from(data, "heldout_impact_weight", 0.36),
            recurrence_weight=_float_from(data, "recurrence_weight", 0.26),
            confidence_weight=_float_from(data, "confidence_weight", 0.2),
            formal_severity_weight=_float_from(data, "formal_severity_weight", 0.18),
            residual_gap_weight=_float_from(data, "residual_gap_weight", 0.03),
            max_gaps_per_cluster=int(_float_from(data, "max_gaps_per_cluster", 50.0)),
            config_version=str(data.get("config_version") or ""),
        )


@dataclass(frozen=True)
class NormalizedLegalIRGap:
    """One normalized LegalIR disagreement on an owned compiler surface."""

    evidence_id: str
    sample_id: str
    semantic_family: str
    compiler_surface: str
    metric_name: str
    gap_kind: str
    raw_value: float
    normalized_score: float
    confidence: float
    heldout_impact: float
    formal_severity: float
    semantic_signature: str
    owned_code_paths: Sequence[str]
    target_family: str = ""
    predicted_family: str = ""
    source_key: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = INTROSPECTION_ANALYSIS_SCHEMA_VERSION
    gap_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != INTROSPECTION_ANALYSIS_SCHEMA_VERSION:
            raise IntrospectionAnalysisSchemaError(
                f"unsupported analysis schema_version: {self.schema_version}"
            )
        if self.semantic_family not in REQUIRED_LEGAL_IR_GAP_FAMILIES:
            raise IntrospectionAnalysisSchemaError(
                f"unknown LegalIR gap family: {self.semantic_family!r}"
            )
        if self.compiler_surface not in OWNED_COMPILER_SURFACES:
            raise IntrospectionAnalysisSchemaError(
                f"unknown owned compiler surface: {self.compiler_surface!r}"
            )
        if OWNED_COMPILER_SURFACES[self.compiler_surface].semantic_family != self.semantic_family:
            raise IntrospectionAnalysisSchemaError(
                "compiler surface semantic family does not match normalized gap family"
            )
        for key, value in (
            ("raw_value", self.raw_value),
            ("normalized_score", self.normalized_score),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise IntrospectionAnalysisSchemaError(f"{key} must be finite")
        if float(self.normalized_score) < 0.0:
            raise IntrospectionAnalysisSchemaError("normalized_score must be non-negative")
        for key in ("confidence", "heldout_impact", "formal_severity"):
            _require_probability(key, float(getattr(self, key)))
        if not self.metric_name.strip():
            raise IntrospectionAnalysisSchemaError("metric_name must not be empty")
        if not self.gap_kind.strip():
            raise IntrospectionAnalysisSchemaError("gap_kind must not be empty")
        if not self.semantic_signature.strip():
            raise IntrospectionAnalysisSchemaError("semantic_signature must not be empty")
        if self.gap_id and self.gap_id != self.expected_gap_id():
            raise IntrospectionAnalysisSchemaError("gap_id does not match frozen payload")

    def expected_gap_id(self) -> str:
        return "lir-gap-" + _hash_json(self.to_dict(include_gap_id=False))[:16]

    def to_dict(self, *, include_gap_id: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "compiler_surface": self.compiler_surface,
            "confidence": _stable_float(self.confidence),
            "evidence_id": self.evidence_id,
            "formal_severity": _stable_float(self.formal_severity),
            "gap_kind": self.gap_kind,
            "heldout_impact": _stable_float(self.heldout_impact),
            "metadata": _json_safe_mapping(self.metadata),
            "metric_name": self.metric_name,
            "normalized_score": _stable_float(self.normalized_score),
            "owned_code_paths": list(self.owned_code_paths),
            "predicted_family": self.predicted_family,
            "raw_value": _stable_float(self.raw_value),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "semantic_family": self.semantic_family,
            "semantic_signature": self.semantic_signature,
            "source_key": self.source_key,
            "target_family": self.target_family,
        }
        if include_gap_id:
            payload["gap_id"] = self.gap_id or self.expected_gap_id()
        return payload

    def to_json(self) -> str:
        return _stable_json(self.to_dict())


@dataclass(frozen=True)
class LegalIRGapCluster:
    """Recurring semantic disagreement cluster for one owned compiler surface."""

    semantic_signature: str
    semantic_family: str
    compiler_surface: str
    owned_code_paths: Sequence[str]
    gaps: Sequence[NormalizedLegalIRGap]
    recurrence: int
    heldout_impact: float
    confidence: float
    formal_severity: float
    mean_normalized_score: float
    max_raw_loss: float
    rank_score: float
    ranking_breakdown: Mapping[str, float]
    schema_version: str = INTROSPECTION_ANALYSIS_SCHEMA_VERSION
    cluster_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != INTROSPECTION_ANALYSIS_SCHEMA_VERSION:
            raise IntrospectionAnalysisSchemaError(
                f"unsupported analysis schema_version: {self.schema_version}"
            )
        if self.semantic_family not in REQUIRED_LEGAL_IR_GAP_FAMILIES:
            raise IntrospectionAnalysisSchemaError(
                f"unknown LegalIR gap family: {self.semantic_family!r}"
            )
        if self.compiler_surface not in OWNED_COMPILER_SURFACES:
            raise IntrospectionAnalysisSchemaError(
                f"unknown owned compiler surface: {self.compiler_surface!r}"
            )
        if self.recurrence < len(self.gaps):
            raise IntrospectionAnalysisSchemaError("cluster recurrence cannot be smaller than gap count")
        if self.recurrence <= 0:
            raise IntrospectionAnalysisSchemaError("cluster must include at least one gap")
        for key in ("heldout_impact", "confidence", "formal_severity"):
            _require_probability(key, float(getattr(self, key)))
        for key in ("mean_normalized_score", "max_raw_loss", "rank_score"):
            value = float(getattr(self, key))
            if not math.isfinite(value) or value < 0.0:
                raise IntrospectionAnalysisSchemaError(f"{key} must be non-negative and finite")
        if self.cluster_id and self.cluster_id != self.expected_cluster_id():
            raise IntrospectionAnalysisSchemaError("cluster_id does not match frozen payload")

    @property
    def evidence_ids(self) -> Tuple[str, ...]:
        return tuple(sorted({gap.evidence_id for gap in self.gaps if gap.evidence_id}))

    @property
    def sample_ids(self) -> Tuple[str, ...]:
        return tuple(sorted({gap.sample_id for gap in self.gaps if gap.sample_id}))

    def expected_cluster_id(self) -> str:
        return "lir-cluster-" + _hash_json(
            {
                "compiler_surface": self.compiler_surface,
                "semantic_family": self.semantic_family,
                "semantic_signature": self.semantic_signature,
            }
        )[:16]

    def to_dict(self, *, include_gaps: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "cluster_id": self.cluster_id or self.expected_cluster_id(),
            "compiler_surface": self.compiler_surface,
            "confidence": _stable_float(self.confidence),
            "evidence_ids": list(self.evidence_ids),
            "formal_severity": _stable_float(self.formal_severity),
            "heldout_impact": _stable_float(self.heldout_impact),
            "max_raw_loss": _stable_float(self.max_raw_loss),
            "mean_normalized_score": _stable_float(self.mean_normalized_score),
            "owned_code_paths": list(self.owned_code_paths),
            "rank_score": _stable_float(self.rank_score),
            "ranking_breakdown": {
                key: _stable_float(value)
                for key, value in sorted(dict(self.ranking_breakdown).items())
            },
            "recurrence": self.recurrence,
            "sample_ids": list(self.sample_ids),
            "schema_version": self.schema_version,
            "semantic_family": self.semantic_family,
            "semantic_signature": self.semantic_signature,
        }
        if include_gaps:
            payload["gaps"] = [gap.to_dict() for gap in self.gaps]
        return payload

    def to_json(self) -> str:
        return _stable_json(self.to_dict())


@dataclass(frozen=True)
class LegalIRGapAnalysis:
    """Full deterministic LegalIR gap analysis output."""

    clusters: Sequence[LegalIRGapCluster]
    gaps: Sequence[NormalizedLegalIRGap]
    config: IntrospectionAnalysisConfig = field(default_factory=IntrospectionAnalysisConfig)
    schema_version: str = INTROSPECTION_ANALYSIS_SCHEMA_VERSION
    required_gap_families: Sequence[str] = REQUIRED_LEGAL_IR_GAP_FAMILIES

    def __post_init__(self) -> None:
        if self.schema_version != INTROSPECTION_ANALYSIS_SCHEMA_VERSION:
            raise IntrospectionAnalysisSchemaError(
                f"unsupported analysis schema_version: {self.schema_version}"
            )
        if tuple(self.required_gap_families) != REQUIRED_LEGAL_IR_GAP_FAMILIES:
            raise IntrospectionAnalysisSchemaError("required_gap_families does not match frozen set")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clusters": [cluster.to_dict() for cluster in self.clusters],
            "config": self.config.to_dict(),
            "gap_count": len(self.gaps),
            "gaps": [gap.to_dict() for gap in self.gaps],
            "required_gap_families": list(self.required_gap_families),
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return _stable_json(self.to_dict())


def normalize_legal_ir_gaps(
    record: Mapping[str, Any] | Any,
    *,
    config: Optional[IntrospectionAnalysisConfig] = None,
) -> List[NormalizedLegalIRGap]:
    """Normalize one packet, metric record, or raw introspection mapping into gaps."""

    _ = config or IntrospectionAnalysisConfig()
    root = _object_to_mapping(record)
    if "payload" in root and isinstance(root["payload"], Mapping):
        root = dict(root["payload"])
    evidence_id = _evidence_id(root)
    sample_id = _sample_id(root)
    target_family, predicted_family = _family_context(root)
    context = _AnalysisContext(
        evidence_id=evidence_id,
        sample_id=sample_id,
        target_family=target_family,
        predicted_family=predicted_family,
        root=root,
    )

    rows: List[NormalizedLegalIRGap] = []
    rows.extend(_explicit_gaps(root, context))
    rows.extend(_component_gaps(root, context))
    rows.extend(_per_family_gaps(root, context))
    rows.extend(_learned_view_component_gaps(root, context))
    rows.extend(_compiler_round_trip_gaps(root, context))
    rows.extend(_proof_route_gaps(root, context))
    rows.extend(_metric_record_gaps(root, context))
    rows.extend(_anti_copy_gaps(root, context))
    rows.extend(_synthesis_focus_gaps(root, context))
    rows = _dedupe_gaps(rows)
    return sorted(
        rows,
        key=lambda gap: (
            gap.semantic_family,
            gap.compiler_surface,
            gap.semantic_signature,
            gap.metric_name,
            gap.evidence_id,
            gap.sample_id,
            gap.source_key,
        ),
    )


def cluster_legal_ir_gaps(
    gaps: Iterable[NormalizedLegalIRGap | Mapping[str, Any]],
    *,
    config: Optional[IntrospectionAnalysisConfig] = None,
) -> List[LegalIRGapCluster]:
    """Cluster repeated disagreements by semantic signature and owned surface."""

    analysis_config = config or IntrospectionAnalysisConfig()
    typed_gaps = [
        gap if isinstance(gap, NormalizedLegalIRGap) else _gap_from_mapping(gap)
        for gap in gaps
    ]
    grouped: Dict[Tuple[str, str], List[NormalizedLegalIRGap]] = {}
    for gap in typed_gaps:
        grouped.setdefault((gap.semantic_signature, gap.compiler_surface), []).append(gap)
    max_recurrence = max((len(items) for items in grouped.values()), default=1)

    clusters: List[LegalIRGapCluster] = []
    for (signature, surface), cluster_gaps in sorted(grouped.items()):
        cluster_gaps = sorted(
            cluster_gaps,
            key=lambda gap: (
                gap.evidence_id,
                gap.sample_id,
                gap.metric_name,
                -gap.heldout_impact,
                -gap.formal_severity,
                -gap.confidence,
            ),
        )
        recurrence = len(cluster_gaps)
        recurrence_norm = min(1.0, recurrence / max_recurrence)
        heldout_impact = max(gap.heldout_impact for gap in cluster_gaps)
        confidence = sum(gap.confidence for gap in cluster_gaps) / recurrence
        formal_severity = max(gap.formal_severity for gap in cluster_gaps)
        mean_normalized_score = sum(gap.normalized_score for gap in cluster_gaps) / recurrence
        max_raw_loss = max(abs(gap.raw_value) for gap in cluster_gaps)
        rank_score = (
            analysis_config.heldout_impact_weight * heldout_impact
            + analysis_config.recurrence_weight * recurrence_norm
            + analysis_config.confidence_weight * confidence
            + analysis_config.formal_severity_weight * formal_severity
            + analysis_config.residual_gap_weight * min(1.0, mean_normalized_score)
        )
        breakdown = {
            "confidence": confidence,
            "confidence_weight": analysis_config.confidence_weight,
            "formal_severity": formal_severity,
            "formal_severity_weight": analysis_config.formal_severity_weight,
            "heldout_impact": heldout_impact,
            "heldout_impact_weight": analysis_config.heldout_impact_weight,
            "mean_normalized_score": mean_normalized_score,
            "recurrence": float(recurrence),
            "recurrence_norm": recurrence_norm,
            "recurrence_weight": analysis_config.recurrence_weight,
            "residual_gap_weight": analysis_config.residual_gap_weight,
        }
        selected_gaps = tuple(cluster_gaps[: analysis_config.max_gaps_per_cluster])
        clusters.append(
            LegalIRGapCluster(
                semantic_signature=signature,
                semantic_family=OWNED_COMPILER_SURFACES[surface].semantic_family,
                compiler_surface=surface,
                owned_code_paths=OWNED_COMPILER_SURFACES[surface].code_paths,
                gaps=selected_gaps,
                recurrence=recurrence,
                heldout_impact=heldout_impact,
                confidence=confidence,
                formal_severity=formal_severity,
                mean_normalized_score=mean_normalized_score,
                max_raw_loss=max_raw_loss,
                rank_score=rank_score,
                ranking_breakdown=breakdown,
            )
        )
    return sorted(
        clusters,
        key=lambda cluster: (
            -cluster.rank_score,
            -cluster.heldout_impact,
            -cluster.recurrence,
            -cluster.confidence,
            -cluster.formal_severity,
            cluster.semantic_signature,
            cluster.compiler_surface,
        ),
    )


def cluster_legal_ir_disagreements(
    records: Iterable[Mapping[str, Any] | Any],
    *,
    config: Optional[IntrospectionAnalysisConfig] = None,
) -> List[LegalIRGapCluster]:
    """Normalize and cluster packet/introspection records in one call."""

    analysis = analyze_legal_ir_gap_clusters(records, config=config)
    return list(analysis.clusters)


def analyze_legal_ir_gap_clusters(
    records: Iterable[Mapping[str, Any] | Any],
    *,
    config: Optional[IntrospectionAnalysisConfig] = None,
) -> LegalIRGapAnalysis:
    """Build a complete normalized, clustered, ranked LegalIR gap analysis."""

    analysis_config = config or IntrospectionAnalysisConfig()
    gaps: List[NormalizedLegalIRGap] = []
    for record in records:
        gaps.extend(normalize_legal_ir_gaps(record, config=analysis_config))
    gaps = _dedupe_gaps(gaps)
    clusters = cluster_legal_ir_gaps(gaps, config=analysis_config)
    return LegalIRGapAnalysis(
        clusters=tuple(clusters),
        gaps=tuple(
            sorted(
                gaps,
                key=lambda gap: (
                    gap.semantic_family,
                    gap.compiler_surface,
                    gap.semantic_signature,
                    gap.metric_name,
                    gap.evidence_id,
                    gap.sample_id,
                ),
            )
        ),
        config=analysis_config,
    )


def analyze_introspection_disagreements(
    records: Iterable[Mapping[str, Any] | Any],
    *,
    config: Optional[IntrospectionAnalysisConfig] = None,
) -> LegalIRGapAnalysis:
    """Alias for callers that work with exported disagreement packet streams."""

    return analyze_legal_ir_gap_clusters(records, config=config)


def analysis_to_json(analysis: LegalIRGapAnalysis | Mapping[str, Any]) -> str:
    """Return stable compact JSON for an analysis object or mapping."""

    if isinstance(analysis, LegalIRGapAnalysis):
        return analysis.to_json()
    return _stable_json(dict(analysis))


@dataclass(frozen=True)
class _AnalysisContext:
    evidence_id: str
    sample_id: str
    target_family: str
    predicted_family: str
    root: Mapping[str, Any]


def _explicit_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    rows: List[NormalizedLegalIRGap] = []
    for source_key in ("normalized_gaps", "legal_ir_gaps", "gaps"):
        for index, item in enumerate(_mapping_sequence(root.get(source_key))):
            metric = str(item.get("metric_name") or item.get("metric") or item.get("name") or source_key)
            raw_value = _float_from(item, "raw_value", _float_from(item, "gap", _float_from(item, "value", 0.0)))
            surface = _surface_for(
                str(item.get("compiler_surface") or item.get("surface") or item.get("component") or metric),
                metric,
            )
            semantic_family = _semantic_family_for(
                str(item.get("semantic_family") or item.get("family") or ""),
                surface,
                metric,
            )
            rows.append(
                _make_gap(
                    context=context,
                    semantic_family=semantic_family,
                    compiler_surface=surface,
                    metric_name=metric,
                    gap_kind=str(item.get("gap_kind") or item.get("kind") or "explicit_gap"),
                    raw_value=raw_value,
                    source_key=f"{source_key}[{index}]",
                    metadata=_compact_metadata(item),
                    confidence=_optional_probability(item, "confidence"),
                    heldout_impact=_optional_heldout(item, context, surface, semantic_family, metric),
                    formal_severity=_optional_probability(item, "formal_severity"),
                    target_family=str(item.get("target_family") or context.target_family),
                    predicted_family=str(item.get("predicted_family") or context.predicted_family),
                )
            )
    return rows


def _component_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    component_gaps = _numeric_mapping(root.get("legal_ir_component_gaps"))
    compiler_round_trip = _mapping(root.get("compiler_round_trip_gaps"))
    component_gaps.update(_numeric_mapping(compiler_round_trip.get("component_gaps")))
    rows: List[NormalizedLegalIRGap] = []
    for component, value in sorted(component_gaps.items()):
        if value == 0.0:
            continue
        surface = _surface_for(component, component)
        semantic_family = OWNED_COMPILER_SURFACES[surface].semantic_family
        rows.append(
            _make_gap(
                context=context,
                semantic_family=semantic_family,
                compiler_surface=surface,
                metric_name=_canonical_token(component),
                gap_kind="compiler_component_gap",
                raw_value=value,
                source_key=f"legal_ir_component_gaps.{component}",
                metadata={"component": component},
                heldout_impact=_heldout_impact_for(context.root, surface, semantic_family, component),
            )
        )
    return rows


def _per_family_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    rows: List[NormalizedLegalIRGap] = []
    for index, item in enumerate(_mapping_sequence(root.get("per_family_gaps"))):
        family = _semantic_family_for(str(item.get("family") or ""), "", "")
        if family not in REQUIRED_LEGAL_IR_GAP_FAMILIES:
            continue
        surface = _surface_for_family(family)
        raw_value = max(
            abs(_float_from(item, "probability_gap", 0.0)),
            _float_from(item, "cross_entropy_gap", _float_from(item, "ce_gap", 0.0)),
            _float_from(item, "cosine_gap", 0.0),
        )
        rows.append(
            _make_gap(
                context=context,
                semantic_family=family,
                compiler_surface=surface,
                metric_name=f"{family}_family_probability_gap",
                gap_kind="semantic_family_gap",
                raw_value=raw_value,
                source_key=f"per_family_gaps[{index}]",
                metadata=_compact_metadata(item),
                confidence=max(
                    _probability_or_default(item.get("predicted_probability"), 0.5),
                    _probability_or_default(item.get("target_probability"), 0.5),
                ),
                heldout_impact=_heldout_impact_for(context.root, surface, family, f"{family}_family_probability_gap"),
                target_family=str(item.get("family") or context.target_family),
                predicted_family=context.predicted_family,
            )
        )
    return rows


def _learned_view_component_gaps(
    root: Mapping[str, Any],
    context: _AnalysisContext,
) -> List[NormalizedLegalIRGap]:
    """Preserve missing/overweighted LegalIR view signals as owned family gaps."""

    learned = _mapping(root.get("learned_view_gaps"))
    if not learned:
        return []
    magnitude = max(
        _float_from(learned, "cross_entropy_excess_loss", 0.0),
        _float_from(learned, "cross_entropy_loss", 0.0),
    )
    if magnitude <= 0.0:
        return []

    rows: List[NormalizedLegalIRGap] = []
    for direction, key in (
        ("underrepresented", "underrepresented_components"),
        ("overrepresented", "overrepresented_components"),
    ):
        values = learned.get(key, ()) or ()
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            continue
        for index, component_value in enumerate(values):
            component = str(component_value or "").strip()
            if not component or component == "modal.autoencoder":
                continue
            surface = _surface_for(component, f"learned_view_{direction}")
            family = OWNED_COMPILER_SURFACES[surface].semantic_family
            metric_name = f"learned_ir_view_{direction}"
            rows.append(
                _make_gap(
                    context=context,
                    semantic_family=family,
                    compiler_surface=surface,
                    metric_name=metric_name,
                    gap_kind="learned_ir_view_component_gap",
                    raw_value=magnitude,
                    source_key=f"learned_view_gaps.{key}[{index}]",
                    metadata={
                        "component": component,
                        "direction": direction,
                    },
                    heldout_impact=_heldout_impact_for(
                        context.root,
                        surface,
                        family,
                        metric_name,
                    ),
                )
            )
    return rows


def _compiler_round_trip_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    container = _mapping(root.get("compiler_round_trip_gaps")) or root
    metric_surface = {
        "embedding_cosine_gap": "modal.ir_decompiler",
        "cosine_loss": "modal.ir_decompiler",
        "legal_ir_view_cross_entropy_excess_loss": "TDFOL.prover",
        "legal_ir_view_cross_entropy_loss": "TDFOL.prover",
        "reconstruction_loss": "modal.ir_decompiler",
        "source_decompiled_text_embedding_cosine_loss": "modal.ir_decompiler",
        "source_decompiled_text_token_loss": "modal.ir_decompiler",
    }
    rows: List[NormalizedLegalIRGap] = []
    for metric, surface in metric_surface.items():
        value = _float_or_none(container.get(metric))
        if value is None or value <= 0.0:
            continue
        family = OWNED_COMPILER_SURFACES[surface].semantic_family
        rows.append(
            _make_gap(
                context=context,
                semantic_family=family,
                compiler_surface=surface,
                metric_name=metric,
                gap_kind="compiler_round_trip_gap",
                raw_value=value,
                source_key=f"compiler_round_trip_gaps.{metric}",
                heldout_impact=_heldout_impact_for(context.root, surface, family, metric),
            )
        )
    return rows


def _proof_route_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    proof = _mapping(root.get("proof_route_status") or root.get("prover_signal"))
    if not proof:
        return []
    failure_ratio = _float_from(proof, "failure_ratio", 0.0)
    route_status = str(proof.get("route_status") or "")
    compiles = bool(proof.get("compiles", proof.get("prover_compiles", True)))
    if failure_ratio <= 0.0 and compiles and route_status not in {"failed", "not_evaluated"}:
        return []
    value = max(failure_ratio, 1.0 if route_status == "failed" and not compiles else 0.0)
    return [
        _make_gap(
            context=context,
            semantic_family="prover",
            compiler_surface="external_provers.router",
            metric_name="proof_route_failure_ratio",
            gap_kind="formal_prover_gap",
            raw_value=value,
            source_key="proof_route_status.failure_ratio",
            metadata={
                "attempted_count": int(_float_from(proof, "attempted_count", 0.0)),
                "route_status": route_status,
                "valid_count": int(_float_from(proof, "valid_count", 0.0)),
            },
            heldout_impact=_heldout_impact_for(
                context.root,
                "external_provers.router",
                "prover",
                "proof_route_failure_ratio",
            ),
            formal_severity=1.0,
        )
    ]


def _metric_record_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    rows: List[NormalizedLegalIRGap] = []
    learned = _mapping(root.get("learned_ir_view_by_family"))
    for family_name, payload in sorted(learned.items()):
        semantic_family = _semantic_family_for(str(family_name), "", "")
        if semantic_family not in REQUIRED_LEGAL_IR_GAP_FAMILIES:
            continue
        surface = _surface_for_family(semantic_family)
        metric = _mapping(payload)
        for metric_name in ("cross_entropy_excess_loss", "cross_entropy_loss", "cosine_loss"):
            value = _float_or_none(metric.get(metric_name))
            if value is None or value <= 0.0:
                continue
            rows.append(
                _make_gap(
                    context=context,
                    semantic_family=semantic_family,
                    compiler_surface=surface,
                    metric_name=f"learned_ir_view_{metric_name}",
                    gap_kind="learned_ir_view_gap",
                    raw_value=value,
                    source_key=f"learned_ir_view_by_family.{family_name}.{metric_name}",
                    metadata={"family": str(family_name)},
                    confidence=max(
                        _probability_or_default(metric.get("predicted_probability"), 0.5),
                        _probability_or_default(metric.get("target_probability"), 0.5),
                    ),
                    heldout_impact=_heldout_impact_for(
                        context.root,
                        surface,
                        semantic_family,
                        f"learned_ir_view_{metric_name}",
                    ),
                    target_family=str(family_name),
                    predicted_family=context.predicted_family,
                )
            )
    source_to_decoded = _mapping(root.get("source_to_decoded"))
    for metric_name in ("embedding_cosine_loss", "token_loss"):
        value = _float_or_none(source_to_decoded.get(metric_name))
        if value is None or value <= 0.0:
            continue
        rows.append(
            _make_gap(
                context=context,
                semantic_family="decompiler",
                compiler_surface="modal.ir_decompiler",
                metric_name=f"source_to_decoded_{metric_name}",
                gap_kind="source_to_decoded_gap",
                raw_value=value,
                source_key=f"source_to_decoded.{metric_name}",
                heldout_impact=_heldout_impact_for(
                    context.root,
                    "modal.ir_decompiler",
                    "decompiler",
                    f"source_to_decoded_{metric_name}",
                ),
            )
        )
    validity = _mapping(root.get("validity"))
    if validity:
        if not bool(validity.get("prover_compiles", True)) or _float_from(validity, "failure_ratio", 0.0) > 0.0:
            rows.append(
                _make_gap(
                    context=context,
                    semantic_family="prover",
                    compiler_surface="external_provers.router",
                    metric_name="validity_failure_ratio",
                    gap_kind="formal_prover_gap",
                    raw_value=max(_float_from(validity, "failure_ratio", 0.0), 1.0 if not bool(validity.get("prover_compiles", True)) else 0.0),
                    source_key="validity.failure_ratio",
                    metadata={"prover_compiles": bool(validity.get("prover_compiles", True))},
                    formal_severity=1.0,
                )
            )
        if not bool(validity.get("structural_valid", True)) or not bool(validity.get("modal_ir_valid", True)):
            rows.append(
                _make_gap(
                    context=context,
                    semantic_family="provenance",
                    compiler_surface="modal.source_provenance",
                    metric_name="structural_modal_ir_validity",
                    gap_kind="structural_validity_gap",
                    raw_value=1.0,
                    source_key="validity.structural_valid",
                    metadata={
                        "modal_ir_valid": bool(validity.get("modal_ir_valid", True)),
                        "structural_valid": bool(validity.get("structural_valid", True)),
                    },
                    formal_severity=0.9,
                )
            )
    return rows


def _anti_copy_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    anti_copy = _mapping(root.get("anti_copy") or root.get("anti_copy_evidence"))
    rows: List[NormalizedLegalIRGap] = []
    for metric_name in ("anti_copy_penalty", "source_copy_loss", "source_span_copy_ratio"):
        value = _float_or_none(anti_copy.get(metric_name))
        if value is None or value <= 0.0:
            continue
        rows.append(
            _make_gap(
                context=context,
                semantic_family="provenance",
                compiler_surface="modal.source_provenance",
                metric_name=metric_name,
                gap_kind="source_provenance_gap",
                raw_value=value,
                source_key=f"anti_copy.{metric_name}",
                heldout_impact=_heldout_impact_for(
                    context.root,
                    "modal.source_provenance",
                    "provenance",
                    metric_name,
                ),
            )
        )
    return rows


def _synthesis_focus_gaps(root: Mapping[str, Any], context: _AnalysisContext) -> List[NormalizedLegalIRGap]:
    rows: List[NormalizedLegalIRGap] = []
    for index, hint in enumerate(_mapping_sequence(root.get("synthesis_hints"))):
        component = str(hint.get("target_component") or "")
        surface = _surface_for(component, str(hint.get("action") or ""))
        family = OWNED_COMPILER_SURFACES[surface].semantic_family
        priority = _float_from(hint, "priority", 0.0)
        if priority <= 0.0:
            continue
        rows.append(
            _make_gap(
                context=context,
                semantic_family=family,
                compiler_surface=surface,
                metric_name=_canonical_token(str(hint.get("action") or component or "synthesis_hint")),
                gap_kind="synthesis_focus_gap",
                raw_value=priority,
                source_key=f"synthesis_hints[{index}]",
                metadata=_compact_metadata(hint),
                heldout_impact=_heldout_impact_for(
                    context.root,
                    surface,
                    family,
                    str(hint.get("action") or component),
                ),
            )
        )
    for index, focus in enumerate(root.get("synthesis_focus", []) or []):
        focus_text = str(focus)
        surface = _surface_for(focus_text, focus_text)
        if surface == "modal.ir_decompiler" and "deontic" in focus_text:
            surface = "deontic.ir"
        family = OWNED_COMPILER_SURFACES[surface].semantic_family
        rows.append(
            _make_gap(
                context=context,
                semantic_family=family,
                compiler_surface=surface,
                metric_name=_canonical_token(focus_text),
                gap_kind="synthesis_focus_gap",
                raw_value=0.25,
                source_key=f"synthesis_focus[{index}]",
                metadata={"focus": focus_text},
                heldout_impact=_heldout_impact_for(context.root, surface, family, focus_text),
            )
        )
    return rows


def _make_gap(
    *,
    context: _AnalysisContext,
    semantic_family: str,
    compiler_surface: str,
    metric_name: str,
    gap_kind: str,
    raw_value: float,
    source_key: str,
    metadata: Optional[Mapping[str, Any]] = None,
    confidence: Optional[float] = None,
    heldout_impact: Optional[float] = None,
    formal_severity: Optional[float] = None,
    target_family: Optional[str] = None,
    predicted_family: Optional[str] = None,
) -> NormalizedLegalIRGap:
    surface = compiler_surface if compiler_surface in OWNED_COMPILER_SURFACES else _surface_for(compiler_surface, metric_name)
    family = semantic_family if semantic_family in REQUIRED_LEGAL_IR_GAP_FAMILIES else OWNED_COMPILER_SURFACES[surface].semantic_family
    target = str(target_family if target_family is not None else context.target_family)
    predicted = str(predicted_family if predicted_family is not None else context.predicted_family)
    normalized_score = _normalize_gap_value(raw_value)
    resolved_confidence = (
        _clamp_probability(confidence)
        if confidence is not None
        else _confidence_for(context.root, target, predicted)
    )
    resolved_impact = (
        _clamp_probability(heldout_impact)
        if heldout_impact is not None
        else _heldout_impact_for(context.root, surface, family, metric_name)
    )
    resolved_severity = (
        _clamp_probability(formal_severity)
        if formal_severity is not None
        else _formal_severity_for(surface, metric_name, gap_kind, context.root)
    )
    compact_metadata = _compact_metadata(metadata or {})
    semantic_signature = _semantic_signature(
        semantic_family=family,
        gap_kind=gap_kind,
        metric_name=metric_name,
        target_family=target,
        predicted_family=predicted,
        metadata=compact_metadata,
    )
    gap = NormalizedLegalIRGap(
        evidence_id=context.evidence_id,
        sample_id=context.sample_id,
        semantic_family=family,
        compiler_surface=surface,
        metric_name=_canonical_token(metric_name),
        gap_kind=_canonical_token(gap_kind),
        raw_value=float(raw_value),
        normalized_score=normalized_score,
        confidence=resolved_confidence,
        heldout_impact=resolved_impact,
        formal_severity=resolved_severity,
        semantic_signature=semantic_signature,
        owned_code_paths=OWNED_COMPILER_SURFACES[surface].code_paths,
        target_family=_canonical_token(target) if target else "",
        predicted_family=_canonical_token(predicted) if predicted else "",
        source_key=source_key,
        metadata=compact_metadata,
    )
    return NormalizedLegalIRGap(**{**gap.to_dict(include_gap_id=False), "gap_id": gap.expected_gap_id()})


def _gap_from_mapping(data: Mapping[str, Any]) -> NormalizedLegalIRGap:
    return NormalizedLegalIRGap(
        evidence_id=str(data.get("evidence_id") or ""),
        sample_id=str(data.get("sample_id") or ""),
        semantic_family=str(data.get("semantic_family") or ""),
        compiler_surface=str(data.get("compiler_surface") or ""),
        metric_name=str(data.get("metric_name") or ""),
        gap_kind=str(data.get("gap_kind") or ""),
        raw_value=_float_from(data, "raw_value", 0.0),
        normalized_score=_float_from(data, "normalized_score", 0.0),
        confidence=_float_from(data, "confidence", 0.0),
        heldout_impact=_float_from(data, "heldout_impact", 0.0),
        formal_severity=_float_from(data, "formal_severity", 0.0),
        semantic_signature=str(data.get("semantic_signature") or ""),
        owned_code_paths=tuple(str(value) for value in data.get("owned_code_paths", []) or []),
        target_family=str(data.get("target_family") or ""),
        predicted_family=str(data.get("predicted_family") or ""),
        source_key=str(data.get("source_key") or ""),
        metadata=_mapping(data.get("metadata")),
        schema_version=str(data.get("schema_version") or ""),
        gap_id=str(data.get("gap_id") or ""),
    )


def _dedupe_gaps(gaps: Sequence[NormalizedLegalIRGap]) -> List[NormalizedLegalIRGap]:
    deduped: Dict[str, NormalizedLegalIRGap] = {}
    for gap in gaps:
        existing = deduped.get(gap.gap_id)
        if existing is None:
            deduped[gap.gap_id] = gap
            continue
        if (
            gap.heldout_impact,
            gap.formal_severity,
            gap.confidence,
            gap.normalized_score,
        ) > (
            existing.heldout_impact,
            existing.formal_severity,
            existing.confidence,
            existing.normalized_score,
        ):
            deduped[gap.gap_id] = gap
    return list(deduped.values())


def _surface_for(component: str, metric_name: str) -> str:
    text = f"{component} {metric_name}".lower()
    if any(token in text for token in ("source_decompiled", "decompiler", "decoded", "round_trip", "reconstruction")):
        return "modal.ir_decompiler"
    if any(token in text for token in ("source_span", "source_cid", "provenance", "anti_copy", "copy_ratio", "structural_modal_ir")):
        return "modal.source_provenance"
    if any(token in text for token in ("tdfol", "fol.", "first_order", "quantifier")):
        return "TDFOL.prover"
    if any(token in text for token in ("external_provers", "prover", "proof", "lean", "z3", "vampire", "validity_failure")):
        return "external_provers.router"
    if any(
        token in text
        for token in (
            "event_calculus",
            "fluent",
            "initiates",
            "terminates",
            "cec.event",
            "cec.native",
            "dcec",
        )
    ):
        return "event_calculus.core"
    if any(token in text for token in ("knowledge_graph", "knowledge_graphs", "neo4j", "graph_projection", "kg.")):
        return "knowledge_graphs.neo4j_compat"
    if any(token in text for token in ("frame_logic", "flogic", "frame.", "ontology", "slot")):
        return "modal.frame_logic"
    if any(token in text for token in ("temporal", "deadline", "interval", "before", "after", "duration")):
        return "modal.temporal"
    if any(token in text for token in ("deontic", "obligation", "permission", "prohibition", "normative", "conditional_normative")):
        return "deontic.ir"
    return "modal.ir_decompiler"


def _surface_for_family(family: str) -> str:
    for surface, profile in OWNED_COMPILER_SURFACES.items():
        if profile.semantic_family == family:
            return surface
    return _surface_for(family, family)


def _semantic_family_for(family: str, component_or_surface: str, metric_name: str) -> str:
    token = _canonical_token(family)
    aliases = {
        "conditional_normative": "deontic",
        "deontic": "deontic",
        "event": "event_calculus",
        "event_calculus": "event_calculus",
        "flogic": "frame_logic",
        "frame": "frame_logic",
        "frame_logic": "frame_logic",
        "ir_decompiler": "decompiler",
        "kg": "knowledge_graph",
        "knowledge_graph": "knowledge_graph",
        "knowledge_graphs": "knowledge_graph",
        "prover": "prover",
        "provenance": "provenance",
        "tdfol": "tdfol",
        "temporal": "temporal",
    }
    if token in aliases:
        return aliases[token]
    surface = component_or_surface if component_or_surface in OWNED_COMPILER_SURFACES else _surface_for(component_or_surface, metric_name)
    return OWNED_COMPILER_SURFACES[surface].semantic_family


def _semantic_signature(
    *,
    semantic_family: str,
    gap_kind: str,
    metric_name: str,
    target_family: str,
    predicted_family: str,
    metadata: Mapping[str, Any],
) -> str:
    slot = _semantic_slot(metric_name, metadata)
    target = _canonical_token(target_family) if target_family else "unknown"
    predicted = _canonical_token(predicted_family) if predicted_family else "unknown"
    return ":".join(
        (
            _canonical_token(semantic_family),
            _canonical_token(gap_kind),
            f"{target}->{predicted}",
            slot,
        )
    )


def _semantic_slot(metric_name: str, metadata: Mapping[str, Any]) -> str:
    for key in ("semantic_slot", "slot", "component", "feature", "loss_name", "action", "focus"):
        value = metadata.get(key)
        if value:
            text = _canonical_token(str(value))
            pieces = [piece for piece in text.split("_") if piece]
            if len(pieces) > 2:
                return "_".join(pieces[-2:])
            return text or "general"
    text = _canonical_token(metric_name)
    for prefix in (
        "compiler_round_trip_gaps_",
        "legal_ir_component_gaps_",
        "learned_ir_view_",
        "source_to_decoded_",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):]
    pieces = [piece for piece in text.split("_") if piece]
    if len(pieces) > 3:
        return "_".join(pieces[-3:])
    return text or "general"


def _confidence_for(root: Mapping[str, Any], target_family: str, predicted_family: str) -> float:
    for key in ("confidence", "model_confidence"):
        value = _float_or_none(root.get(key))
        if value is not None:
            return _clamp_probability(value)
    predicted_probability = _float_or_none(root.get("predicted_probability"))
    target_probability = _float_or_none(root.get("target_probability"))
    legal_ir_views = _mapping(root.get("legal_ir_views"))
    predicted_view = _mapping(legal_ir_views.get("predicted"))
    predicted_dist = _numeric_mapping(predicted_view.get("family_distribution"))
    if predicted_probability is None and predicted_family:
        predicted_probability = predicted_dist.get(predicted_family)
    if target_probability is None and target_family:
        target_probability = predicted_dist.get(target_family)
    candidates = [
        value
        for value in (predicted_probability, target_probability)
        if value is not None and math.isfinite(value)
    ]
    if not candidates:
        return 0.5
    return _clamp_probability(max(candidates))


def _heldout_impact_for(
    root: Mapping[str, Any],
    surface: str,
    semantic_family: str,
    metric_name: str,
) -> float:
    for container_key in (
        "heldout_impact_by_surface",
        "held_out_impact_by_surface",
        "canary_impact_by_surface",
        "heldout_impact_by_family",
        "held_out_impact_by_family",
        "canary_impact_by_family",
        "heldout_impact_by_metric",
        "held_out_impact_by_metric",
        "canary_impact_by_metric",
    ):
        container = _numeric_mapping(root.get(container_key))
        for key in (surface, semantic_family, metric_name, _canonical_token(metric_name)):
            if key in container:
                return _clamp_probability(container[key])
    for key in ("heldout_impact", "held_out_impact", "canary_impact"):
        value = _float_or_none(root.get(key))
        if value is not None:
            return _clamp_probability(value)
    return 0.0


def _optional_heldout(
    item: Mapping[str, Any],
    context: _AnalysisContext,
    surface: str,
    semantic_family: str,
    metric_name: str,
) -> Optional[float]:
    for key in ("heldout_impact", "held_out_impact", "canary_impact"):
        value = _float_or_none(item.get(key))
        if value is not None:
            return _clamp_probability(value)
    return _heldout_impact_for(context.root, surface, semantic_family, metric_name)


def _formal_severity_for(surface: str, metric_name: str, gap_kind: str, root: Mapping[str, Any]) -> float:
    severity = OWNED_COMPILER_SURFACES[surface].base_formal_severity
    text = f"{metric_name} {gap_kind}".lower()
    if any(token in text for token in ("proof", "prover", "validity", "compile")):
        severity = max(severity, 0.95)
    if any(token in text for token in ("provenance", "source_span", "modal_ir_valid")):
        severity = max(severity, 0.86)
    if any(token in text for token in ("deontic", "obligation", "prohibition", "permission")):
        severity = max(severity, 0.84)
    proof = _mapping(root.get("proof_route_status"))
    if proof and str(proof.get("route_status") or "") == "failed":
        severity = max(severity, 0.96)
    return _clamp_probability(severity)


def _normalize_gap_value(value: float) -> float:
    magnitude = abs(float(value))
    if magnitude <= 1.0:
        return _stable_float(magnitude)
    return _stable_float(1.0 - math.exp(-magnitude))


def _family_context(root: Mapping[str, Any]) -> Tuple[str, str]:
    target = str(root.get("target_family") or "")
    predicted = str(root.get("predicted_family") or "")
    legal_ir_views = _mapping(root.get("legal_ir_views"))
    predicted_view = _mapping(legal_ir_views.get("predicted"))
    canonical_view = _mapping(legal_ir_views.get("canonical"))
    if not target:
        target = str(predicted_view.get("target_family") or "")
    if not predicted:
        predicted = str(predicted_view.get("predicted_family") or "")
    if not target:
        target = _top_distribution_key(_numeric_mapping(canonical_view.get("family_distribution")))
    if not predicted:
        predicted = _top_distribution_key(_numeric_mapping(predicted_view.get("family_distribution")))
    return (_canonical_token(target) if target else "", _canonical_token(predicted) if predicted else "")


def _evidence_id(root: Mapping[str, Any]) -> str:
    value = str(root.get("evidence_id") or "")
    if value:
        return value
    sample_id = _sample_id(root)
    return "lir-evidence-" + _hash_json({"sample_id": sample_id, "payload": _compact_for_id(root)})[:16]


def _sample_id(root: Mapping[str, Any]) -> str:
    sample_hashes = _mapping(root.get("sample_hashes"))
    return str(
        root.get("sample_id")
        or root.get("case_id")
        or sample_hashes.get("sample_id")
        or "unknown-sample"
    )


def _object_to_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        mapped = to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {}


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_sequence(value: Any) -> List[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _numeric_mapping(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    rows: Dict[str, float] = {}
    for key, raw_value in value.items():
        numeric = _float_or_none(raw_value)
        if numeric is not None and math.isfinite(numeric):
            rows[str(key)] = numeric
    return rows


def _compact_metadata(data: Mapping[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key, value in sorted(dict(data).items()):
        key_text = str(key)
        if not key_text or key_text in {"decoded_embedding", "residual_vector", "raw_dense_weights"}:
            continue
        if isinstance(value, Mapping):
            nested = _compact_metadata(value)
            if nested:
                compact[key_text] = nested
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if all(not isinstance(item, (Mapping, Sequence)) or isinstance(item, (str, bytes, bytearray)) for item in value):
                compact[key_text] = [_json_safe(item) for item in list(value)[:8]]
        else:
            compact[key_text] = _json_safe(value)
    return compact


def _compact_for_id(data: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: _json_safe(value)
        for key, value in sorted(data.items())
        if key
        in {
            "case_id",
            "compiler_round_trip_gaps",
            "legal_ir_component_gaps",
            "per_family_gaps",
            "proof_route_status",
            "sample_id",
            "validity",
        }
    }


def _json_safe_mapping(data: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe(value) for key, value in sorted(dict(data).items())}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _stable_float(value) if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


def _top_distribution_key(distribution: Mapping[str, float]) -> str:
    if not distribution:
        return ""
    return str(max(distribution, key=lambda key: (float(distribution[key]), str(key))))


def _canonical_token(value: str) -> str:
    token = _WORD_RE.sub("_", str(value).strip().lower()).strip("_")
    return token or "unknown"


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _hash_json(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_json(data).encode("utf-8")).hexdigest()


def _stable_float(value: float) -> float:
    return round(float(value), 12)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _float_from(data: Mapping[str, Any], key: str, default: float) -> float:
    value = _float_or_none(data.get(key))
    return float(default) if value is None else value


def _probability_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return default
    return _clamp_probability(parsed)


def _optional_probability(data: Mapping[str, Any], key: str) -> Optional[float]:
    value = _float_or_none(data.get(key))
    return None if value is None else _clamp_probability(value)


def _clamp_probability(value: Optional[float]) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return _stable_float(max(0.0, min(1.0, float(value))))


def _require_probability(name: str, value: float) -> None:
    if not isinstance(value, (float, int)) or not math.isfinite(float(value)):
        raise IntrospectionAnalysisSchemaError(f"{name} must be finite")
    if float(value) < 0.0 or float(value) > 1.0:
        raise IntrospectionAnalysisSchemaError(f"{name} must be between 0 and 1")
