"""Deterministic LegalIR introspection disagreement packet export.

The exporter is intentionally evidence-oriented: it keeps compact hashes,
version stamps, LegalIR view summaries, feature rankings, and proof-route
status while excluding raw source text, dense embeddings, and trainable weight
tables.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
)

from .synthesis import (
    ModalProgramSynthesisHint,
    synthesis_hints_from_autoencoder_introspection,
)

INTROSPECTION_EXPORT_SCHEMA_VERSION = "legal-ir-introspection-packet-v1"
INTROSPECTION_EXPORT_CONFIG_VERSION = "legal-ir-introspection-export-config-v1"
_HASH_ALGORITHM = "sha256"
_EPSILON = 1.0e-12
_DENSE_FIELD_TOKENS = (
    "decoded_embedding",
    "base_decoded_embedding",
    "residual_vector",
    "embedding_vector",
    "feature_embedding_weights",
    "family_embedding_weights",
    "semantic_slot_embedding_weights",
    "legal_ir_view_embedding_weights",
)
_DENSE_FIELD_ALLOWED_KEYS = frozenset(
    {
        "dense_weight_tables_included",
        "stripped_dense_input_key_hashes",
    }
)
_ACTIVE_EXPORT_MODES = frozenset({"export", "shadow", "seed", "enforce"})
_COMPACT_COMPILER_METRIC_KEYS = (
    "compiler_guidance_applied",
    "compiler_ir_metric_timeout_fallback",
    "cross_entropy_excess_loss",
    "cross_entropy_loss",
    "cosine_similarity",
    "metric_sample_id",
    "metric_text_length",
    "metric_text_policy",
    "metric_text_truncated",
    "reconstruction_loss",
    "sample_timeout_seconds",
    "source_copy_loss",
    "source_copy_reward_hack_penalty",
    "source_decompiled_text_embedding_cosine_loss",
    "source_decompiled_text_embedding_cosine_similarity",
    "source_decompiled_text_token_loss",
    "source_decompiled_text_token_similarity",
    "structural_text_reconstruction_loss",
    "text_reconstruction_loss",
)


@dataclass(frozen=True)
class IntrospectionPacketExportConfig:
    """Limits and version labels for disagreement packet export."""

    max_packet_bytes: int = 12_000
    max_ranked_features: int = 16
    max_family_gaps: int = 12
    max_view_items: int = 12
    max_source_span_hashes: int = 16
    max_proof_details: int = 8
    max_synthesis_focus: int = 12
    config_version: str = INTROSPECTION_EXPORT_CONFIG_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_version": self.config_version,
            "max_family_gaps": int(self.max_family_gaps),
            "max_packet_bytes": int(self.max_packet_bytes),
            "max_proof_details": int(self.max_proof_details),
            "max_ranked_features": int(self.max_ranked_features),
            "max_source_span_hashes": int(self.max_source_span_hashes),
            "max_synthesis_focus": int(self.max_synthesis_focus),
            "max_view_items": int(self.max_view_items),
        }


@dataclass(frozen=True)
class LegalIRDisagreementPacket:
    """Compact deterministic packet for autoencoder/compiler disagreements."""

    evidence_id: str
    payload: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.payload)

    def to_json(self) -> str:
        return _stable_json(self.payload)

    @property
    def size_bytes(self) -> int:
        return len(self.to_json().encode("utf-8"))


def export_introspection_packet(
    sample: Any,
    introspection: Any,
    *,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
    prover_signal: Optional[Any] = None,
    canonical_legal_ir: Optional[Any] = None,
    predicted_legal_ir: Optional[Mapping[str, Any]] = None,
    state_version: str = MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    config: Optional[IntrospectionPacketExportConfig] = None,
    extra_versions: Optional[Mapping[str, Any]] = None,
    export_context: Optional[Mapping[str, Any]] = None,
    compiler_metrics: Optional[Mapping[str, Any]] = None,
) -> LegalIRDisagreementPacket:
    """Export one deterministic autoencoder-to-compiler disagreement packet.

    ``sample`` may be a ``LegalSample`` or persisted sample mapping.
    ``introspection`` may be an ``AutoencoderIntrospection`` or its ``to_dict``
    payload.  Dense vectors and model state tables are never copied into the
    packet.
    """

    export_config = config or IntrospectionPacketExportConfig()
    sample_map = _object_to_mapping(sample)
    introspection_map = _object_to_mapping(introspection)
    guidance_map = dict(compiler_guidance or {})
    context_map = dict(export_context or {})
    compiler_metric_map = _mapping(compiler_metrics)
    canonical_ir_obj = canonical_legal_ir if canonical_legal_ir is not None else _get(sample, "modal_ir")
    canonical_ir = _object_to_mapping(canonical_ir_obj) or _mapping(sample_map.get("modal_ir"))
    sample_id = _sample_id(sample, sample_map, introspection_map, canonical_ir)
    source_text = str(_get(sample, "text") or sample_map.get("text") or "")
    normalized_text = str(
        _get(sample, "normalized_text")
        or sample_map.get("normalized_text")
        or canonical_ir.get("normalized_text")
        or ""
    )
    source_text_hash = _hash_text(source_text)
    normalized_text_hash = _hash_text(normalized_text)
    modal_ir_hash = _modal_ir_hash(canonical_ir_obj, canonical_ir)
    source_span_hashes = _source_span_hashes(
        source_text=source_text,
        canonical_ir=canonical_ir,
        limit=max(0, int(export_config.max_source_span_hashes)),
    )
    canonical_family_distribution = _family_distribution_from_ir(canonical_ir)
    predicted_family_distribution = _predicted_family_distribution(
        introspection_map,
        guidance_map,
        canonical_family_distribution,
    )
    canonical_view_distribution = _numeric_mapping(
        introspection_map.get("legal_ir_view_distribution")
        or guidance_map.get("legal_ir_target_view_distribution")
        or guidance_map.get("legal_ir_view_distribution")
    )
    predicted_view_distribution = _numeric_mapping(
        introspection_map.get("legal_ir_predicted_view_distribution")
        or guidance_map.get("legal_ir_predicted_view_distribution")
    )
    if predicted_legal_ir:
        predicted_view_distribution.update(
            _numeric_mapping(predicted_legal_ir.get("view_distribution"))
        )
    per_family_gaps = _per_family_gaps(
        canonical_family_distribution,
        predicted_family_distribution,
        limit=max(0, int(export_config.max_family_gaps)),
    )
    ranked_features = _ranked_feature_contributions(
        introspection_map,
        guidance_map,
        limit=max(0, int(export_config.max_ranked_features)),
    )
    synthesis_focus = _synthesis_focus(
        introspection_map,
        limit=max(0, int(export_config.max_synthesis_focus)),
    )
    hints = _synthesis_hints(introspection_map)
    proof_status = _proof_route_status(
        prover_signal or introspection_map.get("prover_signal"),
        limit=max(0, int(export_config.max_proof_details)),
    )
    compiler_round_trip_gaps = _compiler_round_trip_gaps(
        introspection_map,
        limit=max(0, int(export_config.max_view_items)),
    )
    compiler_decompiler_metrics = _compact_compiler_decompiler_metrics(
        compiler_metric_map,
        aggregate_fallback=context_map.get("aggregate_compiler_metrics"),
    )
    learned_view_gaps = _learned_view_gaps(
        introspection_map,
        guidance_map,
        limit=max(0, int(export_config.max_view_items)),
    )
    run_context = _run_context(context_map)

    packet: Dict[str, Any] = {
        "anti_copy_evidence": _anti_copy_evidence(
            source_text=source_text,
            source_span_hashes=source_span_hashes,
            stripped_input_keys=sorted(
                set(_dense_keys(introspection_map)) | set(_dense_keys(guidance_map))
            ),
        ),
        "compiler_round_trip_gaps": compiler_round_trip_gaps,
        "compiler_decompiler_metrics": compiler_decompiler_metrics,
        "evidence_id": "",
        "evidence_hashes": {
            "canonical_modal_ir_hash": modal_ir_hash,
            "compiler_guidance_hash": _hash_json(guidance_map),
            "compiler_metrics_hash": _hash_json(compiler_decompiler_metrics),
            "learned_view_gaps_hash": _hash_json(learned_view_gaps),
            "proof_route_hash": _hash_json(proof_status),
            "source_span_hashes_hash": _hash_json(source_span_hashes),
            "state_hash": str(context_map.get("state_hash") or ""),
        },
        "legal_ir_views": {
            "canonical": {
                "document_id": str(canonical_ir.get("document_id") or sample_id),
                "family_distribution": _top_numeric_mapping(
                    canonical_family_distribution,
                    limit=max(0, int(export_config.max_view_items)),
                ),
                "modal_ir_hash": modal_ir_hash,
                "source": str(canonical_ir.get("source") or sample_map.get("source") or ""),
                "version": str(canonical_ir.get("version") or ""),
                "view_distribution": _top_numeric_mapping(
                    canonical_view_distribution,
                    limit=max(0, int(export_config.max_view_items)),
                ),
            },
            "predicted": {
                "family_distribution": _top_numeric_mapping(
                    predicted_family_distribution,
                    limit=max(0, int(export_config.max_view_items)),
                ),
                "predicted_family": str(introspection_map.get("predicted_family") or ""),
                "sample_memory_used": bool(introspection_map.get("sample_memory_used", False)),
                "target_family": str(introspection_map.get("target_family") or ""),
                "view_distribution": _top_numeric_mapping(
                    predicted_view_distribution,
                    limit=max(0, int(export_config.max_view_items)),
                ),
            },
        },
        "learned_view_gaps": learned_view_gaps,
        "per_family_gaps": per_family_gaps,
        "priority_score": _priority_score(
            introspection_map,
            per_family_gaps=per_family_gaps,
            compiler_round_trip_gaps=compiler_round_trip_gaps,
            proof_status=proof_status,
        ),
        "proof_route_status": proof_status,
        "ranked_feature_contributions": ranked_features,
        "sample_hashes": {
            "modal_ir_hash": modal_ir_hash,
            "normalized_text_hash": normalized_text_hash,
            "sample_hash": _hash_json(
                {
                    "modal_ir_hash": modal_ir_hash,
                    "normalized_text_hash": normalized_text_hash,
                    "sample_id": sample_id,
                    "source_text_hash": source_text_hash,
                }
            ),
            "sample_id": sample_id,
            "source_span_hashes": source_span_hashes,
            "source_text_hash": source_text_hash,
        },
        "run_context": run_context,
        "schema_version": INTROSPECTION_EXPORT_SCHEMA_VERSION,
        "synthesis_focus": synthesis_focus,
        "synthesis_hints": [
            _compact_synthesis_hint(hint)
            for hint in hints[: max(0, int(export_config.max_synthesis_focus))]
        ],
        "versions": {
            "autoencoder_architecture_version": MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
            "config_version": export_config.config_version,
            "export_schema_version": INTROSPECTION_EXPORT_SCHEMA_VERSION,
            "modal_ir_version": str(canonical_ir.get("version") or ""),
            "state_version": str(state_version or ""),
            **{str(key): _json_safe(value) for key, value in dict(extra_versions or {}).items()},
        },
    }
    packet = _cap_packet(packet, export_config)
    packet["evidence_id"] = _evidence_id(packet)
    packet = _cap_packet(packet, export_config)
    if not packet.get("evidence_id"):
        packet["evidence_id"] = _evidence_id(packet)
    return LegalIRDisagreementPacket(
        evidence_id=str(packet["evidence_id"]),
        payload=packet,
    )


def export_autoencoder_disagreement_packet(
    sample: Any,
    autoencoder: Any,
    *,
    prover_signal: Optional[Any] = None,
    use_sample_memory: bool = False,
    top_k: int = 16,
    config: Optional[IntrospectionPacketExportConfig] = None,
) -> LegalIRDisagreementPacket:
    """Run autoencoder introspection and export one disagreement packet."""

    introspection = autoencoder.introspect_sample(
        sample,
        use_sample_memory=use_sample_memory,
        top_k=top_k,
    )
    guidance = autoencoder.compiler_guidance_for_sample(
        sample,
        use_sample_memory=use_sample_memory,
        top_k=top_k,
    )
    return export_introspection_packet(
        sample,
        introspection,
        compiler_guidance=guidance,
        prover_signal=prover_signal,
        config=config,
    )


def export_prioritized_disagreement_packets(
    records: Iterable[Mapping[str, Any] | Any],
    *,
    config: Optional[IntrospectionPacketExportConfig] = None,
) -> List[LegalIRDisagreementPacket]:
    """Export and priority-sort packet records.

    Each record can be either a mapping containing ``sample`` and
    ``introspection`` keys, a mapping that already looks like an introspection
    record plus ``modal_ir``/sample fields, or an object with those attributes.
    """

    packets: List[LegalIRDisagreementPacket] = []
    for record in records:
        record_map = _object_to_mapping(record)
        sample = record_map.get("sample") or record
        introspection = record_map.get("introspection") or record_map
        packets.append(
            export_introspection_packet(
                sample,
                introspection,
                compiler_guidance=_mapping(record_map.get("compiler_guidance")),
                prover_signal=record_map.get("prover_signal"),
                config=config,
            )
        )
    return sorted(
        packets,
        key=lambda packet: (
            -float(packet.payload.get("priority_score", 0.0) or 0.0),
            str(packet.payload.get("evidence_id") or ""),
        ),
    )


def packet_to_json(packet: LegalIRDisagreementPacket | Mapping[str, Any]) -> str:
    """Return stable compact JSON for a packet object or payload mapping."""

    if isinstance(packet, LegalIRDisagreementPacket):
        return packet.to_json()
    return _stable_json(dict(packet))


def introspection_export_mode_enabled(mode: str) -> bool:
    """Return whether a daemon rollout mode should emit JSONL packets."""

    return str(mode or "").strip().lower() in _ACTIVE_EXPORT_MODES


def validate_disagreement_packet(
    packet: LegalIRDisagreementPacket | Mapping[str, Any],
) -> List[str]:
    """Return fail-closed schema errors for a compact disagreement packet."""

    payload = packet.to_dict() if isinstance(packet, LegalIRDisagreementPacket) else dict(packet)
    failures: List[str] = []
    if payload.get("schema_version") != INTROSPECTION_EXPORT_SCHEMA_VERSION:
        failures.append("unexpected_schema_version")
    for key in (
        "compiler_decompiler_metrics",
        "evidence_hashes",
        "evidence_id",
        "legal_ir_views",
        "learned_view_gaps",
        "proof_route_status",
        "run_context",
        "sample_hashes",
    ):
        if key not in payload:
            failures.append(f"missing_{key}")
    context = _mapping(payload.get("run_context"))
    for key in ("compiler_commit", "cycle", "evaluation_role", "sample_role", "state_hash"):
        if context.get(key) in (None, ""):
            failures.append(f"missing_run_context_{key}")
    if "frozen_canary" not in context:
        failures.append("missing_run_context_frozen_canary")
    evidence_hashes = _mapping(payload.get("evidence_hashes"))
    for key in (
        "canonical_modal_ir_hash",
        "compiler_guidance_hash",
        "compiler_metrics_hash",
        "learned_view_gaps_hash",
        "proof_route_hash",
        "source_span_hashes_hash",
        "state_hash",
    ):
        if not str(evidence_hashes.get(key) or ""):
            failures.append(f"missing_evidence_hash_{key}")
    if _contains_dense_key(payload):
        failures.append("dense_state_or_vector_field_present")
    encoded = packet_to_json(payload)
    if any(token in encoded for token in _DENSE_FIELD_TOKENS):
        failures.append("dense_field_token_present")
    return list(dict.fromkeys(failures))


def append_disagreement_packets_jsonl(
    path: str | Path,
    packets: Iterable[LegalIRDisagreementPacket | Mapping[str, Any]],
) -> Dict[str, Any]:
    """Append validated packets to compact JSONL and return export telemetry."""

    started_at = time.time()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    packet_count = 0
    schema_failures: List[Dict[str, Any]] = []
    bytes_written = 0
    with destination.open("a", encoding="utf-8") as handle:
        for packet in packets:
            payload = packet.to_dict() if isinstance(packet, LegalIRDisagreementPacket) else dict(packet)
            failures = validate_disagreement_packet(payload)
            if failures:
                schema_failures.append(
                    {
                        "evidence_id": str(payload.get("evidence_id") or ""),
                        "failures": failures,
                        "sample_id": str(_mapping(payload.get("sample_hashes")).get("sample_id") or ""),
                    }
                )
                continue
            line = packet_to_json(payload)
            handle.write(line + "\n")
            packet_count += 1
            bytes_written += len(line.encode("utf-8")) + 1
    return {
        "bytes_written": bytes_written,
        "elapsed_seconds": round(time.time() - started_at, 6),
        "packet_count": packet_count,
        "path": str(destination),
        "schema_failure_count": len(schema_failures),
        "schema_failures": schema_failures[:16],
    }


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


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _sample_id(
    sample: Any,
    sample_map: Mapping[str, Any],
    introspection: Mapping[str, Any],
    canonical_ir: Mapping[str, Any],
) -> str:
    return str(
        _get(sample, "sample_id")
        or sample_map.get("sample_id")
        or introspection.get("sample_id")
        or canonical_ir.get("document_id")
        or "unknown-sample"
    )


def _modal_ir_hash(canonical_ir_obj: Any, canonical_ir: Mapping[str, Any]) -> str:
    canonical_hash = getattr(canonical_ir_obj, "canonical_hash", None)
    if callable(canonical_hash):
        return str(canonical_hash())
    return _hash_json(canonical_ir)


def _source_span_hashes(
    *,
    source_text: str,
    canonical_ir: Mapping[str, Any],
    limit: int,
) -> Dict[str, str]:
    formulas = list(canonical_ir.get("formulas") or [])
    rows: List[tuple[str, str]] = []
    for index, formula in enumerate(formulas):
        if not isinstance(formula, Mapping):
            continue
        formula_id = str(formula.get("formula_id") or f"formula-{index}")
        provenance = _mapping(formula.get("provenance"))
        start = _int_or_none(provenance.get("start_char"))
        end = _int_or_none(provenance.get("end_char"))
        if start is None or end is None or start < 0 or end < start:
            span_payload = {
                "formula_id": formula_id,
                "provenance": provenance,
            }
        else:
            span_payload = {
                "end_char": end,
                "formula_id": formula_id,
                "span_text_hash": _hash_text(source_text[start:end]),
                "start_char": start,
            }
        rows.append((formula_id, _hash_json(span_payload)))
    return dict(sorted(rows)[:limit])


def _family_distribution_from_ir(canonical_ir: Mapping[str, Any]) -> Dict[str, float]:
    counts: Dict[str, float] = {}
    for formula in canonical_ir.get("formulas") or []:
        if not isinstance(formula, Mapping):
            continue
        operator = _mapping(formula.get("operator"))
        family = str(operator.get("family") or "").strip()
        if family:
            counts[family] = counts.get(family, 0.0) + 1.0
    total = sum(counts.values())
    if total <= 0.0:
        return {}
    return {family: round(value / total, 12) for family, value in sorted(counts.items())}


def _predicted_family_distribution(
    introspection: Mapping[str, Any],
    guidance: Mapping[str, Any],
    canonical_family_distribution: Mapping[str, float],
) -> Dict[str, float]:
    distribution = _numeric_mapping(guidance.get("family_distribution"))
    if distribution:
        return _normalize_distribution(distribution)
    target_family = str(introspection.get("target_family") or "").strip()
    predicted_family = str(introspection.get("predicted_family") or "").strip()
    if not target_family and canonical_family_distribution:
        target_family = max(
            canonical_family_distribution,
            key=lambda family: (canonical_family_distribution[family], family),
        )
    predicted_probability = _float_or_none(introspection.get("predicted_probability"))
    target_probability = _float_or_none(introspection.get("target_probability"))
    if predicted_family:
        distribution[predicted_family] = predicted_probability if predicted_probability is not None else 1.0
    if target_family:
        distribution[target_family] = target_probability if target_probability is not None else distribution.get(target_family, 0.0)
    return _normalize_distribution(distribution)


def _per_family_gaps(
    target_distribution: Mapping[str, float],
    predicted_distribution: Mapping[str, float],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for family in sorted(set(target_distribution) | set(predicted_distribution)):
        target = max(0.0, float(target_distribution.get(family, 0.0)))
        predicted = max(0.0, float(predicted_distribution.get(family, 0.0)))
        ce = -target * math.log(max(predicted, _EPSILON)) if target > 0.0 else 0.0
        entropy = -target * math.log(max(target, _EPSILON)) if target > 0.0 else 0.0
        cross_entropy_gap = round(max(0.0, ce - entropy), 12)
        rows.append(
            {
                "ce_gap": cross_entropy_gap,
                "cosine_gap": round(_binary_distribution_cosine_gap(target, predicted), 12),
                "cross_entropy_gap": cross_entropy_gap,
                "family": family,
                "predicted_probability": round(predicted, 12),
                "probability_gap": round(target - predicted, 12),
                "target_probability": round(target, 12),
            }
        )
    rows.sort(
        key=lambda row: (
            -abs(float(row["probability_gap"])),
            -float(row["ce_gap"]),
            str(row["family"]),
        )
    )
    return rows[:limit]


def _binary_distribution_cosine_gap(target: float, predicted: float) -> float:
    left = (target, max(0.0, 1.0 - target))
    right = (predicted, max(0.0, 1.0 - predicted))
    left_norm = math.sqrt(left[0] * left[0] + left[1] * left[1])
    right_norm = math.sqrt(right[0] * right[0] + right[1] * right[1])
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    similarity = (left[0] * right[0] + left[1] * right[1]) / (left_norm * right_norm)
    return max(0.0, 1.0 - similarity)


def _ranked_feature_contributions(
    introspection: Mapping[str, Any],
    guidance: Mapping[str, Any],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for source_key in ("top_family_contributions", "top_embedding_contributions"):
        for item in _mapping_sequence(introspection.get(source_key)):
            rows.append(_compact_contribution(item, source_key))
    for item in _mapping_sequence(guidance.get("ranked_guidance_features")):
        rows.append(_compact_guidance_feature(item))
    rows = [row for row in rows if row.get("feature")]
    rows.sort(
        key=lambda row: (
            -float(row.get("priority", 0.0) or 0.0),
            str(row.get("source") or ""),
            str(row.get("feature") or ""),
            str(row.get("family") or ""),
        )
    )
    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("source") or ""),
            str(row.get("feature") or ""),
            str(row.get("family") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


def _compact_contribution(item: Mapping[str, Any], source: str) -> Dict[str, Any]:
    value = _float_or_zero(item.get("value"))
    magnitude = _float_or_zero(item.get("magnitude"))
    metadata = _compact_metadata(_mapping(item.get("metadata")))
    priority = max(abs(value), magnitude)
    if "alignment_with_residual" in metadata:
        priority = max(priority, abs(_float_or_zero(metadata["alignment_with_residual"])))
    return {
        "contribution_type": str(item.get("contribution_type") or ""),
        "family": str(item.get("family") or ""),
        "feature": str(item.get("feature") or ""),
        "magnitude": round(magnitude, 12),
        "metadata": metadata,
        "priority": round(priority, 12),
        "source": source,
        "value": round(value, 12),
    }


def _compact_guidance_feature(item: Mapping[str, Any]) -> Dict[str, Any]:
    score = _float_or_zero(item.get("score"))
    return {
        "contribution_type": "compiler_guidance_feature",
        "family": "",
        "feature": str(item.get("feature") or ""),
        "magnitude": round(score, 12),
        "metadata": {
            key: round(_float_or_zero(item.get(key)), 12)
            for key in (
                "embedding_weight_norm",
                "family_logit_magnitude",
                "legal_ir_view_logit_magnitude",
            )
            if item.get(key) is not None
        },
        "priority": round(score, 12),
        "source": "ranked_guidance_features",
        "value": round(score, 12),
    }


def _compiler_round_trip_gaps(
    introspection: Mapping[str, Any],
    *,
    limit: int,
) -> Dict[str, Any]:
    diagnostics = _mapping(introspection.get("pipeline_stage_diagnostics"))
    component_gaps = _top_numeric_mapping(
        introspection.get("legal_ir_component_gaps"),
        limit=limit,
        signed=True,
    )
    return {
        "component_gaps": component_gaps,
        "cosine_loss": round(_float_or_zero(introspection.get("cosine_loss")), 12),
        "embedding_cosine_gap": round(
            max(
                _float_or_zero(introspection.get("cosine_loss")),
                _float_or_zero(diagnostics.get("autoencoder_embedding_cosine_gap")),
            ),
            12,
        ),
        "legal_ir_view_cross_entropy_excess_loss": round(
            _float_or_zero(introspection.get("legal_ir_view_cross_entropy_excess_loss")),
            12,
        ),
        "legal_ir_view_cross_entropy_loss": round(
            _float_or_zero(introspection.get("legal_ir_view_cross_entropy_loss")),
            12,
        ),
        "pipeline_stage_focus": [
            str(value)
            for value in introspection.get("pipeline_stage_focus", []) or []
            if str(value)
        ][:limit],
        "reconstruction_loss": round(_float_or_zero(introspection.get("reconstruction_loss")), 12),
        "source_decompiled_text_embedding_cosine_loss": round(
            _float_or_zero(introspection.get("source_decompiled_text_embedding_cosine_loss")),
            12,
        ),
        "source_decompiled_text_token_loss": round(
            _float_or_zero(introspection.get("source_decompiled_text_token_loss")),
            12,
        ),
    }


def _compact_compiler_decompiler_metrics(
    metrics: Mapping[str, Any],
    *,
    aggregate_fallback: Any = None,
) -> Dict[str, Any]:
    source = _mapping(metrics)
    if not source:
        source = _mapping(aggregate_fallback)
    if "metrics" in source and isinstance(source.get("metrics"), Mapping):
        source = {**source, **_mapping(source.get("metrics"))}
    compact: Dict[str, Any] = {}
    for key in _COMPACT_COMPILER_METRIC_KEYS:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, bool):
            compact[key] = value
        elif isinstance(value, int):
            compact[key] = value
        elif isinstance(value, float):
            compact[key] = round(_float_or_zero(value), 12)
        elif value is not None and str(value):
            compact[key] = str(value)
    if "sample_id" in source:
        compact["sample_id"] = str(source.get("sample_id") or "")
    return compact


def _learned_view_gaps(
    introspection: Mapping[str, Any],
    guidance: Mapping[str, Any],
    *,
    limit: int,
) -> Dict[str, Any]:
    target = _numeric_mapping(
        introspection.get("legal_ir_view_distribution")
        or guidance.get("legal_ir_target_view_distribution")
        or guidance.get("legal_ir_view_distribution")
    )
    predicted = _numeric_mapping(
        introspection.get("legal_ir_predicted_view_distribution")
        or guidance.get("legal_ir_predicted_view_distribution")
    )
    explicit_gaps = _numeric_mapping(guidance.get("legal_ir_view_gap_distribution"))
    gaps: Dict[str, float] = {}
    for key in sorted(set(target) | set(predicted) | set(explicit_gaps)):
        if key in explicit_gaps:
            value = explicit_gaps[key]
        else:
            value = float(target.get(key, 0.0)) - float(predicted.get(key, 0.0))
        if abs(value) > _EPSILON:
            gaps[key] = value
    return {
        "cross_entropy_excess_loss": round(
            _float_or_zero(
                introspection.get("legal_ir_view_cross_entropy_excess_loss")
                or _mapping(guidance.get("legal_ir_view_metrics")).get(
                    "cross_entropy_excess_loss"
                )
            ),
            12,
        ),
        "cross_entropy_loss": round(
            _float_or_zero(
                introspection.get("legal_ir_view_cross_entropy_loss")
                or _mapping(guidance.get("legal_ir_view_metrics")).get(
                    "cross_entropy_loss"
                )
            ),
            12,
        ),
        "overrepresented_components": [
            str(value)
            for value in introspection.get("legal_ir_overrepresented_components", []) or []
            if str(value)
        ][:limit],
        "underrepresented_components": [
            str(value)
            for value in introspection.get("legal_ir_underrepresented_components", []) or []
            if str(value)
        ][:limit],
        "view_gap_distribution": _top_numeric_mapping(gaps, limit=limit, signed=True),
    }


def _run_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    frozen_canary = _mapping(context.get("frozen_canary"))
    return {
        "compiler_commit": str(context.get("compiler_commit") or ""),
        "cycle": int(_float_or_zero(context.get("cycle"))),
        "evaluation_role": str(context.get("evaluation_role") or ""),
        "export_mode": str(context.get("export_mode") or ""),
        "frozen_canary": {
            "canary_set_hash": str(frozen_canary.get("canary_set_hash") or ""),
            "enabled": bool(frozen_canary.get("enabled", False)),
            "index": (
                int(_float_or_zero(frozen_canary.get("index")))
                if frozen_canary.get("index") is not None
                else None
            ),
            "sample_id": str(frozen_canary.get("sample_id") or ""),
        },
        "run_id": str(context.get("run_id") or ""),
        "sample_role": str(context.get("sample_role") or ""),
        "state_hash": str(context.get("state_hash") or ""),
    }


def _proof_route_status(prover_signal: Any, *, limit: int) -> Dict[str, Any]:
    signal = _object_to_mapping(prover_signal)
    if not signal:
        return {
            "attempted_count": 0,
            "compiles": False,
            "failure_ratio": 1.0,
            "route_status": "not_evaluated",
            "verified_by": [],
        }
    attempted = int(_float_or_zero(signal.get("attempted_count")))
    valid = int(_float_or_zero(signal.get("valid_count")))
    failed = int(_float_or_zero(signal.get("failed_count")))
    errors = int(_float_or_zero(signal.get("error_count")))
    unavailable = int(_float_or_zero(signal.get("unavailable_count")))
    if attempted <= 0:
        route_status = "not_evaluated"
        compiles = False
        failure_ratio = 1.0
    else:
        compiles = valid == attempted
        failure_ratio = max(0.0, min(1.0, (attempted - valid) / attempted))
        route_status = "compiled" if compiles else "failed"
    details = []
    for detail in _mapping_sequence(signal.get("details"))[:limit]:
        details.append(
            {
                "compiled": bool(detail.get("compiled", False)),
                "formula_id": str(detail.get("formula_id") or ""),
                "overall_valid": bool(detail.get("overall_valid", False)),
                "statuses": [str(value) for value in detail.get("statuses", []) or []][:4],
            }
        )
    return {
        "attempted_count": attempted,
        "compiles": compiles,
        "details": details,
        "error_count": errors,
        "failed_count": failed,
        "failure_ratio": round(failure_ratio, 12),
        "proved_count": int(_float_or_zero(signal.get("proved_count"))),
        "route_status": route_status,
        "unavailable_count": unavailable,
        "valid_count": valid,
        "verified_by": sorted(str(value) for value in signal.get("verified_by", []) or []),
    }


def _synthesis_focus(introspection: Mapping[str, Any], *, limit: int) -> List[str]:
    focus = [str(value) for value in introspection.get("synthesis_focus", []) or [] if str(value)]
    return list(dict.fromkeys(focus))[:limit]


def _synthesis_hints(introspection: Mapping[str, Any]) -> List[ModalProgramSynthesisHint]:
    try:
        return synthesis_hints_from_autoencoder_introspection(introspection)
    except Exception:
        return []


def _compact_synthesis_hint(hint: ModalProgramSynthesisHint) -> Dict[str, Any]:
    evidence = _mapping(getattr(hint, "evidence", {}))
    compact_evidence = {
        key: _json_safe(value)
        for key, value in sorted(evidence.items())
        if key
        in {
            "bridge_failure_name",
            "family_margin",
            "loss_name",
            "loss_value",
            "predicted_family",
            "predicted_view",
            "primary_legal_ir_component_gap",
            "target_family",
            "target_file_lane",
            "target_probability",
            "target_view",
        }
    }
    return {
        "action": hint.action,
        "evidence": compact_evidence,
        "hint_id": hint.hint_id,
        "priority": round(float(hint.priority), 12),
        "status": hint.status,
        "target_component": hint.target_component,
    }


def _anti_copy_evidence(
    *,
    source_text: str,
    source_span_hashes: Mapping[str, str],
    stripped_input_keys: Sequence[str],
) -> Dict[str, Any]:
    return {
        "dense_weight_tables_included": False,
        "exact_source_spans_included": False,
        "hash_algorithm": _HASH_ALGORITHM,
        "raw_source_text_included": False,
        "source_span_hash_count": len(source_span_hashes),
        "source_text_length": len(source_text),
        "source_text_sha256": _hash_text(source_text),
        "stripped_dense_input_key_hashes": [
            _hash_text(str(value)) for value in stripped_input_keys
        ],
    }


def _priority_score(
    introspection: Mapping[str, Any],
    *,
    per_family_gaps: Sequence[Mapping[str, Any]],
    compiler_round_trip_gaps: Mapping[str, Any],
    proof_status: Mapping[str, Any],
) -> float:
    family_gap = max(
        (abs(_float_or_zero(row.get("probability_gap"))) for row in per_family_gaps),
        default=0.0,
    )
    losses = [
        _float_or_zero(compiler_round_trip_gaps.get("embedding_cosine_gap")),
        _float_or_zero(compiler_round_trip_gaps.get("reconstruction_loss")),
        _float_or_zero(compiler_round_trip_gaps.get("legal_ir_view_cross_entropy_excess_loss")),
        _float_or_zero(compiler_round_trip_gaps.get("source_decompiled_text_embedding_cosine_loss")),
        _float_or_zero(compiler_round_trip_gaps.get("source_decompiled_text_token_loss")),
        max(
            (_float_or_zero(value) for value in _mapping(compiler_round_trip_gaps.get("component_gaps")).values()),
            default=0.0,
        ),
        (
            _float_or_zero(proof_status.get("failure_ratio"))
            if int(_float_or_zero(proof_status.get("attempted_count"))) > 0
            else 0.0
        ),
        max(0.0, -_float_or_zero(introspection.get("family_margin"))),
        family_gap,
    ]
    return round(max(losses), 12)


def _cap_packet(
    packet: Mapping[str, Any],
    config: IntrospectionPacketExportConfig,
) -> Dict[str, Any]:
    capped = json.loads(_stable_json(packet))
    max_bytes = int(config.max_packet_bytes)
    if max_bytes <= 0:
        raise ValueError("max_packet_bytes must be positive")
    truncation = capped.setdefault("truncation", {})
    truncation.setdefault("max_packet_bytes", max_bytes)
    truncation.setdefault(
        "original_ranked_feature_count",
        len(capped.get("ranked_feature_contributions", []) or []),
    )
    truncation.setdefault(
        "original_source_span_hash_count",
        len(_mapping(capped.get("sample_hashes")).get("source_span_hashes", {}) or {}),
    )

    if _json_size(capped) <= max_bytes:
        truncation["truncated"] = bool(truncation.get("truncated", False))
        return capped

    truncation["truncated"] = True
    for feature in capped.get("ranked_feature_contributions", []) or []:
        if isinstance(feature, dict):
            feature.pop("metadata", None)
    _trim_until_fits(
        capped,
        max_bytes,
        [
            lambda data: _pop_last(data.get("synthesis_hints")),
            lambda data: _pop_last(data.get("synthesis_focus")),
            lambda data: _pop_mapping_last(_nested_get(data, "compiler_round_trip_gaps", "component_gaps")),
            lambda data: _pop_mapping_last(_nested_get(data, "sample_hashes", "source_span_hashes")),
            lambda data: _pop_mapping_last(_nested_get(data, "learned_view_gaps", "view_gap_distribution")),
            lambda data: _pop_mapping_last(_nested_get(data, "legal_ir_views", "canonical", "view_distribution")),
            lambda data: _pop_mapping_last(_nested_get(data, "legal_ir_views", "predicted", "view_distribution")),
            lambda data: _pop_mapping_last(_nested_get(data, "legal_ir_views", "canonical", "family_distribution")),
            lambda data: _pop_mapping_last(_nested_get(data, "legal_ir_views", "predicted", "family_distribution")),
            lambda data: _pop_last(data.get("per_family_gaps")),
            lambda data: _pop_last(data.get("ranked_feature_contributions")),
            lambda data: _pop_last(_nested_get(data, "proof_route_status", "details")),
        ],
    )
    if _json_size(capped) > max_bytes:
        capped = _minimal_packet(capped)
        capped.setdefault("truncation", {})["truncated"] = True
        capped["truncation"]["minimal_packet"] = True
        capped["truncation"]["max_packet_bytes"] = max_bytes
    if _json_size(capped) > max_bytes:
        raise ValueError(
            "max_packet_bytes is too small for the required disagreement packet envelope"
        )
    return capped


def _minimal_packet(packet: Mapping[str, Any]) -> Dict[str, Any]:
    sample_hashes = _mapping(packet.get("sample_hashes"))
    legal_views = _mapping(packet.get("legal_ir_views"))
    canonical = _mapping(legal_views.get("canonical"))
    predicted = _mapping(legal_views.get("predicted"))
    anti_copy = _mapping(packet.get("anti_copy_evidence"))
    proof_status = _mapping(packet.get("proof_route_status"))
    return {
        "anti_copy_evidence": {
            "dense_weight_tables_included": False,
            "exact_source_spans_included": False,
            "raw_source_text_included": False,
        },
        "compiler_decompiler_metrics": _mapping(packet.get("compiler_decompiler_metrics")),
        "compiler_round_trip_gaps": {
            key: value
            for key, value in _mapping(packet.get("compiler_round_trip_gaps")).items()
            if key
            in {
                "cosine_loss",
                "embedding_cosine_gap",
                "source_decompiled_text_embedding_cosine_loss",
                "source_decompiled_text_token_loss",
            }
        },
        "evidence_id": str(packet.get("evidence_id") or ""),
        "evidence_hashes": _mapping(packet.get("evidence_hashes")),
        "legal_ir_views": {
            "canonical": {
                "modal_ir_hash": canonical.get("modal_ir_hash", ""),
            },
            "predicted": {
                "predicted_family": predicted.get("predicted_family", ""),
                "target_family": predicted.get("target_family", ""),
            },
        },
        "learned_view_gaps": {
            key: value
            for key, value in _mapping(packet.get("learned_view_gaps")).items()
            if key in {"cross_entropy_excess_loss", "cross_entropy_loss"}
        },
        "per_family_gaps": [],
        "priority_score": packet.get("priority_score", 0.0),
        "proof_route_status": {
            key: value
            for key, value in proof_status.items()
            if key
            in {
                "attempted_count",
                "compiles",
                "failure_ratio",
                "route_status",
                "valid_count",
                "verified_by",
            }
        },
        "ranked_feature_contributions": [],
        "sample_hashes": {
            "modal_ir_hash": sample_hashes.get("modal_ir_hash", ""),
            "sample_hash": sample_hashes.get("sample_hash", ""),
            "sample_id": sample_hashes.get("sample_id", ""),
        },
        "run_context": _mapping(packet.get("run_context")),
        "schema_version": packet.get("schema_version", INTROSPECTION_EXPORT_SCHEMA_VERSION),
        "synthesis_focus": [],
        "synthesis_hints": [],
        "truncation": _mapping(packet.get("truncation")),
        "versions": {
            key: value
            for key, value in _mapping(packet.get("versions")).items()
            if key in {"export_schema_version", "state_version"}
        },
    }


def _trim_until_fits(
    data: Dict[str, Any],
    max_bytes: int,
    trimmers: Sequence[Any],
) -> None:
    changed = True
    while _json_size(data) > max_bytes and changed:
        changed = False
        for trim in trimmers:
            while _json_size(data) > max_bytes and trim(data):
                changed = True


def _pop_last(value: Any) -> bool:
    if isinstance(value, list) and value:
        value.pop()
        return True
    return False


def _pop_mapping_last(value: Any) -> bool:
    if isinstance(value, dict) and value:
        key = sorted(value)[-1]
        value.pop(key, None)
        return True
    return False


def _nested_get(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _evidence_id(packet: Mapping[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("evidence_id", None)
    return "lir-disagree-" + _hash_json(payload)[:20]


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(data),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_size(data: Mapping[str, Any]) -> int:
    return len(_stable_json(data).encode("utf-8"))


def _hash_json(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_safe(data),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _is_dense_key(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value if not _is_dense_sequence(item)]
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return 0.0
        return round(value, 12)
    return str(value)


def _is_dense_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _DENSE_FIELD_ALLOWED_KEYS:
        return False
    return (
        any(token in lowered for token in _DENSE_FIELD_TOKENS)
        or lowered.endswith("_weights")
        or lowered.endswith("_weight_table")
        or lowered.endswith("_weight_tables")
    )


def _is_dense_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) > 8 and all(
        isinstance(item, (int, float)) for item in value
    )


def _dense_keys(value: Any, *, prefix: str = "") -> List[str]:
    keys: List[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_dense_key(key_text) or _is_dense_sequence(item):
                keys.append(path)
                continue
            keys.extend(_dense_keys(item, prefix=path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value[:8]):
            keys.extend(_dense_keys(item, prefix=f"{prefix}[{index}]"))
    return keys


def _contains_dense_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_dense_key(str(key)) or _is_dense_sequence(item):
                return True
            if _contains_dense_key(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_dense_key(item) for item in value)
    return False


def _numeric_mapping(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, float] = {}
    for key, item in value.items():
        number = _float_or_none(item)
        if number is not None and math.isfinite(number):
            result[str(key)] = float(number)
    return dict(sorted(result.items()))


def _top_numeric_mapping(
    value: Any,
    *,
    limit: int,
    signed: bool = False,
) -> Dict[str, float]:
    mapping = _numeric_mapping(value)
    rows = sorted(
        mapping.items(),
        key=lambda item: (
            -abs(float(item[1])) if signed else -float(item[1]),
            str(item[0]),
        ),
    )
    return {key: round(float(number), 12) for key, number in rows[:limit]}


def _normalize_distribution(value: Mapping[str, float]) -> Dict[str, float]:
    clean = {str(key): max(0.0, float(item)) for key, item in value.items()}
    total = sum(clean.values())
    if total <= 0.0:
        return {}
    return {key: round(item / total, 12) for key, item in sorted(clean.items())}


def _mapping_sequence(value: Any) -> List[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _compact_metadata(value: Mapping[str, Any], *, limit: int = 6) -> Dict[str, Any]:
    rows: Dict[str, Any] = {}
    for key, item in sorted(value.items()):
        if _is_dense_key(str(key)) or _is_dense_sequence(item):
            continue
        if isinstance(item, (str, bool)) or item is None:
            rows[str(key)] = item
        elif isinstance(item, (int, float)):
            rows[str(key)] = round(_float_or_zero(item), 12)
        if len(rows) >= limit:
            break
    return rows


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(resolved):
        return None
    return resolved


def _float_or_zero(value: Any) -> float:
    resolved = _float_or_none(value)
    return resolved if resolved is not None else 0.0


__all__ = [
    "INTROSPECTION_EXPORT_CONFIG_VERSION",
    "INTROSPECTION_EXPORT_SCHEMA_VERSION",
    "IntrospectionPacketExportConfig",
    "LegalIRDisagreementPacket",
    "append_disagreement_packets_jsonl",
    "export_autoencoder_disagreement_packet",
    "export_introspection_packet",
    "export_prioritized_disagreement_packets",
    "introspection_export_mode_enabled",
    "packet_to_json",
    "validate_disagreement_packet",
]
