"""External legal-expert benchmark packets for LegalIR evaluation.

External expert-authored examples are useful promotion evidence, but they are
not training data and they are not hyperparameter-selection data.  This module
defines the packet contract and the small deterministic evaluator used to keep
external validity separate from internal canary metrics.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_premise_security import (
    LegalIRArtifactUse,
    scan_legal_ir_artifact,
)

from .legal_ir_eval_splits import (
    EXTERNAL_TEST_SPLIT,
    HPARAM_SELECTION_OPERATION,
    TRAINING_OPERATION,
    LegalIRSplitExample,
    LegalIRSplitManifest,
    authorize_legal_ir_split_use,
)
from .legal_ir_family_evaluator import canonical_legal_ir_evaluation_family
from .legal_ir_semantic_metrics import (
    SEMANTIC_EQUIVALENCE_METRICS,
    evaluate_legal_ir_semantic_equivalence,
)


LEGAL_IR_EXTERNAL_BENCHMARK_SCHEMA_VERSION: Final = (
    "legal-ir-external-expert-benchmark-v1"
)
LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION: Final = (
    "legal-ir-external-benchmark-report-v1"
)
EXTERNAL_BENCHMARK_HARD_GUARDRAIL: Final = (
    "external_benchmark_never_training_data"
)
EXTERNAL_EVALUATION_OPERATION: Final = "external_evaluation"

_ADJUDICATION_STATUSES: Final = frozenset(
    {"accepted", "adjudicated", "expert_authored", "reviewed"}
)
_TRAINING_BLOCKED_OPERATIONS: Final = frozenset(
    {TRAINING_OPERATION, HPARAM_SELECTION_OPERATION}
)


class LegalIRExternalBenchmarkError(ValueError):
    """Base error for invalid external benchmark packets."""


class LegalIRExternalBenchmarkPolicyError(LegalIRExternalBenchmarkError):
    """Raised when external benchmark packets are requested for training use."""


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LegalIRExternalBenchmarkError("external benchmark contains a non-finite float")
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


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string(value: Any) -> str:
    return str(value or "").strip()


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_string(value),) if _string(value) else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(_string(item) for item in value if _string(item))
    return (_string(value),) if _string(value) else ()


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _canonical_family(value: str) -> str:
    try:
        return canonical_legal_ir_evaluation_family(value)
    except ValueError as exc:
        raise LegalIRExternalBenchmarkError(str(exc)) from exc


def _canonical_families(value: Any) -> tuple[str, ...]:
    families = tuple(dict.fromkeys(_canonical_family(item) for item in _strings(value)))
    if not families:
        raise LegalIRExternalBenchmarkError("expected_ir_families must be non-empty")
    return families


def _citation_cluster(value: str) -> str:
    text = str(value or "").lower().replace("§", " ")
    text = re.sub(r"\bu\.?\s*s\.?\s*c\.?\b", "usc", text)
    match = re.search(r"\b(\d+)\s*usc\s*([0-9a-z.-]+)", text)
    if match:
        return f"usc:{match.group(1)}:{match.group(2).rstrip('.')}"
    return re.sub(r"[^a-z0-9]+", ":", text).strip(":")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class ExternalBenchmarkCitation:
    """A required citation anchoring one expert-authored benchmark packet."""

    citation: str
    source_id: str
    jurisdiction: str = ""
    url: str = ""
    span: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExternalBenchmarkCitation":
        return cls(
            citation=_string(value.get("citation") or value.get("text")),
            source_id=_string(value.get("source_id") or value.get("source_document_id")),
            jurisdiction=_string(value.get("jurisdiction")),
            url=_string(value.get("url") or value.get("source_url")),
            span=dict(_mapping(value.get("span") or value.get("source_span"))),
        )

    def __post_init__(self) -> None:
        if not self.citation:
            raise LegalIRExternalBenchmarkError("citation text must be non-empty")
        if not self.source_id:
            raise LegalIRExternalBenchmarkError("citation source_id must be non-empty")
        object.__setattr__(self, "span", _json_value(self.span))

    @property
    def cluster(self) -> str:
        return _citation_cluster(self.citation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "citation_cluster": self.cluster,
            "jurisdiction": self.jurisdiction,
            "source_id": self.source_id,
            "span": dict(self.span),
            "url": self.url,
        }


@dataclass(frozen=True, slots=True)
class ProofObligationExpectation:
    """Expert-authored proof obligation expected from a candidate IR."""

    obligation_id: str
    family: str
    statement: str
    required: bool = True
    acceptance_criteria: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProofObligationExpectation":
        return cls(
            obligation_id=_string(value.get("obligation_id") or value.get("id")),
            family=_string(value.get("family") or value.get("ir_family")),
            statement=_string(value.get("statement") or value.get("description")),
            required=_bool(value.get("required"), default=True),
            acceptance_criteria=_strings(value.get("acceptance_criteria")),
        )

    def __post_init__(self) -> None:
        if not self.obligation_id:
            raise LegalIRExternalBenchmarkError("proof obligation id must be non-empty")
        object.__setattr__(self, "family", _canonical_family(self.family))
        if not self.statement:
            raise LegalIRExternalBenchmarkError("proof obligation statement must be non-empty")
        object.__setattr__(
            self,
            "acceptance_criteria",
            tuple(dict.fromkeys(self.acceptance_criteria)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "family": self.family,
            "obligation_id": self.obligation_id,
            "required": self.required,
            "statement": self.statement,
        }


@dataclass(frozen=True, slots=True)
class DecompilerExpectation:
    """Expected decompiler surface behavior for an external benchmark packet."""

    expected_reading: str = ""
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    round_trip_required: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DecompilerExpectation":
        return cls(
            expected_reading=_string(value.get("expected_reading") or value.get("text")),
            required_terms=_strings(value.get("required_terms")),
            forbidden_terms=_strings(value.get("forbidden_terms")),
            round_trip_required=_bool(value.get("round_trip_required"), default=True),
        )

    def __post_init__(self) -> None:
        if not self.expected_reading and not self.required_terms:
            raise LegalIRExternalBenchmarkError(
                "decompiler expectations require expected_reading or required_terms"
            )
        object.__setattr__(self, "required_terms", tuple(dict.fromkeys(self.required_terms)))
        object.__setattr__(self, "forbidden_terms", tuple(dict.fromkeys(self.forbidden_terms)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_reading": self.expected_reading,
            "forbidden_terms": list(self.forbidden_terms),
            "required_terms": list(self.required_terms),
            "round_trip_required": self.round_trip_required,
        }


@dataclass(frozen=True, slots=True)
class ExternalLegalExpertBenchmarkPacket:
    """Versioned expert-authored LegalIR external benchmark packet."""

    packet_id: str
    source_text: str
    expected_ir_families: tuple[str, ...]
    citations: tuple[ExternalBenchmarkCitation, ...]
    proof_obligations: tuple[ProofObligationExpectation, ...]
    decompiler_expectations: DecompilerExpectation
    adjudication_metadata: Mapping[str, Any]
    acceptable_ambiguity: Mapping[str, Any] = field(default_factory=dict)
    reference_ir: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    source_document_id: str = ""
    split: str = EXTERNAL_TEST_SPLIT
    training_eligible: bool = False
    hparam_selection_eligible: bool = False
    schema_version: str = LEGAL_IR_EXTERNAL_BENCHMARK_SCHEMA_VERSION

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "ExternalLegalExpertBenchmarkPacket":
        citations = tuple(
            ExternalBenchmarkCitation.from_mapping(item)
            for item in value.get("citations", ())
            if isinstance(item, Mapping)
        )
        obligations = tuple(
            ProofObligationExpectation.from_mapping(item)
            for item in value.get("proof_obligations", ())
            if isinstance(item, Mapping)
        )
        return cls(
            packet_id=_string(value.get("packet_id") or value.get("id")),
            source_text=_string(value.get("source_text") or value.get("text")),
            expected_ir_families=_canonical_families(value.get("expected_ir_families")),
            citations=citations,
            proof_obligations=obligations,
            decompiler_expectations=DecompilerExpectation.from_mapping(
                _mapping(value.get("decompiler_expectations"))
            ),
            adjudication_metadata=dict(_mapping(value.get("adjudication_metadata"))),
            acceptable_ambiguity=dict(_mapping(value.get("acceptable_ambiguity"))),
            reference_ir=dict(_mapping(value.get("reference_ir"))),
            tags=_strings(value.get("tags")),
            source_document_id=_string(value.get("source_document_id")),
            split=_string(value.get("split") or EXTERNAL_TEST_SPLIT),
            training_eligible=_bool(value.get("training_eligible"), default=False),
            hparam_selection_eligible=_bool(
                value.get("hparam_selection_eligible"),
                default=False,
            ),
            schema_version=_string(
                value.get("schema_version") or LEGAL_IR_EXTERNAL_BENCHMARK_SCHEMA_VERSION
            ),
        )

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_IR_EXTERNAL_BENCHMARK_SCHEMA_VERSION:
            raise LegalIRExternalBenchmarkError("unsupported external benchmark schema version")
        if not self.packet_id:
            raise LegalIRExternalBenchmarkError("packet_id must be non-empty")
        if not self.source_text:
            raise LegalIRExternalBenchmarkError("source_text must be non-empty")
        if self.split != EXTERNAL_TEST_SPLIT:
            raise LegalIRExternalBenchmarkError("external benchmark packets must use external_test split")
        if self.training_eligible or self.hparam_selection_eligible:
            raise LegalIRExternalBenchmarkError(
                "external benchmark packets must not be training or hparam-selection eligible"
            )
        if not self.citations:
            raise LegalIRExternalBenchmarkError("at least one citation is required")
        if not self.proof_obligations:
            raise LegalIRExternalBenchmarkError("at least one proof obligation is required")
        object.__setattr__(
            self,
            "expected_ir_families",
            tuple(dict.fromkeys(_canonical_family(item) for item in self.expected_ir_families)),
        )
        object.__setattr__(
            self,
            "acceptable_ambiguity",
            _normalize_ambiguity(self.acceptable_ambiguity),
        )
        object.__setattr__(self, "adjudication_metadata", _normalize_adjudication(self.adjudication_metadata))
        object.__setattr__(self, "reference_ir", _json_value(self.reference_ir))
        object.__setattr__(self, "tags", tuple(dict.fromkeys(self.tags)))

        security = scan_legal_ir_artifact(
            self.to_dict(include_digest=False, include_security=False),
            artifact_id=self.packet_id,
            artifact_role=LegalIRArtifactUse.PROOF.value,
        )
        if security.rejected:
            raise LegalIRExternalBenchmarkError(
                "external benchmark packet rejected by premise security: "
                + ",".join(security.rejection_reasons)
            )

    @property
    def digest(self) -> str:
        return "sha256:" + _stable_digest(self.to_dict(include_digest=False))

    @property
    def required_proof_obligation_ids(self) -> tuple[str, ...]:
        return tuple(
            obligation.obligation_id
            for obligation in self.proof_obligations
            if obligation.required
        )

    @property
    def citation_clusters(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(citation.cluster for citation in self.citations))

    def split_sample(self) -> Mapping[str, Any]:
        primary = self.citations[0]
        span = primary.span
        return {
            "citation": primary.citation,
            "citations": [citation.citation for citation in self.citations],
            "jurisdiction": primary.jurisdiction,
            "sample_id": self.packet_id,
            "source": "external_test",
            "source_document_id": self.source_document_id or primary.source_id,
            "span_end": span.get("end") if isinstance(span, Mapping) else None,
            "span_start": span.get("start") if isinstance(span, Mapping) else None,
            "statute_family": self.tags[0] if self.tags else "external_expert",
            "text": self.source_text,
        }

    def to_dict(
        self,
        *,
        include_digest: bool = True,
        include_security: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "acceptable_ambiguity": _json_value(self.acceptable_ambiguity),
            "adjudication_metadata": _json_value(self.adjudication_metadata),
            "citations": [citation.to_dict() for citation in self.citations],
            "decompiler_expectations": self.decompiler_expectations.to_dict(),
            "expected_ir_families": list(self.expected_ir_families),
            "hparam_selection_eligible": False,
            "packet_id": self.packet_id,
            "proof_obligations": [
                obligation.to_dict() for obligation in self.proof_obligations
            ],
            "reference_ir": _json_value(self.reference_ir),
            "schema_version": self.schema_version,
            "source_document_id": self.source_document_id,
            "source_text": self.source_text,
            "split": EXTERNAL_TEST_SPLIT,
            "tags": list(self.tags),
            "training_eligible": False,
            "use_policy": {
                "allowed_operations": [EXTERNAL_EVALUATION_OPERATION],
                "blocked_operations": [
                    TRAINING_OPERATION,
                    HPARAM_SELECTION_OPERATION,
                ],
                "excluded_from_hparam_selection": True,
                "excluded_from_training": True,
                "hard_guardrail": EXTERNAL_BENCHMARK_HARD_GUARDRAIL,
            },
        }
        if include_digest:
            payload["packet_digest"] = self.digest
        if include_security:
            payload["premise_security"] = scan_legal_ir_artifact(
                {key: item for key, item in payload.items() if key != "premise_security"},
                artifact_id=self.packet_id,
                artifact_role=LegalIRArtifactUse.PROOF.value,
            ).to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class ExternalBenchmarkPacketResult:
    """External validity result for one packet."""

    packet_id: str
    accepted: bool
    scores: Mapping[str, float]
    block_reasons: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def minimum_score(self) -> float:
        return min(self.scores.values()) if self.scores else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "block_reasons": list(self.block_reasons),
            "detail": _json_value(self.detail),
            "minimum_score": round(self.minimum_score, 12),
            "packet_id": self.packet_id,
            "scores": {key: round(value, 12) for key, value in sorted(self.scores.items())},
            "status": "accepted" if self.accepted else "failed",
        }


@dataclass(frozen=True, slots=True)
class ExternalBenchmarkReport:
    """External-validity report, intentionally separate from canary metrics."""

    packet_results: tuple[ExternalBenchmarkPacketResult, ...]
    benchmark_digest: str
    internal_canary_metrics: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION

    @property
    def accepted(self) -> bool:
        return all(result.accepted for result in self.packet_results)

    @property
    def external_validity_score(self) -> float:
        if not self.packet_results:
            return 0.0
        return sum(1.0 for result in self.packet_results if result.accepted) / len(self.packet_results)

    @property
    def failed_packet_ids(self) -> tuple[str, ...]:
        return tuple(result.packet_id for result in self.packet_results if not result.accepted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "benchmark_digest": self.benchmark_digest,
            "external_validity": {
                "accepted_packet_count": len(self.packet_results) - len(self.failed_packet_ids),
                "external_validity_score": round(self.external_validity_score, 12),
                "failed_packet_ids": list(self.failed_packet_ids),
                "packet_count": len(self.packet_results),
                "packet_results": [result.to_dict() for result in self.packet_results],
            },
            "hard_guardrail": EXTERNAL_BENCHMARK_HARD_GUARDRAIL,
            "internal_canary_metrics": _json_value(self.internal_canary_metrics),
            "schema_version": self.schema_version,
            "separate_from_internal_canary_metrics": True,
            "status": "accepted" if self.accepted else "blocked",
        }


def load_external_expert_benchmark_packets(
    path: str | Path,
) -> tuple[ExternalLegalExpertBenchmarkPacket, ...]:
    """Load a JSONL file of external expert benchmark packets."""

    packets: list[ExternalLegalExpertBenchmarkPacket] = []
    source = Path(path)
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise LegalIRExternalBenchmarkError("line is not a JSON object")
            packets.append(ExternalLegalExpertBenchmarkPacket.from_mapping(payload))
        except (json.JSONDecodeError, LegalIRExternalBenchmarkError) as exc:
            raise LegalIRExternalBenchmarkError(
                f"invalid external benchmark packet at {source}:{line_number}: {exc}"
            ) from exc
    return tuple(packets)


def external_benchmark_split_manifest(
    packets: Sequence[ExternalLegalExpertBenchmarkPacket],
) -> LegalIRSplitManifest:
    """Return a manifest that pins every external packet to ``external_test``."""

    resolved = tuple(packets)
    examples = tuple(
        LegalIRSplitExample.from_sample(packet.split_sample()) for packet in resolved
    )
    assignments = {packet.packet_id: EXTERNAL_TEST_SPLIT for packet in resolved}
    return LegalIRSplitManifest(
        examples=examples,
        assignments=assignments,
        config_digest="sha256:" + _stable_digest([packet.digest for packet in resolved]),
        protected_splits=(EXTERNAL_TEST_SPLIT,),
        metadata={
            "hard_guardrail": EXTERNAL_BENCHMARK_HARD_GUARDRAIL,
            "source": "external_legal_expert_benchmark",
        },
    )


def require_external_benchmark_evaluation_only(
    packets: Sequence[ExternalLegalExpertBenchmarkPacket],
    *,
    operation: str,
) -> None:
    """Fail closed when external benchmark packets are requested for training use."""

    normalized = str(operation or "").strip().lower()
    if normalized != EXTERNAL_EVALUATION_OPERATION:
        manifest = external_benchmark_split_manifest(packets)
        try:
            authorize_legal_ir_split_use(
                manifest,
                operation=normalized,
                items=[{"sample_id": packet.packet_id} for packet in packets],
            )
        except Exception as exc:
            if normalized in _TRAINING_BLOCKED_OPERATIONS:
                raise LegalIRExternalBenchmarkPolicyError(
                    f"external benchmark packets are blocked from {normalized}"
                ) from exc
            raise
    for packet in packets:
        if packet.training_eligible or packet.hparam_selection_eligible:
            raise LegalIRExternalBenchmarkPolicyError(
                "external benchmark packet claims forbidden training eligibility"
            )


def evaluate_external_legal_expert_benchmark(
    packets: Sequence[ExternalLegalExpertBenchmarkPacket],
    predictions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    internal_canary_metrics: Mapping[str, Any] | None = None,
) -> ExternalBenchmarkReport:
    """Evaluate candidate outputs against external expert benchmark packets."""

    resolved = tuple(packets)
    require_external_benchmark_evaluation_only(
        resolved,
        operation=EXTERNAL_EVALUATION_OPERATION,
    )
    by_packet = _prediction_mapping(predictions)
    results = tuple(
        _evaluate_packet(packet, _mapping(by_packet.get(packet.packet_id)))
        for packet in resolved
    )
    return ExternalBenchmarkReport(
        packet_results=results,
        benchmark_digest="sha256:" + _stable_digest([packet.digest for packet in resolved]),
        internal_canary_metrics=dict(internal_canary_metrics or {}),
    )


def _normalize_ambiguity(value: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _json_value(value)
    alternatives: dict[str, list[str]] = {}
    raw_alternatives = _mapping(payload.get("acceptable_family_alternatives"))
    for family, raw_values in raw_alternatives.items():
        alternatives[_canonical_family(family)] = [
            _canonical_family(item) for item in _strings(raw_values)
        ]
    optional = [_canonical_family(item) for item in _strings(payload.get("optional_families"))]
    return {
        **dict(payload),
        "acceptable_family_alternatives": alternatives,
        "allowed": _bool(payload.get("allowed"), default=bool(alternatives or optional)),
        "optional_families": optional,
    }


def _normalize_adjudication(value: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _json_value(value)
    expert_id = _string(payload.get("expert_id") or payload.get("author_id"))
    expert_role = _string(payload.get("expert_role") or payload.get("author_role"))
    authored_at = _string(payload.get("authored_at"))
    status = _string(payload.get("review_status") or payload.get("status")).lower()
    if not expert_id or not expert_role or not authored_at:
        raise LegalIRExternalBenchmarkError(
            "adjudication_metadata requires expert_id, expert_role, and authored_at"
        )
    if status not in _ADJUDICATION_STATUSES:
        raise LegalIRExternalBenchmarkError(
            "adjudication_metadata review_status must be expert-authored or adjudicated"
        )
    if _bool(payload.get("training_eligible"), default=False) or _bool(
        payload.get("hparam_selection_eligible"),
        default=False,
    ):
        raise LegalIRExternalBenchmarkError(
            "adjudication metadata must not mark external packets training eligible"
        )
    return {
        **dict(payload),
        "external_evaluation_only": True,
        "hparam_selection_eligible": False,
        "review_status": status,
        "training_eligible": False,
    }


def _prediction_mapping(
    predictions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if isinstance(predictions, Mapping):
        if "packet_id" in predictions:
            return {_string(predictions.get("packet_id")): predictions}
        return predictions
    result: dict[str, Mapping[str, Any]] = {}
    for item in predictions:
        if isinstance(item, Mapping):
            packet_id = _string(item.get("packet_id") or item.get("id"))
            if packet_id:
                result[packet_id] = item
    return result


def _evaluate_packet(
    packet: ExternalLegalExpertBenchmarkPacket,
    prediction: Mapping[str, Any],
) -> ExternalBenchmarkPacketResult:
    family_score, family_detail, family_blocks = _family_score(packet, prediction)
    citation_score, citation_detail, citation_blocks = _citation_score(packet, prediction)
    proof_score, proof_detail, proof_blocks = _proof_score(packet, prediction)
    decompiler_score, decompiler_detail, decompiler_blocks = _decompiler_score(packet, prediction)
    semantic_score, semantic_detail, semantic_blocks = _semantic_score(packet, prediction)
    scores = {
        "citations": citation_score,
        "decompiler_expectations": decompiler_score,
        "expected_ir_families": family_score,
        "proof_obligations": proof_score,
        "semantic_equivalence": semantic_score,
    }
    block_reasons = tuple(
        dict.fromkeys(
            [
                *family_blocks,
                *citation_blocks,
                *proof_blocks,
                *decompiler_blocks,
                *semantic_blocks,
            ]
        )
    )
    return ExternalBenchmarkPacketResult(
        packet_id=packet.packet_id,
        accepted=not block_reasons,
        scores=scores,
        block_reasons=block_reasons,
        detail={
            "acceptable_ambiguity": packet.acceptable_ambiguity,
            "citations": citation_detail,
            "decompiler_expectations": decompiler_detail,
            "expected_ir_families": family_detail,
            "proof_obligations": proof_detail,
            "semantic_equivalence": semantic_detail,
        },
    )


def _family_score(
    packet: ExternalLegalExpertBenchmarkPacket,
    prediction: Mapping[str, Any],
) -> tuple[float, Mapping[str, Any], tuple[str, ...]]:
    predicted = _predicted_families(prediction)
    optional = set(_strings(packet.acceptable_ambiguity.get("optional_families")))
    alternatives = _mapping(packet.acceptable_ambiguity.get("acceptable_family_alternatives"))
    required = tuple(family for family in packet.expected_ir_families if family not in optional)
    covered: list[str] = []
    missing: list[str] = []
    alternative_hits: dict[str, str] = {}
    for family in required:
        if family in predicted:
            covered.append(family)
            continue
        alt_hit = next(
            (alternative for alternative in _strings(alternatives.get(family)) if alternative in predicted),
            "",
        )
        if alt_hit:
            covered.append(family)
            alternative_hits[family] = alt_hit
        else:
            missing.append(family)
    score = len(covered) / len(required) if required else 1.0
    return (
        score,
        {
            "acceptable_alternative_hits": alternative_hits,
            "expected": list(packet.expected_ir_families),
            "missing_required": missing,
            "predicted": list(predicted),
            "required": list(required),
        },
        ("missing_expected_ir_family",) if missing else (),
    )


def _predicted_families(prediction: Mapping[str, Any]) -> tuple[str, ...]:
    for key in (
        "predicted_ir_families",
        "ir_families",
        "families",
        "view_families",
        "expected_ir_families",
    ):
        raw = prediction.get(key)
        if raw:
            return tuple(
                dict.fromkeys(_canonical_family(item) for item in _strings(raw))
            )
    return ()


def _citation_score(
    packet: ExternalLegalExpertBenchmarkPacket,
    prediction: Mapping[str, Any],
) -> tuple[float, Mapping[str, Any], tuple[str, ...]]:
    predicted = _citation_clusters(prediction)
    required = packet.citation_clusters
    matched = tuple(cluster for cluster in required if cluster in predicted)
    score = len(matched) / len(required) if required else 1.0
    missing = tuple(cluster for cluster in required if cluster not in predicted)
    return (
        score,
        {"matched": list(matched), "missing": list(missing), "required": list(required)},
        ("missing_required_citation",) if missing else (),
    )


def _citation_clusters(prediction: Mapping[str, Any]) -> tuple[str, ...]:
    raw = prediction.get("citations") or prediction.get("citation") or ()
    values: list[str] = []
    if isinstance(raw, Mapping):
        values.extend(_strings(raw.get("citation") or raw.get("text")))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            if isinstance(item, Mapping):
                values.extend(_strings(item.get("citation") or item.get("text")))
            else:
                values.extend(_strings(item))
    else:
        values.extend(_strings(raw))
    return tuple(dict.fromkeys(_citation_cluster(item) for item in values if _citation_cluster(item)))


def _proof_score(
    packet: ExternalLegalExpertBenchmarkPacket,
    prediction: Mapping[str, Any],
) -> tuple[float, Mapping[str, Any], tuple[str, ...]]:
    required = packet.required_proof_obligation_ids
    predicted = _proof_obligation_ids(prediction)
    matched = tuple(obligation_id for obligation_id in required if obligation_id in predicted)
    score = len(matched) / len(required) if required else 1.0
    missing = tuple(obligation_id for obligation_id in required if obligation_id not in predicted)
    return (
        score,
        {"matched": list(matched), "missing": list(missing), "required": list(required)},
        ("missing_required_proof_obligation",) if missing else (),
    )


def _proof_obligation_ids(prediction: Mapping[str, Any]) -> tuple[str, ...]:
    raw = prediction.get("proof_obligations") or prediction.get("proof_obligation_ids") or ()
    ids: list[str] = []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            if isinstance(item, Mapping):
                ids.extend(_strings(item.get("obligation_id") or item.get("id")))
            else:
                ids.extend(_strings(item))
    else:
        ids.extend(_strings(raw))
    candidate_ir = prediction.get("candidate_ir") or prediction.get("predicted_ir")
    if isinstance(candidate_ir, Mapping):
        ids.extend(_ids_from_ir(candidate_ir))
    return tuple(dict.fromkeys(ids))


def _ids_from_ir(value: Any) -> tuple[str, ...]:
    ids: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key) in {"proof_obligation_ids", "proof_obligations", "obligation_id"}:
                    ids.extend(_strings(child))
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(_string(item) for item in ids if _string(item))


def _decompiler_score(
    packet: ExternalLegalExpertBenchmarkPacket,
    prediction: Mapping[str, Any],
) -> tuple[float, Mapping[str, Any], tuple[str, ...]]:
    expected = packet.decompiler_expectations
    text = _string(
        prediction.get("decompiled_text")
        or prediction.get("decompiler_output")
        or prediction.get("round_trip_text")
    ).lower()
    missing_terms = tuple(term for term in expected.required_terms if term.lower() not in text)
    forbidden_hits = tuple(term for term in expected.forbidden_terms if term.lower() in text)
    round_trip = prediction.get("round_trip_success")
    if round_trip is None:
        round_trip = prediction.get("decompiler_round_trip_preservation", True)
    round_trip_ok = (not expected.round_trip_required) or _bool(round_trip, default=False)
    checks = [
        not missing_terms,
        not forbidden_hits,
        round_trip_ok,
    ]
    score = sum(1.0 for item in checks if item) / len(checks)
    blocks: list[str] = []
    if missing_terms:
        blocks.append("decompiler_missing_required_terms")
    if forbidden_hits:
        blocks.append("decompiler_forbidden_terms_present")
    if not round_trip_ok:
        blocks.append("decompiler_round_trip_failed")
    return (
        score,
        {
            "forbidden_terms_present": list(forbidden_hits),
            "missing_required_terms": list(missing_terms),
            "round_trip_ok": round_trip_ok,
        },
        tuple(blocks),
    )


def _semantic_score(
    packet: ExternalLegalExpertBenchmarkPacket,
    prediction: Mapping[str, Any],
) -> tuple[float, Mapping[str, Any], tuple[str, ...]]:
    candidate_ir = prediction.get("candidate_ir") or prediction.get("predicted_ir")
    if not packet.reference_ir or not isinstance(candidate_ir, Mapping):
        return 1.0, {"available": False, "reason": "reference_or_candidate_ir_absent"}, ()
    result = evaluate_legal_ir_semantic_equivalence(
        packet.reference_ir,
        candidate_ir,
        family=packet.expected_ir_families[0],
    )
    failures = tuple(
        metric
        for metric in SEMANTIC_EQUIVALENCE_METRICS
        if result.scores.get(metric, 0.0) < 1.0
    )
    return (
        result.minimum_score,
        result.to_dict(),
        ("semantic_equivalence_failed",) if failures else (),
    )


__all__ = [
    "EXTERNAL_BENCHMARK_HARD_GUARDRAIL",
    "EXTERNAL_EVALUATION_OPERATION",
    "LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION",
    "LEGAL_IR_EXTERNAL_BENCHMARK_SCHEMA_VERSION",
    "DecompilerExpectation",
    "ExternalBenchmarkCitation",
    "ExternalBenchmarkPacketResult",
    "ExternalBenchmarkReport",
    "ExternalLegalExpertBenchmarkPacket",
    "LegalIRExternalBenchmarkError",
    "LegalIRExternalBenchmarkPolicyError",
    "ProofObligationExpectation",
    "evaluate_external_legal_expert_benchmark",
    "external_benchmark_split_manifest",
    "load_external_expert_benchmark_packets",
    "require_external_benchmark_evaluation_only",
]
