"""Named load profiles for the knowledge-graph harness (KGP-029).

Profile sizing follows the production hardening plan:

* ``tiny`` — CI-mandatory correctness profile (small, fast)
* ``smoke`` — 1,000 nodes / 5,000 edges (opt-in for longer CI jobs)
* ``corpus_211`` / ``corpus_cvefixes`` — real corpus replay hooks (opt-in)
* ``synthetic_large`` — 1M nodes / 10M edges (opt-in, resource heavy)
* ``concurrent_mixed`` — ≥16 graph IDs with mixed read/write/query

Only ``tiny`` is intended to run in default CI. Long profiles remain opt-in
via :func:`get_profile` / CLI flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .shapes import GraphShapeSpec

JSONDict = Dict[str, Any]

# Surfaces and storage profiles exercised by the matrix.
DEFAULT_SURFACES: Tuple[str, ...] = ("python", "cli", "mcp", "mcp_plus")
DEFAULT_STORAGE_PROFILES: Tuple[str, ...] = (
    "parquet",
    "ipfs_ipld",
    "ipfs_kit",
    "hybrid",
)

# Operation mix weights (must sum ~1.0; normalized at runtime).
DEFAULT_MIX_WEIGHTS: Mapping[str, float] = {
    "write": 0.35,
    "read": 0.30,
    "query": 0.35,
}


@dataclass(frozen=True, slots=True)
class WorkloadMix:
    """Read / write / query mix for a load run."""

    write_weight: float = 0.35
    read_weight: float = 0.30
    query_weight: float = 0.35
    operations: int = 32
    write_batch_size: int = 64
    query_language: str = "scan"
    query_max_rows: int = 100

    def normalized(self) -> "WorkloadMix":
        total = self.write_weight + self.read_weight + self.query_weight
        if total <= 0:
            raise ValueError("mix weights must sum to a positive value")
        return WorkloadMix(
            write_weight=self.write_weight / total,
            read_weight=self.read_weight / total,
            query_weight=self.query_weight / total,
            operations=self.operations,
            write_batch_size=self.write_batch_size,
            query_language=self.query_language,
            query_max_rows=self.query_max_rows,
        )

    def to_json_dict(self) -> JSONDict:
        n = self.normalized()
        return {
            "write_weight": n.write_weight,
            "read_weight": n.read_weight,
            "query_weight": n.query_weight,
            "operations": n.operations,
            "write_batch_size": n.write_batch_size,
            "query_language": n.query_language,
            "query_max_rows": n.query_max_rows,
        }


@dataclass(frozen=True, slots=True)
class LoadProfile:
    """A named, versioned workload configuration."""

    name: str
    description: str
    seed: int
    shape_spec: GraphShapeSpec
    mix: WorkloadMix
    surfaces: Tuple[str, ...] = DEFAULT_SURFACES
    storage_profiles: Tuple[str, ...] = DEFAULT_STORAGE_PROFILES
    graph_count: int = 1
    warmup_operations: int = 2
    repetitions: int = 1
    concurrent_workers: int = 1
    opt_in: bool = False
    corpus_id: Optional[str] = None
    measure_recovery: bool = True
    tags: Tuple[str, ...] = ()

    def to_json_dict(self) -> JSONDict:
        return {
            "name": self.name,
            "description": self.description,
            "seed": self.seed,
            "shape": {
                "seed": self.shape_spec.seed,
                "node_count": self.shape_spec.node_count,
                "edge_count": self.shape_spec.edge_count,
                "shape": self.shape_spec.shape,
                "id_prefix": self.shape_spec.id_prefix,
                "tenant": self.shape_spec.tenant,
                "graph_id": self.shape_spec.graph_id,
                "shard_count": self.shape_spec.shard_count,
            },
            "mix": self.mix.to_json_dict(),
            "surfaces": list(self.surfaces),
            "storage_profiles": list(self.storage_profiles),
            "graph_count": self.graph_count,
            "warmup_operations": self.warmup_operations,
            "repetitions": self.repetitions,
            "concurrent_workers": self.concurrent_workers,
            "opt_in": self.opt_in,
            "corpus_id": self.corpus_id,
            "measure_recovery": self.measure_recovery,
            "tags": list(self.tags),
        }

    def with_seed(self, seed: int) -> "LoadProfile":
        return replace(
            self,
            seed=seed,
            shape_spec=replace(self.shape_spec, seed=seed),
        )

    def with_surfaces(self, surfaces: Sequence[str]) -> "LoadProfile":
        return replace(self, surfaces=tuple(surfaces))

    def with_storage_profiles(self, profiles: Sequence[str]) -> "LoadProfile":
        return replace(self, storage_profiles=tuple(profiles))


def _shape(
    *,
    seed: int,
    nodes: int,
    edges: int,
    shape: str = "mixed",
    shard_count: int = 1,
    graph_id: str = "shape",
) -> GraphShapeSpec:
    return GraphShapeSpec(
        seed=seed,
        node_count=nodes,
        edge_count=edges,
        shape=shape,
        id_prefix="n",
        tenant="load",
        graph_id=graph_id,
        shard_count=shard_count,
    )


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

TINY = LoadProfile(
    name="tiny",
    description=(
        "CI-mandatory correctness profile: tiny deterministic graph, all "
        "storage profiles on python, plus a one-shot surface matrix probe."
    ),
    seed=42,
    shape_spec=_shape(seed=42, nodes=24, edges=48, shape="mixed", shard_count=4),
    mix=WorkloadMix(
        write_weight=0.4,
        read_weight=0.3,
        query_weight=0.3,
        operations=12,
        write_batch_size=16,
        query_max_rows=50,
    ),
    surfaces=DEFAULT_SURFACES,
    storage_profiles=DEFAULT_STORAGE_PROFILES,
    graph_count=1,
    warmup_operations=1,
    repetitions=1,
    concurrent_workers=1,
    opt_in=False,
    measure_recovery=True,
    tags=("ci", "correctness", "mandatory"),
)

SMOKE = LoadProfile(
    name="smoke",
    description="Plan smoke profile: 1,000 nodes / 5,000 edges.",
    seed=1000,
    shape_spec=_shape(
        seed=1000, nodes=1000, edges=5000, shape="power_law", shard_count=8
    ),
    mix=WorkloadMix(
        write_weight=0.35,
        read_weight=0.30,
        query_weight=0.35,
        operations=64,
        write_batch_size=128,
        query_max_rows=200,
    ),
    surfaces=("python",),
    storage_profiles=("parquet", "hybrid"),
    graph_count=1,
    warmup_operations=4,
    repetitions=2,
    concurrent_workers=1,
    opt_in=True,
    measure_recovery=True,
    tags=("smoke", "opt-in"),
)

CORPUS_211 = LoadProfile(
    name="corpus_211",
    description="Replay hook for the full 211-AI graph corpus (opt-in).",
    seed=211,
    shape_spec=_shape(seed=211, nodes=500, edges=2000, shape="clustered", shard_count=4),
    mix=WorkloadMix(operations=48, write_batch_size=64),
    surfaces=("python",),
    storage_profiles=("parquet", "ipfs_ipld"),
    graph_count=1,
    warmup_operations=2,
    repetitions=1,
    opt_in=True,
    corpus_id="211-ai",
    measure_recovery=True,
    tags=("corpus", "211", "opt-in"),
)

CORPUS_CVEFIXES = LoadProfile(
    name="corpus_cvefixes",
    description="Replay hook for CVEfixes source/release artifacts (opt-in).",
    seed=2024,
    shape_spec=_shape(
        seed=2024, nodes=800, edges=3200, shape="bipartite", shard_count=8
    ),
    mix=WorkloadMix(operations=48, write_batch_size=64),
    surfaces=("python",),
    storage_profiles=("parquet", "ipfs_kit"),
    graph_count=1,
    warmup_operations=2,
    repetitions=1,
    opt_in=True,
    corpus_id="cvefixes",
    measure_recovery=True,
    tags=("corpus", "cvefixes", "opt-in"),
)

SYNTHETIC_LARGE = LoadProfile(
    name="synthetic_large",
    description="Synthetic large: 1,000,000 nodes / 10,000,000 edges (opt-in).",
    seed=1_000_000,
    shape_spec=_shape(
        seed=1_000_000,
        nodes=1_000_000,
        edges=10_000_000,
        shape="power_law",
        shard_count=64,
    ),
    mix=WorkloadMix(
        operations=256,
        write_batch_size=4096,
        query_max_rows=1000,
    ),
    surfaces=("python",),
    storage_profiles=("parquet",),
    graph_count=1,
    warmup_operations=8,
    repetitions=1,
    concurrent_workers=1,
    opt_in=True,
    measure_recovery=True,
    tags=("synthetic", "large", "opt-in"),
)

CONCURRENT_MIXED = LoadProfile(
    name="concurrent_mixed",
    description=(
        "Mixed read/write/query across at least 16 graph IDs (opt-in)."
    ),
    seed=16,
    shape_spec=_shape(
        seed=16, nodes=64, edges=128, shape="ring", shard_count=4, graph_id="g"
    ),
    mix=WorkloadMix(
        write_weight=0.34,
        read_weight=0.33,
        query_weight=0.33,
        operations=48,
        write_batch_size=16,
    ),
    surfaces=("python",),
    storage_profiles=("parquet", "hybrid"),
    graph_count=16,
    warmup_operations=2,
    repetitions=1,
    concurrent_workers=4,
    opt_in=True,
    measure_recovery=True,
    tags=("concurrency", "mixed", "opt-in"),
)

LOAD_PROFILES: Dict[str, LoadProfile] = {
    TINY.name: TINY,
    SMOKE.name: SMOKE,
    CORPUS_211.name: CORPUS_211,
    CORPUS_CVEFIXES.name: CORPUS_CVEFIXES,
    SYNTHETIC_LARGE.name: SYNTHETIC_LARGE,
    CONCURRENT_MIXED.name: CONCURRENT_MIXED,
}

PROFILE_NAMES: Tuple[str, ...] = tuple(LOAD_PROFILES.keys())


def get_profile(name: str) -> LoadProfile:
    """Return a built-in profile by name."""
    key = name.strip().lower().replace("-", "_")
    try:
        return LOAD_PROFILES[key]
    except KeyError as exc:
        raise KeyError(
            f"unknown load profile {name!r}; known: {sorted(LOAD_PROFILES)}"
        ) from exc


def list_profiles(*, include_opt_in: bool = True) -> Tuple[LoadProfile, ...]:
    profiles = list(LOAD_PROFILES.values())
    if not include_opt_in:
        profiles = [p for p in profiles if not p.opt_in]
    return tuple(profiles)
