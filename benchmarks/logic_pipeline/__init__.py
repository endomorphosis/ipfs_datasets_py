"""Isolated execution primitives for the legal logic pipeline benchmark.

This package deliberately lives outside :mod:`ipfs_datasets_py`: importing it
must never configure an optional backend or alter a production routing default.
The backend adapters and runner are added by later benchmark goals.  This
foundation only defines the dependency-free contract they share:

* every mutable path is below a caller-selected run directory;
* the smoke configuration is offline, shadow-only, and deterministic; and
* creating directories is an explicit operation, never an import side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Final, Iterator

BENCHMARK_ID: Final = "hammer-symai-spacy-leanstral"
"""Stable identifier used in manifests and cache namespaces."""

SMOKE_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.smoke-manifest.v1"
)
"""Schema identifier for the deterministic package smoke manifest."""

DEFAULT_BENCHMARK_ROOT: Final = (
    Path("workspace") / "benchmarks" / BENCHMARK_ID
)
"""Base directory below which a required run id scopes all mutable data."""

SMOKE_VARIANTS: Final = ("A0", "A1", "A7", "A8")
"""Offline variants selected by the preregistered deterministic smoke stage."""

RUN_DIRECTORY_NAMES: Final = (
    "cache",
    "corpus",
    "objective_bundles",
    "receipts",
    "results",
    "state",
    "logs",
    "worktrees",
)
"""Complete set of mutable state and output directories for one run."""

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def HSSLEV0009A31() -> str:
    """Return the objective evidence bound to this execution contract.

    The intentionally stable function name is an AST-verifiable receipt for
    HSSL-G000.  It makes the supervisor's evidence a code symbol rather than a
    prose-only mention in generated planning state.
    """

    return "isolated benchmark package and execution skeleton"


def _validate_run_id(run_id: str) -> str:
    """Return a safe run id or raise :class:`ValueError`.

    A run id becomes one path component and a cache-namespace component, so
    absolute paths, traversal, whitespace, path separators, and empty values
    are rejected rather than normalized into a surprising destination.
    """

    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id must be 1-128 characters, start with an ASCII letter or "
            "digit, and contain only ASCII letters, digits, '.', '_', or '-'"
        )
    if run_id in {".", ".."}:
        raise ValueError("run_id must identify a run, not a path traversal")
    return run_id


def _coerce_benchmark_root(benchmark_root: str | Path) -> Path:
    """Return a usable base path while rejecting an accidental empty string."""

    if isinstance(benchmark_root, str) and not benchmark_root.strip():
        raise ValueError("benchmark_root must not be empty")
    return Path(benchmark_root)


@dataclass(frozen=True, slots=True)
class RunPaths:
    """All mutable filesystem locations allocated to one benchmark run.

    Construct instances with :meth:`for_run` so every member is guaranteed to
    be a direct descendant of ``<benchmark_root>/<run_id>``.  Merely creating a
    :class:`RunPaths` value does not touch the filesystem.
    """

    benchmark_root: Path
    run_id: str
    run_root: Path
    cache: Path
    corpus: Path
    objective_bundles: Path
    receipts: Path
    results: Path
    state: Path
    logs: Path
    worktrees: Path

    @classmethod
    def for_run(
        cls,
        run_id: str,
        *,
        benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    ) -> "RunPaths":
        """Build a run-scoped path set without creating any directories."""

        safe_run_id = _validate_run_id(run_id)
        root = _coerce_benchmark_root(benchmark_root)
        run_root = root / safe_run_id
        children = {name: run_root / name for name in RUN_DIRECTORY_NAMES}
        return cls(
            benchmark_root=root,
            run_id=safe_run_id,
            run_root=run_root,
            **children,
        )

    def directories(self) -> Iterator[Path]:
        """Yield the run root followed by every defined child directory."""

        yield self.run_root
        for name in RUN_DIRECTORY_NAMES:
            yield getattr(self, name)

    def as_dict(self) -> dict[str, str]:
        """Return deterministic, JSON-ready path values keyed by purpose."""

        return {
            "run_root": self.run_root.as_posix(),
            **{
                name: getattr(self, name).as_posix()
                for name in RUN_DIRECTORY_NAMES
            },
        }

    def materialize(self, *, mode: int = 0o700) -> None:
        """Create this run's private directories.

        Directory creation is intentionally explicit.  The default mode keeps
        potentially sensitive model traces and proof artifacts private on
        POSIX systems; existing directories are left intact.
        """

        if not 0 <= mode <= 0o777:
            raise ValueError("mode must be a valid permission mask")
        for directory in self.directories():
            directory.mkdir(mode=mode, parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class ExecutionDefaults:
    """Safe defaults shared by smoke runners and future stage adapters."""

    run_id: str
    benchmark_root: Path = DEFAULT_BENCHMARK_ROOT
    variants: tuple[str, ...] = SMOKE_VARIANTS
    shadow_only: bool = True
    network_enabled: bool = False
    model_calls_enabled: bool = False
    auto_merge: bool = False
    production_routing_changes: bool = False

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        object.__setattr__(
            self,
            "benchmark_root",
            _coerce_benchmark_root(self.benchmark_root),
        )
        object.__setattr__(self, "variants", tuple(self.variants))
        if not self.variants or any(
            not isinstance(variant, str) or not variant
            for variant in self.variants
        ):
            raise ValueError("variants must contain at least one nonempty id")
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must not contain duplicate ids")

    @property
    def paths(self) -> RunPaths:
        """Return the isolated path layout for this execution."""

        return RunPaths.for_run(
            self.run_id,
            benchmark_root=self.benchmark_root,
        )

    @property
    def cache_namespace(self) -> str:
        """Return a namespace that cannot be shared across run ids."""

        return f"{BENCHMARK_ID}/{self.run_id}"

    def smoke_manifest(self) -> dict[str, object]:
        """Build a deterministic, JSON-serializable smoke manifest.

        Volatile data such as timestamps, hostnames, process IDs, and random
        identifiers are intentionally absent.  Capability and revision
        identities belong to later versioned run records, not this package
        import smoke contract.
        """

        return {
            "schema": SMOKE_MANIFEST_SCHEMA,
            "benchmark_id": BENCHMARK_ID,
            "evidence": HSSLEV0009A31(),
            "run_id": self.run_id,
            "mode": "shadow" if self.shadow_only else "active",
            "variants": list(self.variants),
            "execution": {
                "network_enabled": self.network_enabled,
                "model_calls_enabled": self.model_calls_enabled,
                "auto_merge": self.auto_merge,
                "production_routing_changes": self.production_routing_changes,
            },
            "cache_namespace": self.cache_namespace,
            "paths": self.paths.as_dict(),
        }


def build_smoke_manifest(
    run_id: str,
    *,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Return the default deterministic manifest for ``run_id``."""

    return ExecutionDefaults(
        run_id=run_id,
        benchmark_root=_coerce_benchmark_root(benchmark_root),
    ).smoke_manifest()


def canonical_manifest_json(manifest: dict[str, object]) -> str:
    """Serialize a manifest canonically for storage or content hashing."""

    return json.dumps(
        manifest,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def manifest_sha256(manifest: dict[str, object]) -> str:
    """Return the SHA-256 digest of a canonical smoke manifest."""

    return hashlib.sha256(canonical_manifest_json(manifest).encode("utf-8")).hexdigest()


__all__ = [
    "BENCHMARK_ID",
    "DEFAULT_BENCHMARK_ROOT",
    "ExecutionDefaults",
    "HSSLEV0009A31",
    "RUN_DIRECTORY_NAMES",
    "RunPaths",
    "SMOKE_MANIFEST_SCHEMA",
    "SMOKE_VARIANTS",
    "build_smoke_manifest",
    "canonical_manifest_json",
    "manifest_sha256",
]

# The protocol module is also standard-library-only and side-effect-free.  The
# imports live at the end so it can reuse ``BENCHMARK_ID`` without creating an
# initialization cycle.
from .contracts import (  # noqa: E402
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    HSSLEV0103C72,
    BenchmarkProtocol,
    ProtocolContractError,
    build_default_protocol,
)

__all__ += [
    "BenchmarkProtocol",
    "DEFAULT_PROTOCOL",
    "DEFAULT_PROTOCOL_SHA256",
    "HSSLEV0103C72",
    "ProtocolContractError",
    "build_default_protocol",
]
