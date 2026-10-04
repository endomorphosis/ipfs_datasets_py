#!/usr/bin/env python3
"""Benchmark sentence_window impact on realistic domain documents."""

from __future__ import annotations

import json
import time
from statistics import mean, median
from pathlib import Path
import sys
import logging

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


LEGAL_TEXT = """
The plaintiff filed a complaint against the defendant in federal court.
The defendant entered into a services agreement with Acme Corp in 2023.
Under Section 12 of the contract, payment is due within 30 days of invoice.
Acme Corp alleges the defendant breached the warranty clause.
The court scheduled arbitration after reviewing the submitted evidence.
"""

TECHNICAL_TEXT = """
The API gateway forwards HTTP requests to the authentication microservice.
The service validates JSON Web Tokens before routing traffic to backend pods.
A GraphQL endpoint aggregates results from SQL and NoSQL sources.
Container metrics are exported to the observability pipeline every minute.
Version 2.4.1 introduced middleware changes for request retries.
"""

FINANCIAL_TEXT = """
The borrower refinanced the principal amount at a lower fixed interest rate.
Quarterly statements reported liabilities, assets, and retained earnings.
A wire transfer was issued with SWIFT details and routing number metadata.
The portfolio allocation shifted from equities to short-term bonds.
Risk controls flagged unusual debit and credit flows in the same account.
"""


def _run_case(
    generator: OntologyGenerator,
    text: str,
    domain: str,
    sentence_window: int,
    iterations: int = 40,
    warmups: int = 5,
) -> dict[str, float]:
    context = OntologyGenerationContext(
        data_source="benchmark",
        data_type=DataType.TEXT,
        domain=domain,
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(sentence_window=sentence_window),
    )

    for _ in range(warmups):
        generator.generate_ontology(text, context)

    samples_ms: list[float] = []
    rel_counts: list[int] = []
    for _ in range(iterations):
        start = time.perf_counter()
        ontology = generator.generate_ontology(text, context)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
        rel_counts.append(len(ontology.get("relationships", [])))

    samples_ms.sort()
    p95_index = max(0, int(iterations * 0.95) - 1)
    return {
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(samples_ms[p95_index], 4),
        "avg_relationships": round(mean(rel_counts), 2),
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    datasets = {
        "legal": LEGAL_TEXT,
        "technical": TECHNICAL_TEXT,
        "financial": FINANCIAL_TEXT,
    }

    windows = [0, 1, 2]
    report: dict[str, dict[str, dict[str, float]]] = {}

    for domain, text in datasets.items():
        report[domain] = {}
        for window in windows:
            report[domain][f"window_{window}"] = _run_case(
                generator=generator,
                text=text,
                domain=domain,
                sentence_window=window,
            )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
