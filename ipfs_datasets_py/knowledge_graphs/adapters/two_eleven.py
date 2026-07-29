"""Read-only 211-AI retrieval package + browser GraphRAG adapter (KGP-026).

Provides a fail-closed, integrity-checked reader over:

* ``data/retrieval_package`` — Parquet documents, BM25, embeddings, graph
  nodes/edges/metrics/communities (authoritative owner: 211-AI)
* generated browser GraphRAG exports — JSON documents, neighborhoods
  (monolithic or sharded), communities, BM25, and f32 embeddings

The adapter mirrors the production exporter/reader surface in
``scraper/browser_graphrag_corpus.py`` and
``scripts/benchmark_211_retrieval.py`` closely enough for differential
parity on entity, neighborhood, community, geography, and hybrid queries.

It is strictly read-only: package and browser artifacts are never mutated.
"""

from __future__ import annotations

import base64
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Paths, env, and expected production counts
# ---------------------------------------------------------------------------

ENV_PACKAGE_ROOT = "TWO_ELEVEN_PACKAGE_ROOT"
ENV_PACKAGE_ROOT_ALT = "TWO11_RETRIEVAL_PACKAGE"
ENV_BROWSER_ROOT = "TWO_ELEVEN_BROWSER_ROOT"
ENV_BROWSER_ROOT_ALT = "TWO11_BROWSER_CORPUS"
ENV_211_AI_ROOT = "TWO_ELEVEN_AI_ROOT"

DEFAULT_211_AI_ROOT = Path("/home/barberb/211-AI")
DEFAULT_PACKAGE_REL = Path("data/retrieval_package")
DEFAULT_BROWSER_SMOKE_REL = Path("data/browser_graphrag_smoke")
DEFAULT_BROWSER_SMOKE_SHARDED_REL = Path("data/browser_graphrag_smoke_sharded")
DEFAULT_BROWSER_SMOKE_DEDUP_REL = Path("data/browser_graphrag_smoke_dedup")
DEFAULT_WALLET_CORPUS_REL = Path(
    "wallet_interface/ui/public/corpus/211-info/current"
)

MANIFEST_REL = Path("manifest/build_manifest.json")
INVENTORY_REL = Path("manifest/artifact_inventory.parquet")

# Authoritative full-corpus counts (KGP inventory / on-disk package).
EXPECTED_FULL_COUNTS: dict[str, int] = {
    "graph_nodes": 48_851,
    "graph_edges": 648_958,
    "documents": 22_638,
    "embeddings": 22_638,
    "bm25_documents": 22_638,
    "bm25_terms": 3_191_432,
    "graph_communities": 41,
    "document_communities": 22_638,
    "page_documents": 11_787,
    "service_documents": 10_851,
}

EXPECTED_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EXPECTED_EMBEDDING_DIM = 384
EXPECTED_WAREHOUSE_PATH = "data/live/state/etl_warehouse.duckdb"

# Browser smoke fixture expected shape (independent of source package drift).
EXPECTED_BROWSER_SMOKE_COUNTS: dict[str, int] = {
    "documents": 25,
    "neighborhoods": 25,
    "communities": 11,
    "shards": 3,  # sharded variant only
}

PACKAGE_ARTIFACTS: dict[str, str] = {
    "documents": "content/documents.parquet",
    "bm25_documents": "retrieval/bm25_documents.parquet",
    "bm25_terms": "retrieval/bm25_terms.parquet",
    "vector_embeddings": "retrieval/vector_embeddings.parquet",
    "knowledge_graph_nodes": "graph/knowledge_graph_nodes.parquet",
    "knowledge_graph_edges": "graph/knowledge_graph_edges.parquet",
    "graph_node_metrics": "graph/graph_node_metrics.parquet",
    "graph_communities": "graph/graph_communities.parquet",
    "document_communities": "graph/document_communities.parquet",
}

# Map manifest artifact_name → expected full count key.
_ARTIFACT_COUNT_KEYS: dict[str, str] = {
    "documents": "documents",
    "bm25_documents": "bm25_documents",
    "bm25_terms": "bm25_terms",
    "vector_embeddings": "embeddings",
    "knowledge_graph_nodes": "graph_nodes",
    "knowledge_graph_edges": "graph_edges",
    "graph_node_metrics": "graph_nodes",
    "graph_communities": "graph_communities",
    "document_communities": "document_communities",
}

REQUIRED_NODE_COLUMNS = (
    "node_id",
    "node_type",
    "label",
    "node_cid",
)
REQUIRED_EDGE_COLUMNS = (
    "source",
    "target",
    "relation",
    "edge_cid",
)
REQUIRED_DOCUMENT_COLUMNS = (
    "doc_id",
    "doc_type",
    "title",
    "text",
    "city",
    "state",
)

BM25_K1 = 1.5
BM25_B = 0.75
MAX_TOP_K = 1_000
MAX_CANDIDATES = 5_000
MAX_NEIGHBORS = 10_000
MAX_QUERY_TERMS = 64
MAX_QUERY_VECTOR_DIMENSION = 16_384

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "near",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)

_CID_RE = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

LEGACY_EXPORTER_CANDIDATES = (
    DEFAULT_211_AI_ROOT / "scraper" / "browser_graphrag_corpus.py",
    DEFAULT_211_AI_ROOT / "scripts" / "benchmark_211_retrieval.py",
)


class TwoElevenAdapterError(RuntimeError):
    """Raised when a package, browser export, or bounded query is malformed."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value or ""))
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise TwoElevenAdapterError(f"unsafe package path: {value!r}")
    return path


def _raw_sha256_cid(digest: bytes) -> str:
    if len(digest) != 32:
        raise TwoElevenAdapterError("SHA-256 digest has an invalid length")
    payload = bytes((0x01, 0x55, 0x12, 0x20)) + digest
    return "b" + base64.b32encode(payload).decode("ascii").lower().rstrip("=")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_cid(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return _raw_sha256_cid(digest.digest())


def _require_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise TwoElevenAdapterError(
            "pyarrow is required for the 211-AI adapter"
        ) from exc
    return pa, pq


def _require_numpy():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise TwoElevenAdapterError(
            "numpy is required for hybrid/vector queries"
        ) from exc
    return np


def _load_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        raise TwoElevenAdapterError(f"missing JSON artifact: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TwoElevenAdapterError(
            f"corrupt or unreadable JSON artifact: {path.name}"
        ) from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def tokenize(text: str) -> list[str]:
    """Tokenize query text the same way as ``benchmark_211_retrieval``."""

    clean = "".join(
        character.lower()
        if character.isalnum() or character in {" ", "-"}
        else " "
        for character in str(text or "")
    )
    terms = [
        term
        for term in (part.strip() for part in clean.split())
        if len(term) > 1 and term not in STOP_WORDS
    ]
    # Preserve order, drop duplicates (bounded).
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        ordered.append(term)
        if len(ordered) >= MAX_QUERY_TERMS:
            break
    return ordered


def normalize_scores(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return {key: 1.0 for key in scores}
    span = maximum - minimum
    return {key: (value - minimum) / span for key, value in scores.items()}


def metadata_score(document: Mapping[str, Any], query: str) -> float:
    lowered_query = str(query or "").lower().strip()
    if not lowered_query:
        return 0.0
    score = 0.0
    if lowered_query in str(document.get("title") or "").lower():
        score += 1.5
    for key in ("provider_name", "program_name", "categories", "city"):
        value = str(document.get(key) or "").lower()
        if value and lowered_query in value:
            score += 0.5
    return score


def score_bm25_document(
    document: Mapping[str, Any],
    query_terms: Sequence[str],
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
    avgdl: float,
) -> float:
    score = 0.0
    doc_length = max(
        float(
            document.get("document_length")
            or document.get("doc_length")
            or 0
        ),
        1.0,
    )
    length_norm = 1 - b + (b * doc_length) / max(avgdl, 1.0)
    terms = document.get("terms") or {}
    term_idf = document.get("term_idf") or {}
    for term in query_terms:
        tf = float(terms.get(term) or 0)
        if tf <= 0:
            continue
        idf = float(term_idf.get(term) or 1.0)
        score += idf * ((tf * (k1 + 1.0)) / (tf + k1 * length_norm))
    return score


def searchable_text(document: Mapping[str, Any]) -> str:
    return " ".join(
        str(document.get(key) or "")
        for key in (
            "title",
            "provider_name",
            "program_name",
            "categories",
            "city",
            "state",
            "text",
            "source_url",
            "label",
        )
    ).lower()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_211_ai_root() -> Path | None:
    candidate = _env_path(ENV_211_AI_ROOT)
    if candidate is not None and candidate.is_dir():
        return candidate.resolve()
    if DEFAULT_211_AI_ROOT.is_dir():
        return DEFAULT_211_AI_ROOT.resolve()
    return None


def discover_package_root() -> Path | None:
    """Locate the 211 retrieval package, or return None when unavailable."""

    for name in (ENV_PACKAGE_ROOT, ENV_PACKAGE_ROOT_ALT):
        candidate = _env_path(name)
        if candidate is not None and _looks_like_package(candidate):
            return candidate.resolve()
    ai_root = discover_211_ai_root()
    if ai_root is not None:
        candidate = ai_root / DEFAULT_PACKAGE_REL
        if _looks_like_package(candidate):
            return candidate.resolve()
    return None


def discover_browser_root() -> Path | None:
    """Locate a browser GraphRAG corpus root (smoke or wallet export)."""

    for name in (ENV_BROWSER_ROOT, ENV_BROWSER_ROOT_ALT):
        candidate = _env_path(name)
        if candidate is not None and _looks_like_browser(candidate):
            return candidate.resolve()
    ai_root = discover_211_ai_root()
    if ai_root is None:
        return None
    for rel in (
        DEFAULT_BROWSER_SMOKE_REL,
        DEFAULT_BROWSER_SMOKE_SHARDED_REL,
        DEFAULT_BROWSER_SMOKE_DEDUP_REL,
        DEFAULT_WALLET_CORPUS_REL,
    ):
        candidate = ai_root / rel
        if _looks_like_browser(candidate):
            return candidate.resolve()
    return None


def discover_browser_smoke_roots() -> dict[str, Path]:
    """Return available browser smoke fixtures keyed by variant name."""

    ai_root = discover_211_ai_root()
    if ai_root is None:
        return {}
    found: dict[str, Path] = {}
    for name, rel in (
        ("smoke", DEFAULT_BROWSER_SMOKE_REL),
        ("smoke_sharded", DEFAULT_BROWSER_SMOKE_SHARDED_REL),
        ("smoke_dedup", DEFAULT_BROWSER_SMOKE_DEDUP_REL),
    ):
        candidate = ai_root / rel
        if _looks_like_browser(candidate):
            found[name] = candidate.resolve()
    return found


def _looks_like_package(root: Path) -> bool:
    if not root.is_dir():
        return False
    return (root / MANIFEST_REL).is_file() and (
        root / PACKAGE_ARTIFACTS["documents"]
    ).is_file()


def _looks_like_browser(root: Path) -> bool:
    if not root.is_dir():
        return False
    generated = root / "generated"
    if not generated.is_dir():
        return False
    return (generated / "documents.json").is_file() or (
        generated / "generated-manifest.json"
    ).is_file()


def load_legacy_exporter_module() -> Any | None:
    """Optionally import the 211-AI browser exporter for differential parity."""

    path = LEGACY_EXPORTER_CANDIDATES[0]
    if not path.is_file():
        return None
    module_name = "_two_eleven_legacy_browser_graphrag_corpus"
    if module_name in sys.modules:
        return sys.modules[module_name]
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        # Ensure 211-AI repo root is importable for nested helpers.
        repo_root = str(path.resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        return None


def load_legacy_benchmark_module() -> Any | None:
    """Optionally import the 211 retrieval benchmark for hybrid parity."""

    path = LEGACY_EXPORTER_CANDIDATES[1]
    if not path.is_file():
        return None
    module_name = "_two_eleven_legacy_benchmark_211_retrieval"
    if module_name in sys.modules:
        return sys.modules[module_name]
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        repo_root = str(path.resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        return None


# ---------------------------------------------------------------------------
# Package validation
# ---------------------------------------------------------------------------


def read_build_manifest(package_root: Path | str) -> dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    path = root / MANIFEST_REL
    if not path.is_file():
        raise TwoElevenAdapterError(f"missing build manifest: {path}")
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise TwoElevenAdapterError("build manifest must be a JSON object")
    return payload


def validate_manifest(
    package_root: Path | str,
    *,
    expected_full_corpus: bool = False,
) -> dict[str, Any]:
    """Validate the build manifest shape and declared counts."""

    root = Path(package_root).expanduser().resolve()
    manifest = read_build_manifest(root)

    required_int_fields = (
        "document_count",
        "embedding_count",
        "graph_node_count",
        "graph_edge_count",
        "graph_community_count",
        "document_community_count",
        "bm25_term_count",
    )
    for field in required_int_fields:
        value = manifest.get(field)
        if type(value) is not int or value < 0:
            raise TwoElevenAdapterError(
                f"build manifest field {field!r} is missing or invalid"
            )

    embedding_model = manifest.get("embedding_model")
    if not isinstance(embedding_model, str) or not embedding_model:
        raise TwoElevenAdapterError(
            "build manifest is missing embedding_model"
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise TwoElevenAdapterError(
            "build manifest is missing artifacts inventory"
        )

    artifact_receipts: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise TwoElevenAdapterError("artifact entry must be an object")
        name = item.get("artifact_name")
        rel = item.get("artifact_path")
        row_count = item.get("row_count")
        size_bytes = item.get("size_bytes")
        cid = item.get("artifact_cid")
        if not isinstance(name, str) or not name:
            raise TwoElevenAdapterError("artifact missing artifact_name")
        if not isinstance(rel, str) or not rel:
            raise TwoElevenAdapterError(
                f"artifact {name!r} missing artifact_path"
            )
        _safe_relative_path(rel)
        if type(row_count) is not int or row_count < 0:
            raise TwoElevenAdapterError(
                f"artifact {name!r} has invalid row_count"
            )
        if type(size_bytes) is not int or size_bytes <= 0:
            raise TwoElevenAdapterError(
                f"artifact {name!r} has invalid size_bytes"
            )
        if not isinstance(cid, str) or _CID_RE.fullmatch(cid) is None:
            raise TwoElevenAdapterError(
                f"artifact {name!r} has invalid artifact_cid"
            )
        by_name[name] = dict(item)
        artifact_receipts.append(
            {
                "artifact_name": name,
                "artifact_path": rel,
                "row_count": row_count,
                "size_bytes": size_bytes,
                "artifact_cid": cid,
            }
        )

    for required in PACKAGE_ARTIFACTS:
        if required not in by_name:
            raise TwoElevenAdapterError(
                f"build manifest missing required artifact {required!r}"
            )
        declared_path = by_name[required]["artifact_path"]
        if declared_path != PACKAGE_ARTIFACTS[required]:
            raise TwoElevenAdapterError(
                f"artifact path drift for {required!r}: "
                f"expected {PACKAGE_ARTIFACTS[required]!r}, got {declared_path!r}"
            )

    counts = {
        "documents": int(manifest["document_count"]),
        "embeddings": int(manifest["embedding_count"]),
        "graph_nodes": int(manifest["graph_node_count"]),
        "graph_edges": int(manifest["graph_edge_count"]),
        "graph_communities": int(manifest["graph_community_count"]),
        "document_communities": int(manifest["document_community_count"]),
        "bm25_terms": int(manifest["bm25_term_count"]),
        "page_documents": int(manifest.get("page_document_count") or 0),
        "service_documents": int(manifest.get("service_document_count") or 0),
        "bm25_documents": int(
            by_name.get("bm25_documents", {}).get("row_count") or 0
        ),
    }

    count_drift: dict[str, dict[str, int]] = {}
    if expected_full_corpus:
        for key, expected in EXPECTED_FULL_COUNTS.items():
            actual = counts.get(key)
            if actual is None:
                continue
            if int(actual) != int(expected):
                count_drift[key] = {
                    "expected": int(expected),
                    "actual": int(actual),
                }
        if count_drift:
            raise TwoElevenAdapterError(
                "full-corpus count drift detected: "
                + ", ".join(
                    f"{k} expected {v['expected']} got {v['actual']}"
                    for k, v in sorted(count_drift.items())
                )
            )
        if embedding_model != EXPECTED_EMBEDDING_MODEL:
            raise TwoElevenAdapterError(
                f"embedding model drift: expected "
                f"{EXPECTED_EMBEDDING_MODEL!r}, got {embedding_model!r}"
            )

    warehouse = manifest.get("warehouse_path")
    stale_source_paths: list[str] = []
    if isinstance(warehouse, str) and warehouse:
        ai_root = discover_211_ai_root()
        warehouse_path = (
            (ai_root / warehouse).resolve()
            if ai_root is not None and not Path(warehouse).is_absolute()
            else Path(warehouse).expanduser()
        )
        if not warehouse_path.is_file():
            stale_source_paths.append(str(warehouse))

    return {
        "schema": "two-eleven-build-manifest-receipt/v1",
        "package_root": str(root),
        "manifest_path": str(root / MANIFEST_REL),
        "embedding_model": embedding_model,
        "warehouse_path": warehouse,
        "build_manifest_cid": manifest.get("build_manifest_cid"),
        "counts": counts,
        "artifacts": artifact_receipts,
        "artifact_by_name": by_name,
        "count_drift": count_drift,
        "stale_source_paths": stale_source_paths,
        "manifest": manifest,
    }


def validate_package_artifacts(
    package_root: Path | str,
    *,
    manifest_receipt: Mapping[str, Any] | None = None,
    verify_checksums: bool = True,
    expected_full_corpus: bool = False,
    max_rows_to_scan: int | None = None,
) -> dict[str, Any]:
    """Validate parquet presence, row counts, sizes, CIDs, and schemas."""

    root = Path(package_root).expanduser().resolve()
    receipt = (
        dict(manifest_receipt)
        if manifest_receipt is not None
        else validate_manifest(root, expected_full_corpus=expected_full_corpus)
    )
    by_name: Mapping[str, Mapping[str, Any]] = receipt["artifact_by_name"]
    _, pq = _require_pyarrow()

    kind_receipts: dict[str, dict[str, Any]] = {}
    checksums_verified = 0
    for name, rel in PACKAGE_ARTIFACTS.items():
        declared = by_name[name]
        path = root / rel
        if path.is_symlink() or not path.is_file():
            raise TwoElevenAdapterError(f"missing package artifact: {rel}")
        size_bytes = path.stat().st_size
        if size_bytes != int(declared["size_bytes"]):
            raise TwoElevenAdapterError(
                f"size drift for {name}: declared "
                f"{declared['size_bytes']}, on disk {size_bytes}"
            )
        try:
            meta = pq.read_metadata(path)
            schema = pq.read_schema(path)
            row_count = int(meta.num_rows)
        except Exception as exc:
            raise TwoElevenAdapterError(
                f"corrupt or unreadable parquet: {rel}"
            ) from exc
        if row_count != int(declared["row_count"]):
            raise TwoElevenAdapterError(
                f"row count drift for {name}: declared "
                f"{declared['row_count']}, parquet {row_count}"
            )
        if expected_full_corpus:
            count_key = _ARTIFACT_COUNT_KEYS.get(name)
            if count_key is not None:
                expected = EXPECTED_FULL_COUNTS[count_key]
                if row_count != expected:
                    raise TwoElevenAdapterError(
                        f"full-corpus row count mismatch for {name}: "
                        f"expected {expected}, got {row_count}"
                    )

        # Schema sanity for core artifacts.
        columns = list(schema.names)
        if name == "knowledge_graph_nodes":
            for col in REQUIRED_NODE_COLUMNS:
                if col not in columns:
                    raise TwoElevenAdapterError(
                        f"nodes parquet missing column {col!r}"
                    )
        elif name == "knowledge_graph_edges":
            for col in REQUIRED_EDGE_COLUMNS:
                if col not in columns:
                    raise TwoElevenAdapterError(
                        f"edges parquet missing column {col!r}"
                    )
        elif name == "documents":
            for col in REQUIRED_DOCUMENT_COLUMNS:
                if col not in columns:
                    raise TwoElevenAdapterError(
                        f"documents parquet missing column {col!r}"
                    )
        elif name == "vector_embeddings":
            for col in ("doc_id", "embedding_model", "embedding_dim", "embedding"):
                if col not in columns:
                    raise TwoElevenAdapterError(
                        f"embeddings parquet missing column {col!r}"
                    )

        cid_receipt: dict[str, Any] = {"verified": False}
        if verify_checksums:
            actual_cid = _file_cid(path)
            declared_cid = str(declared["artifact_cid"])
            if actual_cid != declared_cid:
                raise TwoElevenAdapterError(
                    f"CID differs for {name}: declared {declared_cid}, "
                    f"computed {actual_cid}"
                )
            cid_receipt = {
                "verified": True,
                "cid": actual_cid,
                "sha256": _sha256_file(path),
            }
            checksums_verified += 1

        sample_rows = 0
        if max_rows_to_scan is not None and max_rows_to_scan > 0:
            try:
                table = pq.read_table(
                    path, columns=columns[: min(4, len(columns))]
                )
                sample_rows = min(int(table.num_rows), int(max_rows_to_scan))
            except Exception as exc:
                raise TwoElevenAdapterError(
                    f"failed scanning parquet: {rel}"
                ) from exc

        kind_receipts[name] = {
            "path": rel,
            "row_count": row_count,
            "size_bytes": size_bytes,
            "columns": columns,
            "checksum": cid_receipt,
            "sample_rows_scanned": sample_rows,
        }

    return {
        "schema": "two-eleven-package-artifact-receipt/v1",
        "package_root": str(root),
        "kinds": kind_receipts,
        "checksums_verified": checksums_verified,
        "count_comparisons": {
            key: int(receipt["counts"][key])
            for key in (
                "graph_nodes",
                "graph_edges",
                "documents",
                "embeddings",
                "graph_communities",
            )
            if key in receipt["counts"]
        },
    }


def validate_browser_export(
    browser_root: Path | str,
    *,
    package_receipt: Mapping[str, Any] | None = None,
    require_shards: bool = False,
) -> dict[str, Any]:
    """Validate a generated browser GraphRAG export (smoke or full)."""

    root = Path(browser_root).expanduser().resolve()
    if not root.is_dir():
        raise TwoElevenAdapterError(f"browser root missing: {root}")
    generated = root / "generated"
    if not generated.is_dir():
        raise TwoElevenAdapterError(
            f"browser export missing generated/ directory: {root}"
        )

    gen_manifest_path = generated / "generated-manifest.json"
    artifacts_manifest_path = root / "artifacts.manifest.json"
    gen_manifest = (
        _load_json(gen_manifest_path) if gen_manifest_path.is_file() else {}
    )
    artifacts_manifest = (
        _load_json(artifacts_manifest_path)
        if artifacts_manifest_path.is_file()
        else {}
    )
    if gen_manifest and not isinstance(gen_manifest, dict):
        raise TwoElevenAdapterError("generated-manifest.json must be an object")
    if artifacts_manifest and not isinstance(artifacts_manifest, dict):
        raise TwoElevenAdapterError(
            "artifacts.manifest.json must be an object"
        )

    documents_path = generated / "documents.json"
    documents = _load_json(documents_path) if documents_path.is_file() else None
    if documents is None:
        raise TwoElevenAdapterError("browser export missing documents.json")
    if isinstance(documents, dict) and "documents" in documents:
        document_rows = documents["documents"]
    elif isinstance(documents, list):
        document_rows = documents
    else:
        raise TwoElevenAdapterError(
            "documents.json must be a list or {documents: [...]}"
        )
    if not isinstance(document_rows, list):
        raise TwoElevenAdapterError("documents payload is not a list")

    doc_index = None
    doc_index_path = generated / "document-index.json"
    if doc_index_path.is_file():
        doc_index = _load_json(doc_index_path)
        if not isinstance(doc_index, dict):
            raise TwoElevenAdapterError("document-index.json must be an object")
        if int(doc_index.get("count") or 0) != len(document_rows):
            raise TwoElevenAdapterError(
                "document-index count differs from documents.json length"
            )

    bm25_path = generated / "bm25-documents.json"
    bm25_payload = _load_json(bm25_path) if bm25_path.is_file() else None
    if bm25_payload is not None:
        if not isinstance(bm25_payload, dict):
            raise TwoElevenAdapterError("bm25-documents.json must be an object")
        bm25_docs = bm25_payload.get("documents")
        if not isinstance(bm25_docs, list):
            raise TwoElevenAdapterError(
                "bm25-documents.json missing documents list"
            )
        if len(bm25_docs) != len(document_rows):
            raise TwoElevenAdapterError(
                "bm25 document count differs from documents.json"
            )

    embedding_index = None
    embedding_index_path = generated / "embedding-index.json"
    embedding_binary = generated / "embeddings.f32"
    if embedding_index_path.is_file():
        embedding_index = _load_json(embedding_index_path)
        if not isinstance(embedding_index, dict):
            raise TwoElevenAdapterError(
                "embedding-index.json must be an object"
            )
        count = int(embedding_index.get("count") or 0)
        dim = int(embedding_index.get("dimension") or 0)
        if count != len(document_rows):
            raise TwoElevenAdapterError(
                "embedding-index count differs from documents.json"
            )
        if embedding_binary.is_file():
            expected_bytes = count * dim * 4
            actual_bytes = embedding_binary.stat().st_size
            if expected_bytes and actual_bytes != expected_bytes:
                raise TwoElevenAdapterError(
                    f"embeddings.f32 size differs: expected {expected_bytes}, "
                    f"got {actual_bytes}"
                )

    # Neighborhoods: monolithic and/or sharded.
    neighborhood_path = generated / "graph-neighborhoods.json"
    neighborhood_index_path = generated / "graph-neighborhood-index.json"
    shard_dir = generated / "graph-neighborhoods"
    neighborhood_count = 0
    shard_count = 0
    neighborhood_format = "missing"

    if neighborhood_path.is_file():
        payload = _load_json(neighborhood_path)
        if not isinstance(payload, dict):
            raise TwoElevenAdapterError(
                "graph-neighborhoods.json must be an object"
            )
        neighborhoods = payload.get("neighborhoods")
        if not isinstance(neighborhoods, Mapping):
            raise TwoElevenAdapterError(
                "graph-neighborhoods.json missing neighborhoods map"
            )
        neighborhood_count = len(neighborhoods)
        # Support both legacy embedded nodes/edges and exporter node_ids form.
        sample = next(iter(neighborhoods.values()), {})
        if isinstance(sample, Mapping) and "node_ids" in sample:
            neighborhood_format = "monolithic_indexed"
        else:
            neighborhood_format = "monolithic_embedded"
    if neighborhood_index_path.is_file():
        index_payload = _load_json(neighborhood_index_path)
        if not isinstance(index_payload, dict):
            raise TwoElevenAdapterError(
                "graph-neighborhood-index.json must be an object"
            )
        shard_count = int(index_payload.get("shardCount") or 0)
        neighborhood_count = max(
            neighborhood_count,
            int(index_payload.get("neighborhoodCount") or 0),
        )
        shards = index_payload.get("shards") or []
        if not isinstance(shards, list):
            raise TwoElevenAdapterError(
                "graph-neighborhood-index shards must be a list"
            )
        for shard in shards:
            if not isinstance(shard, Mapping):
                raise TwoElevenAdapterError("invalid neighborhood shard record")
            rel = shard.get("path")
            if not isinstance(rel, str) or not rel:
                raise TwoElevenAdapterError(
                    "neighborhood shard missing path"
                )
            # path is relative to browser root
            shard_path = root / rel
            if not shard_path.is_file():
                # also try under generated/
                alt = generated / Path(rel).name
                if alt.is_file():
                    shard_path = alt
                else:
                    raise TwoElevenAdapterError(
                        f"missing neighborhood shard: {rel}"
                    )
            shard_payload = _load_json(shard_path)
            if not isinstance(shard_payload, dict):
                raise TwoElevenAdapterError(
                    f"corrupt neighborhood shard: {rel}"
                )
            if "neighborhoods" not in shard_payload:
                raise TwoElevenAdapterError(
                    f"neighborhood shard missing neighborhoods: {rel}"
                )
        neighborhood_format = (
            "sharded"
            if neighborhood_format == "missing"
            else f"{neighborhood_format}+sharded"
        )
        if require_shards and shard_count <= 0:
            raise TwoElevenAdapterError(
                "browser export required shards but shardCount is 0"
            )
    elif require_shards:
        raise TwoElevenAdapterError(
            "browser export missing graph-neighborhood-index.json"
        )
    elif neighborhood_count == 0 and shard_dir.is_dir():
        shard_files = sorted(shard_dir.glob("shard-*.json"))
        shard_count = len(shard_files)
        for shard_path in shard_files:
            _ = _load_json(shard_path)
        neighborhood_format = "sharded_dir"

    communities_path = generated / "graph-communities.json"
    community_count = 0
    if communities_path.is_file():
        communities_payload = _load_json(communities_path)
        if not isinstance(communities_payload, dict):
            raise TwoElevenAdapterError(
                "graph-communities.json must be an object"
            )
        communities = communities_payload.get("communities") or []
        if not isinstance(communities, list):
            raise TwoElevenAdapterError(
                "graph-communities communities must be a list"
            )
        community_count = len(communities)

    doc_communities_path = generated / "document-communities.json"
    doc_community_count = 0
    if doc_communities_path.is_file():
        doc_comm = _load_json(doc_communities_path)
        if isinstance(doc_comm, dict):
            rows = doc_comm.get("documents") or []
            if isinstance(rows, list):
                doc_community_count = len(rows)

    # Source package drift vs optional package receipt / embedded sourcePackage.
    source_package = {}
    if isinstance(gen_manifest, dict):
        source_package = dict(gen_manifest.get("sourcePackage") or {})
    if not source_package and isinstance(artifacts_manifest, dict):
        source_package = dict(artifacts_manifest.get("sourcePackage") or {})

    stale_source_paths: list[str] = []
    count_drift: dict[str, dict[str, Any]] = {}
    source_path = source_package.get("path")
    if isinstance(source_path, str) and source_path:
        source_path_obj = Path(source_path)
        if not source_path_obj.is_dir():
            stale_source_paths.append(source_path)

    if package_receipt is not None:
        package_counts = package_receipt.get("counts") or {}
        package_cid = package_receipt.get("build_manifest_cid")
        mapping = {
            "document_count": "documents",
            "graph_node_count": "graph_nodes",
            "graph_edge_count": "graph_edges",
        }
        for src_key, pkg_key in mapping.items():
            if src_key in source_package and pkg_key in package_counts:
                declared = int(source_package[src_key])
                actual = int(package_counts[pkg_key])
                if declared != actual:
                    count_drift[src_key] = {
                        "browser_source_package": declared,
                        "package_actual": actual,
                    }
        browser_cid = source_package.get("build_manifest_cid")
        if (
            browser_cid
            and package_cid
            and str(browser_cid) != str(package_cid)
        ):
            count_drift["build_manifest_cid"] = {
                "browser_source_package": browser_cid,
                "package_actual": package_cid,
            }

    counts = {
        "documents": len(document_rows),
        "neighborhoods": neighborhood_count,
        "communities": community_count,
        "document_communities": doc_community_count,
        "shards": shard_count,
        "bm25_documents": (
            len(bm25_payload.get("documents") or [])
            if isinstance(bm25_payload, dict)
            else 0
        ),
        "embeddings": (
            int(embedding_index.get("count") or 0)
            if isinstance(embedding_index, dict)
            else 0
        ),
    }

    return {
        "schema": "two-eleven-browser-export-receipt/v1",
        "browser_root": str(root),
        "counts": counts,
        "neighborhood_format": neighborhood_format,
        "source_package": source_package,
        "stale_source_paths": stale_source_paths,
        "count_drift": count_drift,
        "has_generated_manifest": gen_manifest_path.is_file(),
        "has_artifacts_manifest": artifacts_manifest_path.is_file(),
        "schema_version": (
            gen_manifest.get("schemaVersion")
            if isinstance(gen_manifest, dict)
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Retrieval package reader
# ---------------------------------------------------------------------------


class TwoElevenPackageReader:
    """Lazy, read-only reader over the 211 retrieval package Parquet layout."""

    def __init__(self, package_root: Path | str) -> None:
        self.package_root = Path(package_root).expanduser().resolve()
        if not _looks_like_package(self.package_root):
            raise TwoElevenAdapterError(
                f"not a 211 retrieval package: {self.package_root}"
            )
        self._manifest: dict[str, Any] | None = None
        self._nodes_by_id: dict[str, dict[str, Any]] | None = None
        self._metrics_by_id: dict[str, dict[str, Any]] | None = None
        self._outgoing: dict[str, list[dict[str, Any]]] | None = None
        self._incoming: dict[str, list[dict[str, Any]]] | None = None
        self._documents_by_id: dict[str, dict[str, Any]] | None = None
        self._bm25_docs: list[dict[str, Any]] | None = None
        self._bm25_avgdl: float | None = None
        self._bm25_k1: float = BM25_K1
        self._bm25_b: float = BM25_B
        self._communities: list[dict[str, Any]] | None = None
        self._doc_communities: dict[str, dict[str, Any]] | None = None
        self._embeddings: dict[str, Any] | None = None

    @property
    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            self._manifest = read_build_manifest(self.package_root)
        return self._manifest

    def _parquet_rows(
        self,
        relative: str,
        *,
        columns: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        path = self.package_root / relative
        if path.is_symlink() or not path.is_file():
            raise TwoElevenAdapterError(f"missing package artifact: {relative}")
        _, pq = _require_pyarrow()
        try:
            table = pq.read_table(path, columns=list(columns) if columns else None)
        except Exception as exc:
            raise TwoElevenAdapterError(
                f"corrupt or unreadable parquet: {relative}"
            ) from exc
        rows = table.to_pylist()
        # Normalize nulls to empty strings for string-like fields used in queries.
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            cleaned.append(
                {
                    key: ("" if value is None else value)
                    for key, value in row.items()
                }
            )
        return cleaned

    def _ensure_nodes(self) -> dict[str, dict[str, Any]]:
        if self._nodes_by_id is None:
            rows = self._parquet_rows(PACKAGE_ARTIFACTS["knowledge_graph_nodes"])
            self._nodes_by_id = {
                str(row["node_id"]): row
                for row in rows
                if row.get("node_id")
            }
        return self._nodes_by_id

    def _ensure_metrics(self) -> dict[str, dict[str, Any]]:
        if self._metrics_by_id is None:
            rows = self._parquet_rows(PACKAGE_ARTIFACTS["graph_node_metrics"])
            self._metrics_by_id = {
                str(row["node_id"]): row
                for row in rows
                if row.get("node_id")
            }
        return self._metrics_by_id

    def _ensure_adjacency(self) -> None:
        if self._outgoing is not None and self._incoming is not None:
            return
        rows = self._parquet_rows(PACKAGE_ARTIFACTS["knowledge_graph_edges"])
        outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            source = str(row.get("source") or "")
            target = str(row.get("target") or "")
            if not source or not target:
                continue
            edge = {
                "source": source,
                "target": target,
                "relation": str(row.get("relation") or ""),
                "edge_cid": str(row.get("edge_cid") or ""),
                "bm25_score": row.get("bm25_score"),
                "tf": row.get("tf"),
                "idf": row.get("idf"),
                "source_content_cid": str(row.get("source_content_cid") or ""),
                "shared_document_count": row.get("shared_document_count"),
                "cooccurrence_score": row.get("cooccurrence_score"),
            }
            outgoing[source].append(edge)
            incoming[target].append(edge)
        self._outgoing = dict(outgoing)
        self._incoming = dict(incoming)

    def _ensure_documents(self) -> dict[str, dict[str, Any]]:
        if self._documents_by_id is None:
            rows = self._parquet_rows(PACKAGE_ARTIFACTS["documents"])
            self._documents_by_id = {
                str(row["doc_id"]): row for row in rows if row.get("doc_id")
            }
        return self._documents_by_id

    def _ensure_bm25(self) -> None:
        if self._bm25_docs is not None:
            return
        doc_rows = self._parquet_rows(PACKAGE_ARTIFACTS["bm25_documents"])
        term_rows = self._parquet_rows(PACKAGE_ARTIFACTS["bm25_terms"])
        terms_by_doc: dict[str, dict[str, float]] = defaultdict(dict)
        idf_by_doc: dict[str, dict[str, float]] = defaultdict(dict)
        avgdl = 0.0
        for row in term_rows:
            doc_id = str(row.get("doc_id") or "")
            term = str(row.get("term") or "")
            if not doc_id or not term:
                continue
            terms_by_doc[doc_id][term] = float(row.get("tf") or 0.0)
            idf_by_doc[doc_id][term] = float(row.get("idf") or 0.0)
            if not avgdl:
                avgdl = float(row.get("avg_doc_length") or 0.0)
        documents: list[dict[str, Any]] = []
        for row in doc_rows:
            doc_id = str(row.get("doc_id") or "")
            documents.append(
                {
                    "doc_id": doc_id,
                    "doc_type": str(row.get("doc_type") or ""),
                    "source_url": str(row.get("source_url") or ""),
                    "source_content_cid": str(
                        row.get("source_content_cid") or ""
                    ),
                    "source_page_cid": str(row.get("source_page_cid") or ""),
                    "document_length": int(row.get("doc_length") or 0),
                    "terms": dict(terms_by_doc.get(doc_id, {})),
                    "term_idf": dict(idf_by_doc.get(doc_id, {})),
                }
            )
        if not avgdl and documents:
            avgdl = sum(d["document_length"] for d in documents) / max(
                len(documents), 1
            )
        self._bm25_docs = documents
        self._bm25_avgdl = float(avgdl)

    def _ensure_communities(self) -> None:
        if self._communities is not None:
            return
        rows = self._parquet_rows(PACKAGE_ARTIFACTS["graph_communities"])
        communities: list[dict[str, Any]] = []
        for row in rows:
            top_terms = row.get("top_terms_json") or "[]"
            top_categories = row.get("top_categories_json") or "[]"
            top_hosts = row.get("top_hosts_json") or "[]"
            if isinstance(top_terms, str):
                try:
                    top_terms = json.loads(top_terms)
                except json.JSONDecodeError:
                    top_terms = []
            if isinstance(top_categories, str):
                try:
                    top_categories = json.loads(top_categories)
                except json.JSONDecodeError:
                    top_categories = []
            if isinstance(top_hosts, str):
                try:
                    top_hosts = json.loads(top_hosts)
                except json.JSONDecodeError:
                    top_hosts = []
            communities.append(
                {
                    "community_id": str(row.get("community_id") or ""),
                    "community_cid": str(row.get("community_cid") or ""),
                    "label": str(row.get("label") or ""),
                    "node_count": int(row.get("node_count") or 0),
                    "document_count": int(row.get("document_count") or 0),
                    "page_count": int(row.get("page_count") or 0),
                    "service_count": int(row.get("service_count") or 0),
                    "keyterm_count": int(row.get("keyterm_count") or 0),
                    "provider_count": int(row.get("provider_count") or 0),
                    "category_count": int(row.get("category_count") or 0),
                    "top_terms": top_terms,
                    "top_categories": top_categories,
                    "top_hosts": top_hosts,
                }
            )
        doc_rows = self._parquet_rows(PACKAGE_ARTIFACTS["document_communities"])
        self._communities = communities
        self._doc_communities = {
            str(row["doc_id"]): {
                "doc_id": str(row.get("doc_id") or ""),
                "doc_type": str(row.get("doc_type") or ""),
                "source_url": str(row.get("source_url") or ""),
                "source_content_cid": str(row.get("source_content_cid") or ""),
                "source_page_cid": str(row.get("source_page_cid") or ""),
                "community_id": str(row.get("community_id") or ""),
                "community_label": str(row.get("community_label") or ""),
            }
            for row in doc_rows
            if row.get("doc_id")
        }

    def _ensure_embeddings(self) -> dict[str, Any]:
        if self._embeddings is not None:
            return self._embeddings
        np = _require_numpy()
        rows = self._parquet_rows(
            PACKAGE_ARTIFACTS["vector_embeddings"],
            columns=[
                "doc_id",
                "embedding_model",
                "embedding_dim",
                "embedding",
            ],
        )
        doc_ids: list[str] = []
        vectors: list[list[float]] = []
        model = EXPECTED_EMBEDDING_MODEL
        dim = EXPECTED_EMBEDDING_DIM
        for row in rows:
            doc_id = str(row.get("doc_id") or "")
            emb = row.get("embedding")
            if not doc_id or emb is None:
                continue
            doc_ids.append(doc_id)
            vectors.append([float(x) for x in emb])
            if row.get("embedding_model"):
                model = str(row["embedding_model"])
            if row.get("embedding_dim"):
                dim = int(row["embedding_dim"])
        matrix = (
            np.asarray(vectors, dtype=np.float32)
            if vectors
            else np.zeros((0, dim), dtype=np.float32)
        )
        norms = np.linalg.norm(matrix, axis=1) if len(matrix) else np.asarray([])
        self._embeddings = {
            "doc_ids": doc_ids,
            "vectors": matrix,
            "vector_norms": norms,
            "embedding_model": model,
            "dimension": dim,
            "index": {doc_id: i for i, doc_id in enumerate(doc_ids)},
        }
        return self._embeddings

    # -- queries ------------------------------------------------------------

    def entity(
        self,
        *,
        node_id: str | None = None,
        label: str | None = None,
        node_type: str | None = None,
        term: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Lookup graph entities by id, type, label substring, or keyterm."""

        limit = max(1, min(int(limit), MAX_TOP_K))
        nodes = self._ensure_nodes()
        metrics = self._ensure_metrics()
        results: list[dict[str, Any]] = []

        if node_id:
            row = nodes.get(str(node_id))
            if row is not None:
                payload = dict(row)
                metric = metrics.get(str(node_id)) or {}
                payload["community_id"] = metric.get("community_id", "")
                payload["degree"] = metric.get("degree")
                payload["weighted_degree"] = metric.get("weighted_degree")
                results.append(payload)
            return {
                "mode": "entity",
                "query": {"node_id": node_id},
                "result_count": len(results),
                "results": results,
                "found": bool(results),
            }

        label_q = (label or "").lower().strip()
        term_q = (term or "").lower().strip()
        type_q = (node_type or "").strip()

        for row in nodes.values():
            if type_q and str(row.get("node_type") or "") != type_q:
                continue
            if label_q and label_q not in str(row.get("label") or "").lower():
                continue
            if term_q:
                hay = " ".join(
                    str(row.get(k) or "")
                    for k in ("label", "term", "category", "provider_name")
                ).lower()
                if term_q not in hay:
                    continue
            payload = dict(row)
            metric = metrics.get(str(row.get("node_id") or "")) or {}
            payload["community_id"] = metric.get("community_id", "")
            payload["degree"] = metric.get("degree")
            payload["weighted_degree"] = metric.get("weighted_degree")
            results.append(payload)
            if len(results) >= limit:
                break

        return {
            "mode": "entity",
            "query": {
                "label": label,
                "node_type": node_type,
                "term": term,
            },
            "result_count": len(results),
            "results": results,
            "found": bool(results),
        }

    def neighborhood(
        self,
        node_id: str,
        *,
        direction: str = "both",
        limit: int = 32,
        relation: str | None = None,
        hydrate: bool = True,
    ) -> dict[str, Any]:
        """Return bounded adjacency for a node (built from edges parquet)."""

        node_id = str(node_id or "")
        if not node_id:
            raise TwoElevenAdapterError("node_id is required for neighborhood")
        direction = str(direction or "both").lower()
        if direction not in {"outgoing", "incoming", "both"}:
            raise TwoElevenAdapterError(
                "direction must be outgoing, incoming, or both"
            )
        limit = max(1, min(int(limit), MAX_NEIGHBORS))
        self._ensure_adjacency()
        assert self._outgoing is not None and self._incoming is not None
        nodes = self._ensure_nodes() if hydrate else {}

        edges: list[dict[str, Any]] = []
        if direction in {"outgoing", "both"}:
            edges.extend(self._outgoing.get(node_id, []))
        if direction in {"incoming", "both"}:
            # Avoid duplicates when both directions requested for loops.
            existing = {(e["source"], e["target"], e["relation"]) for e in edges}
            for edge in self._incoming.get(node_id, []):
                key = (edge["source"], edge["target"], edge["relation"])
                if key not in existing:
                    edges.append(edge)

        if relation:
            edges = [e for e in edges if e.get("relation") == relation]

        def _edge_rank(edge: Mapping[str, Any]) -> tuple[float, float]:
            priority = {
                "HAS_KEYTERM": 100.0,
                "IN_CATEGORY": 90.0,
                "PROVIDES_SERVICE": 80.0,
                "HAS_PROGRAM": 75.0,
                "LOCATED_IN": 70.0,
                "DERIVED_FROM_PAGE": 70.0,
                "HAS_DOCUMENT": 60.0,
                "LINKS_TO": 40.0,
                "CO_OCCURS_WITH": 30.0,
            }.get(str(edge.get("relation") or ""), 10.0)
            score = max(
                float(edge.get("bm25_score") or 0.0),
                float(edge.get("cooccurrence_score") or 0.0),
                float(edge.get("shared_document_count") or 0.0),
            )
            return priority, score

        edges.sort(key=_edge_rank, reverse=True)
        total = len(edges)
        edges = edges[:limit]

        results: list[dict[str, Any]] = []
        for edge in edges:
            if edge["source"] == node_id:
                neighbor_id = edge["target"]
                edge_direction = "outgoing"
            else:
                neighbor_id = edge["source"]
                edge_direction = "incoming"
            neighbor = nodes.get(neighbor_id) if hydrate else None
            results.append(
                {
                    "direction": edge_direction,
                    "edge": edge,
                    "neighbor_node_id": neighbor_id,
                    "neighbor_node_type": (
                        (neighbor or {}).get("node_type")
                        if neighbor
                        else (
                            neighbor_id.split(":", 1)[0]
                            if ":" in neighbor_id
                            else ""
                        )
                    ),
                    "neighbor": neighbor,
                }
            )

        seed = nodes.get(node_id) if hydrate else None
        return {
            "mode": "neighborhood",
            "node_id": node_id,
            "direction": direction,
            "relation": relation,
            "result_count": len(results),
            "total_neighbor_count": total,
            "results": results,
            "seed": seed,
            "found": seed is not None or total > 0,
        }

    def community(
        self,
        *,
        community_id: str | None = None,
        doc_id: str | None = None,
        limit: int = 20,
        include_documents: bool = True,
        max_documents: int = 50,
    ) -> dict[str, Any]:
        """Lookup graph communities and optional member documents."""

        self._ensure_communities()
        assert self._communities is not None
        assert self._doc_communities is not None
        limit = max(1, min(int(limit), MAX_TOP_K))
        max_documents = max(0, min(int(max_documents), MAX_TOP_K))

        if doc_id:
            binding = self._doc_communities.get(str(doc_id))
            if binding is None:
                return {
                    "mode": "community",
                    "query": {"doc_id": doc_id},
                    "found": False,
                    "result_count": 0,
                    "results": [],
                }
            community_id = binding.get("community_id") or community_id

        if community_id:
            matches = [
                c
                for c in self._communities
                if c.get("community_id") == community_id
            ]
        else:
            matches = list(self._communities[:limit])

        results: list[dict[str, Any]] = []
        for community in matches[:limit]:
            payload = dict(community)
            if include_documents and community.get("community_id"):
                members = [
                    row
                    for row in self._doc_communities.values()
                    if row.get("community_id") == community["community_id"]
                ]
                payload["documents"] = members[:max_documents]
                payload["document_sample_count"] = len(payload["documents"])
            results.append(payload)

        return {
            "mode": "community",
            "query": {
                "community_id": community_id,
                "doc_id": doc_id,
            },
            "found": bool(results),
            "result_count": len(results),
            "results": results,
            "total_communities": len(self._communities),
        }

    def geography(
        self,
        *,
        city: str | None = None,
        state: str | None = None,
        location_label: str | None = None,
        limit: int = 20,
        include_graph_locations: bool = True,
    ) -> dict[str, Any]:
        """Filter documents (and optional location nodes) by geography fields."""

        limit = max(1, min(int(limit), MAX_TOP_K))
        city_q = (city or "").lower().strip()
        state_q = (state or "").lower().strip()
        loc_q = (location_label or "").lower().strip()
        if not city_q and not state_q and not loc_q:
            raise TwoElevenAdapterError(
                "geography requires city, state, or location_label"
            )

        documents = self._ensure_documents()
        doc_results: list[dict[str, Any]] = []
        for row in documents.values():
            row_city = str(row.get("city") or "").lower()
            row_state = str(row.get("state") or "").lower()
            if city_q and city_q not in row_city:
                continue
            if state_q and state_q not in row_state:
                continue
            if loc_q:
                hay = f"{row_city} {row_state} {row.get('title') or ''}".lower()
                if loc_q not in hay:
                    continue
            doc_results.append(
                {
                    "doc_id": row.get("doc_id"),
                    "doc_type": row.get("doc_type"),
                    "title": row.get("title"),
                    "provider_name": row.get("provider_name"),
                    "program_name": row.get("program_name"),
                    "city": row.get("city"),
                    "state": row.get("state"),
                    "source_url": row.get("source_url"),
                    "source_content_cid": row.get("source_content_cid"),
                }
            )
            if len(doc_results) >= limit:
                break

        location_nodes: list[dict[str, Any]] = []
        if include_graph_locations:
            nodes = self._ensure_nodes()
            for row in nodes.values():
                if str(row.get("node_type") or "") != "location":
                    continue
                label = str(row.get("label") or "").lower()
                row_city = str(row.get("city") or "").lower()
                row_state = str(row.get("state") or "").lower()
                if city_q and city_q not in row_city and city_q not in label:
                    continue
                if state_q and state_q not in row_state and state_q not in label:
                    continue
                if loc_q and loc_q not in label and loc_q not in row_city:
                    continue
                location_nodes.append(
                    {
                        "node_id": row.get("node_id"),
                        "label": row.get("label"),
                        "city": row.get("city"),
                        "state": row.get("state"),
                        "node_cid": row.get("node_cid"),
                    }
                )
                if len(location_nodes) >= limit:
                    break

        return {
            "mode": "geography",
            "query": {
                "city": city,
                "state": state,
                "location_label": location_label,
            },
            "result_count": len(doc_results),
            "results": doc_results,
            "location_nodes": location_nodes,
            "location_node_count": len(location_nodes),
            "found": bool(doc_results) or bool(location_nodes),
        }

    def keyword(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_limit: int = 200,
    ) -> dict[str, Any]:
        """BM25 keyword retrieval over the package term index."""

        return self._rank_keyword(
            query, top_k=top_k, candidate_limit=candidate_limit, mode="keyword"
        )

    def _rank_keyword(
        self,
        query: str,
        *,
        top_k: int,
        candidate_limit: int,
        mode: str,
    ) -> dict[str, Any]:
        top_k = max(1, min(int(top_k), MAX_TOP_K))
        candidate_limit = max(1, min(int(candidate_limit), MAX_CANDIDATES))
        terms = tokenize(query)
        if not terms:
            return {
                "mode": mode,
                "query": query,
                "result_count": 0,
                "results": [],
                "matched_terms": [],
            }
        self._ensure_bm25()
        assert self._bm25_docs is not None and self._bm25_avgdl is not None
        documents = self._ensure_documents()
        ranked: list[tuple[str, float]] = []
        for document in self._bm25_docs:
            score = score_bm25_document(
                document,
                terms,
                k1=self._bm25_k1,
                b=self._bm25_b,
                avgdl=self._bm25_avgdl,
            )
            if score > 0:
                ranked.append((document["doc_id"], score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        keyword_scores = {
            doc_id: score for doc_id, score in ranked[:candidate_limit]
        }
        results = self._fuse_scores(
            mode=mode,
            query=query,
            documents_by_id=documents,
            keyword_scores=keyword_scores,
            vector_scores={},
            limit=top_k,
        )
        return {
            "mode": mode,
            "query": query,
            "result_count": len(results),
            "results": results,
            "matched_terms": terms,
            "diagnostics": {
                "candidate_count": len(keyword_scores),
                "avgdl": self._bm25_avgdl,
                "k1": self._bm25_k1,
                "b": self._bm25_b,
            },
        }

    def vector(
        self,
        query: str | None = None,
        *,
        query_vector: Sequence[float] | None = None,
        top_k: int = 10,
        candidate_limit: int = 200,
    ) -> dict[str, Any]:
        """Vector similarity over package embeddings.

        Provide either ``query_vector`` or a text ``query`` (requires
        sentence-transformers for the package embedding model).
        """

        top_k = max(1, min(int(top_k), MAX_TOP_K))
        candidate_limit = max(1, min(int(candidate_limit), MAX_CANDIDATES))
        np = _require_numpy()
        emb = self._ensure_embeddings()
        vectors = emb["vectors"]
        if len(vectors) == 0:
            return {
                "mode": "vector",
                "query": query,
                "result_count": 0,
                "results": [],
            }

        if query_vector is not None:
            q = np.asarray(list(query_vector), dtype=np.float32)
        elif query:
            q = self._encode_query(query, dimension=int(emb["dimension"]))
        else:
            raise TwoElevenAdapterError(
                "vector query requires query text or query_vector"
            )
        if q.ndim != 1:
            raise TwoElevenAdapterError("query_vector must be 1-dimensional")
        if q.shape[0] != int(emb["dimension"]):
            raise TwoElevenAdapterError(
                f"query_vector dimension {q.shape[0]} != {emb['dimension']}"
            )
        if q.shape[0] > MAX_QUERY_VECTOR_DIMENSION:
            raise TwoElevenAdapterError("query_vector dimension exceeds limit")

        q_norm = float(np.linalg.norm(q))
        if q_norm == 0:
            return {
                "mode": "vector",
                "query": query,
                "result_count": 0,
                "results": [],
            }
        norms = emb["vector_norms"]
        denominator = np.maximum(norms * q_norm, 1e-12)
        scores = (vectors @ q) / denominator
        top_indexes = np.argsort(scores)[-candidate_limit:][::-1]
        vector_scores = {
            emb["doc_ids"][int(index)]: float(scores[int(index)])
            for index in top_indexes
        }
        documents = self._ensure_documents()
        results = self._fuse_scores(
            mode="vector",
            query=query or "",
            documents_by_id=documents,
            keyword_scores={},
            vector_scores=vector_scores,
            limit=top_k,
        )
        return {
            "mode": "vector",
            "query": query,
            "result_count": len(results),
            "results": results,
            "diagnostics": {
                "candidate_count": len(vector_scores),
                "embedding_model": emb["embedding_model"],
                "dimension": emb["dimension"],
            },
        }

    def hybrid(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_limit: int = 200,
        query_vector: Sequence[float] | None = None,
        skip_vector: bool = False,
    ) -> dict[str, Any]:
        """Hybrid keyword + vector + metadata fusion (browser benchmark parity)."""

        top_k = max(1, min(int(top_k), MAX_TOP_K))
        candidate_limit = max(1, min(int(candidate_limit), MAX_CANDIDATES))
        terms = tokenize(query)
        self._ensure_bm25()
        assert self._bm25_docs is not None and self._bm25_avgdl is not None
        documents = self._ensure_documents()

        keyword_scores: dict[str, float] = {}
        if terms:
            ranked: list[tuple[str, float]] = []
            for document in self._bm25_docs:
                score = score_bm25_document(
                    document,
                    terms,
                    k1=self._bm25_k1,
                    b=self._bm25_b,
                    avgdl=self._bm25_avgdl,
                )
                if score > 0:
                    ranked.append((document["doc_id"], score))
            ranked.sort(key=lambda item: item[1], reverse=True)
            keyword_scores = {
                doc_id: score for doc_id, score in ranked[:candidate_limit]
            }

        vector_scores: dict[str, float] = {}
        vector_diagnostics: dict[str, Any] = {"skipped": True}
        if not skip_vector:
            try:
                vector_hit = self.vector(
                    query,
                    query_vector=query_vector,
                    top_k=candidate_limit,
                    candidate_limit=candidate_limit,
                )
                vector_scores = {
                    row["doc_id"]: float(row["score_parts"]["vector"])
                    for row in vector_hit["results"]
                    # Recompute raw scores from diagnostics path instead:
                }
                # Prefer raw cosine scores for fusion (benchmark uses raw before normalize).
                # Re-run lightweight scoring to obtain raw map.
                vector_scores = self._raw_vector_scores(
                    query=query,
                    query_vector=query_vector,
                    candidate_limit=candidate_limit,
                )
                vector_diagnostics = {
                    "skipped": False,
                    **(vector_hit.get("diagnostics") or {}),
                }
            except TwoElevenAdapterError as exc:
                vector_diagnostics = {
                    "skipped": True,
                    "error": str(exc),
                }

        results = self._fuse_scores(
            mode="hybrid",
            query=query,
            documents_by_id=documents,
            keyword_scores=keyword_scores,
            vector_scores=vector_scores,
            limit=top_k,
        )
        return {
            "mode": "hybrid",
            "query": query,
            "result_count": len(results),
            "results": results,
            "matched_terms": terms,
            "diagnostics": {
                "keyword_candidates": len(keyword_scores),
                "vector": vector_diagnostics,
            },
        }

    def _raw_vector_scores(
        self,
        *,
        query: str | None,
        query_vector: Sequence[float] | None,
        candidate_limit: int,
    ) -> dict[str, float]:
        np = _require_numpy()
        emb = self._ensure_embeddings()
        vectors = emb["vectors"]
        if len(vectors) == 0:
            return {}
        if query_vector is not None:
            q = np.asarray(list(query_vector), dtype=np.float32)
        elif query:
            q = self._encode_query(query, dimension=int(emb["dimension"]))
        else:
            return {}
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0:
            return {}
        norms = emb["vector_norms"]
        denominator = np.maximum(norms * q_norm, 1e-12)
        scores = (vectors @ q) / denominator
        top_indexes = np.argsort(scores)[-candidate_limit:][::-1]
        return {
            emb["doc_ids"][int(index)]: float(scores[int(index)])
            for index in top_indexes
        }

    def _encode_query(self, query: str, *, dimension: int) -> Any:
        np = _require_numpy()
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise TwoElevenAdapterError(
                "sentence-transformers is required to encode text queries; "
                "pass query_vector instead"
            ) from exc
        model_name = str(
            self.manifest.get("embedding_model") or EXPECTED_EMBEDDING_MODEL
        )
        model = SentenceTransformer(model_name)
        vector = model.encode([query], normalize_embeddings=True)[0]
        arr = np.asarray(vector, dtype=np.float32)
        if arr.shape[0] != dimension:
            raise TwoElevenAdapterError(
                f"encoded query dimension {arr.shape[0]} != {dimension}"
            )
        return arr

    def _fuse_scores(
        self,
        *,
        mode: str,
        query: str,
        documents_by_id: Mapping[str, Mapping[str, Any]],
        keyword_scores: Mapping[str, float],
        vector_scores: Mapping[str, float],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fuse keyword/vector/metadata scores like the browser benchmark."""

        normalized_keyword = normalize_scores(keyword_scores)
        normalized_vector = normalize_scores(vector_scores)
        candidates = set(keyword_scores) | set(vector_scores)
        results: list[dict[str, Any]] = []
        for doc_id in candidates:
            document = documents_by_id.get(doc_id)
            if not document:
                # Fall back to BM25-only stub fields when document body missing.
                document = {"doc_id": doc_id}
            keyword = float(normalized_keyword.get(doc_id, 0.0))
            vector = float(normalized_vector.get(doc_id, 0.0))
            meta = metadata_score(document, query)
            if mode == "keyword":
                score = keyword * 2 + meta
            elif mode == "vector":
                score = vector * 2 + meta * 0.5
            else:
                score = keyword * 1.4 + vector * 2 + meta
            results.append(
                {
                    "doc_id": doc_id,
                    "score": float(score),
                    "score_parts": {
                        "keyword": keyword,
                        "vector": vector,
                        "metadata": meta,
                    },
                    "doc_type": document.get("doc_type"),
                    "title": document.get("title"),
                    "provider_name": document.get("provider_name"),
                    "program_name": document.get("program_name"),
                    "categories": document.get("categories"),
                    "city": document.get("city"),
                    "state": document.get("state"),
                    "source_url": document.get("source_url"),
                    "source_content_cid": document.get("source_content_cid"),
                }
            )
        results.sort(
            key=lambda row: (-float(row["score"]), str(row["doc_id"]))
        )
        return results[:limit]

    def adjacency_stats(self) -> dict[str, Any]:
        """Summarize adjacency built from the edges parquet."""

        self._ensure_adjacency()
        assert self._outgoing is not None and self._incoming is not None
        out_degrees = [len(v) for v in self._outgoing.values()]
        in_degrees = [len(v) for v in self._incoming.values()]
        return {
            "schema": "two-eleven-adjacency-stats/v1",
            "outgoing_nodes": len(self._outgoing),
            "incoming_nodes": len(self._incoming),
            "outgoing_edges": sum(out_degrees),
            "incoming_edges": sum(in_degrees),
            "max_out_degree": max(out_degrees) if out_degrees else 0,
            "max_in_degree": max(in_degrees) if in_degrees else 0,
        }


# ---------------------------------------------------------------------------
# Browser corpus reader
# ---------------------------------------------------------------------------


class TwoElevenBrowserReader:
    """Read-only reader for generated browser GraphRAG exports."""

    def __init__(self, browser_root: Path | str) -> None:
        self.browser_root = Path(browser_root).expanduser().resolve()
        if not _looks_like_browser(self.browser_root):
            raise TwoElevenAdapterError(
                f"not a 211 browser export: {self.browser_root}"
            )
        self.generated = self.browser_root / "generated"
        self._documents: list[dict[str, Any]] | None = None
        self._documents_by_id: dict[str, dict[str, Any]] | None = None
        self._bm25: dict[str, Any] | None = None
        self._neighborhoods: dict[str, Any] | None = None
        self._communities: list[dict[str, Any]] | None = None

    def documents(self) -> list[dict[str, Any]]:
        if self._documents is None:
            payload = _load_json(self.generated / "documents.json")
            if isinstance(payload, list):
                self._documents = payload
            elif isinstance(payload, dict):
                docs = payload.get("documents")
                if not isinstance(docs, list):
                    raise TwoElevenAdapterError(
                        "browser documents.json has invalid shape"
                    )
                self._documents = docs
            else:
                raise TwoElevenAdapterError(
                    "browser documents.json has invalid shape"
                )
            self._documents_by_id = {
                str(row.get("doc_id")): row
                for row in self._documents
                if row.get("doc_id")
            }
        return self._documents

    def documents_by_id(self) -> dict[str, dict[str, Any]]:
        self.documents()
        assert self._documents_by_id is not None
        return self._documents_by_id

    def bm25_payload(self) -> dict[str, Any]:
        if self._bm25 is None:
            path = self.generated / "bm25-documents.json"
            if not path.is_file():
                raise TwoElevenAdapterError("browser export missing BM25 payload")
            payload = _load_json(path)
            if not isinstance(payload, dict):
                raise TwoElevenAdapterError("bm25-documents.json must be object")
            self._bm25 = payload
        return self._bm25

    def neighborhood_for(self, doc_id: str) -> dict[str, Any] | None:
        doc_id = str(doc_id)
        # Prefer monolithic neighborhoods.
        mono = self.generated / "graph-neighborhoods.json"
        if mono.is_file():
            payload = _load_json(mono)
            neighborhoods = (payload or {}).get("neighborhoods") or {}
            hit = neighborhoods.get(doc_id)
            if hit is not None:
                return {"format": "monolithic", "doc_id": doc_id, **hit}
        # Sharded index.
        index_path = self.generated / "graph-neighborhood-index.json"
        if index_path.is_file():
            index = _load_json(index_path)
            mapping = (index or {}).get("docIdToShard") or {}
            rel = mapping.get(doc_id)
            if not rel:
                return None
            shard_path = self.browser_root / rel
            if not shard_path.is_file():
                shard_path = self.generated / Path(rel).name
            if not shard_path.is_file():
                raise TwoElevenAdapterError(
                    f"missing neighborhood shard for {doc_id}: {rel}"
                )
            shard = _load_json(shard_path)
            neighborhoods = (shard or {}).get("neighborhoods") or {}
            hit = neighborhoods.get(doc_id)
            if hit is None:
                return None
            # Hydrate nodes/edges when indexed form is used.
            if "node_ids" in hit:
                nodes = (shard or {}).get("nodes") or {}
                edges = (shard or {}).get("edges") or {}
                return {
                    "format": "sharded",
                    "doc_id": doc_id,
                    "node_ids": hit.get("node_ids") or [],
                    "edge_ids": hit.get("edge_ids") or [],
                    "nodes": [
                        nodes[nid]
                        for nid in hit.get("node_ids") or []
                        if nid in nodes
                    ],
                    "edges": [
                        edges[eid]
                        for eid in hit.get("edge_ids") or []
                        if eid in edges
                    ],
                    "shard": rel,
                }
            return {"format": "sharded", "doc_id": doc_id, **hit}
        return None

    def communities(self) -> list[dict[str, Any]]:
        if self._communities is None:
            path = self.generated / "graph-communities.json"
            if not path.is_file():
                self._communities = []
            else:
                payload = _load_json(path)
                rows = (payload or {}).get("communities") or []
                if not isinstance(rows, list):
                    raise TwoElevenAdapterError(
                        "graph-communities.json invalid communities"
                    )
                self._communities = rows
        return self._communities

    def keyword(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_limit: int = 200,
    ) -> dict[str, Any]:
        top_k = max(1, min(int(top_k), MAX_TOP_K))
        candidate_limit = max(1, min(int(candidate_limit), MAX_CANDIDATES))
        bm25 = self.bm25_payload()
        terms = tokenize(query)
        if not terms:
            return {
                "mode": "keyword",
                "query": query,
                "result_count": 0,
                "results": [],
                "matched_terms": [],
            }
        documents_by_id = self.documents_by_id()
        ranked: list[tuple[str, float]] = []
        k1 = float(bm25.get("k1") or BM25_K1)
        b = float(bm25.get("b") or BM25_B)
        avgdl = float(bm25.get("avgdl") or 0.0)
        for document in bm25.get("documents") or []:
            score = score_bm25_document(
                document, terms, k1=k1, b=b, avgdl=avgdl
            )
            if score > 0:
                ranked.append((str(document["doc_id"]), score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        keyword_scores = {
            doc_id: score for doc_id, score in ranked[:candidate_limit]
        }
        results = _browser_fuse(
            mode="keyword",
            query=query,
            documents_by_id=documents_by_id,
            keyword_scores=keyword_scores,
            vector_scores={},
            limit=top_k,
        )
        return {
            "mode": "keyword",
            "query": query,
            "result_count": len(results),
            "results": results,
            "matched_terms": terms,
        }

    def hybrid(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_limit: int = 200,
        query_vector: Sequence[float] | None = None,
        skip_vector: bool = False,
    ) -> dict[str, Any]:
        top_k = max(1, min(int(top_k), MAX_TOP_K))
        candidate_limit = max(1, min(int(candidate_limit), MAX_CANDIDATES))
        keyword = self.keyword(
            query, top_k=candidate_limit, candidate_limit=candidate_limit
        )
        keyword_scores = {
            row["doc_id"]: float(row["score_parts"]["keyword"])
            for row in keyword["results"]
        }
        # keyword path returns normalized parts already fused; recompute raw.
        bm25 = self.bm25_payload()
        terms = tokenize(query)
        k1 = float(bm25.get("k1") or BM25_K1)
        b = float(bm25.get("b") or BM25_B)
        avgdl = float(bm25.get("avgdl") or 0.0)
        raw_keyword: dict[str, float] = {}
        for document in bm25.get("documents") or []:
            score = score_bm25_document(
                document, terms, k1=k1, b=b, avgdl=avgdl
            )
            if score > 0:
                raw_keyword[str(document["doc_id"])] = score
        # Keep top candidates.
        raw_keyword = dict(
            sorted(raw_keyword.items(), key=lambda item: item[1], reverse=True)[
                :candidate_limit
            ]
        )

        vector_scores: dict[str, float] = {}
        if not skip_vector:
            vector_scores = self._vector_scores(
                query=query,
                query_vector=query_vector,
                candidate_limit=candidate_limit,
            )
        results = _browser_fuse(
            mode="hybrid",
            query=query,
            documents_by_id=self.documents_by_id(),
            keyword_scores=raw_keyword,
            vector_scores=vector_scores,
            limit=top_k,
        )
        return {
            "mode": "hybrid",
            "query": query,
            "result_count": len(results),
            "results": results,
            "matched_terms": terms,
        }

    def _vector_scores(
        self,
        *,
        query: str | None,
        query_vector: Sequence[float] | None,
        candidate_limit: int,
    ) -> dict[str, float]:
        np = _require_numpy()
        index_path = self.generated / "embedding-index.json"
        binary_path = self.generated / "embeddings.f32"
        if not index_path.is_file() or not binary_path.is_file():
            return {}
        index = _load_json(index_path)
        count = int(index.get("count") or 0)
        dim = int(index.get("dimension") or 0)
        if count <= 0 or dim <= 0:
            return {}
        vectors = np.fromfile(binary_path, dtype="<f4")
        expected = count * dim
        if vectors.size != expected:
            raise TwoElevenAdapterError(
                f"embeddings.f32 length {vectors.size} != {expected}"
            )
        vectors = vectors.reshape((count, dim))
        norms = np.linalg.norm(vectors, axis=1)
        if query_vector is not None:
            q = np.asarray(list(query_vector), dtype=np.float32)
        elif query:
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:
                raise TwoElevenAdapterError(
                    "sentence-transformers required for browser vector encode"
                ) from exc
            model_name = str(
                index.get("embeddingModel") or EXPECTED_EMBEDDING_MODEL
            )
            model = SentenceTransformer(model_name)
            q = np.asarray(
                model.encode([query], normalize_embeddings=True)[0],
                dtype=np.float32,
            )
        else:
            return {}
        if q.shape[0] != dim:
            raise TwoElevenAdapterError(
                f"query vector dim {q.shape[0]} != {dim}"
            )
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0:
            return {}
        denominator = np.maximum(norms * q_norm, 1e-12)
        scores = (vectors @ q) / denominator
        top_indexes = np.argsort(scores)[-candidate_limit:][::-1]
        doc_ids = list(index.get("doc_ids") or [])
        return {
            str(doc_ids[int(i)]): float(scores[int(i)])
            for i in top_indexes
            if int(i) < len(doc_ids)
        }


def _browser_fuse(
    *,
    mode: str,
    query: str,
    documents_by_id: Mapping[str, Mapping[str, Any]],
    keyword_scores: Mapping[str, float],
    vector_scores: Mapping[str, float],
    limit: int,
) -> list[dict[str, Any]]:
    normalized_keyword = normalize_scores(keyword_scores)
    normalized_vector = normalize_scores(vector_scores)
    candidates = set(keyword_scores) | set(vector_scores)
    results: list[dict[str, Any]] = []
    for doc_id in candidates:
        document = documents_by_id.get(doc_id) or {"doc_id": doc_id}
        keyword = float(normalized_keyword.get(doc_id, 0.0))
        vector = float(normalized_vector.get(doc_id, 0.0))
        meta = metadata_score(document, query)
        if mode == "keyword":
            score = keyword * 2 + meta
        elif mode == "vector":
            score = vector * 2 + meta * 0.5
        else:
            score = keyword * 1.4 + vector * 2 + meta
        results.append(
            {
                "doc_id": doc_id,
                "score": float(score),
                "score_parts": {
                    "keyword": keyword,
                    "vector": vector,
                    "metadata": meta,
                },
                "doc_type": document.get("doc_type"),
                "title": document.get("title"),
                "provider_name": document.get("provider_name"),
                "program_name": document.get("program_name"),
                "categories": document.get("categories"),
                "city": document.get("city"),
                "state": document.get("state"),
                "source_url": document.get("source_url"),
            }
        )
    results.sort(key=lambda row: (-float(row["score"]), str(row["doc_id"])))
    return results[:limit]


# ---------------------------------------------------------------------------
# Facade adapter
# ---------------------------------------------------------------------------


class TwoElevenCorpusAdapter:
    """Read-only facade over the 211 retrieval package (+ optional browser)."""

    def __init__(
        self,
        package_root: Path | str | None = None,
        *,
        browser_root: Path | str | None = None,
    ) -> None:
        if package_root is None and browser_root is None:
            raise TwoElevenAdapterError(
                "package_root or browser_root is required"
            )
        self.package_root = (
            Path(package_root).expanduser().resolve()
            if package_root is not None
            else None
        )
        self.browser_root = (
            Path(browser_root).expanduser().resolve()
            if browser_root is not None
            else None
        )
        self._package_reader: TwoElevenPackageReader | None = None
        self._browser_reader: TwoElevenBrowserReader | None = None

    @classmethod
    def discover(cls, *, require_package: bool = True) -> "TwoElevenCorpusAdapter":
        package = discover_package_root()
        browser = discover_browser_root()
        if package is None and require_package:
            raise TwoElevenAdapterError(
                "no 211 retrieval package discovered; set "
                f"{ENV_PACKAGE_ROOT} or install 211-AI data/retrieval_package"
            )
        if package is None and browser is None:
            raise TwoElevenAdapterError("no 211 package or browser export found")
        return cls(package, browser_root=browser)

    @property
    def package(self) -> TwoElevenPackageReader:
        if self.package_root is None:
            raise TwoElevenAdapterError("adapter has no package_root")
        if self._package_reader is None:
            self._package_reader = TwoElevenPackageReader(self.package_root)
        return self._package_reader

    @property
    def browser(self) -> TwoElevenBrowserReader:
        if self.browser_root is None:
            raise TwoElevenAdapterError("adapter has no browser_root")
        if self._browser_reader is None:
            self._browser_reader = TwoElevenBrowserReader(self.browser_root)
        return self._browser_reader

    def validate(
        self,
        *,
        verify_checksums: bool = True,
        expected_full_corpus: bool = False,
        validate_browser: bool = True,
        require_browser_shards: bool = False,
        max_rows_to_scan: int | None = 0,
    ) -> dict[str, Any]:
        package_receipt: dict[str, Any] | None = None
        artifact_receipt: dict[str, Any] | None = None
        if self.package_root is not None:
            package_receipt = validate_manifest(
                self.package_root,
                expected_full_corpus=expected_full_corpus,
            )
            artifact_receipt = validate_package_artifacts(
                self.package_root,
                manifest_receipt=package_receipt,
                verify_checksums=verify_checksums,
                expected_full_corpus=expected_full_corpus,
                max_rows_to_scan=max_rows_to_scan,
            )
            # Adjacency is derived from edges; confirm readability when full.
            if expected_full_corpus:
                stats = self.package.adjacency_stats()
                if int(stats["outgoing_edges"]) != EXPECTED_FULL_COUNTS[
                    "graph_edges"
                ]:
                    raise TwoElevenAdapterError(
                        "adjacency edge count differs from expected graph_edges"
                    )

        browser_receipt: dict[str, Any] | None = None
        if validate_browser and self.browser_root is not None:
            browser_receipt = validate_browser_export(
                self.browser_root,
                package_receipt=package_receipt,
                require_shards=require_browser_shards,
            )

        return {
            "schema": "two-eleven-corpus-validation-receipt/v1",
            "package_root": (
                str(self.package_root) if self.package_root else None
            ),
            "browser_root": (
                str(self.browser_root) if self.browser_root else None
            ),
            "package": package_receipt,
            "artifacts": artifact_receipt,
            "browser": browser_receipt,
            "expected_full_corpus": expected_full_corpus,
            "stale_source_paths": list(
                (package_receipt or {}).get("stale_source_paths") or []
            )
            + list((browser_receipt or {}).get("stale_source_paths") or []),
            "count_drift": {
                "package": (package_receipt or {}).get("count_drift") or {},
                "browser": (browser_receipt or {}).get("count_drift") or {},
            },
        }

    def entity(self, **kwargs: Any) -> dict[str, Any]:
        return self.package.entity(**kwargs)

    def neighborhood(self, node_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.package.neighborhood(node_id, **kwargs)

    def community(self, **kwargs: Any) -> dict[str, Any]:
        return self.package.community(**kwargs)

    def geography(self, **kwargs: Any) -> dict[str, Any]:
        return self.package.geography(**kwargs)

    def hybrid(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self.package.hybrid(query, **kwargs)

    def keyword(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self.package.keyword(query, **kwargs)

    def vector(self, query: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.package.vector(query, **kwargs)

    def differential_parity(
        self,
        *,
        keyword_query: str = "food pantry",
        entity_label: str = "Portland",
        city: str = "Portland",
        state: str = "OR",
        skip_vector: bool = True,
    ) -> dict[str, Any]:
        return differential_query_parity(
            package_root=self.package_root,
            browser_root=self.browser_root,
            keyword_query=keyword_query,
            entity_label=entity_label,
            city=city,
            state=state,
            skip_vector=skip_vector,
        )


# ---------------------------------------------------------------------------
# Differential parity
# ---------------------------------------------------------------------------


def differential_query_parity(
    *,
    package_root: Path | str | None,
    browser_root: Path | str | None = None,
    keyword_query: str = "food pantry",
    entity_label: str = "Portland",
    city: str = "Portland",
    state: str = "OR",
    skip_vector: bool = True,
) -> dict[str, Any]:
    """Compare adapter results to the current exporter/benchmark readers."""

    receipt: dict[str, Any] = {
        "schema": "two-eleven-differential-parity/v1",
        "legacy_exporter_available": False,
        "legacy_benchmark_available": False,
        "parity": "self_only",
        "checks": {},
    }

    if package_root is None and browser_root is None:
        raise TwoElevenAdapterError(
            "differential parity requires package_root or browser_root"
        )

    adapter = TwoElevenCorpusAdapter(
        package_root, browser_root=browser_root
    )

    # --- self checks on package ---
    if package_root is not None:
        entity = adapter.entity(label=entity_label, limit=5)
        geo = adapter.geography(city=city, state=state, limit=5)
        keyword = adapter.keyword(keyword_query, top_k=5)
        hybrid = adapter.hybrid(
            keyword_query, top_k=5, skip_vector=skip_vector
        )
        communities = adapter.community(limit=3, include_documents=False)
        receipt["checks"]["entity"] = {
            "result_count": entity["result_count"],
            "found": entity["found"],
        }
        receipt["checks"]["geography"] = {
            "result_count": geo["result_count"],
            "location_node_count": geo["location_node_count"],
            "found": geo["found"],
        }
        receipt["checks"]["keyword"] = {
            "result_count": keyword["result_count"],
            "top_doc_ids": [row["doc_id"] for row in keyword["results"]],
        }
        receipt["checks"]["hybrid"] = {
            "result_count": hybrid["result_count"],
            "top_doc_ids": [row["doc_id"] for row in hybrid["results"]],
        }
        receipt["checks"]["community"] = {
            "result_count": communities["result_count"],
            "total_communities": communities.get("total_communities"),
        }
        if entity["results"]:
            seed = str(entity["results"][0]["node_id"])
            neigh = adapter.neighborhood(seed, limit=8)
            receipt["checks"]["neighborhood"] = {
                "node_id": seed,
                "result_count": neigh["result_count"],
                "total_neighbor_count": neigh["total_neighbor_count"],
            }

    # --- browser keyword/hybrid self checks ---
    if browser_root is not None:
        browser_kw = adapter.browser.keyword(keyword_query, top_k=5)
        browser_hy = adapter.browser.hybrid(
            keyword_query, top_k=5, skip_vector=skip_vector
        )
        receipt["checks"]["browser_keyword"] = {
            "result_count": browser_kw["result_count"],
            "top_doc_ids": [row["doc_id"] for row in browser_kw["results"]],
        }
        receipt["checks"]["browser_hybrid"] = {
            "result_count": browser_hy["result_count"],
            "top_doc_ids": [row["doc_id"] for row in browser_hy["results"]],
        }
        # Neighborhood sample from first document.
        docs = adapter.browser.documents()
        if docs:
            sample_id = str(docs[0].get("doc_id") or "")
            nb = adapter.browser.neighborhood_for(sample_id)
            receipt["checks"]["browser_neighborhood"] = {
                "doc_id": sample_id,
                "found": nb is not None,
                "format": (nb or {}).get("format"),
                "node_count": len((nb or {}).get("nodes") or (nb or {}).get("node_ids") or []),
                "edge_count": len((nb or {}).get("edges") or (nb or {}).get("edge_ids") or []),
            }
        receipt["checks"]["browser_communities"] = {
            "count": len(adapter.browser.communities()),
        }

    # --- optional legacy benchmark parity (browser) ---
    benchmark = load_legacy_benchmark_module()
    if benchmark is not None and browser_root is not None:
        receipt["legacy_benchmark_available"] = True
        try:
            bm25_payload = adapter.browser.bm25_payload()
            documents_by_id = adapter.browser.documents_by_id()
            legacy_results = benchmark.search_keyword(
                keyword_query,
                bm25_payload=bm25_payload,
                documents_by_id=documents_by_id,
                candidate_limit=200,
                limit=5,
            )
            adapter_results = adapter.browser.keyword(
                keyword_query, top_k=5, candidate_limit=200
            )["results"]
            legacy_ids = [item.doc_id for item in legacy_results]
            adapter_ids = [row["doc_id"] for row in adapter_results]
            if legacy_ids != adapter_ids:
                raise TwoElevenAdapterError(
                    f"keyword ranking parity failure: "
                    f"legacy={legacy_ids} adapter={adapter_ids}"
                )
            for left, right in zip(legacy_results, adapter_results):
                if abs(float(left.score) - float(right["score"])) > 1e-6:
                    raise TwoElevenAdapterError(
                        "keyword score parity failure"
                    )
            receipt["checks"]["legacy_keyword_parity"] = {
                "matched": True,
                "top_doc_ids": adapter_ids,
            }
            receipt["parity"] = "matched"
            receipt["legacy_benchmark_path"] = str(LEGACY_EXPORTER_CANDIDATES[1])
        except TwoElevenAdapterError:
            raise
        except Exception as exc:
            receipt["checks"]["legacy_keyword_parity"] = {
                "matched": False,
                "error": str(exc),
            }

    # --- optional legacy exporter structural parity (package subset) ---
    exporter = load_legacy_exporter_module()
    if exporter is not None and package_root is not None:
        receipt["legacy_exporter_available"] = True
        try:
            package_path = Path(package_root)
            # Compare community payload shape on the full package is expensive;
            # compare counts and a document→community binding sample instead.
            communities_frame = __import__("pandas").read_parquet(
                package_path / PACKAGE_ARTIFACTS["graph_communities"]
            )
            adapter_communities = adapter.community(
                limit=5, include_documents=False
            )
            if len(communities_frame) != int(
                adapter_communities.get("total_communities") or 0
            ):
                raise TwoElevenAdapterError(
                    "community count parity failure vs exporter source parquet"
                )
            # Neighborhood rebuild for a single document from package.
            docs = list(adapter.package._ensure_documents().values())[:1]
            if docs:
                selected = {str(docs[0]["doc_id"])}
                legacy_graph = exporter.build_graph_neighborhoods(
                    package_path,
                    selected_doc_ids=selected,
                    max_edges_per_document=8,
                )
                seed = str(docs[0]["doc_id"])
                adapter_nb = adapter.neighborhood(
                    seed, direction="both", limit=8
                )
                legacy_nb = (legacy_graph.get("neighborhoods") or {}).get(seed)
                if legacy_nb is None:
                    raise TwoElevenAdapterError(
                        "legacy exporter produced no neighborhood for seed doc"
                    )
                legacy_edge_ids = set(legacy_nb.get("edge_ids") or [])
                adapter_edge_ids = {
                    row["edge"].get("edge_cid")
                    for row in adapter_nb["results"]
                    if row.get("edge")
                }
                # Adapter ranks globally; compare membership of top edges.
                if legacy_edge_ids and not (legacy_edge_ids & adapter_edge_ids):
                    raise TwoElevenAdapterError(
                        "neighborhood edge membership parity failure"
                    )
                receipt["checks"]["legacy_neighborhood_parity"] = {
                    "matched": True,
                    "doc_id": seed,
                    "legacy_edge_count": len(legacy_edge_ids),
                    "adapter_edge_count": len(adapter_edge_ids),
                    "overlap": len(legacy_edge_ids & adapter_edge_ids),
                }
            receipt["checks"]["legacy_community_parity"] = {
                "matched": True,
                "community_count": len(communities_frame),
            }
            if receipt["parity"] != "matched":
                receipt["parity"] = "matched"
            receipt["legacy_exporter_path"] = str(LEGACY_EXPORTER_CANDIDATES[0])
        except TwoElevenAdapterError:
            raise
        except Exception as exc:
            receipt["checks"]["legacy_exporter_parity"] = {
                "matched": False,
                "error": str(exc),
            }

    return receipt


# ---------------------------------------------------------------------------
# Tiny fixture builder (always-on tests)
# ---------------------------------------------------------------------------


def build_tiny_fixture_package(root: Path) -> Path:
    """Materialize a tiny 211-shaped retrieval package + browser export.

    Layout mirrors production paths so validation, adjacency, geography,
    community, and hybrid checks stay realistic without the full corpus.
    """

    pa, pq = _require_pyarrow()
    np = _require_numpy()

    root = Path(root)
    if root.exists():
        # Allow rebuild into empty or new directories only.
        if any(root.iterdir()):
            raise TwoElevenAdapterError(
                f"tiny fixture root is not empty: {root}"
            )
    root.mkdir(parents=True, exist_ok=True)

    # --- graph entities ---
    nodes = [
        {
            "node_id": "host:gethelp.211info.org",
            "node_type": "host",
            "label": "gethelp.211info.org",
            "host": "gethelp.211info.org",
            "node_cid": "bafkreinodehost000000000000000000000000000000000000001",
            "source_url": "",
            "source_content_cid": "",
            "source_page_cid": "",
            "provider_name": "",
            "program_name": "",
            "categories": "",
            "city": "",
            "state": "",
            "category": "",
            "term": "",
            "term_corpus_df": None,
            "term_global_score": None,
        },
        {
            "node_id": "page:doc-food-1",
            "node_type": "page",
            "label": "Food Pantry Directory - Portland",
            "host": "gethelp.211info.org",
            "node_cid": "bafkreinodepage000000000000000000000000000000000000001",
            "source_url": "https://gethelp.211info.org/food",
            "source_content_cid": "bafkreicontent000000000000000000000000000000000000001",
            "source_page_cid": "bafkreicontent000000000000000000000000000000000000001",
            "provider_name": "",
            "program_name": "",
            "categories": "food",
            "city": "Portland",
            "state": "OR",
            "category": "",
            "term": "",
            "term_corpus_df": None,
            "term_global_score": None,
        },
        {
            "node_id": "service:svc-shelter-1",
            "node_type": "service",
            "label": "Emergency Shelter Referral",
            "host": "gethelp.211info.org",
            "node_cid": "bafkreinodeservice00000000000000000000000000000000001",
            "source_url": "https://gethelp.211info.org/shelter",
            "source_content_cid": "bafkreicontent000000000000000000000000000000000000002",
            "source_page_cid": "bafkreicontent000000000000000000000000000000000000002",
            "provider_name": "City Shelter Network",
            "program_name": "Night Shelter",
            "categories": "housing,shelter",
            "city": "Portland",
            "state": "OR",
            "category": "",
            "term": "",
            "term_corpus_df": None,
            "term_global_score": None,
        },
        {
            "node_id": "location:loc-portland-or",
            "node_type": "location",
            "label": "Portland OR",
            "host": "",
            "node_cid": "bafkreinodelocation0000000000000000000000000000000001",
            "source_url": "",
            "source_content_cid": "",
            "source_page_cid": "",
            "provider_name": "",
            "program_name": "",
            "categories": "",
            "city": "Portland",
            "state": "OR",
            "category": "",
            "term": "",
            "term_corpus_df": None,
            "term_global_score": None,
        },
        {
            "node_id": "term:food",
            "node_type": "keyterm",
            "label": "food",
            "host": "",
            "node_cid": "bafkreinodeterm00000000000000000000000000000000000001",
            "source_url": "",
            "source_content_cid": "",
            "source_page_cid": "",
            "provider_name": "",
            "program_name": "",
            "categories": "",
            "city": "",
            "state": "",
            "category": "",
            "term": "food",
            "term_corpus_df": 1,
            "term_global_score": 2.0,
        },
        {
            "node_id": "provider:city-shelter",
            "node_type": "provider",
            "label": "City Shelter Network",
            "host": "",
            "node_cid": "bafkreinodeprovider000000000000000000000000000000001",
            "source_url": "",
            "source_content_cid": "",
            "source_page_cid": "",
            "provider_name": "City Shelter Network",
            "program_name": "",
            "categories": "",
            "city": "Portland",
            "state": "OR",
            "category": "",
            "term": "",
            "term_corpus_df": None,
            "term_global_score": None,
        },
    ]

    edges = [
        {
            "source": "host:gethelp.211info.org",
            "target": "page:doc-food-1",
            "relation": "HAS_DOCUMENT",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000001",
            "bm25_score": None,
            "tf": None,
            "idf": None,
            "source_content_cid": "",
            "shared_document_count": None,
            "cooccurrence_score": None,
        },
        {
            "source": "host:gethelp.211info.org",
            "target": "service:svc-shelter-1",
            "relation": "HAS_DOCUMENT",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000002",
            "bm25_score": None,
            "tf": None,
            "idf": None,
            "source_content_cid": "",
            "shared_document_count": None,
            "cooccurrence_score": None,
        },
        {
            "source": "page:doc-food-1",
            "target": "term:food",
            "relation": "HAS_KEYTERM",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000003",
            "bm25_score": 12.5,
            "tf": 4.0,
            "idf": 1.2,
            "source_content_cid": "bafkreicontent000000000000000000000000000000000000001",
            "shared_document_count": None,
            "cooccurrence_score": None,
        },
        {
            "source": "page:doc-food-1",
            "target": "location:loc-portland-or",
            "relation": "LOCATED_IN",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000004",
            "bm25_score": None,
            "tf": None,
            "idf": None,
            "source_content_cid": "",
            "shared_document_count": None,
            "cooccurrence_score": None,
        },
        {
            "source": "service:svc-shelter-1",
            "target": "location:loc-portland-or",
            "relation": "LOCATED_IN",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000005",
            "bm25_score": None,
            "tf": None,
            "idf": None,
            "source_content_cid": "",
            "shared_document_count": None,
            "cooccurrence_score": None,
        },
        {
            "source": "provider:city-shelter",
            "target": "service:svc-shelter-1",
            "relation": "PROVIDES_SERVICE",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000006",
            "bm25_score": None,
            "tf": None,
            "idf": None,
            "source_content_cid": "",
            "shared_document_count": None,
            "cooccurrence_score": None,
        },
        {
            "source": "page:doc-food-1",
            "target": "service:svc-shelter-1",
            "relation": "LINKS_TO",
            "edge_cid": "bafkreiedge000000000000000000000000000000000000000007",
            "bm25_score": None,
            "tf": None,
            "idf": None,
            "source_content_cid": "",
            "shared_document_count": 1.0,
            "cooccurrence_score": 0.5,
        },
    ]

    community_id = "community:bafkreicomm0000000000000000000000000000000000000001"
    metrics = [
        {
            "node_id": n["node_id"],
            "node_type": n["node_type"],
            "label": n["label"],
            "source_content_cid": n.get("source_content_cid") or "",
            "community_id": community_id,
            "degree": sum(
                1
                for e in edges
                if e["source"] == n["node_id"] or e["target"] == n["node_id"]
            ),
            "weighted_degree": float(
                sum(
                    1
                    for e in edges
                    if e["source"] == n["node_id"] or e["target"] == n["node_id"]
                )
            ),
        }
        for n in nodes
    ]

    communities = [
        {
            "community_id": community_id,
            "community_cid": "bafkreicidcomm00000000000000000000000000000000000001",
            "label": "food / shelter / portland",
            "node_count": len(nodes),
            "document_count": 2,
            "page_count": 1,
            "service_count": 1,
            "keyterm_count": 1,
            "provider_count": 1,
            "category_count": 0,
            "top_terms_json": json.dumps([["food", 1], ["shelter", 1]]),
            "top_categories_json": json.dumps([["food", 1]]),
            "top_hosts_json": json.dumps([["gethelp.211info.org", 1]]),
        }
    ]

    documents = [
        {
            "doc_id": "page:doc-food-1",
            "doc_type": "page",
            "title": "Food Pantry Directory - Portland",
            "text": (
                "Find a food pantry near you in Portland Oregon. "
                "Emergency food boxes and volunteer opportunities."
            ),
            "source_url": "https://gethelp.211info.org/food",
            "source_content_cid": "bafkreicontent000000000000000000000000000000000000001",
            "source_page_cid": "bafkreicontent000000000000000000000000000000000000001",
            "provider_name": "",
            "program_name": "",
            "categories": "food",
            "host": "gethelp.211info.org",
            "city": "Portland",
            "state": "OR",
            "metadata_json": "{}",
        },
        {
            "doc_id": "service:svc-shelter-1",
            "doc_type": "service",
            "title": "Emergency Shelter Referral",
            "text": (
                "Overnight emergency shelter and housing crisis support "
                "in Portland OR for people experiencing homelessness."
            ),
            "source_url": "https://gethelp.211info.org/shelter",
            "source_content_cid": "bafkreicontent000000000000000000000000000000000000002",
            "source_page_cid": "bafkreicontent000000000000000000000000000000000000002",
            "provider_name": "City Shelter Network",
            "program_name": "Night Shelter",
            "categories": "housing,shelter",
            "host": "gethelp.211info.org",
            "city": "Portland",
            "state": "OR",
            "metadata_json": "{}",
        },
    ]

    document_communities = [
        {
            "doc_id": documents[0]["doc_id"],
            "doc_type": "page",
            "source_url": documents[0]["source_url"],
            "source_content_cid": documents[0]["source_content_cid"],
            "source_page_cid": documents[0]["source_page_cid"],
            "community_id": community_id,
            "community_label": communities[0]["label"],
        },
        {
            "doc_id": documents[1]["doc_id"],
            "doc_type": "service",
            "source_url": documents[1]["source_url"],
            "source_content_cid": documents[1]["source_content_cid"],
            "source_page_cid": documents[1]["source_page_cid"],
            "community_id": community_id,
            "community_label": communities[0]["label"],
        },
    ]

    bm25_documents = [
        {
            "doc_id": documents[0]["doc_id"],
            "doc_type": "page",
            "source_url": documents[0]["source_url"],
            "source_content_cid": documents[0]["source_content_cid"],
            "source_page_cid": documents[0]["source_page_cid"],
            "doc_length": 12,
        },
        {
            "doc_id": documents[1]["doc_id"],
            "doc_type": "service",
            "source_url": documents[1]["source_url"],
            "source_content_cid": documents[1]["source_content_cid"],
            "source_page_cid": documents[1]["source_page_cid"],
            "doc_length": 14,
        },
    ]

    avgdl = 13.0
    bm25_terms = [
        {
            "doc_id": documents[0]["doc_id"],
            "term": "food",
            "tf": 4.0,
            "df": 1,
            "idf": 1.2,
            "doc_length": 12.0,
            "avg_doc_length": avgdl,
            "document_count": 2,
        },
        {
            "doc_id": documents[0]["doc_id"],
            "term": "pantry",
            "tf": 2.0,
            "df": 1,
            "idf": 1.5,
            "doc_length": 12.0,
            "avg_doc_length": avgdl,
            "document_count": 2,
        },
        {
            "doc_id": documents[1]["doc_id"],
            "term": "shelter",
            "tf": 3.0,
            "df": 1,
            "idf": 1.4,
            "doc_length": 14.0,
            "avg_doc_length": avgdl,
            "document_count": 2,
        },
        {
            "doc_id": documents[1]["doc_id"],
            "term": "emergency",
            "tf": 2.0,
            "df": 1,
            "idf": 1.3,
            "doc_length": 14.0,
            "avg_doc_length": avgdl,
            "document_count": 2,
        },
        {
            "doc_id": documents[1]["doc_id"],
            "term": "housing",
            "tf": 1.0,
            "df": 1,
            "idf": 1.1,
            "doc_length": 14.0,
            "avg_doc_length": avgdl,
            "document_count": 2,
        },
    ]

    # Simple orthogonal-ish embeddings (dim 8 for fixture speed).
    dim = 8
    emb_food = [1.0] + [0.0] * (dim - 1)
    emb_shelter = [0.0, 1.0] + [0.0] * (dim - 2)
    embeddings = [
        {
            "doc_id": documents[0]["doc_id"],
            "doc_type": "page",
            "source_url": documents[0]["source_url"],
            "source_content_cid": documents[0]["source_content_cid"],
            "source_page_cid": documents[0]["source_page_cid"],
            "embedding_model": EXPECTED_EMBEDDING_MODEL,
            "embedding_dim": dim,
            "embedding": emb_food,
        },
        {
            "doc_id": documents[1]["doc_id"],
            "doc_type": "service",
            "source_url": documents[1]["source_url"],
            "source_content_cid": documents[1]["source_content_cid"],
            "source_page_cid": documents[1]["source_page_cid"],
            "embedding_model": EXPECTED_EMBEDDING_MODEL,
            "embedding_dim": dim,
            "embedding": emb_shelter,
        },
    ]

    def write_parquet(rel: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path, compression="zstd")
        content = path.read_bytes()
        digest = hashlib.sha256(content).digest()
        return {
            "artifact_path": rel,
            "row_count": len(rows),
            "size_bytes": len(content),
            "artifact_cid": _raw_sha256_cid(digest),
            "sha256": digest.hex(),
        }

    artifact_meta = {
        "documents": write_parquet(PACKAGE_ARTIFACTS["documents"], documents),
        "bm25_documents": write_parquet(
            PACKAGE_ARTIFACTS["bm25_documents"], bm25_documents
        ),
        "bm25_terms": write_parquet(PACKAGE_ARTIFACTS["bm25_terms"], bm25_terms),
        "vector_embeddings": write_parquet(
            PACKAGE_ARTIFACTS["vector_embeddings"], embeddings
        ),
        "knowledge_graph_nodes": write_parquet(
            PACKAGE_ARTIFACTS["knowledge_graph_nodes"], nodes
        ),
        "knowledge_graph_edges": write_parquet(
            PACKAGE_ARTIFACTS["knowledge_graph_edges"], edges
        ),
        "graph_node_metrics": write_parquet(
            PACKAGE_ARTIFACTS["graph_node_metrics"], metrics
        ),
        "graph_communities": write_parquet(
            PACKAGE_ARTIFACTS["graph_communities"], communities
        ),
        "document_communities": write_parquet(
            PACKAGE_ARTIFACTS["document_communities"], document_communities
        ),
    }

    # Inventory parquet.
    inventory_rows = [
        {
            "artifact_name": name,
            "artifact_kind": "parquet",
            "path": f"data/retrieval_package/{meta['artifact_path']}",
            "row_count": meta["row_count"],
            "file_cid": meta["artifact_cid"],
            "size_bytes": meta["size_bytes"],
        }
        for name, meta in artifact_meta.items()
    ]
    inv_path = root / INVENTORY_REL
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(inventory_rows), inv_path, compression="zstd")

    artifacts_list = [
        {
            "artifact_name": name,
            "artifact_kind": "parquet",
            "artifact_path": meta["artifact_path"],
            "artifact_cid": meta["artifact_cid"],
            "row_count": meta["row_count"],
            "size_bytes": meta["size_bytes"],
        }
        for name, meta in artifact_meta.items()
    ]

    build_manifest: dict[str, Any] = {
        "warehouse_path": EXPECTED_WAREHOUSE_PATH,
        "document_count": len(documents),
        "page_document_count": 1,
        "service_document_count": 1,
        "bm25_term_count": len(bm25_terms),
        "embedding_count": len(embeddings),
        "embedding_model": EXPECTED_EMBEDDING_MODEL,
        "pdf_extraction_enabled": True,
        "graph_node_count": len(nodes),
        "graph_edge_count": len(edges),
        "graph_community_count": len(communities),
        "document_community_count": len(document_communities),
        "artifacts": artifacts_list,
    }
    # CID of object without the self-referential field.
    build_manifest["build_manifest_cid"] = _raw_sha256_cid(
        hashlib.sha256(
            json.dumps(build_manifest, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).digest()
    )
    manifest_path = root / MANIFEST_REL
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(build_manifest, indent=2) + "\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        "# Tiny 211 Retrieval Package Fixture\n", encoding="utf-8"
    )

    # --- browser export (monolithic + sharded) ---
    browser_root = root / "browser_export"
    generated = browser_root / "generated"
    generated.mkdir(parents=True, exist_ok=True)

    browser_docs = [
        {
            "doc_id": d["doc_id"],
            "doc_type": d["doc_type"],
            "title": d["title"],
            "text": d["text"],
            "text_truncated": False,
            "source_url": d["source_url"],
            "source_content_cid": d["source_content_cid"],
            "source_page_cid": d["source_page_cid"],
            "provider_name": d["provider_name"],
            "program_name": d["program_name"],
            "categories": d["categories"],
            "host": d["host"],
            "city": d["city"],
            "state": d["state"],
        }
        for d in documents
    ]
    _write_json(generated / "documents.json", browser_docs)
    _write_json(
        generated / "document-index.json",
        {
            "schemaVersion": 1,
            "count": len(browser_docs),
            "docIdToIndex": {
                d["doc_id"]: i for i, d in enumerate(browser_docs)
            },
            "contentCidToIndex": {
                d["source_content_cid"]: i for i, d in enumerate(browser_docs)
            },
        },
    )

    bm25_browser_docs = []
    for row in bm25_documents:
        doc_id = row["doc_id"]
        term_map = {
            t["term"]: t["tf"] for t in bm25_terms if t["doc_id"] == doc_id
        }
        idf_map = {
            t["term"]: t["idf"] for t in bm25_terms if t["doc_id"] == doc_id
        }
        bm25_browser_docs.append(
            {
                "doc_id": doc_id,
                "doc_type": row["doc_type"],
                "source_url": row["source_url"],
                "source_content_cid": row["source_content_cid"],
                "source_page_cid": row["source_page_cid"],
                "document_length": row["doc_length"],
                "terms": term_map,
                "term_idf": idf_map,
            }
        )
    _write_json(
        generated / "bm25-documents.json",
        {
            "schemaVersion": 1,
            "documents": bm25_browser_docs,
            "documentFrequency": {
                "food": 1,
                "pantry": 1,
                "shelter": 1,
                "emergency": 1,
                "housing": 1,
            },
            "k1": BM25_K1,
            "b": BM25_B,
            "avgdl": avgdl,
            "documentCount": 2,
            "maxTermsPerDocument": 48,
        },
    )

    # embeddings.f32
    matrix = np.asarray([emb_food, emb_shelter], dtype="<f4")
    (generated / "embeddings.f32").write_bytes(matrix.tobytes())
    _write_json(
        generated / "embedding-index.json",
        {
            "schemaVersion": 1,
            "count": 2,
            "dimension": dim,
            "embeddingModel": EXPECTED_EMBEDDING_MODEL,
            "browserEmbeddingModel": "Xenova/bge-small-en-v1.5",
            "binary": "embeddings.f32",
            "doc_ids": [d["doc_id"] for d in documents],
            "source_content_cids": [d["source_content_cid"] for d in documents],
            "source_page_cids": [d["source_page_cid"] for d in documents],
            "source_urls": [d["source_url"] for d in documents],
        },
    )

    # Monolithic neighborhoods (legacy embedded form).
    neighborhoods_embedded = {
        "page:doc-food-1": {
            "nodes": [
                nodes[1],
                nodes[4],
                nodes[3],
            ],
            "edges": [edges[2], edges[3], edges[6]],
        },
        "service:svc-shelter-1": {
            "nodes": [nodes[2], nodes[3], nodes[5]],
            "edges": [edges[4], edges[5]],
        },
    }
    _write_json(
        generated / "graph-neighborhoods.json",
        {
            "schemaVersion": 1,
            "maxEdgesPerDocument": 8,
            "neighborhoods": neighborhoods_embedded,
        },
    )

    # Sharded form (exporter style) under graph-neighborhoods/
    shard_dir = generated / "graph-neighborhoods"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_nodes = {n["node_id"]: {
        "node_id": n["node_id"],
        "node_type": n["node_type"],
        "label": n["label"],
        "node_cid": n["node_cid"],
        "source_url": n.get("source_url") or "",
        "source_content_cid": n.get("source_content_cid") or "",
        "city": n.get("city") or "",
        "state": n.get("state") or "",
        "term": n.get("term") or "",
    } for n in nodes}
    shard_edges = {e["edge_cid"]: e for e in edges}
    shard_neighborhoods = {
        "page:doc-food-1": {
            "node_ids": ["page:doc-food-1", "term:food", "location:loc-portland-or", "service:svc-shelter-1"],
            "edge_ids": [
                edges[2]["edge_cid"],
                edges[3]["edge_cid"],
                edges[6]["edge_cid"],
            ],
        },
        "service:svc-shelter-1": {
            "node_ids": [
                "service:svc-shelter-1",
                "location:loc-portland-or",
                "provider:city-shelter",
            ],
            "edge_ids": [edges[4]["edge_cid"], edges[5]["edge_cid"]],
        },
    }
    shard_payload = {
        "schemaVersion": 1,
        "shardId": "shard-0000",
        "maxEdgesPerDocument": 8,
        "doc_ids": list(shard_neighborhoods.keys()),
        "nodes": shard_nodes,
        "edges": shard_edges,
        "neighborhoods": shard_neighborhoods,
    }
    shard_path = shard_dir / "shard-0000.json"
    _write_json(shard_path, shard_payload)
    shard_bytes = shard_path.stat().st_size
    shard_cid = _file_cid(shard_path)
    _write_json(
        generated / "graph-neighborhood-index.json",
        {
            "schemaVersion": 1,
            "maxEdgesPerDocument": 8,
            "neighborhoodCount": 2,
            "shardSize": 10,
            "shardCount": 1,
            "shards": [
                {
                    "id": "shard-0000",
                    "path": "generated/graph-neighborhoods/shard-0000.json",
                    "bytes": shard_bytes,
                    "cid": shard_cid,
                    "documentCount": 2,
                    "nodeCount": len(shard_nodes),
                    "edgeCount": len(shard_edges),
                    "firstDocId": "page:doc-food-1",
                    "lastDocId": "service:svc-shelter-1",
                }
            ],
            "docIdToShard": {
                "page:doc-food-1": "generated/graph-neighborhoods/shard-0000.json",
                "service:svc-shelter-1": "generated/graph-neighborhoods/shard-0000.json",
            },
        },
    )

    _write_json(
        generated / "graph-communities.json",
        {
            "schemaVersion": 1,
            "communities": [
                {
                    "community_id": community_id,
                    "community_cid": communities[0]["community_cid"],
                    "label": communities[0]["label"],
                    "node_count": communities[0]["node_count"],
                    "document_count": communities[0]["document_count"],
                    "page_count": 1,
                    "service_count": 1,
                    "keyterm_count": 1,
                    "provider_count": 1,
                    "category_count": 0,
                    "top_terms": [["food", 1], ["shelter", 1]],
                    "top_categories": [["food", 1]],
                    "top_hosts": [["gethelp.211info.org", 1]],
                }
            ],
        },
    )
    _write_json(
        generated / "document-communities.json",
        {"schemaVersion": 1, "documents": document_communities},
    )

    source_package = {
        "path": str(root.resolve()),
        "build_manifest_cid": build_manifest["build_manifest_cid"],
        "document_count": len(documents),
        "graph_node_count": len(nodes),
        "graph_edge_count": len(edges),
    }
    _write_json(
        generated / "generated-manifest.json",
        {
            "schemaVersion": 1,
            "documentCount": 2,
            "embeddingCount": 2,
            "embeddingDimension": dim,
            "embeddingModel": EXPECTED_EMBEDDING_MODEL,
            "bm25DocumentCount": 2,
            "graphNeighborhoodCount": 2,
            "graphNeighborhoodShardCount": 1,
            "graphCommunityCount": 1,
            "documentCommunityCount": 2,
            "sourcePackage": source_package,
            "files": [],
        },
    )
    _write_json(
        browser_root / "artifacts.manifest.json",
        {
            "schemaVersion": 1,
            "datasetId": "endomorphosis/211-info",
            "datasetPath": "browser/211-info/fixture",
            "corpus": {
                "name": "211info retrieval package fixture",
                "documentCount": 2,
                "embeddingModel": EXPECTED_EMBEDDING_MODEL,
                "embeddingDimension": dim,
            },
            "sourcePackage": source_package,
            "artifacts": [],
        },
    )

    return root


def open_package_reader(package_root: Path | str) -> TwoElevenPackageReader:
    return TwoElevenPackageReader(package_root)


def open_browser_reader(browser_root: Path | str) -> TwoElevenBrowserReader:
    return TwoElevenBrowserReader(browser_root)


__all__ = [
    "BM25_B",
    "BM25_K1",
    "DEFAULT_211_AI_ROOT",
    "ENV_211_AI_ROOT",
    "ENV_BROWSER_ROOT",
    "ENV_PACKAGE_ROOT",
    "EXPECTED_BROWSER_SMOKE_COUNTS",
    "EXPECTED_EMBEDDING_DIM",
    "EXPECTED_EMBEDDING_MODEL",
    "EXPECTED_FULL_COUNTS",
    "PACKAGE_ARTIFACTS",
    "TwoElevenAdapterError",
    "TwoElevenBrowserReader",
    "TwoElevenCorpusAdapter",
    "TwoElevenPackageReader",
    "build_tiny_fixture_package",
    "differential_query_parity",
    "discover_211_ai_root",
    "discover_browser_root",
    "discover_browser_smoke_roots",
    "discover_package_root",
    "load_legacy_benchmark_module",
    "load_legacy_exporter_module",
    "metadata_score",
    "normalize_scores",
    "open_browser_reader",
    "open_package_reader",
    "read_build_manifest",
    "score_bm25_document",
    "tokenize",
    "validate_browser_export",
    "validate_manifest",
    "validate_package_artifacts",
]
