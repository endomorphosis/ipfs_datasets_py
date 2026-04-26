"""Shared paths for Netherlands laws package assets."""

from __future__ import annotations

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
NETHERLANDS_LAWS_DIR = PACKAGE_DIR
DATASETS_DIR = PACKAGE_DIR / "datasets"
RAW_DATA_DIR = DATASETS_DIR / "raw"
HF_DATA_DIR = DATASETS_DIR / "huggingface"
DOCS_DIR = PACKAGE_DIR / "docs"
PACKAGE_RAW_OUTPUT_DIR = RAW_DATA_DIR / "nl_discovery_medium_100"
PACKAGE_LEGACY_RAW_OUTPUT_DIR = RAW_DATA_DIR / "nl_test_output"
PACKAGE_LEGACY_RAW_OUTPUT_DOCS_DIR = RAW_DATA_DIR / "nl_test_output_docs"

IPFS_DATASET_NAME = "ipfs_netherlands_laws"
NORMALIZED_DATASET_NAME = "netherlands-laws-nl-normalized"
VECTOR_INDEX_DATASET_NAME = "ipfs_netherlands_laws_vector_index"
BM25_INDEX_DATASET_NAME = "ipfs_netherlands_laws_bm25_index"
KNOWLEDGE_GRAPH_DATASET_NAME = "ipfs_netherlands_laws_knowledge_graph"

DEFAULT_HF_NAMESPACE = "justicedao"
DEFAULT_HF_REPO_IDS = {
    "base": f"{DEFAULT_HF_NAMESPACE}/{IPFS_DATASET_NAME}",
    "normalized": f"{DEFAULT_HF_NAMESPACE}/{NORMALIZED_DATASET_NAME}",
    "vector": f"{DEFAULT_HF_NAMESPACE}/{VECTOR_INDEX_DATASET_NAME}",
    "bm25": f"{DEFAULT_HF_NAMESPACE}/{BM25_INDEX_DATASET_NAME}",
    "knowledge-graph": f"{DEFAULT_HF_NAMESPACE}/{KNOWLEDGE_GRAPH_DATASET_NAME}",
}

REPO_ROOT = PACKAGE_DIR.parents[4]
LEGACY_HF_READY_DIR = REPO_ROOT / "hf_ready"
LEGACY_NL_OUTPUT_DIR = REPO_ROOT / "nl_test_output"
LEGACY_NL_OUTPUT_DOCS_DIR = REPO_ROOT / "nl_test_output_docs"


def hf_dataset_dir(dataset_name: str) -> Path:
    return HF_DATA_DIR / dataset_name


def repo_id_for(target: str, namespace: str = DEFAULT_HF_NAMESPACE) -> str:
    repo_name = DEFAULT_HF_REPO_IDS[target].split("/", 1)[1]
    return f"{namespace}/{repo_name}"


def ensure_package_dirs() -> None:
    for path in [DATASETS_DIR, RAW_DATA_DIR, HF_DATA_DIR, DOCS_DIR]:
        path.mkdir(parents=True, exist_ok=True)
