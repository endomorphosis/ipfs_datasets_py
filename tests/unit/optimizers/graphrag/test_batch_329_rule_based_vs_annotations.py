"""Batch 329: Rule-based extraction benchmark vs manual annotations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Set

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
    OntologyGenerator,
)


@dataclass
class AnnotationBenchmark:
    domain: str
    expected: Set[str]
    extracted: Set[str]

    @property
    def overlap(self) -> Set[str]:
        return self.expected & self.extracted

    @property
    def recall(self) -> float:
        return len(self.overlap) / max(1, len(self.expected))

    @property
    def precision(self) -> float:
        return len(self.overlap) / max(1, len(self.extracted))


_CORPUS: Dict[str, Dict[str, object]] = {
    "legal": {
        "text": (
            "Plaintiff Alice filed a complaint against Defendant Acme Corp "
            "under Section 42 of the Employment Code in California."
        ),
        "expected": {"alice", "acme corp", "section 42", "california", "plaintiff", "defendant"},
    },
    "medical": {
        "text": (
            "Patient Bob was diagnosed with diabetes and prescribed "
            "metformin 500 mg by Dr. Chen at Mercy Hospital."
        ),
        "expected": {"bob", "diabetes", "metformin", "500 mg", "dr. chen", "mercy hospital", "patient"},
    },
    "technical": {
        "text": (
            "Engineer Dana deployed the Kubernetes cluster on AWS using "
            "Terraform and monitored latency with Prometheus."
        ),
        "expected": {"dana", "kubernetes", "aws", "terraform", "prometheus", "engineer"},
    },
}


def _run_benchmark(generator: OntologyGenerator, domain: str, text: str, expected: Set[str]) -> AnnotationBenchmark:
    context = OntologyGenerationContext(
        data_source="manual-annotation-benchmark",
        data_type="text",
        domain=domain,
        extraction_strategy="rule_based",
    )
    result = generator.extract_entities(text, context)
    extracted = {entity.text.lower().strip() for entity in result.entities}
    return AnnotationBenchmark(domain=domain, expected=expected, extracted=extracted)


def test_rule_based_extraction_vs_manual_annotations_common_domains():
    generator = OntologyGenerator(use_ipfs_accelerate=False)

    benchmarks = []
    for domain, payload in _CORPUS.items():
        bench = _run_benchmark(
            generator=generator,
            domain=domain,
            text=payload["text"],
            expected=set(payload["expected"]),
        )
        benchmarks.append(bench)

    # Domain-level floors: require non-trivial overlap with hand-labeled entities.
    for bench in benchmarks:
        assert bench.recall >= 0.35, (
            f"{bench.domain} recall too low: {bench.recall:.3f} "
            f"(matched={sorted(bench.overlap)}, expected={sorted(bench.expected)})"
        )
        assert bench.precision >= 0.35, (
            f"{bench.domain} precision too low: {bench.precision:.3f} "
            f"(matched={sorted(bench.overlap)}, extracted_count={len(bench.extracted)})"
        )

    macro_recall = sum(b.recall for b in benchmarks) / len(benchmarks)
    macro_precision = sum(b.precision for b in benchmarks) / len(benchmarks)

    assert macro_recall >= 0.5
    assert macro_precision >= 0.4
