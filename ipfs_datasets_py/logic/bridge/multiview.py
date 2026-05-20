"""Multi-view legal IR evaluation across bridge adapters."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

from .registry import load_logic_bridge_adapter, logic_bridge_spec, logic_bridge_specs
from .types import BridgeEvaluationReport, LegalIRDocument, LogicIRView

_MULTIVIEW_CACHE_MAX_ITEMS = 1024
_MULTIVIEW_EVALUATION_CACHE: Dict[str, "MultiViewLegalIRReport"] = {}


@dataclass(frozen=True)
class LegalIRTrainingTarget:
    """Canonical optimizer target derived from a multi-view legal IR document."""

    bridge_names: Sequence[str]
    document: LegalIRDocument
    losses: Mapping[str, float] = field(default_factory=dict)
    adapter_losses: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    view_distribution: Mapping[str, float] = field(default_factory=dict)
    accepted: bool = False

    @property
    def total_loss(self) -> float:
        return float(self.losses.get("legal_ir_multiview_total_loss", 0.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adapter_losses": {
                name: dict(sorted(losses.items()))
                for name, losses in sorted(self.adapter_losses.items())
            },
            "bridge_names": list(self.bridge_names),
            "document_hash": self.document.canonical_hash(),
            "document_id": self.document.document_id,
            "document_version": self.document.version,
            "losses": dict(sorted(self.losses.items())),
            "total_loss": self.total_loss,
            "view_distribution": dict(sorted(self.view_distribution.items())),
        }


@dataclass(frozen=True)
class MultiViewLegalIRReport:
    """Canonical legal IR document plus the bridge reports that produced it."""

    bridge_names: Sequence[str]
    document: LegalIRDocument
    reports: Mapping[str, BridgeEvaluationReport] = field(default_factory=dict)
    failures: Mapping[str, str] = field(default_factory=dict)

    @property
    def attempted_count(self) -> int:
        return len(self.bridge_names)

    @property
    def accepted_count(self) -> int:
        return sum(1 for report in self.reports.values() if report.accepted)

    @property
    def acceptance_rate(self) -> float:
        if self.attempted_count <= 0:
            return 0.0
        return self.accepted_count / self.attempted_count

    @property
    def proof_failure_ratio(self) -> float:
        return _mean_with_failures(
            [report.proof_gate.failure_ratio for report in self.reports.values()],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    @property
    def graph_failure_penalty(self) -> float:
        return _mean_with_failures(
            [
                report.graph_projection.graph_failure_penalty
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    @property
    def total_loss(self) -> float:
        return _mean_with_failures(
            [report.total_loss for report in self.reports.values()],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    @property
    def view_count(self) -> int:
        return len(self.document.views)

    @property
    def accepted(self) -> bool:
        return (
            self.attempted_count > 0
            and not self.failures
            and len(self.reports) == self.attempted_count
            and all(report.accepted for report in self.reports.values())
        )

    def loss_vector(self) -> Dict[str, float]:
        """Return adapter-scoped losses for optimizer dashboards."""

        losses: Dict[str, float] = self.canonical_loss_vector()
        for adapter_name, report in sorted(self.reports.items()):
            prefix = _loss_prefix(adapter_name)
            round_trip = report.round_trip
            losses[f"{prefix}.cosine_loss"] = float(round_trip.cosine_loss)
            losses[f"{prefix}.cross_entropy_loss"] = float(round_trip.cross_entropy_loss)
            losses[f"{prefix}.graph_failure_penalty"] = float(
                report.graph_projection.graph_failure_penalty
            )
            losses[f"{prefix}.proof_failure_ratio"] = float(report.proof_gate.failure_ratio)
            losses[f"{prefix}.reconstruction_loss"] = float(round_trip.reconstruction_loss)
            losses[f"{prefix}.text_reconstruction_loss"] = float(
                round_trip.text_reconstruction_loss
            )
            losses[f"{prefix}.total_loss"] = float(report.total_loss)
            for name, value in sorted(round_trip.extra_losses.items()):
                losses[f"{prefix}.{name}"] = _float_or_zero(value)
        for adapter_name in sorted(self.failures):
            losses[f"{_loss_prefix(adapter_name)}.bridge_evaluation_failure_loss"] = 1.0
        return dict(sorted(losses.items()))

    def canonical_loss_vector(self) -> Dict[str, float]:
        """Return unscoped losses for treating the merged IR as one target."""

        return dict(
            sorted(
                {
                    "legal_ir_multiview_acceptance_loss": max(
                        0.0,
                        1.0 - self.acceptance_rate,
                    ),
                    "legal_ir_multiview_cosine_loss": self._round_trip_mean("cosine_loss"),
                    "legal_ir_multiview_cross_entropy_loss": self._round_trip_mean(
                        "cross_entropy_loss"
                    ),
                    "legal_ir_multiview_frame_logic_missing_loss": 0.0
                    if self.document.has_frame_logic
                    else 1.0,
                    "legal_ir_multiview_graph_failure_penalty": self.graph_failure_penalty,
                    "legal_ir_multiview_proof_failure_ratio": self.proof_failure_ratio,
                    "legal_ir_multiview_reconstruction_loss": self._round_trip_mean(
                        "reconstruction_loss"
                    ),
                    "legal_ir_multiview_text_reconstruction_loss": self._round_trip_mean(
                        "text_reconstruction_loss"
                    ),
                    "legal_ir_multiview_total_loss": self.total_loss,
                    "legal_ir_multiview_view_coverage_loss": self.view_coverage_loss(),
                }.items()
            )
        )

    def training_target(self) -> LegalIRTrainingTarget:
        """Return the merged legal IR document as the optimizer training target."""

        adapter_losses = {
            adapter_name: {
                key.split(".", 1)[1]: value
                for key, value in self.loss_vector().items()
                if key.startswith(f"{_loss_prefix(adapter_name)}.")
            }
            for adapter_name in self.bridge_names
        }
        return LegalIRTrainingTarget(
            bridge_names=tuple(self.bridge_names),
            document=self.document,
            losses=self.canonical_loss_vector(),
            adapter_losses=adapter_losses,
            view_distribution=self.view_distribution(),
            accepted=self.accepted,
        )

    def view_distribution(self) -> Dict[str, float]:
        """Return a normalised distribution over formal IR view source components."""

        counts: Dict[str, int] = {}
        for view in self.document.views.values():
            component = str(view.source_component or view.format or view.name)
            counts[component] = counts.get(component, 0) + 1
        total = float(sum(counts.values()))
        if total <= 0.0:
            return {}
        return {
            component: count / total
            for component, count in sorted(counts.items())
        }

    def view_coverage_loss(self) -> float:
        """Return missing expected bridge views as a compact loss."""

        expected_count = 0
        present_count = 0
        for adapter_name in self.bridge_names:
            try:
                expected_views = tuple(logic_bridge_spec(adapter_name).target_views)
            except KeyError:
                expected_views = ()
            if not expected_views:
                continue
            expected_count += len(expected_views)
            present_views = {
                str(view.metadata.get("original_view_name") or view.name)
                for view_name, view in self.document.views.items()
                if str(view_name).startswith(f"{adapter_name}.")
            }
            present_count += sum(1 for view_name in expected_views if view_name in present_views)
        if expected_count <= 0:
            return 0.0
        return max(0.0, 1.0 - min(1.0, present_count / expected_count))

    def _round_trip_mean(self, metric_name: str) -> float:
        return _mean_with_failures(
            [
                _float_or_zero(getattr(report.round_trip, metric_name, 0.0))
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "accepted_count": self.accepted_count,
            "acceptance_rate": self.acceptance_rate,
            "attempted_count": self.attempted_count,
            "bridge_names": list(self.bridge_names),
            "canonical_loss_vector": self.canonical_loss_vector(),
            "document": self.document.to_dict(),
            "failures": dict(sorted(self.failures.items())),
            "graph_failure_penalty": self.graph_failure_penalty,
            "loss_vector": self.loss_vector(),
            "proof_failure_ratio": self.proof_failure_ratio,
            "reports": {
                name: report.to_dict()
                for name, report in sorted(self.reports.items())
            },
            "total_loss": self.total_loss,
            "training_target": self.training_target().to_dict(),
            "view_count": self.view_count,
            "view_coverage_loss": self.view_coverage_loss(),
            "view_distribution": self.view_distribution(),
        }


def evaluate_legal_ir_multiview(
    text: str,
    *,
    bridge_names: Optional[Sequence[str]] = None,
    cache: bool = True,
    citation: Optional[str] = None,
    document_id: Optional[str] = None,
    evaluate_provers: Optional[bool] = None,
    source: str = "us_code",
    source_embedding: Optional[Sequence[float]] = None,
) -> MultiViewLegalIRReport:
    """Evaluate legal text through multiple bridge adapters as one IR document."""

    names = _bridge_names(bridge_names)
    cache_key = _multiview_cache_key(
        text,
        bridge_names=names,
        citation=citation,
        document_id=document_id,
        evaluate_provers=evaluate_provers,
        source=source,
        source_embedding=source_embedding,
    )
    if cache:
        cached = _MULTIVIEW_EVALUATION_CACHE.get(cache_key)
        if cached is not None:
            return cached

    reports: Dict[str, BridgeEvaluationReport] = {}
    failures: Dict[str, str] = {}
    for name in names:
        try:
            adapter = load_logic_bridge_adapter(name)
            reports[name] = _evaluate_adapter(
                adapter,
                text,
                citation=citation,
                document_id=document_id,
                evaluate_provers=evaluate_provers,
                source=source,
                source_embedding=source_embedding,
            )
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"

    document = _merge_reports_to_document(
        text,
        bridge_names=names,
        citation=citation,
        document_id=document_id,
        failures=failures,
        reports=reports,
        source=source,
    )
    result = MultiViewLegalIRReport(
        bridge_names=names,
        document=document,
        reports=reports,
        failures=failures,
    )
    if cache:
        if len(_MULTIVIEW_EVALUATION_CACHE) >= _MULTIVIEW_CACHE_MAX_ITEMS:
            _MULTIVIEW_EVALUATION_CACHE.pop(next(iter(_MULTIVIEW_EVALUATION_CACHE)))
        _MULTIVIEW_EVALUATION_CACHE[cache_key] = result
    return result


def _multiview_cache_key(
    text: str,
    *,
    bridge_names: Sequence[str],
    citation: Optional[str],
    document_id: Optional[str],
    evaluate_provers: Optional[bool],
    source: str,
    source_embedding: Optional[Sequence[float]],
) -> str:
    digest = hashlib.sha256()
    for value in (
        "\0".join(bridge_names),
        citation or "",
        document_id or "",
        str(evaluate_provers),
        source,
        text or "",
        _source_embedding_digest(source_embedding),
    ):
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_embedding_digest(source_embedding: Optional[Sequence[float]]) -> str:
    if source_embedding is None:
        return ""
    digest = hashlib.sha256()
    for value in source_embedding:
        try:
            digest.update(f"{float(value):.9g},".encode("ascii"))
        except (TypeError, ValueError):
            digest.update(str(value).encode("utf-8"))
            digest.update(b",")
    return digest.hexdigest()


def _evaluate_adapter(
    adapter: Any,
    text: str,
    *,
    citation: Optional[str],
    document_id: Optional[str],
    evaluate_provers: Optional[bool],
    source: str,
    source_embedding: Optional[Sequence[float]],
) -> BridgeEvaluationReport:
    kwargs: Dict[str, Any] = {
        "citation": citation,
        "document_id": document_id,
        "source": source,
        "source_embedding": source_embedding,
    }
    if evaluate_provers is not None:
        try:
            parameters = inspect.signature(adapter.evaluate).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "evaluate_provers" in parameters:
            kwargs["evaluate_provers"] = bool(evaluate_provers)
    return adapter.evaluate(text, **kwargs)


def _bridge_names(bridge_names: Optional[Sequence[str]]) -> tuple[str, ...]:
    if bridge_names is None:
        return tuple(spec.name for spec in logic_bridge_specs(implemented_only=True))
    return tuple(
        dict.fromkeys(
            str(name).strip()
            for name in bridge_names
            if str(name).strip()
            and str(name).strip().lower() not in {"none", "off", "false"}
        )
    )


def _merge_reports_to_document(
    text: str,
    *,
    bridge_names: Sequence[str],
    citation: Optional[str],
    document_id: Optional[str],
    failures: Mapping[str, str],
    reports: Mapping[str, BridgeEvaluationReport],
    source: str,
) -> LegalIRDocument:
    resolved_document_id = document_id or _document_id(text)
    normalized_text = " ".join(str(text or "").split())
    views: Dict[str, LogicIRView] = {}
    triples: list[Mapping[str, str]] = []
    seen_triples: set[tuple[str, str, str]] = set()

    for adapter_name, report in sorted(reports.items()):
        if report.ir_document.normalized_text:
            normalized_text = report.ir_document.normalized_text
        for view_name, view in sorted(report.ir_document.views.items()):
            key = f"{adapter_name}.{view_name}"
            views[key] = LogicIRView(
                name=key,
                format=view.format,
                source_component=view.source_component,
                payload=view.payload,
                metadata={
                    **dict(view.metadata),
                    "adapter_name": adapter_name,
                    "original_view_name": view_name,
                },
            )
        for triple in report.ir_document.frame_logic_triples:
            subject = str(triple.get("subject") or "")
            predicate = str(triple.get("predicate") or "")
            obj = str(triple.get("object") or "")
            triple_key = (subject, predicate, obj)
            if not all(triple_key) or triple_key in seen_triples:
                continue
            seen_triples.add(triple_key)
            triples.append({"subject": subject, "predicate": predicate, "object": obj})

    metadata = {
        "accepted_bridge_count": sum(1 for report in reports.values() if report.accepted),
        "attempted_bridge_count": len(bridge_names),
        "bridge_names": list(bridge_names),
        "failed_bridge_count": len(failures),
        "implemented_bridge_count": len(reports),
        "multiview_version": "legal-ir-multiview-v1",
        "view_count": len(views),
    }
    return LegalIRDocument(
        document_id=resolved_document_id,
        source_text=text,
        normalized_text=normalized_text,
        source=source,
        citation=citation or _first_citation(reports),
        views=views,
        frame_logic_triples=tuple(triples),
        metadata=metadata,
        version="legal-ir-multiview-v1",
    )


def _first_citation(reports: Mapping[str, BridgeEvaluationReport]) -> Optional[str]:
    for report in reports.values():
        if report.ir_document.citation:
            return report.ir_document.citation
    return None


def _mean_with_failures(
    values: Sequence[float],
    *,
    expected_count: int,
    failure_count: int,
) -> float:
    if expected_count <= 0:
        return 0.0
    total = sum(float(value) for value in values) + float(failure_count)
    return total / expected_count


def _document_id(text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"legal-ir-multiview:{digest}"


def _loss_prefix(adapter_name: str) -> str:
    return str(adapter_name or "bridge").replace("-", "_")


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "LegalIRTrainingTarget",
    "MultiViewLegalIRReport",
    "evaluate_legal_ir_multiview",
]
