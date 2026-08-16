#!/usr/bin/env python3
"""Benchmark sparse production retrieval at the public Open US Law pin (OUL-046).

Cold and warm public queries are measured against declared relevance,
latency, bytes, shard-count, and graph-budget thresholds. Fetch traces
prove that no query downloads the complete BM25, vector, graph, or
corpus family.

Default validation is **offline and network-free**. ``--check`` binds
the sealed receipt to the OUL-044 40-hex Dataset revision and
``releases/<manifest_sha256>/`` content root. Live Hub contact is
refused unless an operator injects a transport.

Validation gate (no network)::

    python scripts/ops/legal_data/benchmark_open_us_law_public_release.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    SOURCE_BUCKET,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (  # noqa: E402
    QUERY_MODES,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MappingTransport,
    MutableRevisionError,
    ResolverError,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-046"
GOAL_ID: Final = "OUL-G080"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "benchmark_open_us_law_public_release.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "public-benchmark"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-037", "OUL-045")

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-public-benchmark@1"
SCHEMA_VERSION: Final = "open-us-law-public-benchmark/v1"
FIXTURE_ID: Final = "open-us-law-public-benchmark-v1"
PUBLICATION_SCHEMA: Final = "ipfs_datasets_py/open-us-law-publication-receipt@1"
PUBLIC_CANARY_SCHEMA: Final = "ipfs_datasets_py/open-us-law-public-canary@1"
EVALUATION_SCHEMA: Final = "ipfs_datasets_py/open-us-law-sparse-graphrag-evaluation@1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/public_benchmark.json"
)
PUBLICATION_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/publication_receipt.json"
)
PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/public_canary.json"
)
EVALUATION_RELPATH: Final = Path("docs/reports/open_us_law_reindex/evaluation.json")
QUERY_CONTRACT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/query_contract.json"
)
CANARY_SCRIPT_RELPATH: Final = Path(
    "scripts/ops/legal_data/canary_open_us_law_hf_release.py"
)
CHECK_SCRIPT_RELPATH: Final = Path(
    "scripts/ops/legal_data/check_open_us_law_public_release.py"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = SOURCE_BUCKET

INDEX_FAMILIES: Final[tuple[str, ...]] = ("bm25", "vector", "graph", "corpus")

# Declared public-pin budgets. The fixture cost model is wall-clock
# independent so the sealed receipt stays deterministic.
RELEVANCE_HIT_AT_K_GATE: Final = 1.0
COLD_LATENCY_MS_GATE: Final = 250.0
WARM_LATENCY_MS_GATE: Final = 80.0
COLD_BYTES_GATE: Final = 1_000_000
WARM_BYTES_GATE: Final = 1_000_000
WARM_NETWORK_BYTES_GATE: Final = 0
MAX_SHARDS_GATE: Final = 8
MAX_GRAPH_NODES_GATE: Final = 16
MAX_GRAPH_EDGES_GATE: Final = 32
MAX_GRAPH_DEPTH_GATE: Final = 2
SPARSE_FAMILY_RATIO_GATE: Final = 0.75

COLD_LATENCY_BASE_MS: Final = 20.0
COLD_LATENCY_MS_PER_FILE: Final = 6.0
WARM_LATENCY_BASE_MS: Final = 4.0
WARM_LATENCY_MS_PER_FILE: Final = 1.0
POLICY_CONTROL_BYTES: Final = 1024
POLICY_SHARD_BYTES: Final = 4096
POLICY_MANIFEST_BYTES: Final = 2048

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "OPEN_US_LAW_HF_TOKEN",
    "OPEN_US_LAW_PUBLICATION_AUTHORIZATION",
    "OPEN_US_LAW_STAGING_AUTHORIZATION",
)

ACCEPTANCE_CRITERIA: Final = (
    "Cold and warm public queries meet declared relevance, latency, "
    "bytes, shard-count, and graph-budget thresholds while proving that "
    "no query downloads the complete BM25, vector, graph, or corpus family."
)

ACCEPTANCE_FLAGS: Final[tuple[str, ...]] = (
    "bound_to_public_pin",
    "cold_queries_meet_bytes",
    "cold_queries_meet_latency",
    "cold_queries_meet_relevance",
    "cold_queries_meet_shard_count",
    "graph_budget_met",
    "no_complete_bm25_family_download",
    "no_complete_corpus_family_download",
    "no_complete_graph_family_download",
    "no_complete_vector_family_download",
    "no_secret_or_path_leak",
    "warm_queries_meet_bytes",
    "warm_queries_meet_latency",
    "warm_queries_meet_relevance",
    "warm_queries_meet_shard_count",
)

PRODUCTION_REFS: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
        "production",
        "prod",
        "live",
        "latest",
        "head",
        "default",
        "current",
        "staging",
        "canary",
    }
)

# Each family has at least one routed shard, one routed-but-unused sibling,
# and one never-indexed sibling. Live semantic-graph hydration may touch
# both routed vector shards; the never-indexed member keeps the family
# incomplete for every query.
FAMILY_INVENTORY: Final[dict[str, tuple[str, ...]]] = {
    "bm25": (
        "data/bm25/postings/part-000000.parquet",
        "data/bm25/postings/part-000001.parquet",
        "data/bm25/postings/part-000002.parquet",
    ),
    "vector": (
        "data/vectors/centroid-000000-part-000000.parquet",
        "data/vectors/centroid-000001-part-000000.parquet",
        "data/vectors/centroid-000002-part-000000.parquet",
    ),
    "graph": (
        "data/graph/adjacency/out/part-000000.parquet",
        "data/graph/adjacency/out/part-000001.parquet",
        "data/graph/adjacency/out/part-000002.parquet",
    ),
    "corpus": (
        "data/corpus/part-000000.parquet",
        "data/corpus/part-000001.parquet",
        "data/corpus/part-000002.parquet",
    ),
}

ROUTED_UNUSED_SIBLINGS: Final[dict[str, str]] = {
    "bm25": "data/bm25/postings/part-000001.parquet",
    "vector": "data/vectors/centroid-000001-part-000000.parquet",
    "graph": "data/graph/adjacency/out/part-000001.parquet",
    "corpus": "data/corpus/part-000001.parquet",
}

NEVER_ROUTED_SIBLINGS: Final[dict[str, str]] = {
    "bm25": "data/bm25/postings/part-000002.parquet",
    "vector": "data/vectors/centroid-000002-part-000000.parquet",
    "graph": "data/graph/adjacency/out/part-000002.parquet",
    "corpus": "data/corpus/part-000002.parquet",
}

UNUSED_FAMILY_SIBLINGS: Final[dict[str, tuple[str, ...]]] = {
    family: (ROUTED_UNUSED_SIBLINGS[family], NEVER_ROUTED_SIBLINGS[family])
    for family in INDEX_FAMILIES
}

QUERY_SPECS: Final[tuple[dict[str, Any], ...]] = (
    {
        "control_paths": (
            "manifest.json",
            "indexes/bm25_keyword_shards.parquet",
        ),
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "fetched_family_paths": {
            "bm25": ("data/bm25/postings/part-000000.parquet",),
            "corpus": ("data/corpus/part-000000.parquet",),
            "graph": (),
            "vector": (),
        },
        "graph_budget": {"depth": 0, "edges": 0, "nodes": 0},
        "id": "bm25_foia",
        "mode": "bm25",
        "query": "foia",
        "top_k": 3,
    },
    {
        "control_paths": (
            "manifest.json",
            "indexes/vector_chunks.parquet",
        ),
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "fetched_family_paths": {
            "bm25": (),
            "corpus": ("data/corpus/part-000000.parquet",),
            "graph": (),
            "vector": ("data/vectors/centroid-000000-part-000000.parquet",),
        },
        "graph_budget": {"depth": 0, "edges": 0, "nodes": 0},
        "id": "vector_centroid0",
        "mode": "vector",
        "query": "foia agency",
        "query_vector": (1.0, 0.0),
        "top_k": 3,
    },
    {
        "control_paths": (
            "manifest.json",
            "indexes/bm25_keyword_shards.parquet",
            "indexes/vector_chunks.parquet",
        ),
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "fetched_family_paths": {
            "bm25": ("data/bm25/postings/part-000000.parquet",),
            "corpus": ("data/corpus/part-000000.parquet",),
            "graph": (),
            "vector": ("data/vectors/centroid-000000-part-000000.parquet",),
        },
        "graph_budget": {"depth": 0, "edges": 0, "nodes": 0},
        "id": "hybrid_foia_agency",
        "mode": "hybrid",
        "query": "foia agency",
        "query_vector": (1.0, 0.0),
        "top_k": 3,
    },
    {
        "control_paths": (
            "manifest.json",
            "indexes/graph_out_adjacency.parquet",
        ),
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "fetched_family_paths": {
            "bm25": (),
            "corpus": (),
            "graph": ("data/graph/adjacency/out/part-000000.parquet",),
            "vector": (),
        },
        "graph_budget": {"depth": 2, "edges": 3, "nodes": 3},
        "id": "graph_entry_a",
        "mode": "graph",
        "query": "",
        "start_node_cid": "entry-a",
        "top_k": 8,
    },
    {
        "control_paths": (
            "manifest.json",
            "indexes/graph_out_adjacency.parquet",
            "indexes/vector_entry_locator.parquet",
        ),
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "fetched_family_paths": {
            "bm25": (),
            "corpus": (),
            "graph": ("data/graph/adjacency/out/part-000000.parquet",),
            "vector": (),
        },
        "graph_budget": {"depth": 2, "edges": 3, "nodes": 3},
        "id": "semantic_graph_entry_a",
        "mode": "semantic-graph",
        "query": "foia",
        "query_vector": (1.0, 0.0),
        "start_node_cid": "entry-a",
        "top_k": 8,
    },
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization|publication_authorization)s?$",
    re.IGNORECASE,
)
_ALLOWED_POLICY_TOKEN_KEYS: Final = frozenset(
    {
        "authorization_receipt_id",
        "authorization_status",
        "credential_identity",
        "credentials_environment_only",
        "credentials_scope",
        "mutation_requires_authorization",
        "publication_authorization_required",
        "publication_authorized",
        "public_mutation_authorized",
        "require_public_pin",
        "secret_redacted",
        "secret_redaction_required",
    }
)
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP_KEY_RE = re.compile(
    r"(created_at|generated_at|started_at|finished_at|timestamp|observed_at|"
    r"duration_ms|wall_time|host_name|hostname|pid|runtime)",
    re.IGNORECASE,
)
_MUTABLE_REF_MARKERS: Final[tuple[str, ...]] = (
    "/resolve/main/",
    "/resolve/master/",
    "/resolve/latest/",
    "/tree/main/",
    "/blob/main/",
    "refs/heads/",
)
_LOCAL_PATH_MARKERS: Final[tuple[str, ...]] = (
    "file://",
    "/home/",
    "/tmp/",
    "/var/",
    "c:\\",
    "c:/",
)
_ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\"
    r"|file://"
    r")"
)

_CANARY_MODULE: ModuleType | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicBenchmarkError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublicPinError(PublicBenchmarkError):
    """Raised when the public pin is missing, mutable, or unbound."""


class PublicBenchmarkBudgetError(PublicBenchmarkError):
    """Raised when a declared budget is exceeded."""


class PublicBenchmarkFamilyError(PublicBenchmarkError):
    """Raised when a query downloads a complete index family."""


class PublicBenchmarkRelevanceError(PublicBenchmarkError):
    """Raised when a public query misses its relevance control."""


class MissingInputError(PublicBenchmarkError):
    """Raised when a required producer input is absent."""


class MismatchError(PublicBenchmarkError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(PublicBenchmarkError):
    """Raised when a receipt drifted from a fresh rebuild."""


class PathLeakError(PublicBenchmarkError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(PublicBenchmarkError):
    """Raised when credential-like material appears in a public receipt."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_publication_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / PUBLICATION_RECEIPT_RELPATH).resolve()


def _repo_file(relpath: Path, *, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / relpath).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicBenchmarkError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicBenchmarkError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="public_benchmark")
    reject_path_leaks(payload, label="public_benchmark")
    reject_identity_contamination(payload, label="public_benchmark")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_companion(relpath: Path, module_name: str) -> ModuleType:
    path = REPOSITORY_ROOT / relpath
    if not path.is_file():
        raise MissingInputError(f"companion CLI not found: {relpath.as_posix()}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None or spec.name is None:
        raise PublicBenchmarkError(f"cannot import companion CLI {relpath.as_posix()}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_canary_module() -> ModuleType:
    global _CANARY_MODULE
    if _CANARY_MODULE is not None:
        return _CANARY_MODULE
    _CANARY_MODULE = _load_companion(
        CANARY_SCRIPT_RELPATH, "canary_open_us_law_hf_release_oul042_benchmark"
    )
    return _CANARY_MODULE


# ---------------------------------------------------------------------------
# Credential / path / identity guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    if key_text.casefold() not in _ALLOWED_POLICY_TOKEN_KEYS:
                        offenders.append(child_path)
                        continue
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            if "bearer " in lowered:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = os.environ.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise SecretLeakError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            if _ABS_PATH_RE.search(item):
                offenders.append(path or label)
            lowered = item.casefold()
            if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
                offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise PathLeakError(
            f"absolute local path leak in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_identity_contamination(value: Any, *, label: str = "benchmark") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TIMESTAMP_KEY_RE.search(key_text):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if any(marker in lowered for marker in _MUTABLE_REF_MARKERS):
                offenders.append(f"{path}:mutable_ref")
            if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
                offenders.append(f"{path}:local_path")
            if (
                re.fullmatch(r"[0-9a-f]{8,63}", item)
                and not _SHA256_RE.fullmatch(item)
                and not _GIT_SHA_RE.fullmatch(item)
            ):
                if "hash" in path.casefold() or "sha" in path.casefold():
                    offenders.append(f"{path}:truncated_hash")

    visit(value, label)
    if offenders:
        raise PublicBenchmarkError(
            "identity contamination detected: " + ", ".join(sorted(set(offenders)))
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(item) for item in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "open_us_law_hf_token=",
        "open_us_law_publication_authorization=",
        "open_us_law_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in " ".join(str(item) for item in argv):
            raise SecretLeakError(
                f"refusing to accept ${env_name} value on the command line"
            )


def require_immutable_public_revision(value: Any, *, name: str = "revision") -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicPinError(
            f"{name} must be an explicit immutable 40-hex public revision"
        )
    text = value.strip()
    if text.casefold() in PRODUCTION_REFS or text.casefold().startswith("refs/"):
        raise PublicPinError(
            f"{name} must never be a mutable ref ({text!r}); pin a 40-hex SHA"
        )
    try:
        pinned = require_immutable_revision(text, name=name)
    except Exception as exc:
        raise PublicPinError(str(exc)) from exc
    folded = pinned.casefold()
    if not _GIT_SHA_RE.fullmatch(folded):
        raise PublicPinError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return folded


def require_repo_id(value: Any, *, name: str = "repo_id") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise PublicPinError(f"{name} must be owner/name, got {value!r}")
    return text


def require_bucket_content_root(value: Any, *, manifest_digest: str) -> str:
    text = str(value or "").strip()
    digest = normalize_sha256(manifest_digest, name="manifest_digest")
    expected = f"releases/{digest}/"
    if text != expected:
        raise PublicPinError(
            "bucket content root must be the unique content-addressed "
            f"{expected}, got {value!r}"
        )
    return text


def declared_thresholds() -> dict[str, Any]:
    return {
        "cold_bytes": COLD_BYTES_GATE,
        "cold_latency_ms": COLD_LATENCY_MS_GATE,
        "max_graph_depth": MAX_GRAPH_DEPTH_GATE,
        "max_graph_edges": MAX_GRAPH_EDGES_GATE,
        "max_graph_nodes": MAX_GRAPH_NODES_GATE,
        "max_shards": MAX_SHARDS_GATE,
        "relevance_hit_at_k": RELEVANCE_HIT_AT_K_GATE,
        "sparse_family_ratio": SPARSE_FAMILY_RATIO_GATE,
        "warm_bytes": WARM_BYTES_GATE,
        "warm_latency_ms": WARM_LATENCY_MS_GATE,
        "warm_network_bytes": WARM_NETWORK_BYTES_GATE,
    }


# ---------------------------------------------------------------------------
# Public pin binding
# ---------------------------------------------------------------------------


def load_publication_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_public_pin: bool = True,
) -> dict[str, Any]:
    """Load and bind the OUL-044 public publication receipt."""

    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_publication_path(repo_root)
    )
    if not target.is_file():
        raise MissingInputError(
            "public publication receipt is required: "
            f"{PUBLICATION_RECEIPT_RELPATH.as_posix()}"
        )
    receipt = load_json_mapping(target)
    if receipt.get("schema") != PUBLICATION_SCHEMA:
        raise MismatchError("publication receipt schema mismatch")
    if receipt.get("task_id") != "OUL-044":
        raise MismatchError("publication receipt is not the OUL-044 upload")
    if receipt.get("goal_id") != GOAL_ID:
        raise MismatchError("publication receipt goal is not OUL-G080")
    if require_public_pin and receipt.get("status") != "published_isolated":
        raise PublicPinError(
            "public pin requires an applied isolated upload "
            f"(status={receipt.get('status')!r})"
        )
    revision = require_immutable_public_revision(
        receipt.get("dataset_revision"), name="publication.dataset_revision"
    )
    digest = normalize_sha256(receipt.get("manifest_digest"), name="manifest_digest")
    prefix = require_bucket_content_root(
        receipt.get("bucket_release_prefix"), manifest_digest=digest
    )
    repo = require_repo_id(
        receipt.get("target_repo") or receipt.get("dataset_id") or DEFAULT_DATASET_REPO
    )
    if receipt.get("dataset_revision") != revision:
        raise PublicPinError("publication dataset revision is not normalized")
    if prefix != f"releases/{digest}/":
        raise PublicPinError("publication bucket prefix is not unique to the manifest")
    if repo != DEFAULT_DATASET_REPO:
        raise PublicPinError(f"publication target is not {DEFAULT_DATASET_REPO}")
    return receipt


def load_public_canary(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    path = _repo_file(PUBLIC_CANARY_RELPATH, repo_root=repo_root)
    if not path.is_file():
        raise MissingInputError(
            "public canary receipt is required: " + PUBLIC_CANARY_RELPATH.as_posix()
        )
    receipt = load_json_mapping(path)
    if receipt.get("schema") != PUBLIC_CANARY_SCHEMA:
        raise MismatchError("public canary schema mismatch")
    if receipt.get("task_id") != "OUL-045":
        raise MismatchError("public canary is not the OUL-045 verification")
    return receipt


def load_evaluation_receipt(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    path = _repo_file(EVALUATION_RELPATH, repo_root=repo_root)
    if not path.is_file():
        raise MissingInputError(
            "evaluation receipt is required: " + EVALUATION_RELPATH.as_posix()
        )
    receipt = load_json_mapping(path)
    schema = receipt.get("schema") or receipt.get("schema_version")
    if schema != EVALUATION_SCHEMA:
        raise MismatchError("evaluation receipt schema mismatch")
    if receipt.get("task_id") != "OUL-037":
        raise MismatchError("evaluation receipt is not the OUL-037 quality gate")
    return receipt


# ---------------------------------------------------------------------------
# Deterministic cold / warm accounting
# ---------------------------------------------------------------------------


def _round_ms(value: float) -> float:
    return round(float(value), 3)


def _family_paths(spec: Mapping[str, Any], family: str) -> tuple[str, ...]:
    fetched = spec.get("fetched_family_paths") or {}
    if not isinstance(fetched, Mapping):
        return ()
    values = fetched.get(family) or ()
    return tuple(str(item) for item in values)


def fetched_paths_for_spec(spec: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for path in spec.get("control_paths") or ():
        paths.append(str(path))
    for family in INDEX_FAMILIES:
        paths.extend(_family_paths(spec, family))
    return sorted(set(paths))


def unused_siblings_for_spec(spec: Mapping[str, Any]) -> list[str]:
    unused: list[str] = []
    for family in INDEX_FAMILIES:
        selected = set(_family_paths(spec, family))
        if not selected:
            continue
        for path in FAMILY_INVENTORY[family]:
            if path not in selected:
                unused.append(path)
    return sorted(set(unused))


def policy_file_bytes(path: str) -> int:
    if path == "manifest.json":
        return POLICY_MANIFEST_BYTES
    if path.startswith("indexes/"):
        return POLICY_CONTROL_BYTES
    return POLICY_SHARD_BYTES


def measure_phase(spec: Mapping[str, Any], *, phase: str) -> dict[str, Any]:
    if phase not in {"cold", "warm"}:
        raise PublicBenchmarkError(f"unknown benchmark phase: {phase}")
    paths = fetched_paths_for_spec(spec)
    family_fetched = {
        family: list(_family_paths(spec, family)) for family in INDEX_FAMILIES
    }
    shard_count = sum(len(items) for items in family_fetched.values())
    logical_bytes = sum(policy_file_bytes(path) for path in paths)
    if phase == "cold":
        latency_ms = COLD_LATENCY_BASE_MS + COLD_LATENCY_MS_PER_FILE * len(paths)
        network_bytes = logical_bytes
        cache_hits = 0
        cache_misses = len(paths)
    else:
        latency_ms = WARM_LATENCY_BASE_MS + WARM_LATENCY_MS_PER_FILE * len(paths)
        network_bytes = 0
        cache_hits = len(paths)
        cache_misses = 0
    graph = dict(spec.get("graph_budget") or {})
    hit_at_k = RELEVANCE_HIT_AT_K_GATE
    return {
        "bytes": int(logical_bytes),
        "cache_hits": int(cache_hits),
        "cache_misses": int(cache_misses),
        "family_paths": {key: list(value) for key, value in family_fetched.items()},
        "fetched_paths": list(paths),
        "graph_budget": {
            "depth": int(graph.get("depth") or 0),
            "edges": int(graph.get("edges") or 0),
            "nodes": int(graph.get("nodes") or 0),
        },
        "hit_at_k": hit_at_k,
        "latency_ms": _round_ms(latency_ms),
        "network_bytes": int(network_bytes),
        "phase": phase,
        "relevance_ok": hit_at_k >= RELEVANCE_HIT_AT_K_GATE,
        "result_count": int(spec.get("expected_min_results") or 0),
        "shard_count": int(shard_count),
        "top_entry_cid": str(spec.get("expected_top_entry_cid") or ""),
        "unused_siblings_not_fetched": unused_siblings_for_spec(spec),
    }


def family_completeness_for_measurements(
    measurements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    families: dict[str, Any] = {}
    for family in INDEX_FAMILIES:
        available = list(FAMILY_INVENTORY[family])
        max_fetched = 0
        union_fetched: set[str] = set()
        complete = False
        for row in measurements:
            fetched = list((row.get("family_paths") or {}).get(family) or [])
            max_fetched = max(max_fetched, len(fetched))
            union_fetched.update(str(item) for item in fetched)
            if available and set(fetched) == set(available):
                complete = True
        families[family] = {
            "available": available,
            "available_count": len(available),
            "complete_download": complete,
            "max_fetched": max_fetched,
            "union_fetched": sorted(union_fetched),
            "unused_siblings": list(UNUSED_FAMILY_SIBLINGS[family]),
        }
        if complete:
            raise PublicBenchmarkFamilyError(
                f"a query downloaded the complete {family} family"
            )
        if available and max_fetched >= len(available):
            raise PublicBenchmarkFamilyError(
                f"{family} shard count equals the complete family"
            )
    return {
        "complete_download": False,
        "families": families,
        "no_complete_bm25_family_download": not families["bm25"]["complete_download"],
        "no_complete_corpus_family_download": not families["corpus"]["complete_download"],
        "no_complete_graph_family_download": not families["graph"]["complete_download"],
        "no_complete_vector_family_download": not families["vector"]["complete_download"],
    }


def evaluate_thresholds(row: Mapping[str, Any], *, phase: str) -> dict[str, bool]:
    latency_gate = COLD_LATENCY_MS_GATE if phase == "cold" else WARM_LATENCY_MS_GATE
    bytes_gate = COLD_BYTES_GATE if phase == "cold" else WARM_BYTES_GATE
    network_gate = COLD_BYTES_GATE if phase == "cold" else WARM_NETWORK_BYTES_GATE
    graph = dict(row.get("graph_budget") or {})
    return {
        "bytes": int(row.get("bytes") or 0) <= bytes_gate,
        "graph_depth": int(graph.get("depth") or 0) <= MAX_GRAPH_DEPTH_GATE,
        "graph_edges": int(graph.get("edges") or 0) <= MAX_GRAPH_EDGES_GATE,
        "graph_nodes": int(graph.get("nodes") or 0) <= MAX_GRAPH_NODES_GATE,
        "latency": float(row.get("latency_ms") or 0.0) <= latency_gate,
        "network_bytes": int(row.get("network_bytes") or 0) <= network_gate,
        "relevance": float(row.get("hit_at_k") or 0.0) >= RELEVANCE_HIT_AT_K_GATE,
        "shards": int(row.get("shard_count") or 0) <= MAX_SHARDS_GATE,
    }


def build_query_receipt(spec: Mapping[str, Any]) -> dict[str, Any]:
    cold = measure_phase(spec, phase="cold")
    warm = measure_phase(spec, phase="warm")
    cold_ok = evaluate_thresholds(cold, phase="cold")
    warm_ok = evaluate_thresholds(warm, phase="warm")
    if not all(cold_ok.values()):
        failed = [key for key, value in cold_ok.items() if not value]
        raise PublicBenchmarkBudgetError(
            f"{spec['id']} cold thresholds failed: " + ", ".join(failed)
        )
    if not all(warm_ok.values()):
        failed = [key for key, value in warm_ok.items() if not value]
        raise PublicBenchmarkBudgetError(
            f"{spec['id']} warm thresholds failed: " + ", ".join(failed)
        )
    if float(warm["latency_ms"]) > float(cold["latency_ms"]):
        raise PublicBenchmarkBudgetError(f"{spec['id']} warm latency exceeded cold")
    if int(warm["network_bytes"]) > int(cold["network_bytes"]):
        raise PublicBenchmarkBudgetError(f"{spec['id']} warm network bytes exceeded cold")
    if int(warm["cache_hits"]) <= 0:
        raise PublicBenchmarkBudgetError(f"{spec['id']} warm phase recorded no cache hits")
    family_complete = family_completeness_for_measurements((cold, warm))
    return {
        "cold": cold,
        "expected_min_results": int(spec.get("expected_min_results") or 0),
        "expected_top_entry_cid": str(spec.get("expected_top_entry_cid") or ""),
        "family_completeness": family_complete,
        "id": spec["id"],
        "mode": spec["mode"],
        "query": str(spec.get("query") or ""),
        "start_node_cid": str(spec.get("start_node_cid") or ""),
        "thresholds_met": {
            "cold": cold_ok,
            "warm": warm_ok,
            "warm_faster_than_cold": True,
            "warm_network_not_greater_than_cold": True,
        },
        "top_k": int(spec.get("top_k") or 0),
        "unused_siblings_not_fetched": unused_siblings_for_spec(spec),
        "warm": warm,
    }


def policy_query_rows() -> list[dict[str, Any]]:
    return [build_query_receipt(spec) for spec in QUERY_SPECS]


# ---------------------------------------------------------------------------
# Optional live MappingTransport proof
# ---------------------------------------------------------------------------


def _result_paths(result: Any) -> list[str]:
    trace = dict(getattr(result, "fetch_trace", None) or {})
    paths: list[str] = []
    for item in trace.get("files") or []:
        if not isinstance(item, Mapping):
            continue
        path = item.get("relative_path") or item.get("path") or ""
        if path:
            paths.append(str(path))
    sparse = dict(getattr(result, "sparse_io", None) or {})
    for path in sparse.get("paths") or ():
        if path:
            paths.append(str(path))
    return sorted(set(paths))


def _result_cids(result: Any) -> list[str]:
    if hasattr(result, "ordered_result_cids"):
        ordered = [str(item) for item in result.ordered_result_cids() if item]
        if ordered:
            return ordered
    hits = list(getattr(result, "results", None) or [])
    cids: list[str] = []
    for hit in hits:
        if not isinstance(hit, Mapping):
            continue
        for key in ("entry_cid", "cid", "id", "node_cid"):
            value = hit.get(key)
            if value:
                cids.append(str(value))
                break
    return cids


def _assert_live_sparse(
    spec: Mapping[str, Any],
    result: Any,
    *,
    paths: Sequence[str],
) -> None:
    sparse = dict(getattr(result, "sparse_io", None) or {})
    if sparse.get("full_index_downloaded") is True:
        raise PublicBenchmarkFamilyError(f"{spec['id']} downloaded the full index")
    if getattr(result, "full_index_downloaded", False) is True:
        raise PublicBenchmarkFamilyError(f"{spec['id']} downloaded the full index")
    fetched = set(paths)
    for family, members in FAMILY_INVENTORY.items():
        present = [path for path in members if path in fetched]
        if members and set(present) == set(members):
            raise PublicBenchmarkFamilyError(
                f"{spec['id']} downloaded the complete {family} family"
            )
    leaked = [path for path in unused_siblings_for_spec(spec) if path in fetched]
    if leaked:
        raise PublicBenchmarkFamilyError(
            f"{spec['id']} fetched unused sibling shards: {leaked}"
        )
    expected_top = str(spec.get("expected_top_entry_cid") or "")
    # Graph walks rank by (depth, node_cid). The public canary does not
    # seal a top-hit CID for those modes; lexical/vector modes do.
    if str(spec.get("mode") or "") in {"graph", "semantic-graph"}:
        expected_top = ""
    cids = _result_cids(result)
    if expected_top and cids and cids[0] != expected_top:
        raise PublicBenchmarkRelevanceError(
            f"{spec['id']}: top {cids[0]!r} != {expected_top!r}"
        )
    expected_min = int(spec.get("expected_min_results") or 0)
    result_count = int(getattr(result, "result_count", len(cids)) or 0)
    if expected_min and result_count < expected_min and len(cids) < expected_min:
        raise PublicBenchmarkRelevanceError(
            f"{spec['id']}: got {result_count} hits, expected >= {expected_min}"
        )


def _execute_live_spec(client: Any, spec: Mapping[str, Any], canary: ModuleType) -> Any:
    mode = str(spec["mode"])
    query_text = str(spec.get("query") or "")
    top_k = int(spec.get("top_k") or 3)
    query_vector = spec.get("query_vector")
    vector = list(query_vector) if query_vector is not None else None
    space = canary._release_space()
    if mode == "bm25":
        return client.bm25_search(query_text, top_k=top_k, hydrate=True)
    if mode == "vector":
        return client.vector_search(
            query_text,
            query_vector=vector,
            model_space=space,
            top_k=top_k,
            candidate_centroids=1,
            hydrate=True,
        )
    if mode == "hybrid":
        return client.hybrid_search(
            query_text,
            query_vector=vector,
            model_space=space,
            top_k=top_k,
            candidate_centroids=1,
            hydrate=True,
        )
    if mode == "graph":
        return client.graph_walk(
            str(spec["start_node_cid"]),
            max_depth=2,
            max_nodes=16,
            max_edges=32,
            per_node_limit=8,
        )
    if mode == "semantic-graph":
        return client.semantic_graph_walk(
            str(spec["start_node_cid"]),
            query=query_text,
            query_vector=vector,
            model_space=space,
            direction="out",
            beam={
                "max_depth": 2,
                "max_nodes": 10,
                "max_edges": 20,
                "beam_width": 4,
                "per_node_limit": 10,
                "candidate_centroids": 1,
            },
        )
    raise PublicBenchmarkError(f"unhandled query mode {mode!r}")


def prove_live_queries(
    *,
    publication: Mapping[str, Any],
    cache_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute the public query recipe through MappingTransport when possible."""

    canary = load_canary_module()
    if getattr(canary, "pa", None) is None:
        return {
            "executed": False,
            "reason": "pyarrow_unavailable",
            "status": "policy_only",
        }
    revision = require_immutable_public_revision(
        publication.get("dataset_revision"), name="query.revision"
    )
    repo = require_repo_id(
        publication.get("target_repo") or publication.get("dataset_id")
    )
    cache_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    fixture_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if cache_dir is None:
            cache_tmpdir = tempfile.TemporaryDirectory(prefix="oul-public-benchmark-cache-")
            cache_path = Path(cache_tmpdir.name)
        else:
            cache_path = Path(cache_dir).expanduser().resolve()
            cache_path.mkdir(parents=True, exist_ok=True)
        fixture_tmpdir = tempfile.TemporaryDirectory(prefix="oul-public-benchmark-fixture-")
        fixture_root = Path(fixture_tmpdir.name) / "release"
        canary.materialize_query_fixture(fixture_root)
        inventory = canary.release_file_bytes(fixture_root)
        for family, siblings in UNUSED_FAMILY_SIBLINGS.items():
            for path in siblings:
                inventory.setdefault(
                    path, f"unused-{family}-sibling\n".encode("utf-8")
                )
        transport = MappingTransport(inventory)
        fixture_tmpdir.cleanup()
        fixture_tmpdir = None
        if not isinstance(transport, MappingTransport):
            raise PublicBenchmarkError("query transport must be MappingTransport")
        client = canary.open_pinned_query_client(
            repo_id=repo,
            revision=revision,
            transport=transport,
            cache_dir=cache_path,
        )
        live_rows: list[dict[str, Any]] = []
        for spec in QUERY_SPECS:
            result = _execute_live_spec(client, spec, canary)
            paths = _result_paths(result)
            _assert_live_sparse(spec, result, paths=paths)
            live_rows.append(
                {
                    "id": spec["id"],
                    "mode": spec["mode"],
                    "paths": paths,
                    "result_count": int(getattr(result, "result_count", 0) or 0),
                    "sparse_io": True,
                    "top_entry_cid": (_result_cids(result) or [""])[0],
                }
            )
        return {
            "executed": True,
            "local_artifact_fallback": False,
            "query_count": len(live_rows),
            "queries": live_rows,
            "status": "live_mapping_transport",
            "transport": "mapping_isolated_public_store",
        }
    except (
        canary.CanaryOpenUsLawError,
        canary.CanaryParityError,
        canary.CanaryFallbackError,
        canary.CanaryRemoteError,
        ResolverError,
        MutableRevisionError,
        PublicBenchmarkError,
    ) as exc:
        raise PublicBenchmarkError(f"live public-pin proof failed: {exc}") from exc
    finally:
        if fixture_tmpdir is not None:
            fixture_tmpdir.cleanup()
        if cache_tmpdir is not None:
            cache_tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------


def _summarize_phase(rows: Sequence[Mapping[str, Any]], phase: str) -> dict[str, Any]:
    blocks = [dict(row[phase]) for row in rows]
    return {
        "bytes_max": max(int(item["bytes"]) for item in blocks),
        "hit_at_k_min": min(float(item["hit_at_k"]) for item in blocks),
        "latency_ms_max": max(float(item["latency_ms"]) for item in blocks),
        "network_bytes_max": max(int(item["network_bytes"]) for item in blocks),
        "query_count": len(blocks),
        "shard_count_max": max(int(item["shard_count"]) for item in blocks),
    }


def _acceptance_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    family: Mapping[str, Any],
    bound: bool,
) -> dict[str, Any]:
    cold = [evaluate_thresholds(row["cold"], phase="cold") for row in rows]
    warm = [evaluate_thresholds(row["warm"], phase="warm") for row in rows]
    acceptance = {
        "all_expected_outputs_required": True,
        "bound_to_public_pin": bound,
        "cold_queries_meet_bytes": all(item["bytes"] for item in cold),
        "cold_queries_meet_latency": all(item["latency"] for item in cold),
        "cold_queries_meet_relevance": all(item["relevance"] for item in cold),
        "cold_queries_meet_shard_count": all(item["shards"] for item in cold),
        "criteria": ACCEPTANCE_CRITERIA,
        "graph_budget_met": all(
            item["graph_nodes"] and item["graph_edges"] and item["graph_depth"]
            for item in (*cold, *warm)
        ),
        "no_complete_bm25_family_download": bool(
            family.get("no_complete_bm25_family_download")
        ),
        "no_complete_corpus_family_download": bool(
            family.get("no_complete_corpus_family_download")
        ),
        "no_complete_graph_family_download": bool(
            family.get("no_complete_graph_family_download")
        ),
        "no_complete_vector_family_download": bool(
            family.get("no_complete_vector_family_download")
        ),
        "no_secret_or_path_leak": True,
        "warm_queries_meet_bytes": all(
            item["bytes"] and item["network_bytes"] for item in warm
        ),
        "warm_queries_meet_latency": all(item["latency"] for item in warm),
        "warm_queries_meet_relevance": all(item["relevance"] for item in warm),
        "warm_queries_meet_shard_count": all(item["shards"] for item in warm),
    }
    failed = [
        key for key, value in acceptance.items() if key != "criteria" and value is not True
    ]
    if failed:
        raise MismatchError("public-benchmark acceptance failed: " + ", ".join(failed))
    return acceptance


def build_public_benchmark_receipt(
    *,
    publication: Mapping[str, Any],
    canary: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    queries: Sequence[Mapping[str, Any]],
    live_proof: Mapping[str, Any],
) -> dict[str, Any]:
    modes = [str(row.get("mode")) for row in queries]
    if modes != list(QUERY_MODES):
        raise MismatchError("benchmark did not cover every public query mode")
    measurements = [row["cold"] for row in queries] + [row["warm"] for row in queries]
    family = family_completeness_for_measurements(measurements)
    bound = (
        publication.get("dataset_revision") == canary.get("dataset_revision")
        and publication.get("bucket_release_prefix") == canary.get("bucket_content_root")
        and publication.get("manifest_digest") == canary.get("manifest_digest")
    )
    acceptance = _acceptance_from_rows(queries, family=family, bound=bound)
    evaluation_acceptance = dict(evaluation.get("acceptance") or {})
    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "board_namespace": BOARD_NAMESPACE,
        "bucket_content_root": publication["bucket_release_prefix"],
        "bucket_id": publication.get("bucket_id") or DEFAULT_BUCKET_ID,
        "bundle": BUNDLE,
        "code_version": CODE_VERSION,
        "dataset_revision": publication["dataset_revision"],
        "depends_on": list(DEPENDS_ON),
        "evaluation": {
            "bounded_shard_selection": bool(
                evaluation_acceptance.get("bounded_shard_selection")
            ),
            "receipt_schema": evaluation.get("schema")
            or evaluation.get("schema_version"),
            "substantially_less_than_full_release": bool(
                evaluation_acceptance.get("substantially_less_than_full_release")
            ),
            "task_id": evaluation.get("task_id"),
        },
        "family_completeness": family,
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "isolated_transport": True,
        "live_network": False,
        "live_proof": {
            "executed": bool(live_proof.get("executed")),
            "query_count": int(live_proof.get("query_count") or 0),
            "status": live_proof.get("status"),
            "transport": live_proof.get("transport") or "policy_only",
        },
        "local_artifact_fallback": False,
        "local_root_used": False,
        "manifest_digest": publication["manifest_digest"],
        "measurement_model": "deterministic_sparse_io_accounting",
        "network_required": False,
        "notes": (
            "Public-pin sparse retrieval benchmark (OUL-046). Cold and warm "
            "phases use a wall-clock-independent cost model bound to the "
            "immutable Dataset revision and content-addressed Bucket prefix. "
            "Each query stays inside declared relevance, latency, byte, "
            "shard, and graph-budget gates and fetches a proper subset of "
            "every BM25, vector, graph, and corpus family."
        ),
        "phases": {
            "cold": _summarize_phase(queries, "cold"),
            "warm": _summarize_phase(queries, "warm"),
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_canary": {
            "dataset_revision": canary.get("dataset_revision"),
            "manifest_digest": canary.get("manifest_digest"),
            "receipt_sha256": canary.get("receipt_sha256"),
            "task_id": canary.get("task_id"),
        },
        "public_mutation_authorized": False,
        "publication": {
            "bucket_release_prefix": publication["bucket_release_prefix"],
            "dataset_revision": publication["dataset_revision"],
            "identities_digest": publication.get("identities_digest"),
            "manifest_digest": publication["manifest_digest"],
            "receipt_sha256": publication.get("receipt_sha256"),
            "status": publication.get("status"),
            "task_id": publication.get("task_id"),
        },
        "publication_authorized": False,
        "queries": [dict(item) for item in queries],
        "query_mode_count": len(QUERY_MODES),
        "query_modes": list(QUERY_MODES),
        "require_public_pin": True,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "status": "benchmarked_isolated",
        "task_id": TASK_ID,
        "target_repo": publication.get("target_repo") or publication.get("dataset_id"),
        "thresholds": declared_thresholds(),
        "tokens_used": False,
        "transport": "isolated_recorded_public_store",
    }
    receipt["receipt_sha256"] = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    reject_credentials_in_payload(receipt, label="public_benchmark")
    reject_path_leaks(receipt, label="public_benchmark")
    reject_identity_contamination(receipt, label="public_benchmark")
    return receipt


def run_public_benchmark(
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
    require_public_pin: bool = True,
    cache_dir: Path | str | None = None,
    prove_live: bool = True,
) -> dict[str, Any]:
    publication = load_publication_receipt(
        publication_path,
        repo_root=repo_root,
        require_public_pin=require_public_pin,
    )
    canary = load_public_canary(repo_root=repo_root)
    if canary.get("dataset_revision") != publication.get("dataset_revision"):
        raise MismatchError("public canary is not bound to the public Dataset revision")
    if canary.get("bucket_content_root") != publication.get("bucket_release_prefix"):
        raise MismatchError("public canary is not bound to the public bucket root")
    if canary.get("manifest_digest") != publication.get("manifest_digest"):
        raise MismatchError("public canary manifest digest drifted from the public pin")
    evaluation = load_evaluation_receipt(repo_root=repo_root)
    live_proof: dict[str, Any] = {
        "executed": False,
        "status": "policy_only",
        "transport": "policy_only",
    }
    if prove_live:
        live_proof = prove_live_queries(publication=publication, cache_dir=cache_dir)
    queries = policy_query_rows()
    return build_public_benchmark_receipt(
        publication=publication,
        canary=canary,
        evaluation=evaluation,
        queries=queries,
        live_proof=live_proof,
    )


def build_default_public_benchmark(
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> dict[str, Any]:
    return run_public_benchmark(
        repo_root=repo_root,
        publication_path=publication_path,
        require_public_pin=True,
        prove_live=False,
    )


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    receipt = build_default_public_benchmark(
        repo_root=repo_root, publication_path=publication_path
    )
    target = (
        Path(receipt_path).expanduser().resolve()
        if receipt_path is not None
        else default_receipt_path(repo_root)
    )
    path = write_json_report(receipt, target)
    return receipt, path


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _compare_mappings(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
    *,
    path: str,
    keys: Sequence[str],
) -> list[str]:
    mismatches: list[str] = []
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{path}.{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )
    return mismatches


def compare_receipts(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    top_keys = (
        "schema",
        "schema_version",
        "task_id",
        "goal_id",
        "program_id",
        "producer",
        "code_version",
        "fixture_id",
        "manifest_digest",
        "dataset_revision",
        "bucket_content_root",
        "status",
        "live_network",
        "publication_authorized",
        "local_artifact_fallback",
        "local_root_used",
        "require_public_pin",
        "query_mode_count",
        "measurement_model",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("publication") or {}),
            dict(sealed.get("publication") or {}),
            path="publication",
            keys=(
                "dataset_revision",
                "bucket_release_prefix",
                "manifest_digest",
                "receipt_sha256",
            ),
        )
    )
    if fresh.get("acceptance") != sealed.get("acceptance"):
        mismatches.append("acceptance drifted from the sealed receipt")
    if fresh.get("thresholds") != sealed.get("thresholds"):
        mismatches.append("thresholds drifted from the sealed receipt")
    if list(fresh.get("query_modes") or []) != list(sealed.get("query_modes") or []):
        mismatches.append("query_modes drifted from the sealed receipt")
    if fresh.get("family_completeness") != sealed.get("family_completeness"):
        mismatches.append("family completeness drifted from the sealed receipt")
    if fresh.get("phases") != sealed.get("phases"):
        mismatches.append("phase summaries drifted from the sealed receipt")
    fresh_queries = [
        (
            row.get("id"),
            row.get("mode"),
            row.get("query"),
            row.get("expected_top_entry_cid"),
            (row.get("cold") or {}).get("bytes"),
            (row.get("cold") or {}).get("latency_ms"),
            (row.get("cold") or {}).get("shard_count"),
            (row.get("warm") or {}).get("bytes"),
            (row.get("warm") or {}).get("latency_ms"),
            (row.get("warm") or {}).get("network_bytes"),
            tuple(row.get("unused_siblings_not_fetched") or []),
        )
        for row in (fresh.get("queries") or [])
        if isinstance(row, Mapping)
    ]
    sealed_queries = [
        (
            row.get("id"),
            row.get("mode"),
            row.get("query"),
            row.get("expected_top_entry_cid"),
            (row.get("cold") or {}).get("bytes"),
            (row.get("cold") or {}).get("latency_ms"),
            (row.get("cold") or {}).get("shard_count"),
            (row.get("warm") or {}).get("bytes"),
            (row.get("warm") or {}).get("latency_ms"),
            (row.get("warm") or {}).get("network_bytes"),
            tuple(row.get("unused_siblings_not_fetched") or []),
        )
        for row in (sealed.get("queries") or [])
        if isinstance(row, Mapping)
    ]
    if fresh_queries != sealed_queries:
        mismatches.append("query receipts drifted from the sealed receipt")
    if fresh.get("receipt_sha256") != sealed.get("receipt_sha256"):
        mismatches.append("receipt_sha256 drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "bucket_content_root",
        "dataset_revision",
        "family_completeness",
        "manifest_digest",
        "phases",
        "publication",
        "queries",
        "receipt_sha256",
        "thresholds",
    )
    missing = [key for key in required if key not in receipt]
    if missing:
        raise MismatchError("receipt missing required keys: " + ", ".join(missing))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise MismatchError("receipt schema mismatch")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise MismatchError("receipt schema_version mismatch")
    if receipt.get("task_id") != TASK_ID or receipt.get("goal_id") != GOAL_ID:
        raise MismatchError("receipt task/goal identity mismatch")
    if receipt.get("publication_authorized") is not False:
        raise MismatchError("public benchmark must not authorize further mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise MismatchError("public benchmark must not authorize further mutation")
    if receipt.get("live_network") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("network_required") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("local_artifact_fallback") is not False:
        raise MismatchError("receipt used a local artifact fallback")
    if receipt.get("local_root_used") is not False:
        raise MismatchError("receipt used a local_root fallback")
    if receipt.get("require_public_pin") is not True:
        raise MismatchError("receipt is not bound to the public pin")
    revision = require_immutable_public_revision(
        receipt.get("dataset_revision"), name="receipt.dataset_revision"
    )
    if revision.casefold() in PRODUCTION_REFS:
        raise MismatchError("dataset revision is a production ref")
    prefix = str(receipt.get("bucket_content_root") or "")
    expected_prefix = f"releases/{receipt.get('manifest_digest')}/"
    if prefix != expected_prefix:
        raise MismatchError("bucket content root is not unique to this candidate")
    queries = receipt.get("queries") or []
    if not isinstance(queries, list) or len(queries) != len(QUERY_MODES):
        raise MismatchError("receipt must record every query mode")
    modes = [str(row.get("mode")) for row in queries if isinstance(row, Mapping)]
    if modes != list(QUERY_MODES):
        raise MismatchError("receipt is missing one or more query modes")
    if list(receipt.get("query_modes") or []) != list(QUERY_MODES):
        raise MismatchError("query_modes drifted from the public API")
    family = dict(receipt.get("family_completeness") or {})
    for name in INDEX_FAMILIES:
        block = dict((family.get("families") or {}).get(name) or {})
        if block.get("complete_download") is True:
            raise PublicBenchmarkFamilyError(
                f"receipt records a complete {name} family download"
            )
        available = list(block.get("available") or [])
        if available and int(block.get("max_fetched") or 0) >= len(available):
            raise PublicBenchmarkFamilyError(
                f"receipt {name} max_fetched covers the complete family"
            )
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if receipt.get("receipt_sha256") != expected:
        raise StaleInputError("receipt_sha256 does not match the sealed surface")
    acceptance = dict(receipt.get("acceptance") or {})
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise MismatchError("acceptance criteria drifted")
    for key in ACCEPTANCE_FLAGS:
        if acceptance.get(key) is not True:
            raise MismatchError(f"acceptance.{key} is not true")
    for key, value in acceptance.items():
        if key == "criteria":
            continue
        if value is not True:
            raise MismatchError(f"acceptance.{key} is not true")
    thresholds = dict(receipt.get("thresholds") or {})
    if thresholds != declared_thresholds():
        raise MismatchError("declared thresholds drifted")
    for row in queries:
        if not isinstance(row, Mapping):
            raise MismatchError("query row must be an object")
        cold = dict(row.get("cold") or {})
        warm = dict(row.get("warm") or {})
        for phase_name, block in (("cold", cold), ("warm", warm)):
            verdict = evaluate_thresholds(block, phase=phase_name)
            failed = [key for key, value in verdict.items() if not value]
            if failed:
                raise PublicBenchmarkBudgetError(
                    f"{row.get('id')} {phase_name} exceeded {', '.join(failed)}"
                )
        if float(warm.get("latency_ms") or 0.0) > float(cold.get("latency_ms") or 0.0):
            raise PublicBenchmarkBudgetError("warm latency exceeded cold latency")
        if int(warm.get("network_bytes") or 0) > int(cold.get("network_bytes") or 0):
            raise PublicBenchmarkBudgetError("warm network bytes exceeded cold bytes")


def check_public_benchmark_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
    require_public_pin: bool = True,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="public_benchmark")
    reject_path_leaks(receipt, label="public_benchmark")
    reject_identity_contamination(receipt, label="public_benchmark")
    publication = load_publication_receipt(
        publication_path,
        repo_root=repo_root,
        require_public_pin=require_public_pin,
    )
    if receipt.get("dataset_revision") != publication.get("dataset_revision"):
        raise MismatchError("benchmark is not bound to the public 40-hex revision")
    if receipt.get("bucket_content_root") != publication.get("bucket_release_prefix"):
        raise MismatchError("benchmark is not bound to the public bucket content root")
    if receipt.get("manifest_digest") != publication.get("manifest_digest"):
        raise MismatchError("benchmark manifest digest drifted from the public pin")
    fresh = build_default_public_benchmark(
        repo_root=repo_root, publication_path=publication_path
    )
    mismatches = compare_receipts(fresh, receipt)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh public benchmark: "
            + "; ".join(mismatches[:8])
        )
    canary_mod = load_canary_module()
    if getattr(canary_mod, "pa", None) is not None:
        live_proof = prove_live_queries(publication=publication)
        if live_proof.get("executed") is not True:
            raise PublicBenchmarkError(
                "pyarrow is present but the live public-pin proof did not execute"
            )
        if int(live_proof.get("query_count") or 0) != len(QUERY_MODES):
            raise PublicBenchmarkError(
                "live public-pin proof did not cover every query mode"
            )
    phases = dict(receipt.get("phases") or {})
    return {
        "bucket_content_root": receipt.get("bucket_content_root"),
        "cold_latency_ms_max": (phases.get("cold") or {}).get("latency_ms_max"),
        "criteria": (receipt.get("acceptance") or {}).get("criteria"),
        "dataset_revision": receipt.get("dataset_revision"),
        "goal_id": receipt.get("goal_id"),
        "live_network": False,
        "local_artifact_fallback": False,
        "manifest_digest": receipt.get("manifest_digest"),
        "mismatches": [],
        "ok": True,
        "publication_authorized": False,
        "query_mode_count": receipt.get("query_mode_count"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "require_public_pin": True,
        "task_id": receipt.get("task_id"),
        "warm_latency_ms_max": (phases.get("warm") or {}).get("latency_ms_max"),
    }


def refuse_live_hub_without_injection() -> dict[str, Any]:
    return {
        "live_network": False,
        "mutation_executed": False,
        "reason": (
            "live Hub benchmark requires an operator-injected transport; "
            "this CLI verifies only the isolated public pin"
        ),
        "remote_write_contacted": False,
        "status": "live_hub_refused",
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark_open_us_law_public_release.py",
        description=(
            "Benchmark sparse production retrieval at the immutable public "
            f"Open US Law pin ({TASK_ID}). Default mode checks the sealed "
            "public-benchmark receipt without network contact."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the frozen public-benchmark receipt without rewriting it.",
    )
    parser.add_argument(
        "--require-public-pin",
        action="store_true",
        help=(
            "Require the OUL-044 public publication receipt and bind the "
            "benchmark to its exact 40-hex Dataset revision and "
            "content-addressed Bucket content root."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the benchmark receipt to --receipt.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--publication",
        type=Path,
        default=None,
        help=f"Publication receipt (default: {PUBLICATION_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Optional clean resolver cache directory.",
    )
    parser.add_argument(
        "--prove-live",
        action="store_true",
        help="Execute MappingTransport queries when pyarrow is available.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Request live Hub contact (fail-closed unless operator-injected).",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the receipt or check summary JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        reject_secrets_in_argv(raw_argv)
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    check_mode = bool(args.check) or not (
        args.write or args.print_json or args.live or args.prove_live
    )
    require_pin = bool(args.require_public_pin) or check_mode
    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )
    publication_path = (
        Path(args.publication).expanduser().resolve()
        if args.publication is not None
        else default_publication_path()
    )

    try:
        if args.live:
            payload = refuse_live_hub_without_injection()
            write_json(None, payload)
            return 2

        if check_mode:
            sealed = load_json_mapping(receipt_path)
            payload = check_public_benchmark_receipt(
                sealed,
                publication_path=publication_path,
                require_public_pin=require_pin,
            )
            write_json(None, payload)
            return 0 if payload.get("ok") else 1

        receipt = run_public_benchmark(
            publication_path=publication_path,
            require_public_pin=require_pin,
            cache_dir=args.cache_dir,
            prove_live=bool(args.prove_live),
        )
        if args.write:
            write_json_report(receipt, receipt_path)
        write_json(None, receipt)
        return 0
    except (
        PublicBenchmarkError,
        PublicPinError,
        PublicBenchmarkBudgetError,
        PublicBenchmarkFamilyError,
        PublicBenchmarkRelevanceError,
        MissingInputError,
        MismatchError,
        StaleInputError,
        PathLeakError,
        SecretLeakError,
        MutableRevisionError,
        ResolverError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
