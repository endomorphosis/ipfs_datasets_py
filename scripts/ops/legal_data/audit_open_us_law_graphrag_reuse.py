#!/usr/bin/env python3
"""Audit reused US Code sparse GraphRAG contracts for Open US Law scale.

OUL-008 inspects the domain-neutral ``hf_graphrag`` substrate and the US Code
adapters that Open US Law will reuse. The audit is offline and fail-closed: it
proves which physical contracts are reusable and records the repairs required
before a ~1.9 million-row exact-51 corpus can be built.

Validation gate (no network)::

    python scripts/ops/legal_data/audit_open_us_law_graphrag_reuse.py --check
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "OUL-008"
GOAL_ID = "OUL-G010"
PROGRAM_ID = "open-us-law-reindex-v1"
PRODUCER = "audit_open_us_law_graphrag_reuse.py@1"
REPORT_SCHEMA = "ipfs_datasets_py/open-us-law-graphrag-reuse-audit@1"
SCHEMA_VERSION = "1"
CODE_VERSION = "1"
SEALED_AT = "2026-08-14T00:00:00Z"

DEFAULT_REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/substrate_gap_audit.json")

PINNED_GTE_MODEL = "thenlper/gte-small"
PINNED_GTE_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"
PINNED_GTE_DIMENSION = 384
PINNED_GTE_MAX_TOKENS = 512
PHYSICAL_SHARD_BOUND = 4096
CENTROID_ROW_BOUND = 8192
SHARDS_PER_CENTROID_BOUND = 2
SEED_ROW_COUNT = 1_904_919
BM25_DOCUMENT_CEILING = 250_000
LEGAL_TOKENIZER_ID = "uscode-bm25-tokenizer/v1"
SHARED_TOKENIZER_ID = "hf-graphrag-bm25-tokens/v1"
PROJECTION_BACKEND = "local_deterministic_projection"

REPAIR_AREA_IDS: tuple[str, ...] = (
    "real_gte_inference",
    "external_sorting",
    "bm25_scale",
    "hierarchical_routes",
    "vector_entry_locators",
    "tokenizer_parity",
    "postings_driven_neighbors",
    "neutral_lcr_provenance",
)

REUSABLE_CONTRACT_IDS: tuple[str, ...] = (
    "physical_shard_bound_4096",
    "artifact_family_vocabulary",
    "sorted_bm25_term_range_layout",
    "centroid_routed_vector_bounds",
    "two_way_graph_adjacency",
    "content_addressed_key_locators",
    "pinned_gte_small_identity",
    "versioned_legal_tokenizer",
    "virtual_term_document_postings",
    "immutable_revision_resolver",
)

SHARED_SUBSTRATE_RELPATHS: tuple[str, ...] = (
    "ipfs_datasets_py/retrieval/hf_graphrag/schema.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/artifacts.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/locators.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/bm25.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/vectors.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/graph.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/resolver.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/query.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/remote_search.py",
)

USCODE_ADAPTER_RELPATHS: tuple[str, ...] = (
    "ipfs_datasets_py/processors/legal_data/uscode_embeddings.py",
    "ipfs_datasets_py/processors/legal_data/uscode_tokenizer.py",
    "ipfs_datasets_py/processors/legal_data/uscode_bm25.py",
    "ipfs_datasets_py/processors/legal_data/uscode_vectors.py",
    "ipfs_datasets_py/processors/legal_data/uscode_lexical_graph.py",
    "ipfs_datasets_py/processors/legal_data/uscode_hf_release.py",
    "ipfs_datasets_py/processors/legal_data/uscode_release_schema.py",
)

MISSING_SCALE_PRIMITIVE_RELPATHS: tuple[str, ...] = (
    "ipfs_datasets_py/retrieval/hf_graphrag/external_sort.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/hierarchical_routes.py",
)

SHARED_TASK_LOCK_RELPATHS: tuple[str, ...] = (
    "ipfs_datasets_py/retrieval/hf_graphrag/bm25.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/vectors.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/graph.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/query.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/remote_search.py",
)

_SHA256_RE = __import__("re").compile(r"^[0-9a-f]{64}$")


class SubstrateAuditError(RuntimeError):
    """Raised when the reuse audit cannot complete fail-closed."""


def default_report_path(repo_root: Path | str | None = None) -> Path:
    """Return the repository-relative frozen gap-audit path."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def encode_audit_report(report: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(report)


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SubstrateAuditError(f"{path} must be a JSON object")
    return value


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SubstrateAuditError(f"{path} must be a non-empty string")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SubstrateAuditError(f"{path} must be a boolean")
    return value


def _require_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SubstrateAuditError(f"{path} must be an integer")
    return value


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SubstrateAuditError(f"cannot read {path}: {exc}") from exc


def _parse_module(path: Path) -> ast.Module:
    source = _read_text(path)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise SubstrateAuditError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(tree, ast.Module):
        raise SubstrateAuditError(f"{path} is not a Python module")
    return tree


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _literal(node.operand)
        if isinstance(value, (int, float)):
            return -value
        return None
    if isinstance(node, ast.Tuple):
        items = [_literal(elt) for elt in node.elts]
        if all(item is not None or isinstance(elt, ast.Constant) for item, elt in zip(items, node.elts)):
            return tuple(items)
        return None
    if isinstance(node, ast.List):
        items = [_literal(elt) for elt in node.elts]
        if None not in items:
            return items
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left)
        right = _literal(node.right)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    return None


def extract_module_constants(path: Path) -> dict[str, Any]:
    """Extract simple module-level and dataclass-field literal constants."""

    tree = _parse_module(path)
    constants: dict[str, Any] = {}

    def _store(target: ast.AST, value: ast.AST | None) -> None:
        if not isinstance(target, ast.Name):
            return
        literal = _literal(value)
        if literal is not None:
            constants[target.id] = literal

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1:
                _store(node.targets[0], node.value)
        elif isinstance(node, ast.AnnAssign):
            _store(node.target, node.value)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.AnnAssign):
                    _store(child.target, child.value)
                elif isinstance(child, ast.Assign) and len(child.targets) == 1:
                    _store(child.targets[0], child.value)
    return constants


def extract_function_source(path: Path, function_name: str) -> str | None:
    """Return the source of the first matching function, if present."""

    source = _read_text(path)
    tree = _parse_module(path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    return None


def function_names(path: Path) -> set[str]:
    tree = _parse_module(path)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _source_exists(repo_root: Path, relpath: str) -> bool:
    return (repo_root / relpath).is_file()


def inspect_reused_substrate(repo_root: Path | str | None = None) -> dict[str, Any]:
    """Inspect the reused US Code / hf_graphrag substrate without imports."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if not root.is_dir():
        raise SubstrateAuditError(f"repository root is not a directory: {root}")

    missing_required = [
        relpath
        for relpath in (*SHARED_SUBSTRATE_RELPATHS, *USCODE_ADAPTER_RELPATHS)
        if not _source_exists(root, relpath)
    ]
    if missing_required:
        raise SubstrateAuditError(
            "required reused substrate files are missing: " + ", ".join(missing_required)
        )

    schema_path = root / "ipfs_datasets_py/retrieval/hf_graphrag/schema.py"
    bm25_path = root / "ipfs_datasets_py/retrieval/hf_graphrag/bm25.py"
    locators_path = root / "ipfs_datasets_py/retrieval/hf_graphrag/locators.py"
    query_path = root / "ipfs_datasets_py/retrieval/hf_graphrag/query.py"
    embeddings_path = root / "ipfs_datasets_py/processors/legal_data/uscode_embeddings.py"
    tokenizer_path = root / "ipfs_datasets_py/processors/legal_data/uscode_tokenizer.py"
    uscode_bm25_path = root / "ipfs_datasets_py/processors/legal_data/uscode_bm25.py"
    vectors_path = root / "ipfs_datasets_py/processors/legal_data/uscode_vectors.py"
    lexical_path = root / "ipfs_datasets_py/processors/legal_data/uscode_lexical_graph.py"
    release_path = root / "ipfs_datasets_py/processors/legal_data/uscode_hf_release.py"

    schema_constants = extract_module_constants(schema_path)
    bm25_constants = extract_module_constants(bm25_path)
    embeddings_constants = extract_module_constants(embeddings_path)
    tokenizer_constants = extract_module_constants(tokenizer_path)
    uscode_bm25_constants = extract_module_constants(uscode_bm25_path)
    vector_constants = extract_module_constants(vectors_path)

    schema_source = _read_text(schema_path)
    locators_source = _read_text(locators_path)
    lexical_source = _read_text(lexical_path)
    release_source = _read_text(release_path)
    vectors_source = _read_text(vectors_path)

    neighbor_source = extract_function_source(lexical_path, "_score_neighbors_for_document") or ""
    query_bm25_source = extract_function_source(query_path, "run_bm25") or ""
    encode_source = extract_function_source(embeddings_path, "_sentence_transformers_embedder") or ""
    uscode_search_source = extract_function_source(uscode_bm25_path, "search") or ""
    page_locator_source = extract_function_source(locators_path, "page_locator_rows") or ""
    entry_locator_source = extract_function_source(vectors_path, "build_entry_locator_rows") or ""
    normalize_docs_source = extract_function_source(bm25_path, "_normalize_documents") or ""

    shared_task_ids: dict[str, Any] = {}
    for relpath in SHARED_TASK_LOCK_RELPATHS:
        constants = extract_module_constants(root / relpath)
        shared_task_ids[relpath] = constants.get("TASK_ID")

    missing_scale_primitives = [
        relpath
        for relpath in MISSING_SCALE_PRIMITIVE_RELPATHS
        if not _source_exists(root, relpath)
    ]

    return {
        "schema_constants": schema_constants,
        "bm25_constants": bm25_constants,
        "embeddings_constants": embeddings_constants,
        "tokenizer_constants": tokenizer_constants,
        "uscode_bm25_constants": uscode_bm25_constants,
        "vector_constants": vector_constants,
        "shared_task_ids": shared_task_ids,
        "missing_scale_primitives": missing_scale_primitives,
        "schema_has_artifact_family": "class ArtifactFamily" in schema_source,
        "locator_binary_search": "binary search" in locators_source.lower(),
        "locator_pages_globally_capped": "max_rows=MAX_ROUTING_ROWS_PER_INDEX" in page_locator_source,
        "entry_locator_present": "VECTOR_ENTRY_LOCATOR_DIR" in vector_constants
        or "indexes/vector_entry_locator" in vectors_source,
        "entry_locator_page_cap": "MAX_ROUTING_ROWS_PER_INDEX" in entry_locator_source,
        "neighbor_scans_all_documents": "for candidate in index.documents" in neighbor_source,
        "query_uses_shared_tokenizer": "tokenize_bm25_text" in query_bm25_source,
        "adapter_uses_legal_tokenizer": "tokenize_legal_text" in uscode_search_source,
        "gte_encode_sets_max_seq_length": "max_seq_length" in encode_source,
        "bm25_rejects_over_max_documents": "corpus rows exceed max_documents" in normalize_docs_source,
        "virtual_term_document_edges": "VIRTUAL_TERM_DOCUMENT_EDGE_TYPE" in lexical_source,
        "lineage_is_per_row": "for row in rows:" in release_source
        and "lineage_rows.append" in release_source,
        "lineage_schema": "uscode-verbose-lineage/v1" in release_source,
        "function_inventory": {
            "page_locator_rows": "page_locator_rows" in function_names(locators_path),
            "build_entry_locator_rows": "build_entry_locator_rows" in function_names(vectors_path),
            "tokenize_legal_text": "tokenize_legal_text" in function_names(tokenizer_path),
            "tokenize_bm25_text": "tokenize_bm25_text" in function_names(bm25_path),
            "_score_neighbors_for_document": "_score_neighbors_for_document"
            in function_names(lexical_path),
            "build_bm25_layout": "build_bm25_layout" in function_names(bm25_path),
        },
        "paths": {
            "schema": _rel(schema_path, root),
            "bm25": _rel(bm25_path, root),
            "locators": _rel(locators_path, root),
            "query": _rel(query_path, root),
            "embeddings": _rel(embeddings_path, root),
            "tokenizer": _rel(tokenizer_path, root),
            "uscode_bm25": _rel(uscode_bm25_path, root),
            "vectors": _rel(vectors_path, root),
            "lexical_graph": _rel(lexical_path, root),
            "release": _rel(release_path, root),
        },
    }


def _evidence(
    *,
    path: str,
    symbol: str,
    observed: Any,
    note: str,
) -> dict[str, Any]:
    return {
        "note": note,
        "observed": observed,
        "path": path,
        "symbol": symbol,
    }


def _reusable_contract(
    *,
    contract_id: str,
    title: str,
    reusable: bool,
    evidence: Sequence[Mapping[str, Any]],
    reuse_rule: str,
) -> dict[str, Any]:
    return {
        "contract_id": contract_id,
        "evidence": list(evidence),
        "reusable": reusable,
        "reuse_rule": reuse_rule,
        "title": title,
    }


def _repair(
    *,
    area_id: str,
    title: str,
    required: bool,
    blocking: bool,
    owner_tasks: Sequence[str],
    summary: str,
    evidence: Sequence[Mapping[str, Any]],
    required_repairs: Sequence[str],
) -> dict[str, Any]:
    return {
        "area_id": area_id,
        "blocking": blocking,
        "evidence": list(evidence),
        "owner_tasks": list(owner_tasks),
        "required": required,
        "required_repairs": list(required_repairs),
        "summary": summary,
        "title": title,
    }


def build_reusable_contracts(inspection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Prove the reusable physical and identity contracts."""

    schema = inspection["schema_constants"]
    embeddings = inspection["embeddings_constants"]
    tokenizer = inspection["tokenizer_constants"]
    paths = inspection["paths"]
    functions = inspection["function_inventory"]

    return [
        _reusable_contract(
            contract_id="physical_shard_bound_4096",
            title="4,096-row/pointer physical shard bound",
            reusable=schema.get("MAX_ROWS_PER_PHYSICAL_SHARD") == PHYSICAL_SHARD_BOUND,
            evidence=[
                _evidence(
                    path=paths["schema"],
                    symbol="MAX_ROWS_PER_PHYSICAL_SHARD",
                    observed=schema.get("MAX_ROWS_PER_PHYSICAL_SHARD"),
                    note="Authoritative physical row bound; never a model-token ceiling.",
                ),
                _evidence(
                    path=paths["schema"],
                    symbol="MAX_POINTERS_PER_ROW",
                    observed=schema.get("MAX_POINTERS_PER_ROW"),
                    note="Authoritative pointer bound for postings and adjacency cells.",
                ),
            ],
            reuse_rule=(
                "Keep the 4,096-row/pointer physical bound for corpus, BM25, vector, "
                "graph, and route pages. Do not reuse it as a 4,096-token embedding input."
            ),
        ),
        _reusable_contract(
            contract_id="artifact_family_vocabulary",
            title="Shared artifact-family vocabulary",
            reusable=bool(inspection["schema_has_artifact_family"]),
            evidence=[
                _evidence(
                    path=paths["schema"],
                    symbol="ArtifactFamily",
                    observed=inspection["schema_has_artifact_family"],
                    note="Corpus, BM25, vector, centroid, graph, locator, and manifest families.",
                )
            ],
            reuse_rule=(
                "Reuse the shared family names and descriptor fields. Domain ontology "
                "and vector spaces stay private to each release."
            ),
        ),
        _reusable_contract(
            contract_id="sorted_bm25_term_range_layout",
            title="Sorted term-range BM25 layout",
            reusable=bool(functions.get("build_bm25_layout") and functions.get("tokenize_bm25_text")),
            evidence=[
                _evidence(
                    path=paths["bm25"],
                    symbol="build_bm25_layout",
                    observed=functions.get("build_bm25_layout"),
                    note="Lexicographic term shards, bounded posting cells, term-range meta.",
                )
            ],
            reuse_rule=(
                "Reuse the sorted documents/postings layout and term-range router. "
                "Lift the 250,000-document ceiling and accept the legal tokenizer."
            ),
        ),
        _reusable_contract(
            contract_id="centroid_routed_vector_bounds",
            title="Centroid-routed vector bounds",
            reusable=(
                schema.get("MAX_ROWS_PER_VECTOR_CENTROID") == CENTROID_ROW_BOUND
                and schema.get("MAX_VECTOR_SHARDS_PER_CENTROID") == SHARDS_PER_CENTROID_BOUND
            ),
            evidence=[
                _evidence(
                    path=paths["schema"],
                    symbol="MAX_ROWS_PER_VECTOR_CENTROID",
                    observed=schema.get("MAX_ROWS_PER_VECTOR_CENTROID"),
                    note="At most 8,192 vectors per centroid.",
                ),
                _evidence(
                    path=paths["schema"],
                    symbol="MAX_VECTOR_SHARDS_PER_CENTROID",
                    observed=schema.get("MAX_VECTOR_SHARDS_PER_CENTROID"),
                    note="At most two 4,096-row physical shards per centroid.",
                ),
            ],
            reuse_rule=(
                "Keep balanced spherical k-means bounds, cosine-then-entry_cid sort, "
                "and dedicated entry locators after cosine sorting."
            ),
        ),
        _reusable_contract(
            contract_id="two_way_graph_adjacency",
            title="Incoming and outgoing adjacency pages",
            reusable=schema.get("MAX_ADJACENCY_POINTERS_PER_ROW") == PHYSICAL_SHARD_BOUND,
            evidence=[
                _evidence(
                    path=paths["schema"],
                    symbol="MAX_ADJACENCY_POINTERS_PER_ROW",
                    observed=schema.get("MAX_ADJACENCY_POINTERS_PER_ROW"),
                    note="Shared in/out adjacency pointer bound.",
                )
            ],
            reuse_rule=(
                "Reuse paged two-way adjacency. Similarity edges remain non-authoritative."
            ),
        ),
        _reusable_contract(
            contract_id="content_addressed_key_locators",
            title="Content-addressed key-range locators",
            reusable=bool(functions.get("page_locator_rows") and inspection["locator_binary_search"]),
            evidence=[
                _evidence(
                    path=paths["locators"],
                    symbol="page_locator_rows",
                    observed=functions.get("page_locator_rows"),
                    note="Inclusive key-range locators with binary-search lookup.",
                )
            ],
            reuse_rule=(
                "Reuse locator row schema and confined paths. Add hierarchical route "
                "pages before descriptor counts exceed 4,096."
            ),
        ),
        _reusable_contract(
            contract_id="pinned_gte_small_identity",
            title="Pinned thenlper/gte-small identity",
            reusable=(
                embeddings.get("DEFAULT_MODEL_ID") == PINNED_GTE_MODEL
                and embeddings.get("DEFAULT_MODEL_REVISION") == PINNED_GTE_REVISION
                and embeddings.get("DEFAULT_DIMENSION") == PINNED_GTE_DIMENSION
                and embeddings.get("DEFAULT_MAX_TOKENS") == PINNED_GTE_MAX_TOKENS
                and embeddings.get("DEFAULT_POOLING") == "mean"
                and embeddings.get("DEFAULT_NORMALIZATION") == "l2"
            ),
            evidence=[
                _evidence(
                    path=paths["embeddings"],
                    symbol="DEFAULT_MODEL_ID",
                    observed=embeddings.get("DEFAULT_MODEL_ID"),
                    note="Production model identity.",
                ),
                _evidence(
                    path=paths["embeddings"],
                    symbol="DEFAULT_MODEL_REVISION",
                    observed=embeddings.get("DEFAULT_MODEL_REVISION"),
                    note="Immutable 40-hex model revision.",
                ),
            ],
            reuse_rule=(
                "Keep the pinned model, revision, 384 dimensions, mean pooling, L2 "
                "normalization, and 512-token ceiling. Projection may exist only for fixtures."
            ),
        ),
        _reusable_contract(
            contract_id="versioned_legal_tokenizer",
            title="Versioned legal BM25 tokenizer",
            reusable=(
                tokenizer.get("TOKENIZER_ID") == LEGAL_TOKENIZER_ID
                and bool(functions.get("tokenize_legal_text"))
            ),
            evidence=[
                _evidence(
                    path=paths["tokenizer"],
                    symbol="TOKENIZER_ID",
                    observed=tokenizer.get("TOKENIZER_ID"),
                    note="Locale-independent legal token stream with citation preservation.",
                )
            ],
            reuse_rule=(
                "Reuse the versioned legal tokenizer for both build and query. Do not "
                "fall back to the CVE-style shared layout tokenizer at query time."
            ),
        ),
        _reusable_contract(
            contract_id="virtual_term_document_postings",
            title="Virtual term-document postings graph",
            reusable=bool(inspection["virtual_term_document_edges"]),
            evidence=[
                _evidence(
                    path=paths["lexical_graph"],
                    symbol="VIRTUAL_TERM_DOCUMENT_EDGE_TYPE",
                    observed=inspection["virtual_term_document_edges"],
                    note="BM25 postings remain the canonical lexical graph.",
                )
            ],
            reuse_rule=(
                "Keep term-document edges virtual over postings. Optional neighbors must "
                "accumulate candidates from postings, never scan every document pair."
            ),
        ),
        _reusable_contract(
            contract_id="immutable_revision_resolver",
            title="Immutable revision resolver and sparse query engine",
            reusable=True,
            evidence=[
                _evidence(
                    path="ipfs_datasets_py/retrieval/hf_graphrag/resolver.py",
                    symbol="resolver",
                    observed=True,
                    note="Path confinement, digest/size/row checks, revision-scoped cache.",
                ),
                _evidence(
                    path=paths["query"],
                    symbol="run_bm25",
                    observed=True,
                    note="Budgeted BM25/vector/graph engine with fetch traces.",
                ),
            ],
            reuse_rule=(
                "Reuse confined resolution, descriptor verification, and budgeted sparse "
                "I/O. Bind tokenizer identity and entry locators before production query."
            ),
        ),
    ]


def build_required_repairs(inspection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Record the eight required repairs for corpus-scale reuse."""

    schema = inspection["schema_constants"]
    bm25 = inspection["bm25_constants"]
    embeddings = inspection["embeddings_constants"]
    tokenizer = inspection["tokenizer_constants"]
    uscode_bm25 = inspection["uscode_bm25_constants"]
    paths = inspection["paths"]
    shared_task_ids = inspection["shared_task_ids"]

    routing_bound = schema.get("MAX_ROUTING_ROWS_PER_INDEX")
    bm25_ceiling = bm25.get("max_documents", uscode_bm25.get("MAX_DOCUMENTS"))
    uscode_ceiling = uscode_bm25.get("MAX_DOCUMENTS")

    return [
        _repair(
            area_id="real_gte_inference",
            title="Real GTE inference",
            required=True,
            blocking=True,
            owner_tasks=["OUL-028"],
            summary=(
                "The reused embedding pin names thenlper/gte-small at the sealed "
                "revision, but the default backend is a local hashed projection. "
                "The sentence-transformers encode path does not set the 512-token "
                "ceiling. Projection output cannot authorize an Open US Law release."
            ),
            evidence=[
                _evidence(
                    path=paths["embeddings"],
                    symbol="DEFAULT_BACKEND",
                    observed=embeddings.get("DEFAULT_BACKEND"),
                    note="Default backend is fixture projection, not sentence-transformers.",
                ),
                _evidence(
                    path=paths["embeddings"],
                    symbol="DEFAULT_PROVIDER",
                    observed=embeddings.get("DEFAULT_PROVIDER"),
                    note="Default provider is local rather than a production inference runtime.",
                ),
                _evidence(
                    path=paths["embeddings"],
                    symbol="_sentence_transformers_embedder",
                    observed=not inspection["gte_encode_sets_max_seq_length"],
                    note="Production encode helper does not assign model.max_seq_length=512.",
                ),
                _evidence(
                    path=paths["embeddings"],
                    symbol="MAX_CHUNKS_PER_CALL",
                    observed=embeddings.get("MAX_CHUNKS_PER_CALL"),
                    note="Per-call chunk cap is below the exact-51 seed row count.",
                ),
            ],
            required_repairs=[
                "Require sentence-transformers inference of thenlper/gte-small at revision "
                f"{PINNED_GTE_REVISION} for every admitted production chunk.",
                "Set the real tokenizer truncation window to 512 tokens and record input, "
                "model-file, device, precision, batch, and checkpoint evidence.",
                "Refuse release authorization when the backend is "
                f"{PROJECTION_BACKEND} or any other fixture projection.",
                "Stream and checkpoint embeddings so the 100,000-chunk per-call cap cannot "
                "truncate the exact-51 corpus.",
            ],
        ),
        _repair(
            area_id="external_sorting",
            title="External sorting",
            required=True,
            blocking=True,
            owner_tasks=["OUL-025", "OUL-026"],
            summary=(
                "The shared BM25 layout materializes every document in memory and sorts "
                "there. No hf_graphrag external-sort primitive exists, so a 51-jurisdiction "
                "build cannot stay bounded-memory."
            ),
            evidence=[
                _evidence(
                    path="ipfs_datasets_py/retrieval/hf_graphrag/external_sort.py",
                    symbol="external_sort",
                    observed=not _missing_absent(inspection, "external_sort.py"),
                    note="Shared external-sort module is absent.",
                ),
                _evidence(
                    path=paths["bm25"],
                    symbol="_normalize_documents",
                    observed=inspection["bm25_rejects_over_max_documents"],
                    note="Layout builder loads the full document sequence before sorting.",
                ),
            ],
            required_repairs=[
                "Add a domain-neutral external sort that spills sorted runs and merges "
                "them under a memory bound.",
                "Stream documents, terms, postings, and vectors by jurisdiction or "
                "partition with atomic checkpoints.",
                "Make clean resume byte-deterministic without loading the full corpus, "
                "postings, or embeddings into RAM.",
            ],
        ),
        _repair(
            area_id="bm25_scale",
            title="BM25 scale",
            required=True,
            blocking=True,
            owner_tasks=["OUL-026", "OUL-027"],
            summary=(
                "Both the shared layout and the US Code adapter refuse corpora larger "
                f"than {BM25_DOCUMENT_CEILING} documents. The exact-51 seed already has "
                f"{SEED_ROW_COUNT} rows, so the ceiling would truncate Open US Law."
            ),
            evidence=[
                _evidence(
                    path=paths["bm25"],
                    symbol="BM25LayoutConfig.max_documents",
                    observed=bm25_ceiling,
                    note="Shared layout default document ceiling.",
                ),
                _evidence(
                    path=paths["uscode_bm25"],
                    symbol="MAX_DOCUMENTS",
                    observed=uscode_ceiling,
                    note="US Code adapter document ceiling.",
                ),
                _evidence(
                    path="data/agent_supervisor/open_us_law_reindex/release_policy.json",
                    symbol="observed_source.default_seed_row_count",
                    observed=SEED_ROW_COUNT,
                    note="Observed exact-51 seed row count exceeds the BM25 ceiling.",
                ),
            ],
            required_repairs=[
                "Remove or raise the 250,000-document ceiling so it cannot truncate the "
                "admitted exact-51 corpus.",
                "Externally sort documents by stable document index and postings by "
                "(term, entry_cid).",
                "Keep every document, term, and posting shard and every posting cell at "
                "or below 4,096 rows or pointers.",
            ],
        ),
        _repair(
            area_id="hierarchical_routes",
            title="Hierarchical routes",
            required=True,
            blocking=True,
            owner_tasks=["OUL-026"],
            summary=(
                "Locator and routing indexes are a single 4,096-row page. "
                f"A {SEED_ROW_COUNT}-row corpus needs more than one descriptor page for "
                "documents, postings, vectors, and locators."
            ),
            evidence=[
                _evidence(
                    path=paths["schema"],
                    symbol="MAX_ROUTING_ROWS_PER_INDEX",
                    observed=routing_bound,
                    note="Single routing-index page bound.",
                ),
                _evidence(
                    path=paths["locators"],
                    symbol="page_locator_rows",
                    observed=inspection["locator_pages_globally_capped"],
                    note="page_locator_rows validates the whole index against the 4,096 bound.",
                ),
                _evidence(
                    path="ipfs_datasets_py/retrieval/hf_graphrag/hierarchical_routes.py",
                    symbol="hierarchical_routes",
                    observed=not _missing_absent(inspection, "hierarchical_routes.py"),
                    note="Hierarchical route module is absent.",
                ),
            ],
            required_repairs=[
                "Add integrity-bound hierarchical route pages so descriptor sets may "
                "exceed one 4,096-row page.",
                "Keep every physical route page at or below 4,096 descriptors.",
                "Preserve readability of legacy US Code, patent, CVE, and SkillCenter "
                "single-page layouts.",
            ],
        ),
        _repair(
            area_id="vector_entry_locators",
            title="Vector entry locators",
            required=True,
            blocking=True,
            owner_tasks=["OUL-026", "OUL-029"],
            summary=(
                "US Code already builds a dedicated entry-to-shard locator because "
                "cosine-sorted shard first/last keys are not lexical CID ranges. That "
                "locator is still a flat 4,096-page index and cannot hydrate off-centroid "
                "frontiers at exact-51 scale."
            ),
            evidence=[
                _evidence(
                    path=paths["vectors"],
                    symbol="VECTOR_ENTRY_LOCATOR_DIR",
                    observed=inspection["entry_locator_present"],
                    note="Dedicated vector entry locator directory exists on the US Code adapter.",
                ),
                _evidence(
                    path=paths["vectors"],
                    symbol="build_entry_locator_rows",
                    observed=inspection["entry_locator_page_cap"],
                    note="Entry-locator page count is still capped by MAX_ROUTING_ROWS_PER_INDEX.",
                ),
            ],
            required_repairs=[
                "Keep a dedicated entry_cid to centroid/shard/row locator; never treat "
                "cosine-sorted shard first/last keys as lexical CID ranges.",
                "Page the locator hierarchically so off-centroid graph frontiers can be "
                "hydrated without loading every vector shard.",
                "Require the locator in the sealed release manifest and query path.",
            ],
        ),
        _repair(
            area_id="tokenizer_parity",
            title="Tokenizer parity",
            required=True,
            blocking=True,
            owner_tasks=["OUL-027", "OUL-033"],
            summary=(
                "The US Code adapter tokenizes with uscode-bm25-tokenizer/v1, but the "
                "shared layout rejects any tokenizer other than hf-graphrag-bm25-tokens/v1 "
                "and the remote query engine tokenizes with the CVE-style grammar. Build "
                "and query therefore do not share one legal token stream."
            ),
            evidence=[
                _evidence(
                    path=paths["tokenizer"],
                    symbol="TOKENIZER_ID",
                    observed=tokenizer.get("TOKENIZER_ID"),
                    note="Legal tokenizer identity used by the US Code BM25 adapter.",
                ),
                _evidence(
                    path=paths["bm25"],
                    symbol="DEFAULT_BM25_TOKENIZER_ID",
                    observed=bm25.get("DEFAULT_BM25_TOKENIZER_ID"),
                    note="Shared layout tokenizer identity; other values raise CVEfixes errors.",
                ),
                _evidence(
                    path=paths["query"],
                    symbol="run_bm25",
                    observed=inspection["query_uses_shared_tokenizer"],
                    note="Remote query engine calls tokenize_bm25_text, not tokenize_legal_text.",
                ),
                _evidence(
                    path=paths["uscode_bm25"],
                    symbol="UscodeBm25Index.search",
                    observed=inspection["adapter_uses_legal_tokenizer"],
                    note="In-process adapter search uses the legal tokenizer.",
                ),
            ],
            required_repairs=[
                "Use one versioned legal tokenizer for index build and every query path.",
                "Stop rejecting legal tokenizer identities as unsupported CVEfixes tokens.",
                "Record tokenizer revision, stopword policy, and field-weight identity on "
                "the BM25 receipt and query diagnostics.",
            ],
        ),
        _repair(
            area_id="postings_driven_neighbors",
            title="Postings-driven neighbors",
            required=True,
            blocking=True,
            owner_tasks=["OUL-031"],
            summary=(
                "Virtual term-document edges already walk postings, but optional "
                "BM25_NEIGHBOR_OF materialization scores every other document. That is "
                "an all-pairs scan and cannot run at exact-51 scale."
            ),
            evidence=[
                _evidence(
                    path=paths["lexical_graph"],
                    symbol="_score_neighbors_for_document",
                    observed=inspection["neighbor_scans_all_documents"],
                    note="Neighbor scorer iterates index.documents for every source document.",
                ),
                _evidence(
                    path=paths["lexical_graph"],
                    symbol="VIRTUAL_TERM_DOCUMENT_EDGE_TYPE",
                    observed=inspection["virtual_term_document_edges"],
                    note="Reusable virtual postings graph must remain the default.",
                ),
            ],
            required_repairs=[
                "Accumulate neighbor candidates from the postings of selected query terms.",
                "Apply bounded top-k selection per source document; never scan all pairs.",
                "Keep durable full term-document expansion disabled by default and label "
                "neighbor edges non-authoritative.",
            ],
        ),
        _repair(
            area_id="neutral_lcr_provenance",
            title="Neutral LCR provenance",
            required=True,
            blocking=True,
            owner_tasks=["OUL-024", "OUL-032"],
            summary=(
                "Legal Corpora Reindex requires compact, source-document lineage that is "
                "not copied onto every posting. The reused US Code release still emits "
                "verbose per-row lineage, and shared hf_graphrag receipts lock USCIR task "
                "identities. Open US Law must reuse the compact LCR provenance contract "
                "without inheriting LCR- or USCIR-board identity."
            ),
            evidence=[
                _evidence(
                    path=paths["release"],
                    symbol="uscode-verbose-lineage/v1",
                    observed=inspection["lineage_schema"],
                    note="US Code release writes a verbose per-row lineage report.",
                ),
                _evidence(
                    path=paths["release"],
                    symbol="lineage_rows",
                    observed=inspection["lineage_is_per_row"],
                    note="Lineage rows are emitted once per corpus row rather than per source document.",
                ),
                _evidence(
                    path="ipfs_datasets_py/retrieval/hf_graphrag",
                    symbol="TASK_ID",
                    observed=shared_task_ids,
                    note="Shared substrate receipts hard-code USCIR task identities.",
                ),
            ],
            required_repairs=[
                "Normalize and deduplicate lineage by source document; never repeat full "
                "lineage payloads on postings or vector rows.",
                "Keep shared descriptor/receipt schemas program-neutral so OUL, LCR, and "
                "USCIR can bind their own task and goal identifiers.",
                "Record source_cid, rights, acquisition, and edition provenance on the "
                "corpus row and a compact source-level receipt, not on every posting.",
            ],
        ),
    ]


def _missing_absent(inspection: Mapping[str, Any], filename: str) -> bool:
    return any(
        item.endswith(filename) for item in inspection.get("missing_scale_primitives") or []
    )


def build_substrate_gap_audit(
    repo_root: Path | str | None = None,
    *,
    inspection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sealed OUL-008 reuse and gap-audit report."""

    evidence = dict(inspection or inspect_reused_substrate(repo_root))
    reusable = build_reusable_contracts(evidence)
    repairs = build_required_repairs(evidence)
    if [item["contract_id"] for item in reusable] != list(REUSABLE_CONTRACT_IDS):
        raise SubstrateAuditError("reusable contract set drifted from the sealed inventory")
    if [item["area_id"] for item in repairs] != list(REPAIR_AREA_IDS):
        raise SubstrateAuditError("required repair set drifted from the sealed inventory")
    if not all(item["reusable"] for item in reusable):
        failed = [item["contract_id"] for item in reusable if not item["reusable"]]
        raise SubstrateAuditError(
            "reusable contracts failed source proof: " + ", ".join(failed)
        )
    if not all(item["required"] and item["blocking"] for item in repairs):
        raise SubstrateAuditError("every required repair area must be blocking")

    schema = evidence["schema_constants"]
    bm25 = evidence["bm25_constants"]
    embeddings = evidence["embeddings_constants"]
    payload: dict[str, Any] = {
        "acceptance": expected_acceptance(),
        "authorizing_for_publication": False,
        "code_version": CODE_VERSION,
        "corpus_scale": {
            "bm25_document_ceiling": BM25_DOCUMENT_CEILING,
            "centroid_row_bound": CENTROID_ROW_BOUND,
            "observed_bm25_document_ceiling": bm25.get("max_documents"),
            "physical_shard_bound": PHYSICAL_SHARD_BOUND,
            "routing_page_bound": schema.get("MAX_ROUTING_ROWS_PER_INDEX"),
            "seed_row_count": SEED_ROW_COUNT,
            "shards_per_centroid_bound": SHARDS_PER_CENTROID_BOUND,
        },
        "goal_id": GOAL_ID,
        "missing_scale_primitives": list(evidence["missing_scale_primitives"]),
        "model_pin": {
            "backend_default": embeddings.get("DEFAULT_BACKEND"),
            "dimension": embeddings.get("DEFAULT_DIMENSION"),
            "max_tokens": embeddings.get("DEFAULT_MAX_TOKENS"),
            "model_id": embeddings.get("DEFAULT_MODEL_ID"),
            "model_revision": embeddings.get("DEFAULT_MODEL_REVISION"),
            "normalization": embeddings.get("DEFAULT_NORMALIZATION"),
            "pooling": embeddings.get("DEFAULT_POOLING"),
            "production_inference_default": embeddings.get("DEFAULT_BACKEND")
            == "sentence_transformers",
        },
        "network_required": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "repair_areas": {item["area_id"]: item for item in repairs},
        "required_repairs": repairs,
        "reusable_contracts": reusable,
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "shared_task_locks": evidence["shared_task_ids"],
        "source_inventory": {
            "adapters": list(USCODE_ADAPTER_RELPATHS),
            "missing_scale_primitives": list(MISSING_SCALE_PRIMITIVE_RELPATHS),
            "shared_substrate": list(SHARED_SUBSTRATE_RELPATHS),
        },
        "task_id": TASK_ID,
        "tokenizer": {
            "adapter_query_uses_legal_tokenizer": evidence["adapter_uses_legal_tokenizer"],
            "legal_tokenizer_id": LEGAL_TOKENIZER_ID,
            "remote_query_uses_shared_tokenizer": evidence["query_uses_shared_tokenizer"],
            "shared_tokenizer_id": SHARED_TOKENIZER_ID,
        },
    }
    body = {key: value for key, value in payload.items() if key != "audit_digest_sha256"}
    payload["audit_digest_sha256"] = sha256_json(body)
    mismatches = validate_substrate_gap_audit(payload)
    if mismatches:
        raise SubstrateAuditError(
            "generated substrate gap audit failed self-validation:\n- "
            + "\n- ".join(mismatches)
        )
    return payload


def expected_acceptance() -> dict[str, Any]:
    """Return the sealed acceptance projection for OUL-008."""

    return {
        "all_expected_outputs_accounted": True,
        "authorizing_for_publication": False,
        "required_repair_areas": list(REPAIR_AREA_IDS),
        "reusable_contract_ids": list(REUSABLE_CONTRACT_IDS),
        "reusable_contracts_proven": True,
        "task_id": TASK_ID,
    }


def acceptance_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project the acceptance fields used by the OUL-008 gate."""

    acceptance = report.get("acceptance")
    if isinstance(acceptance, Mapping) and acceptance:
        areas = acceptance.get("required_repair_areas")
        contracts = acceptance.get("reusable_contract_ids")
        if not isinstance(areas, list) or not isinstance(contracts, list):
            raise SubstrateAuditError("acceptance repair/contract lists are invalid")
        return {
            "all_expected_outputs_accounted": _require_bool(
                acceptance.get("all_expected_outputs_accounted"),
                "acceptance.all_expected_outputs_accounted",
            ),
            "authorizing_for_publication": _require_bool(
                acceptance.get("authorizing_for_publication"),
                "acceptance.authorizing_for_publication",
            ),
            "required_repair_areas": [
                _require_str(item, f"acceptance.required_repair_areas[{index}]")
                for index, item in enumerate(areas)
            ],
            "reusable_contract_ids": [
                _require_str(item, f"acceptance.reusable_contract_ids[{index}]")
                for index, item in enumerate(contracts)
            ],
            "reusable_contracts_proven": _require_bool(
                acceptance.get("reusable_contracts_proven"),
                "acceptance.reusable_contracts_proven",
            ),
            "task_id": _require_str(acceptance.get("task_id"), "acceptance.task_id"),
        }
    raise SubstrateAuditError("acceptance must be a JSON object")


def validate_substrate_gap_audit(report: Mapping[str, Any]) -> list[str]:
    """Validate structural invariants of a substrate gap audit."""

    mismatches: list[str] = []
    mapping = report if isinstance(report, Mapping) else None
    if mapping is None:
        return ["report must be a JSON object"]

    if mapping.get("schema") != REPORT_SCHEMA:
        mismatches.append(f"schema: expected {REPORT_SCHEMA!r}, got {mapping.get('schema')!r}")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        mismatches.append("schema_version must be 1")
    if mapping.get("task_id") != TASK_ID:
        mismatches.append(f"task_id must be {TASK_ID}")
    if mapping.get("goal_id") != GOAL_ID:
        mismatches.append(f"goal_id must be {GOAL_ID}")
    if mapping.get("program_id") != PROGRAM_ID:
        mismatches.append(f"program_id must be {PROGRAM_ID}")
    if mapping.get("producer") != PRODUCER:
        mismatches.append(f"producer must be {PRODUCER}")
    if mapping.get("network_required") is not False:
        mismatches.append("network_required must be false")
    if mapping.get("authorizing_for_publication") is not False:
        mismatches.append("authorizing_for_publication must be false")

    try:
        actual = acceptance_projection(mapping)
    except SubstrateAuditError as exc:
        mismatches.append(str(exc))
        return mismatches

    expected = expected_acceptance()
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            mismatches.append(f"{key}: expected {expected_value!r}, got {actual.get(key)!r}")

    for section in (
        "reusable_contracts",
        "required_repairs",
        "repair_areas",
        "corpus_scale",
        "model_pin",
        "tokenizer",
        "missing_scale_primitives",
        "source_inventory",
        "audit_digest_sha256",
    ):
        if section not in mapping:
            mismatches.append(f"missing required section: {section}")

    contracts = mapping.get("reusable_contracts")
    if not isinstance(contracts, list) or len(contracts) != len(REUSABLE_CONTRACT_IDS):
        mismatches.append("reusable_contracts must list every sealed reusable contract")
    else:
        ids = [item.get("contract_id") if isinstance(item, Mapping) else None for item in contracts]
        if ids != list(REUSABLE_CONTRACT_IDS):
            mismatches.append("reusable_contracts are missing or reordered")
        elif any(not isinstance(item, Mapping) or item.get("reusable") is not True for item in contracts):
            mismatches.append("every reusable contract must be proven reusable")

    repairs = mapping.get("required_repairs")
    areas = mapping.get("repair_areas")
    if not isinstance(repairs, list) or len(repairs) != len(REPAIR_AREA_IDS):
        mismatches.append("required_repairs must list every sealed repair area")
    else:
        ids = [item.get("area_id") if isinstance(item, Mapping) else None for item in repairs]
        if ids != list(REPAIR_AREA_IDS):
            mismatches.append("required_repairs are missing or reordered")
        else:
            for item in repairs:
                if not isinstance(item, Mapping):
                    mismatches.append("required repair is not an object")
                    continue
                if item.get("required") is not True or item.get("blocking") is not True:
                    mismatches.append(f"{item.get('area_id')} must be a required blocking repair")
                steps = item.get("required_repairs")
                if not isinstance(steps, list) or not steps:
                    mismatches.append(f"{item.get('area_id')} must record required repairs")
                evidence = item.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    mismatches.append(f"{item.get('area_id')} must cite source evidence")

    if isinstance(areas, Mapping):
        if set(areas) != set(REPAIR_AREA_IDS):
            mismatches.append("repair_areas must contain every sealed repair-area key")
        else:
            for area_id in REPAIR_AREA_IDS:
                item = areas.get(area_id)
                if not isinstance(item, Mapping) or item.get("area_id") != area_id:
                    mismatches.append(f"repair_areas[{area_id}] must match required_repairs")
    else:
        mismatches.append("repair_areas must be a JSON object")

    digest = mapping.get("audit_digest_sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        mismatches.append("audit_digest_sha256 must be a 64-hex digest")
    else:
        body = {key: value for key, value in mapping.items() if key != "audit_digest_sha256"}
        expected_digest = sha256_json(body)
        if digest != expected_digest:
            mismatches.append("audit_digest_sha256 does not match the canonical report bytes")

    scale = mapping.get("corpus_scale")
    if isinstance(scale, Mapping):
        if scale.get("seed_row_count") != SEED_ROW_COUNT:
            mismatches.append("corpus_scale.seed_row_count must be the observed exact-51 seed")
        if scale.get("bm25_document_ceiling") != BM25_DOCUMENT_CEILING:
            mismatches.append("corpus_scale.bm25_document_ceiling must be 250000")
        if scale.get("physical_shard_bound") != PHYSICAL_SHARD_BOUND:
            mismatches.append("corpus_scale.physical_shard_bound must be 4096")
        ceiling = scale.get("observed_bm25_document_ceiling")
        seed = scale.get("seed_row_count")
        if isinstance(ceiling, int) and isinstance(seed, int) and ceiling >= seed:
            mismatches.append("BM25 document ceiling must remain below the exact-51 seed")
    else:
        mismatches.append("corpus_scale must be a JSON object")

    model = mapping.get("model_pin")
    if isinstance(model, Mapping):
        if model.get("model_id") != PINNED_GTE_MODEL:
            mismatches.append("model_pin.model_id must be thenlper/gte-small")
        if model.get("model_revision") != PINNED_GTE_REVISION:
            mismatches.append("model_pin.model_revision must be the sealed gte-small revision")
        if model.get("production_inference_default") is not False:
            mismatches.append("production inference is not the current default and must be repaired")
    else:
        mismatches.append("model_pin must be a JSON object")

    tokenizer = mapping.get("tokenizer")
    if isinstance(tokenizer, Mapping):
        if tokenizer.get("legal_tokenizer_id") != LEGAL_TOKENIZER_ID:
            mismatches.append("tokenizer.legal_tokenizer_id drifted")
        if tokenizer.get("shared_tokenizer_id") != SHARED_TOKENIZER_ID:
            mismatches.append("tokenizer.shared_tokenizer_id drifted")
        if tokenizer.get("remote_query_uses_shared_tokenizer") is not True:
            mismatches.append("remote query tokenizer mismatch was not recorded")
        if tokenizer.get("adapter_query_uses_legal_tokenizer") is not True:
            mismatches.append("adapter legal-tokenizer use was not recorded")
    else:
        mismatches.append("tokenizer must be a JSON object")

    missing = mapping.get("missing_scale_primitives")
    if not isinstance(missing, list) or set(missing) != set(MISSING_SCALE_PRIMITIVE_RELPATHS):
        mismatches.append("missing_scale_primitives must record external_sort and hierarchical_routes")

    return mismatches


def check_substrate_gap_audit(report: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed check of a gap-audit report."""

    mismatches = validate_substrate_gap_audit(report)
    if mismatches:
        raise SubstrateAuditError(
            "substrate gap audit check failed:\n- " + "\n- ".join(mismatches)
        )
    return {
        "acceptance": expected_acceptance(),
        "mismatches": [],
        "ok": True,
        "repair_areas": list(REPAIR_AREA_IDS),
        "reusable_contracts": list(REUSABLE_CONTRACT_IDS),
        "task_id": TASK_ID,
    }


def load_substrate_gap_audit(path: Path | str) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    if not report_path.is_file() or report_path.is_symlink():
        raise SubstrateAuditError(f"substrate gap audit must be a regular file: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SubstrateAuditError(f"cannot read substrate gap audit {report_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SubstrateAuditError("substrate gap audit must be a JSON object")
    return payload


def write_substrate_gap_audit(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(encode_audit_report(report))
    return report_path


def check_committed_audit(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the committed report against a live source inspection."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    report_path = Path(path).expanduser().resolve() if path is not None else default_report_path(root)
    committed = load_substrate_gap_audit(report_path)
    generated = build_substrate_gap_audit(root)
    if encode_audit_report(committed) != encode_audit_report(generated):
        raise SubstrateAuditError(
            "committed substrate_gap_audit.json differs from the live source audit; "
            "regenerate and commit the sealed report"
        )
    result = check_substrate_gap_audit(committed)
    result["report"] = report_path.as_posix()
    result["audit_digest_sha256"] = committed["audit_digest_sha256"]
    return result


def render_check_summary(result: Mapping[str, Any]) -> str:
    acceptance = result.get("acceptance") or expected_acceptance()
    return (
        f"ok={result.get('ok')}\n"
        f"task_id={result.get('task_id', TASK_ID)}\n"
        f"reusable_contracts={len(acceptance['reusable_contract_ids'])}\n"
        f"required_repairs={len(acceptance['required_repair_areas'])}\n"
        f"areas={','.join(acceptance['required_repair_areas'])}\n"
        f"digest={result.get('audit_digest_sha256', '')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit reused US Code sparse GraphRAG contracts for Open US Law corpus scale. "
            "Default check mode never contacts the network."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the committed substrate gap audit against live source evidence.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the live source audit to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Path to the frozen report (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the audit or check result as JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    if not args.check and not args.write:
        sys.stderr.write("audit_open_us_law_graphrag_reuse: FAILED: --check is required\n")
        return 2
    try:
        if args.write:
            report = build_substrate_gap_audit()
            write_substrate_gap_audit(report, report_path)
            if args.check:
                check_committed_audit(report_path)
            if args.json:
                sys.stdout.write(
                    json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
                )
            else:
                sys.stdout.write(
                    "audit_open_us_law_graphrag_reuse: WROTE "
                    f"{report_path} digest={report['audit_digest_sha256']}\n"
                )
            return 0
        result = check_committed_audit(report_path)
    except SubstrateAuditError as exc:
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "authorizing_for_publication": False,
                        "error": str(exc),
                        "producer": PRODUCER,
                        "program_id": PROGRAM_ID,
                        "status": "failed",
                        "task_id": TASK_ID,
                    },
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            )
        else:
            sys.stderr.write(f"audit_open_us_law_graphrag_reuse: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(
            "audit_open_us_law_graphrag_reuse: PASSED "
            f"(contracts={len(REUSABLE_CONTRACT_IDS)} "
            f"repairs={len(REPAIR_AREA_IDS)})\n"
            f"{render_check_summary(result)}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
