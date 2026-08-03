"""Reproducible knowledge-graph load harness (KGP-029).

Public surface for generating deterministic graph shapes, replaying corpus
workloads across surfaces and storage profiles, and emitting versioned
load receipts for CI and baseline comparison (KGP-030).

Long-running profiles (smoke full size, synthetic 1M/10M, 24h soak) are
**opt-in**. The default ``tiny`` profile is mandatory for CI correctness.
"""

from __future__ import annotations

from .harness import GraphLoadHarness, run_profile
from .metrics import LatencyHistogram, ResourceSnapshot, sample_resources
from .profiles import (
    LOAD_PROFILES,
    PROFILE_NAMES,
    LoadProfile,
    WorkloadMix,
    get_profile,
)
from .receipt import (
    RECEIPT_SCHEMA,
    RECEIPT_SCHEMA_VERSION,
    LoadReceipt,
    build_receipt,
    receipt_to_json,
    validate_receipt,
)
from .shapes import (
    DeterministicGraph,
    GraphShapeSpec,
    generate_graph,
    shape_fingerprint,
)
from .surfaces import SURFACE_NAMES, STORAGE_PROFILES, open_load_surface
from .workloads import MixResult, execute_mix

__all__ = [
    "DeterministicGraph",
    "GraphLoadHarness",
    "GraphShapeSpec",
    "LOAD_PROFILES",
    "LatencyHistogram",
    "LoadProfile",
    "LoadReceipt",
    "MixResult",
    "PROFILE_NAMES",
    "RECEIPT_SCHEMA",
    "RECEIPT_SCHEMA_VERSION",
    "ResourceSnapshot",
    "SURFACE_NAMES",
    "STORAGE_PROFILES",
    "WorkloadMix",
    "build_receipt",
    "execute_mix",
    "generate_graph",
    "get_profile",
    "open_load_surface",
    "receipt_to_json",
    "run_profile",
    "sample_resources",
    "shape_fingerprint",
    "validate_receipt",
]

__version__ = "1.0.0"
