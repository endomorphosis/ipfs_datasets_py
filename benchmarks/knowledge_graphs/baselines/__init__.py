"""Labelled load baselines and SLO regression gates (KGP-030).

Hardware- and environment-labelled performance baselines for the knowledge-
graph load harness. Absolute latency/throughput claims are never portable;
every baseline is bound to an ``environment_label`` and multi-sample
methodology (warmup, repetitions, variance).

Release gates enforced by :func:`compare_to_baseline`:

* zero correctness / security errors (hard fail)
* unexplained p95 latency regression greater than 10% (hard fail)
* unexplained throughput regression greater than 10% (hard fail)
* recovery / resource bound checks when declared on the baseline
"""

from __future__ import annotations

from .catalog import (
    BASELINE_SCHEMA,
    BASELINE_SCHEMA_VERSION,
    REQUIRED_BASELINE_PROFILES,
    REGRESSION_RATIO_LIMIT,
    BaselineCatalog,
    load_baseline,
    load_catalog,
    baselines_root,
)
from .compare import (
    ComparisonResult,
    GateVerdict,
    MetricDelta,
    compare_metrics,
    compare_receipt_to_baseline,
    compare_to_baseline,
    unexplained_regression,
)
from .methodology import (
    MetricSummary,
    aggregate_samples,
    bound_from_summary,
    validate_methodology,
)
from .ratify import (
    build_baseline_document,
    extract_metrics_from_receipt,
    ratify_profile_runs,
    validate_baseline_document,
)

__all__ = [
    "BASELINE_SCHEMA",
    "BASELINE_SCHEMA_VERSION",
    "BaselineCatalog",
    "ComparisonResult",
    "GateVerdict",
    "MetricDelta",
    "MetricSummary",
    "REGRESSION_RATIO_LIMIT",
    "REQUIRED_BASELINE_PROFILES",
    "aggregate_samples",
    "baselines_root",
    "bound_from_summary",
    "build_baseline_document",
    "compare_metrics",
    "compare_receipt_to_baseline",
    "compare_to_baseline",
    "extract_metrics_from_receipt",
    "load_baseline",
    "load_catalog",
    "ratify_profile_runs",
    "unexplained_regression",
    "validate_baseline_document",
    "validate_methodology",
]

__version__ = "1.0.0"
