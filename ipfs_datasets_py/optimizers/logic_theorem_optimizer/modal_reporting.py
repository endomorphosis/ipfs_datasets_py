"""Reporting helpers for deterministic modal legal parser runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping

from .legal_samples import LegalSample
from .modal_autoencoder import AutoencoderEvaluation
from .modal_prover_router import ModalProverRouteResult


@dataclass(frozen=True)
class ModalParserReport:
    """Compact report for modal parser quality dashboards."""

    sample_count: int
    modal_family_counts: Dict[str, int]
    frame_top1_accuracy: float
    reconstruction_loss: float
    parser_failures: List[str] = field(default_factory=list)
    prover_availability: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_top1_accuracy": self.frame_top1_accuracy,
            "modal_family_counts": dict(sorted(self.modal_family_counts.items())),
            "parser_failures": list(self.parser_failures),
            "prover_availability": dict(sorted(self.prover_availability.items())),
            "reconstruction_loss": self.reconstruction_loss,
            "sample_count": self.sample_count,
        }

    def to_markdown(self) -> str:
        """Render a short human-readable report."""
        lines = [
            "# Modal Parser Report",
            "",
            f"- Samples: {self.sample_count}",
            f"- Frame top-1 accuracy: {self.frame_top1_accuracy:.3f}",
            f"- Reconstruction loss: {self.reconstruction_loss:.6f}",
            f"- Parser failures: {len(self.parser_failures)}",
            "",
            "## Modal Families",
        ]
        for family, count in sorted(self.modal_family_counts.items()):
            lines.append(f"- {family}: {count}")
        lines.append("")
        lines.append("## Prover Availability")
        for status, count in sorted(self.prover_availability.items()):
            lines.append(f"- {status}: {count}")
        return "\n".join(lines)


def build_modal_parser_report(
    *,
    samples: Iterable[LegalSample],
    autoencoder: AutoencoderEvaluation | None = None,
    prover_results: Iterable[ModalProverRouteResult] = (),
    expected_frames: Mapping[str, str] | None = None,
) -> ModalParserReport:
    """Build a report from sample, reconstruction, and prover outputs."""
    sample_list = list(samples)
    expected = expected_frames or {}
    family_counts: Dict[str, int] = {}
    parser_failures: List[str] = []
    top1_hits = 0
    top1_total = 0

    for sample in sample_list:
        if not sample.modal_ir.formulas:
            parser_failures.append(sample.sample_id)
        for formula in sample.modal_ir.formulas:
            family_counts[formula.operator.family] = family_counts.get(formula.operator.family, 0) + 1
        if sample.sample_id in expected:
            top1_total += 1
            if sample.selected_frame == expected[sample.sample_id]:
                top1_hits += 1

    availability: Dict[str, int] = {}
    for result in prover_results:
        status = result.status.value
        availability[status] = availability.get(status, 0) + 1

    return ModalParserReport(
        sample_count=len(sample_list),
        modal_family_counts=family_counts,
        frame_top1_accuracy=(top1_hits / top1_total) if top1_total else 0.0,
        reconstruction_loss=autoencoder.reconstruction_loss if autoencoder else 0.0,
        parser_failures=parser_failures,
        prover_availability=availability,
    )


__all__ = [
    "ModalParserReport",
    "build_modal_parser_report",
]
